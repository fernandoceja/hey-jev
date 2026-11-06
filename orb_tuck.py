"""Eney-style edge tuck for the floating orb: edge detection, tucked and untucked frames, eye layout and the
persisted value. Pure Python, so the math is tested headless. AppKit lives in assistant_ui and orb_layers.

A tucked orb is half past the screen edge. Its body is centred on the window, so the window's edge sits on the
screen edge and exactly half the round body is off screen. The body is never scaled or squished.
"""
import math

from orb_motion import peek_edge_allowed

TUCK_KEY = "orb_tuck"  # the persisted tuck: "left:<y>" or "right:<y>". Missing means not tucked.
TUCK_EDGE_DISTANCE = 24.0  # a drop this close to a free left or right edge tucks the orb
TUCK_SECONDS = 0.9  # the slide, ease-out
TUCK_FADE_IN_SECONDS = 0.25  # the close button after the slide
TUCK_FADE_OUT_SECONDS = 0.15  # the close button on untuck or drag
TUCK_INSET = 12.0  # an untucked orb rests this far in from the edge it came from
TUCK_CLOSE_SIZE = 20.0  # the round "x" button
TUCK_CLOSE_CENTRE = (58.0, 60.0)  # in the 72 pt window: above and toward the screen side, outside the body circle
TUCK_EYE_REACH = 12.0  # how far toward the screen the tucked eyes sit from the window centre
TUCK_EYE_STACK = 8.0  # each tucked eye is this far above or below the centre line


def tuck_edge(frame, screen, screens=None):
    """'left' or 'right' when the orb's frame is within TUCK_EDGE_DISTANCE of that edge of its screen, else None.

    An edge shared with another display is never a tuck edge, as with peeking. The frame must also overlap the
    screen vertically, so an orb far above or below the screen does not tuck.
    """
    try:
        fx, fy, fw, fh = (float(v) for v in frame)
        sx, sy, sw, sh = (float(v) for v in screen)
    except (TypeError, ValueError):
        return None
    if fy + fh <= sy or fy >= sy + sh:
        return None
    if fx - sx <= TUCK_EDGE_DISTANCE and peek_edge_allowed("left", screen, screens or ()):
        return "left"
    if (sx + sw) - (fx + fw) <= TUCK_EDGE_DISTANCE and peek_edge_allowed("right", screen, screens or ()):
        return "right"
    return None


def _clamped_y(y, height, screen):
    sy, sh = float(screen[1]), float(screen[3])
    if sh < height:
        return sy
    return min(max(float(y), sy), sy + sh - height)


def tucked_frame(size, screen, edge, y):
    """Window frame (x, y, w, h) when tucked: half the window past the edge, at height y kept on screen."""
    w, h = float(size[0]), float(size[1])
    sx, _sy, sw, _sh = (float(v) for v in screen)
    if edge == "left":
        x = sx - w / 2.0
    elif edge == "right":
        x = sx + sw - w / 2.0
    else:
        raise ValueError("edge must be left or right")
    return (x, _clamped_y(y, h, screen), w, h)


def untucked_frame(size, screen, edge, y):
    """Window frame (x, y, w, h) an untucked orb rests at: TUCK_INSET in from the edge it came from."""
    w, h = float(size[0]), float(size[1])
    sx, _sy, sw, _sh = (float(v) for v in screen)
    if edge == "left":
        x = sx + TUCK_INSET
    elif edge == "right":
        x = sx + sw - w - TUCK_INSET
    else:
        raise ValueError("edge must be left or right")
    return (x, _clamped_y(y, h, screen), w, h)


def tuck_eye_centres(edge, horizontal):
    """Eye centres (design points) for the tucked layout, or the horizontal ones when not tucked.

    horizontal is {"L": (x, y), "R": (x, y)}, the normal layout. A tuck rotates it 90 degrees: the eyes stack
    vertically, near the visible curved side of the body, facing into the screen.
    """
    if edge is None:
        return {side: (float(x), float(y)) for side, (x, y) in horizontal.items()}
    centre_x = 36.0  # the body centre line in the 72 pt design space
    centre_y = 36.0
    toward_screen = 1.0 if edge == "left" else -1.0  # a left tuck faces right, into the screen
    x = centre_x + toward_screen * TUCK_EYE_REACH
    return {"L": (x, centre_y + TUCK_EYE_STACK), "R": (x, centre_y - TUCK_EYE_STACK)}


def tuck_close_centre(edge):
    """Centre of the "x" button in the 72 pt window, on the screen side of the orb."""
    x, y = TUCK_CLOSE_CENTRE
    if edge == "right":
        x = 72.0 - x
    return (x, y)


def encode_tuck(edge, y):
    """The persisted tuck value, "left:<y>" or "right:<y>"."""
    if edge not in ("left", "right"):
        raise ValueError("edge must be left or right")
    return "{0}:{1:.1f}".format(edge, float(y))


def decode_tuck(text):
    """(edge, y) from a persisted value, or None for missing or bad text. Never raises."""
    if not text:
        return None
    try:
        edge, _sep, raw = str(text).partition(":")
        y = float(raw)
    except (TypeError, ValueError):
        return None
    if edge not in ("left", "right") or not math.isfinite(y):
        return None
    return (edge, y)
