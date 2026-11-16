"""Phantom Dust Stage: build arenas in Blender and export them to the game's format.

- Collection Properties > Phantom Dust: give a collection a role (Colliders, Spawn Points) and, for collision,
  a surface type. Objects inside need no tags.
- File > Export > Phantom Dust Stage (.dat): pick the arena slot to replace and write a new .dat.
- File > Import > Phantom Dust Stage (.dat): optional, loads an existing arena as a starting point.
"""
import os

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import convert as cv
from . import exporter, importer
from ._lib import effects_build, objects_build

PRESET_ITEMS = [(k, k.replace('_', ' ').title(), v[2]) for k, v in objects_build.PRESETS.items()]
EFFECT_ITEMS = [(k, v[2], 'Copied from %s, effect %d, in your game files' % (v[0], v[1]))
                for k, v in effects_build.PRESETS.items()]

ARENA_ITEMS = [(k, '%s (%s)' % (name, k), 'Replace %s' % name) for k, name in cv.ARENAS]


class PDSTAGE_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    game_data: StringProperty(
        name='Game data folder', subtype='DIR_PATH',
        description="Phantom Dust's Assets\\Data folder (contains Map\\st04.dat and so on)")

    def draw(self, context):
        self.layout.prop(self, 'game_data')


def _prefs_game_data(context):
    try:
        return context.preferences.addons[__package__].preferences.game_data
    except (KeyError, AttributeError):
        return ''


class PDSTAGE_OT_import(bpy.types.Operator, ImportHelper):
    """Import a Phantom Dust arena (Assets/Data/Map/stNN.dat) as a starting point"""
    bl_idname = 'import_scene.phantom_dust_stage'
    bl_label = 'Import Phantom Dust Stage'
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = '.dat'
    filter_glob: StringProperty(default='st*.dat', options={'HIDDEN'})
    scale: FloatProperty(name='Scale', description='Blender units per game unit', default=cv.DEFAULT_SCALE, min=0.0001)
    collision: BoolProperty(name='Collision', default=True)
    spawns: BoolProperty(name='Spawns and orbs', default=True)
    visuals: BoolProperty(name='Visible model', default=True,
                          description='Stage, background and sky from stNN.alr, with textures (reference only)')

    def execute(self, context):
        try:
            _root, msg = importer.import_stage(context, self.filepath, self.scale, self.collision, self.spawns,
                                               self.visuals)
        except Exception as e:
            self.report({'ERROR'}, 'Import failed: %s' % e)
            return {'CANCELLED'}
        self.report({'INFO'}, 'Imported: ' + msg)
        return {'FINISHED'}


class PDSTAGE_OT_export(bpy.types.Operator, ExportHelper):
    """Write this scene as a Phantom Dust arena .dat, replacing the chosen arena slot"""
    bl_idname = 'export_scene.phantom_dust_stage'
    bl_label = 'Export Phantom Dust Stage'

    filename_ext = '.dat'
    filter_glob: StringProperty(default='*.dat', options={'HIDDEN'})
    base_arena: EnumProperty(name='Replaces', items=ARENA_ITEMS,
                             description='Arena slot this map replaces; its file supplies the parts not made in Blender')
    game_data: StringProperty(name='Game data folder', subtype='DIR_PATH',
                              description="Phantom Dust's Assets\\Data folder")
    scale: FloatProperty(name='Scale', description='Blender units per game unit', default=cv.DEFAULT_SCALE, min=0.0001)
    background_and_sky: BoolProperty(
        name='Replace background and sky', default=False,
        description='Also export Visuals child collections named Background/Sky (off: keep the arena\'s own, '
                    'including its animated sky)')
    remove_objects: BoolProperty(
        name='Clean slate', default=True,
        description='Remove everything the replaced arena placed: its props and breakables (stairs, lockers, '
                    'boxes...) and all its effects (lamps, falling rubble, floating debris...). Turn off only when '
                    'editing an imported arena')
    shadows: BoolProperty(
        name='Character shadows', default=True,
        description='Add the shadow mesh the game needs for characters to cast shadows (a tiny hidden box; '
                    'the stage itself casts no shadows yet)')

    def invoke(self, context, event):
        self.base_arena = context.scene.pd_base_arena
        self.scale = context.scene.pd_scale
        # Editing an imported arena keeps its objects; a map built from scratch drops them.
        self.remove_objects = not context.scene.pd_imported
        if not self.game_data:
            self.game_data = _prefs_game_data(context)
        self.filepath = self.base_arena + '.dat'
        return super().invoke(context, event)

    def execute(self, context):
        game_data = bpy.path.abspath(self.game_data or _prefs_game_data(context))
        if not game_data:
            self.report({'ERROR'}, 'Set the game data folder (Assets\\Data) in the export options or add-on preferences')
            return {'CANCELLED'}
        try:
            base_alr = os.path.join(game_data, 'Map', self.base_arena + '.alr')
            out_alr = os.path.splitext(self.filepath)[0] + '.alr'
            vmsg, objects, placements = exporter.export_models(context, base_alr, out_alr, self.scale,
                                                               self.background_and_sky, self.shadows)
            msg = exporter.export_scene(context, exporter.base_dat_path(game_data, self.base_arena),
                                        self.filepath, self.scale, self.remove_objects, objects, placements,
                                        game_data)
            if vmsg:
                msg += '; ' + vmsg + ' -> ' + os.path.basename(out_alr)
        except exporter.ExportError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        context.scene.pd_base_arena = self.base_arena
        context.scene.pd_scale = self.scale
        self.report({'INFO'}, 'Exported %s: %s' % (os.path.basename(self.filepath), msg))
        return {'FINISHED'}


class PDSTAGE_PT_collection(bpy.types.Panel):
    bl_label = 'Phantom Dust'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'collection'

    def draw(self, context):
        c = context.collection
        lay = self.layout
        parent = next((p for p in bpy.data.collections if c.name in p.children), None)
        if parent is not None and parent.pd_role == 'EFFECTS':
            lay.label(text='Effect type (in %s)' % parent.name, icon='SHADERFX')
            lay.prop(c, 'pd_effect')
            col = lay.column(align=True)
            col.label(text='Each object here (empties work well) is one placement:')
            col.label(text='location, turn about Z, and scale (multiplies the effect size)')
            return
        if parent is not None and parent.pd_role == 'OBJECTS':
            lay.label(text='Object type (in %s)' % parent.name, icon='OBJECT_DATA')
            lay.prop(c, 'pd_preset')
            destructible = objects_build.PRESETS[c.pd_preset][0] == 2      # category 2 = breakable objects
            if destructible:
                lay.prop(c, 'pd_hits')
                lay.prop(c, 'pd_damage')
                lay.prop(c, 'pd_debris_stays')
            if c.pd_preset == 'JUMP_PAD':
                lay.prop(c, 'pd_jump_power')
            lay.prop(c, 'pd_surface', text='Collider surface')
            col = lay.column(align=True)
            col.label(text='Meshes here = placements (linked duplicates of one mesh)')
            col.label(text='Child collections: Broken (pieces), Debris, Collider' if destructible
                      else 'Child collection: Collider (optional)')
            if destructible:
                box = lay.box()
                box.label(text='Debris speed is set by the game, from mass:', icon='INFO')
                box.label(text='lighter (smaller) pieces fly faster, heavier ones slower,')
                box.label(text='up to a fixed limit. The game works mass out from the model.')
            return
        lay.prop(c, 'pd_role')
        lay.prop(c, 'pd_surface')
        if c.pd_role == 'SPAWNS':
            lay.label(text='Child collections = layouts; spawn empties (+Y = facing) with 3 orb children')
        elif c.pd_role == 'VISUALS':
            lay.label(text='Texture from each material; baked lighting from the PD_Light colour attribute')
        elif c.pd_role == 'OBJECTS':
            lay.label(text='Each child collection is one object type')
        elif c.pd_role == 'EFFECTS':
            lay.label(text='Each child collection is one effect type (steam, sparks, smoke)')


def menu_import(self, context):
    self.layout.operator(PDSTAGE_OT_import.bl_idname, text='Phantom Dust Stage (.dat)')


def menu_export(self, context):
    self.layout.operator(PDSTAGE_OT_export.bl_idname, text='Phantom Dust Stage (.dat)')


classes = (PDSTAGE_Preferences, PDSTAGE_OT_import, PDSTAGE_OT_export, PDSTAGE_PT_collection)


def register():
    bpy.types.Collection.pd_role = EnumProperty(name='Role', items=cv.ROLES, default='NONE',
                                                description='What this collection is in the exported arena')
    bpy.types.Collection.pd_surface = StringProperty(
        name='Surface type', default='',
        description='Collision surface type in hex (e.g. 08, the common floor/wall type). Empty = inherit from the parent collection')
    bpy.types.Collection.pd_preset = EnumProperty(
        name='Behaviour', items=PRESET_ITEMS, default='SOLID',
        description='How objects of this type behave in game (the game\'s own object classes)')
    bpy.types.Collection.pd_debris_stays = BoolProperty(
        name='Debris stays', default=False,
        description='Leave the debris model lying where the object broke (off: it disappears, like the game\'s boxes)')
    bpy.types.Collection.pd_effect = EnumProperty(
        name='Effect', items=EFFECT_ITEMS, default='STEAM',
        description='Which of the game\'s effects to place (copied from your game files when exporting)')
    bpy.types.Collection.pd_jump_power = bpy.props.IntProperty(
        name='Jump power', default=150, min=1, max=255,
        description='How hard the pad launches players (the game\'s pads use 100-250)')
    bpy.types.Collection.pd_hits = bpy.props.IntProperty(
        name='Hits to break', default=1, min=1, max=255,
        description='How many hits the object takes before it breaks')
    bpy.types.Collection.pd_damage = bpy.props.IntProperty(
        name='Debris damage', default=2, min=0, max=255,
        description='Damage a player takes when hit by this object\'s moving broken pieces or debris '
                    '(the game\'s boxes use 2, benches 3). How fast debris moves is up to the game: it depends on '
                    'the piece\'s mass (lighter = faster, with a fixed limit)')
    bpy.types.Scene.pd_base_arena = EnumProperty(name='Base arena', items=ARENA_ITEMS, default='st04')
    bpy.types.Scene.pd_scale = FloatProperty(name='Scale', default=cv.DEFAULT_SCALE, min=0.0001)
    bpy.types.Scene.pd_imported = BoolProperty(name='Started from an imported arena', default=False)
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_import.append(menu_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_export)
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    del bpy.types.Scene.pd_imported
    del bpy.types.Scene.pd_scale
    del bpy.types.Scene.pd_base_arena
    del bpy.types.Collection.pd_effect
    del bpy.types.Collection.pd_damage
    del bpy.types.Collection.pd_hits
    del bpy.types.Collection.pd_jump_power
    del bpy.types.Collection.pd_debris_stays
    del bpy.types.Collection.pd_preset
    del bpy.types.Collection.pd_surface
    del bpy.types.Collection.pd_role
