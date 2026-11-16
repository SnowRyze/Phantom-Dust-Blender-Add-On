"""Objects collections -> placed objects (props, breakables, jump pads).

  Objects                 role Objects
    Crate                 one child collection per object type (Collection Properties > Phantom Dust):
                          preset (how it behaves), "debris stays", surface type for its collider
      Crate, Crate.001    every mesh directly in the type collection is one placement: its location and
                          rotation about Z are used; all must share the same mesh (linked duplicates, Alt+D)
                          and have scale 1. The shared mesh, around its own origin, is the intact model.
      Broken...           optional child collection: each mesh is one piece of the broken model
      Debris...           optional child collection: the debris model
      Collider...         optional child collection: the collision shape (default: a box around the model)
  Broken, Debris and Collider meshes are modelled around the world origin (= the object's own origin).
"""
import math

from mathutils import Matrix

from ._lib import objects_build
from . import convert as cv
from .visuals_export import mesh_parts, resolve, to_meshes


class ObjectsError(Exception):
    pass


def _child(coll, prefix):
    return next((c for c in coll.children if c.name.lower().startswith(prefix)), None)


def _box(lo, hi, surface):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    c = lambda i: (x1 if i & 1 else x0, y1 if i & 2 else y0, z1 if i & 4 else z0)
    quads = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    out = []
    for q in quads:
        a, b, cc, d = (c(i) for i in q)
        out += [(a, b, cc, surface), (a, cc, d, surface)]
    # make every normal point outwards from the centre
    mid = [(lo[k] + hi[k]) / 2 for k in range(3)]
    fixed = []
    for a, b, cc, s in out:
        u = [b[k] - a[k] for k in range(3)]
        v = [cc[k] - a[k] for k in range(3)]
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        f = [(a[k] + b[k] + cc[k]) / 3 - mid[k] for k in range(3)]
        fixed.append((a, b, cc, s) if sum(n[k] * f[k] for k in range(3)) > 0 else (a, cc, b, s))
    return fixed


def _collider_tris(depsgraph, coll, scale, surface):
    tris = []
    for ob in coll.all_objects:
        if ob.type != 'MESH':
            continue
        ev = ob.evaluated_get(depsgraph)
        me = ev.to_mesh()
        try:
            me.calc_loop_triangles()
            mw = ob.matrix_world
            co = [cv.to_game(mw @ v.co, scale) for v in me.vertices]
            flip = mw.determinant() < 0
            for lt in me.loop_triangles:
                a, b, c = (co[i] for i in lt.vertices)
                tris.append((a, c, b, surface) if flip else (a, b, c, surface))
        finally:
            ev.to_mesh_clear()
    return tris


def gather(context, obj_colls, scale, textures):
    """Returns (types, stats). Each type: dict(name, models=[intact, broken, debris] (None if absent; model =
    dict(meshes, nodes)), collision, category, type, placements=[dict(pos, rot)])."""
    depsgraph = context.evaluated_depsgraph_get()
    types, stats = [], dict(clamped_uv=0)
    for oc in obj_colls:
        for tc in oc.children:
            insts = [o for o in tc.objects if o.type == 'MESH']
            if not insts:
                continue
            datas = {o.data.name for o in insts}
            if len(datas) > 1:
                raise ObjectsError('object type %s: its placements use different meshes (%s); use linked duplicates '
                                   '(Alt+D) or put each mesh in its own type collection' % (tc.name, ', '.join(sorted(datas))))
            for o in insts:
                if any(abs(s - 1.0) > 1e-4 for s in o.matrix_world.to_scale()):
                    raise ObjectsError('%s is scaled; apply the scale (Ctrl+A) so the model has the right size' % o.name)
            preset = getattr(tc, 'pd_preset', 'SOLID')
            category, typ, _desc, _states = objects_build.PRESETS[preset]
            surface = cv.surface_value(getattr(tc, 'pd_surface', ''), cv.DEFAULT_SURFACE)

            # Per-node values the game reads (see FORMATS.md): intact root value 3 = hits to break (min 1);
            # broken/debris root value 2 = damage dealt to a player the moving pieces hit; debris root value 1
            # = 2 makes the debris go away after breaking, 0 leaves it lying there.
            hits = max(1, min(255, int(getattr(tc, 'pd_hits', 1))))
            damage = max(0, min(255, int(getattr(tc, 'pd_damage', 2))))

            # intact model: the shared mesh around its own origin
            intact = resolve(to_meshes(mesh_parts(depsgraph, insts[0], Matrix.Identity(4), scale, textures, stats)))
            models = [dict(meshes=intact, nodes=[dict(flags=0x0004, values=(0, 0, hits if hits > 1 else 0, 0))]),
                      None, None]

            broken = _child(tc, 'broken')
            if broken is not None:
                pieces = [o for o in broken.all_objects if o.type == 'MESH']
                meshes = []
                for k, p in enumerate(pieces, 1):
                    meshes += resolve(to_meshes(mesh_parts(depsgraph, p, p.matrix_world, scale, textures, stats), node=k))
                if meshes:
                    models[1] = dict(meshes=meshes, nodes=[dict(flags=0x0000, values=(0, damage, 0, 0))] +
                                     [dict(flags=0x0004, parent=0, values=(3, 0, 0, 0)) for _ in pieces])
            debris = _child(tc, 'debris')
            if debris is not None:
                parts = {}
                for p in (o for o in debris.all_objects if o.type == 'MESH'):
                    mesh_parts(depsgraph, p, p.matrix_world, scale, textures, stats, parts)
                meshes = resolve(to_meshes(parts))
                if meshes:
                    stays = getattr(tc, 'pd_debris_stays', False)
                    models[2] = dict(meshes=meshes, nodes=[dict(flags=0x0004, values=(0 if stays else 2, damage, 0, 0))])

            col = _child(tc, 'collider')
            collision = _collider_tris(depsgraph, col, scale, surface) if col is not None else []
            if not collision:
                pts = [v[0] for m in intact for v in m['verts']]
                lo = tuple(min(p[k] for p in pts) for k in range(3))
                hi = tuple(max(p[k] for p in pts) for k in range(3))
                collision = _box(lo, hi, surface)

            placements = []
            for o in insts:
                mw = o.matrix_world
                e = mw.to_euler('XYZ')
                if abs(e.x) > 1e-3 or abs(e.y) > 1e-3:
                    raise ObjectsError('%s is tilted; only rotation about Z (turning) is supported for now' % o.name)
                placements.append(dict(pos=cv.to_game(mw.translation, scale), rot=(0.0, e.z, 0.0)))
            if preset == 'JUMP_PAD':
                # The game's jump pads put the jump strength in the first spare placement byte (100-250).
                power = max(1, min(255, int(getattr(tc, 'pd_jump_power', 150))))
                for p in placements:
                    p['extra'] = (power, 0)
            types.append(dict(name=tc.name, models=models, collision=collision, category=category, type=typ,
                              placements=placements, preset=preset))
    return types, stats


def add_to_files(types, alr_add_models, alr_added_roots):
    """After the .alr is built (models added in order), turn types into objects_build inputs."""
    objects, placements = [], []
    k = 0
    for t in types:
        roots = []
        for m in t['models']:
            if m is None:
                roots.append(None)
            else:
                roots.append(alr_added_roots[k])
                k += 1
        idx = len(objects)
        objects.append(dict(name=t['name'][:31], roots=tuple(roots), collision=t['collision']))
        for p in t['placements']:
            placements.append(dict(object=idx, category=t['category'], type=t['type'], pos=p['pos'], rot=p['rot'],
                                   extra=p.get('extra', (0, 0))))
    return objects, placements
