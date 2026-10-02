"""Shortcuts verified in the Jev folder, plus focus and Princess Academy."""
import difflib
import re
import subprocess
import time
from .config import FOCUS_OFF_NAME, FOCUS_ON_NAME, FUZZY_CUTOFF, PRINCESS_SHORTCUT, SHORTCUT_CACHE_SECONDS, SHORTCUT_FOLDER, _BARE_RUN_RE
from .textutil import _clean, _norm, _spoken_span
from .shell import _run
from .system import _open_in_chrome
from .live import _live

_UUID_RE = re.compile(
    r"^(?P<name>.*?)\s+\((?P<id>[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})\)$"
)
_shortcut_cache = {"at": 0.0, "catalog": None, "valid": False}


def run_jev_folder_shortcut(name):
    """Run one shortcut by its real name, if it is verified in the Jev folder.

    Returns None on success, or a sentence describing why it did not run.
    The process is started by identifier, never by a name that might exist outside the folder.
    """
    ok, info = _run_catalog_shortcut(name)
    if ok:
        return None
    if info and info.startswith("I couldn't find"):
        return f"Add a shortcut named {name} to the Jev folder."
    return info


def begin_focus(seconds, arm):
    """Run 'Jev Focus On' and arm a timer. arm(seconds) is called only on success."""
    problem = run_jev_folder_shortcut(FOCUS_ON_NAME)
    if problem:
        return problem
    try:
        arm(int(seconds))
    except Exception:
        return "Focus is on, but I couldn't start the timer."
    return f"Focus is on for {_spoken_span(seconds)}."


def finish_focus():
    """Run 'Jev Focus Off' and return the line to announce."""
    problem = run_jev_folder_shortcut(FOCUS_OFF_NAME)
    if problem:
        return "Focus time is up. " + problem
    return "Focus is off."


def open_princess_academy():
    ok, info = _run_catalog_shortcut(PRINCESS_SHORTCUT)
    if ok:
        return f"Ran {info}."
    if _live("PRINCESS_ACADEMY_URL"):
        opened = _open_in_chrome(_live("PRINCESS_ACADEMY_URL"), "Opening Princess Academy.")
        if info and "couldn't verify" in info:
            return "I didn't run a shortcut. " + opened
        return opened
    if info and "couldn't verify" in info:
        return info
    return (
        "Zoe's Princess Academy isn't in the Jev folder. "
        "Add that shortcut, or set PRINCESS_ACADEMY_URL in commands.py."
    )


# --------------------------------------------------------------------------- Shortcuts (Jev folder only)
def parse_shortcut_name(text):
    """Name from 'run shortcut Leaving for work', 'run my Focus shortcut', 'do Jev morning'."""
    raw = _clean(text).strip()
    patterns = (
        r"\b(?:run|start|trigger)\s+(?:my\s+)?(?:the\s+)?shortcut(?:\s+named|\s+called)?\s+(.+)$",
        r"\b(?:run|start|do)\s+my\s+(.+?)\s+shortcut\s*$",
        r"\bdo\s+jev\s+(.+)$",
    )
    name = None
    for pattern in patterns:
        match = re.search(pattern, raw, re.I)
        if match:
            name = match.group(1).strip(" .,!?")
            break
    if not name:
        return None
    # "run shortcut Morning and open Notes" — the shortcut name stops at the join.
    name = re.split(r"\s+(?:and|then)\b", name, maxsplit=1, flags=re.I)[0]
    name = re.sub(r"\s+shortcut$", "", name, flags=re.I).strip(" .,!?")
    if not name or re.fullmatch(r"jev", name, re.I):
        return None
    return name


def spoken_shortcut_from(text):
    """Explicit shortcut phrase, or the name in a bare 'run NAME'."""
    name = parse_shortcut_name(text)
    if name:
        return name
    match = _BARE_RUN_RE.match(_clean(text).strip())
    if not match:
        return None
    spoken = re.sub(r"^(?:the|my|a)\s+", "", match.group(1).strip(" .,!?"), flags=re.I).strip()
    if not spoken or re.search(r"\bshortcut\b", spoken, re.I):
        return None
    return spoken


def clear_shortcut_cache():
    _shortcut_cache.update(at=0.0, catalog=None, valid=False)


def _shortcuts_output(*args):
    """stdout of `shortcuts list`, or None when the command fails. Argument list only."""
    try:
        result = subprocess.run(
            ["shortcuts", "list", *args],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    return result.stdout


def _parse_id_line(line):
    """(identifier or None, name) for one shortcuts-list line, or None if blank."""
    line = (line or "").strip()
    if not line:
        return None
    match = _UUID_RE.match(line)
    if match:
        name = match.group("name").strip()
        if not name:
            return None
        return match.group("id").upper(), name
    return None, line


def parse_shortcut_ids(stdout):
    """({identifier: name}, count of lines with no identifier). None if stdout is None."""
    if stdout is None:
        return None
    items, unidentified = {}, 0
    for line in stdout.splitlines():
        parsed = _parse_id_line(line)
        if parsed is None:
            continue
        ident, name = parsed
        if ident:
            items[ident] = name
        elif name:
            unidentified += 1
    return items, unidentified


def parse_folder_rows(stdout):
    """(identifier or None, name) rows. None when the command failed."""
    if stdout is None:
        return None
    rows = []
    for line in stdout.splitlines():
        parsed = _parse_id_line(line)
        if parsed is None:
            continue
        ident, name = parsed
        if name:
            rows.append((ident, name))
    return rows


def find_jev_folder(rows):
    """(identifier or None, actual name) for the Jev folder, or None if it is absent."""
    if not rows:
        return None
    for ident, name in rows:
        if name.lower() == SHORTCUT_FOLDER.lower():
            return ident, name
    return None


def catalog_from_listings(folders_out, name_out, id_out, all_out):
    """{identifier: name} verified in the Jev folder, {} if that folder is empty, or None.

    `shortcuts list --folder-name Jev` prints every shortcut when the folder does
    not exist, and it still exits 0. A folder-name listing is ignored unless
    `shortcuts list --folders` contains Jev. When the folder has an identifier,
    a name filter that dumped the whole library is discarded in favor of the
    identifier filter, if that one is a real subset.
    """
    folders = parse_folder_rows(folders_out)
    if folders is None:
        return None
    found = find_jev_folder(folders)
    if not found:
        return None
    folder_ident, _folder_name = found
    named = parse_shortcut_ids(name_out)
    everyone = parse_shortcut_ids(all_out)
    if named is None or everyone is None:
        return None
    name_items, name_bad = named
    all_items, _all_bad = everyone
    if name_bad and not name_items:
        return None
    if not set(name_items).issubset(all_items):
        return None
    chosen = name_items
    if folder_ident:
        identified = parse_shortcut_ids(id_out)
        if identified is None:
            # The identifier-scoped list failed. A name list that is the entire
            # library is the missing-folder bug, so refuse it. A real subset is kept.
            if all_items and set(name_items) == set(all_items):
                return None
            return dict(name_items)
        id_items, id_bad = identified
        if id_bad and not id_items and (id_out or "").strip():
            return None
        if not set(id_items).issubset(all_items):
            return None
        name_is_all = bool(all_items) and set(name_items) == set(all_items)
        id_is_all = bool(all_items) and set(id_items) == set(all_items)
        if name_is_all and not id_is_all:
            chosen = id_items
        elif id_is_all and not name_is_all:
            chosen = name_items
        elif set(name_items) != set(id_items):
            both = set(name_items) & set(id_items)
            if not both and (name_items or id_items):
                return None
            chosen = {ident: id_items.get(ident) or name_items[ident] for ident in both}
        else:
            chosen = id_items
    return dict(chosen)


def _load_shortcut_catalog():
    folders_out = _shortcuts_output("--folders", "--show-identifiers")
    if folders_out is None:
        folders_out = _shortcuts_output("--folders")
    folders = parse_folder_rows(folders_out)
    if folders is None:
        return None
    found = find_jev_folder(folders)
    if not found:
        # Do not read --folder-name. That flag lists the whole library when Jev is missing.
        return None
    folder_ident, folder_name = found
    name_out = _shortcuts_output("--folder-name", folder_name, "--show-identifiers")
    all_out = _shortcuts_output("--show-identifiers")
    id_out = _shortcuts_output("--folder-name", folder_ident, "--show-identifiers") if folder_ident else None
    return catalog_from_listings(folders_out, name_out, id_out, all_out)


def jev_shortcut_catalog(force=False):
    """Verified {identifier: name}, {} when the folder is empty, or None when it can't be verified."""
    now = time.time()
    if not force and _shortcut_cache["valid"] and now - _shortcut_cache["at"] < SHORTCUT_CACHE_SECONDS:
        return _shortcut_cache["catalog"]
    catalog = _load_shortcut_catalog()
    _shortcut_cache.update(at=now, catalog=catalog, valid=True)
    return catalog


def list_jev_shortcuts():
    """Verified shortcut names in the Jev folder. None when the folder can't be verified."""
    catalog = jev_shortcut_catalog()
    if catalog is None:
        return None
    return list(catalog.values())


def resolve_shortcut(spoken, names):
    """Fuzzy-match a spoken name against the Jev folder only. Returns the canonical name."""
    if not spoken or not names:
        return None
    for name in names:
        if name.lower() == spoken.lower():
            return name
    by_key = {}
    for name in names:
        by_key.setdefault(_norm(name), name)
    wanted = _norm(spoken)
    if wanted in by_key:
        return by_key[wanted]
    if len(wanted) < 3:
        return None
    match = difflib.get_close_matches(wanted, list(by_key.keys()), n=1, cutoff=FUZZY_CUTOFF)
    return by_key[match[0]] if match else None


def _ident_for_name(catalog, name):
    hits = [ident for ident, title in catalog.items() if title == name]
    if len(hits) != 1:
        return None
    return hits[0]


def _run_catalog_shortcut(spoken):
    """(True, canonical name) or (False, spoken reason). Runs by identifier only."""
    catalog = jev_shortcut_catalog()
    if catalog is None:
        return False, "I only run shortcuts in the Jev folder, and I couldn't verify that folder, so I didn't run anything."
    if not catalog:
        return False, "The Jev shortcuts folder is empty."
    name = resolve_shortcut(spoken, list(catalog.values()))
    if not name:
        return False, f"I couldn't find {spoken} in the Jev shortcuts folder."
    ident = _ident_for_name(catalog, name)
    if not ident:
        return False, f"I couldn't verify {spoken} is in the Jev folder, so I didn't run it."
    try:
        _run(("shortcuts", "run", ident), timeout=120)
    except subprocess.TimeoutExpired:
        return False, f"{name} took too long, so I stopped waiting."
    except RuntimeError:
        return False, f"I couldn't run {name}."
    return True, name


def run_named_shortcut(text):
    """Run one shortcut verified in the Jev folder. Anything else is refused."""
    spoken = spoken_shortcut_from(text)
    if not spoken:
        return "Which shortcut should I run?"
    ok, info = _run_catalog_shortcut(spoken)
    if ok:
        return f"Ran {info}."
    return info
