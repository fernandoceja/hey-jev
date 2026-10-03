"""Spoken yes/no before quit-all and emptying the trash."""
import re
import time
from .config import CONFIRM, CONFIRM_SECONDS, JOINER_RE, NO_RE, QUIT_ALL_ONLY_RE, QUIT_ALL_RE, YES_RE
from .textutil import _clean

_PENDING = {"action": None, "arg": None, "source": None, "reply_key": None, "fmt": None, "expires": 0.0}


# --------------------------------------------------------------------------- Confirmation
def confirmation_pending():
    return bool(_PENDING["action"]) and time.time() < _PENDING["expires"]


def clear_confirmation():
    _PENDING.update(action=None, arg=None, source=None, reply_key=None, fmt=None, expires=0.0)


def arm_confirmation(action, arg, source, reply_key, fmt, seconds=CONFIRM_SECONDS):
    _PENDING.update(action=action, arg=arg, source=source, reply_key=reply_key,
                    fmt=dict(fmt or {}), expires=time.time() + seconds)


def refresh_confirmation(seconds=CONFIRM_SECONDS):
    """Restart the window once the prompt has finished speaking."""
    if _PENDING["action"]:
        _PENDING["expires"] = time.time() + seconds


def confirmation_status(text):
    """Yes/no for a pending confirmation. Local regex only: no network, no Jev.

    Returns 'yes', 'no', 'expired', 'other', or None when nothing is waiting.
    'other' and 'expired' clear the pending action so the utterance is handled normally.
    """
    if not _PENDING["action"]:
        return None
    if time.time() >= _PENDING["expires"]:
        clear_confirmation()
        return "expired"
    stripped = _clean(text).strip()
    if YES_RE.match(stripped):
        return "yes"
    if NO_RE.match(stripped):
        return "no"
    clear_confirmation()
    return "other"


def take_confirmation():
    """Return the armed action and clear it. Call only after confirmation_status says yes."""
    data = (_PENDING["action"], _PENDING["arg"], _PENDING["source"],
            _PENDING["reply_key"], dict(_PENDING["fmt"] or {}))
    clear_confirmation()
    return data


def isolate_confirmations(actions):
    """Drop the other half of a two-part command when one half needs confirmation."""
    if not actions:
        return actions
    hit = [a for a in actions if a[1] in CONFIRM]
    if hit and len(actions) > 1:
        return hit[:1]
    return actions


def is_quit_all(text):
    raw = _clean(text)
    if re.search(r"\b(?:timer|timers|reminder|reminders)\b", raw, re.I):
        return False
    return bool(QUIT_ALL_RE.search(raw))


def quit_all_is_compound(text, jev_compound):
    """True when this utterance asks for something besides quitting every app.

    A bare 'quit all' is allowed even if Jev marks it compound. 'quit all and open Notes'
    is not: confirmation is never one half of a two-part command.
    """
    raw = _clean(text).strip()
    if JOINER_RE.search(raw):
        return True
    only = bool(QUIT_ALL_ONLY_RE.fullmatch(raw))
    return bool(jev_compound) and not only


def is_private_message_request(text):
    """True when this utterance is asking to read messages from My Love.

    The command itself must stay off the network, and the message text must
    never be spoken by Fish or handed to an LLM.
    """
    raw = _clean(text)
    if not re.search(r"\bmy love\b", raw, re.I):
        return False
    return bool(re.search(r"\b(?:messages?|texts?|imessages?)\b", raw, re.I))
