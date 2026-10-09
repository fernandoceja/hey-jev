"""Optional Fish Audio Drama 3 voice. Off unless a local file says dramatic.

The Text to Speech API picks the model with the ``model`` request header
(https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech).
Drama 3 is ``drama-3-preview``. Directions travel in the ``text`` field:
square brackets such as ``[warm and relaxed]`` or ``[sigh]``, and paired
tags such as ``<whisper>go on</whisper>`` for a few words
(https://fish.audio/drama-3/).

The voice id stays the one siri.py already sends as ``reference_id``.
The API key stays in the Keychain and is passed in by the caller.

If the ``model`` header is omitted or unrecognized, Fish serves ``s2.1-pro``
(the paid model). A failed Drama 3 call therefore retries with the header
set to ``s2.1-pro-free``, which is the model this app already uses. Cue
text is removed from that retry so a tag cannot be spoken as words.

A 401, 402, or 403 is different. Drama 3 stays off for the rest of this
process, the voice-mode file is left as it was, and one line is logged.
Playback says this once, before the reply, and later lines skip Drama 3:

    Dramatic voice isn't available on your Fish Audio plan right now, so I'm using my normal voice.

Timeouts and 5xx responses still fall back one call at a time.
"""
import hashlib
import os
import re
import threading
import time

from .config import VOICE_MODE_PATH

FISH_TTS_URL = "https://api.fish.audio/v1/tts"
# Current Hey Jev voice. Also the explicit fallback. Do not leave the header
# off: Fish would answer with paid s2.1-pro.
FISH_MODEL = "s2.1-pro-free"
DRAMA_MODEL = "drama-3-preview"
FISH_TTS_TIMEOUT = 60
# Fish plan and auth failures. After the first one, Drama 3 is not tried again
# until the process starts over. The saved voice setting is not changed.
DRAMA_PLAN_STATUSES = (401, 402, 403)
DRAMA_PLAN_NOTICE = (
    "Dramatic voice isn't available on your Fish Audio plan right now, "
    "so I'm using my normal voice."
)
# Light default direction. The Drama 3 page uses this phrasing.
DEFAULT_CUE = "[warm and relaxed]"

VOICE_DRAMATIC = "voice_dramatic"
VOICE_NORMAL = "voice_normal"
VOICE_WHICH = "voice_which"

_BRACKET_CUE = re.compile(r"\[[^\[\]]{1,240}\]")
# Paired emphasis. The Drama 3 page's API example is <whisper>...</whisper>.
# The tag menu also lists emphasis, soft, faster, slower, stress, forceful.
# Any other single-word paired tag is removed the same way, keeping the words.
_PAIRED_CUE = re.compile(
    r"<\s*([A-Za-z][A-Za-z0-9]*)\s*>(.*?)<\s*/\s*\1\s*>",
    re.I | re.S,
)
_LOOSE_TAG = re.compile(
    r"</?\s*(?:whisper|emphasis|soft|faster|slower|stress|forceful)\s*/?\s*>",
    re.I,
)

_lock = threading.Lock()
_path_override = None
# In-memory only. A relaunch tries Drama 3 again if the file still says dramatic.
_drama_session_blocked = False
_drama_notice_pending = False


class Speech(object):
    """A wav that is ready to play. ``fell_back`` means Drama 3 was not used."""

    def __init__(self, path, ms, cached, model, text, fell_back):
        self.path = path
        self.ms = ms
        self.cached = cached
        self.model = model
        self.text = text
        self.fell_back = fell_back


def set_voice_mode_path(path):
    """Tests point this at a temp file. None uses the real support folder."""
    global _path_override
    with _lock:
        _path_override = path


def reset_drama_session():
    """Forget a plan block. Tests use this. A real session ends when the app quits."""
    global _drama_session_blocked, _drama_notice_pending
    with _lock:
        _drama_session_blocked = False
        _drama_notice_pending = False


def _drama_blocked():
    with _lock:
        return _drama_session_blocked


def _mark_drama_blocked():
    """Remember the plan block. True only for the call that hits it first."""
    global _drama_session_blocked, _drama_notice_pending
    with _lock:
        first = not _drama_session_blocked
        _drama_session_blocked = True
        if first:
            _drama_notice_pending = True
        return first


def _claim_drama_notice():
    """The sentence Jev says once, or "" after it has been claimed."""
    global _drama_notice_pending
    with _lock:
        if not _drama_notice_pending:
            return ""
        _drama_notice_pending = False
        return DRAMA_PLAN_NOTICE


def _restore_drama_notice(notice):
    """Put the sentence back when the normal model never got to speak it."""
    global _drama_notice_pending
    if notice != DRAMA_PLAN_NOTICE:
        return
    with _lock:
        _drama_notice_pending = True


def _http_status(exc):
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    if not isinstance(code, int):
        code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    return None


def _drama_plan_denied(exc):
    return _http_status(exc) in DRAMA_PLAN_STATUSES


def claim_drama_plan_notice():
    """The sentence to say once after a plan block, or "" if it was already taken."""
    return _claim_drama_notice()


def _path():
    return _path_override or VOICE_MODE_PATH


def dramatic_voice_enabled():
    """True only when the flag file says dramatic. A missing file is off."""
    try:
        with open(_path(), encoding="utf-8") as handle:
            return handle.read().strip().lower() == "dramatic"
    except OSError:
        return False


def _write_dramatic(on):
    path = _path()
    folder = os.path.dirname(path)
    try:
        if folder:
            os.makedirs(folder, exist_ok=True)
        if not on:
            try:
                os.remove(path)
            except FileNotFoundError:
                return True
            except OSError:
                return False
            return True
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write("dramatic\n")
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def use_dramatic_voice():
    """Turn Drama 3 on and remember it. Already on is a no-op."""
    with _lock:
        if dramatic_voice_enabled():
            return "You're already using the dramatic voice."
        if not _write_dramatic(True):
            return "I couldn't save the voice setting."
        return "Dramatic voice is on."


def use_normal_voice():
    """Turn Drama 3 off. Already off is a no-op."""
    with _lock:
        if not dramatic_voice_enabled():
            return "You're already using the normal voice."
        if not _write_dramatic(False):
            return "I couldn't save the voice setting."
        return "Normal voice is on."


def which_voice():
    """Say which model the next reply will use."""
    if dramatic_voice_enabled():
        return "I'm using the dramatic voice."
    return "I'm using the normal voice."


def strip_fish_cues(text):
    """Words only. Bracket directions and paired emphasis tags are removed.

    The words inside a paired tag stay. Those are the words to speak.
    The tag name does not.
    """
    out = text or ""
    for _ in range(6):
        nxt = _PAIRED_CUE.sub(lambda match: match.group(2), out)
        nxt = _LOOSE_TAG.sub(" ", nxt)
        nxt = _BRACKET_CUE.sub(" ", nxt)
        if nxt == out:
            break
        out = nxt
    return re.sub(r"\s+", " ", out).strip()


def with_default_cue(text):
    """Put the light Drama 3 direction at the front of a line."""
    body = (text or "").strip()
    if body.lower().startswith(DEFAULT_CUE.lower()):
        return body
    if not body:
        return DEFAULT_CUE
    return DEFAULT_CUE + " " + body


def speech_request(text, dramatic):
    """The model header value and the text body for one Fish call."""
    if dramatic:
        return {"model": DRAMA_MODEL, "text": with_default_cue(text)}
    return {"model": FISH_MODEL, "text": text or ""}


def cache_token(voice_id, model, text):
    """Disk-cache key. The normal model keeps the historical ``voice|text`` form."""
    if model == FISH_MODEL:
        return "{0}|{1}".format(voice_id, text)
    return "{0}|{1}|{2}".format(voice_id, model, text)


def cache_path(cache_dir, voice_id, model, text):
    name = hashlib.sha1(cache_token(voice_id, model, text).encode("utf-8")).hexdigest()
    return os.path.join(cache_dir, name + ".wav")


def fish_failure_reason(exc):
    """A short reason that cannot include the API key or the reply text."""
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    name = type(exc).__name__
    if isinstance(code, int):
        return "{0} {1}".format(name, code)
    return name


def _read_cached(path):
    try:
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return path
    except OSError:
        return None
    return None


def _store(path, content):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as handle:
        handle.write(content)
    os.replace(tmp, path)


def _post_audio(post, model, text, api_key, voice_id, timeout):
    response = post(
        FISH_TTS_URL,
        headers={
            "Authorization": "Bearer {0}".format(api_key),
            "Content-Type": "application/json",
            "model": model,
        },
        json={"text": text, "reference_id": voice_id, "format": "wav"},
        timeout=timeout,
    )
    raiser = getattr(response, "raise_for_status", None)
    if raiser is not None:
        raiser()
    elif getattr(response, "status_code", 200) >= 400:
        error = RuntimeError("fish status {0}".format(response.status_code))
        error.response = response
        raise error
    content = getattr(response, "content", None)
    if isinstance(content, str):
        content = content.encode("utf-8")
    if not isinstance(content, (bytes, bytearray)) or not bytes(content):
        raise ValueError("empty audio")
    return bytes(content)


def _speak_saved(path, model, text, ms, cached, fell_back):
    return Speech(path, ms, cached, model, text, fell_back)


def _speak_normal(text, post, api_key, voice_id, cache_dir, timeout, log, log_failure=True):
    """One normal-model call, with cues removed.

    A Speech means audio is ready. A string means the normal model failed
    (the failure reason). None means there was nothing left to speak.
    The plan sentence is not part of this audio. Playback says it once.
    """
    spoken = strip_fish_cues(text)
    if not spoken:
        return None
    started = time.time()
    outcome = _fallback(spoken, post, api_key, voice_id, cache_dir, timeout, started)
    if isinstance(outcome, Speech):
        return outcome
    if log_failure:
        log("  fish: {0} failed ({1})".format(FISH_MODEL, outcome))
        return None
    return outcome


def _block_drama(text, exc, post, api_key, voice_id, cache_dir, timeout, log):
    """Plan or auth failure: log once, then the normal model.

    The voice-mode file is not written. Playback says the plan sentence once.
    Later calls skip Drama 3 entirely.
    """
    reason = fish_failure_reason(exc)
    first = _mark_drama_blocked()
    outcome = _speak_normal(
        text, post, api_key, voice_id, cache_dir, timeout, log, log_failure=False,
    )
    if isinstance(outcome, Speech):
        if first:
            log("  fish: {0} failed ({1}), using {2} for the rest of this session".format(
                DRAMA_MODEL, reason, FISH_MODEL))
        return outcome
    if first:
        extra = ""
        if outcome:
            extra = "; {0} also failed ({1})".format(FISH_MODEL, outcome)
        log("  fish: {0} failed ({1}), using {2} for the rest of this session{3}".format(
            DRAMA_MODEL, reason, FISH_MODEL, extra))
        return None
    if outcome:
        log("  fish: {0} failed ({1})".format(FISH_MODEL, outcome))
    return None


def synthesize_speech(text, post, api_key, voice_id, dramatic, cache_dir, timeout=FISH_TTS_TIMEOUT, log=print):
    """Return a Speech, or None when Fish could not produce audio.

    Drama 3 errors and timeouts retry on ``s2.1-pro-free`` with cues removed.
    A 401, 402, or 403 disables Drama 3 for the rest of this process instead
    of retrying it on the next line. This function does not raise for those
    failures, and it does not change the saved voice setting.
    """
    if dramatic and _drama_blocked():
        return _speak_normal(text, post, api_key, voice_id, cache_dir, timeout, log)

    primary = speech_request(text, dramatic)
    primary_path = cache_path(cache_dir, voice_id, primary["model"], primary["text"])
    hit = _read_cached(primary_path)
    if hit:
        return _speak_saved(hit, primary["model"], primary["text"], 0, True, False)

    started = time.time()
    try:
        content = _post_audio(post, primary["model"], primary["text"], api_key, voice_id, timeout)
    except Exception as exc:
        if not dramatic:
            log("  fish: {0} failed ({1})".format(FISH_MODEL, fish_failure_reason(exc)))
            return None
        if _drama_plan_denied(exc):
            return _block_drama(text, exc, post, api_key, voice_id, cache_dir, timeout, log)
        reason = fish_failure_reason(exc)
        spoken = strip_fish_cues(text)
        if not spoken:
            log("  fish: {0} failed ({1}), no words left to speak".format(DRAMA_MODEL, reason))
            return None
        outcome = _fallback(spoken, post, api_key, voice_id, cache_dir, timeout, started)
        if isinstance(outcome, Speech):
            log("  fish: {0} failed ({1}), using {2}".format(DRAMA_MODEL, reason, FISH_MODEL))
            return outcome
        log("  fish: {0} failed ({1}); {2} also failed ({3})".format(
            DRAMA_MODEL, reason, FISH_MODEL, outcome))
        return None
    try:
        _store(primary_path, content)
    except OSError as exc:
        log("  fish: {0} failed ({1})".format(primary["model"], type(exc).__name__))
        return None
    ms = int((time.time() - started) * 1000)
    return _speak_saved(primary_path, primary["model"], primary["text"], ms, False, False)


def play_fish_reply(text, fetch, play):
    """Speak one reply. ``fetch(line)`` returns ``(path, ms)``. ``play(path)`` plays a wav.

    The reply is fetched first, because that is the call that can discover a
    plan block. The plan sentence is then fetched and played once, before the
    reply wav, so a cache warmup that never plays audio cannot swallow it.
    A missing notice wav is put back for the next reply that does play.
    """
    path, ms = fetch(text)
    notice = _claim_drama_notice()
    extra = 0
    if notice:
        try:
            notice_path, extra = fetch(notice)
        except Exception:
            _restore_drama_notice(notice)
            raise
        if notice_path:
            play(notice_path)
        else:
            _restore_drama_notice(notice)
            extra = 0
    if path:
        play(path)
    return (ms or 0) + (extra or 0)


def _fallback(spoken, post, api_key, voice_id, cache_dir, timeout, started):
    """Cue-free retry on the current model. A string return is the failure reason."""
    secondary = speech_request(spoken, False)
    path = cache_path(cache_dir, voice_id, secondary["model"], secondary["text"])
    hit = _read_cached(path)
    if hit:
        waited = int((time.time() - started) * 1000)
        return _speak_saved(hit, FISH_MODEL, spoken, waited, True, True)
    try:
        content = _post_audio(post, FISH_MODEL, spoken, api_key, voice_id, timeout)
    except Exception as exc:
        return fish_failure_reason(exc)
    try:
        _store(path, content)
    except OSError as exc:
        return type(exc).__name__
    ms = int((time.time() - started) * 1000)
    return _speak_saved(path, FISH_MODEL, spoken, ms, False, True)
