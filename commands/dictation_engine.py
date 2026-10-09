"""Which cloud model types dictation, and how a chunk is sent.

OpenAI stays the default: gpt-4o-mini-transcribe, direct when an OpenAI key
is saved, otherwise through OpenRouter. "use scribe for dictation" switches
to ElevenLabs Scribe v2 on OpenRouter's speech-to-text endpoint. That call
uses the OpenRouter key already in the Keychain. No second key.

Confirmed against OpenRouter's docs (October 2026):

- model slug: elevenlabs/scribe-v2
- endpoint: POST https://openrouter.ai/api/v1/audio/transcriptions
- JSON body: model, optional language, input_audio.data (base64), input_audio.format

The model page lists $0.000031 per second of audio. The endpoints API shows
the same ElevenLabs route as live. This module never opens a socket itself
unless the default poster is used. Tests pass their own poster.

Wake-word and command transcription stay on local Whisper. This file does
not load that model. A Scribe failure tries the OpenAI path, then a local
callable the caller supplies, and prints one line about which one ran.
"""
import base64
import os
import time

from .config import DICTATION_ENGINE_PATH

# OpenRouter slug. Not the ElevenLabs native id.
SCRIBE_MODEL = "elevenlabs/scribe-v2"
OPENAI_MODEL = "openai/gpt-4o-mini-transcribe"
OPENROUTER_TRANSCRIPTIONS_URL = "https://openrouter.ai/api/v1/audio/transcriptions"
OPENAI_TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"
# Page price is per second. $0.000031 * 60 = $0.00186 per audio minute.
# Listed next to a struck-through $0.000061/second through 19 Oct 2026.
SCRIBE_USD_PER_SECOND = 0.000031

PROMPT = (
    "The following is a transcript of a person talking, you can remove and duplicated words and any fillers words. "
    "If its a longer transcript put into paragraphs for better readability."
)

DICTATION_ENGINE_KEYS = frozenset({"dictation_scribe", "dictation_openai"})
ENGINES = ("openai", "scribe")

FALLBACK_OPENAI = "  dictation: scribe failed, using openai"
FALLBACK_WHISPER = "  dictation: scribe failed, using local whisper"
FALLBACK_FAILED = "  dictation: scribe failed, local whisper failed"

_path_override = None


def set_dictation_engine_path(path):
    """Tests point this at a temp file. None uses the real support folder."""
    global _path_override
    _path_override = path


def _engine_path(path):
    if path:
        return path
    if _path_override:
        return _path_override
    return DICTATION_ENGINE_PATH


def dictation_engine(path=None):
    """'scribe' when that was saved. Anything else, including a missing file, is openai."""
    try:
        with open(_engine_path(path), encoding="utf-8") as handle:
            saved = handle.read().strip().lower()
    except OSError:
        return "openai"
    if saved == "scribe":
        return "scribe"
    return "openai"


def set_dictation_engine(engine, path=None):
    """Save openai or scribe and return the sentence to speak."""
    choice = str(engine or "").strip().lower()
    if choice not in ENGINES:
        return "Dictation can use OpenAI or Scribe."
    dest = _engine_path(path)
    folder = os.path.dirname(dest)
    try:
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = dest + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(choice + "\n")
        os.replace(tmp, dest)
    except OSError:
        return "I couldn't save the dictation engine."
    if choice == "scribe":
        return "Dictation will use Scribe."
    return "Dictation will use OpenAI."


def scribe_body(wav_bytes):
    """JSON body for Scribe v2. The prompt is an OpenAI option and is not sent."""
    return {
        "model": SCRIBE_MODEL,
        "language": "en",
        "input_audio": {
            "data": base64.b64encode(wav_bytes).decode("ascii"),
            "format": "wav",
        },
    }


def openrouter_openai_body(wav_bytes):
    """The existing OpenRouter request for gpt-4o-mini-transcribe."""
    return {
        "model": OPENAI_MODEL,
        "language": "en",
        "provider": {"options": {"openai": {"prompt": PROMPT}}},
        "input_audio": {
            "data": base64.b64encode(wav_bytes).decode("ascii"),
            "format": "wav",
        },
    }


def _post(url, headers, data=None, files=None, json_body=None, timeout=90):
    import requests
    kwargs = {"headers": headers, "timeout": timeout}
    if data is not None:
        kwargs["data"] = data
    if files is not None:
        kwargs["files"] = files
    if json_body is not None:
        kwargs["json"] = json_body
    return requests.post(url, **kwargs)


def _pair(keys):
    got = keys() if callable(keys) else keys
    if not got:
        return "", ""
    openai_key = got[0] or ""
    openrouter_key = got[1] if len(got) > 1 and got[1] else ""
    return openai_key, openrouter_key


def _text_of(response):
    return response.json().get("text", "").strip()


def _stop_retrying(exc, attempt):
    """Same rule as the old loop: give up on the third try, or on a 4xx other than 429."""
    if attempt == 2:
        return True
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status is None:
        return False
    return status < 500 and status != 429


def _post_openai(wav_bytes, keys, post, log_errors):
    openai_key, openrouter_key = _pair(keys)
    if openai_key:
        response = post(
            OPENAI_TRANSCRIPTIONS_URL,
            headers={"Authorization": "Bearer {0}".format(openai_key)},
            data={"model": OPENAI_MODEL.split("/")[1], "language": "en", "prompt": PROMPT},
            files={"file": ("dictation.wav", wav_bytes, "audio/wav")},
            json_body=None,
            timeout=90,
        )
        label = "openai"
    else:
        response = post(
            OPENROUTER_TRANSCRIPTIONS_URL,
            headers={"Authorization": "Bearer {0}".format(openrouter_key)},
            data=None,
            files=None,
            json_body=openrouter_openai_body(wav_bytes),
            timeout=90,
        )
        label = "openrouter"
    if not response.ok and log_errors:
        print("  {0} said: {1} {2}".format(label, response.status_code, response.text[:200]))
    response.raise_for_status()
    return _text_of(response)


def _openai_path(wav_bytes, keys, post, sleep, log_errors):
    for attempt in range(3):
        try:
            return _post_openai(wav_bytes, keys, post, log_errors)
        except Exception as exc:
            if _stop_retrying(exc, attempt):
                raise
            sleep(2 ** attempt)
    raise RuntimeError("dictation failed")


def _scribe_once(wav_bytes, keys, post):
    _openai_key, openrouter_key = _pair(keys)
    if not openrouter_key:
        raise RuntimeError("scribe needs an OpenRouter key")
    response = post(
        OPENROUTER_TRANSCRIPTIONS_URL,
        headers={"Authorization": "Bearer {0}".format(openrouter_key)},
        data=None,
        files=None,
        json_body=scribe_body(wav_bytes),
        timeout=90,
    )
    response.raise_for_status()
    return _text_of(response)


def _call_local(local):
    if local is None:
        raise RuntimeError("local whisper is not available")
    text = local()
    if text is None:
        raise RuntimeError("local whisper is not available")
    return str(text).strip()


def transcribe_wav(wav_bytes, keys, engine="openai", post=None, local=None, sleep=None, save_failed=None):
    """Transcribe one wav. Scribe falls back to OpenAI, then local, with one log line.

    `post` replaces the HTTP call in tests. `local` is the Whisper fallback and
    is not used for the OpenAI engine. `save_failed` runs only when nothing
    returned text.
    """
    poster = post or _post
    pause = sleep or time.sleep
    if str(engine or "").strip().lower() == "scribe":
        try:
            return _scribe_once(wav_bytes, keys, poster)
        except Exception:
            pass
        try:
            text = _openai_path(wav_bytes, keys, poster, pause, False)
        except Exception:
            text = None
        else:
            print(FALLBACK_OPENAI)
            return text
        try:
            text = _call_local(local)
        except Exception:
            print(FALLBACK_FAILED)
            if save_failed is not None:
                save_failed()
            raise
        print(FALLBACK_WHISPER)
        return text
    try:
        return _openai_path(wav_bytes, keys, poster, pause, True)
    except Exception:
        if save_failed is not None:
            save_failed()
        raise
