"""Access to the pdstage readers/writers.

The installable zip bundles pdstage inside this package (tools/build_addon.py). When running the add-on
straight from the repository, fall back to the repository's top-level pdstage.
"""
try:
    from .pdstage import dat, collision_build
except ImportError:
    import os
    import sys
    _root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from pdstage import dat, collision_build  # noqa: F401
