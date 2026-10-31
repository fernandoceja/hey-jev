"""The brief as text, with an offer to read it aloud (PR 8c). Pure logic: no audio, no network, no AppKit.

The offer is "Want me to read it out loud?". A yes within OFFER_WINDOW_SECONDS plays the audio, by voice, by typing, or
by the button. Anything else dismisses the offer. The sentence splitter keeps "G 05.72 hrs", "11 AM", "a.m." and em
dashes intact, and keeps voice tags such as "[chuckling]" with the sentence they belong to.
"""
import re
import time

BRIEF_OFFER_LINE = "Want me to read it out loud?"
OFFER_WINDOW_SECONDS = 60.0

_YES = {
    "yes", "yes please", "yeah", "yep", "yup", "sure", "sure thing", "read it", "read it out loud", "read it aloud",
    "play it", "play it out loud", "play audio", "play it please", "read it please", "yes read it", "yes play it",
}
_NO = {"no", "no thanks", "no thank you", "nope", "not now", "no please"}


def _words(text):
    lowered = str(text or "").lower()
    lowered = re.sub(r"[^a-z' ]+", " ", lowered)
    return " ".join(lowered.split())


def answer_kind(text):
    """"yes", "no", or "other" for a reply to the offer. Case and punctuation do not matter."""
    words = _words(text)
    if words in _YES:
        return "yes"
    if words in _NO:
        return "no"
    return "other"


def split_sentences(text):
    """Speech-sized pieces of the brief, in order. Splits only where a sentence really ends: after . ! or ? and a space,
    with a capital, digit or "[" next. Not inside a number such as 05.72, not after an abbreviation such as a.m. or
    e.g., and not at an em dash. Empty input gives no pieces."""
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return []
    pieces = []
    start = 0
    for i, ch in enumerate(cleaned):
        if ch not in ".!?" or i + 2 >= len(cleaned) or cleaned[i + 1] != " ":
            continue
        following = cleaned[i + 2]
        if not (following.isupper() or following.isdigit() or following == "["):
            continue
        last_word = cleaned[start:i].split(" ")[-1] if cleaned[start:i] else ""
        if ch == "." and "." in last_word:
            continue  # an abbreviation such as a.m. or e.g.: the word before this dot already holds a dot
        pieces.append(cleaned[start:i + 1])
        start = i + 2
    tail = cleaned[start:]
    if tail:
        pieces.append(tail)
    return [piece.strip() for piece in pieces if piece.strip()]


SPEECH_CHUNK_CHARS = 150


def speech_chunks(text, limit=SPEECH_CHUNK_CHARS):
    """The pieces the audio is made from, in order. Each is a sentence from split_sentences, and any sentence longer than
    limit is cut at the last space before limit, so the first piece is always quick to make. No words are lost."""
    chunks = []
    for piece in split_sentences(text):
        while len(piece) > limit:
            cut = piece.rfind(" ", 0, limit + 1)
            if cut <= 0:
                cut = limit
            chunks.append(piece[:cut].strip())
            piece = piece[cut:].strip()
        if piece:
            chunks.append(piece)
    return [chunk for chunk in chunks if chunk]


class BriefOffer:
    """One open offer at a time. Clock is injected, so tests use a fake one."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._deadline = None

    def offer(self, now=None):
        now = float(self._clock() if now is None else now)
        self._deadline = now + OFFER_WINDOW_SECONDS

    def pending(self, now=None):
        now = float(self._clock() if now is None else now)
        return self._deadline is not None and now < self._deadline

    def expire_if_due(self, now=None):
        """"expired" once, when the window has passed with no answer. None otherwise."""
        now = float(self._clock() if now is None else now)
        if self._deadline is not None and now >= self._deadline:
            self._deadline = None
            return "expired"
        return None

    def answer(self, text, now=None):
        """(outcome, consumed) for one reply. outcome is accepted, declined, expired, or None when there is no offer.

        consumed is True when the reply belongs to the offer and must not run as a command. Anything other than a
        yes is a decline, and an other reply is not consumed, so it still runs as a request.
        """
        if self._deadline is None:
            return None, False
        now = float(self._clock() if now is None else now)
        if now >= self._deadline:
            self._deadline = None
            return "expired", False
        kind = answer_kind(text)
        self._deadline = None
        if kind == "yes":
            return "accepted", True
        if kind == "no":
            return "declined", True
        return "declined", False
