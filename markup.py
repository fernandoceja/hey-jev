"""Mark up on screen (PR 5b): the stroke model and the geometry for saving a marked-up capture.

Pure Python, no AppKit, so CI can test it. The overlay in assistant_ui.py draws these strokes and composites them
onto a silent full-screen capture. Points are in global screen points (AppKit, bottom-left origin).
"""
import math
import os
from datetime import datetime

LINE_WIDTH_PT = 3.0  # systemRed strokes, round caps
MIN_STEP_PT = 1.5  # drag points closer than this to the last kept point are dropped
ASPECT_TOLERANCE = 0.01  # a capture matches the desktop union when its width/height ratio is this close


class Strokes:
    """Finished strokes plus the one in progress. A click without a drag is not a stroke."""

    def __init__(self):
        self._done = []
        self._current = None

    def begin(self, point):
        """Start a stroke at point. A stroke still open is finished first."""
        if self._current is not None:
            self.end()
        self._current = [(float(point[0]), float(point[1]))]

    def extend(self, point):
        """Add a point to the open stroke. Returns False when it was dropped (no open stroke, or too close)."""
        if self._current is None:
            return False
        last_x, last_y = self._current[-1]
        x, y = float(point[0]), float(point[1])
        if math.hypot(x - last_x, y - last_y) < MIN_STEP_PT:
            return False
        self._current.append((x, y))
        return True

    def end(self):
        """Finish the open stroke. Returns False for a single point, which is not kept."""
        if self._current is None:
            return False
        stroke, self._current = self._current, None
        if len(stroke) < 2:
            return False
        self._done.append(stroke)
        return True

    def undo(self):
        """Remove the last finished stroke. Returns False when there is nothing to remove."""
        self.end()
        if not self._done:
            return False
        self._done.pop()
        return True

    def clear(self):
        self._done = []
        self._current = None

    def all_strokes(self):
        """Every stroke as a list of (x, y) tuples, including one in progress with at least two points."""
        strokes = [list(stroke) for stroke in self._done]
        if self._current is not None and len(self._current) >= 2:
            strokes.append(list(self._current))
        return strokes

    def count(self):
        return len(self.all_strokes())

    def is_empty(self):
        return self.count() == 0

    def bounds(self):
        """(x, y, width, height) around every point of every stroke, or None when there are no strokes."""
        points = [point for stroke in self.all_strokes() for point in stroke]
        if not points:
            return None
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        left, bottom = min(xs), min(ys)
        return (left, bottom, max(xs) - left, max(ys) - bottom)


def can_save(strokes):
    """An empty mark up is never saved."""
    return strokes is not None and not strokes.is_empty()


def markup_folder(home=None):
    """~/Documents/.cos-tmp. Temp files for a mark up go here and nowhere else."""
    base = home if home is not None else os.path.expanduser("~")
    return os.path.join(base, "Documents", ".cos-tmp")


def temp_capture_path(folder, when):
    """Unique temp file for the silent full-screen capture before the strokes are composited."""
    return os.path.join(folder, "markup-" + when.strftime("%Y%m%d-%H%M%S-%f") + ".png")


def temp_capture_now(folder):
    return temp_capture_path(folder, datetime.now())


def reference_rect(image_px, screen_frames):
    """The desktop rectangle (points) that the capture covers.

    The union of every screen when the capture's aspect ratio matches it, otherwise the first screen in the list
    (main screen first), so strokes still line up if the capture holds only one display.
    """
    frames = [tuple(float(v) for v in frame) for frame in screen_frames or []]
    if not frames:
        return None
    left = min(f[0] for f in frames)
    bottom = min(f[1] for f in frames)
    right = max(f[0] + f[2] for f in frames)
    top = max(f[1] + f[3] for f in frames)
    union = (left, bottom, right - left, top - bottom)
    width_px, height_px = image_px
    if height_px and union[3] and abs((width_px / height_px) - (union[2] / union[3])) <= ASPECT_TOLERANCE * (union[2] / union[3]):
        return union
    return frames[0]


def to_image_points(strokes, ref, image_px):
    """Map global points into the capture's pixel space. Image origin is bottom-left, as the strokes are."""
    rect_x, rect_y, rect_w, rect_h = ref
    width_px, height_px = image_px
    sx = width_px / rect_w
    sy = height_px / rect_h
    return [[((x - rect_x) * sx, (y - rect_y) * sy) for x, y in stroke] for stroke in strokes]


def image_line_width(image_px, ref):
    """The 3 pt stroke width in the capture's pixels."""
    return LINE_WIDTH_PT * (image_px[0] / ref[2])
