"""Effects collections -> arena effects (steam, sparks, smoke...).

  Effects                 role Effects
    Steam vents           one child collection per effect type: Effect preset (Collection Properties)
      Empty, Empty.001    every object directly in it is one placement: location, rotation about Z
                          (added to the preset's own turn), and scale (multiplies the preset's size)

Presets copy one of the game's own effect entries from the user's game files at export time.
"""
import os
import struct

from ._lib import effects_build
from . import convert as cv


class EffectsError(Exception):
    pass


def gather(context, eff_colls, scale, game_data):
    """Returns (list of raw entries, count per preset)."""
    cache, entries, counts = {}, [], {}
    for ec in eff_colls:
        for tc in ec.children:
            preset = getattr(tc, 'pd_effect', 'STEAM')
            arena, index, _label = effects_build.PRESETS[preset]
            if arena not in cache:
                from .exporter import original_path       # the game's own file, even if a map replaced it
                path = original_path(game_data, arena + '.dat')
                if not os.path.isfile(path):
                    raise EffectsError('effect preset %s needs %s from the game' % (preset, path))
                cache[arena] = open(path, 'rb').read()
            raw = effects_build.preset_entry(cache[arena], index)
            base_scale = struct.unpack_from('<3f', raw, 0x1C)
            for ob in tc.objects:
                mw = ob.matrix_world
                e = mw.to_euler('XYZ')
                s = mw.to_scale()
                # Blender scale (x, y, z) -> game axes (x, z, y)
                mult = (s.x, s.z, s.y)
                entries.append(effects_build.place(raw, cv.to_game(mw.translation, scale), yaw=e.z,
                                                   scale=tuple(base_scale[k] * mult[k] for k in range(3))))
                counts[preset] = counts.get(preset, 0) + 1
    return entries, counts
