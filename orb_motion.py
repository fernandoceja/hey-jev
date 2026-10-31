"""Orb geometry, palette and pupil rules. Pure Python: no AppKit, Quartz or Cocoa.

Every number here is in the 72 pt design space that orb_view scales to the view.
orb_layers reads these constants to build the Core Animation tree.
"""
import math

DESIGN_SIZE = 72.0
DESIGN_EXTENT = 70.0  # orb + listening ring, with a hair of margin; the fit scale divides by this
DESIGN_CENTER = DESIGN_SIZE / 2.0

BODY_SIZE = 56.0
BODY_ORIGIN = (DESIGN_SIZE - BODY_SIZE) / 2.0

EYE_SIZE = 11.0
EYE_SPACING = 8.0  # each eye sits this far left or right of the body centre
EYE_CENTER_Y = 38.0
PUPIL_SIZE = 4.4

HIGHLIGHT_SIZE = (20.0, 12.0)
HIGHLIGHT_ORIGIN = (18.0, 46.0)  # fixed: the highlight is a sibling of the bob group
HIGHLIGHT_ALPHA = 0.85

SHADOW_SIZE = (44.0, 10.0)
SHADOW_ORIGIN = (14.0, 1.0)
SHADOW_RADIUS = 8.0
SHADOW_OPACITY = 0.35

RING_INSET = 5.0
RING_DIAMETER = 62.0

MAX_PUPIL_OFFSET = 3.0
PUPIL_REACH = 300.0

# Jev's existing cyan → blue → indigo, as 0–1 floats (was NSColor in orb_view).
ORB_PALETTE = (
    (0.36, 0.95, 0.92),
    (0.16, 0.42, 0.95),
    (0.08, 0.07, 0.36),
)
SHADE_RGB = (0.02, 0.02, 0.2)
SHADE_ALPHA = {"light": 0.40, "dark": 0.50}  # tune on the hand test
RIM_RGB = (0.45, 0.85, 1.0)
RIM_ALPHA = 0.35
EYE_EDGE_RGB = (0.894, 0.902, 0.933)  # #E4E6EE, the matte eye edge
GLYPH_RGB = (1.0, 0.98, 0.88)  # the cream used for the thinking, speaking and error cues
LISTEN_GLYPH_RGB = (0.55, 0.86, 1.0)
RING_RGB = (0.18, 0.65, 1.0)


def layer_geometry(bob=0.0):
    """Frames (x, y, w, h) in design space. bob moves the body group, not the highlight."""
    bob = float(bob)
    body = (BODY_ORIGIN, BODY_ORIGIN + bob, BODY_SIZE, BODY_SIZE)
    frames = {
        "shadow": (SHADOW_ORIGIN[0], SHADOW_ORIGIN[1], SHADOW_SIZE[0], SHADOW_SIZE[1]),
        "body": body,
        "highlight": (HIGHLIGHT_ORIGIN[0], HIGHLIGHT_ORIGIN[1], HIGHLIGHT_SIZE[0], HIGHLIGHT_SIZE[1]),
        "ring": (RING_INSET, RING_INSET + bob, RING_DIAMETER, RING_DIAMETER),
    }
    for side, sign in (("L", -1.0), ("R", 1.0)):
        cx = DESIGN_CENTER + sign * EYE_SPACING
        cy = EYE_CENTER_Y + bob
        frames["eye" + side] = (cx - EYE_SIZE / 2.0, cy - EYE_SIZE / 2.0, EYE_SIZE, EYE_SIZE)
        frames["pupil" + side] = (cx - PUPIL_SIZE / 2.0, cy - PUPIL_SIZE / 2.0, PUPIL_SIZE, PUPIL_SIZE)
    return frames


def pupil_offset(eye_center, cursor, max_offset=MAX_PUPIL_OFFSET, reach=PUPIL_REACH):
    """Shift for a pupil toward the cursor. Length grows to max_offset at reach points."""
    try:
        ex, ey = float(eye_center[0]), float(eye_center[1])
        cx, cy = float(cursor[0]), float(cursor[1])
    except (TypeError, ValueError, IndexError):
        return (0.0, 0.0)
    dx, dy = cx - ex, cy - ey
    if not all(math.isfinite(v) for v in (ex, ey, cx, cy, dx, dy)):
        return (0.0, 0.0)
    dist = math.hypot(dx, dy)
    if dist == 0.0 or not math.isfinite(dist):
        return (0.0, 0.0)
    ratio = min(1.0, dist / reach) if reach > 0 else 1.0
    magnitude = max_offset * ratio
    return (dx / dist * magnitude, dy / dist * magnitude)


# Idle character timing. Frame counts come from the REA study notes, which guess 60 fps for the clips.
CLIP_FPS = 60  # assumed, not confirmed: see docs/plans/eney-bubble-v2-rea-notes.md
BOB_AMPLITUDE = 2.5
BOB_PERIOD = 2.6
SHADOW_MIN_SCALE = 0.94
SHADOW_MIN_OPACITY = 0.28
BREATH_FRAMES = 450
BREATH_SCALE_X = 0.995
BREATH_SCALE_Y = 1.015
FLOAT_FRAMES = 1500
FLOAT_AMPLITUDE = 1.0
CURSOR_POLL_SECONDS = 1.0 / 20.0
CURSOR_EPS = 0.5


def idle_active(visible, motion, docked, asleep):
    """Decorative idle motion runs only when the orb is on screen, motion is allowed, and the screens are awake."""
    return bool(visible and motion and not docked and not asleep)


def cursor_moved(prev, now, eps=CURSOR_EPS):
    """True when the cursor moved at least eps points since the last poll. Bad input counts as moved."""
    if prev is None:
        return True
    try:
        dx = float(now[0]) - float(prev[0])
        dy = float(now[1]) - float(prev[1])
    except (TypeError, ValueError, IndexError):
        return True
    dist = math.hypot(dx, dy)
    if not math.isfinite(dist):
        return True
    return dist >= eps


def sine_samples(period, amplitude, count=24):
    """(t, offset) for one loop that starts and ends at rest, so starting it never snaps the pose."""
    return [(period * i / count, amplitude * math.sin(math.tau * i / count)) for i in range(count + 1)]


def shadow_for_bob(offset):
    """Shadow (scale, opacity factor) for a bob offset. Higher orb, smaller and fainter shadow.

    The opacity factor multiplies the shadow image, which is already drawn at SHADOW_OPACITY.
    """
    t = max(-1.0, min(1.0, float(offset) / BOB_AMPLITUDE))
    scale = (1.0 + SHADOW_MIN_SCALE) / 2.0 - t * (1.0 - SHADOW_MIN_SCALE) / 2.0
    min_factor = SHADOW_MIN_OPACITY / SHADOW_OPACITY
    opacity = (1.0 + min_factor) / 2.0 - t * (1.0 - min_factor) / 2.0
    return scale, opacity


def spring_decay(k, c, t):
    """Free response of a unit spring (m = 1) released from rest at displacement 1. Underdamped only."""
    if t < 0.0:
        return 1.0
    omega = math.sqrt(k)
    zeta = c / (2.0 * omega)
    if zeta >= 1.0:
        raise ValueError("spring_decay needs an underdamped spring")
    omega_d = omega * math.sqrt(1.0 - zeta * zeta)
    envelope = math.exp(-zeta * omega * t)
    return envelope * (math.cos(omega_d * t) + zeta * omega / omega_d * math.sin(omega_d * t))


def sample_track(fn, duration, fps=CLIP_FPS):
    """(t, fn(t)) every 1/fps seconds from 0 to duration, with the last sample exactly at duration."""
    count = max(1, int(round(duration * fps)))
    pairs = [(i / float(fps), fn(i / float(fps))) for i in range(count)]
    pairs.append((float(duration), fn(float(duration))))
    return pairs
