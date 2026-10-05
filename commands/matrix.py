"""Blue pill and red pill: Matrix rain in Terminal, then close that session.

Local Mac commands. They open Terminal and run cmatrix, or close the session
this module started. They do not touch the iPhone bridge, the Keychain, or
the network. Other Terminal windows are left alone. A window that also has
unrelated tabs loses only the Matrix tab.
"""
import os
import re
import shutil

from .shell import _run

MARKER = "Hey Jev Matrix"
INSTALL_LINE = "Fernando, install cmatrix with brew install cmatrix."
CMATRIX_CANDIDATES = ("/opt/homebrew/bin/cmatrix", "/usr/local/bin/cmatrix")
_TTY_RE = re.compile(r"^/dev/tty[a-zA-Z0-9]+$")
_UNSAFE = set("\"'`\n\r$\\;|&<> \t")


def _safe_binary(path):
    """An absolute path with no shell metacharacters, or None."""
    if not path or not str(path).startswith("/"):
        return None
    text = str(path)
    if any(ch in text for ch in _UNSAFE):
        return None
    return text


def _is_exec(path):
    return os.path.isfile(path) and os.access(path, os.X_OK)


def find_cmatrix(which=None, isfile=None):
    """cmatrix on PATH, then the usual Homebrew locations. Else None."""
    check = isfile or _is_exec
    probe = shutil.which if which is None else which
    found = None
    if probe is not None:
        try:
            found = probe("cmatrix")
        except Exception:
            found = None
    safe = _safe_binary(found)
    if safe and check(safe):
        return safe
    for path in CMATRIX_CANDIDATES:
        if check(path) and _safe_binary(path):
            return path
    return None


def _default_shell():
    return _safe_binary(os.environ.get("SHELL")) or "/bin/zsh"


def _id_path(path):
    if path:
        return path
    return os.path.expanduser("~/Library/Application Support/Hey Jev/matrix-window-id")


def _write_id(path, window_id):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(str(int(window_id)))


def _clear_id(path):
    try:
        os.remove(path)
    except OSError:
        pass


def launch_command(binary, shell=None):
    """Run cmatrix by exec, through the user's shell when that path is safe."""
    binary = _safe_binary(binary)
    if not binary:
        raise ValueError("unsafe cmatrix path")
    chosen = _safe_binary(shell) or _default_shell()
    return f"{chosen} -c 'exec {binary}'"


def start_script(binary, shell=None):
    """Open Terminal, fill the screen, and exec cmatrix. Returns the window id.

    The command runs in a new Terminal window under the user's shell (`exec`
    replaces that shell, so no prompt is left). Background color is set on
    this tab only. Full screen is best-effort and does not change the saved
    Terminal profile.
    """
    command = launch_command(binary, shell)
    return f'''tell application "Terminal"
  activate
  set matrixTab to do script "{command}"
  set matrixWindow to window 1
  set wid to id of matrixWindow
  try
    set custom title of matrixTab to "{MARKER}"
  end try
  try
    set background color of matrixTab to {{0, 0, 0}}
    set normal text color of matrixTab to {{0, 65535, 0}}
  end try
  try
    tell application "Finder" to set screenBounds to bounds of window of desktop
    set bounds of matrixWindow to screenBounds
  end try
  try
    set zoomed of matrixWindow to true
  end try
end tell
try
  tell application "System Events" to tell process "Terminal" to set value of attribute "AXFullScreen" of window 1 to true
end try
return wid
'''


def report_script():
    """One row per Terminal tab. Does not launch Terminal when it is not running."""
    return '''tell application "System Events"
  if not (exists process "Terminal") then
    return "absent"
  end if
end tell
set collected to ""
set sep to ASCII character 9
tell application "Terminal"
  repeat with w in windows
    set n to count of tabs of w
    set wid to id of w as text
    repeat with t in tabs of w
      set theTitle to ""
      set theTTY to ""
      set procText to ""
      try
        set rawTitle to custom title of t
        if rawTitle is not missing value then set theTitle to rawTitle as text
      end try
      try
        set rawTTY to tty of t
        if rawTTY is not missing value then set theTTY to rawTTY as text
      end try
      try
        set oldDelims to AppleScript's text item delimiters
        set AppleScript's text item delimiters to ","
        set procText to (processes of t) as text
        set AppleScript's text item delimiters to oldDelims
      end try
      set collected to collected & wid & sep & (n as text) & sep & theTTY & sep & theTitle & sep & procText & linefeed
    end repeat
  end repeat
end tell
return collected
'''


def close_script(window_ids, ttys):
    """Close whole Matrix windows, or only the Matrix tabs in a mixed window.

    This never quits Terminal, so unrelated windows stay open.
    """
    ids = [str(int(item)) for item in window_ids]
    safe_ttys = []
    for tty in ttys:
        if _TTY_RE.match(str(tty)):
            safe_ttys.append(str(tty))
    id_list = ", ".join(ids) if ids else ""
    tty_list = ", ".join('"' + tty + '"' for tty in safe_ttys)
    window_clause = ""
    if id_list:
        window_clause = f"if id of w is in {{{id_list}}} then\n      close w\n    else\n"
    tab_clause = ""
    if tty_list:
        tab_clause = (
            "      repeat with t in tabs of w\n"
            "        try\n"
            f"          if tty of t is in {{{tty_list}}} then close t\n"
            "        end try\n"
            "      end repeat\n"
        )
    if window_clause and tab_clause:
        body = window_clause + tab_clause + "    end if"
    elif window_clause:
        body = f"if id of w is in {{{id_list}}} then close w"
    elif tab_clause:
        body = tab_clause.rstrip("\n")
    else:
        body = ""
    return f'''tell application "System Events"
  if not (exists process "Terminal") then return "absent"
end tell
delay 0.3
tell application "Terminal"
  repeat with w in windows
    {body}
  end repeat
end tell
'''


def parse_report(text):
    """Rows of window id, tab count, tty, custom title, and process names."""
    if text is None:
        return []
    raw = str(text).strip()
    if not raw or raw == "absent":
        return []
    rows = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        try:
            window_id = int(parts[0].strip())
            tab_count = int(parts[1].strip())
        except ValueError:
            continue
        processes = [item.strip() for item in parts[4].split(",") if item.strip()]
        rows.append({
            "window_id": window_id,
            "tab_count": tab_count,
            "tty": parts[2].strip(),
            "title": parts[3].strip(),
            "processes": processes,
        })
    return rows


def _tty_key(tty):
    text = str(tty or "").strip()
    if not text or text in {"-", "??"}:
        return ""
    return text.rsplit("/", 1)[-1]


def _process_is_cmatrix(name):
    return str(name or "").strip().rsplit("/", 1)[-1] == "cmatrix"


def _ps_cmatrix(ps_text):
    """tty key -> pids, from `ps -ax -o pid=,tty=,comm=`."""
    found = {}
    for line in str(ps_text or "").splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3 or not _process_is_cmatrix(parts[2]):
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        key = _tty_key(parts[1])
        if key:
            found.setdefault(key, []).append(pid)
    return found


def _is_matrix_tab(row):
    if row.get("title") == MARKER:
        return True
    if row.get("ps_cmatrix"):
        return True
    return any(_process_is_cmatrix(name) for name in row.get("processes") or [])


def plan_close(rows, ps_text=""):
    """Which windows, tabs, and cmatrix pids the red pill may touch.

    A window is closed only when every tab in it is a Matrix tab. Otherwise
    only those tabs are closed. Tabs that are neither titled by Jev nor
    running cmatrix are not included.
    """
    tty_pids = _ps_cmatrix(ps_text)
    grouped = {}
    order = []
    for row in rows:
        key = _tty_key(row.get("tty"))
        pids = list(tty_pids.get(key, []))
        noted = dict(row)
        noted["pids"] = pids
        if pids:
            noted["ps_cmatrix"] = True
        wid = noted["window_id"]
        if wid not in grouped:
            order.append(wid)
            grouped[wid] = []
        grouped[wid].append(noted)
    close_windows = []
    close_ttys = []
    pids = []
    for wid in order:
        tabs = grouped[wid]
        matrix = [tab for tab in tabs if _is_matrix_tab(tab)]
        if not matrix:
            continue
        for tab in matrix:
            pids.extend(tab["pids"])
        if len(matrix) == len(tabs):
            close_windows.append(wid)
        else:
            for tab in matrix:
                if _TTY_RE.match(tab.get("tty") or ""):
                    close_ttys.append(tab["tty"])
    unique_pids = []
    for pid in pids:
        if pid not in unique_pids:
            unique_pids.append(pid)
    return {
        "running": bool(close_windows or close_ttys or unique_pids),
        "close_windows": close_windows,
        "close_ttys": close_ttys,
        "pids": unique_pids,
    }


def _parse_window_id(text):
    match = re.search(r"\d+", str(text or ""))
    if not match:
        return None
    return int(match.group(0))


def start_matrix(runner=None, which=None, isfile=None, shell=None, id_path=None):
    """Open the Matrix. If cmatrix is missing, say so and do not open Terminal."""
    binary = find_cmatrix(which=which, isfile=isfile)
    if not binary:
        return INSTALL_LINE
    run = runner or _run
    try:
        out = run(("osascript", "-e", start_script(binary, shell)))
    except Exception:
        return "I couldn't open Terminal for the matrix."
    wid = _parse_window_id(out)
    if wid is not None:
        try:
            _write_id(_id_path(id_path), wid)
        except OSError:
            pass
    return "Matrix is on."


def stop_matrix(runner=None, id_path=None):
    """Quit cmatrix and close the Terminal session Jev opened for it."""
    run = runner or _run
    path = _id_path(id_path)
    try:
        report = run(("osascript", "-e", report_script()))
    except Exception:
        report = "absent"
    rows = parse_report(report)
    ps_text = ""
    if rows:
        try:
            ps_text = run(("ps", "-ax", "-o", "pid=,tty=,comm="))
        except Exception:
            ps_text = ""
    plan = plan_close(rows, ps_text)
    if not plan["running"]:
        _clear_id(path)
        return "The matrix isn't running."
    if plan["pids"]:
        try:
            run(["kill", "-INT"] + [str(pid) for pid in plan["pids"]])
        except Exception:
            pass
    if plan["close_windows"] or plan["close_ttys"]:
        try:
            run(("osascript", "-e", close_script(plan["close_windows"], plan["close_ttys"])))
        except Exception:
            return "I couldn't close the Matrix window."
    _clear_id(path)
    return "Matrix is off."
