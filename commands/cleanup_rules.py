"""Path safety rules shared by cleanup discovery and approval."""
import json
import os
from pathlib import Path
import re

PROTECTED_NAMES = {"voicestudio", "luigi", "highonlife", "dmios", "jarvis"}
DATABASE_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".sqlite-wal", ".sqlite-shm")
ALWAYS_PROTECTED_FILES = {"notestore.sqlite", "omnivoice.db"}
ACTIVE_SUFFIXES = (".download", ".crdownload", ".part", ".partial")


def _key(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def load_protected(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf8"))
        return tuple(Path(p).expanduser() for p in data.get("paths", ()) if isinstance(p, str))
    except (OSError, ValueError, TypeError, AttributeError):
        return ()


def protected_reason(path, home, extra=()):
    path, home = Path(path).resolve(), Path(home).resolve()
    try:
        path.relative_to(home)
    except ValueError:
        return "outside home"
    if path == home:
        return "home folder"
    parts = path.relative_to(home).parts
    if any(any(k in _key(part) for k in PROTECTED_NAMES) for part in parts):
        return "protected name"
    if any(part == ".cache" for part in parts):
        return "Jev model cache"
    if any(part == ".git" for part in parts) or (parts and parts[0] == "Developer"):
        return "developer work"
    for ancestor in (path.parent, *path.parents):
        if ancestor == home.parent:
            break
        if (ancestor / '.git').exists():
            return "developer work"
    if any(part == "Xcode.app" or (part.startswith("Xcode") and part.endswith(".app")) for part in parts):
        return "Xcode"
    if "Xcode" in parts and "UserData" in parts:
        return "Xcode user data"
    if any(_key(part).endswith(tuple(_key(s) for s in ACTIVE_SUFFIXES)) for part in parts):
        return "active download"
    name = path.name.lower()
    if name in ALWAYS_PROTECTED_FILES:
        return "protected database (size only)"
    if name.endswith(DATABASE_SUFFIXES) and "Caches" not in parts:
        return "database (size only)"
    if any(path == root or root in path.parents for root in (home / "Documents/.cos-tmp", home / "Library/Application Support/Hey Jev")):
        return "Jev data"
    roots = [Path(p).expanduser().absolute() for p in extra]
    for root in roots:
        if path == root or root in path.parents:
            return "locally protected"
    return None


def fernando_reason(path, home, uid=None, writable=None):
    path = Path(path)
    try:
        path.absolute().relative_to(Path(home).absolute())
    except ValueError:
        return "Fernando does this: outside the home folder"
    try:
        st = path.stat()
    except OSError:
        return "Fernando does this: needs permission"
    if uid is not None and st.st_uid != uid:
        return "Fernando does this: owned by another user"
    parent_writable = os_access(path.parent) if writable is None else writable
    if not parent_writable:
        return "Fernando does this: parent folder is not writable"
    return None


def os_access(path):
    import os
    return os.access(path, os.W_OK)


def bucket_of(proposal):
    if not getattr(proposal, "deletable", False) or getattr(proposal, "safety", "") == "leave_alone":
        return "left_alone"
    kind = getattr(proposal, "kind", "file")
    if kind == "app":
        return "apps"
    return "safe" if getattr(proposal, "safety", "") == "safe" else "your_call"


def recently_modified(mtime, now):
    return mtime > now - 24 * 60 * 60
