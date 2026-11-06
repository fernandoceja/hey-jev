"""Pure @ picker helpers for the full window, Home and the orb right-click panel. File discovery runs only in the warmer."""
import os
import re
import threading
import time

AT_MAX_ROWS = 8
AT_PER_SECTION = 4
AT_ROW_H = 30.0
AT_PAD = 6.0
AT_GAP = 6.0
AT_RADIUS = 12.0
AT_QUERY_MAX = 40
AT_MIN_W = 300.0
AT_MAX_W = 640.0
NOTICE_TEMPLATE = 'No app or file matches \u201c@{0}\u201d. Press Return again to send as typed.'
FILE_ROOTS = ("~/Desktop", "~/Documents", "~/Downloads")
FILE_DEPTH = 2
FILE_SCAN_CAP = 2000
FILE_TTL = 60.0
PACKAGE_SUFFIXES = (".app", ".bundle", ".photoslibrary", ".musiclibrary", ".fcpbundle",
                    ".imovielibrary", ".pkg", ".framework")
_files = []
_files_at = None
_warm_lock = threading.Lock()


def utf16_len(text):
    return len(text.encode("utf-16-le")) // 2


def py_index(text, utf16_offset):
    used = 0
    for i, char in enumerate(text):
        used += utf16_len(char)
        if used > utf16_offset:
            return i
    return len(text)


def at_query(text, caret):
    caret = max(0, min(int(caret), len(text)))
    start = text.rfind("@", 0, caret)
    if start < 0 or (start and not text[start - 1].isspace()):
        return None
    query = text[start + 1:caret]
    if len(query) > AT_QUERY_MAX or any(c.isspace() for c in query):
        return None
    return start, query


def match_rank(query, name):
    query, name = query.casefold(), name.casefold()
    if name.startswith(query):
        return 0
    if any(part.startswith(query) for part in re.split(r"[\s_.-]+", name)):
        return 1
    return 2 if query in name else None


def app_rows(index):
    rows = {}
    for path in index.values():
        title = os.path.basename(path)
        if title.lower().endswith(".app"):
            title = title[:-4]
        rows.setdefault(title.casefold(), {"kind": "app", "title": title, "subtitle": "App",
                                         "insert": title, "path": path})
    return sorted(rows.values(), key=lambda row: row["title"].casefold())


def scan_files(roots=FILE_ROOTS, depth=FILE_DEPTH, cap=FILE_SCAN_CAP):
    rows, seen = [], 0
    home = os.path.realpath(os.path.expanduser("~"))

    def walk(folder, level):
        nonlocal seen
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if seen >= cap:
                        return
                    seen += 1
                    name = entry.name
                    if name.startswith(".") or any(c in name for c in ('"', '\n', '\r')):
                        continue
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if level < depth and not name.lower().endswith(PACKAGE_SUFFIXES):
                                walk(entry.path, level + 1)
                        elif entry.is_file(follow_symlinks=False):
                            path = os.path.abspath(entry.path)
                            if not path.startswith(home + os.sep):
                                continue
                            relative = os.path.relpath(path, home)
                            rows.append({"kind": "file", "title": name,
                                         "subtitle": os.path.dirname(relative),
                                         "insert": '"~/' + relative + '"', "path": path,
                                         "mtime": entry.stat(follow_symlinks=False).st_mtime})
                    except OSError:
                        continue
        except OSError:
            return

    for root in roots:
        folder = os.path.expanduser(root)
        if not os.path.islink(folder) and depth > 0:
            walk(folder, 1)
    return rows


def warm_files():
    global _files, _files_at
    with _warm_lock:
        now = time.monotonic()
        if _files_at is None or now - _files_at >= FILE_TTL:
            rows = scan_files()
            _files = rows
            _files_at = now


def cached_files():
    return _files


def picker_rows(query, apps, files):
    def matches(rows, file_rows=False):
        ranked = [(match_rank(query, r["title"]), r) for r in rows]
        ranked = [(rank, row) for rank, row in ranked if rank is not None]
        ranked.sort(key=lambda pair: (pair[0], -pair[1].get("mtime", 0), pair[1]["title"].casefold())
                    if file_rows else (pair[0], pair[1]["title"].casefold()))
        return [row for rank, row in ranked]
    apps, files = matches(apps), matches(files, True)
    na, nf = min(AT_PER_SECTION, len(apps)), min(AT_PER_SECTION, len(files))
    na = min(len(apps), AT_MAX_ROWS - nf)
    nf = min(len(files), AT_MAX_ROWS - na)
    return apps[:na] + files[:nf]


def at_tokens(text):
    """Every @token: "@" at index 0 or after whitespace, then 1..AT_QUERY_MAX non-whitespace characters."""
    tokens = []
    for start, char in enumerate(text):
        if char != "@" or (start and not text[start - 1].isspace()):
            continue
        end = start + 1
        while end < len(text) and not text[end].isspace():
            end += 1
        query = text[start + 1:end]
        if 1 <= len(query) <= AT_QUERY_MAX:
            tokens.append((start, end, query))
    return tokens


def token_end(text, start):
    """Index just after the non-whitespace run that starts at an "@"."""
    end = start + 1
    while end < len(text) and not text[end].isspace():
        end += 1
    return end


def is_bulk_insert(old_text, new_text):
    """Paste, dictation or autocomplete: more than one character arrived in one edit."""
    return len(new_text or "") - len(old_text or "") > 1


def submit_decision(text, rows_for, bypass_text):
    """("send", None), ("pick", token) or ("nomatch", token) for the first @token in the line."""
    tokens = at_tokens(text)
    if not tokens or (bypass_text is not None and text == bypass_text):
        return "send", None
    token = tokens[0]
    return ("pick", token) if rows_for(token[2]) else ("nomatch", token)


def insert_pick(text, start, end, row):
    """Replace the whole token text[start:end] with the pick and one space. Returns (text, caret)."""
    inserted = row["insert"] + " "
    return text[:start] + inserted + text[end:], start + len(inserted)


def picker_screen_frame(anchor, row_count, visible, prefer):
    """(x, y, w, h) in screen points, bottom-left origin, for a list beside anchor inside visible."""
    ax, ay, aw, ah = anchor
    vx, vy, vw, vh = visible
    width = max(AT_MIN_W, min(AT_MAX_W, aw))
    height = row_count * AT_ROW_H + 2 * AT_PAD
    x = max(vx, min(ax, vx + vw - width))
    above = ay + ah + AT_GAP
    below = ay - AT_GAP - height
    fits_above = above + height <= vy + vh
    fits_below = below >= vy
    if prefer == "above":
        y = above if fits_above or not fits_below else below
    else:
        y = below if fits_below or not fits_above else above
    return x, y, width, height
