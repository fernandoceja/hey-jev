"""Choose a local action from the transcript before any API call."""
import re
from .config import JOINER_RE, LOCAL_PATTERNS, STRICT_PATTERNS, _BARE_RUN_RE, _FOCUS_VERBS, _HIDE_VERBS, _IHSS_CMD_RE, _NOTE_CMD_RE, _OPEN_VERBS, _PLEASE, _QUIT_VERBS
from .textutil import _clean
from .confirm import is_private_message_request, is_quit_all
from .apps import known_app_name, parse_app_name, resolve_app, resolve_folder, resolve_site, unclear_app_guess
from .passwords import is_password_lookup
from .tutor import is_tutor_phrase
from .recreate import is_recreate_phrase, is_recreate_status
from .games import is_game_close_phrase, is_game_phrase
from .cleanmymac import is_cleanmymac_phrase
from .fm_serve import offline_brain_action
from .calendar_add import is_calendar_add_phrase
from .mail_voice import mail_action
from .notes_search import is_notes_question
from .dashboard import is_test_results_phrase

from .agent_jobs import is_agent_job_phrase, is_agent_status_phrase
from .shortcuts import jev_shortcut_catalog, parse_shortcut_name, resolve_shortcut

def route_before_api(text):
    """Action key for one local command, or None.

    decide() calls this before TypeSafe and before the LLM. A joiner such as
    "and" returns None so a two-part sentence can still be split, except a
    note or an IHSS line, whose words may contain "and". Message reads always
    match, joiner or not, so that phrase is never sent out.
    """
    raw = _clean(text).strip()
    if not raw:
        return None
    if _NOTE_CMD_RE.match(raw):
        return "note_take"
    if _IHSS_CMD_RE.search(raw):
        return "ihss_log"
    if is_private_message_request(raw):
        return "info_messages"
    # Before the joiner check. "password for Netflix is ..." must not be sent
    # to an API, even when the sentence also says "and".
    if is_password_lookup(raw):
        return "password_lookup"
    # Before the joiner check. "tutor me on sine and cosine" is one explanation.
    # "explain this problem and mute" does not match, so that sentence can still split.
    if is_tutor_phrase(raw):
        return "tutor_explain"
    # Before the joiner check. "recreate airbnb.com and add dark mode" is one job.
    # Mac-only, not in BRIDGE_ALLOW.
    if is_recreate_status(raw):
        return "recreate_status"
    if is_recreate_phrase(raw):
        return "recreate_this"
    # Before the joiner check. "have an agent build X and Y" is one job.
    # Mac-only, not in BRIDGE_ALLOW.
    if is_agent_status_phrase(raw):
        return "agent_status"
    if is_agent_job_phrase(raw):
        return "agent_job"
    # Before the joiner check. "lunch with mom and dad Friday at noon" is one event.
    # Mac-only, not in BRIDGE_ALLOW.
    if is_calendar_add_phrase(raw):
        return "calendar_add"
    # Before the joiner check. A dictated reply may say "and". Draft only, never delivered.
    # Mac-only, not in BRIDGE_ALLOW.
    mail = mail_action(raw)
    if mail:
        return mail
    # Before the joiner check. "notes about Zoe and Maria" is one search. Mac-only, not in BRIDGE_ALLOW.
    if is_notes_question(raw):
        return "notes_ask"
    if JOINER_RE.search(raw):
        return None
    # Game ports. Mac-only, not in BRIDGE_ALLOW.
    if is_game_phrase(raw):
        return "game_open"
    if is_game_close_phrase(raw):
        return "game_close"
    # CleanMyMac Smart Care scan. Scan only. Mac-only, not in BRIDGE_ALLOW.
    # Before the "clean my mac" open-app nickname, which "open CleanMyMac" keeps.
    if is_cleanmymac_phrase(raw):
        return "cleanmymac_scan"
    # Offline brain: start/stop/status of `fm serve` on 127.0.0.1:1976 only.
    # Mac-only, not in BRIDGE_ALLOW. Never started automatically.
    fm_action = offline_brain_action(raw)
    if fm_action:
        return fm_action
    # Test results dashboard. Static local HTML. Mac-only, not in BRIDGE_ALLOW.
    if is_test_results_phrase(raw):
        return "test_results_open"
    for pattern, key in STRICT_PATTERNS:
        if pattern.match(raw):
            return key
    for pattern, key in LOCAL_PATTERNS:
        if not pattern.search(raw):
            continue
        if key == "info_time" and re.search(r"\b(?:in|for)\s+[A-Za-z]", raw, re.I):
            continue
        # "what's the time left" is a timer check, not the clock.
        if key == "info_time" and re.search(r"\b(?:left|remaining|timer|timers)\b", raw, re.I):
            continue
        return key
    opened = route_open_phrase(raw)
    if opened:
        return opened
    named = route_named_app(raw)
    if named:
        return named
    if parse_shortcut_name(raw):
        return "shortcut_run"
    if bare_run_matches_folder(raw):
        return "shortcut_run"
    return None


def preview_action(text):
    """Action key for phrases we answer locally, or None.

    'what time is it in Tokyo' is left for the LLM. A bare 'what time is it' is not.
    """
    return route_before_api(text)


def route_open_phrase(raw):
    """app_open, site_open, or folder_open when the name is one we know. Else None.

    An unknown 'open ...' stays with the LLM so a stray sentence is not launched.
    """
    if not re.match(rf"^{_PLEASE}(?:{_OPEN_VERBS})\b", raw, re.I):
        return None
    spoken = parse_app_name(raw, "open")
    if not spoken or len(spoken.split()) > 6:
        return None
    if resolve_folder(spoken):
        return "folder_open"
    if resolve_site(spoken):
        return "site_open"
    if known_app_name(spoken) or resolve_app(spoken) or unclear_app_guess(spoken):
        return "app_open"
    return None


def route_named_app(raw):
    """app_quit, app_hide, or app_focus when the name resolves the way open does.

    Quit-all is left unmatched so the spoken yes/no stays in charge. close and
    quit name one app. The quit action is a polite terminate(), never a force quit.
    """
    if is_quit_all(raw):
        return None
    if re.search(r"\bfocus\s+mode\b", raw, re.I) or re.match(rf"^{_PLEASE}start\s+focus\b", raw, re.I):
        return None
    routes = (
        (_QUIT_VERBS, "quit", "app_quit"),
        (_HIDE_VERBS, "hide", "app_hide"),
        (_FOCUS_VERBS, "focus", "app_focus"),
    )
    for verbs, kind, action in routes:
        if not re.match(rf"^{_PLEASE}(?:{verbs})\b", raw, re.I):
            continue
        spoken = parse_app_name(raw, kind)
        if not spoken or len(spoken.split()) > 6:
            return None
        if known_app_name(spoken) or resolve_app(spoken) or unclear_app_guess(spoken):
            return action
        return None
    return None


def bare_run_matches_folder(raw):
    """True only when 'run NAME' fuzzy-matches a shortcut verified in the Jev folder.

    'run shortcut NAME' is handled by parse_shortcut_name. A bare 'run ...' that
    does not match the folder is left alone so it can still be a normal sentence.
    """
    if parse_shortcut_name(raw):
        return False
    match = _BARE_RUN_RE.match(raw)
    if not match:
        return False
    spoken = re.sub(r"^(?:the|my|a)\s+", "", match.group(1).strip(" .,!?"), flags=re.I).strip()
    if not spoken or len(spoken.split()) > 6:
        return False
    if re.search(r"\b(?:how|why|what|when|where|who)\b", spoken, re.I):
        return False
    catalog = jev_shortcut_catalog()
    if not catalog:
        return False
    return resolve_shortcut(spoken, list(catalog.values())) is not None
