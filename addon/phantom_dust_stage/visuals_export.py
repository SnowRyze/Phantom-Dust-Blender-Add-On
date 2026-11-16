"""Blender meshes -> model meshes for the .alr writer (stage model and object models).

Meshes under a Visuals collection replace the base arena's main stage model. A child collection named
"Background..." or "Sky..." replaces that model instead (the import creates those names).

Per triangle: position, the corner normal, the active UV map (game V = 1 - Blender V) and the baked lighting
colour from the "PD_Light" colour attribute (or the active colour attribute; white if none). The colour is
multiplied with the texture in game, so it carries light and shade.

Textures: the image in each material (the Image Texture feeding Base Color, else any Image Texture). An image
whose name matches a texture in the base arena (as the import names them) reuses that texture. Others are
added uncompressed, resized to a power of two (largest side at most 1024) with a full mip chain.
"""
import math
import re

import numpy as np
from mathutils import Matrix

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


class Textures:
    """Texture references shared by every model in one export: arena textures reused by name, others added."""

    def __init__(self, base_textures):
        self.base_by_name = {t['name']: t['index'] for t in base_textures}
        self.new = []
        self.key = {}
        self.reused = 0

    def ref(self, img):
        key = img.name if img is not None else None
        if key in self.key:
            return self.key[key]
        if img is None:
            ref = ('new', len(self.new))
            self.new.append(dict(name='pd_white', width=4, height=4, levels=[b'\xff' * 64, b'\xff' * 16, b'\xff' * 4]))
        elif game_texture_name(img.name) in self.base_by_name:
            ref = ('base', self.base_by_name[game_texture_name(img.name)])
            self.reused += 1
        else:
            w, h, levels = image_levels(img)
            ref = ('new', len(self.new))
            self.new.append(dict(name=game_texture_name(img.name), width=w, height=h, levels=levels))
        self.key[key] = ref
        return ref


def mesh_parts(depsgraph, ob, matrix, scale, textures, stats, parts=None):
    """Add one Blender mesh object's triangles to `parts` ({texture ref: part}), transformed by `matrix`
    (Blender space) then converted to game space. Returns `parts`."""
    parts = {} if parts is None else parts
    ev = ob.evaluated_get(depsgraph)
    me = ev.to_mesh()
    try:
        me.calc_loop_triangles()
        nmat = matrix.to_3x3().inverted_safe().transposed()
        flip = matrix.determinant() < 0
        uvl = me.uv_layers.active
        col = me.color_attributes.get(LIGHT_LAYER) or me.color_attributes.active_color
        cnormals = me.corner_normals
        co = [matrix @ v.co for v in me.vertices]
        slots_mat = [s.material for s in ob.material_slots]
        for lt in me.loop_triangles:
            mat = slots_mat[lt.material_index] if lt.material_index < len(slots_mat) else None
            ref = textures.ref(_image_of(mat))
            part = parts.setdefault(ref, dict(verts=[], index={}, tris=[], ref=ref))
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
                    stats['clamped_uv'] = stats.get('clamped_uv', 0) + 1
                    u, v = min(u, UV_LIMIT), min(v, UV_LIMIT)
                l = math.sqrt(sum(x * x for x in n)) or 1.0
                n = tuple(x / l for x in n)
                key = (tuple(round(x, 4) for x in pos), tuple(round(x, 3) for x in n), (round(u, 5), round(v, 5)), c)
                if key not in part['index']:
                    part['index'][key] = len(part['verts'])
                    part['verts'].append((pos, n, (u, v), c))
                tri.append(part['index'][key])
            if len(set(tri)) == 3:
                part['tris'].append((tri[0], tri[2], tri[1]) if flip else tuple(tri))
    finally:
        ev.to_mesh_clear()
    return parts


def to_meshes(parts, node=0):
    """Parts -> mesh dicts for alr_build (texture refs resolved later via 'ref')."""
    out = []
    for ref, part in parts.items():
        if part['tris']:
            out.append(dict(verts=part['verts'], tris=part['tris'], ref=ref, node=node))
    return out


def resolve(meshes):
    """Turn each mesh's texture ref into texture_index / texture for alr_build."""
    for m in meshes:
        kind, i = m.pop('ref')
        if kind == 'base':
            m['texture_index'] = i
        else:
            m['texture'] = i
    return meshes


def gather(context, vis_colls, scale, textures):
    """Visuals -> ({slot: [mesh dicts]}, stats). Each Blender object stays a separate mesh per texture."""
    slot_of = []

    def walk(c, slot):
        s = _slot_for(c.name, slot)
        slot_of.append((c, s))
        for ch in c.children:
            walk(ch, s)

    for c in vis_colls:
        walk(c, 0)

    depsgraph = context.evaluated_depsgraph_get()
    stats = dict(objects=0, clamped_uv=0)
    replace, seen = {}, set()
    for coll, slot in slot_of:
        for ob in coll.objects:
            if ob.type != 'MESH' or ob.name in seen:
                continue
            seen.add(ob.name)
            stats['objects'] += 1
            parts = mesh_parts(depsgraph, ob, ob.matrix_world, scale, textures, stats)
            replace.setdefault(slot, []).extend(resolve(to_meshes(parts)))
    stats['triangles'] = sum(len(m['tris']) for ms in replace.values() for m in ms)
    return replace, stats
