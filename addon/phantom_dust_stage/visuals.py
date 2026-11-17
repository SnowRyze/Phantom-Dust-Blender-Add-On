"""Import an arena's visible model (Map/stNN.alr) as a reference: stage, background and sky.

Each mesh record becomes an object with its UVs and a material showing its colour texture. Shadow meshes
(shaders starting with "sshadow") are skipped. Vertex positions get their node transforms applied, then the
same game -> Blender conversion as collision, so the model lines up with the imported collision.
"""
import os
import tempfile

import bpy

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
            img = bpy.data.images.load(path)
            img.name = t['name'] or os.path.basename(path)
            img.pack()                       # keep it in the .blend; the temp file is deleted afterwards
        except RuntimeError:
            img = None
    cache[t['index']] = img
    return img


def _material(name, img):
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    if img is not None:
        nt = mat.node_tree
        bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = img
        tex.location = (-350, 250)
        nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
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
                mtx = alr.node_matrix(m['nodes'], m['node']) if m['node'] < len(m['nodes']) else alr._identity()
                used = sorted({i for t in tris for i in t})
                remap = {old: new for new, old in enumerate(used)}
                verts = [cv.to_blender(alr.apply(mtx, pos[i]), scale) for i in used]
                faces = [tuple(remap[i] for i in t) for t in tris]
                name = '%s_%s_%02d_%s' % (stage, ROOT_NAMES.get(ri, 'm%d' % ri), mi, shader or 'mesh')
                me = bpy.data.meshes.new(name)
                me.from_pydata(verts, [], faces)
                if uv:
                    layer = me.uv_layers.new(name='UVMap')
                    for poly in me.polygons:
                        for li in poly.loop_indices:
                            u, v = uv[used[me.loops[li].vertex_index]]
                            layer.data[li].uv = (u, 1.0 - v)
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
