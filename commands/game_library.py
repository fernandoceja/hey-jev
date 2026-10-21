"""Find console games on disk for the Quick Commands menus. Mac-only, read-only.

Scans Fernando's ROM folders plus each emulator's own configured game
folders, and returns clean titles per console. Nothing here launches,
writes, listens, reads the Keychain, or touches the bridge. Launching is
commands.games.launch_rom.
"""
import hashlib
import json
import os
import re
import time
import xml.etree.ElementTree as ET

CONSOLES = ("switch", "wiiu", "gamecube", "melee")
SWITCH_EXTS = (".nsp", ".xci")
WIIU_EXTS = (".wua", ".wux", ".wud")
GC_ONLY_EXTS = (".rvz", ".ciso")    # Dolphin formats; safe anywhere
GC_SHARED_EXTS = (".iso", ".gcm")   # .iso is also PS1/PSP/PS3, so only in GameCube-looking folders
GC_FOLDER_HINT = re.compile(r"gamecube|game cube|dolphin|(^|[^a-z])gc([^a-z]|$)|wii(?! ?u)", re.I)
MELEE_HINT = re.compile(r"melee|GALE01", re.I)
TITLE_ID = re.compile(r"\b(0100[0-9A-Fa-f]{12})\b")
MAX_DEPTH = 5
CACHE_SECONDS = 30.0

ROOTS = (
    "~/Emulation/roms/switch", "~/Emulation/roms/wiiu", "~/Emulation/roms/gc",
    "~/Documents/Fernando Ceja/Emulation", "~/Games/GameCube",
)
RYUJINX_DIR = "~/Library/Application Support/Ryujinx"
DOLPHIN_INI = "~/Library/Application Support/Dolphin/Config/Dolphin.ini"
CEMU_XML = "~/Library/Application Support/Cemu/settings.xml"


def _read(path):
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return ""


def ryujinx_dirs(home_dir=RYUJINX_DIR):
    try:
        dirs = json.loads(_read(os.path.join(home_dir, "Config.json")) or "{}").get("game_dirs") or []
    except ValueError:
        return []
    return [d for d in dirs if isinstance(d, str)]


def dolphin_dirs(ini=DOLPHIN_INI):
    return [m.group(1).strip() for m in re.finditer(r"(?m)^\s*ISOPath\d+\s*=\s*(.+)$", _read(ini))]


def cemu_dirs(xml=CEMU_XML):
    text = _read(xml)
    if not text:
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    return [(e.text or "").strip() for gp in root.iter("GamePaths")
            for e in gp.findall("Entry") if (e.text or "").strip()]


def ryujinx_title(title_id, home_dir=RYUJINX_DIR):
    """Ryujinx's cached name for a title id, or ''."""
    if not title_id:
        return ""
    meta = os.path.join(os.path.expanduser(home_dir), "games", title_id.lower(), "gui", "metadata.json")
    try:
        return str(json.loads(_read(meta) or "{}").get("title") or "").strip()
    except ValueError:
        return ""


def tidy_title(name):
    """'Legend of Zelda, The - Wind Waker (USA) [v0].iso' -> 'The Legend of Zelda - Wind Waker'."""
    base = os.path.basename(name.rstrip("/"))
    stem, ext = os.path.splitext(base)
    if ext.lower() in SWITCH_EXTS + WIIU_EXTS + GC_ONLY_EXTS + GC_SHARED_EXTS + (".rpx",):
        base = stem
    base = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", base)
    base = base.replace("_ ", ": ").replace("_", " ")
    base = re.sub(r"\s+", " ", base).strip(" -.")
    m = re.match(r"^(.+?), (The|A|An)\b(.*)$", base)
    if m:
        base = "{} {}{}".format(m.group(2), m.group(1), m.group(3))
    return base or stem


def _console_for(path, ext):
    ext = ext.lower()
    if ext in SWITCH_EXTS:
        return "switch"
    if ext in WIIU_EXTS or ext == ".rpx":
        return "wiiu"
    if ext in GC_ONLY_EXTS or (ext in GC_SHARED_EXTS and GC_FOLDER_HINT.search(os.path.dirname(path))):
        return "melee" if MELEE_HINT.search(os.path.basename(path)) else "gamecube"
    return ""


def _walk(root, depth=MAX_DEPTH, listdir=os.listdir, isdir=os.path.isdir):
    try:
        names = sorted(listdir(root))
    except OSError:
        return
    for name in names:
        if name.startswith("."):
            continue
        path = os.path.join(root, name)
        if isdir(path):
            if name.endswith(".app"):
                continue
            if depth > 0:
                yield from _walk(path, depth - 1, listdir, isdir)
        else:
            yield path


def default_roots():
    # Emulator-configured folders first, so a duplicate keeps the copy the emulator already uses.
    roots = ryujinx_dirs() + dolphin_dirs() + cemu_dirs() + list(ROOTS)
    out, seen = [], set()
    for r in roots:
        full = os.path.realpath(os.path.expanduser(r))
        if full not in seen:
            seen.add(full)
            out.append(full)
    return out


def item_id(console, path):
    return "game_{}_{}".format(console, hashlib.sha1(path.encode("utf-8")).hexdigest()[:10])


def scan(roots=None, title_lookup=ryujinx_title):
    """{console: [{"id", "title", "path"}]} sorted by title, one entry per title."""
    found = {c: [] for c in CONSOLES}
    seen_paths, seen_titles = set(), {c: set() for c in CONSOLES}
    for root in (default_roots() if roots is None else roots):
        for path in _walk(root):
            real = os.path.realpath(path)
            if real in seen_paths:
                continue
            ext = os.path.splitext(path)[1]
            console = _console_for(path, ext)
            if not console:
                continue
            if ext.lower() == ".rpx":
                code = os.path.dirname(path)
                if os.path.basename(code).lower() != "code":
                    continue
                path = os.path.dirname(code)  # Cemu -g takes the .rpx; title from the game folder
                title = tidy_title(path)
                path = real
            else:
                tid = TITLE_ID.search(os.path.basename(path))
                title = (title_lookup(tid.group(1)) if console == "switch" and tid else "") or tidy_title(path)
            key = title.lower()
            if key in seen_titles[console]:
                continue
            seen_paths.add(real)
            seen_titles[console].add(key)
            found[console].append({"id": item_id(console, real), "title": title, "path": real})
    for c in CONSOLES:
        found[c].sort(key=lambda g: g["title"].lower())
    return found


_CACHE = {"at": 0.0, "games": None}


def library(refresh=False, now=time.monotonic, scanner=scan):
    """Cached scan. The menu calls this each time it opens; a rescan runs at most every CACHE_SECONDS."""
    t = now()
    if refresh or _CACHE["games"] is None or t - _CACHE["at"] > CACHE_SECONDS:
        try:
            _CACHE["games"] = scanner()
        except Exception:
            _CACHE["games"] = {c: [] for c in CONSOLES}
        _CACHE["at"] = t
    return _CACHE["games"]


def find_game(game_id, games=None):
    for console, items in (games if games is not None else library()).items():
        for g in items:
            if g["id"] == game_id:
                return console, g
    return None
