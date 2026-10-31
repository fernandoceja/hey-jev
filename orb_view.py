"""Original Jev vector orb. Pure presentation rules are usable without AppKit."""
import math
import random
import time

from orb_character import look_intensity, next_accent_delay, pick_accent
from orb_motion import BODY_SIZE as ORB_SIZE
from orb_motion import CURSOR_POLL_SECONDS, DESIGN_CENTER, EYE_CENTER_Y, EYE_SPACING
from orb_motion import DESIGN_EXTENT as ORB_DESIGN_EXTENT
from orb_motion import DESIGN_SIZE as PANEL_SIZE
from orb_motion import cursor_moved, idle_active, pupil_offset


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
    """Pose for the solid path and the listening ring. Motion never carries the only state cue.

    Bob and breath run in the render server (orb_layers), and blinks are random accents (orb_character),
    so this pose only needs the static values and the listening ring width.
    """
    level = min(1.0, max(0.0, float(level))) if math.isfinite(float(level)) else 0.0
    if reduce_motion:
        return (0.0, 1.0, 0.0, 2.0)
    sweep = math.sin(seconds * math.tau / 3) * 8 if state == "thinking" else 0.0
    return (0.0, 1.0, sweep, 2.0 + 2.0 * level if state == "listening" else 2.0)


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

    def fired(self):
        """A single-shot timer ran. Forget it without invalidating, so the next sync schedules a new one."""
        self.timer = None


_ORB_CLASS = None


def make_orb_view(frame):
    """Load Cocoa only for the actual Mac UI, keeping rule tests hardware-free."""
    global _ORB_CLASS
    if _ORB_CLASS is None:
        import objc
        from AppKit import (NSView, NSColor, NSBezierPath, NSMakeRect, NSMakePoint, NSAffineTransform, NSEvent,
                            NSWorkspace, NSViewLayerContentsRedrawNever, NSViewLayerContentsRedrawOnSetNeedsDisplay)
        from Foundation import NSTimer
        import orb_layers

        class JevOrbView(NSView):
            def initWithFrame_(self, rect):
                self = objc.super(JevOrbView, self).initWithFrame_(rect)
                if self is not None:
                    self.ticker = OrbTicker()  # 20 Hz pupil poll
                    self.accentTicker = OrbTicker()  # one single-shot idle accent at a time
                    self.state = "idle"
                    self.level = 0.0
                    self.reduceMotion = False
                    self.solid = False
                    self.cfg = (False, True, False, False)  # visible, motion, docked, popover
                    self.halted = False  # stop() sets this; a later configure with visible clears it
                    self.alive = False  # timers and passives are running
                    self.asleep = False
                    self.lastCursor = None
                    self.clipName = None
                    self.clipEnd = 0.0
                    self.previousAccent = None
                    self.rng = random.Random()
                    # Layer-backed: Core Animation draws the orb, so drawRect_ runs only for the solid case.
                    self.setWantsLayer_(True)
                    self.setLayerContentsRedrawPolicy_(NSViewLayerContentsRedrawNever)
                    self.tree = orb_layers.OrbLayers(self.layer(), self.rng)
                    self.setAccessibilityElement_(True)
                    self.setAccessibilityRole_("AXButton")
                    self.setAccessibilityLabel_("Jev — Ready. Click to type; hold right Option to speak.")
                    center = NSWorkspace.sharedWorkspace().notificationCenter()
                    center.addObserver_selector_name_object_(
                        self, "screensDidSleep:", "NSWorkspaceScreensDidSleepNotification", None)
                    center.addObserver_selector_name_object_(
                        self, "screensDidWake:", "NSWorkspaceScreensDidWakeNotification", None)
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

            def viewWillMoveToWindow_(self, window):
                if window is None:
                    self.stop()

            def screensDidSleep_(self, _notification):
                self.asleep = True
                self.syncMotion()

            def screensDidWake_(self, _notification):
                self.asleep = False
                self.syncMotion()

            def trackCursor_(self, _timer):
                self.followCursor()

            def playAccent_(self, _timer):
                self.accentTicker.fired()
                if not self.alive or self.state != "idle" or self.cfg[3]:
                    return
                name = pick_accent(self.rng, self.previousAccent)
                self.previousAccent = name
                seconds = self.tree.play_accent(name)
                self.clipName = name
                self.clipEnd = time.monotonic() + seconds
                self.accentTicker.sync(True, self.scheduleAccent)

            @objc.python_method
            def scheduleAccent(self):
                return NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    next_accent_delay(self.rng), self, "playAccent:", None, False)

            @objc.python_method
            def scheduleCursor(self):
                return NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    CURSOR_POLL_SECONDS, self, "trackCursor:", None, True)

            @objc.python_method
            def fitLayers(self):
                tree = getattr(self, "tree", None)
                if tree is not None:
                    bounds = self.bounds()
                    tree.fit(float(bounds.size.width), float(bounds.size.height))
                self.lastCursor = None  # the eyes may have moved, so the next poll must recompute

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
            def configure(self, status, held, level, visible, motion, solid, docked=False, popover=False):
                self.state = orb_state(status, held)
                self.level = level
                self.reduceMotion = not motion
                self.solid = solid
                self.cfg = (bool(visible), bool(motion), bool(docked), bool(popover))
                if visible:
                    self.halted = False
                label = "Listening" if held else status or "Ready"
                self.setAccessibilityLabel_("Jev — " + label + ". Click to type; hold right Option to speak.")
                self.setToolTip_("Jev — " + label)
                self.setHidden_(not visible)
                self.setLayerContentsRedrawPolicy_(
                    NSViewLayerContentsRedrawOnSetNeedsDisplay if solid else NSViewLayerContentsRedrawNever)
                if not solid:
                    self.layer().setContents_(None)  # Clear any solid frame from a previous draw.
                self.tree.apply(self.state, solid, orb_pose(self.state, 0, self.level, self.reduceMotion)[3])
                self.fitLayers()
                self.syncMotion()
                if solid:
                    self.setNeedsDisplay_(True)

            @objc.python_method
            def syncMotion(self):
                """Start or stop everything that moves, from the last configure and the sleep state."""
                visible, motion, docked, popover = self.cfg
                alive = not self.halted and idle_active(visible, motion, docked, self.asleep)
                if self.alive and not alive:
                    self.tree.reset_motion()
                self.alive = alive
                idle = alive and self.state == "idle"
                self.tree.set_passives(idle and not self.solid)
                self.ticker.sync(alive and not self.solid, self.scheduleCursor)
                self.accentTicker.sync(idle and not popover and not self.solid, self.scheduleAccent)

            @objc.python_method
            def followCursor(self):
                """Pupils follow the mouse anywhere on any display. Exits early when the cursor hasn't moved."""
                if self.window() is None or not self.alive or self.solid:
                    return
                mouse = NSEvent.mouseLocation()
                cursor = (float(mouse.x), float(mouse.y))
                if not cursor_moved(self.lastCursor, cursor):
                    return
                self.lastCursor = cursor
                intensity = look_intensity(self.state, self.currentClip())
                scale = self.tree.scale or 1.0
                offsets = {}
                for side, sign in (("L", -1.0), ("R", 1.0)):
                    dx, dy = pupil_offset(self.eyeOnScreen(sign), cursor)
                    offsets[side] = (dx * intensity / scale, dy * intensity / scale)
                self.tree.set_pupils(offsets)

            @objc.python_method
            def eyeOnScreen(self, sign):
                """Screen position of one eye centre. sign is -1 for the left eye and 1 for the right."""
                bounds = self.bounds()
                scale = self.tree.scale or 1.0
                view_x = float(bounds.size.width) / 2.0 + sign * EYE_SPACING * scale
                view_y = float(bounds.size.height) / 2.0 + (EYE_CENTER_Y - DESIGN_CENTER) * scale
                in_window = self.convertPoint_toView_(NSMakePoint(view_x, view_y), None)
                on_screen = self.window().convertRectToScreen_(NSMakeRect(in_window.x, in_window.y, 0, 0))
                return (on_screen.origin.x, on_screen.origin.y)

            @objc.python_method
            def currentClip(self):
                if self.clipName is not None and time.monotonic() < self.clipEnd:
                    return self.clipName
                return None

            @objc.python_method
            def followLevel(self):
                """The listening ring width follows the mic level. The old 30 fps loop did this."""
                if self.solid or not self.alive or self.state != "listening":
                    return
                self.tree.set_ring_width(orb_pose(self.state, 0, self.level, self.reduceMotion)[3])

            @objc.python_method
            def pressSquash(self):
                """Mouse down on the orb. Skipped with Reduce Motion or the solid fill, where the layers are hidden."""
                if self.solid or self.reduceMotion:
                    return 0.0
                return self.tree.press_squash()

            @objc.python_method
            def releaseSquash(self):
                """A click lets go without moving. Returns the spring's settling time, or 0 when it did nothing."""
                if self.solid or self.reduceMotion:
                    return 0.0
                return self.tree.release_spring()

            @objc.python_method
            def dragStretch(self, sx, sy, angle):
                """Stretch the orb along its direction of travel while dragging."""
                if self.solid or self.reduceMotion:
                    return
                self.tree.set_stretch(sx, sy, angle)

            @objc.python_method
            def dropJiggle(self):
                """A drag ends. Returns the jiggle's settling time, or 0 when it did nothing."""
                if self.solid or self.reduceMotion:
                    return 0.0
                return self.tree.drop_jiggle()

            @objc.python_method
            def renderLayers(self):
                """(tree_attached, {name: (opacity, width, height)}) for orb_health.render_problems."""
                tree = getattr(self, "tree", None)
                host = self.layer()
                if tree is None:
                    return False, {}
                attached = host is not None and tree.root.superlayer() is host
                layers = {}
                for name in ("root", "squash", "body_group", "body"):
                    layer = getattr(tree, name, None)
                    if layer is None:
                        continue
                    size = layer.bounds().size
                    layers[name] = (float(layer.opacity()), float(size.width), float(size.height))
                return attached, layers

            @objc.python_method
            def healRender(self):
                """Re-attach the layer tree if AppKit replaced the backing layer, restore opacity, and refit.

                Transforms and animations are left alone, so the squash, stretch, jiggle and spring are untouched.
                """
                tree = getattr(self, "tree", None)
                if tree is None:
                    return
                self.setHidden_(False)
                if self.layer() is None:
                    self.setWantsLayer_(True)
                host = self.layer()
                if host is not None and tree.root.superlayer() is not host:
                    tree.root.removeFromSuperlayer()
                    host.addSublayer_(tree.root)
                for name in ("root", "squash", "body_group", "body"):
                    layer = getattr(tree, name, None)
                    if layer is not None and float(layer.opacity()) < 0.99:
                        layer.setOpacity_(1.0)
                self.refreshLook()

            @objc.python_method
            def stop(self):
                self.halted = True
                self.syncMotion()

            def drawRect_(self, _rect):
                if not self.solid:
                    return  # Layers draw everything else.
                bob, blink, sweep, ring_width = orb_pose(self.state, 0.0, self.level, self.reduceMotion)
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
