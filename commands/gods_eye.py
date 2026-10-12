"""Open God's Eye, a local Vite app. Mac-only.

The app lives in GODS_EYE_DIR (usually ~/Developer/gods-eye). Set
JEV_GODS_EYE_DIR to use another folder. It serves http://127.0.0.1:5827.

If that port already accepts a connection, the page is opened in the
default browser. Otherwise `npm run dev` is started in the project folder,
detached, with output appended to .dev.log there. Jev then waits up to
GODS_EYE_WAIT_SECONDS for the port.

The port check is a client connection. This module never binds or listens.
The command is an argument list with a working directory, the same work as
`cd <folder> && npm run dev` without a shell string. Nothing here reads the
Keychain or talks to the iPhone bridge.
"""
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser

from . import config

OPENING_GODS_EYE = "Opening God's Eye."
GODS_EYE_NOT_MAC = "God's Eye runs on this Mac."
GODS_EYE_MISSING = "The God's Eye folder isn't there."
GODS_EYE_FAILED = "I couldn't open God's Eye."

NPM_CANDIDATES = ("/opt/homebrew/bin/npm", "/usr/local/bin/npm")
_UNSAFE = set("\"'`\n\r\t$\\;|&<>")


def _log(detail):
    print("  gods eye: {0}".format(detail))


def gods_eye_url(host=None, port=None):
    """http://127.0.0.1:5827 unless a test passes another host or port."""
    chosen_host = config.GODS_EYE_HOST if host is None else str(host)
    chosen_port = config.GODS_EYE_PORT if port is None else int(port)
    return "http://{0}:{1}".format(chosen_host, chosen_port)


def gods_eye_dir(override=None, env=None, configured=None):
    """Absolute project folder.

    `override` wins, then JEV_GODS_EYE_DIR, then GODS_EYE_DIR. A leading ~
    is expanded here. A path that is still a tilde, or that contains a
    newline, is refused. The folder is not created.
    """
    if override:
        raw = override
    else:
        if env is None:
            env = os.environ
        custom = ""
        if hasattr(env, "get"):
            custom = env.get("JEV_GODS_EYE_DIR") or ""
        raw = custom or (config.GODS_EYE_DIR if configured is None else configured)
    return _absolute_dir(raw)


def _absolute_dir(raw):
    if not isinstance(raw, str):
        return ""
    text = raw.strip()
    if not text or "\x00" in text or any(ch in text for ch in _UNSAFE):
        return ""
    expanded = os.path.expanduser(text)
    if not expanded or expanded.startswith("~"):
        return ""
    target = os.path.abspath(expanded)
    if not target.startswith("/"):
        return ""
    return target


def _safe_npm(path):
    """An absolute npm path with no shell metacharacters, or empty."""
    text = str(path or "")
    if not text.startswith("/") or "\x00" in text:
        return ""
    if any(ch in text for ch in _UNSAFE):
        return ""
    return text


def _is_exec(path):
    return os.path.isfile(path) and os.access(path, os.X_OK)


def find_npm(which=None, isfile=None):
    """npm on PATH, then the usual Homebrew locations. Empty when none is usable."""
    check = isfile or _is_exec
    probe = shutil.which if which is None else which
    found = None
    if probe is not None:
        try:
            found = probe("npm")
        except Exception:
            found = None
    safe = _safe_npm(found)
    if safe and check(safe):
        return safe
    for path in NPM_CANDIDATES:
        if _safe_npm(path) and check(path):
            return path
    return ""


def dev_command(npm_path):
    """[npm, 'run', 'dev']. A string would be a shell command, so it is refused."""
    binary = _safe_npm(npm_path)
    if not binary:
        return None
    return [binary, "run", "dev"]


def _child_env(npm_path, base=None):
    """The parent environment, with npm's directory on PATH.

    A Mac app launched from Finder often has a short PATH. `npm run dev`
    still has to find `node` beside the Homebrew npm.
    """
    env = dict(os.environ if base is None else base)
    npm_dir = os.path.dirname(npm_path)
    parts = [part for part in str(env.get("PATH", "")).split(":") if part]
    if npm_dir and npm_dir not in parts:
        parts.insert(0, npm_dir)
    env["PATH"] = ":".join(parts)
    return env


def port_is_open(host, port, timeout=None, connector=None):
    """True when a client connection to host:port succeeds.

    This never binds or listens. A refused or timed-out connection is not open.
    """
    connect = socket.create_connection if connector is None else connector
    budget = config.GODS_EYE_CONNECT_TIMEOUT if timeout is None else timeout
    try:
        sock = connect((host, int(port)), budget)
    except OSError:
        return False
    try:
        sock.close()
    except OSError:
        pass
    return True


def _ask_port(probe, host, port):
    """True, False, or None when the check itself failed."""
    try:
        return bool(probe(host, port))
    except Exception as exc:
        _log(type(exc).__name__)
        return None


def wait_for_port(host, port, seconds, poll, probe, clock, sleep):
    """Poll until the port accepts a client connection, or the budget runs out."""
    deadline = clock() + float(seconds)
    # One extra look past the exact count, so a port that opens on the last
    # check still counts. A clock that does not move cannot loop forever.
    if poll <= 0:
        limit = 1
    else:
        limit = int(float(seconds) / float(poll)) + 2
    for _ in range(max(1, limit)):
        result = _ask_port(probe, host, port)
        if result is None:
            return False
        if result:
            return True
        now = clock()
        if now >= deadline:
            return False
        pause = min(float(poll), deadline - now)
        if pause > 0:
            sleep(pause)
    return False


def start_dev_server(folder, log_path, npm_path, popen=None, env=None):
    """Start `npm run dev` in `folder`. Detached. Output goes to log_path.

    The process is a new session, so closing Jev does not stop it. The
    parent does not wait. stdin is closed. stdout and stderr share the log.
    """
    command = dev_command(npm_path)
    if not command or isinstance(command, str):
        raise TypeError("npm run dev takes an argument list")
    runner = subprocess.Popen if popen is None else popen
    child_env = _child_env(npm_path, env)
    log = open(log_path, "ab", buffering=0)
    try:
        return runner(
            command,
            cwd=folder,
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        log.close()


def _open_page(url, opener):
    open_fn = webbrowser.open if opener is None else opener
    try:
        opened = open_fn(url)
    except Exception as exc:
        _log(type(exc).__name__)
        return False
    return opened is True


def _on_mac(platform):
    name = sys.platform if platform is None else platform
    return name == "darwin"


def open_gods_eye(folder=None, env=None, host=None, port=None, url=None,
                  wait_seconds=None, poll_seconds=None, platform=None,
                  probe=None, popen=None, opener=None, npm=None,
                  which=None, npm_isfile=None, clock=None, sleep=None,
                  isdir=None, child_env=None):
    """Open God's Eye in the default browser. Speak a short line either way.

    A port that is already up is opened immediately. Otherwise the dev
    server is started once and this waits for the port. A missing folder
    is not created. Not on macOS, this does not connect and does not start
    anything.
    """
    if not _on_mac(platform):
        return GODS_EYE_NOT_MAC
    chosen_host = config.GODS_EYE_HOST if host is None else host
    chosen_port = config.GODS_EYE_PORT if port is None else int(port)
    page = gods_eye_url(chosen_host, chosen_port) if url is None else url
    check = port_is_open if probe is None else probe
    up = _ask_port(check, chosen_host, chosen_port)
    if up is None:
        return GODS_EYE_FAILED
    if up:
        _log("already up")
        if not _open_page(page, opener):
            return GODS_EYE_FAILED
        return OPENING_GODS_EYE

    project = gods_eye_dir(override=folder, env=env)
    if not project:
        return GODS_EYE_MISSING
    exists = os.path.isdir if isdir is None else isdir
    try:
        there = bool(exists(project))
    except OSError:
        there = False
    if not there:
        return GODS_EYE_MISSING

    binary = _safe_npm(npm) if npm else find_npm(which=which, isfile=npm_isfile)
    if not binary:
        _log("npm missing")
        return GODS_EYE_FAILED
    log_path = os.path.join(project, config.GODS_EYE_LOG_NAME)
    try:
        start_dev_server(project, log_path, binary, popen=popen, env=child_env)
    except Exception as exc:
        _log(type(exc).__name__)
        return GODS_EYE_FAILED
    _log("starting")

    wait = config.GODS_EYE_WAIT_SECONDS if wait_seconds is None else float(wait_seconds)
    poll = config.GODS_EYE_POLL_SECONDS if poll_seconds is None else float(poll_seconds)
    now = time.monotonic if clock is None else clock
    pause = time.sleep if sleep is None else sleep
    if not wait_for_port(chosen_host, chosen_port, wait, poll, check, now, pause):
        return GODS_EYE_FAILED
    if not _open_page(page, opener):
        return GODS_EYE_FAILED
    return OPENING_GODS_EYE
