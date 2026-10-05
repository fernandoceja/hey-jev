"""Blue pill and red pill: Matrix rain in Terminal, then close that session.

Local Mac commands. They open Terminal and run cmatrix, or close the session
this module started. They do not touch the iPhone bridge, the Keychain, or
the network. If Jev had to launch Terminal and no other work remains, red
pill quits Terminal. If Terminal was already open, only the Matrix window is
closed, or only the Matrix tab when that window has other tabs.
"""
import os
import re
import shutil
import subprocess

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


def _state_paths(id_path):
    """Window-id file and the sibling that records whether Jev launched Terminal."""
    path = _id_path(id_path)
    folder = os.path.dirname(path)
    launched = os.path.join(folder, "matrix-terminal-launched") if folder else "matrix-terminal-launched"
    return path, launched


def _write_launched(path):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("1")


def _read_launched(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip() == "1"
    except OSError:
        return False


def _log(message):
    """Jev's log, not her voice. Failure reasons stay off the spoken line."""
    print(f"  matrix: {message}", flush=True)


def _run_logged(args, timeout=30):
    """Same contract as shell._run, and osascript stderr is written to the log."""
    result = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
    err = (result.stderr or "").strip()
    if err:
        _log(err)
    if result.returncode:
        detail = err or (result.stdout or "").strip() or "command failed"
        raise RuntimeError(detail)
    return result.stdout


def launch_command(binary, shell=None):
    """Run cmatrix by exec, through the user's shell when that path is safe."""
    binary = _safe_binary(binary)
    if not binary:
        raise ValueError("unsafe cmatrix path")
    chosen = _safe_binary(shell) or _default_shell()
    return f"{chosen} -c 'exec {binary}'"


def terminal_running_script():
    """Whether Terminal is already open. System Events only, so this does not launch it."""
    return '''tell application "System Events"
  if exists process "Terminal" then
    return "running"
  end if
end tell
return "absent"
'''


def start_script(binary, shell=None, reuse_startup=False):
    """Open Terminal, enter native full screen, and exec cmatrix.

    Returns ``id:<n>`` and ``screen:ok`` (or a screen note when full screen
    had to fall back to Control-Command-F). When Jev launched Terminal,
    cmatrix runs in the idle startup tab and any extra blank window is
    closed. An already-open Terminal gets a new window; other windows stay.
    """
    command = launch_command(binary, shell)
    if reuse_startup:
        open_lines = f'''  activate
  delay 0.4
  set matrixTab to missing value
  if (count of windows) > 0 then
    try
      if busy of selected tab of window 1 is false then
        set matrixTab to do script "{command}" in selected tab of window 1
      end if
    end try
  end if
  if matrixTab is missing value then
    set matrixTab to do script "{command}"
  end if
  set matrixWindow to window 1
  set wid to id of matrixWindow
  set extraIds to {{}}
  repeat with w in windows
    try
      set extraIds to extraIds & (id of w)
    end try
  end repeat
  repeat with extraId in extraIds
    try
      if (extraId as integer) is not (wid as integer) then close (first window whose id is (extraId as integer))
    end try
  end repeat'''
    else:
        open_lines = f'''  activate
  set matrixTab to do script "{command}"
  set matrixWindow to window 1
  set wid to id of matrixWindow'''
    return f'''tell application "Terminal"
{open_lines}
  try
    set custom title of matrixTab to "{MARKER}"
  end try
  try
    set background color of matrixTab to {{0, 0, 0}}
    set normal text color of matrixTab to {{0, 65535, 0}}
  end try
end tell
delay 0.8
set screenNote to "ok"
try
  tell application "Terminal"
    set index of (first window whose id is wid) to 1
    activate
  end tell
  tell application "System Events"
    tell process "Terminal"
      set frontmost to true
      set value of attribute "AXFullScreen" of (first window whose name contains "{MARKER}") to true
    end tell
  end tell
on error errMsg
  set screenNote to "AX failed: " & errMsg & "; keystroke"
  try
    tell application "Terminal" to activate
    tell application "System Events" to tell process "Terminal"
      set frontmost to true
      keystroke "f" using {{control down, command down}}
    end tell
  on error keyErr
    set screenNote to screenNote & "; keystroke failed: " & keyErr
  end try
end try
return "id:" & (wid as text) & linefeed & "screen:" & screenNote
'''


def parse_start_result(text):
    """``(window id or None, screen note)`` from the start script."""
    wid = None
    screen = ""
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("id:"):
            wid = _parse_window_id(stripped[3:])
        elif stripped.startswith("screen:"):
            screen = stripped[len("screen:"):].strip()
    if wid is None:
        wid = _parse_window_id(text)
    return wid, screen


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


def close_script(window_ids, ttys, quit_terminal=False):
    """Leave full screen, then close Matrix windows by id or Matrix tabs by tty.

    Ids are closed one at a time. The script does not walk ``windows`` and
    close the loop variable, which shifts the remaining references. When
    ``quit_terminal`` is set, Terminal itself quits after those closes.
    Stdout is ``ok``, ``absent``, or ``failed`` plus the reason. The process
    exit code stays 0 so the caller can choose the spoken line.
    """
    ids = [int(item) for item in window_ids]
    safe_ttys = [str(tty) for tty in ttys if _TTY_RE.match(str(tty))]
    window_blocks = []
    for wid in ids:
        window_blocks.append(
            f'''  try
    close (first window whose id is {wid})
  on error errMsg
    set notes to notes & "window {wid}: " & errMsg & linefeed
  end try'''
        )
    tab_blocks = []
    for tty in safe_ttys:
        tab_blocks.append(
            f'''  try
    set closedOne to false
    repeat with w in windows
      if closedOne then exit repeat
      repeat with t in tabs of w
        set matched to false
        try
          if (tty of t as text) is "{tty}" then set matched to true
        end try
        if matched then
          close t
          set closedOne to true
          exit repeat
        end if
      end repeat
    end repeat
  on error errMsg
    set notes to notes & "tab {tty}: " & errMsg & linefeed
  end try'''
        )
    quit_block = ""
    if quit_terminal:
        quit_block = '''try
  tell application "Terminal" to quit
on error errMsg
  set notes to notes & "quit: " & errMsg & linefeed
end try
'''
    return f'''tell application "System Events"
  if not (exists process "Terminal") then return "absent"
end tell
set notes to ""
try
  tell application "System Events"
    tell process "Terminal"
      repeat with w in windows
        try
          if name of w contains "{MARKER}" then
            set value of attribute "AXFullScreen" of w to false
          end if
        end try
      end repeat
    end tell
  end tell
on error errMsg
  set notes to notes & "fullscreen exit: " & errMsg & linefeed
end try
delay 0.6
tell application "Terminal"
{chr(10).join(window_blocks)}
{chr(10).join(tab_blocks)}
end tell
{quit_block}if notes is "" then
  return "ok"
end if
return "failed" & linefeed & notes
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


def plan_close(rows, ps_text="", launched_by_jev=False):
    """Which windows, tabs, and cmatrix pids the red pill may touch.

    A window is closed only when every tab in it is a Matrix tab. Otherwise
    only those tabs are closed. Tabs that are neither titled by Jev nor
    running cmatrix are not included. Terminal itself quits only when Jev
    launched it and every remaining tab is a Matrix tab.
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
    other_work = any(
        not _is_matrix_tab(tab)
        for tabs in grouped.values()
        for tab in tabs
    )
    running = bool(close_windows or close_ttys or unique_pids)
    return {
        "running": running,
        "close_windows": close_windows,
        "close_ttys": close_ttys,
        "pids": unique_pids,
        "quit_terminal": bool(launched_by_jev and running and not other_work),
    }


def _parse_window_id(text):
    match = re.search(r"\d+", str(text or ""))
    if not match:
        return None
    return int(match.group(0))


def _close_succeeded(text):
    head = str(text or "").strip().splitlines()
    if not head:
        return False
    return head[0].strip() in {"ok", "absent"}


def start_matrix(runner=None, which=None, isfile=None, shell=None, id_path=None):
    """Open the Matrix. If cmatrix is missing, say so and do not open Terminal."""
    binary = find_cmatrix(which=which, isfile=isfile)
    if not binary:
        return INSTALL_LINE
    run = runner or _run_logged
    id_file, launched_file = _state_paths(id_path)
    reuse = False
    try:
        probe = run(("osascript", "-e", terminal_running_script()))
    except Exception as exc:
        # A failed probe must not look like "Jev launched Terminal", or a
        # later red pill could quit a Terminal the user already had open.
        _log(f"terminal probe failed: {exc}")
        probe = "running"
    if str(probe).strip() == "absent":
        reuse = True
    try:
        out = run(("osascript", "-e", start_script(binary, shell, reuse_startup=reuse)))
    except Exception as exc:
        _log(f"start failed: {exc}")
        return "I couldn't open Terminal for the matrix."
    wid, screen = parse_start_result(out)
    if screen and screen != "ok":
        _log(screen)
    if wid is not None:
        try:
            _write_id(id_file, wid)
        except OSError as exc:
            _log(f"could not save window id: {exc}")
    try:
        if reuse:
            _write_launched(launched_file)
        else:
            _clear_id(launched_file)
    except OSError as exc:
        _log(f"could not save launch flag: {exc}")
    return "Matrix is on."


def stop_matrix(runner=None, id_path=None):
    """Quit cmatrix and close the Terminal session Jev opened for it.

    "Matrix is off." is spoken only after the close script reports success.
    A failed close keeps the saved id and launch flag so a retry still knows
    whether Terminal should quit.
    """
    run = runner or _run_logged
    id_file, launched_file = _state_paths(id_path)
    launched = _read_launched(launched_file)
    try:
        report = run(("osascript", "-e", report_script()))
    except Exception as exc:
        _log(f"report failed: {exc}")
        report = "absent"
    rows = parse_report(report)
    ps_text = ""
    if rows:
        try:
            ps_text = run(("ps", "-ax", "-o", "pid=,tty=,comm="))
        except Exception as exc:
            _log(f"ps failed: {exc}")
            ps_text = ""
    plan = plan_close(rows, ps_text, launched_by_jev=launched)
    if not plan["running"]:
        _clear_id(id_file)
        _clear_id(launched_file)
        return "The matrix isn't running."
    if plan["pids"]:
        try:
            run(["kill", "-INT"] + [str(pid) for pid in plan["pids"]])
        except Exception as exc:
            _log(f"kill failed: {exc}")
    if plan["close_windows"] or plan["close_ttys"] or plan["quit_terminal"]:
        script = close_script(
            plan["close_windows"],
            plan["close_ttys"],
            quit_terminal=plan["quit_terminal"],
        )
        try:
            out = run(("osascript", "-e", script))
        except Exception as exc:
            _log(f"close failed: {exc}")
            return "I couldn't close the Matrix window."
        if not _close_succeeded(out):
            _log(str(out or "").strip() or "close returned nothing")
            return "I couldn't close the Matrix window."
    _clear_id(id_file)
    _clear_id(launched_file)
    return "Matrix is off."
