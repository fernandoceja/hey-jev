"""Analyze the front app with REA. Read-only. Mac-only. Not on the bridge.

The only command that may be spawned is ``analyze``. The app path is its own
argv element. Node and the REA script are configurable; their versions are
pinned and checked before analyze runs. Anything else is refused first.

Money apps are refused by a generic banking or finance rule. Work apps, Apple
apps, and a child's other apps and devices are refused from a local file that
is not in this public repo. A configured kids learning app is analyzed as
structure only: progress and user fields are dropped.

Output is redacted and trimmed before it is spoken or logged. Logs stay on
this Mac for 7 days. A refused run logs a timestamp and the word refused.
This module does not listen, and it does not call a paid API. A screenshot
is used only to name the app. Its pixels are never read.
"""
import errno
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

from . import config
from .messages import LocalSpeech

ALLOWED_COMMANDS = frozenset({"analyze"})
REFUSAL = "I can't look at that app"
MISSING_FIELD = "REA didn't find that"
NOT_MAC = "REA analyze runs on this Mac."
NO_APP = "I can't see which app is in front."
NO_PATH = "I can't see that app's path."
MISSING_NODE = "I can't find the Node binary for REA."
MISSING_REA = "I can't find the REA script."
NODE_VERSION_UNREADABLE = "I can't read the Node version."
REA_VERSION_UNREADABLE = "I can't read the REA version."
BAD_JSON = "REA analyze did not return JSON."
REJECTED = "I only run REA analyze."
BAD_TIMEOUT = "REA timeout must be from 30 to 60 seconds."
TOO_BIG = "REA output was too large to read."
GENERIC = "I couldn't analyze that app."
# Above this, the body is not parsed. The spoken line stays the short error.
_HARD_STDOUT_CAP = 2000000

_PHRASE = re.compile(
    r"^(?:please\s+)?(?:hey\s+jev\b\s*,?\s+)?(?:please\s+)?"
    r"analy[sz]e\s+(?:this|the\s+front)\s+app"
    r"(?:\s+for\s+(?P<field>[A-Za-z][A-Za-z0-9_]{0,40}))?"
    r"(?:\s+please)?[.!?]*$",
    re.I,
)
_IDENTITY = ("name", "bundle_id", "path", "site")
# Generic categories only. Institution names stay in the local file.
_FINANCE_WORDS = frozenset({
    "bank", "banking", "finance", "financial", "credit", "wallet", "brokerage", "payment",
})
_USER_DATA_WORDS = frozenset({
    "progress", "user", "users", "profile", "profiles", "account", "accounts",
    "email", "emails", "phone", "phones", "score", "scores", "level", "levels",
    "xp", "streak", "streaks", "achievement", "achievements", "password",
    "passwords", "token", "tokens", "secret", "secrets", "session", "sessions",
    "cookie", "cookies", "student", "students", "child", "children", "learner",
    "learners", "username", "pii", "personal", "userdata",
})
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(
    r"(?<!\d)(?:\+\d{1,3}[\s.\-]?)?(?:\(\d{3}\)|\d{3})[\s.\-]\d{3}[\s.\-]\d{4}(?!\d)"
)
_PHONE_COMPACT = re.compile(r"(?<!\d)\+\d{10,15}(?!\d)")
_KEY = re.compile(
    r"\b(?:sk-(?:ant-|proj-)?[A-Za-z0-9_\-]{8,}"
    r"|ghp_[A-Za-z0-9]{8,}"
    r"|github_pat_[A-Za-z0-9_]{8,}"
    r"|crsr_[A-Za-z0-9_\-]{8,}"
    r"|AKIA[A-Z0-9]{16})\b"
)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{8,}\b", re.I)
_ENTROPY = re.compile(r"\b[A-Za-z0-9+/=_\-]{32,}\b")
_HOME = re.compile(r"/(?:Users|home)/[^/\s]+")
_REDACT = (
    (_EMAIL, "[redacted]"),
    (_PHONE, "[redacted]"),
    (_PHONE_COMPACT, "[redacted]"),
    (_KEY, "[redacted]"),
    (_JWT, "[redacted]"),
    (_BEARER, "[redacted]"),
    (_HOME, "/[redacted]"),
)


def rea_action(text):
    """``rea_analyze`` when the utterance is only an analyze request. Else None."""
    if _PHRASE.match((text or "").strip()):
        return "rea_analyze"
    return None


def requested_field(text):
    """Field name the utterance asked for, or empty when it asked for the app."""
    match = _PHRASE.match((text or "").strip())
    if not match:
        return ""
    return match.group("field") or ""


def command_allowed(command):
    """True only for the v1 allowlist. Anything else must not be spawned."""
    return command in ALLOWED_COMMANDS


def build_argv(node, script, command, app_path):
    """``[node, script, analyze, path, --json]``, or None when it must not run.

    ``command`` has to be the single allowlisted name. ``app_path`` is one
    element. A shell string is never returned.
    """
    if not command_allowed(command) or command != "analyze":
        return None
    if not _absolute_tool(node) or not _absolute_tool(script):
        return None
    if not isinstance(app_path, str):
        return None
    path = app_path.strip()
    if not path or path.startswith("~") or "\x00" in path or "\n" in path or "\r" in path:
        return None
    return [node, script, "analyze", path, "--json"]


def resolve_timeout(value=None):
    """Whole seconds from 30 to 60, or None when the value is refused."""
    if value is None:
        raw = os.environ.get("JEV_REA_TIMEOUT")
        value = config.REA_TIMEOUT_SECONDS if raw in (None, "") else raw
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return None
    if seconds < config.REA_TIMEOUT_MIN or seconds > config.REA_TIMEOUT_MAX:
        return None
    return seconds


def resolve_output_cap(value=None):
    """Character cap for text that leaves this process toward a model or a log."""
    if value is None:
        raw = os.environ.get("JEV_REA_OUTPUT_CAP")
        value = config.REA_OUTPUT_CAP if raw in (None, "") else raw
    try:
        cap = int(value)
    except (TypeError, ValueError):
        return config.REA_OUTPUT_CAP
    if cap < 1:
        return config.REA_OUTPUT_CAP
    return cap


def identify_app(front=None, screenshot=None):
    """Name, bundle id, path, and site. Screenshot pixels are ignored.

    A screenshot may carry those four identity strings. Keys such as pixels,
    image, or bytes are not read. ``front`` wins when both name the same field.
    """
    found = {}
    if isinstance(screenshot, dict):
        for key in _IDENTITY:
            value = screenshot.get(key)
            if isinstance(value, str) and value.strip():
                found[key] = value.strip()
    if isinstance(front, dict):
        for key in _IDENTITY:
            value = front.get(key)
            if isinstance(value, str) and value.strip():
                found[key] = value.strip()
    return found


def load_blocklist(path):
    """Local rules. A missing or broken file means no extra names, not a crash."""
    rules = {
        "blocked_bundle_ids": [],
        "blocked_names": [],
        "blocked_sites": [],
        "kids_app_ids": [],
    }
    if not path or not os.path.isfile(path):
        return rules
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return rules
    if not isinstance(data, dict):
        return rules
    for key in rules:
        value = data.get(key) or []
        if not isinstance(value, list):
            continue
        rules[key] = [str(item).strip() for item in value if str(item).strip()]
    return rules


def is_finance(identity):
    """True when a bundle id, name, or site uses a banking or finance word."""
    for key in ("bundle_id", "name", "site"):
        if any(part in _FINANCE_WORDS for part in _tokens(identity.get(key))):
            return True
    return False


def is_kids_app(identity, rules):
    bundle = (identity.get("bundle_id") or "").lower()
    if not bundle:
        return False
    for item in rules.get("kids_app_ids") or []:
        if bundle == item.lower():
            return True
    return False


def is_listed(identity, rules):
    """True when the local file names this app, site, or device."""
    bundle = (identity.get("bundle_id") or "").lower()
    name = (identity.get("name") or "").lower()
    site = (identity.get("site") or "").lower()
    for item in rules.get("blocked_bundle_ids") or []:
        if bundle and bundle == item.lower():
            return True
    for item in rules.get("blocked_names") or []:
        needle = item.lower()
        if needle and needle in name:
            return True
    for item in rules.get("blocked_sites") or []:
        needle = item.lower()
        if needle and site and (site == needle or site.endswith("." + needle) or needle in site):
            return True
    return False


def access_decision(identity, rules):
    """``refuse``, ``structure``, or ``analyze``. Finance is never analyzed."""
    if is_finance(identity):
        return "refuse"
    if is_kids_app(identity, rules):
        return "structure"
    if is_listed(identity, rules):
        return "refuse"
    return "analyze"


def redact(text):
    """Replace keys, tokens, emails, phone numbers, and home-directory names."""
    value = "" if text is None else str(text)
    for pattern, replacement in _REDACT:
        value = pattern.sub(replacement, value)
    return _ENTROPY.sub(_entropy_replacement, value)


def trim_text(text, cap):
    """Keep at most ``cap`` characters. The marker says the rest was cut."""
    value = "" if text is None else str(text)
    if cap < 1:
        return ""
    if len(value) <= cap:
        return value
    note = " [trimmed]"
    if cap <= len(note):
        return value[:cap]
    return value[:cap - len(note)] + note


def strip_user_data(value):
    """Drop progress and user-data fields. Structural fields stay."""
    if isinstance(value, dict):
        kept = {}
        for key, item in value.items():
            if _is_user_data_key(key):
                continue
            kept[key] = strip_user_data(item)
        return kept
    if isinstance(value, list):
        return [strip_user_data(item) for item in value]
    return value


def quote_answer(data, field):
    """Quote REA's own fields. A missing field is never filled in."""
    if not isinstance(data, dict) or not data:
        return MISSING_FIELD
    if field:
        if field not in data:
            return MISSING_FIELD
        return "{0}: {1}".format(field, _dump(data[field]))
    parts = []
    for key in sorted(data):
        parts.append("{0}: {1}".format(key, _dump(data[key])))
    return " ".join(parts) if parts else MISSING_FIELD


def cleanup_logs(log_dir, now=None):
    """Delete log files older than 7 days. The window is not configurable.

    Returns the paths that were removed. A missing folder removes nothing.
    """
    if not log_dir or not os.path.isdir(log_dir):
        return []
    moment = _as_utc(now)
    cutoff = (moment - timedelta(days=config.REA_LOG_RETENTION_DAYS)).timestamp()
    removed = []
    try:
        names = os.listdir(log_dir)
    except OSError:
        return []
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(log_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            continue
        if stamp <= cutoff:
            try:
                os.remove(path)
            except OSError:
                continue
            removed.append(path)
    return removed


def log_refused(log_dir, now=None):
    """Write a timestamp and the word refused. Nothing else."""
    moment = _as_utc(now)
    payload = {"timestamp": _stamp(moment), "refused": "refused"}
    return _write_log(log_dir, payload)


def analyze_front_app(text, front=None, screenshot=None, run=None, platform=None,
                      blocklist_path=None, log_dir=None, now=None, timeout=None,
                      output_cap=None, node_path=None, script_path=None,
                      exists=None, front_reader=None):
    """Speak one local answer. REA is spawned only after the blocklist says yes.

    The return value is LocalSpeech so the words stay on the Mac ``say``
    command. Cleanup of logs older than 7 days runs on every Mac invocation.
    """
    if (platform or sys.platform) != "darwin":
        return LocalSpeech(NOT_MAC)
    try:
        return _analyze(
            text, front, screenshot, run, blocklist_path, log_dir, now, timeout,
            output_cap, node_path, script_path, exists, front_reader,
        )
    except Exception as exc:
        if isinstance(exc, AssertionError):
            raise
        return LocalSpeech(GENERIC)


def _analyze(text, front, screenshot, run, blocklist_path, log_dir, now, timeout,
             output_cap, node_path, script_path, exists, front_reader):
    moment = _as_utc(now)
    folder = log_dir or config.REA_LOG_DIR
    cap = resolve_output_cap(output_cap)
    cleanup_logs(folder, moment)
    identity = _identity(front, screenshot, front_reader)
    if not identity:
        return LocalSpeech(NO_APP)
    rules = load_blocklist(blocklist_path if blocklist_path is not None else config.REA_BLOCKLIST_PATH)
    decision = access_decision(identity, rules)
    if decision == "refuse":
        log_refused(folder, moment)
        return LocalSpeech(REFUSAL)
    path = identity.get("path") or ""
    if not path:
        _log_attempt(folder, moment, "", "", "", "analyze", "", NO_PATH, cap)
        return LocalSpeech(NO_PATH)
    seconds = resolve_timeout(timeout)
    if seconds is None:
        _log_attempt(folder, moment, path, identity.get("bundle_id") or "", requested_field(text),
                     "analyze", "", BAD_TIMEOUT, cap)
        return LocalSpeech(BAD_TIMEOUT)
    node = os.path.expanduser(node_path or os.environ.get("JEV_REA_NODE") or config.REA_NODE_PATH)
    script = os.path.expanduser(script_path or os.environ.get("JEV_REA_SCRIPT") or config.REA_SCRIPT_PATH)
    present = os.path.isfile if exists is None else exists
    spawn = subprocess.run if run is None else run
    if not present(node):
        _log_attempt(folder, moment, path, identity.get("bundle_id") or "", requested_field(text),
                     "analyze", "", MISSING_NODE, cap)
        return LocalSpeech(MISSING_NODE)
    if not present(script):
        _log_attempt(folder, moment, path, identity.get("bundle_id") or "", requested_field(text),
                     "analyze", "", MISSING_REA, cap)
        return LocalSpeech(MISSING_REA)
    version_error = _check_versions(node, script, seconds, spawn)
    if version_error:
        _log_attempt(folder, moment, path, identity.get("bundle_id") or "", requested_field(text),
                     "analyze", "", version_error, cap)
        return LocalSpeech(version_error)
    outcome = _run_analyze(node, script, path, seconds, spawn)
    if outcome.get("error"):
        _log_attempt(folder, moment, path, identity.get("bundle_id") or "", requested_field(text),
                     "analyze", outcome.get("output") or "", outcome["error"], cap)
        return LocalSpeech(outcome["error"])
    data = outcome["data"]
    if decision == "structure":
        data = strip_user_data(data)
    field = requested_field(text)
    answer = quote_answer(data, field)
    if decision == "structure" and answer != MISSING_FIELD:
        answer = "Structure only. {0}".format(answer)
    rendered = _dump(data)
    _log_attempt(folder, moment, path, identity.get("bundle_id") or "", field,
                 "analyze", rendered, answer, cap)
    return LocalSpeech(trim_text(redact(answer), cap))


def _run_analyze(node, script, path, seconds, spawn):
    argv = build_argv(node, script, "analyze", path)
    if argv is None:
        return {"error": REJECTED, "output": ""}
    try:
        result = spawn(argv, capture_output=True, text=True, timeout=seconds)
    except FileNotFoundError:
        return {"error": MISSING_NODE, "output": ""}
    except subprocess.TimeoutExpired:
        return {"error": "REA timed out after {0} seconds.".format(seconds), "output": ""}
    except OSError as exc:
        if getattr(exc, "errno", None) == errno.ENOENT:
            return {"error": MISSING_NODE, "output": ""}
        return {"error": GENERIC, "output": ""}
    code = getattr(result, "returncode", 1)
    stdout = getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr", "") or ""
    if code:
        return {
            "error": "REA analyze exited with status {0}.".format(code),
            "output": stderr or stdout,
        }
    if len(stdout) > _HARD_STDOUT_CAP:
        return {"error": TOO_BIG, "output": stdout[:_HARD_STDOUT_CAP]}
    try:
        data = json.loads(stdout)
    except ValueError:
        return {"error": BAD_JSON, "output": stdout}
    if not isinstance(data, dict):
        return {"data": data}
    return {"data": data}


def _check_versions(node, script, seconds, spawn):
    try:
        result = spawn([node, "--version"], capture_output=True, text=True, timeout=seconds)
    except FileNotFoundError:
        return MISSING_NODE
    except subprocess.TimeoutExpired:
        return "Node version check timed out after {0} seconds.".format(seconds)
    except OSError as exc:
        if getattr(exc, "errno", None) == errno.ENOENT:
            return MISSING_NODE
        return NODE_VERSION_UNREADABLE
    if getattr(result, "returncode", 1):
        return NODE_VERSION_UNREADABLE
    got = _node_version_text(getattr(result, "stdout", "") or "")
    if got != config.REA_NODE_VERSION:
        shown = got or "unknown"
        return "Node is {0}. This command needs Node {1}.".format(shown, config.REA_NODE_VERSION)
    found = _package_version(script)
    if not found:
        return REA_VERSION_UNREADABLE
    if found != config.REA_VERSION:
        return "REA is {0}. This command needs REA {1}.".format(found, config.REA_VERSION)
    return ""


def _package_version(script):
    root = os.path.dirname(os.path.dirname(os.path.abspath(script)))
    path = os.path.join(root, "package.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    version = data.get("version")
    if not isinstance(version, str):
        return ""
    return version.strip()


def _node_version_text(stdout):
    text = (stdout or "").strip().lstrip("vV")
    if not text:
        return ""
    return text.split()[0]


def _identity(front, screenshot, front_reader):
    found = identify_app(front, screenshot)
    if found.get("path") or found.get("bundle_id") or found.get("name") or found.get("site"):
        return found
    reader = front_reader or _mac_front_app
    try:
        live = reader()
    except Exception:
        live = None
    if not isinstance(live, dict):
        return {}
    return identify_app(live, screenshot)


def _mac_front_app():
    """Front app identity from AppKit. There is no screenshot and no socket."""
    try:
        from AppKit import NSWorkspace
    except Exception:
        return None
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return None
    url = app.bundleURL()
    path = ""
    if url is not None:
        path = str(url.path() or "")
    return {
        "name": str(app.localizedName() or ""),
        "bundle_id": str(app.bundleIdentifier() or ""),
        "path": path,
    }


def _log_attempt(folder, moment, path, bundle_id, field, command, output, answer, cap):
    payload = {
        "timestamp": _stamp(moment),
        "input": {
            "command": command,
            "path": trim_text(redact(path), cap),
            "bundle_id": trim_text(redact(bundle_id), cap),
            "field": field or "",
        },
        "output": trim_text(redact(output), cap),
        "answer": trim_text(redact(answer), cap),
    }
    return _write_log(folder, payload)


def _write_log(folder, payload):
    os.makedirs(folder, exist_ok=True)
    try:
        os.chmod(folder, 0o700)
    except OSError:
        pass
    name = "{0}-{1}.json".format(_file_stamp(), uuid.uuid4().hex[:8])
    path = os.path.join(folder, name)
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.write("\n")
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        raise
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def _file_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _stamp(moment):
    return _as_utc(moment).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_utc(moment):
    if moment is None:
        return datetime.now(timezone.utc)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _absolute_tool(path):
    if not isinstance(path, str):
        return False
    text = path.strip()
    if not text.startswith("/") or "\x00" in text or "\n" in text or "\r" in text:
        return False
    return True


def _tokens(text):
    return [part for part in re.split(r"[^A-Za-z0-9]+", (text or "").lower()) if part]


def _is_user_data_key(key):
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", str(key).lower()) if part]
    return any(part in _USER_DATA_WORDS for part in parts)


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _entropy_replacement(match):
    part = match.group(0)
    if re.fullmatch(r"[0-9a-fA-F]+", part):
        return part
    if re.search(r"[A-Za-z]", part) and re.search(r"\d", part) and len(set(part)) >= 8:
        return "[redacted]"
    return part
