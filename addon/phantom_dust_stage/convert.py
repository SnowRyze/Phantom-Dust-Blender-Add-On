"""Game <-> Blender coordinates, arena list and collection settings.

Game space is y-up. Blender is z-up: blender = (x, -z, y) * scale, a pure rotation plus uniform scale, so
triangle winding (and so the collision normals) is preserved.

Spawn facing: in game space the player faces (sin yaw, 0, cos yaw). In Blender that is the spawn empty's
+Y axis, so rotation_euler.z = yaw + pi.
"""
import math
import re

DEFAULT_SURFACE = 0x08      # the common floor/wall type
DEFAULT_SCALE = 0.1         # Blender units per game unit

# Battle arenas (names from setup/stageset/stageset_en.dat). Exporting replaces one of these.
ARENAS = [
    ('st02', 'Spiral Highway'), ('st12', 'Lightning Highway'), ('st22', 'Sunlight Highway'),
    ('st03', 'Lost Palace'), ('st13', 'Light Palace'), ('st23', 'Noble Palace'),
    ('st04', 'Panorama Earthquake'), ('st14', 'Panorama Building'), ('st24', 'Panorama Boss'),
    ('st05', 'Dawn City'), ('st15', 'Dusk City'), ('st25', 'Midnight City'),
    ('st06', 'Storm Refinery'), ('st16', 'Sunset Refinery'), ('st26', 'Acid Refinery'),
    ('st07', 'Twilight Lane'), ('st17', 'Silent Lane'),
    ('st08', 'Sein'), ('st01', "Edgar's Dream"),
]

ROLES = [
    ('NONE', 'None', 'Not exported'),
    ('COLLIDERS', 'Colliders', 'Meshes in here (and in child collections) become collision'),
    ('SPAWNS', 'Spawn Points', 'Child collections are layouts; each holds spawn empties with 3 orb children'),
    ('VISUALS', 'Visuals', 'Visible meshes: replace the arena\'s stage model (child collections named '
                           'Background/Sky replace those, if enabled on export)'),
    ('MISC', 'Misc (planned)', 'Cameras, kill height, skybox; not exported yet'),
    ('BREAKABLES', 'Breakables (planned)', 'Not exported yet'),
]


def to_blender(v, s):
    return (v[0] * s, -v[2] * s, v[1] * s)


def to_game(v, s):
    return (v[0] / s, v[2] / s, -v[1] / s)


def yaw_to_blender(yaw):
    return wrap(yaw + math.pi)


def yaw_to_game(rz):
    return wrap(rz - math.pi)


def wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


def surface_value(text, default):
    """Collection surface setting: hex text like "08" or "0x12"; empty = inherit."""
    text = (text or '').strip()
    return int(text, 16) if text else default


def natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', name)]
