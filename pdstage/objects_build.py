"""Write placed objects (props, breakables, jump pads...) into a stage .dat.

How the game uses them (PDUWP.exe FUN_140203720 / FUN_140203dc0, and Esper-RE st00.h):
- NM00 (header 0x5C, count at 0x60): object names, NUL-terminated.
- OB00 (header 0x90): one 0x38-byte entry per object: 3 .alr root indices (model per state: intact, broken,
  debris; FFFFFFFF = none), then 9 file offsets (FFFFFFFF = none): [3..5] unknown, [6] collision chain for the
  intact state, [7..8] unused in arenas, [9] effect block (EF00) for the intact state, [10..11] unused. [12..13]
  are 0 and FFFFFFFF in the first entry and uninitialised in the rest.
- Placement tables (header 0x04 + 4*slot, count at 0x30 + 4*slot): 0x24-byte entries: s32 object index,
  u8 category, u8 type, u8, u8, u32 0, f32 position[3], f32 rotation[3] (radians). A match uses slot
  (layout + 1) and falls back to slot 0.
- category/type choose the object's class through the game's factory table (0x1402dc4f0). Category 2 is the
  destructible family; see PRESETS.

Everything new is appended to the end of the file and the header offsets are pointed at it (the same method
confirmed in game for collision), so nothing else in the file moves.
"""
import struct

from . import dat
from .collision_build import build_block

NONE = 0xFFFFFFFF

# Behaviour presets: name -> (category, type, description, states used). From the factory table's class names
# and how the original arenas use them.
PRESETS = {
    'SOLID':       (1, 4,  'Solid prop: can be hit, never breaks (lights, signs)', 'I'),
    'BREAK_SCATTER': (2, 1, 'Breaks and the pieces scatter (boxes, chairs, handrails)', 'ID'),
    'BREAK_ROLL':  (2, 2,  'Breaks and the pieces roll (cones, barricades)', 'ID'),
    'CRUMBLE':     (2, 3,  'Crumbles in place (desks, benches, fences)', 'IBD'),
    'BREAK_TOUCH': (2, 18, 'Breaks when touched (glass railings)', 'IBD'),
    'WALL':        (2, 7,  'Breakable wall, pieces roll', 'IB'),
    'WALL_CRUMBLE': (2, 8, 'Breakable wall that crumbles', 'IB'),
    'CEILING':     (2, 12, 'Ceiling piece that falls', 'IB'),
    'PILLAR':      (2, 48, 'Pillar that crumbles', 'IB'),
    'JUMP_PAD':    (4, 16, 'Jump pad', 'I'),
}


def _tagged(tag, data):
    return tag + data


def add_objects(b, objects, placements):
    """Return a new .dat with these objects as the stage's only objects.

    objects:    list of dict(name, roots=(intact, broken, debris) .alr root indices or None,
                collision=[(v0, v1, v2, surface)] in the object's local game space, or None)
    placements: list of dict(object=index into objects, category, type, pos=(x, y, z), rot=(x, y, z),
                extra=(u8, u8) optional)
    The base arena's own object tables are left in the file but no longer used."""
    buf = bytearray(b)
    buf += b'\0' * (-len(buf) % 4)

    # names
    names = b''.join(o['name'].encode('ascii', 'replace')[:31] + b'\0' for o in objects)
    buf += b'NM00'
    names_off = len(buf)
    buf += names
    buf += b'\0' * (-len(buf) % 4)

    # per-object collision chains (each ends with its own 0xFF)
    col_off = []
    for o in objects:
        if o.get('collision'):
            block, _ = build_block(o['collision'])
            col_off.append(len(buf))
            buf += block
            buf += b'\0' * (-len(buf) % 4)
        else:
            col_off.append(NONE)

    # object table
    buf += b'OB00'
    ob_off = len(buf)
    for i, o in enumerate(objects):
        roots = [NONE if r is None else r for r in (list(o['roots']) + [None, None, None])[:3]]
        offs = [NONE] * 9
        offs[3] = col_off[i]
        tail = (0, NONE) if i == 0 else (NONE, NONE)
        buf += struct.pack('<3I9I2I', *roots, *offs, *tail)

    # one placement table, used by every layout (slot 0 is the fallback for all of them)
    buf += b'PS00'
    ps_off = len(buf)
    for p in placements:
        e6, e7 = p.get('extra', (0, 0))
        buf += struct.pack('<i4BI3f3f', p['object'], p['category'], p['type'], e6, e7, 0, *p['pos'], *p['rot'])

    struct.pack_into('<I', buf, dat.H_NAMES, names_off)
    struct.pack_into('<I', buf, dat.H_OBJECT_COUNT, len(objects))
    struct.pack_into('<I', buf, dat.H_OBJECTS, ob_off)
    for slot in range(11):
        struct.pack_into('<I', buf, dat.H_LAYOUT_SLOTS + 4 * slot, ps_off if slot == 0 else NONE)
        struct.pack_into('<I', buf, dat.H_LAYOUT_COUNTS + 4 * slot, len(placements) if slot == 0 else NONE)
    struct.pack_into('<I', buf, dat.H_FILE_SIZE, len(buf))
    return bytes(buf)


def read_objects(b):
    """Names, object table entries and placements as the game would see them (for checks)."""
    h = dat.header(b)
    names, o = [], h['names']
    for _ in range(h['object_count']):
        e = b.index(b'\0', o)
        names.append(b[o:e].decode('ascii', 'replace'))
        o = e + 1
    table = [struct.unpack_from('<14I', b, h['objects'] + i * 0x38) for i in range(h['object_count'])]
    places = []
    for slot, off, cnt in dat.placement_tables(b):
        for i in range(cnt):
            oid, cat, typ, e6, e7, _pad, *rest = struct.unpack_from('<i4BI3f3f', b, off + i * 0x24)
            places.append(dict(slot=slot, object=oid, category=cat, type=typ, extra=(e6, e7),
                               pos=tuple(rest[:3]), rot=tuple(rest[3:])))
    return names, table, places
