"""Analyze the front app with REA. Read-only. Mac-only. Not on the bridge.

The only command that may be spawned is ``analyze``. The app path is its own
argv element. Node and the REA script are configurable; their versions are
pinned and checked before analyze runs. Anything else is refused first.

A missing, unreadable, or invalid local blocklist refuses every run. Money
apps are also refused by generic words and by salted hashes of bundle-id
prefixes and domains. Browsers are refused, because this version does not
know the site. Every com.apple bundle is refused. Work apps and a child's
other apps come from the local file, which is not in this public repo. A
configured kids learning app is analyzed as structure only: progress and
user fields are dropped.

Output is redacted before it is spoken or logged. The spoken line is short.
The local log keeps the longer text. Logs stay on this Mac for 7 days. A
refused run logs a timestamp and the word refused.
This module does not listen, and it does not call a paid API. A screenshot
is used only to name the app. Its pixels are never read.
"""
import errno
import hashlib
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
# Fragments that still match inside a longer token (banking, loanapp, payroll).
_MONEY_SUBSTRINGS = (
    "bank", "credit", "invest", "brokerage", "finance", "loan", "pay", "wallet",
)
# Whole tokens only. "mint" matches Mint and Mints, not mintty.
_MONEY_TOKENS = (
    "budget", "tax", "crypto", "coin", "bitcoin", "stock", "trade",
    "money", "cash", "venmo", "mint", "robinhood",
)
_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
_CAMEL_ACRONYM = re.compile(r"([A-Z]+)([A-Z][a-z])")
# Two-label public suffixes. A hash of one of these would match too widely.
_PUBLIC_SUFFIXES = frozenset({
    "ca.gov", "co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au",
    "co.jp", "com.br", "co.nz", "com.mx", "gov.au",
})
_BROWSER_LABELS = frozenset({
    "safari", "chrome", "chromium", "firefox", "edge", "edgemac", "arc",
    "brave", "opera", "vivaldi", "orion", "duckduckgo", "waterfox",
    "librewolf", "torbrowser", "browser", "sigmaos", "palemoon", "floorp",
})
_BROWSER_PREFIXES = (
    "com.apple.safari",
    "com.google.chrome",
    "org.mozilla.firefox",
    "org.mozilla.nightly",
    "com.microsoft.edgemac",
    "com.microsoft.edge",
    "company.thebrowser.browser",
    "company.thebrowser.dia",
    "com.brave.browser",
    "com.operasoftware.opera",
    "com.vivaldi.vivaldi",
    "org.chromium.chromium",
    "com.kagi.kagimacos",
    "org.torproject.torbrowser",
    "com.duckduckgo.macos.browser",
    "org.waterfoxproject.waterfox",
    "org.mozilla.librewolf",
    "com.sigmaos.sigmaos",
)
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


def resolve_spoken_cap(value=None):
    """Character cap for the line that is spoken. The log can be longer."""
    if value is None:
        return config.REA_SPOKEN_CAP
    try:
        cap = int(value)
    except (TypeError, ValueError):
        return config.REA_SPOKEN_CAP
    if cap < 1:
        return config.REA_SPOKEN_CAP
    return cap


def resolve_output_cap(value=None):
    """Character cap for text kept in the local log."""
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


def money_hash_path():
    """Shipped salt and digests. The file has no plaintext ids."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "rea_money_hashes.json")


def load_blocklist(path):
    """Local rules, or None when the file is missing, unreadable, or invalid.

    None fails closed: the command refuses every run. A JSON object that
    omits a list is valid and incomplete. Built-in rules still apply.
    """
    rules = {
        "blocked_bundle_ids": [],
        "blocked_names": [],
        "blocked_sites": [],
        "kids_app_ids": [],
    }
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, UnicodeError):
        return None
    if not isinstance(data, dict):
        return None
    for key in rules:
        if key not in data or data[key] is None:
            continue
        value = data[key]
        if not isinstance(value, list):
            return None
        cleaned = []
        for item in value:
            if not isinstance(item, str):
                return None
            text = item.strip()
            if text:
                cleaned.append(text)
        rules[key] = cleaned
    return rules


def is_finance(identity):
    """True when a bundle id, name, site, or path is a money app.

    ``budget``, ``tax``, ``crypto``, ``coin``, ``bitcoin``, ``stock``,
    ``trade``, ``money``, ``cash``, ``venmo``, ``mint``, and ``robinhood``
    match a whole token, that token plus ``s`` or ``es`` (``Stocks``, ``Coins``,
    ``Taxes``), or that token plus ``ing`` (``Budgeting``, ``stocking``).
    A word that ends in ``e`` also matches with that ``e`` dropped, so
    ``trade`` matches ``trading``. Tokens split on dots, dashes,
    underscores, spaces, and camelCase. ``mint`` does not match ``mintty``:
    that is a different word that only contains the letters. The same rule
    leaves ``taxi``, ``stockade``, and ``trademark`` alone. Older fragments
    such as ``bank`` and ``pay`` still match inside a longer token, so
    ``banking`` stays refused.
    """
    parts = []
    for key in ("bundle_id", "name", "site", "path"):
        parts.append(identity.get(key) or "")
    blob = " ".join(parts).lower()
    if any(word in blob for word in _MONEY_SUBSTRINGS):
        return True
    for key in ("bundle_id", "name", "site", "path"):
        for token in _money_tokens(identity.get(key)):
            if _is_money_token(token):
                return True
    return False


def is_browser(identity):
    """True for Safari, Chrome, Firefox, Edge, Arc, Brave, and similar apps."""
    bundle = (identity.get("bundle_id") or "").strip().lower()
    if bundle:
        for prefix in _BROWSER_PREFIXES:
            if bundle == prefix or bundle.startswith(prefix + "."):
                return True
        if any(label in _BROWSER_LABELS for label in bundle.split(".")):
            return True
    for key in ("name", "path"):
        if any(part in _BROWSER_LABELS for part in _tokens(identity.get(key))):
            return True
    return False


def is_apple_bundle(identity):
    """True for every com.apple bundle id."""
    bundle = (identity.get("bundle_id") or "").strip().lower()
    return bundle == "com.apple" or bundle.startswith("com.apple.")


def hash_money_value(text, salt):
    """Salted SHA-256 hex of one normalized prefix or domain. Empty when unusable."""
    if not isinstance(text, str) or not text:
        return ""
    if not isinstance(salt, str) or not re.fullmatch(r"[0-9a-fA-F]{16,}", salt) or len(salt) % 2:
        return ""
    digest = hashlib.sha256(bytes.fromhex(salt) + b"\0" + text.encode("utf-8"))
    return digest.hexdigest()


def money_forms(value):
    """Dot prefixes and suffixes with at least two labels.

    A single label such as ``com`` is never returned. Public suffixes such as
    ``ca.gov`` are never returned, so a state portal does not match every
    government host.
    """
    text = _normalize_host(value)
    labels = [part for part in text.split(".") if part]
    found = []
    seen = set()
    for end in range(2, len(labels) + 1):
        _add_form(found, seen, ".".join(labels[:end]))
    for start in range(0, len(labels) - 1):
        _add_form(found, seen, ".".join(labels[start:]))
    return found


def candidate_forms(identity):
    """Forms of the front app's bundle id and site."""
    found = []
    seen = set()
    bundle = (identity.get("bundle_id") or "").strip().lower()
    for form in money_forms(bundle):
        _add_form(found, seen, form)
    for form in money_forms(_normalize_host(identity.get("site"))):
        _add_form(found, seen, form)
    return found


def hash_money_ids(bundle_ids, domains, salt):
    """Sorted unique digests for bundle-id prefixes and domains."""
    forms = []
    seen = set()
    for bundle in bundle_ids or []:
        for form in money_forms(bundle):
            _add_form(forms, seen, form)
    for domain in domains or []:
        for form in money_forms(domain):
            _add_form(forms, seen, form)
    hashes = []
    used = set()
    for form in forms:
        digest = hash_money_value(form, salt)
        if digest and digest not in used:
            used.add(digest)
            hashes.append(digest)
    hashes.sort()
    return hashes


def hashes_for_id_file(path, salt=None):
    """Read a local id file and return ``{"salt", "hashes"}``.

    The id file is not copied into the result. A broken file raises ValueError.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, UnicodeError):
        raise ValueError("unreadable")
    if not isinstance(data, dict):
        raise ValueError("shape")
    bundles = _string_list(data.get("bundle_ids"))
    domains = _string_list(data.get("domains"))
    if bundles is None or domains is None:
        raise ValueError("shape")
    if salt is None:
        table = load_money_table(money_hash_path())
        salt = table.get("salt") or ""
    if not salt:
        raise ValueError("salt")
    return {"salt": salt.lower(), "hashes": hash_money_ids(bundles, domains, salt)}


def load_money_table(path=None):
    """Salt and digests. A broken file yields an empty table, not a crash."""
    empty = {"salt": "", "hashes": frozenset()}
    target = path or money_hash_path()
    try:
        with open(target, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, UnicodeError):
        return empty
    if not isinstance(data, dict):
        return empty
    salt = data.get("salt")
    hashes = data.get("hashes")
    if not isinstance(salt, str) or not isinstance(hashes, list):
        return empty
    salt = salt.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{16,}", salt) or len(salt) % 2:
        return empty
    clean = []
    for item in hashes:
        if isinstance(item, str) and re.fullmatch(r"[0-9a-fA-F]{64}", item):
            clean.append(item.lower())
    return {"salt": salt, "hashes": frozenset(clean)}


def builtin_money_table():
    """The shipped table. Loaded once."""
    cached = getattr(builtin_money_table, "_cache", None)
    if cached is None:
        cached = load_money_table(money_hash_path())
        builtin_money_table._cache = cached
    return cached


def is_builtin_money(identity, table=None):
    """True for a money word or a salted hash of a bundle prefix or domain."""
    if is_finance(identity):
        return True
    chosen = builtin_money_table() if table is None else table
    if not isinstance(chosen, dict):
        return False
    salt = chosen.get("salt") or ""
    hashes = chosen.get("hashes") or ()
    if not salt or not hashes:
        return False
    for form in candidate_forms(identity):
        digest = hash_money_value(form, salt)
        if digest and digest in hashes:
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


def access_decision(identity, rules, money=None):
    """``refuse``, ``structure``, or ``analyze``. Money apps are never analyzed."""
    if is_browser(identity) or is_apple_bundle(identity) or is_builtin_money(identity, money):
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
                      exists=None, front_reader=None, spoken_cap=None, money=None):
    """Speak one local answer. REA is spawned only after the blocklist says yes.

    The return value is LocalSpeech so the words stay on the Mac ``say``
    command. Cleanup of logs older than 7 days runs on every Mac invocation.
    A missing or invalid blocklist refuses the run before any app is read.
    """
    if (platform or sys.platform) != "darwin":
        return LocalSpeech(NOT_MAC)
    try:
        return _analyze(
            text, front, screenshot, run, blocklist_path, log_dir, now, timeout,
            output_cap, node_path, script_path, exists, front_reader, spoken_cap,
            money,
        )
    except Exception as exc:
        if isinstance(exc, AssertionError):
            raise
        return LocalSpeech(GENERIC)


def _analyze(text, front, screenshot, run, blocklist_path, log_dir, now, timeout,
             output_cap, node_path, script_path, exists, front_reader, spoken_cap,
             money):
    moment = _as_utc(now)
    folder = log_dir or config.REA_LOG_DIR
    cap = resolve_output_cap(output_cap)
    spoken_limit = min(resolve_spoken_cap(spoken_cap), cap)
    cleanup_logs(folder, moment)
    rules = load_blocklist(blocklist_path if blocklist_path is not None else config.REA_BLOCKLIST_PATH)
    if rules is None:
        log_refused(folder, moment)
        return LocalSpeech(REFUSAL)
    identity = _identity(front, screenshot, front_reader)
    if not identity:
        return LocalSpeech(NO_APP)
    decision = access_decision(identity, rules, money)
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
    return LocalSpeech(trim_text(redact(answer), spoken_limit))


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


def _money_tokens(text):
    """Words split on punctuation and camelCase. The case split happens first."""
    if not text:
        return []
    spaced = _CAMEL_BOUNDARY.sub(r"\1 \2", str(text))
    spaced = _CAMEL_ACRONYM.sub(r"\1 \2", spaced)
    return [part.lower() for part in re.split(r"[^A-Za-z0-9]+", spaced) if part]


def _is_money_token(token):
    """Exact token, a simple plural (s or es), or an ``-ing`` form.

    ``budget`` matches ``budgeting``. ``trade`` matches ``trading`` because
    a trailing ``e`` is dropped before ``ing``. ``stocking`` matches
    ``stock``. A longer word such as ``mintty`` does not match.
    """
    for word in _MONEY_TOKENS:
        if token == word or token == word + "s" or token == word + "es":
            return True
        if token == word + "ing":
            return True
        if word.endswith("e") and token == word[:-1] + "ing":
            return True
    return False


def _normalize_host(value):
    text = (value or "").strip().lower()
    text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", text)
    text = text.split("/")[0].split("?")[0].split("#")[0]
    if "@" in text:
        text = text.rsplit("@", 1)[-1]
    if text.count(":") == 1:
        text = text.split(":", 1)[0]
    if text.startswith("www."):
        text = text[4:]
    return text.strip(".")


def _add_form(found, seen, form):
    if not form or form in seen or form in _PUBLIC_SUFFIXES:
        return
    if form.count(".") < 1:
        return
    seen.add(form)
    found.append(form)


def _string_list(value):
    """A list of strings, an empty list when the key is absent, or None."""
    if value is None:
        return []
    if not isinstance(value, list):
        return None
    cleaned = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            return None
        cleaned.append(item.strip())
    return cleaned


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
