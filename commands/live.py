"""Read commands package attributes at call time.

Tests patch names on the package (commands.DUE_PATH and the same kind of
constant). Callers use _live so that patch is the value the function sees.
"""


def _live(name):
    import sys
    pkg = sys.modules.get("commands")
    if pkg is not None and name in vars(pkg):
        return vars(pkg)[name]
    from . import config
    return getattr(config, name)
