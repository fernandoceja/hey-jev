"""After an area capture: the orb settles at a corner of the selection and a small "What is this?" field pops up beside
it. The capture panel opens only on a second click on the orb, or Esc from the field. Pure layout and rules.

Coordinates are AppKit screen points (origin bottom-left). A screen is (x, y, w, h), the visible frame.
"""
import math
import re

PLACEHOLDER = "What is this?"
FIELD_W = 270.0  # the inline pill's width
FIELD_H = 40.0  # the field row
ANSWER_PAD = 10.0
ANSWER_LINE_H = 16.0
ANSWER_CHARS_PER_LINE = 36  # rough, at 12 pt across the pill
ANSWER_MAX_LINES = 7
SIDE_GAP = 8.0  # between the orb and the pill
CORNER_PUSH = 0.25  # the orb's centre sits this fraction of its size outside the selection's corner
IDLE_SECONDS = 30.0  # the inline field closes by itself after this long untouched
CORNERS = ("bl", "br", "tl", "tr")


def pick_corner(rect, release_point):
    """The selection's corner nearest where the pointer was released. 'br' when the point is missing."""
    x, y, w, h = [float(v) for v in rect]
    corners = {"bl": (x, y), "br": (x + w, y), "tl": (x, y + h), "tr": (x + w, y + h)}
    try:
        px, py = float(release_point[0]), float(release_point[1])
    except (TypeError, ValueError, IndexError):
        return "br"
    if not (math.isfinite(px) and math.isfinite(py)):
        return "br"
    return min(CORNERS, key=lambda name: math.hypot(corners[name][0] - px, corners[name][1] - py))


def _clamp(value, low, high):
    if high < low:
        return low
    return max(low, min(high, value))


def orb_target_origin(rect, corner, orb_size, screen):
    """Window origin that puts the orb's centre just outside the chosen corner, kept fully on the screen."""
    x, y, w, h = [float(v) for v in rect]
    ow, oh = float(orb_size[0]), float(orb_size[1])
    cx = x if corner in ("bl", "tl") else x + w
    cy = y if corner in ("bl", "br") else y + h
    push_x = -CORNER_PUSH * ow if corner in ("bl", "tl") else CORNER_PUSH * ow
    push_y = -CORNER_PUSH * oh if corner in ("bl", "br") else CORNER_PUSH * oh
    ox = cx + push_x - ow / 2.0
    oy = cy + push_y - oh / 2.0
    sx, sy, sw, sh = [float(v) for v in screen]
    return (_clamp(ox, sx, sx + sw - ow), _clamp(oy, sy, sy + sh - oh))


def answer_lines(text, chars_per_line=ANSWER_CHARS_PER_LINE, max_lines=ANSWER_MAX_LINES):
    """How many lines a reply needs, between 1 and max_lines. Words wrap; a word longer than a line is split."""
    words = str(text or "").split()
    if not words:
        return 1
    lines, used = 1, 0
    for word in words:
        n = len(word)
        while n > chars_per_line:
            if used:
                lines += 1
            lines += n // chars_per_line - (1 if n % chars_per_line == 0 else 0)
            n = n % chars_per_line or chars_per_line
            used = 0
        if used == 0:
            used = n
        elif used + 1 + n <= chars_per_line:
            used += 1 + n
        else:
            lines += 1
            used = n
    return min(max_lines, lines)


def tidy_answer(text):
    """The reply as plain text for a small label: no markdown emphasis or code ticks, whitespace collapsed."""
    text = str(text or "")
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", text)
    text = text.replace("`", "")
    return " ".join(text.split())


def clip_answer(text, chars_per_line=ANSWER_CHARS_PER_LINE, max_lines=ANSWER_MAX_LINES):
    """Cut a long reply at a word boundary with an ellipsis so it fits max_lines. The full answer is in the capture panel."""
    text = str(text or "")
    limit = int(chars_per_line * max_lines * 0.88)
    if len(text) <= limit and answer_lines(text, chars_per_line, max_lines + 1) <= max_lines:
        return text
    cut = text[:limit].rstrip()
    if " " in cut:
        cut = cut[:cut.rindex(" ")]
    return cut.rstrip(" ,;:-") + "\u2026"


def pill_size(answer_text=None):
    """(w, h) of the inline pill: the field row, plus the answer when there is one."""
    if not answer_text:
        return (FIELD_W, FIELD_H)
    lines = answer_lines(answer_text)
    return (FIELD_W, FIELD_H + ANSWER_PAD + lines * ANSWER_LINE_H + ANSWER_PAD / 2.0)


def inline_frame(orb_frame, screen, size):
    """The pill's frame: beside the orb (right if it fits, else left), its field row level with the orb, grown
    downward for an answer, and always inside the screen. Returns (x, y, w, h, side)."""
    ox, oy, ow, oh = [float(v) for v in orb_frame]
    w, h = float(size[0]), float(size[1])
    sx, sy, sw, sh = [float(v) for v in screen]
    right_x = ox + ow + SIDE_GAP
    if right_x + w <= sx + sw:
        x, side = right_x, "right"
    else:
        x, side = ox - SIDE_GAP - w, "left"
    row_top = oy + oh / 2.0 + FIELD_H / 2.0  # the field row is centred on the orb
    y = row_top - h
    x = _clamp(x, sx, sx + sw - w)
    y = _clamp(y, sy, sy + sh - h)
    return (x, y, w, h, side)


def idle_expired(shown_at, now, hovered, editing):
    """True when the inline field should close by itself."""
    if hovered or editing:
        return False
    return float(now) - float(shown_at) >= IDLE_SECONDS


def should_start(orb_visible, collapsed, docked, busy, has_rect):
    """Only a visible, quiet, collapsed orb moves to the selection. Anything else keeps the normal capture panel."""
    return bool(orb_visible and collapsed and not docked and not busy and has_rect)


ACCEPT_SELECTORS = ("insertTab:", "moveRight:")  # Tab and Right Arrow, as the text system names them


def accepted_text(current, selector, placeholder=PLACEHOLDER):
    """The text to put in the field when Tab or Right Arrow accepts the grey suggestion, else None.

    Only an empty field accepts it. With any text in it, Tab and Right Arrow keep their normal meaning."""
    if str(current or "") == "" and str(selector) in ACCEPT_SELECTORS:
        return placeholder
    return None
