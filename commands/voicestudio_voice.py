"""Local VoiceStudio adapter, using the running app's OpenAPI 0.5.7 API."""
import hashlib
import io
import os
import tempfile
import time
import wave

import requests

from .fish_voice import strip_fish_cues

BASE_URL = "http://localhost:3900"
MODEL = "omnivoice"
MODEL_REPO = "k2-fsa/OmniVoice"


def provider():
    return os.environ.get("JEV_TTS_PROVIDER", "FISH").strip().upper()


def fetch_speech(text, cache_dir):
    """Return (WAV path, synthesis milliseconds, cached), without installing models.

    A model/consent failure raises to the caller, which retains Fish fallback.
    Never select an engine implicitly: the installed OmniVoice model is required.
    """
    voice = os.environ.get("JEV_VOICESTUDIO_VOICE", "default")
    body = {"model": MODEL, "input": strip_fish_cues(text),
            "voice": voice, "response_format": "wav"}
    key = hashlib.sha256(repr(sorted(body.items())).encode()).hexdigest()
    folder = os.path.join(cache_dir, "voicestudio")
    path = os.path.join(folder, key + ".wav")
    if os.path.isfile(path):
        return path, 0, True
    with requests.Session() as session:
        session.trust_env = False  # Loopback speech never goes through a proxy.
        response = session.get(BASE_URL + "/models", timeout=10)
        response.raise_for_status()
        model = next((m for m in response.json()["models"]
                      if m["repo_id"] == MODEL_REPO), {})
        if not model.get("installed") or model.get("incomplete"):
            raise RuntimeError("VoiceStudio OmniVoice model is not fully installed; download requires Fernando")
        consent = model.get("license_acceptance", {})
        if consent.get("required") and not consent.get("accepted"):
            raise RuntimeError("VoiceStudio model consent requires Fernando")
        started = time.monotonic()
        response = session.post(BASE_URL + "/v1/audio/speech", json=body, timeout=(5, 180))
        response.raise_for_status()
        content = response.content
        elapsed = int((time.monotonic() - started) * 1000)
    with wave.open(io.BytesIO(content), "rb") as wav:
        if wav.getnframes() == 0:
            raise ValueError("VoiceStudio returned empty audio")
    os.makedirs(folder, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, suffix=".wav", delete=False) as output:
            temporary = output.name
            output.write(content)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    print("  voicestudio: {}ms ({} / {})".format(elapsed, MODEL, voice), flush=True)
    return path, elapsed, False
