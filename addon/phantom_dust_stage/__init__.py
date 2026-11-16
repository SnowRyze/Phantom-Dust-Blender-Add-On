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
    shadows: BoolProperty(
        name='Character shadows', default=True,
        description='Add the shadow mesh the game needs for characters to cast shadows (a tiny hidden box; '
                    'the stage itself casts no shadows yet)')

    def invoke(self, context, event):
        self.base_arena = context.scene.pd_base_arena
        self.scale = context.scene.pd_scale
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
            msg = exporter.export_scene(context, exporter.base_dat_path(game_data, self.base_arena),
                                        self.filepath, self.scale)
            base_alr = os.path.join(game_data, 'Map', self.base_arena + '.alr')
            out_alr = os.path.splitext(self.filepath)[0] + '.alr'
            vmsg = exporter.export_visuals(context, base_alr, out_alr, self.scale, self.background_and_sky,
                                           self.shadows)
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
        lay.prop(c, 'pd_role')
        lay.prop(c, 'pd_surface')
        if c.pd_role == 'SPAWNS':
            lay.label(text='Child collections = layouts; spawn empties (+Y = facing) with 3 orb children')
        elif c.pd_role == 'VISUALS':
            lay.label(text='Texture from each material; baked lighting from the PD_Light colour attribute')
        elif c.pd_role in ('MISC', 'BREAKABLES'):
            lay.label(text='Not exported yet', icon='INFO')


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
    bpy.types.Scene.pd_base_arena = EnumProperty(name='Base arena', items=ARENA_ITEMS, default='st04')
    bpy.types.Scene.pd_scale = FloatProperty(name='Scale', default=cv.DEFAULT_SCALE, min=0.0001)
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_import.append(menu_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_export)
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    del bpy.types.Scene.pd_scale
    del bpy.types.Scene.pd_base_arena
    del bpy.types.Collection.pd_surface
    del bpy.types.Collection.pd_role
