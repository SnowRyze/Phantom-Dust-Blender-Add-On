# Phantom Dust stage formats

Phantom Dust (2017 UWP release, `PDUWP.exe`). Paths are relative to the game's `Assets\Data`.
Function names are Ghidra addresses in `PDUWP.exe` (image base `0x140000000`).

Status words: **confirmed** = changed in a test file and seen in game. **read from code** = taken from the
decompiled loader, consistent across every arena, not tested on its own. **likely** / **unknown** as stated.

## Files that make an arena

| File | What it holds |
|---|---|
| `Map\stNN.alr` | Visual stage: meshes, materials, textures, nodes |
| `Map\stNN.dat` | Collision, spawn/orb layouts, object table and more (below) |
| `Map\stNNcam.alr` | Intro camera keyframes (likely) |
| `com\stNN\comdata.cad` | AI navigation mesh (likely) |

Stage names are in `setup\stageset\stageset_en.dat`, e.g. st04 = Panorama Earthquake (`st04Panorama-earth`).
Arenas share files across lighting variants only by copy: st04 / st14 / st24 are separate files.
`st00` and `st09_0x` are story/event stages with a different `.dat` header.

## `stNN.dat` header (read from code: `FUN_140203720`)

Magic `ST00`, then u32 values. Offsets are from the start of the file; `FFFFFFFF` = absent.
Section offsets point just past a 4-character tag (e.g. `NM00`).

| Offset | Meaning |
|---|---|
| `0x04 + 4*i` (i = 0..10) | Layout slot i. The match uses slot `layout + 1`, falling back to slot 0 |
| `0x30 + 4*i` (i = 0..10) | Per-layout value (u16 used) |
| `0x5C` | `NM00` object names (e.g. `st04_kaidanA_` = stairs) |
| `0x60` | Object count (a count, not an offset) |
| `0x64` .. `0x84` | `OC00`, `OC01`, `OC02`, `OE00`, `OE01`, `OE02`, `OA00`, `OA01`, `OA02` (unknown) |
| `0x90` | `OB00` object table, 0x38-byte entries; the first 3 u32 are root indices into `stNN.alr` |
| `0x94` | **Collision** (below) |
| `0x98` | `EF00` (unknown, likely effects) |
| `0x9C` | `SP00` (unknown) |
| `0xA0` .. `0xBC` | `MD00`, then the `CP00` spawn layouts |
| `0xD0 + 4*v` | Lighting script (`mapLight`, below) for variant v; unused variants fall back to `0xD0` |
| `0xF4` | Light animation block (an `.alr`-style chunk `0x0E` of `0x05` animation chunks) |
| `0x138` | File size (true in every arena) |

Online, the host picks the layout as `rand() % count` and sends it to the other players.

## Spawns and orbs: `CP00` sections (confirmed)

Each arena has 4-6 `CP00` sections, one per layout, usually with 4 entries each. Some layouts are exact
duplicates (st02: layout 0 = 3). Exceptions: st01 has 2 entries per layout, st06/16/26 have one layout
with a single entry, and st09 (Sein) has one layout of 8 entries.

```
"CP00"
u32  (size << 16) | count        e.g. 0x01400004 = 4 entries of 0x50
count x entry (0x50 bytes):
  +0x00 f32 x, y, z              spawn position, y up                     confirmed
  +0x0C f32 yaw                  facing, radians                          confirmed
  +0x10 u32 0x80100003
  +0x14 3 x f32 x, y, z          that player's 3 orb points               confirmed
  +0x38 u32 0xFFFFFFFF
  +0x3C u32 x4                   usually 128, 3, 24, 0                    unknown
  +0x4C u32 flags                0x000b641c / 0x000b664c                  unknown
```

Orbs normally lie in front of the spawn's facing, about 50 units apart in a row.

How it was confirmed (st04): stacking orbs 2-3 onto orb 1 put all orbs in one spot; raising every spawn
250 units made players drop from the sky; adding pi to the yaw put the orb row behind the player.

## Collision: header `0x94` (confirmed)

Read from `FUN_1401d3d70`, `FUN_1401d2c20`, `FUN_1401d3040`, `FUN_1401d4070`. Confirmed in game: lowering
every vertex, centre and bounding box by 15 left players standing sunk into the visible floor.

A chain of records, ended by a record whose first byte is `0xFF`:

```
u8  type        surface type (game special-cases 0x12, 0x13, 0x1F); meaning unknown
u8  kind        8 = vertex list, 3 = triangle chunk (1 also handled, not seen in arenas)
u8  flags       0x03 in every arena (bit 0: registered in the spatial tree)
u8  0xFF
u32 size        bytes after this 12-byte header; next record at +size+0x0C
u32 0
```

**Kind 8, vertex list:** `size / 12` x f32 xyz. Every arena has exactly one.

**Kind 3, triangle chunk** (`size = 0x30 + 20 * n`):

```
+0x0C f32 x3  centre
+0x18 f32     radius
+0x1C f32 x3  bounding box min
+0x28 f32 x3  bounding box max
+0x34 u16     triangle count n
+0x38 u32     which vertex list (index among kind-8 records)
+0x3C n x 20 bytes:
      u16 a, b, c        vertex indices
      u16 attr           0 in every arena
      f32 x3 normal      normalize((b - a) x (c - a))
```

Chunks are small (1-11 triangles). The game builds its spatial grid (30 x 20 x 30 cells) and tree at load
time from these records, so a writer only needs the records.

**Chunk centre and radius:** the centre is the smallest sphere enclosing the chunk's vertices (matches every
chunk in st04 and st32 to 0.003); the radius is the farthest vertex from that centre; the bounding box is the
exact min/max of the vertices.

**Writing collision (confirmed):** `pdstage/collision_build.py` builds the block from any triangles. Rebuilding
each of the 21 arenas from its own triangles gives back the same triangles, surface types and normals (chunking
differs, which the game handles). In game, st04 with its collision fully rebuilt by the writer plus a 40 x 40 x 25
box at every first orb point played normally, and the boxes were solid.

**Replacing collision without resizing (confirmed):** append the new block (records plus the `0xFF` end
byte) at the end of the file, set header `0x94` to its offset and `0x138` to the new file size. The old block
stays in place unused, so no other offset changes. Tested on st04 with a lowered copy appended: players sank
into the floor, and the file grew by 111 KB with no load problems. (Growing the block in place would instead
shift `EF00`, `SP00`, `MD00`, the `CP00` layouts and about half the object-table offsets.)

Every battle arena parses with no out-of-range index, every normal unit length and matching its winding
(about 1,200 to 9,300 triangles per arena).

Surface types seen: st04 uses `02`, `07` (slopes and stairs), `08` (most floors and walls), `12`, and `21` on
the vertex list. Other arenas use other values. Copy an existing arena's values until they are understood.

## `com\stNN\comdata*.cad`: AI navigation data (likely; on hold)

On hold: custom arenas are not expected to need bots.

The game loads `com\st%02d\comdata%d.cad` and `camdata.cam`. Two formats exist:

**Battle arenas: `comdataN.cad`, not decoded.** Always exactly 674,312 bytes. Starts with a u32 count
(st04: 340) followed by xyz points at floor heights; the rest is unknown. Arenas have 1-3 of these
(st04: `comdata0`-`2`; `comdata0` and `comdata1` are identical). Arenas 12-26 mostly have none
(only st24 has one), so those variants may share data or run without it.

**st01 only: `comdata.cad`, small format:**

```
u32 n_verts, u32 n_quads_a, u32 n_quads_b
n_verts x f32 xyz
(n_quads_a + n_quads_b) x u32[4]     quad vertex indices
```

Not tested in game.

`camdata.cam` (776 bytes in every arena) is not decoded.

## `.alr` containers

Same container as the original Xbox release (see [desert-breeze-dust](https://github.com/ZacheerKour/desert-breeze-dust),
`docs/FORMATS.md`): header `0x11`, root offsets at `0x20`, each root a chain of `[u32 type][u32 size]` records
ending at type 0. In `stNN.alr`, root 0 is the main stage mesh (type 2 meshes, type 3 node list with 64-byte
entries from record offset +16). Many roots are empty placeholders, and type 19 records are all zero.
No spawn or orb data was found in the `.alr`.

### Reading models and textures (confirmed by import)

Following the Phantom Dust wiki ALR page and Esper-RE `alr.h`, checked on st04 (`pdstage/alr.py`):
- Header: resource buffer offset at `0x0C` and size at `0x14` add up to the file size; the buffer starts on a
  `0x1000` boundary. Version is `0x52` in the 2017 release.
- `0x15` texture table: names decode with the base-40 text encoding (`st04_c_kabe3`, `st04_n_...`); sizes match
  format and mip count for 63 of 64 entries. st04 uses BC1, BC3 and uncompressed BGRA (`0x86`).
  **Texture data is linear** in the 2017 release (not Xbox-swizzled).
- `0x02` meshes: index data starts at `+0x68`; every index is within its `0x16` vertex buffer. Primitive 5 =
  triangle list, 6 = strip. Node transforms (`0x03`) composed as T * Rz * Ry * Rx * S, then parents.
- Imported into Blender, the stage, background and sky render correctly textured and line up with the
  collision and spawns. Compared with the game, the orientation is correct (not mirrored) with
  Blender = (x, -z, y) x scale.

### Writing models (confirmed in game)

`pdstage/alr_build.py` rebuilds an `.alr` from its parts: header (root offsets), texture table (new entries
appended), each root's chunk chain (replaced roots rebuilt, others copied), padding to `0x1000`, then the base
resource buffer unchanged with new vertex/texture data appended. With no changes it reproduces all 22 arena
files byte for byte.

- New meshes use vertex format `0x01` (shader `sd`, 0x18 bytes): position (3 floats), **packed normal** at
  `0x0C` (11/11/10 bits signed: x * 1023, y * 1023, z * 511), UV int16 / 4096 at `0x10`, and a **baked vertex
  colour** at `0x14` (bytes B, G, R, A). The colour is the stage's baked lighting: the game multiplies the texture
  by it. Format `0x03` (`sbts`) has the same colour at `0x14`, plus tangent data at `0x18`/`0x1C`.
- Material, vertex-buffer and mesh fields not understood are copied from an existing `sd` mesh.
- Mesh header `+0x08` centre and `+0x14` radius: smallest enclosing sphere; `+0x18`/`+0x24` bounding box.
- New textures: uncompressed BGRA (`0x86`), power of two, full mip chain, 12-character base-40 name.
- Confirmed in game on st04: the stage rebuilt from its own meshes with colours (and the `sshadow*` shadow
  meshes carried over) looks like the original; without the colours it is uniformly too bright. A stage exported
  from Blender with an added textured, vertex-lit cube (and collider) shows correctly.

### Shadow mesh (confirmed in game)

Each stage model has a mesh with shader `sshadowch` (vertex format `0x07`: position + packed normal, 0x10 bytes),
and st04 also a small `sshadowc` one (format `0x10`, position only). In st04 the `sshadowch` mesh is mostly
walls, pillars and stairs between heights 50 and 160, a third of it coinciding with visible triangles: it behaves
like **shadow volumes** of the stage.

Tested on st04:
- Stage without any shadow mesh: characters cast **no shadow**.
- Stage rebuilt with the original shadow meshes carried over: character shadows as normal.
- Shadow mesh = a copy of every stage triangle: surfaces turn dark, patchy and partly see-through.
- Shadow mesh = a **1-unit closed box 1000 units below the stage**: clean surfaces and character shadows work.
  The writer uses this by default; the stage then casts no shadows of its own.

## Objects: props and breakables (confirmed in game)

Read from `FUN_140203720` (object table) and `FUN_140203dc0` (creates placed objects), with names from Esper-RE
`st00.h`. New objects written by `pdstage/objects_build.py` appear, block players and break in game.

- **`NM00`** (header `0x5C`, count at `0x60`): object names, NUL-terminated (`st04_kaidanA_` = stairs).
- **`OB00`** (header `0x90`): one `0x38`-byte entry per object:
  `u32 model[3]` (`.alr` root index for the **intact**, **broken** and **debris** states, `FFFFFFFF` = none),
  then 9 file offsets: `[6]` = the object's own **collision chain** (same record format as the stage collision,
  in object-local space), `[9]` = its **effect block** (a small `EF00` table, e.g. a break burst); the others are
  unused in arenas. The last two u32 are uninitialised (`cdcdcdcd`) except in the first entry.
- **Placements** (header `0x04 + 4*slot`, counts at `0x30 + 4*slot`, section tags `PS00`/`PS01`): `0x24`-byte
  entries `s32 object, u8 category, u8 type, u8, u8, u32 0, f32 pos[3], f32 rot[3]`. A match uses slot
  `layout + 1`, else slot 0. Setting the counts to 0 removes every placed object (confirmed).
- **category / type pick the object's class** through the factory table at `0x1402dc4f0`. Category 2 is the
  destructible family: 1 `Rep01` (breaks, pieces scatter: boxes, chairs, handrails), 2 (cones, barricades),
  3 `Rep03` (crumbles: desks, benches, fences), 7/8 breakable walls, 12/13 falling ceiling pieces, 18 breaks when
  touched (glass railings), 48 crumbling pillars, and more. Category 4: 15 `ReadLim` ("genkai"/limit), **16 `Jump`**
  (jump pads). Category 1: simple hittable props (type 4: lights). Category 3: hub-world doors and chairs.
- **Object models** are small local-space `.alr` roots. The game reads **four per-node values** (bytes `0x30-0x3F`
  of each 64-byte node, as floats) when an object breaks:
  - broken models: each piece on its own node with `(3, 0, 0, 0)`. Tested: a broken model made of two such
    pieces breaks into 2 in game; a single node with zeros makes the object vanish.
  - debris roots: `(2, 2)` (boxes) made new debris disappear after breaking; zeros left it lying there.
  - intact roots: zeros, or `(0, 3)` on desks and lockers (meaning not yet known).
  Original nodes use flags `0x0004`.
- **Read from the code** (`pdStageObjAHitCrash`, `pdStageObjARoll`, `FUN_1401ec350`/`FUN_1401ec800`):
  - **Hits to break** = intact root node value 3 (object field `+0x4e`, minimum 1). Each hit lowers it; the hit that
    finds it below 2 breaks the object. Confirmed in game (3 hits).
  - **Damage on contact** = second value of the current model's root node: passed to the player when a moving
    broken/debris object touches them (only if the value is non-zero). Not yet seen in game (debris barely moves).
  - Breaking spawns the object's effect entries of kind 2 (its `EF00` effect block) at the hit, then launches the
    next state's model as a physics body: speed = sqrt(1200 / max(mass, 200)) along the hit direction, plus a small
    random upward kick, **capped at 1.5 units per frame**; mass comes from the model. A per-object scale exists in
    the code but nothing in the files sets it. So debris speed/distance is fixed by the game.
  - Object table offset slots per state (intact, broken, debris): `[3..5]` animation (`OA` sections, `.alr` 0x05
    chunks; e.g. Spiral Highway's collapsing bridges), `[6..8]` collision (`OC`), `[9..11]` effects (`OE`).

### Jump pads and falling out (confirmed in game)

- **Jump pads** (category 4, type 16, class `pdStageObjJump`): the game's pads have no model, only a flat square
  collider (30-60 units wide) as the trigger, and put the **jump strength in the first spare placement byte**
  (+6): 100, 120, 200 or 250 in the arenas. A pad written with 200 launched a player to about twice the height of
  a 60-unit wall.
- **No kill height in arena files**: no arena places an object for it, and the collision bounds are only used for
  the lookup grid. Tested with a gap in the floor collision: a player who fell through was put back on the map by
  the game. Narrow gaps are hard to fall through (players catch on edges).
- Category 4 also has `ReadLim` ("genkai", type 15) and trigger walls (types 1-12), only used in Sein (st09).

## Effects (`EF00`, header `0x98`) (confirmed in game)

`0x5C`-byte entries: `u8 kind, u8 layout filter (0 = always, else only for layout value - 6), u8 0xFF, u8 0,
f32 position[3], f32 rotation[3] (radians), f32 scale[3]`, then 13 kind-specific values. Count and byte size
follow the `EF00` tag (`u16, u16`). The kind picks the effect class through the table at `0x1402dc520`
(`FUN_1401ef940`):

| Kind | Class | Kind | Class |
|---|---|---|---|
| 2, 3, 8 | smoke (`pdvkEbSmoke`) | 13, 10 | effect model (lamps, signs) |
| 4 | belt smoke | 14, 15 | effect model (other) |
| 5 | glow | 16, 17 | screen shake |
| 6, 9 | crash (break burst) | 18, 19 | water drops |
| 7 | jump point | 20 | stage parameters (`pdvkEbStgParam`, one per arena): the stage's variants, see below |
| 11, 12 | sound emitter | 21, 22 / 23, 24 | steam / sparks |

Copied into another arena (tested in Panorama Earthquake's slot): **steam** (Sein), **sparks** (Sein) and
**smoke** work; **glow** (Twilight Lane) draws as a white square and **water drops** (Lost Palace) don't show:
they need their home arena's textures. Effect models, sound emitters and crash bursts reference arena-specific
resources (small index values), so they aren't portable either. A new table is written by
`pdstage/effects_build.py`, appended to the file with header `0x98` repointed.

**Stage variants.** Per the user's knowledge of the game, the stage-parameters effect (kind 20) goes with the
stage's **variants**: different effects, object positions and so on for the same stage, one of which is picked
at random when a match starts. In the files this shows up as the per-layout placement tables (`PS00`/`PS01`...,
one per layout slot) and the effect entries' layout filter byte (an effect shown only in one variant). The
add-on currently writes one variant (placement slot 0, effects for all layouts) and the clean slate drops the
base arena's kind-20 entry.

## Lighting: the `mapLight` script (header `0xD0`) (confirmed in game)

Loaded by `FUN_140199b00` (it falls back to `maplight%d.ssb` files, which the PC version doesn't ship). A
compiled SSB script: header (0x20 bytes: header size, function table offset, string pool offset twice, 0,
`FFFF FFFF`, a u32 that varies per file, 0), 32-bit code words, a function table with one entry (`maplight`,
two base-40 words, start at word 8) and an empty string pool. The code is only argument pushes and native calls:

| Word | Meaning |
|---|---|
| `(v << 16) \| 0x0E` | push the small int v |
| `(low 16 bits << 16) \| 0x0F`, then the 32 bits | push a float, or a packed `0x00RRGGBB` colour |
| `(id << 16) \| (count << 8) \| 0x01` | call native `id` with the last `count` pushed values |
| `0x00000005` | return |

The game keeps four light sets (0x58 bytes each at `0x1403e8a40`). Set 0 lights the stage, placed objects
and effects; set 1 lights characters; sets 2 and 3 are used while drawing the far models (`FUN_1401c87f0`).

| Call | Arguments |
|---|---|
| `2000` | ambient axis (3 floats), light direction (3 floats, the way the light travels: y < 0 = from above), light colour, second colour, ambient colour, set |
| `2002` | fog: a, b, colour, mode (0 off, 1/2 exponential with density a, 3 linear from b to a), set |
| `2005` | point light: range, position (3 floats), colour, slot 0-2, set |
| `2001` | 0, a colour |
| `2003` | a scale (0.7-1.1 across arenas), 0 |

Confirmed in game: set 0's light and ambient colours tint the stage, objects and effects (multiplying the
baked vertex colours, with the shaded side getting the ambient colour); set 1's tint characters. **Fog does
nothing on PC**: the fog render states the script feeds (`0x5C`-`0x60`, `0x8A`) have no case in the PC
version's render-state setter `FUN_140020660`, and a test with bright fog colours showed none.
`addon/phantom_dust_stage/pdstage/maplight.py` reads and writes the script (every arena's script rebuilds byte-identical);
`tools/dump_ssb.py` prints it.

## Not yet known

- How stage materials pick shaders (new meshes use `sd`).
- What surface types mean, and the `128, 3, 24, 0` / flags values in spawn entries.
- `OA`/`OC`/`OE` sections, `SP00`, `MD00`, the object table beyond its first 3 fields.
- `stNNcam.alr` details; natives `2001` and `2003` of the lighting script; the light animation block.
