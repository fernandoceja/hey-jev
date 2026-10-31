"""Core Animation layer tree for the orb. AppKit and Quartz load only when a tree is built.

Layer order, back to front: shadow, body group, highlight. The body group holds
the body (gradient layers masked to a circle), the ring, the eyes with pupils,
and the glyphs. The highlight is a sibling of the body group, so the bob moves
the body and not the shine.

The body, eyes and highlight are native CAGradientLayers with circular masks.
Only the soft shadow is a pre-rendered image, rendered once per backing scale.
"""
import math
import random

from orb_character import EYE_SHAPES, accent_seconds, accent_timeline, breath_batch, eye_shape
from orb_motion import (
    MOUTH_PULSE_HZ,
    BODY_SIZE,
    BOB_AMPLITUDE,
    BOB_PERIOD,
    DESIGN_CENTER,
    DESIGN_EXTENT,
    DESIGN_SIZE,
    EYE_EDGE_RGB,
    EYE_PERSPECTIVE,
    EYE_SIZE,
    ENVELOPE_HZ,
    FLOAT_AMPLITUDE,
    FLOAT_FRAMES,
    CLIP_FPS,
    GLYPH_RGB,
    HIGHLIGHT_ALPHA,
    LISTEN_GLYPH_RGB,
    MOUTH_GLYPH_HEIGHT,
    OUTLINE_ALPHA,
    ORB_GRADIENT_ANGLE,
    ORB_PALETTE,
    PRESS_SCALE,
    PRESS_SECONDS,
    PUPIL_SIZE,
    RIM_ALPHA,
    RIM_RGB,
    RING_RGB,
    SEARCH_SWEEP_SECONDS,
    SHADE_ALPHA,
    SHADE_RGB,
    SHADOW_OPACITY,
    SHADOW_RGB,
    SHADOW_SIZE,
    SPINNER_LINE_WIDTH,
    SPINNER_RADIUS,
    SPINNER_ALPHA,
    SPINNER_SECONDS,
    SPINNER_SWEEP_DEGREES,
    SPRING_DROP_JIGGLE,
    SPRING_RELEASE,
    layer_geometry,
    mouth_height,
    pulse_mouth,
    shadow_for_bob,
    sine_samples,
    squint_scale,
    stretch_matrix,
)

FLOAT_SECONDS = FLOAT_FRAMES / float(CLIP_FPS)
MOUTH_RECT = (33.0, 23.0, 6.0, 6.0)  # design space, centred under the eyes. yawn opens it to 6 pt.
MOUTH_RGB = (0.04, 0.06, 0.22)
POSE_SECONDS = 0.25  # eye shapes morph and the body eases over this long when the pose changes
LEVEL_SECONDS = 0.12  # the listening body follows the mic level with a short implicit ease
SPIN_KEY = "spin"
SWEEP_KEY = "sweep"
SPEECH_KEY = "speech"
SPEECH_GLYPH_ANCHOR_Y = 20.5  # centre of the speaking glyph (18 to 23 pt), where its scale pivots

_SHADOW_IMAGES = {}  # backing scale -> CGImage; the shadow does not depend on appearance
SQUASH_KEY = "squash"  # press, release and jiggle share one key, so each replaces the last

# The body gradient runs along ORB_GRADIENT_ANGLE through the centre of the body, as 1c63b74's NSGradient did.
_ANGLE = math.radians(ORB_GRADIENT_ANGLE)
_BODY_START = (0.5 - 0.5 * math.cos(_ANGLE), 0.5 - 0.5 * math.sin(_ANGLE))
_BODY_END = (0.5 + 0.5 * math.cos(_ANGLE), 0.5 + 0.5 * math.sin(_ANGLE))


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
            r, g, b = SHADOW_RGB
            soft = _gradient([(r, g, b, SHADOW_OPACITY, 0.0), (r, g, b, 0.0, 1.0)])
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


def _arc_path(cx, cy, radius, sweep):
    """An arc of the given sweep (radians) starting at 3 o'clock, for the thinking spinner."""
    from Quartz import CGPathAddArc, CGPathCreateMutable
    path = CGPathCreateMutable()
    CGPathAddArc(path, None, float(cx), float(cy), float(radius), 0.0, float(sweep), False)
    return path


def _scale_y(scale):
    """Eye height only: the bar grows or shrinks, and its width stays put."""
    from Quartz import CGAffineTransformMakeScale
    return CGAffineTransformMakeScale(1.0, float(scale))


def _eye_transform(side, scale_y):
    """One eye's height from the pose, with its perspective: the left eye is a little wider and taller."""
    from Quartz import CGAffineTransformMake
    kx, ky = EYE_PERSPECTIVE[side]
    return CGAffineTransformMake(kx, 0.0, 0.0, ky * float(scale_y), 0.0, 0.0)


def _body_transform(scale, lean_degrees):
    """Body scale (listening level, 1 at rest) with a small lean. Both are about the body's centre."""
    from Quartz import CATransform3DMakeScale, CATransform3DRotate
    s = float(scale)
    return CATransform3DRotate(CATransform3DMakeScale(s, s, 1.0), math.radians(float(lean_degrees)), 0.0, 0.0, 1.0)


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


def _shape_path(points):
    """CGPath from a 13-point eye shape: one move, then four cubic segments, closed."""
    from Quartz import CGPathAddCurveToPoint, CGPathCloseSubpath, CGPathCreateMutable, CGPathMoveToPoint
    path = CGPathCreateMutable()
    CGPathMoveToPoint(path, None, points[0][0], points[0][1])
    for i in range(1, len(points), 3):
        c1, c2, end = points[i], points[i + 1], points[i + 2]
        CGPathAddCurveToPoint(path, None, c1[0], c1[1], c2[0], c2[1], end[0], end[1])
    CGPathCloseSubpath(path)
    return path


def _shape_layer(path, size):
    """A CAShapeLayer mask of the given path, sized to its layer."""
    from Quartz import CAShapeLayer, CGRectMake
    mask = CAShapeLayer.layer()
    mask.setFrame_(CGRectMake(0, 0, size, size))
    mask.setPath_(path)
    return mask


def _track(keypath, pairs, duration, calc="linear"):
    """Keyframe animation from (t, value) pairs. Holds the first value from 0 s and ends exactly at duration."""
    from Quartz import CAKeyframeAnimation
    pairs = list(pairs)
    if pairs[0][0] > 0.0:
        pairs.insert(0, (0.0, pairs[0][1]))
    times = [min(1.0, max(0.0, t / float(duration))) for t, _ in pairs]
    times[0] = 0.0
    times[-1] = 1.0
    anim = CAKeyframeAnimation.animationWithKeyPath_(keypath)
    anim.setValues_([value for _, value in pairs])
    anim.setKeyTimes_(times)
    anim.setDuration_(float(duration))
    anim.setCalculationMode_(calc)
    return anim


def _loop(keypath, pairs, duration):
    """An endless, smooth loop that starts and ends at rest."""
    anim = _track(keypath, pairs, duration, calc="cubic")
    anim.setRepeatCount_(float("inf"))
    return anim


def _spring_animation(constants):
    """CASpringAnimation on the squash transform, from the current value to the model value. Duration is its settling time."""
    from Quartz import CASpringAnimation
    stiffness, damping = constants
    anim = CASpringAnimation.animationWithKeyPath_("transform")
    anim.setStiffness_(float(stiffness))
    anim.setDamping_(float(damping))
    anim.setMass_(1.0)
    anim.setInitialVelocity_(0.0)
    anim.setDuration_(anim.settlingDuration())
    return anim


def _accent_group(animations, duration):
    from Quartz import CAAnimationGroup
    group = CAAnimationGroup.animation()
    group.setAnimations_(animations)
    group.setDuration_(float(duration))
    return group


class OrbLayers:
    """Owns the layer tree under a host layer. Frames come from orb_motion.layer_geometry."""

    def __init__(self, host, rng=None):
        from Quartz import CALayer, CAShapeLayer, CGPointMake, CGRectMake
        geometry = layer_geometry()
        self.rng = rng or random.Random()  # breath speeds; not seeded, so each run varies
        self.scale = 1.0
        self._passives = False
        self._eye_paths = {name: _shape_path(eye_shape(name, EYE_SIZE)) for name in EYE_SHAPES}

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
                                          _BODY_START, _BODY_END, kind="axial")
        self.shade = _gradient_layer(local, _shade_stops(False), (0.5, 0.5), (0.5, 0.0), kind="axial")
        self.rim = _gradient_layer(local, [(RIM_RGB, 0.0, 0.0), (RIM_RGB, RIM_ALPHA, 1.0)],
                                         (0.5, 0.5), (1.0, 1.0))
        self.outline = CAShapeLayer.layer()
        place(self.outline, local)
        self.outline.setFillColor_(None)
        self.outline.setStrokeColor_(_cg_color((1.0, 1.0, 1.0), OUTLINE_ALPHA))
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
        self.eye_masks = {}
        for side in ("L", "R"):
            eye_rect = geometry["eye" + side]
            pupil_rect = geometry["pupil" + side]
            # Restored from 1c63b74: a solid cream bar, so both stops are the same colour.
            eye = _gradient_layer((0, 0, EYE_SIZE, EYE_SIZE),
                                        [(EYE_EDGE_RGB, 1.0, 0.0), (EYE_EDGE_RGB, 1.0, 1.0)],
                                        (0.5, 0.5), (1.0, 1.0))
            # The eye's mask is a path that morphs between eye shapes. It starts as the open eye.
            mask = _shape_layer(self._eye_paths["open"], EYE_SIZE)
            eye.setMask_(mask)
            self.eye_masks[side] = mask
            place(eye, eye_rect)
            pupil = CAShapeLayer.layer()
            pupil.setFrame_(CGRectMake(pupil_rect[0] - eye_rect[0], pupil_rect[1] - eye_rect[1],
                                       pupil_rect[2], pupil_rect[3]))
            pupil.setFillColor_(_cg_color((0.0, 0.0, 0.0)))
            pupil.setPath_(_ellipse_path(0, 0, pupil_rect[2], pupil_rect[3]))
            eye.addSublayer_(pupil)
            self.eyes[side] = eye
            self.pupils[side] = pupil
            pupil.setHidden_(True)  # PR 8: the eyes are plain white pills, with no pupils

        self.mouth = place(CAShapeLayer.layer(), MOUTH_RECT)
        self.mouth.setPath_(_ellipse_path(0, 0, MOUTH_RECT[2], MOUTH_RECT[3]))
        self.mouth.setFillColor_(_cg_color(MOUTH_RGB, 0.9))
        self.mouth.setOpacity_(0.0)

        self.glyph = place(CAShapeLayer.layer(), (0, 0, DESIGN_SIZE, DESIGN_SIZE))
        self.glyph_stroke = place(CAShapeLayer.layer(), (0, 0, DESIGN_SIZE, DESIGN_SIZE))
        self.glyph_stroke.setFillColor_(None)
        self.glyph_stroke.setLineWidth_(1.5)

        # PR 7: a 270 degree arc around the body. It is hidden except in thinking and searching.
        self.spinner = place(CAShapeLayer.layer(), (0, 0, DESIGN_SIZE, DESIGN_SIZE))
        self.spinner.setFillColor_(None)
        self.spinner.setStrokeColor_(_cg_color((1.0, 1.0, 1.0), SPINNER_ALPHA))
        self.spinner.setLineWidth_(SPINNER_LINE_WIDTH)
        self.spinner.setLineCap_("round")
        self.spinner.setPath_(_arc_path(DESIGN_CENTER, DESIGN_CENTER, SPINNER_RADIUS,
                                        math.radians(SPINNER_SWEEP_DEGREES)))
        self.spinner.setHidden_(True)
        self.pupil_bias = (0.0, 0.0)  # PR 7: per-clip or per-state offset, added to the cursor offset
        self.pupil_size = PUPIL_SIZE
        self.pupil_cursor = {"L": (0.0, 0.0), "R": (0.0, 0.0)}
        self.speech_glyph_pivot = False
        self.lean = 0.0  # body lean in degrees, from the current clip

        # Restored from 1c63b74: a flat white oval, not a radial fade.
        hx, hy, hw, hh = geometry["highlight"]
        self.highlight = place(CAShapeLayer.layer(), (hx, hy, hw, hh))
        self.highlight.setFillColor_(_cg_color((1.0, 1.0, 1.0), HIGHLIGHT_ALPHA))
        self.highlight.setPath_(_ellipse_path(0, 0, hw, hh))

        self.body_group = place(CALayer.layer(), (0, 0, DESIGN_SIZE, DESIGN_SIZE))
        # Press squash and drag stretch live on their own layer, so they never fight the bob, breath and accents
        # on the body group. The highlight goes in too, so the shine squashes with the body.
        # PR 8: the press squash and drag stretch act on the body and its shine only. The eyes, mouth and glyphs
        # are siblings of that shell inside the body group, so they never move with the pointer.
        self.squash = place(CALayer.layer(), (0, 0, DESIGN_SIZE, DESIGN_SIZE))
        self.squash.setSublayers_([self.body, self.highlight])
        self.body_group.setSublayers_([self.squash, self.ring, self.eyes["L"], self.eyes["R"],
                                       self.mouth, self.glyph, self.glyph_stroke, self.spinner])
        self.root.setSublayers_([self.shadow, self.body_group])

    def fit(self, width, height):
        """Centre the design space in the view and scale it like the old drawRect_ path."""
        from Quartz import CGAffineTransformMakeScale, CGPointMake
        scale = min(width, height) / DESIGN_EXTENT if min(width, height) > 0 else 1.0
        self.scale = scale
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
        """State cues: ring, mic, ellipsis, speaking mouth glyph and the error "!". The eye pose is apply_pose."""
        fill, fill_rgb, stroke = _glyph_paths(state)

        def update():
            self.root.setHidden_(bool(solid))
            self.glyph.setFillColor_(_cg_color(fill_rgb))
            self.glyph.setPath_(fill)
            self.glyph_stroke.setStrokeColor_(_cg_color(LISTEN_GLYPH_RGB))
            self.glyph_stroke.setPath_(stroke)
            self.ring.setHidden_(state != "listening")
            self.ring.setLineWidth_(ring_width)
        self._disable_actions(update)

    def set_ring_width(self, width):
        self._disable_actions(lambda: self.ring.setLineWidth_(width))

    def apply_pose(self, pose, clip=None, static=False):
        """Static pose from voice_pose, with a clip's overrides. Eye shapes morph and the body eases over POSE_SECONDS.

        static is the Reduce Motion (still) case: the arc is drawn but does not turn. Otherwise this only sets
        values; the spinner and the sweep have their own loops, which applyClip starts.
        """
        shapes = clip.eyes if clip is not None else (pose["eye_shape"], pose["eye_shape"])
        scale_y = clip.scale_y if clip is not None else pose["eye_scale_y"]
        lean = clip.lean if clip is not None else 0.0
        spinning = bool(clip.spinner) if clip is not None else bool(pose["spinner_on"])

        def update():
            for side, shape in (("L", shapes[0]), ("R", shapes[1])):
                self.eye_masks[side].setPath_(self._eye_paths[shape])
                self.eyes[side].setAffineTransform_(_eye_transform(side, scale_y))
            self.lean = lean
            self.body_group.setTransform_(_body_transform(pose["body_scale"], lean))
            self.spinner.setHidden_(not spinning)
            self.set_pupil_look(pose["pupil_bias"] if clip is None else clip.bias, pose["pupil_size"])
        self._timed(POSE_SECONDS, update)
        self._set_spin(spinning and not static)

    def set_tuck_eyes(self, centres, animated, seconds):
        """Move both eyes to centres (design points, body group space). Animated, they slide with the tuck."""
        from Foundation import NSValue
        from Quartz import CABasicAnimation, CAMediaTimingFunction, CGPointMake
        for side in ("L", "R"):
            cx, cy = centres[side]
            layer = self.eyes[side]
            presented = layer.presentationLayer()
            start = (presented or layer).position()
            layer.removeAnimationForKey_("tuck")
            if animated and seconds > 0.0:
                anim = CABasicAnimation.animationWithKeyPath_("position")
                anim.setFromValue_(NSValue.valueWithPoint_(start))
                anim.setToValue_(NSValue.valueWithPoint_(CGPointMake(float(cx), float(cy))))
                anim.setDuration_(float(seconds))
                anim.setTimingFunction_(CAMediaTimingFunction.functionWithName_("easeOut"))
                layer.addAnimation_forKey_(anim, "tuck")
            self._disable_actions(lambda layer=layer, x=cx, y=cy: layer.setPosition_(CGPointMake(float(x), float(y))))

    def set_listen_level(self, scale):
        """The listening body follows the mic level with a short ease, and keeps the clip's lean."""
        self._timed(LEVEL_SECONDS, lambda: self.body_group.setTransform_(_body_transform(scale, self.lean)))

    def set_pupil_look(self, bias, size):
        """Bias and size for the pupils. The cursor offset is added on top of the bias, in set_pupils."""
        self.pupil_bias = (float(bias[0]), float(bias[1]))
        self.pupil_size = float(size)
        self._write_pupils()

    def _write_pupils(self):
        from Quartz import CAMediaTimingFunction, CATransaction, CGAffineTransformMake
        scale = self.pupil_size / PUPIL_SIZE
        CATransaction.begin()
        CATransaction.setAnimationDuration_(0.08)
        CATransaction.setAnimationTimingFunction_(CAMediaTimingFunction.functionWithName_("linear"))
        try:
            for side in ("L", "R"):
                cx, cy = self.pupil_cursor[side]
                # Scale about the pupil's centre, then move by the cursor offset plus the bias.
                transform = CGAffineTransformMake(scale, 0.0, 0.0, scale,
                                                  cx + self.pupil_bias[0], cy + self.pupil_bias[1])
                self.pupils[side].setAffineTransform_(transform)
        finally:
            CATransaction.commit()

    def _timed(self, seconds, work):
        """Run work with implicit animations on, for the given time, so poses ease instead of snapping."""
        from Quartz import CAMediaTimingFunction, CATransaction
        CATransaction.begin()
        CATransaction.setAnimationDuration_(float(seconds))
        CATransaction.setAnimationTimingFunction_(CAMediaTimingFunction.functionWithName_("easeInEaseOut"))
        try:
            work()
        finally:
            CATransaction.commit()

    def _set_spin(self, on):
        """The thinking and searching spinner: one endless 1.2 s linear turn, added once and removed when it stops."""
        from Quartz import CABasicAnimation, CAMediaTimingFunction
        if on:
            if self.spinner.animationForKey_(SPIN_KEY) is not None:  # already turning
                return
            anim = CABasicAnimation.animationWithKeyPath_("transform.rotation.z")
            anim.setFromValue_(0.0)
            anim.setToValue_(math.tau)
            anim.setDuration_(SPINNER_SECONDS)
            anim.setTimingFunction_(CAMediaTimingFunction.functionWithName_("linear"))
            anim.setRepeatCount_(float("inf"))
            self.spinner.addAnimation_forKey_(anim, SPIN_KEY)
        else:
            self.spinner.removeAnimationForKey_(SPIN_KEY)

    def set_sweep(self, amplitude):
        """Searching: the eyes slide left and right over 1.6 s. Additive, so the pose still applies."""
        for side in ("L", "R"):
            layer = self.eyes[side]
            layer.removeAnimationForKey_(SWEEP_KEY)
            if amplitude <= 0.0:
                continue
            samples = sine_samples(SEARCH_SWEEP_SECONDS, float(amplitude), 24)
            anim = _track("position.x", samples, SEARCH_SWEEP_SECONDS, calc="cubic")
            anim.setAdditive_(True)
            anim.setRepeatCount_(float("inf"))
            layer.addAnimation_forKey_(anim, SWEEP_KEY)

    def start_speech(self, levels):
        """Speaking: the mouth glyph follows the reply's loudness, and the eyes squint on the peaks.

        levels is wav_envelope(), 30 values a second, built once per reply. An empty list gives the 3.5 Hz pulse.
        """
        self.stop_speech()
        if levels:
            pairs = [(i / float(ENVELOPE_HZ), mouth_height(v) / MOUTH_GLYPH_HEIGHT) for i, v in enumerate(levels)]
            duration = len(levels) / float(ENVELOPE_HZ)
            self.glyph.addAnimation_forKey_(_track("transform.scale.y", pairs, duration), SPEECH_KEY)
            squint = [(i / float(ENVELOPE_HZ), squint_scale(v)) for i, v in enumerate(levels)]
            for side in ("L", "R"):
                self.eyes[side].addAnimation_forKey_(_track("transform.scale.y", squint, duration), SPEECH_KEY)
        else:
            period = 1.0 / MOUTH_PULSE_HZ
            pairs = [(period * i / 10.0, pulse_mouth(period * i / 10.0) / MOUTH_GLYPH_HEIGHT) for i in range(11)]
            self.glyph.addAnimation_forKey_(_loop("transform.scale.y", pairs, period), SPEECH_KEY)
        self._set_glyph_pivot(True)

    def stop_speech(self):
        """Remove the speech loops and put the glyph's pivot back to the centre."""
        self.glyph.removeAnimationForKey_(SPEECH_KEY)
        for eye in self.eyes.values():
            eye.removeAnimationForKey_(SPEECH_KEY)
        self._set_glyph_pivot(False)

    def _set_glyph_pivot(self, speech):
        """The speaking glyph scales about its own centre, so it grows up and down, not from the body's middle."""
        from Quartz import CGPointMake
        if speech == self.speech_glyph_pivot:
            return
        self.speech_glyph_pivot = speech
        if speech:
            anchor, position = (0.5, SPEECH_GLYPH_ANCHOR_Y / DESIGN_SIZE), (DESIGN_CENTER, SPEECH_GLYPH_ANCHOR_Y)
        else:
            anchor, position = (0.5, 0.5), (DESIGN_CENTER, DESIGN_CENTER)
        self._disable_actions(lambda: (
            self.glyph.setAnchorPoint_(CGPointMake(*anchor)),
            self.glyph.setPosition_(CGPointMake(*position)),
        ))

    def set_passives(self, on):
        """Bob, float, breath and shadow pulse. They run in the render server, so Python does no per-frame work."""
        on = bool(on)
        if on == self._passives:
            return
        self._passives = on
        if on:
            self._add_passives()
        else:
            self._remove_passives()

    def _add_passives(self):
        body = self.body_group
        bob = sine_samples(BOB_PERIOD, BOB_AMPLITUDE)
        body.addAnimation_forKey_(_loop("position.y", [(t, DESIGN_CENTER + off) for t, off in bob], BOB_PERIOD),
                                  "bob")
        drift = sine_samples(FLOAT_SECONDS, FLOAT_AMPLITUDE, 48)
        body.addAnimation_forKey_(_loop("position.x", [(t, DESIGN_CENTER + off) for t, off in drift],
                                        FLOAT_SECONDS), "float")
        # One batch of breath cycles with random speeds. The batch is picked again each time passives start.
        breath = breath_batch(self.rng)
        total = breath[-1][0]
        body.addAnimation_forKey_(_loop("transform.scale.x", [(t, sx) for t, sx, _ in breath], total), "breathX")
        body.addAnimation_forKey_(_loop("transform.scale.y", [(t, sy) for t, _, sy in breath], total), "breathY")
        # The shadow follows the bob, so it is smallest and faintest at the top of the bob.
        shadow = self.shadow
        shadow.addAnimation_forKey_(_loop("transform.scale", [(t, shadow_for_bob(off)[0]) for t, off in bob],
                                          BOB_PERIOD), "shadowScale")
        shadow.addAnimation_forKey_(_loop("opacity", [(t, shadow_for_bob(off)[1]) for t, off in bob],
                                          BOB_PERIOD), "shadowOpacity")

    def _remove_passives(self):
        for key in ("bob", "float", "breathX", "breathY"):
            self.body_group.removeAnimationForKey_(key)
        for key in ("shadowScale", "shadowOpacity"):
            self.shadow.removeAnimationForKey_(key)

    def play_accent(self, name):
        """Start one idle accent and return its length in seconds. One group per layer, keyed 'accent'."""
        timeline = accent_timeline(name)
        duration = accent_seconds(name)
        targets = {}  # target name -> (layer, [animations])

        def add(target, layer, animation):
            targets.setdefault(target, (layer, []))[1].append(animation)

        for side in ("L", "R"):
            track = timeline.get("eyes_" + side)
            if track:
                add("mask" + side, self.eye_masks[side],
                    _track("path", [(t, self._eye_paths[shape]) for t, shape in track], duration))
        if "pupil_x" in timeline:
            for side in ("L", "R"):
                add("pupil" + side, self.pupils[side],
                    _track("transform.translation.x", timeline["pupil_x"], duration))
        if "body_y" in timeline:
            add("body", self.body_group, _track("transform.translation.y", timeline["body_y"], duration))
        if "body_sy" in timeline:
            add("body", self.body_group, _track("transform.scale.y", timeline["body_sy"], duration))
        if "body_scale" in timeline:
            add("body", self.body_group, _track("transform.scale", timeline["body_scale"], duration))
        if "mouth" in timeline:
            add("mouth", self.mouth, _track("transform.scale.y", timeline["mouth"], duration))
            add("mouth", self.mouth, _track("opacity", timeline["mouth"], duration))
        for layer, animations in targets.values():
            layer.removeAnimationForKey_("accent")
            layer.addAnimation_forKey_(_accent_group(animations, duration), "accent")
        return duration

    def press_squash(self):
        """Mouse down on the orb: the body and eyes squash to PRESS_SCALE over PRESS_SECONDS, easeOut."""
        from Quartz import CABasicAnimation, CAMediaTimingFunction, CATransform3DMakeScale
        anim = CABasicAnimation.animationWithKeyPath_("transform")
        anim.setDuration_(PRESS_SECONDS)
        anim.setTimingFunction_(CAMediaTimingFunction.functionWithName_("easeOut"))
        return self._squash_to(CATransform3DMakeScale(PRESS_SCALE[0], PRESS_SCALE[1], 1.0), anim)

    def release_spring(self):
        """A click lets go: the squash springs back to round. Returns the spring's settling time in seconds."""
        from Quartz import CATransform3DIdentity
        return self._squash_to(CATransform3DIdentity, _spring_animation(SPRING_RELEASE))

    def drop_jiggle(self):
        """A drag ends: the stretch springs back to round with two wobbles. Returns the settling time in seconds."""
        from Quartz import CATransform3DIdentity
        return self._squash_to(CATransform3DIdentity, _spring_animation(SPRING_DROP_JIGGLE))

    def set_stretch(self, sx, sy, angle):
        """Drag stretch: R(angle)·S·R(-angle). Set every frame with no implicit animation, so the drag stays exact."""
        from Quartz import CATransform3DMakeAffineTransform, CGAffineTransformMake
        a, b, c, d = stretch_matrix(sx, sy, angle)
        transform = CATransform3DMakeAffineTransform(CGAffineTransformMake(a, b, c, d, 0.0, 0.0))
        self.squash.removeAnimationForKey_(SQUASH_KEY)  # an unfinished press must not hold the layer
        self._disable_actions(lambda: self.squash.setTransform_(transform))

    def _squash_to(self, target, animation):
        """Make target the resting value, then animate from wherever the layer is now.

        Core Animation takes the start from the presentation value when the animation is added, and the
        end from the model value set here. One key, so a new squash replaces the one in flight.
        """
        self._disable_actions(lambda: self.squash.setTransform_(target))
        self.squash.addAnimation_forKey_(animation, SQUASH_KEY)
        return float(animation.duration())

    def set_pupils(self, offsets):
        """offsets: {"L": (dx, dy), "R": (dx, dy)} in design points, the cursor part. Eases over 0.08 s, linear."""
        self.pupil_cursor = {side: (float(dx), float(dy)) for side, (dx, dy) in offsets.items()}
        self._write_pupils()

    def reset_motion(self):
        """Stop the idle motion and centre the cursor offset. Keeps the state's pupil bias, and the clip loops.

        Used when motion stops or the orb is docked. The spinner, sweep and speech belong to the character state,
        so they keep running while the orb is docked.
        """
        from Quartz import CATransform3DIdentity
        self.set_passives(False)
        for layer in [self.body_group, self.mouth] + list(self.eye_masks.values()) + list(self.pupils.values()):
            layer.removeAnimationForKey_("accent")
        self.squash.removeAnimationForKey_(SQUASH_KEY)
        self.pupil_cursor = {"L": (0.0, 0.0), "R": (0.0, 0.0)}
        self._disable_actions(lambda: self.squash.setTransform_(CATransform3DIdentity))
        self._write_pupils()

    @staticmethod
    def _disable_actions(work):
        from Quartz import CATransaction
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        try:
            work()
        finally:
            CATransaction.commit()


# PR 6a: the expand and collapse ghost. A snapshot of the full window, grown from the orb's centre (or shrunk back).

def _spring_on(keypath, constants):
    from Quartz import CASpringAnimation
    stiffness, damping = constants
    anim = CASpringAnimation.animationWithKeyPath_(keypath)
    anim.setStiffness_(float(stiffness))
    anim.setDamping_(float(damping))
    anim.setMass_(1.0)
    anim.setInitialVelocity_(0.0)
    anim.setDuration_(anim.settlingDuration())
    return anim


def ghost_layer(image, size, backing_scale):
    """A layer holding the snapshot, sized to the window, anchored at its centre so scale and position line up."""
    from Quartz import CALayer, CGPointMake, CGRectMake
    layer = CALayer.layer()
    layer.setContents_(image)
    layer.setContentsScale_(float(backing_scale))
    layer.setBounds_(CGRectMake(0, 0, float(size[0]), float(size[1])))
    layer.setAnchorPoint_(CGPointMake(0.5, 0.5))
    layer.setPosition_(CGPointMake(float(size[0]) / 2.0, float(size[1]) / 2.0))
    return layer


def animate_ghost(layer, size, start_center, end_center, start_scale, end_scale, fade_from, fade_to,
                  reduce_motion=False, spring=None):
    """Play one ghost move, and return how long it takes to land.

    Motion: transform.scale and position share the same spring (SPRING_EXPAND by default), so the
    centre travels along the line that the scale implies. Opacity uses a 0.18 s easeOut.
    Reduce Motion: no scale or position change, only a 0.15 s crossfade.
    Model values are set to the end state, so the layer rests there when the animations are removed.
    """
    from Foundation import NSValue
    from Quartz import CABasicAnimation, CAMediaTimingFunction, CATransform3DIdentity, CATransform3DMakeScale
    from Quartz import CGPointMake
    from orb_motion import EXPAND_FADE_SECONDS, REDUCE_CROSSFADE_SECONDS, SPRING_EXPAND
    spring = spring or SPRING_EXPAND
    fade = CABasicAnimation.animationWithKeyPath_("opacity")
    fade.setFromValue_(float(fade_from))
    fade.setToValue_(float(fade_to))
    fade.setTimingFunction_(CAMediaTimingFunction.functionWithName_("easeOut"))
    layer.setOpacity_(float(fade_to))
    if reduce_motion:
        fade.setDuration_(REDUCE_CROSSFADE_SECONDS)
        layer.addAnimation_forKey_(fade, "ghostFade")
        return REDUCE_CROSSFADE_SECONDS
    fade.setDuration_(EXPAND_FADE_SECONDS)
    scale = _spring_on("transform.scale", spring)
    scale.setFromValue_(float(start_scale))
    scale.setToValue_(float(end_scale))
    move = _spring_on("position", spring)
    move.setFromValue_(NSValue.valueWithPoint_(CGPointMake(float(start_center[0]), float(start_center[1]))))
    move.setToValue_(NSValue.valueWithPoint_(CGPointMake(float(end_center[0]), float(end_center[1]))))
    layer.setPosition_(CGPointMake(float(end_center[0]), float(end_center[1])))
    layer.setTransform_(CATransform3DIdentity if float(end_scale) == 1.0
                        else CATransform3DMakeScale(float(end_scale), float(end_scale), 1.0))
    layer.addAnimation_forKey_(scale, "ghostScale")
    layer.addAnimation_forKey_(move, "ghostMove")
    layer.addAnimation_forKey_(fade, "ghostFade")
    return max(float(scale.duration()), EXPAND_FADE_SECONDS)
