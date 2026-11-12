"""The capture glimmer: a short sweep over the selected region when an area capture is taken. Pure Python.

macOS's own crosshair (screencapture -i) does not say which rectangle was chosen, so Jev watches the pointer while the
crosshair is up: where the left button went down and where it came back up. That rectangle is where the glimmer plays.
The glimmer starts only after the image file is written, so it can never be part of the captured picture.
"""
import math

GLIMMER_SECONDS = 0.5  # one sweep, plus the fade out
GLIMMER_REDUCED_SECONDS = 0.4  # Reduce Motion: a steady brief highlight, no sweep
GLIMMER_BAND = 0.5  # the bright band's width as a fraction of the region's width
GLIMMER_BASE_ALPHA = 0.10  # white wash over the whole region
GLIMMER_BAND_ALPHA = 0.55  # the sweeping band's peak
GLIMMER_REDUCED_ALPHA = 0.22  # the steady highlight
GLIMMER_MIN_SIDE = 4.0  # a smaller drag is a click, not a selection
GLIMMER_POLL_SECONDS = 0.01  # how often the pointer is sampled while the crosshair is up
PANEL_AFTER_GLIMMER_GAP = 0.05  # the capture panel appears this long after the glimmer ends


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
                self._done = True
        self._was_down = pressed

    def rect(self):
        """The drag's rectangle once the button came up, else None (no drag, or too small)."""
        return self._rect


def glimmer_seconds(reduce_motion):
    return GLIMMER_REDUCED_SECONDS if reduce_motion else GLIMMER_SECONDS


def panel_delay(flash_started, now, reduce_motion):
    """Seconds the capture panel should wait so it appears after the glimmer. 0 when the glimmer is over."""
    end = float(flash_started) + glimmer_seconds(reduce_motion) + PANEL_AFTER_GLIMMER_GAP
    return max(0.0, end - float(now))
