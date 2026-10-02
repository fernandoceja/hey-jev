"""Little floating pill at the bottom middle of the screen with a live waveform while dictating."""
import math
import sys

import objc

from AppKit import (
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSMakePoint,
    NSMakeRect,
    NSPanel,
    NSScreen,
    NSView,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSTimer

WIDTH, HEIGHT, BARS = 132, 36, 20
STATUS_LEVEL = 25  # NSStatusWindowLevel, above normal and floating windows
ALL_SPACES = 1 | 16 | 256  # canJoinAllSpaces, stationary, fullScreenAuxiliary


class WaveView(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(WaveView, self).initWithFrame_(frame)
        self.working, self.phase = False, 0.0
        return self

    def drawRect_(self, _rect):
        try:  # any Python error inside drawing would crash the whole app
            self._draw()
        except Exception as exc:
            print(f"  bubble draw failed: {exc}")

    @objc.python_method
    def _draw(self):
        bounds = self.bounds()
        NSColor.colorWithWhite_alpha_(0.08, 0.9).setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bounds, HEIGHT / 2, HEIGHT / 2).fill()
        siri = sys.modules.get("siri")
        levels = list(getattr(siri, "MIC_LEVELS", ()))[-BARS:]  # siri may still be loading, and an error here kills the app
        levels = [0.0] * (BARS - len(levels)) + levels
        gap, bar_w = 3.0, 3.0
        left = (bounds.size.width - BARS * (bar_w + gap) + gap) / 2
        max_h = bounds.size.height - 14
        (NSColor.systemBlueColor() if self.working else NSColor.whiteColor()).setFill()
        for i, rms in enumerate(levels):
            if self.working:  # gentle travelling pulse while OpenRouter writes it up
                h = 0.25 + 0.2 * (1 + math.sin(self.phase - i * 0.5))
            else:
                h = min(1.0, math.sqrt(rms / 0.08))
            h = max(3.0, h * max_h)
            x = left + i * (bar_w + gap)
            y = (bounds.size.height - h) / 2
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(x, y, bar_w, h), 1.5, 1.5).fill()

    def tick_(self, _timer):
        self.phase += 0.35
        self.setNeedsDisplay_(True)


class Bubble:
    def __init__(self):
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIDTH, HEIGHT), NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered, False
        )
        self.panel.setLevel_(STATUS_LEVEL)
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setHasShadow_(True)
        self.panel.setIgnoresMouseEvents_(True)  # clicks go straight through, it never takes focus
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setCollectionBehavior_(ALL_SPACES)
        self.wave = WaveView.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, HEIGHT))
        self.panel.setContentView_(self.wave)
        self.timer = None

    def show(self, working=False):
        self.wave.working = working
        if not self.panel.isVisible():
            screen = NSScreen.mainScreen().visibleFrame()
            self.panel.setFrameOrigin_(NSMakePoint(screen.origin.x + (screen.size.width - WIDTH) / 2,
                                                   screen.origin.y + 28))
            self.panel.orderFrontRegardless()
        if not self.timer:
            self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1 / 30, self.wave, "tick:", None, True)

    def hide(self):
        if self.timer:
            self.timer.invalidate()
            self.timer = None
        self.panel.orderOut_(None)
