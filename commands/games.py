"""Launch game ports on this Mac. Mac-only.

GAMES is a small data map: a spoken name, aliases Jev listens for, and the
app bundles to try in order. The first bundle that exists is opened with
["open", path], an argument list, never a shell string.

Not in BRIDGE_ALLOW, so the iPhone bridge cannot start a game. Nothing here
binds or listens, reads the Keychain, or touches the bridge.
"""
import os
import re
import sys
import time

from .shell import _run

DOLPHIN_APPS = ("/Applications/Dolphin.app", "~/Applications/Dolphin.app")
DOLPHIN_BUNDLE_ID = "org.dolphin-emu.dolphin"
GAMECUBE_DIR = "~/Games/GameCube"


def dolphin_game(game_id, name, rom, aliases, bare_ok=()):
    """A GameCube game opened by Dolphin. Add one line per new game.

    rom is a file name inside GAMECUBE_DIR (or an absolute/~ path). It is
    launched as ["open", "-a", Dolphin.app, "--args", "-e", rom].
    """
    path = rom if rom.startswith(("/", "~")) else GAMECUBE_DIR + "/" + rom
    return {
        "id": game_id,
        "name": name,
        "aliases": tuple(aliases),
        "needs_verb": tuple(a for a in aliases if a not in bare_ok and len(a.split()) == 1),
        "apps": DOLPHIN_APPS,
        "rom": path,
        "bundle_id": DOLPHIN_BUNDLE_ID,
        "process": "Dolphin",
    }


DOLPHIN_GAMES = (
    dolphin_game(
        "sunshine", "Super Mario Sunshine", "Super Mario Sunshine (USA, Canada).ciso",
        ("super mario sunshine", "mario sunshine", "the mario sunshine",
         "super mario sunshine gamecube", "mario sunshine gamecube"),
    ),
)

GAMES = (
    {
        "id": "ocarina",
        "name": "Ocarina of Time",
        "aliases": (
            "zelda", "the zelda", "zelda ocarina", "zelda ocarina of time",
            "ocarina of time", "ocarina", "the ocarina of time",
            "ship of harkinian", "ship of harkin", "ship of harkinnian",
            "ship of harkenian", "soh",
        ),
        "apps": ("~/Applications/soh.app", "/Applications/soh.app"),
        "bundle_id": "com.shipofharkinian.ShipOfHarkinian",
        "process": "soh",
    },
    {
        "id": "majora",
        "name": "Majora's Mask",
        "aliases": (
            "majora's mask", "majoras mask", "majora mask", "majora",
            "zelda majora's mask", "zelda majoras mask",
            "2 ship", "two ship", "2 ship 2 harkinian", "two ship two harkinian",
            "2s2h",
        ),
        "apps": ("~/Applications/2s2h.app", "/Applications/2s2h.app"),
        "bundle_id": "com.2ship2harkinian.2s2h",
        "process": "2s2h",
    },
) + DOLPHIN_GAMES


def emulator(emu_id, name, app, bundle_id, process, aliases):
    """A whole console emulator. Every alias needs a verb ("play switch"),
    so a bare "switch" or "smash" in conversation never opens anything.
    Closing is an AppleScript quit only, never a forced kill, so a save
    prompt is never lost.
    """
    return {
        "id": emu_id,
        "name": name,
        "aliases": tuple(aliases),
        "needs_verb": tuple(aliases),
        "apps": (app, "~" + app),
        "bundle_id": bundle_id,
        "process": process,
        "graceful_only": True,
        "emulator": True,
    }


# Bundle names, ids, and executables checked on Fernando's Mac.
EMULATORS = (
    emulator(
        "switch", "the Switch", "/Applications/Ryujinx.app",
        "org.ryujinx.Ryujinx", "Ryujinx",
        ("switch", "the switch", "my switch", "nintendo switch", "the nintendo switch",
         "switch games", "swich", "swiss", "twitch switch"),
    ),
    emulator(
        "wiiu", "the Wii U", "/Applications/Cemu.app", "info.cemu.Cemu", "Cemu",
        ("wii u", "wiiu", "the wii u", "nintendo wii u", "we you", "wee you", "we u",
         "wii you", "we yu", "wee u", "the we you", "wi u", "why you"),
    ),
    emulator(
        "gamecube", "the GameCube", "/Applications/Dolphin.app",
        DOLPHIN_BUNDLE_ID, "Dolphin",
        ("gamecube", "game cube", "the gamecube", "the game cube", "nintendo gamecube",
         "nintendo game cube", "game q", "gamecubes", "game cubes"),
    ),
)

GAMES = GAMES + EMULATORS
OPENING_EMULATOR = "Firing up {name}. Have fun!"
EMULATOR_NOT_INSTALLED = "{name} emulator isn't installed on this Mac."
CLOSING_EMULATOR = "Okay, turning off {name}."
EMULATOR_STILL_OPEN = "I asked {name} to quit, but it's still open. It may be waiting on you to save."

GAMES_NOT_MAC = "Games open on this Mac."
GAME_FAILED = "I couldn't open {name}."
OPENING_GAME = "Opening {name}."
GAME_NOT_INSTALLED = "{name} isn't installed yet."
GAME_UNKNOWN = "I don't know that game yet."

_VERB = r"(?:play|open|launch|start|run|load|turn\s+on|fire\s+up|boot\s+up)"
_LEAD = r"^(?:(?:hey\s+)?jev\b[\s,]*)?(?:(?:please|can\s+you|could\s+you|let'?s|i\s+want\s+to)\s+)*"


def _norm(text):
    raw = (text or "").lower().replace("\u2019", "'")
    raw = re.sub(r"[^a-z0-9' ]+", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def _strip(text):
    t = _norm(text)
    t = re.sub(_LEAD, "", t)
    t = re.sub(r"\s+please$", "", t)
    return t.strip()


def match_game(text):
    """The GAMES entry a phrase asks for, or None.

    A bare title ("ocarina of time") or a verb plus title ("play zelda").
    """
    t = _strip(text)
    if not t:
        return None
    m = re.match(_VERB + r"\s+(?:the\s+)?(?:game\s+(?!cubes?$|q$))?(.+)$", t)
    body = m.group(1).strip() if m else t
    body = re.sub(r"\s+(?:game|on (?:the|my) mac)$", "", body).strip()
    for game in GAMES:
        for alias in game["aliases"]:
            if body == _norm(alias):
                # A bare "zelda"/"ocarina"/"majora"/"soh" needs a verb.
                if not m and (alias in ("zelda", "the zelda", "ocarina", "majora", "soh", "2s2h")
                              or alias in game.get("needs_verb", ())):
                    continue
                return game
    return None


def is_game_phrase(text):
    return match_game(text) is not None


def game_app_path(game, exists=os.path.exists):
    for raw in game.get("apps", ()):
        path = os.path.abspath(os.path.expanduser(raw))
        if path.startswith("/") and exists(path):
            return path
    return ""


def open_game(game, platform=None, exists=os.path.exists):
    name = game["name"]
    if (sys.platform if platform is None else platform) != "darwin":
        return GAMES_NOT_MAC
    path = game_app_path(game, exists)
    if not path:
        if game.get("emulator"):
            return _cap(EMULATOR_NOT_INSTALLED.format(name=name))
        return GAME_NOT_INSTALLED.format(name=name)
    argv = ["open", path]
    if game.get("rom"):
        rom = os.path.abspath(os.path.expanduser(game["rom"]))
        if not exists(rom):
            return GAME_NOT_INSTALLED.format(name=name)
        argv = ["open", "-a", path, "--args", "-e", rom]
    try:
        _run(argv)
    except Exception:
        return GAME_FAILED.format(name=name)
    if game.get("emulator"):
        return OPENING_EMULATOR.format(name=name)
    return OPENING_GAME.format(name=name)


def _cap(line):
    return line[:1].upper() + line[1:]


def open_game_from_text(text, platform=None, exists=os.path.exists):
    game = match_game(text)
    if game is None:
        return GAME_UNKNOWN
    return open_game(game, platform=platform, exists=exists)


CLOSING_GAME = "Closing {name}."
GAME_NOT_RUNNING = "{name} isn't running."
GAME_CLOSE_FAILED = "I couldn't close {name}."
_CLOSE_VERB = r"(?:close|quit|exit|stop|kill|end|turn\s+off|shut\s+down|shut\s+off)"


def match_game_close(text):
    """The GAMES entry a close phrase names ("close zelda"), or None."""
    t = _strip(text)
    m = re.match(_CLOSE_VERB + r"\s+(?:out\s+of\s+)?(?:the\s+)?(?:game\s+(?!cubes?$|q$))?(.+)$", t)
    if not m:
        return None
    body = re.sub(r"\s+(?:game|app)$", "", m.group(1).strip()).strip()
    for game in GAMES:
        for alias in game["aliases"]:
            if body == _norm(alias):
                return game
    return None


def is_game_close_phrase(text):
    return match_game_close(text) is not None


def _is_running(process):
    try:
        _run(["pgrep", "-x", process])
        return True
    except Exception:
        return False


CLOSE_WAIT_SECONDS = 5.0
_POLL_SECONDS = 0.25


def _wait_gone(process, check, sleep, wait):
    """True once the process is gone, polling up to wait seconds."""
    steps = max(1, int(wait / _POLL_SECONDS))
    for _ in range(steps):
        if not check(process):
            return True
        sleep(_POLL_SECONDS)
    return not check(process)


def close_game(game, platform=None, running=None, sleep=None, wait=CLOSE_WAIT_SECONDS):
    """Quit by bundle id via osascript, then poll for the process to exit.

    Some apps (Dolphin) return -128 "User canceled" from a clean quit, so the
    osascript return code is ignored: if the process is gone, it closed. If it
    is still running after the wait, fall back to pkill -x and re-check.
    """
    name = game["name"]
    if (sys.platform if platform is None else platform) != "darwin":
        return GAMES_NOT_MAC
    check = running or _is_running
    nap = sleep or time.sleep
    process = game.get("process", "")
    if not process or not check(process):
        return _cap(GAME_NOT_RUNNING.format(name=name))
    bundle = game.get("bundle_id", "")
    if bundle:
        try:
            _run(["osascript", "-e", 'tell application id "{0}" to quit'.format(bundle)], timeout=10)
        except Exception:
            pass  # e.g. -128 on a clean quit; the poll below decides.
        if _wait_gone(process, check, nap, wait):
            if game.get("emulator"):
                return CLOSING_EMULATOR.format(name=name)
            return CLOSING_GAME.format(name=name)
    if game.get("graceful_only"):
        return EMULATOR_STILL_OPEN.format(name=name)
    try:
        _run(["pkill", "-x", process])
    except Exception:
        pass
    if _wait_gone(process, check, nap, 2.0):
        return CLOSING_GAME.format(name=name)
    return GAME_CLOSE_FAILED.format(name=name)


def close_game_from_text(text, platform=None, running=None, sleep=None, wait=CLOSE_WAIT_SECONDS):
    game = match_game_close(text)
    if game is None:
        return GAME_UNKNOWN
    return close_game(game, platform=platform, running=running, sleep=sleep, wait=wait)


# Quick Commands game rows. Each console's emulator gets the ROM path as an
# argument list (never a shell string).
ROM_ARGS = {"switch": (), "wiiu": ("-g",), "gamecube": ("-e",)}
LAUNCHING_ROM = "Starting {title}."
ROM_MISSING = "I can't find {title} anymore."


def emulator_for(console):
    for game in EMULATORS:
        if game["id"] == console:
            return game
    return None


def launch_rom(console, path, title="", platform=None, exists=os.path.exists, run=None):
    """Open one scanned game in its console's emulator. Returns a short line to show."""
    run = run or _run
    title = title or os.path.basename(path)
    if (sys.platform if platform is None else platform) != "darwin":
        return GAMES_NOT_MAC
    if console == "nxnative":
        from .nxnative import launch_port
        return launch_port(path, title, platform=platform, exists=exists, run=run)
    emu = emulator_for(console)
    if emu is None:
        return GAME_UNKNOWN
    app = game_app_path(emu, exists)
    if not app:
        return _cap(EMULATOR_NOT_INSTALLED.format(name=emu["name"]))
    if not path or not exists(path):
        return ROM_MISSING.format(title=title)
    argv = ["open", "-a", app, "--args"] + list(ROM_ARGS[console]) + [path]
    try:
        run(argv)
    except Exception:
        return GAME_FAILED.format(name=title)
    return LAUNCHING_ROM.format(title=title)
