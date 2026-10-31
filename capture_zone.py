"""Edge capture zone: geometry, show and hide rules, and copy. Pure Python: no AppKit, Quartz or Cocoa.

Frames are (x, y, w, h) in AppKit screen coordinates, the same as orb_motion. A zone is anchored to one
outer screen edge. `edge` is one of "left", "right", "top", "bottom". Screens are passed as full frames,
so the cursor can reach the edge under the Dock or the menu bar. zone_frame takes the visible frame.
"""
import math

from orb_motion import spring

ZONE_W = 260.0
ZONE_H = 56.0
ZONE_RADIUS = 14.0
ZONE_TEXT = "Drag to capture · Esc to cancel"

ZONE_EDGES = ("left", "right", "top", "bottom")
ZONE_SHOW_DISTANCE = 4.0  # pt: cursor this close to an outer edge shows the zone
ZONE_APPROACH_DISTANCE = 40.0  # pt: a fast approach shows it from this far out
ZONE_APPROACH_SPEED = 1500.0  # pt/s toward the edge
ZONE_HIDE_DISTANCE = 80.0  # pt: a shown zone hides only beyond this (hysteresis)
ZONE_EDGE_TOLERANCE = 1.0  # pt, for "touches another display"
ZONE_SLIDE_IN_SECONDS = 0.22  # spring k=500, c=40 (see orb_motion.SPRING_CAPTURE_ZONE)
ZONE_SLIDE_OUT_SECONDS = 0.18  # easeIn
ZONE_SPRING = (500.0, 40.0)


def _rect(values):
    """(x, y, w, h) as floats, or None for bad input or an empty size."""
    try:
        out = tuple(float(v) for v in values)
    except (TypeError, ValueError):
        return None
    if len(out) != 4 or not all(math.isfinite(v) for v in out):
        return None
    if out[2] <= 0.0 or out[3] <= 0.0:
        return None
    return out


def _point(values):
    try:
        x, y = (float(v) for v in values)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return (x, y)


def _overlap(a0, a1, b0, b1):
    return min(a1, b1) - max(a0, b0)


def _clamp_axis(pos, start, length, size):
    """Keep a span of `size` inside [start, start + length]. A span bigger than the screen sits at start."""
    if size >= length:
        return start
    return min(max(pos, start), start + length - size)


def is_outer_edge(edge, screen, screens):
    """True when no other display touches `screen` along this edge.

    A display counts as touching only when it shares a span of that edge, so a corner-only contact stays outer.
    """
    if edge not in ZONE_EDGES:
        return False
    s = _rect(screen) if screen is not None else None
    if s is None:
        return False
    sx, sy, sw, sh = s
    for other in screens or ():
        o = _rect(other)
        if o is None or o == s:
            continue
        ox, oy, ow, oh = o
        if edge in ("left", "right"):
            if _overlap(sy, sy + sh, oy, oy + oh) <= 0.0:
                continue
            if edge == "left" and abs((ox + ow) - sx) <= ZONE_EDGE_TOLERANCE:
                return False
            if edge == "right" and abs(ox - (sx + sw)) <= ZONE_EDGE_TOLERANCE:
                return False
        else:
            if _overlap(sx, sx + sw, ox, ox + ow) <= 0.0:
                continue
            if edge == "bottom" and abs((oy + oh) - sy) <= ZONE_EDGE_TOLERANCE:
                return False
            if edge == "top" and abs(oy - (sy + sh)) <= ZONE_EDGE_TOLERANCE:
                return False
    return True


def screen_at(cursor, screens):
    """The full frame that contains the cursor (edges included), or None when it is on no screen."""
    c = _point(cursor)
    if c is None:
        return None
    for frame in screens or ():
        s = _rect(frame)
        if s is None:
            continue
        sx, sy, sw, sh = s
        if sx <= c[0] <= sx + sw and sy <= c[1] <= sy + sh:
            return s
    return None


def inward_distance(edge, cursor, screen):
    """Points from the cursor to `edge` of `screen`, positive inside the screen. Past the edge is negative."""
    sx, sy, sw, sh = _rect(screen)
    x, y = _point(cursor)
    if edge == "left":
        return x - sx
    if edge == "right":
        return sx + sw - x
    if edge == "bottom":
        return y - sy
    if edge == "top":
        return sy + sh - y
    raise ValueError("unknown edge: {0!r}".format(edge))


def _toward_speed(edge, velocity):
    """Speed toward `edge` in pt/s. Positive means moving toward it."""
    vx, vy = velocity
    return {"left": -vx, "right": vx, "bottom": -vy, "top": vy}[edge]


def zone_state(prev_shown, cursor, velocity, screen, screens):
    """The edge the zone should show on now, or None.

    prev_shown is the edge shown last tick, or None. A shown zone stays up until the cursor is beyond
    ZONE_HIDE_DISTANCE from its edge. A hidden zone shows when the cursor is within ZONE_SHOW_DISTANCE of an
    outer edge, or within ZONE_APPROACH_DISTANCE of one while moving toward it faster than ZONE_APPROACH_SPEED.
    When several edges qualify, the nearest wins. Bad input hides the zone.
    """
    s = _rect(screen) if screen is not None else None
    c = _point(cursor)
    if s is None or c is None:
        return None
    v = _point(velocity) or (0.0, 0.0)
    if prev_shown in ZONE_EDGES and is_outer_edge(prev_shown, s, screens):
        if inward_distance(prev_shown, c, s) <= ZONE_HIDE_DISTANCE:
            return prev_shown
    best = None
    for edge in ZONE_EDGES:
        if not is_outer_edge(edge, s, screens):
            continue
        d = inward_distance(edge, c, s)
        close = d <= ZONE_SHOW_DISTANCE
        fast = d <= ZONE_APPROACH_DISTANCE and _toward_speed(edge, v) > ZONE_APPROACH_SPEED
        if (close or fast) and (best is None or d < best[0]):
            best = (d, edge)
    return best[1] if best else None


def zone_frame(edge, cursor, screen):
    """Rest frame (x, y, w, h) of the zone on `edge`, flush with it and centred on the cursor along it.

    `screen` is the visible frame. The frame is clamped inside it. Returns None for bad input.
    """
    if edge not in ZONE_EDGES:
        return None
    s = _rect(screen) if screen is not None else None
    c = _point(cursor)
    if s is None or c is None:
        return None
    sx, sy, sw, sh = s
    w, h = ZONE_W, ZONE_H
    if edge in ("left", "right"):
        x = sx if edge == "left" else sx + sw - w
        y = _clamp_axis(c[1] - h / 2.0, sy, sh, h)
    else:
        y = sy if edge == "bottom" else sy + sh - h
        x = _clamp_axis(c[0] - w / 2.0, sx, sw, w)
    return (_clamp_axis(x, sx, sw, w), _clamp_axis(y, sy, sh, h), w, h)


def zone_travel(edge):
    """How far the zone slides from its rest frame to fully outside: its width for left and right, height for top and bottom."""
    if edge in ("left", "right"):
        return ZONE_W
    if edge in ("top", "bottom"):
        return ZONE_H
    raise ValueError("unknown edge: {0!r}".format(edge))


def zone_offset(edge, travel):
    """(dx, dy) to move a rest frame `travel` points outward, toward its edge's outside."""
    t = float(travel)
    return {"left": (-t, 0.0), "right": (t, 0.0), "bottom": (0.0, -t), "top": (0.0, t)}[edge]


def zone_slide_in(start, elapsed):
    """Remaining offset for a slide in: a spring from `start` to 0. Exactly 0 once ZONE_SLIDE_IN_SECONDS has passed."""
    if elapsed >= ZONE_SLIDE_IN_SECONDS:
        return 0.0
    x, _v = spring(max(0.0, float(elapsed)), float(start), 0.0, ZONE_SPRING[0], ZONE_SPRING[1])
    return x


def ease_in(progress):
    """Quadratic ease-in on [0, 1]. Clamped outside it."""
    p = min(1.0, max(0.0, float(progress)))
    return p * p


def zone_slide_out(start, travel, elapsed):
    """Offset for a slide out: from `start` to `travel` along easeIn over ZONE_SLIDE_OUT_SECONDS."""
    progress = ease_in(float(elapsed) / ZONE_SLIDE_OUT_SECONDS)
    return float(start) + (float(travel) - float(start)) * progress


class CaptureZone:
    """Edge capture zone slide state for the orb drag. Pure: the panel is injected, so tests use a fake.

    make_panel(orb_window) builds the panel on first show. It needs order_below(orb_window), set_frame(frame)
    and order_out(). The rules for when to show live in zone_state and zone_frame.

    edge is the edge the zone is anchored to, and it stays set while the zone slides out (retracting).
    offset is how far the panel sits outside its rest frame: 0 is fully in, the travel is fully out.
    """

    def __init__(self, make_panel):
        self.make_panel = make_panel
        self.panel = None
        self.edge = None
        self.rest = None
        self.offset = 0.0
        self.anim = None  # ("in" or "out", started at, offset at start)
        self.retracting = False
        self.showing = False
        self.cancelled = False  # Esc during this drag: the zone stays down, and the drop returns the orb
        self.pending = False  # a capture drop, waiting for the orb to spring home

    def visible_for_drop(self):
        return self.edge is not None and not self.retracting

    def show(self, edge, rest, orb_window, now):
        if self.edge != edge:
            self.edge = edge
            self.offset = zone_travel(edge)
            self.anim = ("in", now, self.offset)
        elif self.retracting:
            self.retracting = False
            self.anim = ("in", now, self.offset)
        self.rest = rest
        if self.panel is None:
            self.panel = self.make_panel(orb_window)
        if not self.showing:
            self.panel.order_below(orb_window)
            self.showing = True
        self.place()

    def retract(self, now):
        if self.edge is None or self.retracting:
            return
        self.retracting = True
        self.anim = ("out", now, self.offset)

    def step(self, now):
        """Advance the slide. Call once per tick, with the same clock the animation started on."""
        if self.anim is None or self.edge is None:
            return
        kind, started, start = self.anim
        elapsed = now - started
        if kind == "in":
            self.offset = zone_slide_in(start, elapsed)
            if elapsed >= ZONE_SLIDE_IN_SECONDS:
                self.offset = 0.0
                self.anim = None
        else:
            self.offset = zone_slide_out(start, zone_travel(self.edge), elapsed)
            if elapsed >= ZONE_SLIDE_OUT_SECONDS:
                self.hide_now()
                return
        self.place()

    def place(self):
        if self.panel is None or self.rest is None or self.edge is None:
            return
        dx, dy = zone_offset(self.edge, self.offset)
        x, y, w, h = self.rest
        self.panel.set_frame((x + dx, y + dy, w, h))

    def hide_now(self):
        if self.panel is not None and self.showing:
            self.panel.order_out()
        self.showing = False
        self.edge = None
        self.rest = None
        self.offset = 0.0
        self.anim = None
        self.retracting = False
