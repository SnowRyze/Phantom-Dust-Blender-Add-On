# Phantom Dust Blender Add-On

Tools for building custom arenas for Phantom Dust (2017 Windows release) in Blender.

**Status:** research stage. The Python readers below work on every battle arena; the Blender add-on
itself is not written yet. See [FORMATS.md](FORMATS.md) for what is decoded and how it was confirmed.

| Part | Status |
|---|---|
| Spawns and orbs (`stNN.dat`, `CP00`) | Decoded, confirmed in game |
| Collision (`stNN.dat`) | Decoded; writer confirmed in game |
| AI navigation (`comdataN.cad`) | On hold (custom arenas aren't expected to need bots) |
| Visual stage (`stNN.alr`) | Import and export with textures and baked lighting; confirmed in game |
| Blender add-on (Blender 5.3) | Import/export of spawns, orbs and collision; confirmed in game |

## Requirements

- Python 3.10+
- Pillow, only for `tools/render_stage.py` (`pip install pillow`)
- Your own copy of the game. This repository contains no game files.

## Tools

Run from the repository root. Paths point at your game's `Assets\Data` folder.

```
python tools/dump_dat.py      Map/st04.dat --spawns       header, layouts, spawns, collision summary
python tools/collision_obj.py Map/st04.dat st04_col.obj   collision to OBJ (import into Blender)
python tools/render_stage.py  Map/st04.dat st04.png       picture of collision, spawns and orbs
python tools/dump_cad.py      com/st01/comdata.cad nav.obj   (st01's small format only)
python tools/dump_alr.py      Map/st04.alr --root 0
python tools/build_collision.py Map/st04.dat out.dat --obj mesh.obj [--keep]   new collision (writes a new file)
python tools/test_patch.py    ...                         the in-game test edits (writes a new file)
```

`test_patch.py` never edits a file in place. To try an edit, back up the arena's `.dat`, copy the output
over it, play that arena, then put the backup back.

## Blender add-on

Build the zip with `python tools/build_addon.py`, then in Blender 5.3: Edit > Preferences > Get Extensions >
menu (top right) > Install from Disk, and pick `dist/phantom_dust_stage-<version>.zip`.

The add-on converts what you build in Blender into the files Phantom Dust reads. Maps come first; character
models and skill animations/projectiles are planned.

**Building a map**
1. Set the game data folder once: Edit > Preferences > Add-ons > Phantom Dust Stage > `Assets\Data` folder.
2. Make collections and give each a role in **Collection Properties > Phantom Dust**:
   - **Colliders**: every mesh inside (and in child collections) becomes collision. Set **Surface type** on a
     collection (hex, e.g. `07`); children inherit it; the default is `08`, the common floor/wall type.
     Faces must point the way players stand on or hit them (Blender face normals).
   - **Spawn Points**: each child collection is a layout. In a layout, each spawn is an empty whose **+Y axis
     is the facing** (Blender's green arrow), with exactly **3 child empties** as its orb points.
   - **Visuals**: the visible meshes; they replace the arena's stage model. Each material's image is the
     texture (power of two is best; resized to at most 1024). **Lighting is baked into a colour attribute named
     `PD_Light`** (the game multiplies the texture by it; paint it or bake into it in Blender). Child collections
     named `Background`/`Sky` replace those models only if "Replace background and sky" is ticked on export.
3. **File > Export > Phantom Dust Stage (.dat)**: choose which arena it **replaces** and save. The game only
   loads its existing arena slots, so a custom map takes one over. With Visuals it also writes `stNN.alr` next
   to the `.dat`. Copy both over the game's `Map\stNN.dat` / `.alr` after backing them up.

How the base arena is used: it supplies the parts not made in Blender (background, sky, effects, objects).
Without a Colliders, Spawn Points or Visuals collection its collision, spawns or stage model are kept. Most arenas have 4-6 layouts
of 4 spawns; make 1 or more layouts of 4 and they are repeated to fill the slots.

**Starting from an existing arena (optional):** File > Import > Phantom Dust Stage (.dat) loads an arena's
collision and spawns into tagged collections, and sets the export to go back to the same slot. With
**Visible model** on, it also loads `stNN.alr` from the same folder: the stage, background and sky with their
textures, lined up with the collision, as a reference (it is not exported yet).

Character shadows work on exported stages ("Character shadows" export option, on by default). Not exported
yet: shadows cast by the stage itself (e.g. under stairs), normal maps and reflections (new meshes use the simple
`sd` shader), cameras, kill height, breakables, and adding more layouts than the base arena has.

**Tests:** `tests/blender_roundtrip.py` runs in Blender without a window: an imported arena exports with
identical triangles and spawns, a map built from scratch exports exactly its own geometry and spawns, and
mistakes (wrong orb or spawn counts) are refused. A file exported by the add-on worked in game.

```
blender -b --factory-startup --python tests/blender_roundtrip.py -- <Assets/Data folder> <out_dir> [--ingame-test]
blender -b --factory-startup --python tests/blender_visuals.py   -- <Assets/Data folder> <out_dir> [--ingame-test]
python tests/alr_rebuild.py <Assets/Data/Map folder> [out_dir]
```

## Credits

The `.alr` container layout builds on [desert-breeze-dust](https://github.com/ZacheerKour/desert-breeze-dust)
by ZacheerKour (original Xbox release).
