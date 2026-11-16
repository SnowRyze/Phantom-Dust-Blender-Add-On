"""Import an arena's visible model (Map/stNN.alr) as a reference: stage, background and sky.

Each mesh record becomes an object with its UVs and a material showing its colour texture. Shadow meshes
(shaders starting with "sshadow") are skipped. Vertex positions get their node transforms applied, then the
same game -> Blender conversion as collision, so the model lines up with the imported collision.
"""
import os
import tempfile

import bpy
import numpy as np

from ._lib import alr
from . import convert as cv

ROOT_NAMES = {0: 'Stage', 1: 'Background', 2: 'Sky'}


def _image(b, t, cache, tmpdir):
    if t['index'] in cache:
        return cache[t['index']]
    img = None
    data = alr.texture_dds(b, t)
    if data:
        path = os.path.join(tmpdir, '%03d_%s.dds' % (t['index'], t['name'] or 'tex'))
        with open(path, 'wb') as f:
            f.write(data)
        try:
            dds = bpy.data.images.load(path)
            w, h = dds.size
            px = np.empty(w * h * 4, dtype=np.float32)
            dds.pixels.foreach_get(px)
            bpy.data.images.remove(dds)
            # Keep a plain image packed as PNG: packed DDS images don't survive saving and reopening well.
            img = bpy.data.images.new(t['name'] or 'tex', w, h, alpha=True)
            img.pixels.foreach_set(px)
            img.file_format = 'PNG'
            img.pack()
        except (RuntimeError, ValueError):
            img = None
    cache[t['index']] = img
    return img


LIGHT_LAYER = 'PD_Light'     # colour attribute holding the baked lighting (exported as vertex colour)


def _material(name, img):
    """Texture x baked vertex colour, like the game's simple stage shader."""
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    light = nt.nodes.new('ShaderNodeVertexColor')
    light.layer_name = LIGHT_LAYER
    light.location = (-550, 0)
    if img is not None:
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = img
        tex.location = (-550, 300)
        mix = nt.nodes.new('ShaderNodeMix')
        mix.data_type = 'RGBA'
        mix.blend_type = 'MULTIPLY'
        mix.inputs['Factor'].default_value = 1.0
        mix.location = (-250, 200)
        nt.links.new(tex.outputs['Color'], mix.inputs['A'])
        nt.links.new(light.outputs['Color'], mix.inputs['B'])
        nt.links.new(mix.outputs['Result'], bsdf.inputs['Base Color'])
    else:
        nt.links.new(light.outputs['Color'], bsdf.inputs['Base Color'])
    return mat


def import_visuals(context, alr_path, parent, scale, roots=(0, 1, 2)):
    b = open(alr_path, 'rb').read()
    h = alr.header(b)
    texs = alr.textures(b)
    cache, report = {}, []
    vis = bpy.data.collections.new('Visuals')
    parent.children.link(vis)
    vis.pd_role = 'VISUALS'
    stage = os.path.splitext(os.path.basename(alr_path))[0]
    with tempfile.TemporaryDirectory() as tmpdir:
        for ri in roots:
            if ri >= len(h['roots']):
                continue
            meshes = alr.meshes(b, h['roots'][ri])
            if not meshes:
                continue
            coll = bpy.data.collections.new(ROOT_NAMES.get(ri, 'Model_%d' % ri))
            vis.children.link(coll)
            n_obj = n_tri = 0
            for mi, m in enumerate(meshes):
                mat_entry = m['materials'][m['material']] if m['material'] < len(m['materials']) else None
                shader = mat_entry['shader'] if mat_entry else ''
                if shader.startswith('sshadow') or m['vbuf'] >= len(m['vbufs']):
                    continue
                tris = alr.triangles_from_indices(m['indices'], m['primitive'])
                if not tris:
                    continue
                vb = m['vbufs'][m['vbuf']]
                pos, uv, _uv2 = alr.read_vertices(b, h['resource_offset'], vb)
                cols = alr.read_colours(b, h['resource_offset'], vb)
                mtx = alr.node_matrix(m['nodes'], m['node']) if m['node'] < len(m['nodes']) else alr._identity()
                used = sorted({i for t in tris for i in t})
                remap = {old: new for new, old in enumerate(used)}
                verts = [cv.to_blender(alr.apply(mtx, pos[i]), scale) for i in used]
                faces, seen_faces = [], set()
                for t in tris:
                    f = tuple(remap[i] for i in t)
                    if frozenset(f) in seen_faces:
                        # Same corners as an earlier face (a double-sided wall): Blender would merge the two,
                        # so give this one its own copies of the vertices.
                        f2 = []
                        for k in f:
                            used.append(used[k])
                            verts.append(verts[k])
                            f2.append(len(verts) - 1)
                        f = tuple(f2)
                    seen_faces.add(frozenset(f))
                    faces.append(f)
                name = '%s_%s_%02d_%s' % (stage, ROOT_NAMES.get(ri, 'm%d' % ri), mi, shader or 'mesh')
                me = bpy.data.meshes.new(name)
                me.from_pydata(verts, [], faces)
                if uv:
                    layer = me.uv_layers.new(name='UVMap')
                    for poly in me.polygons:
                        for li in poly.loop_indices:
                            u, v = uv[used[me.loops[li].vertex_index]]
                            layer.data[li].uv = (u, 1.0 - v)
                light = me.color_attributes.new(LIGHT_LAYER, 'BYTE_COLOR', 'POINT')
                for new_i, old_i in enumerate(used):
                    c = cols[old_i] if cols else (255, 255, 255, 255)
                    light.data[new_i].color_srgb = (c[0] / 255, c[1] / 255, c[2] / 255, c[3] / 255)
                me.color_attributes.active_color = light
                me.validate()
                me.update()
                tex_i = mat_entry['textures'][0] if mat_entry else None
                img = _image(b, texs[tex_i], cache, tmpdir) if tex_i is not None and tex_i < len(texs) else None
                tex_name = texs[tex_i]['name'] if img is not None else 'untextured'
                me.materials.append(_material('%s_%s_%s' % (stage, shader or 'mat', tex_name), img))
                ob = bpy.data.objects.new(name, me)
                coll.objects.link(ob)
                n_obj += 1
                n_tri += len(faces)
            report.append('%s: %d meshes, %d triangles' % (coll.name, n_obj, n_tri))
    n_img = sum(1 for v in cache.values() if v is not None)
    report.append('%d textures' % n_img)
    return '; '.join(report)
