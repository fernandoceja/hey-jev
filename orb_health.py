"""Is the orb actually drawing? Pure checks on a snapshot of the live window, views and layers. No AppKit.

The window can be on screen at level 28 with alpha 1 and still show nothing, if the content view is hidden
or transparent, the orb view is hidden or laid out outside the window, the orb's layer tree has come loose
from the view's backing layer (AppKit may replace a layer-backed view's layer), or a layer is at opacity 0
or has empty bounds. render_problems names each of those; the delegate heals them and logs the snapshot.
"""

ORB_LAYERS = ("root", "squash", "body_group", "body")


def _rect_ok(rect):
    try:
        x, y, w, h = (float(v) for v in rect)
    except (TypeError, ValueError):
        return False
    return w > 0.0 and h > 0.0 and all(v == v and abs(v) != float("inf") for v in (x, y, w, h))


def _inside(rect, bounds, slack=0.5):
    x, y, w, h = (float(v) for v in rect)
    bx, by, bw, bh = (float(v) for v in bounds)
    return x >= bx - slack and y >= by - slack and x + w <= bx + bw + slack and y + h <= by + bh + slack


def render_problems(snapshot):
    """Names of everything that would stop the orb drawing. Empty means it should be visible.

    snapshot keys: content_hidden, content_alpha, content_layer_opacity (None when not layer-backed),
    content_bounds, orb_hidden, orb_frame, tree_attached, layers {name: (opacity, width, height)}.
    """
    problems = []
    if snapshot.get("content_hidden"):
        problems.append("content_hidden")
    if float(snapshot.get("content_alpha", 1.0)) < 0.99:
        problems.append("content_alpha")
    opacity = snapshot.get("content_layer_opacity")
    if opacity is not None and float(opacity) < 0.99:
        problems.append("content_layer_opacity")
    if snapshot.get("orb_hidden"):
        problems.append("orb_hidden")
    frame = snapshot.get("orb_frame")
    bounds = snapshot.get("content_bounds")
    if not _rect_ok(frame):
        problems.append("orb_frame_empty")
    elif _rect_ok(bounds) and not _inside(frame, bounds):
        problems.append("orb_frame_outside")
    if not snapshot.get("tree_attached", True):
        problems.append("tree_detached")
    layers = snapshot.get("layers") or {}
    for name in ORB_LAYERS:
        if name not in layers:
            continue
        layer_opacity, width, height = layers[name]
        if float(layer_opacity) < 0.99:
            problems.append(name + "_opacity")
        if not (float(width) > 0.0 and float(height) > 0.0):
            problems.append(name + "_bounds")
    return problems


def render_summary(snapshot, problems):
    """Compact key=value text appended to the 'jev orb window' stderr line."""
    layers = snapshot.get("layers") or {}
    parts = [
        "contentHidden={0}".format(bool(snapshot.get("content_hidden"))),
        "contentAlpha={0:.2f}".format(float(snapshot.get("content_alpha", 1.0))),
        "contentLayerOpacity={0}".format(
            "none" if snapshot.get("content_layer_opacity") is None
            else "{0:.2f}".format(float(snapshot["content_layer_opacity"]))),
        "orbHidden={0}".format(bool(snapshot.get("orb_hidden"))),
        "orbFrame={0}".format(_fmt_rect(snapshot.get("orb_frame"))),
        "contentBounds={0}".format(_fmt_rect(snapshot.get("content_bounds"))),
        "treeAttached={0}".format(bool(snapshot.get("tree_attached", True))),
    ]
    for name in ORB_LAYERS:
        if name in layers:
            opacity, width, height = layers[name]
            parts.append("{0}={1:.2f}@{2:.0f}x{3:.0f}".format(name, float(opacity), float(width), float(height)))
    parts.append("problems={0}".format(",".join(problems) if problems else "none"))
    return " ".join(parts)


def _fmt_rect(rect):
    try:
        return "{0:.0f},{1:.0f},{2:.0f}x{3:.0f}".format(*(float(v) for v in rect))
    except (TypeError, ValueError):
        return "none"
