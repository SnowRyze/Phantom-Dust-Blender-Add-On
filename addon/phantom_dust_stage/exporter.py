"""Export a Blender scene as an arena .dat.

Works on any scene: collections are found by their Phantom Dust role (Collection Properties > Phantom Dust).
The exported file starts from a base arena's .dat (the stage slot being replaced), which supplies the parts
not authored in Blender, then:

- Colliders: every mesh under a Colliders collection, modifiers applied, world space. Surface type comes from
  the nearest collection with a surface set (default 08). Written as a new collision block appended to the end
  of the file (confirmed in game). Without a Colliders collection the base arena's collision is kept.
- Spawn Points: each child collection is a layout; each spawn is an empty whose +Y axis is the facing, with
  exactly 3 child empties as orb points. The base arena fixes how many layouts there are and how many spawns
  each has (4 in most arenas). If the scene has fewer layouts they are repeated to fill. Without a Spawn Points
  collection the base arena's spawns are kept.
"""
import os

from ._lib import dat, collision_build
from . import convert as cv


class ExportError(Exception):
    pass


def collections_with_role(scene, role):
    return [c for c in scene.collection.children_recursive if getattr(c, 'pd_role', 'NONE') == role]


def base_dat_path(game_data, arena):
    return os.path.join(game_data, 'Map', arena + '.dat')


def _spawn_objects(layout_coll):
    obs = set(layout_coll.all_objects)
    return sorted((o for o in obs if o.type == 'EMPTY' and (o.parent is None or o.parent not in obs)),
                  key=lambda o: cv.natural_key(o.name))


def gather_spawns(sp_coll, scale):
    layouts = []
    children = sorted(sp_coll.children, key=lambda c: cv.natural_key(c.name))
    if not children:
        raise ExportError('%s has no layout collections; put the spawns in a child collection like LAYOUT_1'
                          % sp_coll.name)
    for lc in children:
        entries = []
        for s in _spawn_objects(lc):
            orbs = sorted(s.children, key=lambda o: cv.natural_key(o.name))
            if len(orbs) != 3:
                raise ExportError('%s has %d orb children; each spawn needs exactly 3' % (s.name, len(orbs)))
            mw = s.matrix_world
            entries.append((cv.to_game(mw.translation, scale),
                            cv.yaw_to_game(mw.to_euler('XYZ').z),
                            [cv.to_game(o.matrix_world.translation, scale) for o in orbs]))
        layouts.append((lc.name, entries))
    return layouts


def gather_collision(context, col_colls, scale):
    found = []                                    # (collection, surface type), parents first

    def walk(c, inherited):
        try:
            st = cv.surface_value(getattr(c, 'pd_surface', ''), inherited)
        except ValueError:
            raise ExportError('collection %s: surface "%s" is not a hex number like 08' % (c.name, c.pd_surface))
        if not 0 <= st <= 0xFE:
            raise ExportError('collection %s: surface must be 00-FE' % c.name)
        found.append((c, st))
        for ch in c.children:
            walk(ch, st)

    for c in col_colls:
        walk(c, cv.DEFAULT_SURFACE)

    depsgraph = context.evaluated_depsgraph_get()
    tris, seen = [], set()
    for coll, st in found:
        for ob in coll.objects:
            if ob.type != 'MESH' or ob.name in seen:
                continue
            seen.add(ob.name)
            ev = ob.evaluated_get(depsgraph)
            me = ev.to_mesh()
            try:
                me.calc_loop_triangles()
                mw = ob.matrix_world
                flip = mw.determinant() < 0
                co = [cv.to_game(mw @ v.co, scale) for v in me.vertices]
                for lt in me.loop_triangles:
                    a, b, c3 = (co[i] for i in lt.vertices)
                    tris.append((a, c3, b, st) if flip else (a, b, c3, st))
            finally:
                ev.to_mesh_clear()
    return tris


def export_models(context, base_alr_path, out_alr_path, scale, background_and_sky=False, shadows=True):
    """Write the .alr from Visuals and Objects collections.

    Returns (report string, objects, placements) for the .dat, or (None, None, None) when the scene has
    neither Visuals nor Objects (the base model file is then not needed)."""
    from . import objects_export as ox
    from . import visuals_export as vx
    scene = context.scene
    vis_cols = collections_with_role(scene, 'VISUALS')
    obj_cols = collections_with_role(scene, 'OBJECTS')
    if not vis_cols and not obj_cols:
        return None, None, None
    if not os.path.isfile(base_alr_path):
        raise ExportError('base arena model not found: %s' % base_alr_path)
    base = open(base_alr_path, 'rb').read()
    textures = vx.Textures(vx.alr.textures(base))
    report = []
    try:
        replace, vstats = vx.gather(context, vis_cols, scale, textures) if vis_cols else ({}, dict(clamped_uv=0))
        types, ostats = ox.gather(context, obj_cols, scale, textures) if obj_cols else ([], dict(clamped_uv=0))
    except (vx.VisualsError, ox.ObjectsError) as e:
        raise ExportError(str(e))
    if not background_and_sky:
        replace = {k: v for k, v in replace.items() if k == 0}
    if vis_cols and not replace:
        raise ExportError('the Visuals collection has no mesh triangles for the stage')
    add_models = [m for t in types for m in t['models'] if m is not None]
    data, built = vx.alr_build.rebuild(base, replace=replace, textures=textures.new, add_models=add_models,
                                       shadows_for=(0,) if shadows and 0 in replace else ())
    with open(out_alr_path, 'wb') as f:
        f.write(data)
    if replace:
        written = sum(len(m['tris']) for ms in replace.values() for m in ms)
        report.append('model: %d triangles' % written + (', character shadows on' if shadows and 0 in replace else ''))
    report.append('%d new textures' % len(textures.new))
    objects = placements = None
    if obj_cols:
        objects, placements = ox.add_to_files(types, add_models, built['added_roots'])
        report.append('%d object types, %d placed' % (len(objects), len(placements)))
    clamped = vstats.get('clamped_uv', 0) + ostats.get('clamped_uv', 0)
    if clamped:
        report.append('%d UVs clamped: keep each triangle within 8 texture repeats' % clamped)
    return '; '.join(report), objects, placements


def export_scene(context, base_path, out_path, scale, remove_objects=False, objects=None, placements=None):
    """Write the .dat. remove_objects = clean slate (no placed objects or effects from the base arena).
    objects/placements (from export_models) become the stage's objects."""
    if not os.path.isfile(base_path):
        raise ExportError('base arena file not found: %s (set the game data folder in the export options)' % base_path)
    if os.path.abspath(out_path) == os.path.abspath(base_path):
        raise ExportError('choose a different output file than the base arena (back it up and copy over it afterwards)')
    scene = context.scene
    b = bytearray(open(base_path, 'rb').read())
    report = []

    sp = collections_with_role(scene, 'SPAWNS')
    if len(sp) > 1:
        raise ExportError('more than one Spawn Points collection: %s' % ', '.join(c.name for c in sp))
    if sp:
        base_layouts = dat.spawn_layouts(b)
        got = gather_spawns(sp[0], scale)
        for (name, entries) in got:
            if len(entries) != len(base_layouts[0]):
                raise ExportError('%s has %d spawns; this base arena needs %d per layout'
                                  % (name, len(entries), len(base_layouts[0])))
        if len(got) > len(base_layouts):
            raise ExportError('%d layouts in the scene; this base arena has %d' % (len(got), len(base_layouts)))
        for i, layout in enumerate(base_layouts):
            _name, entries = got[i % len(got)]
            if len(entries) != len(layout):
                raise ExportError('base layout %d has %d spawns; the scene layout has %d' % (i + 1, len(layout), len(entries)))
            for s, (pos, yaw, orbs) in zip(layout, entries):
                s.pos, s.yaw, s.orbs = pos, yaw, orbs
                dat.write_spawn(b, s)
        report.append('%d layouts from the scene into %d slots' % (len(got), len(base_layouts)))
    else:
        report.append('no Spawn Points collection: kept the base spawns')

    cols = collections_with_role(scene, 'COLLIDERS')
    if cols:
        tris = gather_collision(context, cols, scale)
        if not tris:
            raise ExportError('the Colliders collection has no mesh triangles')
        block, stats = collision_build.build_block(tris)
        b = bytearray(collision_build.append_collision(bytes(b), block))
        report.append('%d collision triangles' % stats['triangles'] + (' (%d degenerate skipped)' % stats['skipped'] if stats['skipped'] else ''))
    else:
        report.append('no Colliders collection: kept the base collision')

    if remove_objects:
        n = dat.clear_placements(b)
        m = dat.clear_effects(b)
        report.append('clean slate: removed %d placed objects and %d effects of the base arena' % (n, m))
    if objects:
        from ._lib import objects_build
        b = bytearray(objects_build.add_objects(bytes(b), objects, placements))

    with open(out_path, 'wb') as f:
        f.write(b)
    return '; '.join(report)
