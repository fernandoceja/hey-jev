"""The capture glimmer: what plays over the selected region when an area capture is taken. Pure Python.

macOS's own crosshair (screencapture -i) does not say which rectangle was chosen, so Jev watches the pointer while the
crosshair is up: where the left button went down and where it came back up. That rectangle is where the glimmer plays.
The glimmer starts only after the image file is written, so it can never be part of the captured picture.

The look is Jev's own, in the orb's blue: a translucent blue wash, a thin cyan-blue border with a soft glow, a short
shimmer sweep, and a few cyan sparkles near the edges and corners, then a smooth fade. Every color comes from the
orb's constants in orb_motion, so the glimmer follows the orb if its palette ever changes.
"""
import math
import random

from orb_motion import LISTEN_GLYPH_RGB, ORB_PALETTE, RING_RGB

# Colors, taken from the orb: its blue body, its cyan-blue ring, and its light cyan highlight.
WASH_RGB = ORB_PALETTE[1]  # the orb's blue body
BORDER_RGB = RING_RGB  # the orb's cyan-blue ring: the border and its glow
SPARKLE_RGB = LISTEN_GLYPH_RGB  # the orb's light cyan highlight: the sparkles
BAND_RGB = LISTEN_GLYPH_RGB  # and the sweep's bright band

GLIMMER_SECONDS = 0.6  # wash, sweep, sparkles and the fade out
GLIMMER_REDUCED_SECONDS = 0.4  # Reduce Motion: a steady highlight and border, no sweep or sparkles
GLIMMER_BAND = 0.5  # the bright band's width as a fraction of the region's width
GLIMMER_WASH_ALPHA = 0.25  # the translucent blue over the whole region
GLIMMER_REDUCED_WASH_ALPHA = 0.30  # Reduce Motion: a little firmer, since nothing moves
GLIMMER_BAND_ALPHA = 0.50  # the sweeping band's peak
GLIMMER_BORDER_WIDTH = 1.5
GLIMMER_BORDER_ALPHA = 0.95
GLIMMER_GLOW_RADIUS = 8.0  # soft glow around the border
GLIMMER_GLOW_OPACITY = 0.85
GLIMMER_PAD = 16.0  # the overlay extends this far past the region so the glow is not clipped
GLIMMER_MIN_SIDE = 4.0  # a smaller drag is a click, not a selection
GLIMMER_POLL_SECONDS = 0.01  # how often the pointer is sampled while the crosshair is up
PANEL_AFTER_GLIMMER_GAP = 0.05  # the capture panel appears this long after the glimmer ends

SPARKLE_COUNT = 7
SPARKLE_SIZE = (5.0, 10.0)  # points, tip to tip
SPARKLE_LIFE = (0.22, 0.38)  # seconds each one twinkles
SPARKLE_SPREAD = 0.4  # sparkles start within this fraction of the glimmer's length


def rgba(rgb, alpha):
    """(r, g, b, a) from an orb color and an alpha."""
    return (float(rgb[0]), float(rgb[1]), float(rgb[2]), float(alpha))


def star_points(size):
    """The eight vertices of a four-point sparkle centred on (0, 0), tip to tip `size` points across."""
    outer = float(size) / 2.0
    inner = outer * 0.32
    points = []
    for i in range(8):
        angle = math.pi / 2.0 + i * math.pi / 4.0
        radius = outer if i % 2 == 0 else inner
        points.append((radius * math.cos(angle), radius * math.sin(angle)))
    return points


def sparkle_specs(width, height, seconds=GLIMMER_SECONDS, count=SPARKLE_COUNT, rng=None):
    """Where and when the sparkles twinkle, in the region's own coordinates (origin at its bottom-left corner).

    The first one sits at a corner. The rest sit along the edges, a little in or out of the border. Each has a
    size, a start delay and a short life, so they twinkle in turn rather than all at once.
    """
    rng = rng or random.Random()
    width, height = float(width), float(height)
    specs = []
    corners = [(0.0, 0.0), (width, 0.0), (0.0, height), (width, height)]
    for i in range(int(count)):
        if i == 0:
            cx, cy = rng.choice(corners)
            x, y = cx + rng.uniform(-4.0, 4.0), cy + rng.uniform(-4.0, 4.0)
        else:
            edge = rng.randrange(4)
            t = rng.uniform(0.08, 0.92)
            off = rng.uniform(-4.0, 6.0)
            if edge == 0:
                x, y = t * width, off
            elif edge == 1:
                x, y = t * width, height - off
            elif edge == 2:
                x, y = off, t * height
            else:
                x, y = width - off, t * height
        life = rng.uniform(*SPARKLE_LIFE)
        specs.append({
            "x": x, "y": y,
            "size": rng.uniform(*SPARKLE_SIZE),
            "delay": rng.uniform(0.0, max(0.0, float(seconds) * SPARKLE_SPREAD)),
            "life": life,
        })
    return specs


def rect_from_points(a, b, min_side=GLIMMER_MIN_SIDE):
    """(x, y, w, h) spanned by two points, or None when it is smaller than min_side on either side or not finite."""
    try:
        ax, ay, bx, by = float(a[0]), float(a[1]), float(b[0]), float(b[1])
    except (TypeError, ValueError, IndexError):
        return None
    if not all(math.isfinite(v) for v in (ax, ay, bx, by)):
        return None
    x, y = min(ax, bx), min(ay, by)
    w, h = abs(bx - ax), abs(by - ay)
    if w < min_side or h < min_side:
        return None
    return (x, y, w, h)


class DragTracker:
    """Feed it pointer samples; it reports the rectangle of the first left-button drag.

    A button that is already down when watching starts (the click that began the capture) is ignored until it is
    released, so only a press seen from its start counts.
    """

    def __init__(self):
        self._was_down = None
        self._start = None
        self._last = None
        self._rect = None
        self._release = None
        self._done = False

    @property
    def done(self):
        return self._done

    def feed(self, point, pressed):
        if self._done:
            return
        pressed = bool(pressed)
        if self._was_down is None:
            self._was_down = pressed
            self._ignore_until_up = pressed
            return
        if self._start is None:
            if self._ignore_until_up:
                if not pressed:
                    self._ignore_until_up = False
            elif pressed and not self._was_down:
                self._start = tuple(point)
                self._last = tuple(point)
        else:
            if pressed:
                self._last = tuple(point)
            else:
                self._rect = rect_from_points(self._start, tuple(point))
                self._release = tuple(point)
                self._done = True
        self._was_down = pressed

    def rect(self):
        """The drag's rectangle once the button came up, else None (no drag, or too small)."""
        return self._rect

    def release_point(self):
        """Where the pointer was when the button came up, else None."""
        return self._release


def glimmer_seconds(reduce_motion):
    return GLIMMER_REDUCED_SECONDS if reduce_motion else GLIMMER_SECONDS


def panel_delay(flash_started, now, reduce_motion):
    """Seconds the capture panel should wait so it appears after the glimmer. 0 when the glimmer is over."""
    end = float(flash_started) + glimmer_seconds(reduce_motion) + PANEL_AFTER_GLIMMER_GAP
    return max(0.0, end - float(now))
