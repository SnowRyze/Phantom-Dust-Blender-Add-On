"""Turn Visuals collections into the arena's visible model (.alr).

Meshes under a Visuals collection replace the base arena's main stage model. A child collection named
"Background..." or "Sky..." replaces that model instead (the import creates those names).

Per triangle: world-space position, the corner normal, the active UV map (game V = 1 - Blender V) and the baked
lighting colour from the "PD_Light" colour attribute (or the active colour attribute; white if none). The
colour is multiplied with the texture in game, so it carries light and shade.

Textures: the image in each material (the Image Texture feeding Base Color, else any Image Texture). An image
whose name matches a texture in the base arena (as the import names them) reuses that texture. Others are
added uncompressed, resized to a power of two (largest side at most 1024) with a full mip chain.
"""
import math
import re

import numpy as np

from ._lib import alr, alr_build
from . import convert as cv

SLOTS = (('background', 1), ('sky', 2))
LIGHT_LAYER = 'PD_Light'
MAX_TEX = 1024
UV_LIMIT = 7.99                      # UVs are stored as int16 / 4096


class VisualsError(Exception):
    pass


def _slot_for(name, inherited):
    low = name.lower()
    for prefix, slot in SLOTS:
        if low.startswith(prefix):
            return slot
    return inherited


def _image_of(mat):
    if mat is None or not mat.use_nodes or mat.node_tree is None:
        return None
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is not None and bsdf.inputs['Base Color'].is_linked:
        todo, seen = [bsdf.inputs['Base Color'].links[0].from_node], set()
        while todo:
            n = todo.pop()
            if n.name in seen:
                continue
            seen.add(n.name)
            if n.type == 'TEX_IMAGE' and n.image is not None:
                return n.image
            for inp in n.inputs:
                for link in inp.links:
                    todo.append(link.from_node)
    return next((n.image for n in nt.nodes if n.type == 'TEX_IMAGE' and n.image is not None), None)


def game_texture_name(name):
    name = re.sub(r'\.\d{3}$', '', name).lower()
    name = re.sub(r'[^0-9a-z_]', '_', name)
    return name[:12] or 'tex'


def image_levels(img):
    """(width, height, [BGRA bytes per mip, top row first]) for a Blender image."""
    w, h = img.size
    if w == 0 or h == 0:
        raise VisualsError('image %s has no pixels (is the file missing?)' % img.name)
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)[::-1]                             # Blender stores bottom row first
    W = 1 << int(math.floor(math.log2(min(w, MAX_TEX))))
    H = 1 << int(math.floor(math.log2(min(h, MAX_TEX))))
    W, H = max(W, 4), max(H, 4)
    if (W, H) != (w, h):                                       # box-average into the power-of-two size
        ys = (np.arange(H + 1) * h / H).astype(int)
        xs = (np.arange(W + 1) * w / W).astype(int)
        csum = np.zeros((h + 1, w + 1, 4), dtype=np.float64)
        csum[1:, 1:] = px.cumsum(0).cumsum(1)
        area = np.maximum(1, (ys[1:] - ys[:-1])[:, None] * (xs[1:] - xs[:-1])[None, :])[..., None]
        px = (csum[ys[1:]][:, xs[1:]] - csum[ys[:-1]][:, xs[1:]] - csum[ys[1:]][:, xs[:-1]]
              + csum[ys[:-1]][:, xs[:-1]]) / area
    levels = []
    cur = px.astype(np.float32)
    while True:
        b8 = np.clip(np.round(cur * 255), 0, 255).astype(np.uint8)[..., [2, 1, 0, 3]]
        levels.append(b8.tobytes())
        hh, ww = cur.shape[:2]
        if hh == 1 and ww == 1:
            break
        cur = cur.reshape(max(1, hh // 2), 2 if hh > 1 else 1, max(1, ww // 2), 2 if ww > 1 else 1, 4).mean(axis=(1, 3))
    return W, H, levels


def gather(context, vis_colls, scale, base_textures):
    """Returns ({slot: [mesh dicts]}, [new texture specs], stats)."""
    slot_of = []

    def walk(c, slot):
        s = _slot_for(c.name, slot)
        slot_of.append((c, s))
        for ch in c.children:
            walk(ch, s)

    for c in vis_colls:
        walk(c, 0)

    base_by_name = {t['name']: t['index'] for t in base_textures}
    new_textures, tex_key = [], {}
    stats = dict(objects=0, clamped_uv=0, reused_textures=0)

    def texture_ref(img):
        key = img.name if img is not None else None
        if key in tex_key:
            return tex_key[key]
        if img is None:
            ref = ('new', len(new_textures))
            new_textures.append(dict(name='pd_white', width=4, height=4,
                                     levels=[b'\xff' * 64, b'\xff' * 16, b'\xff' * 4]))
        elif game_texture_name(img.name) in base_by_name:
            ref = ('base', base_by_name[game_texture_name(img.name)])
            stats['reused_textures'] += 1
        else:
            w, h, levels = image_levels(img)
            ref = ('new', len(new_textures))
            new_textures.append(dict(name=game_texture_name(img.name), width=w, height=h, levels=levels))
        tex_key[key] = ref
        return ref

    depsgraph = context.evaluated_depsgraph_get()
    parts = {}                                   # (slot, object, texture ref) -> part
    seen = set()
    for coll, slot in slot_of:
        for ob in coll.objects:
            if ob.type != 'MESH' or ob.name in seen:
                continue
            seen.add(ob.name)
            stats['objects'] += 1
            ev = ob.evaluated_get(depsgraph)
            me = ev.to_mesh()
            try:
                me.calc_loop_triangles()
                mw = ob.matrix_world
                nmat = mw.to_3x3().inverted_safe().transposed()
                flip = mw.determinant() < 0
                uvl = me.uv_layers.active
                col = me.color_attributes.get(LIGHT_LAYER) or me.color_attributes.active_color
                cnormals = me.corner_normals
                co = [mw @ v.co for v in me.vertices]
                slots_mat = [s.material for s in ob.material_slots]
                for lt in me.loop_triangles:
                    mat = slots_mat[lt.material_index] if lt.material_index < len(slots_mat) else None
                    ref = texture_ref(_image_of(mat))
                    part = parts.setdefault((slot, ob.name, ref), dict(verts=[], index={}, tris=[], ref=ref))
                    corners = []
                    for li, vi in zip(lt.loops, lt.vertices):
                        uv = (uvl.data[li].uv[0], 1.0 - uvl.data[li].uv[1]) if uvl else (0.0, 0.0)
                        n = nmat @ cnormals[li].vector
                        if col is None:
                            c = (255, 255, 255, 255)
                        else:
                            src = col.data[li if col.domain == 'CORNER' else vi].color_srgb
                            c = tuple(int(round(max(0.0, min(1.0, x)) * 255)) for x in src)
                        corners.append((cv.to_game(co[vi], scale), cv.to_game(n, 1.0), uv, c))
                    du = math.floor(min(c[2][0] for c in corners))
                    dv = math.floor(min(c[2][1] for c in corners))
                    tri = []
                    for pos, n, uv, c in corners:
                        u, v = uv[0] - du, uv[1] - dv
                        if u > UV_LIMIT or v > UV_LIMIT:
                            stats['clamped_uv'] += 1
                            u, v = min(u, UV_LIMIT), min(v, UV_LIMIT)
                        l = math.sqrt(sum(x * x for x in n)) or 1.0
                        n = tuple(x / l for x in n)
                        key = (tuple(round(x, 4) for x in pos), tuple(round(x, 3) for x in n),
                               (round(u, 5), round(v, 5)), c)
                        if key not in part['index']:
                            part['index'][key] = len(part['verts'])
                            part['verts'].append((pos, n, (u, v), c))
                        tri.append(part['index'][key])
                    if len(set(tri)) == 3:
                        part['tris'].append((tri[0], tri[2], tri[1]) if flip else tuple(tri))
            finally:
                ev.to_mesh_clear()

    replace = {}
    for (slot, _ob, ref), part in parts.items():
        if not part['tris']:
            continue
        m = dict(verts=part['verts'], tris=part['tris'])
        if ref[0] == 'base':
            m['texture_index'] = ref[1]
        else:
            m['texture'] = ref[1]
        replace.setdefault(slot, []).append(m)
    stats['triangles'] = sum(len(m['tris']) for ms in replace.values() for m in ms)
    stats['new_textures'] = len(new_textures)
    return replace, new_textures, stats


def export_alr(context, vis_colls, base_alr_bytes, scale):
    replace, textures, stats = gather(context, vis_colls, scale, alr.textures(base_alr_bytes))
    if not replace:
        raise VisualsError('the Visuals collection has no mesh triangles')
    data, _ = alr_build.rebuild(base_alr_bytes, replace=replace, textures=textures)
    return data, stats
