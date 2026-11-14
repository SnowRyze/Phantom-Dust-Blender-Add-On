# Phantom Dust Blender Add-On

Tools for building custom arenas for Phantom Dust (2017 Windows release) in Blender.

**Status:** research stage. The Python readers below work on every battle arena; the Blender add-on
itself is not written yet. See [FORMATS.md](FORMATS.md) for what is decoded and how it was confirmed.

| Part | Status |
|---|---|
| Spawns and orbs (`stNN.dat`, `CP00`) | Decoded, confirmed in game |
| Collision (`stNN.dat`) | Decoded, confirmed in game |
| AI navigation (`comdataN.cad`) | Arena format not decoded (st01's small format is) |
| Visual stage (`stNN.alr`) | Readable; writing not done |
| Blender add-on | Not started |

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
python tools/test_patch.py    ...                         the in-game test edits (writes a new file)
```

`test_patch.py` never edits a file in place. To try an edit, back up the arena's `.dat`, copy the output
over it, play that arena, then put the backup back.

## Planned Blender workflow

Collections carry the role, so objects inside need no tags:

- **Visuals**: the visible meshes
- **Colliders**: collision meshes
- **Spawn_Points**: one sub-collection per layout, 4 `SPAWN_n` empties each with 3 `ORB` children
  (empty position = spawn, its rotation = facing)
- **Misc**: `CAM_01`, `CAM_02`... for the intro camera, `KILL_HEIGHT` empty, `SKYBOX`
- **Breakables**: reserved

## Credits

The `.alr` container layout builds on [desert-breeze-dust](https://github.com/ZacheerKour/desert-breeze-dust)
by ZacheerKour (original Xbox release).
