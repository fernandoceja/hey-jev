"""Morning brief voice memo. Local mp3/m4a files, played with afplay.

No network and no listening socket. The iPhone bridge does not get these
commands. "brief me" is a different command: the spoken summary in brief.py.
"""
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta

from .config import (
    BRIEF_MEMO_DIR,
    BRIEF_MEMO_ENABLED,
    BRIEF_MEMO_POLL_SECONDS,
    BRIEF_MEMO_RETRIES,
    BRIEF_MEMO_STATE_PATH,
    BRIEF_MEMO_TIME,
    BRIEF_MEMO_WINDOW_MINUTES,
)
from .textutil import _month_day

NOT_READY_LINE = "Your brief isn't ready yet."
MISSING_FOLDER_LINE = "I can't find the brief folder."
EMPTY_FOLDER_LINE = "There's no brief memo yet."
AFPLAY = "/usr/bin/afplay"
_AUDIO = (".mp3", ".m4a")
_OFF = ("0", "false", "no", "off")

_player = None
_player_lock = threading.Lock()
_thread = None
_thread_lock = threading.Lock()


class BriefPlayback(object):
    """Spoken line first, then a local file. An empty path means speak only."""

    def __init__(self, line, path):
        self.line = line or ""
        self.path = path or ""


class MemoPlayer(object):
    """One afplay process. play() replaces whatever is already running."""

    def __init__(self, spawn=None):
        self._spawn = spawn or _spawn_afplay
        self._proc = None
        self._lock = threading.Lock()

    def play(self, path):
        with self._lock:
            self._halt()
            self._proc = self._spawn(path)
        return True

    def stop(self):
        with self._lock:
            return self._halt()

    def _halt(self):
        proc = self._proc
        if proc is None:
            return False
        self._proc = None
        try:
            if proc.poll() is not None:
                return False
        except Exception:
            return False
        try:
            proc.terminate()
        except Exception:
            return False
        return True


def afplay_command(path):
    """Argument list for local playback. Never a shell string."""
    return [AFPLAY, path]


def _spawn_afplay(path):
    return subprocess.Popen(afplay_command(path))


def shared_player():
    global _player
    with _player_lock:
        if _player is None:
            _player = MemoPlayer()
        return _player


def play_memo_file(path, player=None):
    """Start afplay on one local memo. Returns False if the path is not a memo."""
    if not _is_memo(path):
        return False
    (player or shared_player()).play(path)
    return True


def stop_brief(player=None):
    """Stop the memo. Apple Music pause is a different command."""
    stopped = (player or shared_player()).stop()
    if stopped:
        return "Stopped."
    return "Nothing is playing."


def _is_memo(path):
    if not path or os.path.islink(path) or not os.path.isfile(path):
        return False
    return os.path.splitext(path)[1].lower() in _AUDIO


def _env_text(env, name):
    if name not in env:
        return None
    raw = env.get(name)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def parse_brief_time(raw, default=None):
    """HH:MM, or 07:10 when the value is not a real time of day."""
    fallback = default or datetime.strptime(BRIEF_MEMO_TIME, "%H:%M").time()
    text = str(raw or "").strip()
    parts = text.split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return fallback
    if len(parts[1]) != 2:
        return fallback
    hour = int(parts[0])
    minute = int(parts[1])
    if hour > 23 or minute > 59:
        return fallback
    return fallback.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _bounded_int(raw, default, low, high):
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    if value < low or value > high:
        return default
    return value


def brief_memo_settings(environ=None):
    """Folder, clock, and retry window. Explicit env values override the constants."""
    env = os.environ if environ is None else environ
    raw_dir = _env_text(env, "BRIEF_MEMO_DIR")
    if raw_dir is None:
        folder = BRIEF_MEMO_DIR
    else:
        folder = os.path.expanduser(raw_dir)
    flag = _env_text(env, "BRIEF_MEMO_ENABLED")
    if flag is None:
        enabled = bool(BRIEF_MEMO_ENABLED)
    else:
        enabled = flag.lower() not in _OFF
    when_raw = _env_text(env, "BRIEF_MEMO_TIME")
    when = parse_brief_time(when_raw if when_raw is not None else BRIEF_MEMO_TIME)
    retries = _bounded_int(
        _env_text(env, "BRIEF_MEMO_RETRIES") if _env_text(env, "BRIEF_MEMO_RETRIES") is not None else BRIEF_MEMO_RETRIES,
        BRIEF_MEMO_RETRIES, 0, 12,
    )
    window = _bounded_int(
        _env_text(env, "BRIEF_MEMO_WINDOW_MINUTES") if _env_text(env, "BRIEF_MEMO_WINDOW_MINUTES") is not None else BRIEF_MEMO_WINDOW_MINUTES,
        BRIEF_MEMO_WINDOW_MINUTES, 0, 240,
    )
    return {
        "folder": folder,
        "enabled": enabled,
        "when": when,
        "retries": retries,
        "window_minutes": window,
        "state_path": BRIEF_MEMO_STATE_PATH,
    }


def _local_now(now):
    if now is None:
        return datetime.now().astimezone().replace(tzinfo=None)
    if isinstance(now, datetime) and now.tzinfo is not None:
        return now.astimezone().replace(tzinfo=None)
    return now


def _as_date(value):
    if value is None:
        return _local_now(None).date()
    if isinstance(value, datetime):
        return _local_now(value).date()
    return value


def list_memos(folder):
    """(mtime, name, path, local date) oldest first. None if the folder is missing.

    Only regular .mp3 and .m4a files in that folder. Subfolders and symlinks
    are skipped. The date is the file's mtime, which is what "from today" means.
    """
    if not folder or not os.path.isdir(folder):
        return None
    found = []
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    for name in names:
        if not name or name.startswith("."):
            continue
        if os.path.splitext(name)[1].lower() not in _AUDIO:
            continue
        path = os.path.join(folder, name)
        if not _is_memo(path):
            continue
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        found.append((mtime, name, path, datetime.fromtimestamp(mtime).date()))
    found.sort(key=lambda item: (item[0], item[1]))
    return found


def _newest(files, day=None):
    if not files:
        return None
    chosen = files
    if day is not None:
        chosen = [item for item in files if item[3] == day]
    if not chosen:
        return None
    return chosen[-1]


def _blank_state(day):
    return {
        "date": day.isoformat(),
        "played": False,
        "attempts": 0,
        "not_ready": False,
        "gave_up": False,
    }


def load_memo_state(path, day):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return _blank_state(day)
    if not isinstance(data, dict) or data.get("date") != day.isoformat():
        return _blank_state(day)
    try:
        attempts = int(data.get("attempts") or 0)
    except (TypeError, ValueError):
        attempts = 0
    if attempts < 0:
        attempts = 0
    return {
        "date": day.isoformat(),
        "played": bool(data.get("played")),
        "attempts": attempts,
        "not_ready": bool(data.get("not_ready")),
        "gave_up": bool(data.get("gave_up")),
    }


def _save_state(path, state):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    payload = {
        "date": state["date"],
        "played": bool(state["played"]),
        "attempts": int(state["attempts"]),
        "not_ready": bool(state["not_ready"]),
        "gave_up": bool(state["gave_up"]),
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
        handle.write("\n")
    os.replace(tmp, path)


def _slot_time(start, window_minutes, retries, index):
    """When attempt `index` is due. Index 0 is the clock time. Later ones spread across the window."""
    if index <= 0 or retries <= 0:
        return start
    seconds = (int(window_minutes) * 60 * int(index)) // int(retries)
    slot = start + timedelta(seconds=seconds)
    end = start + timedelta(minutes=int(window_minutes))
    if slot > end:
        return end
    return slot


def plan_morning_brief(now, folder, state, when, retries, window_minutes, enabled):
    """What the 7:10 check should do. Does not play, speak, or write the state file.

    Returns None when it is too early, already done, or disabled. Otherwise a
    dict with line, path, and the state to save. A play is today's newest memo.
    A missing folder is the same as no file yet: say the line once, retry, then
    stay quiet. Restarts read the saved state, so a played memo is not replayed.
    """
    if not enabled:
        return None
    now = _local_now(now)
    day = now.date()
    if state.get("date") != day.isoformat():
        state = _blank_state(day)
    if state["played"] or state["gave_up"]:
        return None
    start = datetime.combine(day, when)
    end = start + timedelta(minutes=int(window_minutes))
    if now < start:
        return None
    new_state = dict(state)
    if now > end:
        new_state["gave_up"] = True
        return {"action": "give_up", "line": "", "path": "", "state": new_state}
    max_attempts = 1 + max(0, int(retries))
    if state["attempts"] >= max_attempts:
        new_state["gave_up"] = True
        return {"action": "give_up", "line": "", "path": "", "state": new_state}
    slot = _slot_time(start, window_minutes, retries, state["attempts"])
    if now < slot:
        return None
    files = list_memos(folder)
    chosen = _newest(files, day)
    new_state["attempts"] = state["attempts"] + 1
    if chosen is not None:
        new_state["played"] = True
        return {"action": "play", "line": "", "path": chosen[2], "state": new_state}
    line = ""
    if not state["not_ready"]:
        line = NOT_READY_LINE
        new_state["not_ready"] = True
    if new_state["attempts"] >= max_attempts:
        new_state["gave_up"] = True
    action = "not_ready" if line else ("give_up" if new_state["gave_up"] else "retry")
    return {"action": action, "line": line, "path": "", "state": new_state}


def run_scheduled_brief(now=None, folder=None, state_path=None, player=None, speaker=None,
                        enabled=None, when=None, retries=None, window_minutes=None, environ=None):
    """Save today's outcome, then speak or play. None when there is nothing to do.

    The state is written before playback so a restart does not start the file again.
    `player` and `speaker` are injected in tests. The real speaker is macOS say,
    and the real player is afplay. Neither one uses the network.
    """
    settings = None

    def pick(value, key):
        nonlocal settings
        if value is not None:
            return value
        if settings is None:
            settings = brief_memo_settings(environ)
        return settings[key]

    folder = pick(folder, "folder")
    state_path = pick(state_path, "state_path")
    enabled = pick(enabled, "enabled")
    when = pick(when, "when")
    retries = pick(retries, "retries")
    window_minutes = pick(window_minutes, "window_minutes")
    now_local = _local_now(now)
    state = load_memo_state(state_path, now_local.date())
    job = plan_morning_brief(
        now_local, folder, state, when, retries, window_minutes, enabled,
    )
    if not job:
        return None
    _save_state(state_path, job["state"])
    line = job.get("line") or ""
    path = job.get("path") or ""
    if line:
        (speaker or _say_local)(line)
    if path:
        play_memo_file(path, player=player)
    return job


def _say_local(line):
    if not line:
        return
    subprocess.run(["/usr/bin/say", line], check=False)


def _playback_line(day, today):
    if day == today:
        return "Playing your brief."
    if day.year == today.year:
        return "Playing the brief from {0}.".format(_month_day(day))
    return "Playing the brief from {0}, {1}.".format(_month_day(day), day.year)


def request_brief(folder=None, today=None, environ=None):
    """The newest memo of any date. Say the date when it is not today.

    This does not start playback. The caller speaks the line, then calls
    play_memo_file, so the reply and the memo do not play at the same time.
    """
    if folder is None:
        folder = brief_memo_settings(environ)["folder"]
    today = _as_date(today)
    files = list_memos(folder)
    if files is None:
        return MISSING_FOLDER_LINE
    newest = _newest(files)
    if newest is None:
        return EMPTY_FOLDER_LINE
    _mtime, _name, path, day = newest
    return BriefPlayback(_playback_line(day, today), path)


def start_brief_memo_thread(speaker=None, player=None, interval=None):
    """Check the clock on a daemon thread. No socket is opened.

    `speaker(line)` is used for "Your brief isn't ready yet." Playback goes
    through the shared afplay player unless `player` is passed.
    """
    global _thread
    wait = BRIEF_MEMO_POLL_SECONDS if interval is None else interval
    if wait < 1:
        wait = 1

    def loop():
        while True:
            try:
                run_scheduled_brief(speaker=speaker, player=player)
            except Exception as exc:
                print("  brief: {0}".format(type(exc).__name__))
            time.sleep(wait)

    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=loop, name="jev-brief-memo", daemon=True)
        _thread.start()
