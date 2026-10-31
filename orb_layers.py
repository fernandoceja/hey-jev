"""Core Animation layer tree for the orb. AppKit and Quartz load only when a tree is built.

Layer order, back to front: shadow, body group (body, ring, eyes with pupils,
glyphs), then highlight. The highlight is a sibling of the body group so the
bob moves the body and not the shine.
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
    HIGHLIGHT_SIZE,
    LISTEN_GLYPH_RGB,
    ORB_PALETTE,
    RIM_ALPHA,
    RIM_RGB,
    RING_RGB,
    SHADE_ALPHA,
    SHADE_RGB,
    SHADOW_OPACITY,
    SHADOW_RADIUS,
    layer_geometry,
)

_IMAGES = {}  # (kind, palette, scale, dark) -> CGImage; rendered once per key


def _cg_color(rgb, alpha=1.0):
    from AppKit import NSColor
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(rgb[0], rgb[1], rgb[2], alpha).CGColor()


def _gradient(stops):
    """stops: (r, g, b, a, location) tuples, location 0–1."""
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


def _render_body(scale, dark):
    from Quartz import (CGContextAddEllipseInRect, CGContextClip, CGContextDrawLinearGradient,
                        CGContextDrawRadialGradient, CGContextRestoreGState, CGContextSaveGState,
                        CGContextSetLineWidth, CGContextSetRGBStrokeColor, CGContextStrokeEllipseInRect,
                        CGPointMake, CGRectMake)
    size = BODY_SIZE
    centre = size / 2.0
    light_point = CGPointMake(centre - 0.35 * centre, centre + 0.45 * centre)

    def draw(ctx):
        CGContextSaveGState(ctx)
        CGContextAddEllipseInRect(ctx, CGRectMake(0, 0, size, size))
        CGContextClip(ctx)
        base = _gradient([(c[0], c[1], c[2], 1.0, loc) for c, loc in zip(ORB_PALETTE, (0.0, 0.5, 1.0))])
        CGContextDrawRadialGradient(ctx, base, light_point, 0.0, light_point, 40.0, 0)
        shade = _gradient([
            (SHADE_RGB[0], SHADE_RGB[1], SHADE_RGB[2], 0.0, 0.0),
            (SHADE_RGB[0], SHADE_RGB[1], SHADE_RGB[2], SHADE_ALPHA["dark" if dark else "light"], 1.0)])
        CGContextDrawLinearGradient(ctx, shade, CGPointMake(centre, centre), CGPointMake(centre, 0.0), 0)
        rim = _gradient([(RIM_RGB[0], RIM_RGB[1], RIM_RGB[2], 0.0, 0.0),
                         (RIM_RGB[0], RIM_RGB[1], RIM_RGB[2], RIM_ALPHA, 1.0)])
        CGContextDrawRadialGradient(ctx, rim, CGPointMake(centre, centre), 0.0,
                                    CGPointMake(centre, centre), centre, 0)
        CGContextRestoreGState(ctx)
        CGContextSetRGBStrokeColor(ctx, 1.0, 1.0, 1.0, 0.18)
        CGContextSetLineWidth(ctx, 0.75)
        CGContextStrokeEllipseInRect(ctx, CGRectMake(0.375, 0.375, size - 0.75, size - 0.75))

    return _bitmap(size, size, scale, draw)


def _render_eye(scale):
    from Quartz import (CGContextAddEllipseInRect, CGContextClip, CGContextDrawRadialGradient,
                        CGPointMake, CGRectMake, CGContextSaveGState, CGContextRestoreGState)
    half = EYE_SIZE / 2.0
    centre = CGPointMake(half, half)

    def draw(ctx):
        CGContextSaveGState(ctx)
        CGContextAddEllipseInRect(ctx, CGRectMake(0, 0, EYE_SIZE, EYE_SIZE))
        CGContextClip(ctx)
        white = _gradient([(1.0, 1.0, 1.0, 1.0, 0.0),
                           (EYE_EDGE_RGB[0], EYE_EDGE_RGB[1], EYE_EDGE_RGB[2], 1.0, 1.0)])
        CGContextDrawRadialGradient(ctx, white, centre, 0.0, centre, half, 0)
        CGContextRestoreGState(ctx)

    return _bitmap(EYE_SIZE, EYE_SIZE, scale, draw)


def _render_highlight(scale):
    from Quartz import (CGContextAddEllipseInRect, CGContextClip, CGContextDrawRadialGradient,
                        CGContextRestoreGState, CGContextSaveGState, CGPointMake, CGRectMake)
    width, height = HIGHLIGHT_SIZE
    centre = CGPointMake(width / 2.0, height / 2.0)

    def draw(ctx):
        CGContextSaveGState(ctx)
        CGContextAddEllipseInRect(ctx, CGRectMake(0, 0, width, height))
        CGContextClip(ctx)
        soft = _gradient([(1.0, 1.0, 1.0, HIGHLIGHT_ALPHA, 0.0), (1.0, 1.0, 1.0, 0.0, 1.0)])
        CGContextDrawRadialGradient(ctx, soft, centre, 0.0, centre, width / 2.0, 0)
        CGContextRestoreGState(ctx)

    return _bitmap(width, height, scale, draw)


def _cached(kind, scale, dark, render):
    key = (kind, ORB_PALETTE, round(float(scale), 2), bool(dark))
    if key not in _IMAGES:
        _IMAGES[key] = render()
    return _IMAGES[key]


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

        def frame(layer, rect):
            layer.setFrame_(CGRectMake(*rect))
            return layer

        self.root = CALayer.layer()
        self.root.setBounds_(CGRectMake(0, 0, DESIGN_SIZE, DESIGN_SIZE))
        self.root.setAnchorPoint_(CGPointMake(0.5, 0.5))
        host.addSublayer_(self.root)

        self.shadow = frame(CALayer.layer(), geometry["shadow"])
        shadow_w, shadow_h = geometry["shadow"][2], geometry["shadow"][3]
        self.shadow.setShadowPath_(_ellipse_path(0, 0, shadow_w, shadow_h))
        self.shadow.setShadowColor_(_cg_color((0.0, 0.0, 0.0)))
        self.shadow.setShadowOpacity_(SHADOW_OPACITY)
        self.shadow.setShadowRadius_(SHADOW_RADIUS)
        self.shadow.setShadowOffset_((0.0, 0.0))

        self.body_group = frame(CALayer.layer(), (0, 0, DESIGN_SIZE, DESIGN_SIZE))
        self.body = frame(CALayer.layer(), geometry["body"])
        self.ring = frame(CAShapeLayer.layer(), (0, 0, DESIGN_SIZE, DESIGN_SIZE))
        self.ring.setFillColor_(None)
        self.ring.setStrokeColor_(_cg_color(RING_RGB))
        self.ring.setPath_(_ellipse_path(geometry["ring"][0], geometry["ring"][1],
                                         geometry["ring"][2], geometry["ring"][3]))
        self.eyes = {}
        self.pupils = {}
        for side in ("L", "R"):
            eye_rect = geometry["eye" + side]
            pupil_rect = geometry["pupil" + side]
            eye = frame(CALayer.layer(), eye_rect)
            pupil = CAShapeLayer.layer()
            pupil.setFrame_(CGRectMake(pupil_rect[0] - eye_rect[0], pupil_rect[1] - eye_rect[1],
                                       pupil_rect[2], pupil_rect[3]))
            pupil.setFillColor_(_cg_color((0.0, 0.0, 0.0)))
            pupil.setPath_(_ellipse_path(0, 0, pupil_rect[2], pupil_rect[3]))
            eye.addSublayer_(pupil)
            self.eyes[side] = eye
            self.pupils[side] = pupil

        self.glyph = frame(CAShapeLayer.layer(), (0, 0, DESIGN_SIZE, DESIGN_SIZE))
        self.glyph_stroke = frame(CAShapeLayer.layer(), (0, 0, DESIGN_SIZE, DESIGN_SIZE))
        self.glyph_stroke.setFillColor_(None)
        self.glyph_stroke.setLineWidth_(1.5)

        self.highlight = frame(CALayer.layer(), geometry["highlight"])

        self.root.setSublayers_([self.shadow, self.body_group, self.highlight])
        self.body_group.setSublayers_([self.body, self.ring, self.eyes["L"], self.eyes["R"],
                                       self.glyph, self.glyph_stroke])
        self._all = [self.root, self.shadow, self.body_group, self.body, self.ring,
                     self.eyes["L"], self.eyes["R"], self.pupils["L"], self.pupils["R"],
                     self.glyph, self.glyph_stroke, self.highlight]

    def fit(self, width, height):
        """Centre the design space in the view and scale it like the old drawRect_ path."""
        from Quartz import CGAffineTransformMakeScale, CGPointMake
        scale = min(width, height) / DESIGN_EXTENT if min(width, height) > 0 else 1.0
        self._disable_actions(lambda: (
            self.root.setPosition_(CGPointMake(width / 2.0, height / 2.0)),
            self.root.setAffineTransform_(CGAffineTransformMakeScale(scale, scale)),
        ))

    def rescale(self, backing_scale, dark):
        """Set contents and contentsScale at the backing scale. Images are cached per key."""
        body = _cached("body", backing_scale, dark, lambda: _render_body(backing_scale, dark))
        eye = _cached("eye", backing_scale, dark, lambda: _render_eye(backing_scale))
        highlight = _cached("highlight", backing_scale, dark, lambda: _render_highlight(backing_scale))
        for layer in self._all:
            layer.setContentsScale_(backing_scale)
        self._disable_actions(lambda: (
            self.body.setContents_(body),
            self.highlight.setContents_(highlight),
            self.eyes["L"].setContents_(eye),
            self.eyes["R"].setContents_(eye),
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
