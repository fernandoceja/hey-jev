"""Local speech-to-text hints. No model is loaded here, and nothing listens on a socket.

faster-whisper repeats an initial prompt when the audio is silence. App names
Fernando actually says are passed as hotwords, which is a separate bias, and a
transcript that is only that list is thrown away.
"""
import re

# Whisper's own "this probably isn't speech" score. Above this, the segment is dropped.
NO_SPEECH_MAX = 0.6

# Names the small.en model mishears. Kept as a word list, not a command sentence,
# so silence is less likely to come back as "Open ChatGPT".
WHISPER_HOTWORDS = (
    "ChatGPT, Claude, Grok, Gemini, Perplexity, CapCut, "
    "WorkJam, UKG, Spotify, YouTube TV, iMessage"
)


def whisper_transcribe_kwargs(prompt, hotwords=None):
    """Arguments for faster-whisper.transcribe.

    `prompt` is the command examples for push-to-talk, or None in wake mode.
    Hotwords stay in their own argument. They are not appended to the prompt,
    because a prompt is what Whisper echoes on silence. Previous-text
    conditioning is off so one echoed window is not fed into the next.
    """
    return {
        "language": "en",
        "beam_size": 1,
        "vad_filter": True,
        "initial_prompt": prompt,
        "hotwords": WHISPER_HOTWORDS if hotwords is None else hotwords,
        "condition_on_previous_text": False,
    }


def _words(text):
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def is_hotword_echo(text, hotwords=None):
    """True when every word is from the vocabulary hint.

    Silence with a hotword bias often comes back as the hint itself
    ("ChatGPT, Claude, Grok, ...") or one name from it. A real command has a
    word that is not in that list, such as "open".
    """
    heard = _words(text)
    if not heard:
        return False
    vocab = set(_words(WHISPER_HOTWORDS if hotwords is None else hotwords))
    return all(word in vocab for word in heard)


def transcript_from_segments(segments, drop_noise=False, hotwords=None):
    """Join Whisper segments. High no-speech scores and a pure hotword echo are blank.

    drop_noise is what wake mode and push-to-talk both pass once hotwords are
    on. A segment Whisper itself calls silence is not allowed to become a command.
    """
    parts = []
    for seg in segments:
        if drop_noise and getattr(seg, "no_speech_prob", 0.0) > NO_SPEECH_MAX:
            continue
        text = str(getattr(seg, "text", "") or "").strip()
        if text:
            parts.append(text)
    heard = " ".join(parts).strip()
    if is_hotword_echo(heard, hotwords):
        return ""
    return heard
