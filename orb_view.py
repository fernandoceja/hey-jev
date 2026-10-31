"""Original Jev vector orb. Pure presentation rules are usable without AppKit."""
import math
import time

from orb_motion import BODY_SIZE as ORB_SIZE
from orb_motion import DESIGN_EXTENT as ORB_DESIGN_EXTENT
from orb_motion import DESIGN_SIZE as PANEL_SIZE


def orb_frame(expanded):
    """Keep the existing right-edge/vertical-center anchor; no placement policy."""
    x, y, w, h = expanded
    return (x + w - PANEL_SIZE, y + (h - PANEL_SIZE) / 2, PANEL_SIZE, PANEL_SIZE)


def orb_state(status, held=False):
    if held or status in ("Listening", "Dictating"):
        return "listening"
    if status in ("Transcribing", "Thinking", "Doing it", "Finishing"):
        return "thinking"
    if status == "Speaking":
        return "speaking"
    if status in ("Something went wrong", "Time's up"):
        return "error"
    return "idle"


def orb_pose(state, seconds, level=0.0, reduce_motion=False):
    """Motion never carries the only state cue. Audio uses the existing meter."""
    level = min(1.0, max(0.0, float(level))) if math.isfinite(float(level)) else 0.0
    if reduce_motion:
        return (0.0, 1.0, 0.0, 2.0)
    bob = 1.5 * math.sin(seconds * math.tau / 4) if state == "idle" else 0.0
    blink = 0.15 if state == "idle" and seconds % 7.0 > 6.85 else 1.0
    sweep = math.sin(seconds * math.tau / 3) * 8 if state == "thinking" else 0.0
    return (bob, blink, sweep, 2.0 + 2.0 * level if state == "listening" else 2.0)


class OrbTicker:
    """One decorative timer, invalidated on hide, expand, reduced motion or quit."""
    def __init__(self):
        self.timer = None

    def sync(self, active, schedule):
        if active and self.timer is None:
            self.timer = schedule()
        elif not active and self.timer is not None:
            self.timer.invalidate()
            self.timer = None


_ORB_CLASS = None


def make_orb_view(frame):
    """Load Cocoa only for the actual Mac UI, keeping rule tests hardware-free."""
    global _ORB_CLASS
    if _ORB_CLASS is None:
        import objc
        from AppKit import (NSView, NSColor, NSBezierPath, NSMakeRect, NSMakePoint, NSAffineTransform,
                            NSViewLayerContentsRedrawNever, NSViewLayerContentsRedrawOnSetNeedsDisplay)
        from Foundation import NSTimer
        import orb_layers

        class JevOrbView(NSView):
            def initWithFrame_(self, rect):
                self = objc.super(JevOrbView, self).initWithFrame_(rect)
                if self is not None:
                    self.ticker = OrbTicker()
                    self.state = "idle"
                    self.level = 0.0
                    self.reduceMotion = False
                    self.solid = False
                    self.started = time.monotonic()
                    # Layer-backed: Core Animation draws the orb, so drawRect_ runs only for the solid case.
                    self.setWantsLayer_(True)
                    self.setLayerContentsRedrawPolicy_(NSViewLayerContentsRedrawNever)
                    self.tree = orb_layers.OrbLayers(self.layer())
                    self.setAccessibilityElement_(True)
                    self.setAccessibilityRole_("AXButton")
                    self.setAccessibilityLabel_("Jev — Ready. Click to type; hold right Option to speak.")
                return self

            def hitTest_(self, _point):
                return None  # Existing background owns click versus drag.

            def accessibilityPerformPress(self):
                window = self.window()
                if window is None:
                    return False
                window.delegate().expandMiniBar_(self)
                return True

            def setFrameSize_(self, size):
                objc.super(JevOrbView, self).setFrameSize_(size)
                self.fitLayers()

            def viewDidMoveToWindow(self):
                self.refreshLook()

            def viewDidChangeBackingProperties(self):
                self.refreshLook()

            def viewDidChangeEffectiveAppearance(self):
                self.refreshLook()

            @objc.python_method
            def fitLayers(self):
                tree = getattr(self, "tree", None)
                if tree is not None:
                    bounds = self.bounds()
                    tree.fit(float(bounds.size.width), float(bounds.size.height))

            @objc.python_method
            def refreshLook(self):
                tree = getattr(self, "tree", None)
                if tree is None:
                    return
                window = self.window()
                scale = float(window.backingScaleFactor()) if window is not None else 1.0
                tree.rescale(scale, orb_layers.is_dark(self.effectiveAppearance()))
                self.fitLayers()

            @objc.python_method
            def configure(self, status, held, level, visible, motion, solid):
                self.state = orb_state(status, held)
                self.level = level
                self.reduceMotion = not motion
                self.solid = solid
                label = "Listening" if held else status or "Ready"
                self.setAccessibilityLabel_("Jev — " + label + ". Click to type; hold right Option to speak.")
                self.setToolTip_("Jev — " + label)
                self.setHidden_(not visible)
                self.setLayerContentsRedrawPolicy_(
                    NSViewLayerContentsRedrawOnSetNeedsDisplay if solid else NSViewLayerContentsRedrawNever)
                if not solid:
                    self.layer().setContents_(None)  # Clear any solid frame from a previous draw.
                self.tree.apply(self.state, solid, orb_pose(self.state, 0, self.level, self.reduceMotion)[3])
                # The solid path keeps its old 30 fps pose. The layer path only refreshes the listening ring.
                self.ticker.sync(visible and motion and (solid or self.state == "listening"),
                                 lambda: NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                                     1 / 30, self, "animateOrb:", None, True))
                self.setNeedsDisplay_(True)

            @objc.python_method
            def stop(self):
                self.ticker.sync(False, None)

            def viewWillMoveToWindow_(self, window):
                if window is None:
                    self.stop()

            def animateOrb_(self, _timer):
                if self.solid:
                    self.setNeedsDisplay_(True)
                else:
                    self.tree.set_ring_width(orb_pose(self.state, 0, self.level, self.reduceMotion)[3])

            def drawRect_(self, _rect):
                if not self.solid:
                    return  # Layers draw everything else.
                bob, blink, sweep, ring_width = orb_pose(
                    self.state, time.monotonic() - self.started, self.level, self.reduceMotion)
                def color(r, g, b, a=1):
                    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)
                def oval(x, y, w, h):
                    return NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(x, y, w, h))
                # Vectors only, drawn in a 72pt design space scaled to the
                # view, so AppKit renders them at the backing scale (Retina
                # crisp). The window draws the drop shadow; no fake ovals.
                bounds = self.bounds()
                bw, bh = float(bounds.size.width), float(bounds.size.height)
                scale = min(bw, bh) / ORB_DESIGN_EXTENT
                xf = NSAffineTransform.transform()
                xf.translateXBy_yBy_(bw / 2.0, bh / 2.0)
                xf.scaleBy_(scale)
                xf.translateXBy_yBy_(-36.0, -36.0)
                xf.concat()
                body = oval(8, 8 + bob, ORB_SIZE, ORB_SIZE)
                color(0.12, 0.27, 0.65).setFill()
                body.fill()
                if self.state == "listening":
                    color(0.18, 0.65, 1).setStroke()
                    ring = oval(5, 5 + bob, 62, 62)
                    ring.setLineWidth_(ring_width)
                    ring.stroke()
                color(1, 0.98, 0.88).setFill()
                for x in (26, 40):
                    eye_h = (5 if self.state == "thinking" else 10) * blink
                    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                        NSMakeRect(x, 35 + bob - eye_h / 2, 4, eye_h), 2, 2).fill()
                # A mic, ellipsis, mouth or exclamation gives each state a shape cue.
                if self.state == "listening":
                    color(0.55, 0.86, 1).setFill()
                    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(33, 19 + bob, 6, 10), 3, 3).fill()
                    color(0.55, 0.86, 1).setStroke()
                    arc = NSBezierPath.bezierPath()
                    arc.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(NSMakePoint(36, 23 + bob), 5, 180, 0, False)
                    arc.moveToPoint_(NSMakePoint(36, 18 + bob))
                    arc.lineToPoint_(NSMakePoint(36, 15 + bob))
                    arc.setLineWidth_(1.5)
                    arc.stroke()
                elif self.state == "thinking":
                    for x in (29, 35, 41):
                        oval(x, 21 + bob, 2, 2).fill()
                elif self.state == "speaking":
                    oval(32, 18 + bob, 8, 5).fill()
                elif self.state == "error":
                    NSBezierPath.bezierPathWithRect_(NSMakeRect(35, 21, 2, 7)).fill()
                    oval(35, 17, 2, 2).fill()

        _ORB_CLASS = JevOrbView
    return _ORB_CLASS.alloc().initWithFrame_(frame)
