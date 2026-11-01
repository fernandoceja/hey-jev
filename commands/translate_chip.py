"""Translate chip (PR 8b): offer to translate a copied non-English text for 20 seconds. Pure logic: no AppKit, no network,
no audio, no clock of its own (the clock is injected).

When the clipboard gets new plain text that looks non-English, the popover and the full window show a "Translate"
chip for TRANSLATE_WINDOW_SECONDS. A click returns the command "translate this to English: <text>", which the caller
runs as a normal typed turn. Nothing here runs anything: a chip appears, and a click is the only way to get a command.

Copies the clipboard history refuses (paused, password manager, concealed type, secret) never reach the heuristic and
never show a chip. Log lines name the outcome and a reason, never the text.
"""
import re
import time

TRANSLATE_WINDOW_SECONDS = 20.0
TRANSLATE_COMMAND = "translate this to English"
MIN_LETTERS = 8
MIN_WORDS = 3
MIN_EVIDENCE = 2
CODE_RATIO = 0.06
MIXED_SHARE_HIGH = 0.6  # foreign share of common words at or above this is non-English; at or below 0.4 is English
NON_LATIN_RATIO = 0.3
NON_LATIN_MIN = 3

# Common words only. Ambiguous words (a, i in Spanish, die, do, per, no, en in English) are left out on purpose.
_ENGLISH = frozenset((
    "the", "and", "is", "are", "to", "of", "in", "that", "it", "for", "with", "on", "this", "you", "be", "not",
    "have", "was", "but", "they", "we", "at", "or", "from", "by", "an", "as", "my", "your", "will", "can", "there",
    "what", "which", "their", "about", "would", "should", "just", "all", "so", "if", "when", "more", "its", "has",
    "been", "were", "do", "does", "did", "me", "he", "she", "him", "her", "us", "our", "how", "who",
))
_FOREIGN = frozenset((
    # Spanish
    "de", "la", "que", "el", "los", "las", "por", "con", "para", "una", "es", "del", "se", "pero", "como", "esta",
    "muy", "y", "lo", "su", "son", "fue", "hay",
    # French
    "le", "les", "des", "est", "une", "et", "pour", "dans", "qui", "avec", "pas", "sur", "mais", "du", "je", "il",
    "elle", "nous", "vous", "ce", "cette",
    # German
    "der", "das", "und", "ist", "nicht", "ein", "eine", "mit", "auf", "zu", "sich", "auch", "dem", "den", "wir", "sie",
    # Portuguese
    "da", "dos", "das", "uma", "com", "mas", "foi", "ser", "muito", "você", "seu", "sua",
    # Italian
    "di", "che", "non", "sono", "della", "gli", "anche", "questo", "questa", "come", "sei", "nel",
))

_URL = re.compile(r"(?i)\b(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|org|net|io|dev|app|edu|gov|co|uk)\b\S*")
_CODE_LINE = re.compile(
    r"(?m)^\s*(?:def|class|import|from\s+\S+\s+import|function|const|public|private|#include|"
    r"SELECT|INSERT|UPDATE)\b"
)
_CODE_TOKENS = re.compile(r"->|=>|::|==|!=|<=|>=|\+=|-=")
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_CODE_CHARS = frozenset("{}[];=<>")  # parentheses are left out: ordinary prose uses them all the time
_NON_LATIN = re.compile(
    "[Ͱ-ϿЀ-ӿ֐-׿؀-ۿऀ-ॿ฀-๿"
    "぀-ヿ㐀-鿿가-힯]"
)


def _letters(text):
    return [ch for ch in text if ch.isalpha()]


def classify_copy(text):
    """(True, "non_english") for a copy worth offering. Otherwise (False, reason).

    Reasons: empty, short, url, code, english, mixed, unsure. Order: empty, short, url, code, script, then common
    words. A word with an accent that is not a known English word counts as foreign evidence.
    """
    raw = str(text or "").strip()
    if not raw:
        return False, "empty"
    if len(_letters(raw)) < MIN_LETTERS:
        return False, "short"
    stripped = _URL.sub(" ", raw)
    if stripped != raw and len(_WORD.findall(stripped)) < MIN_WORDS:
        return False, "url"
    if _looks_like_code(raw):
        return False, "code"
    letters = _letters(stripped)
    non_latin = len(_NON_LATIN.findall(stripped))
    if non_latin >= NON_LATIN_MIN and non_latin >= NON_LATIN_RATIO * max(1, len(letters)):
        return True, "non_english"
    words = [w.lower() for w in _WORD.findall(stripped)]
    if len(words) < MIN_WORDS:
        return False, "short"
    english = sum(1 for w in words if w in _ENGLISH)
    foreign = sum(1 for w in words if w in _FOREIGN or (w not in _ENGLISH and not w.isascii()))
    if english >= MIN_EVIDENCE and foreign >= MIN_EVIDENCE:
        share = foreign / float(english + foreign)
        if share >= MIXED_SHARE_HIGH:
            return True, "non_english"
        if share <= 1.0 - MIXED_SHARE_HIGH:
            return False, "english"
        return False, "mixed"  # both languages are well represented: no chip
    if foreign >= MIN_EVIDENCE:
        return True, "non_english"
    if english >= MIN_EVIDENCE:
        return False, "english"
    return False, "unsure"


def _looks_like_code(text):
    if _CODE_LINE.search(text) or _CODE_TOKENS.search(text):
        return True
    code_chars = sum(1 for ch in text if ch in _CODE_CHARS)
    return code_chars / float(max(1, len(text))) >= CODE_RATIO


def translate_command(text):
    """The normal typed turn for a click. The copied text follows the command, on one line."""
    return "{0}: {1}".format(TRANSLATE_COMMAND, " ".join(str(text or "").split()))


class TranslateChip(object):
    """One open offer at a time. A newer clipboard change always replaces the offer, so a stale chip never stays up.

    Every method returns (outcome, reason) for the log, or None when there is nothing to log. Outcomes are shown,
    expired, clicked and skipped. The text is kept only while the offer is open.
    """

    def __init__(self, clock=time.monotonic, window=TRANSLATE_WINDOW_SECONDS):
        self._clock = clock
        self._window = float(window)
        self._deadline = None
        self._text = ""
        self._seq = None

    def _now(self, now):
        return float(self._clock() if now is None else now)

    def _clear(self):
        self._deadline = None
        self._text = ""

    def visible(self, now=None, paused=False):
        """True while the chip should show: an open offer, not expired, and clipboard history not paused."""
        if self._deadline is None or paused:
            return False
        return self._now(now) < self._deadline

    def on_observation(self, seq, status, text="", paused=False, now=None):
        """Feed one clipboard observation (ClipboardHistory.last_observation). Never shows a chip for a refused copy.

        `status` is the value returned by ClipboardHistory.observe. A repeat of the same `seq` is ignored.
        """
        if seq is None or not status or seq == self._seq:
            return None
        self._seq = seq
        if status == "unchanged":
            return None
        if status == "duplicate":
            return None  # same text as the newest item: the offer for it is already decided
        if paused or status == "paused":
            self._clear()
            return ("skipped", "paused")
        if status != "stored":
            self._clear()
            return ("skipped", str(status or "unknown"))
        ok, reason = classify_copy(text)
        if not ok:
            self._clear()
            return ("skipped", reason)
        self._text = str(text)
        self._deadline = self._now(now) + self._window
        return ("shown", "non_english")

    def expire_if_due(self, now=None, paused=False):
        """("expired", reason) once when the offer ends by pause or by time. None otherwise."""
        if self._deadline is None:
            return None
        if paused:
            self._clear()
            return ("expired", "paused")
        if self._now(now) >= self._deadline:
            self._clear()
            return ("expired", "timeout")
        return None

    def click(self, now=None, paused=False):
        """(command, outcome, reason). The command is set only for an open, unexpired offer. It is the one way out."""
        if self._deadline is None:
            return None, "skipped", "no_offer"
        if paused:
            self._clear()
            return None, "skipped", "paused"
        if self._now(now) >= self._deadline:
            self._clear()
            return None, "expired", "timeout"
        text = self._text
        self._clear()
        return translate_command(text), "clicked", ""


def log_line(result):
    """"translate chip: <outcome> <reason>" for a (outcome, reason) pair. Never includes the copied text."""
    if not result:
        return None
    outcome, reason = result
    return "translate chip: {0} {1}".format(outcome, reason).rstrip()
