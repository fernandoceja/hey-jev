"""Start, stop, or check Apple's `fm serve` (macOS 27) for the offline fallback.

Narrow exception to Jev's no-listening-sockets rule, approved by Fernando:
Jev may start `fm serve` bound ONLY to 127.0.0.1 port 1976, and only when
he asks ("start offline brain"). Never automatic, never 0.0.0.0.

- Launched detached (own session), output to ~/Library/Logs/Hey Jev/fm-serve.log.
- The PID Jev started is saved; stop sends SIGTERM to that PID only, and only
  if it is still an `fm serve` process.
- Status is GET http://127.0.0.1:1976/health.
- Never runs sudo or `fm license`. Mac-only. Not in BRIDGE_ALLOW.
Commands are argument lists, never shell strings.
"""
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request

FM_HOST = "127.0.0.1"
FM_PORT = 1976
HEALTH_URL = f"http://{FM_HOST}:{FM_PORT}/health"
FM_CANDIDATES = ("/usr/bin/fm", "/usr/local/bin/fm", "/opt/homebrew/bin/fm")
PID_FILE = os.path.expanduser("~/Library/Application Support/Hey Jev/fm-serve.pid")
LOG_FILE = os.path.expanduser("~/Library/Logs/Hey Jev/fm-serve.log")
START_WAIT = 8.0

FM_NOT_MAC = "The offline brain runs on this Mac."
FM_MISSING = ("I can't find Apple's fm tool. It needs macOS 27 with Apple Intelligence turned on.")
FM_LICENSE = ("The offline brain needs Apple's license accepted first. Open Terminal, "
              "type fm serve once, and accept it. I won't do that for you.")
FM_FAILED = "I couldn't start the offline brain. The log is in Library, Logs, Hey Jev."
FM_STARTED = "Offline brain is on, on this Mac only."
FM_STARTING = "Starting the offline brain. Give it a few seconds."
FM_ALREADY = "The offline brain is already on."
FM_STOPPED = "Offline brain is off."
FM_NOT_RUNNING = "The offline brain is already off."
FM_NOT_OURS = ("The offline brain is running, but I didn't start it, so I left it alone. "
               "Close its Terminal window to stop it.")
FM_STATUS_ON = "The offline brain is on."
FM_STATUS_OFF = "The offline brain is off. Say start offline brain to turn it on."

_NAME = r"(?:the\s+)?offline\s+(?:brain|mode|ai|backup)"
_START = re.compile(rf"(?:start|turn\s+on|enable|launch)\s+{_NAME}|{_NAME}\s+on")
_STOP = re.compile(rf"(?:stop|turn\s+off|disable|shut\s+down|kill)\s+{_NAME}|{_NAME}\s+off")
_STATUS = re.compile(rf"{_NAME}\s+status|status\s+of\s+{_NAME}|is\s+{_NAME}\s+(?:on|running|up)")


def _strip(text):
    t = (text or "").lower().strip()
    t = re.sub(r"^(?:hey\s+)?jev[,\s]+", "", t)
    t = re.sub(r"^(?:please\s+|can\s+you\s+)", "", t)
    return re.sub(r"[\s.!?]+$", "", t).strip()


def offline_brain_action(text):
    """Return "fm_serve_start", "fm_serve_stop", "fm_serve_status", or None."""
    t = _strip(text)
    if not t:
        return None
    if _START.fullmatch(t):
        return "fm_serve_start"
    if _STOP.fullmatch(t):
        return "fm_serve_stop"
    if _STATUS.fullmatch(t):
        return "fm_serve_status"
    return None


def find_fm(which=shutil.which, exists=os.path.isfile, access=os.access):
    found = which("fm")
    if found:
        return found
    for path in FM_CANDIDATES:
        if exists(path) and access(path, os.X_OK):
            return path
    return None


def serve_args(fm):
    """Explicit localhost bind. Never 0.0.0.0."""
    return [fm, "serve", "--host", FM_HOST, "--port", str(FM_PORT)]


def is_healthy(opener=urllib.request.urlopen, timeout=1.0):
    try:
        with opener(HEALTH_URL, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except Exception:
        return False


def _read_pid(path=PID_FILE):
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _write_pid(pid, path=PID_FILE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(str(pid))


def _clear_pid(path=PID_FILE):
    try:
        os.remove(path)
    except OSError:
        pass


def _is_our_fm(pid, run=subprocess.run):
    """True only if pid is alive and is an `fm serve` process."""
    if not pid or pid <= 1:
        return False
    try:
        out = run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return False
    parts = (out or "").split()
    return len(parts) >= 2 and os.path.basename(parts[0]) == "fm" and parts[1] == "serve"


def _log_tail(path=LOG_FILE, size=2000):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - size))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def start(platform=None, popen=subprocess.Popen, healthy=is_healthy, fm_path=None,
          sleep=time.sleep, wait=START_WAIT, log_path=LOG_FILE, pid_path=PID_FILE):
    if (platform or sys.platform) != "darwin":
        return FM_NOT_MAC
    if healthy():
        return FM_ALREADY
    fm = fm_path or find_fm()
    if not fm:
        return FM_MISSING
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    try:
        with open(log_path, "ab") as log:
            proc = popen(serve_args(fm), stdin=subprocess.DEVNULL, stdout=log,
                         stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
    except OSError:
        return FM_FAILED
    _write_pid(proc.pid, pid_path)
    waited = 0.0
    while waited < wait:
        if healthy():
            return FM_STARTED
        if proc.poll() is not None:
            _clear_pid(pid_path)
            return FM_LICENSE if "licen" in _log_tail(log_path).lower() else FM_FAILED
        sleep(0.5)
        waited += 0.5
    return FM_STARTING


def stop(platform=None, kill=os.kill, healthy=is_healthy, is_ours=_is_our_fm,
         pid_path=PID_FILE, sleep=time.sleep):
    if (platform or sys.platform) != "darwin":
        return FM_NOT_MAC
    pid = _read_pid(pid_path)
    if pid and is_ours(pid):
        try:
            kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError:
            return FM_FAILED
        _clear_pid(pid_path)
        for _ in range(6):
            if not healthy():
                break
            sleep(0.5)
        return FM_STOPPED
    _clear_pid(pid_path)
    return FM_NOT_OURS if healthy() else FM_NOT_RUNNING


def status(platform=None, healthy=is_healthy):
    if (platform or sys.platform) != "darwin":
        return FM_NOT_MAC
    return FM_STATUS_ON if healthy() else FM_STATUS_OFF
