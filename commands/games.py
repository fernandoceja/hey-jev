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

from .shell import _run

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
    },
)

GAMES_NOT_MAC = "Games open on this Mac."
GAME_FAILED = "I couldn't open {name}."
OPENING_GAME = "Opening {name}."
GAME_NOT_INSTALLED = "{name} isn't installed yet."
GAME_UNKNOWN = "I don't know that game yet."

_VERB = r"(?:play|open|launch|start|run|load)"
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
    m = re.match(_VERB + r"\s+(?:the\s+)?(?:game\s+)?(.+)$", t)
    body = m.group(1).strip() if m else t
    body = re.sub(r"\s+(?:game|on (?:the|my) mac)$", "", body).strip()
    for game in GAMES:
        for alias in game["aliases"]:
            if body == _norm(alias):
                # A bare "zelda"/"ocarina"/"majora"/"soh" needs a verb.
                if not m and alias in ("zelda", "the zelda", "ocarina", "majora", "soh", "2s2h"):
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
        return GAME_NOT_INSTALLED.format(name=name)
    try:
        _run(["open", path])
    except Exception:
        return GAME_FAILED.format(name=name)
    return OPENING_GAME.format(name=name)


def open_game_from_text(text, platform=None, exists=os.path.exists):
    game = match_game(text)
    if game is None:
        return GAME_UNKNOWN
    return open_game(game, platform=platform, exists=exists)
