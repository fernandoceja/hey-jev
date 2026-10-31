"""Idle character rules for the orb: eye shapes, random accents and breath timing. Pure Python.

Every random choice takes an injected random.Random, so tests can seed it. No AppKit, Quartz or Cocoa.
"""
from collections import namedtuple

from orb_motion import (
    BREATH_FRAMES,
    BREATH_SCALE_X,
    BREATH_SCALE_Y,
    CLIP_FPS,
    sample_track,
    spring_decay,
)

# Handle length for a cubic through four cardinal points. 0.2762 is kappa / 2, so the open eye is a true circle.
HANDLE = 0.2762
EYE_POINTS = 13  # one move, then four cubic segments (three points each), per eye shape

# Four anchors per shape (top, right, bottom, left) as fractions of the eye size. Every point stays in 0..1.
EYE_SHAPES = {
    "open": ((0.5, 0.0), (1.0, 0.5), (0.5, 1.0), (0.0, 0.5)),
    "closedDown": ((0.5, 0.5), (1.0, 0.56), (0.5, 0.62), (0.0, 0.56)),
    "closedUp": ((0.5, 0.36), (1.0, 0.44), (0.5, 0.5), (0.0, 0.44)),
    "smileClosed": ((0.5, 0.28), (1.0, 0.62), (0.5, 0.5), (0.0, 0.62)),
    "wide": ((0.5, 0.0), (0.92, 0.5), (0.5, 1.0), (0.08, 0.5)),
}

# lookIntensity by character state. Only "idle" is driven by PR 2; the other rows are the plan's table for later PRs.
STATE_LOOK = {"idle": 1.0, "listening": 0.6, "thinking": 0.0, "searching": 0.3, "speaking": 0.5, "still": 0.0}

Accent = namedtuple("Accent", "name frames weight look")

# The idle accents from the plan's Character model table. Frames are at CLIP_FPS.
ACCENTS = (
    Accent("blink", 20, 30, 1.0),
    Accent("blink_stagger", 28, 15, 1.0),
    Accent("double_blink", 42, 10, 1.0),
    Accent("look_around", 90, 12, 0.0),
    Accent("yawn", 96, 6, 0.0),
    Accent("bounce", 36, 8, 0.5),
    Accent("jiggle", 30, 4, 1.0),
    Accent("happy", 60, 8, 0.0),
)
_ACCENT_BY_NAME = {accent.name: accent for accent in ACCENTS}


def eye_shape(name, size):
    """Closed Bézier loop for an eye, as 13 (x, y) points in the eye's own coordinates."""
    try:
        anchors = EYE_SHAPES[name]
    except KeyError:
        raise ValueError("unknown eye shape: %r" % (name,))
    points = [(x * size, y * size) for x, y in anchors]
    count = len(points)
    out = [points[0]]
    for i in range(count):
        p0 = points[(i - 1) % count]
        p1 = points[i]
        p2 = points[(i + 1) % count]
        p3 = points[(i + 2) % count]
        out.append((p1[0] + HANDLE * (p2[0] - p0[0]), p1[1] + HANDLE * (p2[1] - p0[1])))
        out.append((p2[0] - HANDLE * (p3[0] - p1[0]), p2[1] - HANDLE * (p3[1] - p1[1])))
        out.append(p2)
    return tuple(out)


def accent_seconds(name):
    return _ACCENT_BY_NAME[name].frames / float(CLIP_FPS)


def _frames(count):
    return count / float(CLIP_FPS)


def _blink(start):
    """Open, closed (half-way through 20 frames), open. Used by every blink accent."""
    return [(start, "open"), (start + _frames(10), "closedDown"), (start + _frames(20), "open")]


def _hop(t):
    """A 6 pt hop that lands at 0.36 s."""
    if t >= 0.36:
        return 0.0
    u = t / 0.36
    return 6.0 * 4.0 * u * (1.0 - u)


def _landing_squash(t):
    """Scale y dips 6% on landing, then the spring (k=500, c=18) settles it back to 1."""
    if t < 0.36:
        return 1.0
    return 1.0 - 0.06 * spring_decay(500.0, 18.0, t - 0.36)


def _jiggle(t):
    return 1.0 + 0.04 * spring_decay(500.0, 14.0, t)


def _tl_blink():
    return {"eyes_L": _blink(0.0), "eyes_R": _blink(0.0)}


def _tl_blink_stagger():
    left = _blink(0.0) + [(_frames(28), "open")]
    right = _blink(_frames(5)) + [(_frames(28), "open")]  # the right eye follows about 0.08 s later
    return {"eyes_L": left, "eyes_R": right}


def _tl_double_blink():
    return {"eyes_L": _blink(0.0) + _blink(_frames(22)), "eyes_R": _blink(0.0) + _blink(_frames(22))}


def _tl_look_around():
    return {"pupil_x": [(0.0, 0.0), (0.4, -2.2), (0.9, 2.2), (1.5, 0.0)]}


def _tl_yawn():
    eyes = [(0.0, "open"), (0.4, "closedUp"), (1.2, "closedUp"), (1.6, "open")]
    mouth = [(0.0, 0.0), (0.4, 1.0), (1.2, 1.0), (1.6, 0.0)]
    body = [(0.0, 1.0), (0.5, 1.06), (1.1, 1.06), (1.6, 1.0)]
    return {"eyes_L": eyes, "eyes_R": list(eyes), "mouth": mouth, "body_sy": body}


def _tl_bounce():
    return {"body_y": sample_track(_hop, 0.6), "body_sy": sample_track(_landing_squash, 0.6)}


def _tl_jiggle():
    return {"body_scale": sample_track(_jiggle, 0.5)}


def _tl_happy():
    eyes = [(0.0, "open"), (0.25, "smileClosed"), (0.75, "smileClosed"), (1.0, "open")]
    return {"eyes_L": eyes, "eyes_R": list(eyes)}


_TIMELINES = {
    "blink": _tl_blink,
    "blink_stagger": _tl_blink_stagger,
    "double_blink": _tl_double_blink,
    "look_around": _tl_look_around,
    "yawn": _tl_yawn,
    "bounce": _tl_bounce,
    "jiggle": _tl_jiggle,
    "happy": _tl_happy,
}


def accent_timeline(name):
    """Channel -> [(t, value)] for one accent. Eye channels hold shape names. Every track ends at accent_seconds."""
    return _TIMELINES[name]()


def next_accent_delay(rng):
    return rng.uniform(4.0, 9.0)


def pick_accent(rng, previous=None):
    """Weighted pick that never returns the previous accent."""
    choices = [accent for accent in ACCENTS if accent.name != previous]
    return rng.choices([accent.name for accent in choices], weights=[accent.weight for accent in choices])[0]


def breath_speed(rng):
    return rng.uniform(0.5, 1.3)


def breath_timeline(cycles):
    """[(t, scale_x, scale_y)] for back-to-back breath cycles, one cycle per entry in seconds."""
    out = [(0.0, 1.0, 1.0)]
    t = 0.0
    for cycle in cycles:
        out.append((t + cycle / 2.0, BREATH_SCALE_X, BREATH_SCALE_Y))
        t += cycle
        out.append((t, 1.0, 1.0))
    return out


def breath_batch(rng, count=8):
    """A batch of breath cycles, each 7.5 s divided by its own random speed."""
    base = BREATH_FRAMES / float(CLIP_FPS)
    return breath_timeline([base / breath_speed(rng) for _ in range(count)])


def look_intensity(state, clip=None):
    """How much the pupils follow the cursor. A clip overrides its state's value."""
    if clip is not None and clip in _ACCENT_BY_NAME:
        return _ACCENT_BY_NAME[clip].look
    return STATE_LOOK.get(state, 1.0)
