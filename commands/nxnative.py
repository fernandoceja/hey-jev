"""NXNative game ports on this Mac. Mac-only, read-only discovery plus `open`.

nxnative (~/Developer/nxnative) turns a Switch game Fernando owns into a
native Mac app: `scripts/build_ipa_from_nsp.py --platform mac-app` writes a
bundle whose Info.plist has DMTitleID and whose executable is
Contents/MacOS/nxnative; a hand-made wrapper (like /Applications/High On
Life.app) uses a bundle id containing "nxnative" and runs the build's
tools/dmhost. Either way the app is started like any app, so Jev only
discovers bundles and runs ["open", path] (detached, an argument list,
never a shell string).

Nothing here binds or listens, reads the Keychain, writes files, reads keys
or dumps, or touches the bridge. Not in BRIDGE_ALLOW: the iPhone cannot
start a game.
"""
import hashlib
import os
import plistlib
import re
import sys
import time

APP_DIRS = (
    "/Applications", "~/Applications", "~/Games",
    "~/Documents/Fernando Ceja/Emulation",
)
MAX_DEPTH = 3
CACHE_SECONDS = 30.0

NOT_MAC = "Games open on this Mac."
NONE_FOUND = "No NXNative games found yet. Build one with nxnative's --platform mac-app."
LISTING = "Your NXNative games: {names}."
STARTING = "Starting {title}."
MISSING = "I can't find {title} anymore."
FAILED = "I couldn't open {title}."
UNKNOWN = "I don't see a ported game called that."

_LEAD = r"^(?:(?:hey\s+)?jev\b[\s,]*)?(?:(?:please|can\s+you|could\s+you|let'?s|i\s+want\s+to)\s+)*"
_VERB = r"(?:play|open|launch|start|run|load|fire\s+up|boot\s+up)"
_LIST_RE = re.compile(
    r"^(?:(?:list|show)(?:\s+me)?(?:\s+my)?|what(?:'s| are| is)?(?:\s+my)?)\s+"
    r"(?:(?:nx\s*native|switch|ported)\s+)?(?:games|ports)(?:\s+(?:do i have|can i play))?$")


def _norm(text):
    raw = (text or "").lower().replace("\u2019", "'")
    raw = re.sub(r"[^a-z0-9' ]+", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def _strip(text):
    t = re.sub(_LEAD, "", _norm(text))
    return re.sub(r"\s+please$", "", t).strip()


def _key(text):
    return re.sub(r"[^a-z0-9]", "", _norm(text).replace("'", ""))


def read_plist(app):
    try:
        with open(os.path.join(app, "Contents", "Info.plist"), "rb") as f:
            data = plistlib.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def port_info(app, plist_reader=read_plist, exists=os.path.exists):
    """{"title", "title_id", "path", "id"} for an nxnative app bundle, else None."""
    info = plist_reader(app)
    bundle_id = str(info.get("CFBundleIdentifier") or "")
    title_id = str(info.get("DMTitleID") or "")
    is_port = bool(title_id) or "nxnative" in bundle_id.lower() or exists(
        os.path.join(app, "Contents", "MacOS", "nxnative"))
    if not is_port:
        return None
    title = str(info.get("CFBundleDisplayName") or info.get("CFBundleName") or "").strip()
    title = title or os.path.splitext(os.path.basename(app.rstrip("/")))[0]
    return {"id": "nx_" + hashlib.sha1(app.encode("utf-8")).hexdigest()[:10],
            "title": title, "title_id": title_id, "path": app}


def _apps(root, depth, listdir, isdir):
    try:
        names = sorted(listdir(root))
    except OSError:
        return
    for name in names:
        if name.startswith("."):
            continue
        path = os.path.join(root, name)
        if name.endswith(".app"):
            yield path
        elif depth > 0 and isdir(path):
            yield from _apps(path, depth - 1, listdir, isdir)


def scan(dirs=APP_DIRS, listdir=os.listdir, isdir=os.path.isdir,
         plist_reader=read_plist, exists=os.path.exists):
    """Every nxnative port found, sorted by title, one per title."""
    out, seen = [], set()
    for d in dirs:
        root = os.path.expanduser(d)
        for app in _apps(root, MAX_DEPTH, listdir, isdir):
            port = port_info(app, plist_reader, exists)
            if port and port["title"].lower() not in seen:
                seen.add(port["title"].lower())
                out.append(port)
    out.sort(key=lambda p: p["title"].lower())
    return out


_CACHE = {"at": 0.0, "ports": None}


def ports(refresh=False, now=time.monotonic, scanner=scan):
    t = now()
    if refresh or _CACHE["ports"] is None or t - _CACHE["at"] > CACHE_SECONDS:
        try:
            _CACHE["ports"] = scanner()
        except Exception:
            _CACHE["ports"] = []
        _CACHE["at"] = t
    return _CACHE["ports"]


def is_list_phrase(text):
    return bool(_LIST_RE.match(_strip(text)))


def match_port(text, found=None):
    """The port a "play <game>" phrase names, or None. A verb is required."""
    m = re.match(_VERB + r"\s+(?:the\s+)?(?:game\s+)?(.+?)(?:\s+(?:game|on (?:the|my) mac))?$", _strip(text))
    if not m:
        return None
    want = _key(m.group(1))
    if len(want) < 3:
        return None
    for port in (ports() if found is None else found):
        if _key(port["title"]) == want or port["title_id"].lower() == want:
            return port
    return None


def list_ports(platform=None, found=None):
    if (sys.platform if platform is None else platform) != "darwin":
        return NOT_MAC
    found = ports(refresh=True) if found is None else found
    if not found:
        return NONE_FOUND
    return LISTING.format(names=", ".join(p["title"] for p in found))


def launch_port(path, title="", platform=None, exists=os.path.exists, run=None):
    """open the port's app bundle, detached. Returns a short line to show."""
    title = title or os.path.splitext(os.path.basename(path or ""))[0]
    if (sys.platform if platform is None else platform) != "darwin":
        return NOT_MAC
    if not path or not exists(path):
        return MISSING.format(title=title)
    if run is None:
        from .shell import _run as run
    try:
        run(["open", path])
    except Exception:
        return FAILED.format(title=title)
    return STARTING.format(title=title)


def play_from_text(text, platform=None, found=None, exists=os.path.exists, run=None):
    port = match_port(text, found)
    if port is None:
        return UNKNOWN
    return launch_port(port["path"], port["title"], platform=platform, exists=exists, run=run)
