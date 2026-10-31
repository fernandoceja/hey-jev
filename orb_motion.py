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


# Press, drag and drop physics (PR 3a). Springs are (stiffness k, damping c) with mass 1, as in section 3 of the plan.
SPRING_PEEK_IN = (300.0, 22.0)
SPRING_PEEK_OUT = (200.0, 26.0)
SPRING_RELEASE = (500.0, 26.0)  # press released with a click
SPRING_FOLLOW = (400.0, 36.0)  # drag: the window trails the cursor
SPRING_DROP_JIGGLE = (500.0, 18.0)  # drop: stretch returns to round with two wobbles
SPRING_SNAP = (300.0, 24.0)  # drop: window to the finish_drag target. Capture drop uses it too.
SPRING_CAPTURE_ZONE = (500.0, 40.0)
SPRING_MENU_FAN = (500.0, 30.0)
SPRING_EXPAND = (400.0, 32.0)  # expand and collapse share this one
SPRINGS = (SPRING_PEEK_IN, SPRING_PEEK_OUT, SPRING_RELEASE, SPRING_FOLLOW, SPRING_DROP_JIGGLE,
           SPRING_SNAP, SPRING_CAPTURE_ZONE, SPRING_MENU_FAN, SPRING_EXPAND)

PRESS_SCALE = (1.12, 0.88)  # x, y of the body group while the mouse is down
PRESS_SECONDS = 0.10
STRETCH_MAX = 0.22  # sx is at most 1.22
STRETCH_SPEED = 3000.0  # pt/s for the full stretch
ROUGH_SPEED = 3500.0  # pt/s above which a drag counts as rough (PR 7b dizzy)
REVERSAL_MIN_SPEED = 300.0  # pt/s a segment must reach before a direction flip counts as a reversal
DRAG_TICK_SECONDS = 1.0 / 60.0
SETTLE_EPS = 0.25  # pt
SETTLE_SPEED_PER_EPS = 8.0  # a settled spring is also slower than eps × this, in pt/s
FOLLOW_MAX_STEP = 1.0 / 120.0  # the follow integrator sub-steps at this size, so it stays stable
FOLLOW_MAX_FRAME = 0.05  # a stalled frame never moves the window more than this much time


def _num(value):
    """A finite float, or None for anything that is not a finite number."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def spring(t, x0, x1, stiffness, damping, mass=1.0, v0=0.0):
    """(x, v) at time t for a spring from x0 with speed v0 toward x1. Closed form, so any t gives the exact answer.

    Underdamped, critically damped and overdamped each have their own formula, so the critically and
    overdamped cases never overshoot. Bad input goes straight to x1 at rest.
    """
    target = _num(x1)
    k, c, m = _num(stiffness), _num(damping), _num(mass)
    if target is None:
        target = 0.0
    if k is None or c is None or m is None or k <= 0.0 or c < 0.0 or m <= 0.0:
        return (target, 0.0)
    try:
        t = float(t)
    except (TypeError, ValueError, OverflowError):
        t = 0.0
    if math.isnan(t) or t < 0.0:
        t = 0.0
    if math.isinf(t):
        return (target, 0.0)
    start = _num(x0)
    start = target if start is None else start
    speed = _num(v0) or 0.0
    if t == 0.0:
        return (start, speed)
    omega0 = math.sqrt(k / m)
    zeta = c / (2.0 * math.sqrt(k * m))
    decay = zeta * omega0
    if decay * t > 700.0:  # e^-700 is zero for these purposes; skip the trig on huge arguments
        return (target, 0.0)
    d0 = start - target
    if zeta < 1.0 - 1e-9:
        wd = omega0 * math.sqrt(1.0 - zeta * zeta)
        env = math.exp(-decay * t)
        cos_t, sin_t = math.cos(wd * t), math.sin(wd * t)
        b = (speed + decay * d0) / wd
        d = env * (d0 * cos_t + b * sin_t)
        v = env * ((-decay * d0 + wd * b) * cos_t + (-decay * b - wd * d0) * sin_t)
    elif zeta <= 1.0 + 1e-9:
        env = math.exp(-omega0 * t)
        b = speed + omega0 * d0
        d = env * (d0 + b * t)
        v = env * (b - omega0 * (d0 + b * t))
    else:
        s = omega0 * math.sqrt(zeta * zeta - 1.0)
        r1, r2 = -decay + s, -decay - s
        c1 = (speed - r2 * d0) / (r1 - r2)
        c2 = d0 - c1
        e1, e2 = math.exp(r1 * t), math.exp(r2 * t)
        d = c1 * e1 + c2 * e2
        v = c1 * r1 * e1 + c2 * r2 * e2
    x = target + d
    if not (math.isfinite(x) and math.isfinite(v)):
        return (target, 0.0)
    return (x, v)


def spring_done(x, v, x1, eps=SETTLE_EPS):
    """True when a spring sits within eps of x1 and is nearly still. Bad input counts as done, so timers stop."""
    position, speed, target = _num(x), _num(v), _num(x1)
    if position is None or speed is None or target is None:
        return True
    return abs(position - target) <= eps and abs(speed) <= eps * SETTLE_SPEED_PER_EPS


def follow_step(pos, vel, target, dt, stiffness=SPRING_FOLLOW[0], damping=SPRING_FOLLOW[1]):
    """One semi-implicit Euler step of a spring that pulls pos toward target. Works in 2D tuples.

    dt is split into sub-steps of at most FOLLOW_MAX_STEP, so 1/30 s and 1/120 s frames behave the same.
    """
    px, py = _num(pos[0]) or 0.0, _num(pos[1]) or 0.0
    vx, vy = _num(vel[0]) or 0.0, _num(vel[1]) or 0.0
    tx, ty = _num(target[0]), _num(target[1])
    if tx is None or ty is None:
        return (px, py), (vx, vy)
    k, c = _num(stiffness) or 0.0, _num(damping) or 0.0
    step = _num(dt) or 0.0
    step = min(max(step, 0.0), FOLLOW_MAX_FRAME)
    if step <= 0.0 or k <= 0.0:
        return (px, py), (vx, vy)
    count = int(math.ceil(step / FOLLOW_MAX_STEP))
    h = step / count
    for _ in range(count):
        vx += (k * (tx - px) - c * vx) * h
        vy += (k * (ty - py) - c * vy) * h
        px += vx * h
        py += vy * h
    if not all(math.isfinite(v) for v in (px, py, vx, vy)):
        return (0.0, 0.0), (0.0, 0.0)
    return (px, py), (vx, vy)


def _velocity_part(value):
    """A velocity component as a float. NaN and non-numbers count as zero; inf stays inf and clamps."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return 0.0 if math.isnan(number) else number


def drag_stretch(vx, vy):
    """(sx, sy, angle) for the drag squash. sx = 1 + min(0.22, speed / 3000), sy = 1 / sx, angle = direction of travel."""
    x, y = _velocity_part(vx), _velocity_part(vy)
    speed = math.hypot(x, y)
    sx = 1.0 + min(STRETCH_MAX, speed / STRETCH_SPEED)  # inf speed clamps to the maximum
    return (sx, 1.0 / sx, math.atan2(y, x))


def stretch_matrix(sx, sy, angle):
    """(a, b, c, d) of R(θ)·S·R(−θ) for a CGAffineTransform. Symmetric, so the row or column order does not matter."""
    s_x = _num(sx) or 1.0
    s_y = _num(sy) or 1.0
    theta = _num(angle) or 0.0
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    a = cos_t * cos_t * s_x + sin_t * sin_t * s_y
    d = sin_t * sin_t * s_x + cos_t * cos_t * s_y
    b = cos_t * sin_t * (s_x - s_y)
    return (a, b, b, d)


def drag_roughness(samples):
    """(direction_reversals, seconds_above_3500pt_s) for a drag. samples are (t, x, y) in order, in seconds and points.

    A reversal is a segment whose direction flips against the one before, with both moving at REVERSAL_MIN_SPEED or
    faster. Non-finite samples and segments with no time between them are skipped.
    """
    points = []
    for sample in samples or ():
        try:
            t, x, y = float(sample[0]), float(sample[1]), float(sample[2])
        except (TypeError, ValueError, IndexError):
            continue
        if math.isfinite(t) and math.isfinite(x) and math.isfinite(y):
            points.append((t, x, y))
    reversals = 0
    seconds_fast = 0.0
    previous = None  # (vx, vy, speed) of the last segment that had time in it
    for (t0, x0, y0), (t1, x1, y1) in zip(points, points[1:]):
        dt = t1 - t0
        if dt <= 0.0:
            continue
        vx, vy = (x1 - x0) / dt, (y1 - y0) / dt
        speed = math.hypot(vx, vy)
        if speed > ROUGH_SPEED:
            seconds_fast += dt
        if previous is not None:
            pvx, pvy, pspeed = previous
            if (speed >= REVERSAL_MIN_SPEED and pspeed >= REVERSAL_MIN_SPEED
                    and vx * pvx + vy * pvy < 0.0):
                reversals += 1
        previous = (vx, vy, speed)
    if not math.isfinite(seconds_fast):
        seconds_fast = 0.0
    return (reversals, seconds_fast)


# Peek-dock (PR 3b). A snapped orb on a free screen edge tucks most of itself off-screen.
PEEK_VISIBLE_FRACTION = 0.75  # share of the orb window still on screen at rest (33 pt of a 44 pt window)
PEEK_MIN_VISIBLE = 32.0  # pt still on screen at rest, whatever the window size
PEEK_GLOW_WIDTH = 14.0  # pt: the soft blue edge on the visible side of a tucked orb
PEEK_GLOW_ALPHA = 0.85  # opacity of the glow at the screen edge (fades to 0 across its width)
PEEK_GLOW_FADE_SECONDS = 0.15
PEEK_HOT_DISTANCE = 24.0  # cursor this close to the edge slides the orb in
PEEK_HOT_Y = 100.0  # ... and within this many points of the orb's centre height
PEEK_RETRACT_DISTANCE = 120.0  # cursor this far from the orb starts the retract timer
PEEK_RETRACT_SECONDS = 1.5
PEEK_FADE_SECONDS = 0.15  # Reduce Motion: fade instead of sliding
PEEK_EDGE_TOLERANCE = 1.0  # pt, for "touches" and "is at the edge"


def _span_overlap(a0, a1, b0, b1):
    return min(a1, b1) - max(a0, b0)


def peek_edge_allowed(edge, screen, screens):
    """False when another display's visible frame touches this edge of `screen` with vertical overlap.

    Peeking on a shared edge would hide the orb on the other display, so that edge is never allowed.
    """
    if edge not in ("left", "right") or not screen:
        return False
    try:
        sx, sy, sw, sh = (float(v) for v in screen)
    except (TypeError, ValueError):
        return False
    for other in screens or ():
        try:
            ox, oy, ow, oh = (float(v) for v in other)
        except (TypeError, ValueError):
            continue
        if (ox, oy, ow, oh) == (sx, sy, sw, sh):
            continue
        if _span_overlap(sy, sy + sh, oy, oy + oh) <= 0.0:
            continue
        if edge == "left" and abs((ox + ow) - sx) <= PEEK_EDGE_TOLERANCE:
            return False
        if edge == "right" and abs(ox - (sx + sw)) <= PEEK_EDGE_TOLERANCE:
            return False
    return True


def peek_visible_width(width):
    """Points of a tucked orb window that stay on screen: PEEK_VISIBLE_FRACTION of it, at least PEEK_MIN_VISIBLE, never more than it."""
    w = max(0.0, float(width))
    return min(w, max(PEEK_MIN_VISIBLE, PEEK_VISIBLE_FRACTION * w))


def peek_frame(origin, size, screen, edge):
    """Rest frame (x, y, w, h) for a tucked orb: all but peek_visible_width(w) of the width is past the edge.

    The height is kept and kept on screen.
    """
    sx, sy, sw, sh = (float(v) for v in screen)
    w, h = float(size[0]), float(size[1])
    past = w - peek_visible_width(w)
    y = float(origin[1])
    if sh >= h:
        y = min(max(y, sy), sy + sh - h)
    if edge == "left":
        x = sx - past
    elif edge == "right":
        x = sx + sw - (w - past)
    else:
        raise ValueError("peek_frame needs 'left' or 'right'")
    return (x, y, w, h)


def in_hot_zone(cursor, edge, screen, orb_center_y):
    """True when the cursor is within PEEK_HOT_DISTANCE of the edge and PEEK_HOT_Y of the orb's centre height."""
    try:
        cx, cy = float(cursor[0]), float(cursor[1])
        sx, sy, sw, sh = (float(v) for v in screen)
        oy = float(orb_center_y)
    except (TypeError, ValueError, IndexError):
        return False
    if edge == "left":
        edge_x = sx
    elif edge == "right":
        edge_x = sx + sw
    else:
        return False
    if not all(math.isfinite(v) for v in (cx, cy, oy, edge_x)):
        return False
    return abs(cx - edge_x) <= PEEK_HOT_DISTANCE and abs(cy - oy) <= PEEK_HOT_Y


def should_retract(cursor, orb_center, seconds_outside, busy):
    """True when the cursor has been more than PEEK_RETRACT_DISTANCE from the orb for PEEK_RETRACT_SECONDS, and nothing is busy.

    The caller measures seconds_outside and resets it whenever the cursor comes back. Bad input never retracts.
    """
    if busy:
        return False
    try:
        cx, cy = float(cursor[0]), float(cursor[1])
        ox, oy = float(orb_center[0]), float(orb_center[1])
        seconds = float(seconds_outside)
    except (TypeError, ValueError, IndexError):
        return False
    if not all(math.isfinite(v) for v in (cx, cy, ox, oy, seconds)):
        return False
    if seconds < PEEK_RETRACT_SECONDS:
        return False
    return math.hypot(cx - ox, cy - oy) > PEEK_RETRACT_DISTANCE
