"""Write a stage .alr: replace models (roots) of a base arena's .alr with new meshes and textures.

The file is rebuilt from its parts: the 0x11 header (root offsets updated), the 0x15 texture table (new
entries appended), every root's chunk chain (replaced roots rebuilt, the rest copied unchanged), zero
padding to 0x1000, then the resource buffer: the base buffer unchanged with the new vertex and texture data
appended. Offsets into the resource buffer are relative to its start, so the base data keeps working.

New meshes use vertex format 0x01 (shader "sd"): position, packed normal, UV (/4096) and a white vertex
colour. Fields not understood are copied from an existing "sd" mesh/material/vertex buffer in the base file.
New textures are uncompressed BGRA (format 0x86) with a full mip chain.
"""
import math
import struct

from . import alr
from .collision_build import enclosing_sphere

FORMAT = 0x01
VERTEX_SIZE = 0x18
UV_DIV = 4096
MAX_VERTS = 0xFFFF
TEX_FORMAT = 0x86
ALIGN = 0x100
NAME_CHARS = '0123456789abcdefghijklmnopqrstuvwxyz'


# ---------------------------------------------------------------- small encoders

def encode_word(text):
    v = 0
    for c in (text + '\0' * 6)[:6]:
        c = c.lower()
        if c.isdigit():
            k = 1 + ord(c) - ord('0')
        elif 'a' <= c <= 'z':
            k = 11 + ord(c) - ord('a')
        elif c in ' _-':
            k = 37
        else:
            k = 0
        v = v * 40 + k
    return v


def encode_text(text):
    return encode_word(text[:6]), encode_word(text[6:12])


def pack_normal(n):
    l = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) or 1.0
    x, y, z = (c / l for c in n)
    q = lambda v, m, bits: int(round(max(-1.0, min(1.0, v)) * m)) & ((1 << bits) - 1)
    return q(x, 1023, 11) | (q(y, 1023, 11) << 11) | (q(z, 511, 10) << 22)


def _pad(data, align):
    return data + b'\0' * (-len(data) % align)


# ---------------------------------------------------------------- templates from the base file

def _templates(b):
    """Raw records of an existing format-0x01 "sd" mesh to copy unknown fields from."""
    h = alr.header(b)
    found = None
    prim5_unk = None
    for r in h['roots']:
        mats = vbs = None
        mat_hdr = None
        for off, t, size in alr.chain(b, r):
            if t == 0x01:
                mats = alr._materials(b, off)
                mat_hdr = b[off:off + 12]
            elif t == 0x16:
                vbs = (off, alr._vertex_buffers(b, off))
            elif t == 0x02 and mats and vbs:
                mat_i, _node, vb_i, prim = struct.unpack_from('<4H', b, off + 0x40)
                if prim == 5 and prim5_unk is None:
                    prim5_unk = b[off + 0x30:off + 0x40]
                if found is None and mat_i < len(mats) and vb_i < len(vbs[1]):
                    m = mats[mat_i]
                    if m['shader'] == 'sd' and m['vertex_format'] == FORMAT and vbs[1][vb_i]['format'] == FORMAT:
                        found = dict(material=bytearray(m['raw']), material_hdr=bytes(mat_hdr),
                                     vbuf=bytearray(b[vbs[0] + 0xC + vb_i * 0x1C:vbs[0] + 0xC + (vb_i + 1) * 0x1C]),
                                     mesh=bytearray(b[off:off + 0x68]), mesh_prim=prim)
    if found is None:
        raise ValueError('base .alr has no "sd" format-0x01 mesh to copy settings from')
    if prim5_unk is not None:
        found['mesh'][0x30:0x40] = prim5_unk          # fields that go with triangle-list meshes
    tex = [t for t in alr.textures(b)]
    t86 = next((t for t in tex if t['raw_format'] == TEX_FORMAT), None)
    hoff = h['header_size']
    found['texture'] = bytearray(b[hoff + 0xC + t86['index'] * 0x1C:hoff + 0xC + (t86['index'] + 1) * 0x1C]) if t86 else \
        bytearray(struct.pack('<3I4BI2I', 0x00040001, 0, 0, 0x29, TEX_FORMAT, 0, 0, 0, 0, 0))
    return found


def _empty_chain(b):
    """An existing empty root chain (no meshes), to clear a model."""
    for r in alr.header(b)['roots']:
        c = alr.chain(b, r)
        if not any(t == 0x02 for _, t, _ in c):
            return bytes(b[r:c[-1][0] + c[-1][2]])
    return (struct.pack('<IIHH', 1, 12, 0, 0x41) + struct.pack('<IIHHI', 3, 16, 0, 0, 0)
            + struct.pack('<III', 0x16, 12, 0) + struct.pack('<III', 0xD, 12, 0) + struct.pack('<II', 0, 8))


# ---------------------------------------------------------------- building a model

def texture_record(tpl, name, width, height, mips, rel_offset):
    e = bytearray(tpl)
    wp, hp = width.bit_length() - 1, height.bit_length() - 1
    struct.pack_into('<I', e, 0x04, rel_offset)
    struct.pack_into('<4B', e, 0x0C, e[0x0C], TEX_FORMAT, (wp << 4) | (mips & 0xF), hp & 0xF)
    struct.pack_into('<I', e, 0x10, 0)
    struct.pack_into('<2I', e, 0x14, *encode_text(name))
    return bytes(e)


def split_mesh(verts, tris, limit=MAX_VERTS):
    """Split (verts, tris) into parts that each use at most `limit` vertices."""
    if len(verts) <= limit:
        return [(verts, tris)]
    parts, cur, remap = [], [], {}
    for t in tris:
        new = [i for i in t if i not in remap]
        if len(remap) + len(new) > limit:
            parts.append(([verts[i] for i in sorted(remap, key=remap.get)], cur))
            cur, remap = [], {}
        for i in t:
            remap.setdefault(i, len(remap))
        cur.append(tuple(remap[i] for i in t))
    if cur:
        parts.append(([verts[i] for i in sorted(remap, key=remap.get)], cur))
    return parts


def build_model(tpl, meshes, texture_base_index, rb_base):
    """Chunk chain for one root plus its vertex data.

    meshes: list of dict(verts=[(pos, normal, uv) or (pos, normal, uv, (r, g, b, a))], tris=[(a, b, c)],
            texture=index into the new textures) or texture_index=an existing entry of the base texture table.
            The optional colour (0-255) is the baked lighting the game multiplies the texture by; white if missing.
            A mesh can instead be dict(raw=...) to carry an existing mesh over unchanged in format (see raw_mesh).
    Returns (chain bytes, vertex data bytes appended at rb_base, stats)."""
    mat_index, materials = {}, []
    parts = []
    for m in meshes:
        if 'raw' in m:
            r = m['raw']
            key = ('raw', r['material'])
            if key not in mat_index:
                mat_index[key] = len(materials)
                raw = bytearray(r['material'])
                raw[0x12] = len(materials) & 0xFF
                materials.append(bytes(raw))
            parts.append((mat_index[key], r, r['tris']))
            continue
        tex = m['texture_index'] if 'texture_index' in m else texture_base_index + m['texture']
        if tex not in mat_index:
            mat_index[tex] = len(materials)
            raw = bytearray(tpl['material'])
            raw[0x12] = len(materials) & 0xFF
            struct.pack_into('<4H', raw, 0x18, tex, 0, 0, 0)
            materials.append(bytes(raw))
        for verts, tris in split_mesh(m['verts'], m['tris']):
            parts.append((mat_index[tex], verts, tris))

    vdata = bytearray()
    vb_entries, mesh_chunks = [], []
    for i, (mi, verts, tris) in enumerate(parts):
        pad = -(rb_base + len(vdata)) % ALIGN
        vdata += b'\0' * pad
        rel = rb_base + len(vdata)
        e = bytearray(tpl['vbuf'])
        if isinstance(verts, dict):                      # carried-over mesh: its own format and vertex bytes
            r = verts
            vdata += r['vertex_bytes']
            e[0], e[1], e[2] = r['format'], r['vertex_size'], r['vertex_size']
            n_verts = len(r['vertex_bytes']) // r['vertex_size']
            pts = [struct.unpack_from('<3f', r['vertex_bytes'], k * r['vertex_size']) for k in range(n_verts)]
        else:
            for vert in verts:
                pos, nrm, uv = vert[:3]
                col = vert[3] if len(vert) > 3 and vert[3] is not None else (255, 255, 255, 255)
                u = int(round(uv[0] * UV_DIV))
                v = int(round(uv[1] * UV_DIV))
                vdata += struct.pack('<3fIhh4B', *pos, pack_normal(nrm), max(-32768, min(32767, u)),
                                     max(-32768, min(32767, v)), col[2], col[1], col[0], col[3])
            e[0], e[1], e[2] = FORMAT, VERTEX_SIZE, VERTEX_SIZE
            n_verts = len(verts)
            pts = [vert[0] for vert in verts]
        struct.pack_into('<I', e, 0x08, n_verts)
        struct.pack_into('<I', e, 0x14, rel)
        vb_entries.append(bytes(e))

        centre, _ = enclosing_sphere(pts)
        radius = max(math.dist(centre, p) for p in pts)
        idx = [i for t in tris for i in t]
        hdr = bytearray(verts['header'] if isinstance(verts, dict) else tpl['mesh'])
        struct.pack_into('<3ff', hdr, 0x08, *centre, radius)
        struct.pack_into('<3f', hdr, 0x18, *(min(p[k] for p in pts) for k in range(3)))
        struct.pack_into('<3f', hdr, 0x24, *(max(p[k] for p in pts) for k in range(3)))
        struct.pack_into('<4H', hdr, 0x40, mi, 0, i, 5)
        struct.pack_into('<3I', hdr, 0x48, min(idx), len(tris), len(idx))
        body = _pad(bytes(hdr[8:]) + struct.pack('<%dH' % len(idx), *idx), 4)
        mesh_chunks.append(struct.pack('<II', 0x02, 8 + len(body)) + body)

    chain = bytearray()
    unk = struct.unpack_from('<H', tpl['material_hdr'], 0x0A)[0]
    chain += struct.pack('<IIHH', 0x01, 12 + 0x4C * len(materials), len(materials), unk) + b''.join(materials)
    node = struct.pack('<9fHHHHI16x', 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0xFFFF, 0xFFFFFFFF)
    chain += struct.pack('<IIHHI', 0x03, 16 + len(node), 1, 0, 0) + node
    chain += struct.pack('<III', 0x16, 12 + 0x1C * len(vb_entries), len(vb_entries)) + b''.join(vb_entries)
    chain += b''.join(mesh_chunks)
    chain += struct.pack('<III', 0x0D, 12, 0) + struct.pack('<II', 0x00, 8)
    stats = dict(meshes=len(parts), materials=len(materials), triangles=sum(len(p[2]) for p in parts))
    return bytes(chain), bytes(vdata), stats


def raw_mesh(b, mesh, rb_off):
    """Carry an existing mesh (e.g. a shadow mesh) into a rebuilt model: its material record, vertex format
    and bytes, with node transforms applied to the positions (the rebuilt model has one identity node)."""
    vb = mesh['vbufs'][mesh['vbuf']]
    size = vb['vertex_size']
    start = rb_off + vb['offset']
    data = bytearray(b[start:start + vb['count'] * size])
    mtx = alr.node_matrix(mesh['nodes'], mesh['node']) if mesh['node'] < len(mesh['nodes']) else None
    if mtx:
        for k in range(vb['count']):
            p = struct.unpack_from('<3f', data, k * size)
            struct.pack_into('<3f', data, k * size, *alr.apply(mtx, p))
    tris = alr.triangles_from_indices(mesh['indices'], mesh['primitive'])
    return dict(raw=dict(material=bytes(mesh['materials'][mesh['material']]['raw']), format=vb['format'],
                         vertex_size=size, vertex_bytes=bytes(data), tris=tris,
                         header=bytes(b[mesh['offset']:mesh['offset'] + 0x68])))


# ---------------------------------------------------------------- the whole file

def rebuild(b, replace=None, textures=(), clear=()):
    """New .alr bytes.

    replace:  {root index: list of meshes} (see build_model); texture indices refer to `textures`.
    textures: list of dict(name, width, height, levels=[BGRA bytes per mip, top row first]).
    clear:    root indices to empty (e.g. remove the background).
    With no arguments the result is byte-identical to the input."""
    replace = replace or {}
    h = alr.header(b)
    hsize, rb_off, rb_size = h['header_size'], h['resource_offset'], h['resource_size']
    t15 = struct.unpack_from('<3I', b, hsize)
    tex_entries = bytes(b[hsize + 0xC:hsize + 0xC + 0x1C * t15[2]])
    rb = bytearray(b[rb_off:rb_off + rb_size])
    tpl = _templates(b) if (replace or textures) else None
    stats = {}

    # new textures appended to the resource buffer and the table
    new_entries = []
    for t in textures:
        rb += b'\0' * (-len(rb) % ALIGN)
        rel = len(rb)
        for lvl in t['levels']:
            rb += lvl
        new_entries.append(texture_record(tpl['texture'], t['name'], t['width'], t['height'], len(t['levels']), rel))
    n_tex = t15[2] + len(new_entries)
    tex_chunk = struct.pack('<III', 0x15, 0xC + 0x1C * n_tex, n_tex) + tex_entries + b''.join(new_entries)
    tex_chunk = tex_chunk + bytes(b[hsize + 0xC + 0x1C * t15[2]:hsize + t15[1]])   # keep any trailing bytes

    chains = []
    empty = _empty_chain(b) if clear else None
    for i, r in enumerate(h['roots']):
        if i in replace:
            chain, vdata, st = build_model(tpl, replace[i], t15[2], len(rb))
            rb += vdata
            stats[i] = st
            chains.append(chain)
        elif i in clear:
            chains.append(empty)
        else:
            c = alr.chain(b, r)
            chains.append(bytes(b[r:c[-1][0] + c[-1][2]]))

    # metadata layout: header, texture table, chains in the original order of their offsets
    order = sorted(range(len(h['roots'])), key=lambda i: h['roots'][i])
    meta = bytearray(b[:hsize]) + tex_chunk
    roots = [0] * len(h['roots'])
    for i in order:
        roots[i] = len(meta)
        meta += chains[i]
    end_of_meta = len(meta)
    meta += b'\0' * (-len(meta) % 0x1000)
    if b[end_of_meta:rb_off] and len(meta) == rb_off:
        meta[end_of_meta:] = b[end_of_meta:rb_off]          # identical padding when nothing moved
    struct.pack_into('<I', meta, 0x0C, len(meta))
    struct.pack_into('<I', meta, 0x14, len(rb))
    struct.pack_into('<%dI' % len(roots), meta, 0x20, *roots)
    return bytes(meta) + bytes(rb), stats
