"""Helpers for building a map: a starter scene, the lighting bake, restoring the game's own arena files,
and the 3D View sidebar (N panel > Phantom Dust) that gathers every step."""
import math

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty

from . import convert as cv
from . import exporter
from . import visuals as pd_visuals
from . import visuals_export as vx

FLOOR_Z = 6.4                 # Panorama Earthquake's floor height (game 64): a safe height for any arena slot
LIGHT = vx.LIGHT_LAYER


def _prefs_game_data(context):
    try:
        return bpy.path.abspath(context.preferences.addons[__package__].preferences.game_data)
    except (KeyError, AttributeError):
        return ''


def _collection(scene, name, parent=None, role='NONE', surface=''):
    c = bpy.data.collections.new(name)
    (parent or scene.collection).children.link(c)
    c.pd_role = role
    c.pd_surface = surface
    return c


def _checker(name, size=64, cells=8):
    img = bpy.data.images.new(name, size, size, alpha=False)
    px = []
    for y in range(size):
        for x in range(size):
            on = ((x * cells // size) + (y * cells // size)) % 2
            v = 0.62 if on else 0.48
            px += (v, v, v * 1.04, 1.0)
    img.pixels = px
    img.pack()
    return img


def _stripes(name, size=64):
    img = bpy.data.images.new(name, size, size, alpha=False)
    px = []
    for y in range(size):
        for x in range(size):
            on = ((x + y) * 6 // size) % 2
            px += (0.9, 0.75, 0.1, 1.0) if on else (0.08, 0.08, 0.08, 1.0)
    img.pixels = px
    img.pack()
    return img


def _jump_pad_object(name='JumpPad', size=3.0, height=0.1):
    """A 3 x 3 m hazard-striped slab, origin at its bottom centre, standing on the floor in the middle."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x *= size
        v.co.y *= size
        v.co.z = (v.co.z + 0.5) * height
    bm.to_mesh(me)
    bm.free()
    uv = me.uv_layers.new(name='UVMap')
    for li, loop in enumerate(me.loops):
        p = me.vertices[loop.vertex_index].co
        uv.data[li].uv = (p.x / size + 0.5, p.y / size + 0.5)
    me.materials.append(pd_visuals._material('JumpPad_mat', _stripes('pd_jumppad')))
    light = me.color_attributes.new(LIGHT, 'BYTE_COLOR', 'CORNER')     # top bright, sides a little darker
    for poly in me.polygons:
        s = 1.0 if poly.normal.z > 0.5 else 0.7
        for li in poly.loop_indices:
            light.data[li].color_srgb = (s, s, s, 1.0)
    me.color_attributes.active_color = light
    ob = bpy.data.objects.new(name, me)
    ob.location = (0, 0, FLOOR_Z)
    ob.hide_render = True                    # objects stay out of the stage lighting bake
    return ob


class PDSTAGE_OT_new_arena(bpy.types.Operator):
    """Set up this scene for a new arena: tagged collections, a floor with its collider, one spawn layout
    (4 spawns with 3 orbs each), a jump pad and a sun for the lighting"""
    bl_idname = 'pdstage.new_arena'
    bl_label = 'New Arena Setup'
    bl_options = {'REGISTER', 'UNDO'}

    size: bpy.props.FloatProperty(name='Floor size (m)', default=30.0, min=4.0, max=200.0)

    def execute(self, context):
        scene = context.scene
        if any(getattr(c, 'pd_role', 'NONE') != 'NONE' for c in scene.collection.children_recursive):
            self.report({'ERROR'}, 'This scene already has Phantom Dust collections; use a new scene (or a new file)')
            return {'CANCELLED'}
        scene.pd_scale = cv.DEFAULT_SCALE
        scene.pd_imported = False
        half = self.size / 2

        vis = _collection(scene, 'Visuals', role='VISUALS')
        _collection(scene, 'Sky', vis)
        _collection(scene, 'Background', vis)
        cols = _collection(scene, 'Colliders', role='COLLIDERS', surface='08')
        sp = _collection(scene, 'Spawn_Points', role='SPAWNS')
        lay = _collection(scene, 'LAYOUT_1', sp)
        objs = _collection(scene, 'Objects', role='OBJECTS')
        _collection(scene, 'Effects', role='EFFECTS')

        # floor: a subdivided plane (more vertices = smoother baked light), with a checker so scale is visible
        def floor_mesh(name, cuts):
            me = bpy.data.meshes.new(name)
            bm = bmesh.new()
            bmesh.ops.create_grid(bm, x_segments=cuts, y_segments=cuts, size=half)
            bm.to_mesh(me)
            bm.free()
            return me

        me = floor_mesh('Floor', 24)
        uv = me.uv_layers.new(name='UVMap')
        for li, loop in enumerate(me.loops):
            p = me.vertices[loop.vertex_index].co
            uv.data[li].uv = (p.x / 4.0, p.y / 4.0)                  # one checker tile per 4 m
        me.materials.append(pd_visuals._material('Floor_mat', _checker('pd_floor')))
        light = me.color_attributes.new(LIGHT, 'BYTE_COLOR', 'POINT')
        for d in light.data:
            d.color_srgb = (1, 1, 1, 1)
        me.color_attributes.active_color = light
        floor = bpy.data.objects.new('Floor', me)
        floor.location = (0, 0, FLOOR_Z)
        vis.objects.link(floor)

        col = bpy.data.objects.new('COL_Floor', floor_mesh('COL_Floor', 1))
        col.location = (0, 0, FLOOR_Z)
        col.display_type = 'WIRE'
        col.hide_render = True                    # colliders stay out of the lighting bake
        cols.objects.link(col)

        r = min(half * 0.7, 11.0)
        for i, a in enumerate((225, 315, 45, 135), 1):
            x, y = r * math.cos(math.radians(a)), r * math.sin(math.radians(a))
            e = bpy.data.objects.new('SPAWN_%d' % i, None)
            e.empty_display_type = 'ARROWS'
            e.empty_display_size = 2.0
            e.location = (x, y, FLOOR_Z + 0.3)
            e.rotation_euler = (0, 0, math.atan2(x, -y))             # +Y (the facing) towards the middle
            lay.objects.link(e)
            for k in range(1, 4):
                o = bpy.data.objects.new('SPAWN_%d_ORB_%d' % (i, k), None)
                o.empty_display_type = 'SPHERE'
                o.empty_display_size = 0.4
                o.parent = e
                o.location = (0, 2.0 + 1.5 * k, 0.5)
                lay.objects.link(o)

        # a jump pad in the middle: an object type with the Jump Pad behaviour; duplicate it (Alt+D) for more
        pads = _collection(scene, 'JumpPad', objs)
        pads.pd_preset = 'JUMP_PAD'
        pads.pd_jump_power = 200
        pads.objects.link(_jump_pad_object())

        sun = bpy.data.objects.new('Sun', bpy.data.lights.new('Sun', 'SUN'))
        sun.data.energy = 3.0
        sun.rotation_euler = (math.radians(50), math.radians(15), math.radians(35))
        scene.collection.objects.link(sun)
        scene.pd_sun = sun
        scene.pd_light_custom = True
        if scene.world is None:
            scene.world = bpy.data.worlds.new('World')
        scene.world.use_nodes = True
        bg = scene.world.node_tree.nodes.get('Background')
        if bg is not None:
            bg.inputs['Color'].default_value = (0.55, 0.6, 0.7, 1)
            bg.inputs['Strength'].default_value = 0.6
        self.report({'INFO'}, 'Arena set up: build under Visuals, add collider shapes under Colliders, '
                              'then Bake Lighting and Export')
        return {'FINISHED'}


def stage_meshes(scene):
    """Mesh objects that make the stage model (Visuals, not its Sky/Background children)."""
    out = []

    def walk(c, slot):
        s = vx._slot_for(c.name, slot)
        if s == 0:
            out.extend(o for o in c.objects if o.type == 'MESH' and o not in out)
        for ch in c.children:
            walk(ch, s)

    for c in exporter.collections_with_role(scene, 'VISUALS'):
        walk(c, 0)
    return out


class PDSTAGE_OT_bake_light(bpy.types.Operator):
    """Bake the scene's lights (sun, world, lamps) into the PD_Light colours of the stage meshes under
    Visuals. Uses Cycles; colliders, objects, sky and background are left out of the bake"""
    bl_idname = 'pdstage.bake_light'
    bl_label = 'Bake Lighting'
    bl_options = {'REGISTER', 'UNDO'}

    samples: IntProperty(name='Samples', default=64, min=1, max=4096)
    normalise: BoolProperty(name='Brightest = white', default=True,
                            description='Scale the result so the brightest vertex is white (the game multiplies '
                                        'textures by this colour, so white = the texture as painted)')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        scene = context.scene
        targets = [o for o in stage_meshes(scene) if o.visible_get()]
        if not targets:
            self.report({'ERROR'}, 'No visible meshes under the Visuals collection')
            return {'CANCELLED'}
        if context.object is not None and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for o in targets:
            attr = o.data.color_attributes.get(LIGHT) or o.data.color_attributes.new(LIGHT, 'BYTE_COLOR', 'POINT')
            o.data.color_attributes.active_color = attr
        keep = set(targets) | {o for o in scene.objects if o.type == 'LIGHT'}
        hidden = [o for o in scene.objects if o not in keep and not o.hide_render]
        engine, samples = scene.render.engine, scene.cycles.samples
        sel = [o for o in context.view_layer.objects if o.select_get()]
        active = context.view_layer.objects.active
        try:
            for o in hidden:
                o.hide_render = True
            scene.render.engine = 'CYCLES'
            scene.cycles.samples = self.samples
            for o in context.view_layer.objects:
                o.select_set(False)
            for o in targets:
                o.select_set(True)
            context.view_layer.objects.active = targets[0]
            bpy.ops.object.bake(type='DIFFUSE', pass_filter={'DIRECT', 'INDIRECT'}, target='VERTEX_COLORS')
        except RuntimeError as e:
            self.report({'ERROR'}, 'Bake failed: %s' % e)
            return {'CANCELLED'}
        finally:
            for o in hidden:
                o.hide_render = False
            scene.render.engine = engine
            scene.cycles.samples = samples
            for o in context.view_layer.objects:
                o.select_set(o in sel)
            context.view_layer.objects.active = active
        peak = 0.0
        for o in targets:
            for c in o.data.color_attributes[LIGHT].data:
                peak = max(peak, sum(c.color_srgb[:3]) / 3)
        if self.normalise and peak > 0:
            for o in targets:
                for c in o.data.color_attributes[LIGHT].data:
                    r, g, b, _a = c.color_srgb
                    c.color_srgb = (min(1, r / peak), min(1, g / peak), min(1, b / peak), 1.0)
        self.report({'INFO'}, 'Baked lighting into %d meshes%s' % (
            len(targets), ' (scaled x%.2f)' % (1 / peak) if self.normalise and peak > 0 else ''))
        return {'FINISHED'}


ARENA_ITEMS = [(k, '%s (%s)' % (name, k), 'Restore %s' % name) for k, name in cv.ARENAS]


class PDSTAGE_OT_restore(bpy.types.Operator):
    """Put the game's own files for an arena back (from the backup made when a map was installed)"""
    bl_idname = 'pdstage.restore_arena'
    bl_label = 'Restore Original Arena'

    arena: EnumProperty(name='Arena', items=ARENA_ITEMS)

    def invoke(self, context, event):
        self.arena = context.scene.pd_base_arena
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        game_data = _prefs_game_data(context)
        if not game_data:
            self.report({'ERROR'}, 'Set the game data folder in the add-on preferences')
            return {'CANCELLED'}
        try:
            done = exporter.restore(game_data, self.arena)
        except OSError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        if not done:
            self.report({'WARNING'}, 'No backup for %s: the game\'s own files were never replaced' % self.arena)
            return {'CANCELLED'}
        self.report({'INFO'}, 'Restored %s' % ', '.join(done))
        return {'FINISHED'}


class PDSTAGE_PT_sidebar(bpy.types.Panel):
    bl_label = 'Phantom Dust Stage'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Phantom Dust'

    def draw(self, context):
        s = context.scene
        lay = self.layout
        if not _prefs_game_data(context):
            box = lay.box()
            box.label(text='Set the game data folder in', icon='ERROR')
            box.label(text='Preferences > Add-ons > Phantom Dust')
        col = lay.column(align=True)
        col.label(text='1. Start')
        col.operator(PDSTAGE_OT_new_arena.bl_idname, icon='ADD')
        col.operator('import_scene.phantom_dust_stage', text='Import Arena...', icon='IMPORT')
        col = lay.column(align=True)
        col.label(text='2. Light')
        col.operator(PDSTAGE_OT_bake_light.bl_idname, icon='LIGHT_SUN')
        col.prop(s, 'pd_light_custom', text='Game lighting (Scene tab)')
        col = lay.column(align=True)
        col.label(text='3. Export')
        col.prop(s, 'pd_base_arena', text='Replaces')
        col.operator('export_scene.phantom_dust_stage', text='Export...', icon='EXPORT')
        col.operator(PDSTAGE_OT_restore.bl_idname, icon='LOOP_BACK')
        n = {r: len(exporter.collections_with_role(s, r)) for r in ('VISUALS', 'COLLIDERS', 'SPAWNS', 'OBJECTS', 'EFFECTS')}
        box = lay.box()
        box.label(text='Collections in this scene:')
        for r, label in (('VISUALS', 'Visuals'), ('COLLIDERS', 'Colliders'), ('SPAWNS', 'Spawn Points'),
                         ('OBJECTS', 'Objects'), ('EFFECTS', 'Effects')):
            box.label(text='%s: %s' % (label, n[r] or 'none (base arena kept)' if r in ('VISUALS', 'COLLIDERS', 'SPAWNS') else n[r]),
                      icon='CHECKMARK' if n[r] else 'DOT')


classes = (PDSTAGE_OT_new_arena, PDSTAGE_OT_bake_light, PDSTAGE_OT_restore, PDSTAGE_PT_sidebar)
