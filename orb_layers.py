"""Core Animation layer tree for the orb. AppKit and Quartz load only when a tree is built.

Layer order, back to front: shadow, body group, highlight. The body group holds
the body (gradient layers masked to a circle), the ring, the eyes with pupils,
and the glyphs. The highlight is a sibling of the body group, so the bob moves
the body and not the shine.

The body, eyes and highlight are native CAGradientLayers with circular masks.
Only the soft shadow is a pre-rendered image, rendered once per backing scale.
"""
import math

from orb_motion import (
    BODY_SIZE,
    DESIGN_EXTENT,
    DESIGN_SIZE,
    EYE_EDGE_RGB,
    EYE_SIZE,
    GLYPH_RGB,
    HIGHLIGHT_ALPHA,
    LISTEN_GLYPH_RGB,
    ORB_PALETTE,
    RIM_ALPHA,
    RIM_RGB,
    RING_RGB,
    SHADE_ALPHA,
    SHADE_RGB,
    SHADOW_OPACITY,
    SHADOW_SIZE,
    layer_geometry,
)

_SHADOW_IMAGES = {}  # backing scale -> CGImage; the shadow does not depend on appearance

# Radial gradient ellipse radii come from the start and end points in unit space.
# This reaches the body's edge at a circular radius of about 40 pt.
_BODY_LIGHT = (0.325, 0.725)
_BODY_LIGHT_END = (0.325 + 40.0 / BODY_SIZE, 0.725 + 40.0 / BODY_SIZE)


def _cg_color(rgb, alpha=1.0):
    from AppKit import NSColor
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(rgb[0], rgb[1], rgb[2], alpha).CGColor()


def _gradient(stops):
    """Quartz gradient for the shadow image. stops: (r, g, b, a, location)."""
    from Quartz import CGColorSpaceCreateDeviceRGB, CGGradientCreateWithColorComponents
    components = []
    locations = []
    for r, g, b, a, location in stops:
        components.extend((r, g, b, a))
        locations.append(location)
    return CGGradientCreateWithColorComponents(CGColorSpaceCreateDeviceRGB(), components, locations, len(locations))


def _bitmap(width, height, scale, draw):
    """Draw in design points into a CGImage at the backing scale."""
    from Quartz import (CGBitmapContextCreate, CGBitmapContextCreateImage, CGColorSpaceCreateDeviceRGB,
                        CGContextScaleCTM, kCGImageAlphaPremultipliedLast)
    px = max(1, int(round(width * scale)))
    py = max(1, int(round(height * scale)))
    ctx = CGBitmapContextCreate(None, px, py, 8, 0, CGColorSpaceCreateDeviceRGB(), kCGImageAlphaPremultipliedLast)
    CGContextScaleCTM(ctx, px / width, py / height)
    draw(ctx)
    return CGBitmapContextCreateImage(ctx)


def _shadow_image(scale):
    key = round(float(scale), 2)
    if key not in _SHADOW_IMAGES:
        from Quartz import (CGContextDrawRadialGradient, CGContextScaleCTM, CGContextTranslateCTM, CGPointMake)
        width, height = SHADOW_SIZE
        radius = width / 2.0

        def draw(ctx):
            # Squash a circle of radius `radius` into an ellipse `height` tall, centred in the image.
            CGContextTranslateCTM(ctx, width / 2.0, height / 2.0)
            CGContextScaleCTM(ctx, 1.0, (height / 2.0) / radius)
            soft = _gradient([(0.0, 0.0, 0.0, SHADOW_OPACITY, 0.0), (0.0, 0.0, 0.0, 0.0, 1.0)])
            centre = CGPointMake(0.0, 0.0)
            CGContextDrawRadialGradient(ctx, soft, centre, 0.0, centre, radius, 0)

        _SHADOW_IMAGES[key] = _bitmap(width, height, scale, draw)
    return _SHADOW_IMAGES[key]


def is_dark(appearance):
    from AppKit import NSAppearanceNameAqua, NSAppearanceNameDarkAqua
    if appearance is None:
        return False
    name = appearance.bestMatchFromAppearancesWithNames_([NSAppearanceNameAqua, NSAppearanceNameDarkAqua])
    return name == NSAppearanceNameDarkAqua


def _ellipse_path(x, y, w, h):
    from Quartz import CGPathAddEllipseInRect, CGPathCreateMutable, CGRectMake
    path = CGPathCreateMutable()
    CGPathAddEllipseInRect(path, None, CGRectMake(x, y, w, h))
    return path


def _circle_mask(size):
    """Circular mask in its layer's own coordinates."""
    from Quartz import CAShapeLayer, CGRectMake
    mask = CAShapeLayer.layer()
    mask.setFrame_(CGRectMake(0, 0, size, size))
    mask.setPath_(_ellipse_path(0, 0, size, size))
    return mask


def _set_stops(layer, stops):
    """stops: (rgb, alpha, location) tuples."""
    layer.setColors_([_cg_color(rgb, alpha) for rgb, alpha, _ in stops])
    layer.setLocations_([location for _, _, location in stops])


def _gradient_layer(rect, stops, start, end, kind="radial"):
    from Quartz import CAGradientLayer, CGPointMake, CGRectMake
    layer = CAGradientLayer.layer()
    layer.setFrame_(CGRectMake(*rect))
    layer.setType_(kind)
    layer.setStartPoint_(CGPointMake(*start))
    layer.setEndPoint_(CGPointMake(*end))
    _set_stops(layer, stops)
    return layer


def _each_layer(layer):
    """The layer, its mask, and every sublayer below it."""
    yield layer
    mask = layer.mask()
    if mask is not None:
        yield from _each_layer(mask)
    for sub in layer.sublayers() or []:
        yield from _each_layer(sub)


def _shade_stops(dark):
    alpha = SHADE_ALPHA["dark" if dark else "light"]
    return [(SHADE_RGB, 0.0, 0.0), (SHADE_RGB, alpha, 1.0)]


def _glyph_paths(state):
    """Filled glyph, its colour, and an optional stroked glyph for each state cue."""
    from Quartz import (CGPathAddArc, CGPathAddEllipseInRect, CGPathAddRect, CGPathCreateMutable,
                        CGPathMoveToPoint, CGPathAddLineToPoint, CGRectMake)
    if state == "listening":
        fill = CGPathCreateMutable()
        CGPathAddEllipseInRect(fill, None, CGRectMake(33, 19, 6, 10))
        stroke = CGPathCreateMutable()
        CGPathAddArc(stroke, None, 36.0, 23.0, 5.0, math.pi, 0.0, False)
        CGPathMoveToPoint(stroke, None, 36.0, 18.0)
        CGPathAddLineToPoint(stroke, None, 36.0, 15.0)
        return fill, LISTEN_GLYPH_RGB, stroke
    if state == "thinking":
        fill = CGPathCreateMutable()
        for x in (29, 35, 41):
            CGPathAddEllipseInRect(fill, None, CGRectMake(x, 21, 2, 2))
        return fill, GLYPH_RGB, None
    if state == "speaking":
        return _ellipse_path(32, 18, 8, 5), GLYPH_RGB, None
    if state == "error":
        fill = CGPathCreateMutable()
        CGPathAddRect(fill, None, CGRectMake(35, 21, 2, 7))
        CGPathAddEllipseInRect(fill, None, CGRectMake(35, 17, 2, 2))
        return fill, GLYPH_RGB, None
    return None, GLYPH_RGB, None


class OrbLayers:
    """Owns the layer tree under a host layer. Frames come from orb_motion.layer_geometry."""

    def __init__(self, host):
        from Quartz import CALayer, CAShapeLayer, CGPointMake, CGRectMake
        geometry = layer_geometry()

        def place(layer, rect):
            layer.setFrame_(CGRectMake(*rect))
            return layer

        self.root = CALayer.layer()
        self.root.setBounds_(CGRectMake(0, 0, DESIGN_SIZE, DESIGN_SIZE))
        self.root.setAnchorPoint_(CGPointMake(0.5, 0.5))
        host.addSublayer_(self.root)

        self.shadow = place(CALayer.layer(), geometry["shadow"])

        # Body: gradient layers, clipped to a circle by the container's mask.
        local = (0, 0, BODY_SIZE, BODY_SIZE)
        self.body = place(CALayer.layer(), geometry["body"])
        self.body.setMask_(_circle_mask(BODY_SIZE))
        self.base = _gradient_layer(local, [(c, 1.0, loc) for c, loc in zip(ORB_PALETTE, (0.0, 0.5, 1.0))],
                                          _BODY_LIGHT, _BODY_LIGHT_END)
        self.shade = _gradient_layer(local, _shade_stops(False), (0.5, 0.5), (0.5, 0.0), kind="axial")
        self.rim = _gradient_layer(local, [(RIM_RGB, 0.0, 0.0), (RIM_RGB, RIM_ALPHA, 1.0)],
                                         (0.5, 0.5), (1.0, 1.0))
        self.outline = CAShapeLayer.layer()
        place(self.outline, local)
        self.outline.setFillColor_(None)
        self.outline.setStrokeColor_(_cg_color((1.0, 1.0, 1.0), 0.18))
        self.outline.setLineWidth_(0.75)
        self.outline.setPath_(_ellipse_path(0.375, 0.375, BODY_SIZE - 0.75, BODY_SIZE - 0.75))
        self.body.setSublayers_([self.base, self.shade, self.rim, self.outline])

        self.ring = place(CAShapeLayer.layer(), (0, 0, DESIGN_SIZE, DESIGN_SIZE))
        self.ring.setFillColor_(None)
        self.ring.setStrokeColor_(_cg_color(RING_RGB))
        ring = geometry["ring"]
        self.ring.setPath_(_ellipse_path(ring[0], ring[1], ring[2], ring[3]))

        self.eyes = {}
        self.pupils = {}
        for side in ("L", "R"):
            eye_rect = geometry["eye" + side]
            pupil_rect = geometry["pupil" + side]
            eye = _gradient_layer((0, 0, EYE_SIZE, EYE_SIZE),
                                        [((1.0, 1.0, 1.0), 1.0, 0.0), (EYE_EDGE_RGB, 1.0, 1.0)],
                                        (0.5, 0.5), (1.0, 1.0))
            eye.setMask_(_circle_mask(EYE_SIZE))
            place(eye, eye_rect)
            pupil = CAShapeLayer.layer()
            pupil.setFrame_(CGRectMake(pupil_rect[0] - eye_rect[0], pupil_rect[1] - eye_rect[1],
                                       pupil_rect[2], pupil_rect[3]))
            pupil.setFillColor_(_cg_color((0.0, 0.0, 0.0)))
            pupil.setPath_(_ellipse_path(0, 0, pupil_rect[2], pupil_rect[3]))
            eye.addSublayer_(pupil)
            self.eyes[side] = eye
            self.pupils[side] = pupil

        self.glyph = place(CAShapeLayer.layer(), (0, 0, DESIGN_SIZE, DESIGN_SIZE))
        self.glyph_stroke = place(CAShapeLayer.layer(), (0, 0, DESIGN_SIZE, DESIGN_SIZE))
        self.glyph_stroke.setFillColor_(None)
        self.glyph_stroke.setLineWidth_(1.5)

        self.highlight = _gradient_layer(geometry["highlight"],
                                               [((1.0, 1.0, 1.0), HIGHLIGHT_ALPHA, 0.0),
                                                ((1.0, 1.0, 1.0), 0.0, 1.0)],
                                               (0.5, 0.5), (1.0, 1.0))

        self.body_group = place(CALayer.layer(), (0, 0, DESIGN_SIZE, DESIGN_SIZE))
        self.body_group.setSublayers_([self.body, self.ring, self.eyes["L"], self.eyes["R"],
                                       self.glyph, self.glyph_stroke])
        self.root.setSublayers_([self.shadow, self.body_group, self.highlight])

    def fit(self, width, height):
        """Centre the design space in the view and scale it like the old drawRect_ path."""
        from Quartz import CGAffineTransformMakeScale, CGPointMake
        scale = min(width, height) / DESIGN_EXTENT if min(width, height) > 0 else 1.0
        self._disable_actions(lambda: (
            self.root.setPosition_(CGPointMake(width / 2.0, height / 2.0)),
            self.root.setAffineTransform_(CGAffineTransformMakeScale(scale, scale)),
        ))

    def rescale(self, backing_scale, dark):
        """Set contentsScale on every layer, the shadow image, and the shade colours for the appearance."""
        image = _shadow_image(backing_scale)
        for layer in _each_layer(self.root):
            layer.setContentsScale_(backing_scale)
        self._disable_actions(lambda: (
            self.shadow.setContents_(image),
            _set_stops(self.shade, _shade_stops(dark)),
        ))

    def apply(self, state, solid, ring_width):
        """State cues and the thinking eye squash. Motion is not in this PR."""
        from Quartz import CGAffineTransformIdentity, CGAffineTransformMakeScale
        fill, fill_rgb, stroke = _glyph_paths(state)

        def update():
            self.root.setHidden_(bool(solid))
            self.glyph.setFillColor_(_cg_color(fill_rgb))
            self.glyph.setPath_(fill)
            self.glyph_stroke.setStrokeColor_(_cg_color(LISTEN_GLYPH_RGB))
            self.glyph_stroke.setPath_(stroke)
            self.ring.setHidden_(state != "listening")
            self.ring.setLineWidth_(ring_width)
            squash = CGAffineTransformMakeScale(1.0, 0.5) if state == "thinking" else CGAffineTransformIdentity
            for eye in self.eyes.values():
                eye.setAffineTransform_(squash)
        self._disable_actions(update)

    def set_ring_width(self, width):
        self._disable_actions(lambda: self.ring.setLineWidth_(width))

    @staticmethod
    def _disable_actions(work):
        from Quartz import CATransaction
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        try:
            work()
        finally:
            CATransaction.commit()
