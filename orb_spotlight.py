"""The orb's right-click panel: a Spotlight-style Jev search panel. Pure Python, so the rules are tested headless.

AppKit lives in assistant_ui (OrbSpotlightPanel and its helpers). This module holds the rows, the keyboard
mapping, the arrow-key wrap and the placement beside the orb, which must stay on screen.
"""

SPOTLIGHT_WIDTH = 440.0
SPOTLIGHT_RADIUS = 26.0  # the rounded corner of the Apple glass panel
SPOTLIGHT_FIELD_H = 52.0  # "Search or Ask Jev" with the mic at its right
SPOTLIGHT_ROW_H = 36.0  # one line per item
SPOTLIGHT_PAD = 10.0
SPOTLIGHT_GAP = 10.0  # between the orb and the panel
SPOTLIGHT_FADE_SECONDS = 0.15
SPOTLIGHT_START_SCALE = 0.96

# Keyboard, by macOS virtual key code.
KEY_RETURN = 36
KEY_ESCAPE = 53
KEY_DOWN = 125
KEY_UP = 126

# The rows, in order. Each is (title, selector, SF Symbol, shortcut hint). The selectors are the menu's existing
# action selectors, so a pick runs the same code as before.
SPOTLIGHT_ROWS = (
    ("Open Jev", "orbMenuOpen:", "macwindow", ""),
    ("New Chat", "orbMenuNewChat:", "square.and.pencil", ""),
    ("Capture Area", "captureAreaWand:", "wand.and.stars", "⌘W"),
    ("Mark Up", "orbMenuMarkup:", "pencil.tip.crop.circle", ""),
    ("Type to Jev", "focusTypeField:", "keyboard", "⌃⌥J"),
    ("Settings", "showSettings:", "gearshape", "⌘,"),
    ("Quit", "terminate:", "power", "⌘Q"),
)


def panel_height(rows=SPOTLIGHT_ROWS):
    """Field, then the rows, with padding around each part."""
    return SPOTLIGHT_PAD + SPOTLIGHT_FIELD_H + SPOTLIGHT_PAD + len(rows) * SPOTLIGHT_ROW_H + SPOTLIGHT_PAD


def next_index(current, key, count):
    """The highlighted row after an arrow key. Wraps at both ends. None or -1 means no row is highlighted yet."""
    if count <= 0:
        return -1
    unset = current is None or current < 0
    if key == KEY_DOWN:
        return 0 if unset else (current + 1) % count
    if key == KEY_UP:
        return count - 1 if unset else (current - 1) % count
    return -1 if unset else current


def spotlight_frame(orb, visible, size=None):
    """Panel frame (x, y, w, h) beside the orb: to its right if there is room, otherwise to its left.

    Vertically centred on the orb, then clamped so the whole panel stays inside the visible frame.
    """
    ox, oy, ow, oh = (float(v) for v in orb)
    vx, vy, vw, vh = (float(v) for v in visible)
    w, h = (SPOTLIGHT_WIDTH, panel_height()) if size is None else (float(size[0]), float(size[1]))
    x = ox + ow + SPOTLIGHT_GAP
    if x + w > vx + vw:
        x = ox - SPOTLIGHT_GAP - w
    y = oy + oh / 2.0 - h / 2.0
    x = min(max(x, vx), max(vx, vx + vw - w))
    y = min(max(y, vy), max(vy, vy + vh - h))
    return (x, y, w, h)
