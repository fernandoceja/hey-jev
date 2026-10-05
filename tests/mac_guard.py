"""Block tests from touching a real Mac display, Terminal, or system preferences.

Production brightness code catches OSError and Exception and then tries the
next backend. A guard that raised either of those would be treated as a
missing tool and the test would continue into a real ``brightness`` write or
key code. RealHardwareCall is a BaseException so it always fails the test.
"""
import ctypes
import os
import subprocess

_FRAMEWORK_MARKERS = (
    "displayservices",
    "coredisplay",
    "coregraphics",
    "corebrightness",
    "iokit",
    "applicationservices",
    "skylight",
    "quartz",
    "accessibility",
    "privateframeworks",
    "/system/library/frameworks",
    "brightness",
)

_PROCESS_STARTERS = (
    "system",
    "popen",
    "execl",
    "execle",
    "execlp",
    "execlpe",
    "execv",
    "execve",
    "execvp",
    "execvpe",
    "spawnl",
    "spawnle",
    "spawnlp",
    "spawnlpe",
    "spawnv",
    "spawnve",
    "spawnvp",
    "spawnvpe",
    "posix_spawn",
    "posix_spawnp",
)


class RealHardwareCall(BaseException):
    """A test reached a real Mac command or display framework."""

    def __init__(self, detail):
        super().__init__("test tried to touch the Mac: {0}. Stub the call.".format(detail))


def _describe(args):
    if isinstance(args, (str, bytes)):
        return str(args)
    try:
        return " ".join(str(part) for part in args)
    except TypeError:
        return repr(args)


def _framework_path(name):
    if not name:
        return False
    text = os.fsdecode(name).lower() if isinstance(name, (str, bytes)) else str(name).lower()
    return any(marker in text for marker in _FRAMEWORK_MARKERS)


def _refuse(label):
    def blocked(*args, **kwargs):
        detail = args[0] if args else label
        if not isinstance(detail, str):
            detail = _describe(detail)
        raise RealHardwareCall(detail)

    blocked._mac_guard = True
    blocked.__name__ = "blocked_{0}".format(label)
    return blocked


def _guard_loader(real):
    def load(name, *args, **kwargs):
        if _framework_path(name):
            raise RealHardwareCall("ctypes load {0}".format(name))
        return real(name, *args, **kwargs)

    load._mac_guard = True
    load.__name__ = "guarded_{0}".format(getattr(real, "__name__", "cdll"))
    return load


def install(monkeypatch):
    """Replace process and display-framework entry points for one test."""
    for name in ("run", "call", "check_call", "check_output", "getoutput", "getstatusoutput"):
        if hasattr(subprocess, name):
            monkeypatch.setattr(subprocess, name, _refuse(name))
    monkeypatch.setattr(subprocess, "Popen", _refuse("Popen"))
    for name in _PROCESS_STARTERS:
        if hasattr(os, name):
            monkeypatch.setattr(os, name, _refuse(name))
    for cls_name in ("CDLL", "PyDLL", "WinDLL"):
        real = getattr(ctypes, cls_name, None)
        if real is None:
            continue
        monkeypatch.setattr(ctypes, cls_name, _guard_loader(real))
    for loader_name in ("cdll", "pydll", "windll"):
        loader = getattr(ctypes, loader_name, None)
        if loader is None or not hasattr(loader, "LoadLibrary"):
            continue
        monkeypatch.setattr(loader, "LoadLibrary", _guard_loader(loader.LoadLibrary))
