# Phantom Dust Blender Add-On

Build custom arenas for **Phantom Dust** (2017 Windows release) in **Blender 5.3** and play them in the game.
You model the arena in Blender, tag a few collections, and export. The add-on writes the game's own arena
files (`stNN.dat` and `stNN.alr`) and can install them for you.

| Map feature | Status |
|---|---|
| Visible stage with your own textures and baked lighting | Works in game |
| Collision with surface types (floors, walls, slopes) | Works in game |
| Spawn points and orb points (several layouts) | Works in game |
| Character shadows | Works in game |
| Props and breakables (hits to break, debris damage, debris stays) | Works in game |
| Jump pads | Works in game |
| Effects: steam, sparks, smoke | Works in game |
| Your own sky and background | Works in game |
| Game lighting for the stage and characters (sun direction and colours) | Works in game |
| Fog | Not possible: the PC version ignores fog |
| Shadows cast by the stage itself, normal maps, reflections | Not yet |

Character models and skill animations/projectiles are planned after maps.

You need your own copy of the game. This repository contains no game files.

## Install

1. Get `phantom_dust_stage-<version>.zip` (from the releases, or build it: `python tools/build_addon.py`
   writes it to `dist/`).
2. Blender 5.3: **Edit > Preferences > Get Extensions**, menu (top right) **> Install from Disk**, pick the zip.
3. **Edit > Preferences > Add-ons > Phantom Dust Stage**: set **Game data folder** to the game's
   `Assets\Data` folder (the one with `Map\st04.dat` in it).

Everything is in the 3D View sidebar: press **N**, tab **Phantom Dust**.

## Quick start

1. **New Arena Setup** (sidebar). In an empty scene it makes the tagged collections, a 30 m floor with its
   collider, one spawn layout (4 spawns, 3 orbs each), a jump pad in the middle and a sun.
2. Model your arena under **Visuals**. Put simple shapes for what players stand on and bump into under
   **Colliders**. Move the spawns and orbs where you want them.
3. **Bake Lighting** (sidebar): bakes the sun and sky light into the stage's colours.
4. **Export...**: pick the arena it **Replaces**, tick **Install into the game**, save anywhere outside the game
   folder. The game's own files are backed up first.
5. Start the game and play that arena. **Restore Original Arena** (sidebar) puts the game's own files back.

`examples/build_example_arena.py` builds a complete example (walls, pillars, ramp, platform, crates, benches, a
jump pad, effects, sky and background) and exports it:

```
blender -b --factory-startup --python examples/build_example_arena.py -- <Assets/Data folder> <out_dir>
```

## Building a map

Tags go on **collections**, in **Collection Properties > Phantom Dust**. Objects inside need no tags.
1 Blender metre = 10 game units (the default scale).

**Visuals**: the visible stage. Each material's image is the texture (power-of-two sizes are best; larger than
1024 is resized). Lighting is a colour attribute named **`PD_Light`**: the game multiplies the texture by it.
Bake Lighting fills it; you can also paint it. Images whose names match one of the replaced arena's textures
reuse that texture. Keep each triangle within 8 texture repeats (larger UVs are clamped).

**Sky and background**: child collections of Visuals named `Sky...` and `Background...`, exported when
**Replace background and sky** is ticked (otherwise the arena's own animated sky stays). A big inward-facing
sphere textured with a gradient works as a sky; give it a white `PD_Light`. They use the simple shader, so they
don't animate.

**Colliders**: every mesh inside (and in child collections) becomes collision. Faces must point the way players
stand on or hit them (Blender face normals; check with Face Orientation). **Surface type** (hex) on a collection
applies to its children: `08` (the default) for floors and walls, `07` for slopes. Players who fall out of the
map are put back on it by the game, so no kill floor is needed.

**Spawn Points**: each child collection is one layout (`LAYOUT_1`, `LAYOUT_2`...). In a layout each spawn is an
empty whose **+Y axis is the facing** (Blender's green arrow) with exactly **3 child empties** as its orb points.
Each layout needs as many spawns as the replaced arena has (4 in most arenas). With fewer layouts than the arena
has, they are repeated; the game picks one per match.

**Objects** (props, breakables, jump pads): an Objects collection holds one child collection per object type.
Every mesh directly in a type collection is one placement (use linked duplicates; turn about Z only; scale 1).
Model the object around the world origin. On the type collection:
- **Behaviour**: the game's own object classes: Solid, Break Scatter, Break Roll, Crumble, Break Touch, Wall,
  Wall Crumble, Ceiling, Pillar, Jump Pad.
- Breakables: **Hits to break**, **Debris damage**, **Debris stays**, and optional child collections `Broken`
  (each mesh is one piece) and `Debris`. Debris speed is set by the game from the piece's size (lighter pieces
  fly faster, up to a fixed limit).
- Jump pads: **Jump power** (the game's pads use 100-250; 200 launches a player about twice a 6 m wall).
- Optional child collection `Collider` (default: a box around the model).

**Effects**: an Effects collection holds one child collection per effect type (**Effect**: Steam, Sparks,
Smoke). Every object in it (empties work well) is one placement: location, turn about Z, and scale.

**Lighting** (Scene Properties > **Phantom Dust Lighting**, tick the header): the game lights the stage, objects
and effects with one light and characters with another. Each has a **Light** colour and an **Ambient** colour
(the shaded side). **Sun**: the game's light follows this Sun's direction; use the sun you baked with. The game
multiplies the stage's baked colours by its light, so keep the stage colours near the defaults unless you want
a tint. Off: the replaced arena's lighting is kept.

## Export

**File > Export > Phantom Dust Stage (.dat)** or the sidebar's **Export...**:
- **Replaces**: the arena slot the map takes over (the game only loads its own arenas). That arena supplies
  what the scene doesn't have: without Colliders, Spawn Points or Visuals its own are kept.
- **Clean slate** (on for new maps): removes the replaced arena's own props and effects.
- **Replace background and sky**, **Character shadows** (on).
- **Install into the game**: copies the result over the arena in the game data folder, after backing up the
  game's files once into `Map\pd_addon_backup`. Exports always start from the game's own files (the backup),
  never from a map installed earlier. Without it, copy `stNN.dat` and `stNN.alr` over the game's yourself.

Everyone in an online match should have the same map installed.

**Editing an existing arena** (secondary): **Import Arena...** loads an arena's collision, spawns and (with
**Visible model**) its stage, background and sky with textures. Edit and export back to the same slot; Clean
slate is off for imported arenas so their objects stay.

## For developers

See [handoff/HANDOFF.md](handoff/HANDOFF.md) for setting up a new machine and continuing the work, and [FORMATS.md](FORMATS.md) for every decoded format and how it was confirmed in game. The readers and writers
are plain Python in `addon/phantom_dust_stage/pdstage/` (no Blender needed; `import pdstage` works from the repository root).

```
python tools/dump_dat.py      Map/st04.dat --spawns       header, layouts, spawns, collision summary
python tools/collision_obj.py Map/st04.dat st04_col.obj   collision to OBJ
python tools/render_stage.py  Map/st04.dat st04.png       picture of collision, spawns and orbs (needs Pillow)
python tools/dump_alr.py      Map/st04.alr --root 0       models and textures
python tools/dump_ssb.py      Map/st04.dat                the arena's lighting script
python tools/test_patch.py    ...                         the in-game test edits (writes a new file)
```

Tests (Blender without a window, or plain Python):

```
blender -b --factory-startup --python tests/blender_workflow.py  -- <Assets/Data folder> <work_dir>
blender -b --factory-startup --python tests/blender_roundtrip.py -- <Assets/Data folder> <out_dir>
blender -b --factory-startup --python tests/blender_visuals.py   -- <Assets/Data folder> <out_dir>
python tests/alr_rebuild.py   <Assets/Data/Map folder>
python tests/maplight_test.py <Assets/Data/Map folder>
python tests/objects_test.py  <arena.dat> <arena.alr> <out_dir>
```

`blender_workflow.py` works on a copy of the game's files: setup, bake, export with install, a second export,
and restore.

## Credits

The `.alr` container layout builds on [desert-breeze-dust](https://github.com/ZacheerKour/desert-breeze-dust)
by ZacheerKour (original Xbox release).
