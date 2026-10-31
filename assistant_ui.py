"""Native macOS window for the Jev voice assistant: status on top, sidebar tabs for the dictionary, apps, history and keys.

The window is resizable. Frames come from assistant_layout so a smaller window
reflows instead of clipping. The frame is saved under HeyJevMainWindow, and a
missing or offscreen frame is centered.
"""
import json
import math
import os
import re
import queue
import subprocess
import sys
import threading
import time

import objc
from AppKit import (
    NSAlert,
    NSAnimationContext,
    NSApp,
    NSAppearance,
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSBox,
    NSButton,
    NSColor,
    NSEvent,
    NSEventMaskFlagsChanged,
    NSEventMaskKeyDown,
    NSEventModifierFlagCommand,
    NSEventModifierFlagControl,
    NSEventModifierFlagOption,
    NSImageView,
    NSEventMaskLeftMouseDragged,
    NSEventMaskLeftMouseUp,
    NSEventTypeLeftMouseUp,
    NSFont,
    NSEdgeInsets,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSGraphicsContext,
    NSImage,
    NSMakePoint,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSPanel,
    NSPasteboard,
    NSPasteboardTypeString,
    NSPopUpButton,
    NSScreen,
    NSScrollView,
    NSSearchField,
    NSSecureTextField,
    NSSegmentedControl,
    NSTableColumn,
    NSTableView,
    NSTextField,
    NSTextFieldCell,
    NSTextView,
    NSTrackingActiveAlways,
    NSTrackingArea,
    NSTrackingInVisibleRect,
    NSTrackingMouseEnteredAndExited,
    NSView,
    NSWorkspace,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialHUDWindow,
    NSVisualEffectStateActive,
    NSVisualEffectStateFollowsWindowActiveState,
    NSVisualEffectView,
    NSWindow,
    NSWindowAbove,
    NSWindowBelow,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskFullSizeContentView,
    NSWindowStyleMaskMiniaturizable,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
    NSImageScaleProportionallyUpOrDown,
    NSViewHeightSizable,
    NSViewWidthSizable,
    NSWindowStyleMaskNonactivatingPanel,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSInsetRect, NSAttributedString, NSMutableAttributedString, NSString, NSMakeSize, NSObject, NSURL, NSTimer, NSUserDefaults, NSDate, NSDefaultRunLoopMode
from assistant_layout import (
    DEFAULT_H,
    DEFAULT_W,
    FRAME_AUTOSAVE_NAME,
    HEADER,
    MIN_H,
    MIN_W,
    SIDEBAR,
    frame_is_usable,
    layout_window,
)
from bubble import Bubble
from dictation import HISTORY, read_vocab, save_vocab
from mini_bar import (
    ORIGIN_KEY,
    PEEK_PREF_KEY,
    PLACEHOLDER,
    PREF_KEY,
    SIZE_KEY,
    peek_enabled_from_pref,
    peek_plan,
    BarController,
    BAR_COLLECTION,
    PillPresentation,
    background_action,
    bar_controls,
    bar_metrics,
    capsule_click_moved,
    capsule_controls,
    collapsed_frame,
    default_size,
    expanded_frame_from_capsule,
    greeting_text,
    home_draft_from_popover,
    chip_command_plan,
    chip_width,
    popover_chip_ids,
    POPOVER_CHIPS,
    refresh_chip_suggestions,
    popover_controls,
    popover_open_animation,
    popover_subframes,
    POPOVER_PANEL_RADIUS,
    screen_for_frame,
    status_shows_in_pill,
    window_frame_for_presentation,
    drag_origin,
    finish_drag,
    enabled_from_pref,
    format_origin,
    format_size,
    level_to_unit,
    meter_active,
    mic_event,
    parse_origin,
    pill_chrome,
    capture_choice_actions,
    capture_saved,
    choice_due,
    choice_origin,
    choice_panel_box,
    pointer_inside,
    migrate_saved_origin,
    place_bar,
    plus_item,
    plus_menu,
    clipboard_item_index,
    clipboard_menu,
    clipboard_menu_phrase,
    option_held,
    remembered_size,
    reply_text,
    reset_origin,
    resize_edges,
    resize_frame,
    smooth,
    submission,
    trailing_symbol,
    control_option_command_held, type_focus_hotkey,
    TypedHistory,
    PillKeyFocus,
    caret_range,
    keyable_panel,
    PILL_BECOMES_KEY_ONLY_IF_NEEDED,
    undo_main_reveal,
    is_our_app,
)
from orb_motion import (
    CURSOR_POLL_SECONDS, DRAG_TICK_SECONDS, PEEK_FADE_SECONDS, PEEK_RETRACT_DISTANCE, SPRING_FOLLOW,
    SPRING_PEEK_IN, SPRING_PEEK_OUT, SPRING_SNAP,
    drag_roughness, drag_stretch, follow_step, in_hot_zone, peek_frame, should_retract,
    spring, spring_done,
)
from orb_view import make_orb_view, orb_frame, orb_state
from area_hotkey import AreaCaptureHotKey
from orb_motion import (
    MENU_CORNER_RADIUS, MENU_FILL_HOVER, MENU_FILL_REST, MENU_FAN_START_SCALE, MENU_HOVER_SECONDS,
    HINT_SECONDS, HINT_TEXT_INSET, RESULT_FADE_SECONDS, RESULT_SCALE_FROM, SPRING_MENU_FAN, TEXT_ACTIONS,
    hint_layout, menu_layout, result_frames, result_layout,
)
from mini_bar import FIND_IMAGE_HINT, capture_outcome, menu_on_drop, orb_action_menu
import full_window as fw
from ptt import PushToTalk
from secrets_store import KEY_NAMES, OPTIONAL, get_secret, missing_secrets, save_secret
from commands.model import CLAUDE_MODEL, MODEL_PREF
from updates import check_upstream, safe_browser_url


KeyablePanel = keyable_panel(NSPanel)

NORMAL, FLOATING = 0, 3  # NSNormalWindowLevel, NSFloatingWindowLevel
BAR_LEVEL = 28  # above NSStatusWindowLevel, so the capsule stays over status items
SIDEBAR_MATERIAL = 7  # NSVisualEffectMaterialSidebar
HINTS = {"ptt": "Hold right Option to talk", "wake": "Say “Hey Jev”, then your command"}
MODES = ("ptt", "wake")
TABS = (("home", "Home"), ("dict", "Dictionary"), ("apps", "Apps"), ("hist", "Dictation history"), ("priv", "Privacy"), ("settings", "Settings"), ("keys", "Keys"))
LOG_FILE = os.path.expanduser("~/Library/Logs/Hey Jev.log")
TYPING_WPM, SPEAKING_WPM = 40, 150  # average typing vs talking speed, for "time saved"
ACTION_NAMES = {"app_open": "Open app", "app_quit": "Quit app", "app_hide": "Hide app", "app_minimise": "Minimise",
                "app_focus": "Switch to app", "media_play": "Play", "media_pause": "Pause", "media_next": "Next track",
                "media_previous": "Previous track", "timer_set": "Timers", "timer_remind": "Reminders"}
APPS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apps.json")
HOW_TO = ("“Hey Jev, open Spotify” runs a command. In Hold Option mode, hold right Option and just say it.\n"
          "“Hey Jev, transcribe” starts dictating, with a bubble at the bottom of the screen. "
          "Say “stop transcribing” and it pastes where your cursor is.\n"
          "“Clipboard history” reads recent plain-text copies. That list stays on this Mac.")
PRIVACY = (
    ("Stays on your Mac", "Everything the mic hears. Whisper listens for \u201cHey Jev\u201d on your Mac and throws away anything that isn't for her. Your dictionary, dictation history and logs stay in this folder and ~/Library/Logs."),
    ("TypeSafe (Jev)  \u00b7  text", "Only the words after \u201cHey Jev\u201d, like \u201copen Spotify\u201d, to work out what to do."),
    ("OpenRouter or OpenAI  \u00b7  audio", "Dictation audio, only between \u201ctranscribe\u201d and \u201cstop transcribing\u201d. OpenAI is the default: straight to OpenAI if that key is saved, otherwise through OpenRouter. \u201cUse scribe for dictation\u201d sends it through OpenRouter to ElevenLabs Scribe v2, with the same OpenRouter key. If Scribe fails, OpenAI is tried, then Whisper on this Mac. Questions that aren't commands go to Claude Haiku on OpenRouter as text."),
    ("Fish Audio  \u00b7  text", "The text of her replies, to turn into her voice. Scripted replies are saved after the first time, so most are never sent again."),
    ("GitHub  \u00b7  read only", "Check for updates, only when you click it, asks api.github.com whether henryklunaris/hey-jev has new commits. No token is sent. Nothing is downloaded or installed."),
    ("Clipboard history  \u00b7  on this Mac", "Recent plain-text copies stay in memory. Secrets, one-time codes, and password-manager copies are skipped. Nothing is sent to an API, and the iPhone bridge cannot read it."),
)
KEY_ROWS = (
    ("TypeSafe", "TYPESAFE_API_KEY", "Jev, decides what each command means"),
    ("Fish Audio", "FISH_AUDIO_API_KEY", "Her voice"),
    ("OpenRouter", "OPENROUTER_API_KEY", "Questions, and dictation when there's no OpenAI key"),
    ("OpenAI", "OPENAI_API_KEY", "Optional, sends dictation straight to OpenAI"),
)

STATUS_COLORS = {
    "Starting": NSColor.systemOrangeColor(),
    "Ready": NSColor.systemGreenColor(),
    "Listening": NSColor.systemRedColor(),
    "Transcribing": NSColor.systemBlueColor(),
    "Thinking": NSColor.systemPurpleColor(),
    "Doing it": NSColor.systemOrangeColor(),
    "Speaking": NSColor.systemTealColor(),
    "Something went wrong": NSColor.systemRedColor(),
    "Time's up": NSColor.systemYellowColor(),
    "Dictating": NSColor.systemRedColor(),
    "Finishing": NSColor.systemBlueColor(),
}


_IDLE_STATUS_DETAILS = {
    "",
    "Loading Whisper\u2026",
    "Add your API keys to begin",
    "Ready when you are",
    "Say \u201cHey Jev\u201d and your command",
}


def _hold_option_detail(owner, state, detail):
    """Keep the permission line on idle states. A real reply still shows."""
    if not getattr(owner, "_hold_option_blocked", False):
        return detail
    if state in ("Starting", "Ready") and detail in _IDLE_STATUS_DETAILS:
        return "Hold-Option needs Accessibility"
    return detail


def label(text, frame, size, color=None, weight=0.5):
    view = NSTextField.labelWithString_(text)
    view.setFrame_(frame)
    view.setFont_(NSFont.systemFontOfSize_weight_(size, weight))
    view.setTextColor_(color or NSColor.labelColor())
    view.setLineBreakMode_(4)  # truncate the end
    return view


def text_field(frame, placeholder, secure=False):
    field = (NSSecureTextField if secure else NSTextField).alloc().initWithFrame_(frame)
    field.setBezelStyle_(1)  # rounded
    field.setPlaceholderString_(placeholder)
    return field


def button(title, target, action, frame):
    b = NSButton.buttonWithTitle_target_action_(title, target, action)
    b.setFrame_(frame)
    b.setBezelStyle_(1)
    return b


def _place(view, frame):
    view.setFrame_(NSMakeRect(frame[0], frame[1], frame[2], frame[3]))


def _scroll_from_top(scroll):
    doc = scroll.documentView()
    if doc is None:
        return 0.0
    clip = scroll.contentView()
    doc_h = float(doc.frame().size.height)
    origin_y = float(clip.bounds().origin.y)
    clip_h = float(clip.bounds().size.height)
    return max(0.0, doc_h - (origin_y + clip_h))


def _restore_scroll_from_top(scroll, offset):
    doc = scroll.documentView()
    clip = scroll.contentView()
    if doc is None or clip is None:
        return
    doc_h = float(doc.frame().size.height)
    clip_h = float(clip.bounds().size.height)
    origin_y = doc_h - clip_h - float(offset)
    if origin_y < 0.0:
        origin_y = 0.0
    clip.scrollToPoint_((0.0, origin_y))
    scroll.reflectScrolledClipView_(clip)


def _set_column_widths(table, widths):
    for column, width in zip(list(table.tableColumns()), widths):
        column.setWidth_(float(width))


def _place_table(scroll, frame, table, widths):
    """Size the table's scroll view, then the columns, so rows scroll inside the new width."""
    _place(scroll, frame)
    height = max(float(frame[3]), float(table.frame().size.height))
    table.setFrame_(NSMakeRect(0, 0, frame[2], height))
    _set_column_widths(table, widths)


# Layout keys are longer than the tab keys the rest of the window uses.
_PAGE_SPECS = (
    ("home", "home"),
    ("dict", "dictionary"),
    ("apps", "apps"),
    ("hist", "history"),
    ("priv", "privacy"),
    ("settings", "settings"),
    ("keys", "keys"),
)


def spec_pages(spec):
    for ui_key, layout_key in _PAGE_SPECS:
        yield ui_key, spec[layout_key]


def app_key(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")  # "Claude Code" -> claude_code, what Jev matches on



def hid_modifier_flags():
    """Modifier flags with the device-dependent bits, or None.

    NSEvent.modifierFlags() drops NX_DEVICERALTKEYMASK (0x40), so the PTT
    watchdog read right Option as up while it was held and cut every hold
    off within half a second. CGEventSourceFlagsState keeps that bit. When
    Quartz is missing the watchdog is skipped rather than guessing.
    """
    try:
        import Quartz
        return int(Quartz.CGEventSourceFlagsState(Quartz.kCGEventSourceStateHIDSystemState))
    except Exception:
        return None


class CenteredFieldCell(NSTextFieldCell):
    """One line of text, vertically centered in the field. Placeholder included."""

    def drawingRectForBounds_(self, bounds):
        rect = objc.super(CenteredFieldCell, self).drawingRectForBounds_(bounds)
        font = self.font()
        if font is None:
            return rect
        line = float(font.ascender() - font.descender())
        extra = float(rect.size.height) - line
        if extra <= 1.0:
            return rect
        return NSMakeRect(float(rect.origin.x), float(rect.origin.y) + extra / 2.0, float(rect.size.width), line)

    def selectWithFrame_inView_editor_delegate_start_length_(self, rect, view, editor, delegate, start, length):
        objc.super(CenteredFieldCell, self).selectWithFrame_inView_editor_delegate_start_length_(
            self.drawingRectForBounds_(rect), view, editor, delegate, start, length)


def _capsule_layer(view, radius, mask):
    """Continuous-corner capsule. The backing clips. The pill itself does not, so the window shadow stays."""
    if view is None:
        return
    try:
        view.setWantsLayer_(True)
        layer = view.layer()
    except Exception:
        return
    if layer is None:
        return
    layer.setCornerRadius_(float(radius))
    layer.setMasksToBounds_(bool(mask))
    if hasattr(layer, "setCornerCurve_"):
        layer.setCornerCurve_("continuous")


def _glass_pass_through():
    """NSGlassEffectView that does not eat clicks, or None when this Mac has no such class."""
    cached = getattr(_glass_pass_through, "cls", None)
    if cached is not None:
        return cached
    try:
        glass = objc.lookUpClass("NSGlassEffectView")
    except Exception:
        return None
    if glass is None:
        return None

    class PassThroughGlass(glass):
        def hitTest_(self, _point):
            return None

    _glass_pass_through.cls = PassThroughGlass
    return PassThroughGlass


def _corner_mask(radius):
    """Resizable rounded-rect mask for NSVisualEffectView (crisp at any scale)."""
    radius = float(radius)
    side = radius * 2.0 + 1.0

    def draw(rect):
        NSColor.blackColor().setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, radius, radius).fill()
        return True

    image = NSImage.imageWithSize_flipped_drawingHandler_((side, side), False, draw)
    image.setCapInsets_(NSEdgeInsets(radius, radius, radius, radius))
    image.setResizingMode_(1)  # NSImageResizingModeStretch
    return image


class SolidPanelView(NSView):
    """Reduce Transparency: an opaque rounded panel instead of vibrancy."""

    def hitTest_(self, _point):
        return None

    def drawRect_(self, _rect):
        b = self.bounds()
        NSColor.windowBackgroundColor().setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            b, POPOVER_PANEL_RADIUS, POPOVER_PANEL_RADIUS).fill()


class SolidFullView(NSView):
    """Flat REA-token fill for the full window (also the Reduce Transparency backing)."""

    def drawRect_(self, _rect):
        name = getattr(self, "fill", "soft")
        radius = float(getattr(self, "radius", 0.0))
        dark = "Dark" in str(self.effectiveAppearance().name())
        r, g, b = fw.token(name, dark)
        NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0).setFill()
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSInsetRect(self.bounds(), 0.5, 0.5) if getattr(self, "stroke", None) else self.bounds(), radius, radius)
        path.fill()
        stroke = getattr(self, "stroke", None)
        if stroke:
            r, g, b = fw.token(stroke, dark)
            NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0).setStroke()
            path.setLineWidth_(1.0)
            path.stroke()


class PassThroughEffect(NSVisualEffectView):
    """HUD vibrancy that does not eat clicks. Drag and resize stay on the pill."""

    def hitTest_(self, _point):
        return None


class PillChromeOverlay(NSView):
    """Hairline and specular highlight drawn above the glass and under the controls."""

    def hitTest_(self, _point):
        return None

    def drawRect_(self, _rect):
        try:
            bounds = self.bounds()
            width = float(bounds.size.width)
            height = float(bounds.size.height)
            if width < 2.0 or height < 2.0:
                return
            inset = 0.75
            radius = max(1.0, height / 2.0 - inset)
            rect = NSMakeRect(inset, inset, width - inset * 2.0, height - inset * 2.0)
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, radius, radius)
            if getattr(self, "solidFill", False):
                NSColor.windowBackgroundColor().setFill()
                path.fill()
            ctx = NSGraphicsContext.currentContext()
            if ctx is not None:
                ctx.saveGraphicsState()
                path.addClip()
                gloss = NSBezierPath.bezierPath()
                gloss.moveToPoint_(NSMakePoint(radius, height - 1.25))
                gloss.lineToPoint_(NSMakePoint(width - radius, height - 1.25))
                NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.45).setStroke()
                gloss.setLineWidth_(1.0)
                gloss.stroke()
                ctx.restoreGraphicsState()
            contrast = bool(getattr(self, "contrastBorder", False))
            hairline = NSColor.separatorColor()
            if not contrast:
                hairline = hairline.colorWithAlphaComponent_(0.85)
            hairline.setStroke()
            path.setLineWidth_(1.5 if contrast else 0.75)
            path.stroke()
        except Exception as exc:
            print(f"  mini bar draw failed: {exc}")


class MiniBarBackground(NSView):
    """Capsule behind the controls. The background moves it. The outer edge resizes it.

    Glass or vibrancy sits underneath. This view does not fill, so the wallpaper
    can show through. The + button, the text field, and the mic sit on top and
    keep their own clicks. A double-click on the background recenters the pill
    and restores its default size. A nonactivating panel ignores the normal
    title-bar drag, so a single click tracks the mouse in screen coordinates
    and moves or resizes the frame itself. That works across displays.
    """

    def drawRect_(self, _rect):
        return

    def hitTest_(self, point):
        hit = objc.super(MiniBarBackground, self).hitTest_(point)
        if hit is not None and hit is not self and getattr(hit, "passesClicks", False):
            return self
        return hit

    def viewDidChangeEffectiveAppearance(self):
        window = self.window()
        if window is None:
            return
        delegate = window.delegate()
        if delegate is not None and hasattr(delegate, "refreshPillChrome_"):
            delegate.refreshPillChrome_(self)

    @objc.python_method
    def _collapsed_click_or_drag(self, window, delegate, _event):
        """A still click opens the typing pill. A drag moves the capsule.

        Press squashes the orb. A drag trails the cursor on a spring, stretches along its travel, then
        jiggles and springs to the snap target on release. Reduce Motion keeps the exact-follow drag.
        """
        self._finish_drag_settle()
        if delegate is not None and hasattr(delegate, "_peek_before_drag"):
            delegate._peek_before_drag()  # a tucked orb comes out to its inset before the drag starts
        orb = getattr(delegate, "orb_view", None) if delegate is not None else None
        animate = orb is not None and not orb.reduceMotion
        if animate:
            orb.pressSquash()
        down = NSEvent.mouseLocation()
        start = (float(down.x), float(down.y))
        frame = window.frame()
        origin = (float(frame.origin.x), float(frame.origin.y))
        if animate:
            moved = self._drag_with_spring(window, delegate, orb, start, origin)
            if moved:
                return  # the settle spring finalizes the drag when it lands
        else:
            moved = self._drag_exactly(window, start, origin)
            if moved and delegate is not None and hasattr(delegate, "_finalize_mini_bar_drag"):
                delegate._finalize_mini_bar_drag(window)
                return
        if delegate is not None:
            delegate._orb_dragging = False  # only a press that never moved gets here; a real drag clears it on finalize
        if animate:
            orb.releaseSquash()
        if not moved and delegate is not None and hasattr(delegate, "expandMiniBar_"):
            delegate.expandMiniBar_(self)

    @objc.python_method
    def _drag_exactly(self, window, start, origin):
        """Reduce Motion: the window follows the cursor exactly, as before PR 3a. Returns True once it moved."""
        mask = NSEventMaskLeftMouseDragged | NSEventMaskLeftMouseUp
        moved = False
        while True:
            nxt = window.nextEventMatchingMask_(mask)
            if nxt is None or nxt.type() == NSEventTypeLeftMouseUp:
                break
            now = NSEvent.mouseLocation()
            point = (float(now.x), float(now.y))
            if capsule_click_moved(start, point):
                moved = True
            if moved:
                x, y = drag_origin(origin, start, point)
                window.setFrameOrigin_(NSMakePoint(x, y))
        return moved

    @objc.python_method
    def _drag_with_spring(self, window, delegate, orb, start, origin):
        """Spring drag. Returns True once it moved past the click threshold, and then starts the release.

        The window trails the cursor target with follow_step, and the orb stretches from the smoothed speed.
        The loop wakes at DRAG_TICK_SECONDS even when the mouse is still, which is the 60 Hz tick. A nested
        tracking loop blocks on events, so an NSTimer is not used here. The release uses an NSTimer.
        """
        mask = NSEventMaskLeftMouseDragged | NSEventMaskLeftMouseUp
        pos, vel, smoothed = origin, (0.0, 0.0), (0.0, 0.0)
        samples = []
        moved = False
        last = time.monotonic()
        while True:
            nxt = window.nextEventMatchingMask_untilDate_inMode_dequeue_(
                mask, NSDate.dateWithTimeIntervalSinceNow_(DRAG_TICK_SECONDS), NSDefaultRunLoopMode, True)
            if nxt is not None and nxt.type() == NSEventTypeLeftMouseUp:
                break
            now = NSEvent.mouseLocation()
            point = (float(now.x), float(now.y))
            stamp = time.monotonic()
            dt = stamp - last
            last = stamp
            if not moved:
                if not capsule_click_moved(start, point):
                    continue
                moved = True
            pos, vel = follow_step(pos, vel, drag_origin(origin, start, point), dt, *SPRING_FOLLOW)
            smoothed = (smooth(smoothed[0], vel[0]), smooth(smoothed[1], vel[1]))
            window.setFrameOrigin_(NSMakePoint(pos[0], pos[1]))
            orb.dragStretch(*drag_stretch(smoothed[0], smoothed[1]))
            samples.append((stamp, pos[0], pos[1]))
        if not moved:
            return False
        orb.dropJiggle()
        if delegate is not None:
            delegate.last_drag_roughness = drag_roughness(samples)
            size = window.frame().size
            target = finish_drag(pos, (float(size.width), float(size.height)), delegate._visible_screens())
            self._start_drag_settle(window, delegate, pos, vel, target)
        return True

    @objc.python_method
    def _start_drag_settle(self, window, delegate, origin, velocity, target):
        """Spring the window from where the drag left it to the snap target, at 60 Hz."""
        self._stop_drag_settle()
        self._drag_settle = {"window": window, "delegate": delegate, "origin": origin,
                             "velocity": velocity, "target": target, "started": time.monotonic()}
        self._drag_settle_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            DRAG_TICK_SECONDS, self, "settleDragTick:", None, True)

    def settleDragTick_(self, _timer):
        state = getattr(self, "_drag_settle", None)
        if state is None:
            self._stop_drag_settle()
            return
        elapsed = time.monotonic() - state["started"]
        axes = [spring(elapsed, state["origin"][i], state["target"][i], *SPRING_SNAP,
                       v0=state["velocity"][i]) for i in (0, 1)]
        done = all(spring_done(axes[i][0], axes[i][1], state["target"][i]) for i in (0, 1))
        x, y = state["target"] if done else (axes[0][0], axes[1][0])
        state["window"].setFrameOrigin_(NSMakePoint(x, y))
        if done:
            self._land_drag_settle(state)

    @objc.python_method
    def _land_drag_settle(self, state):
        self._stop_drag_settle()
        delegate = state["delegate"]
        if delegate is not None and hasattr(delegate, "_finalize_mini_bar_drag"):
            delegate._finalize_mini_bar_drag(state["window"])

    @objc.python_method
    def _finish_drag_settle(self):
        """A new press during the settle lands the window at once, so the drag never stacks two springs."""
        state = getattr(self, "_drag_settle", None)
        if state is None:
            return
        state["window"].setFrameOrigin_(NSMakePoint(state["target"][0], state["target"][1]))
        self._land_drag_settle(state)

    @objc.python_method
    def _stop_drag_settle(self):
        timer = getattr(self, "_drag_settle_timer", None)
        if timer is not None:
            timer.invalidate()
        self._drag_settle_timer = None
        self._drag_settle = None

    def mouseDown_(self, event):
        window = self.window()
        if window is None:
            return
        delegate = window.delegate()
        if delegate is not None and getattr(delegate, "pillCollapsed", False):
            self._collapsed_click_or_drag(window, delegate, event)
            return
        bounds = self.bounds()
        size = (float(bounds.size.width), float(bounds.size.height))
        point = self.convertPoint_fromView_(event.locationInWindow(), None)
        px, py = float(point.x), float(point.y)
        controls = None
        control_size = size
        if delegate is not None and hasattr(delegate, "_composer_rect"):
            composer_rect = delegate._composer_rect()
            screens = delegate._visible_screens() if hasattr(delegate, "_visible_screens") else []
            screen = screen_for_frame(composer_rect, screens) if screens else None
            if screen is None and screens:
                screen = screens[0]
            layout = popover_subframes(composer_rect, screen or (0.0, 0.0, size[0], size[1]))
            cx, cy, cw, ch = layout["composer"]
            if cx <= px < cx + cw and cy <= py < cy + ch:
                controls = popover_controls((cw, ch))
                control_size = (cw, ch)
                px -= cx
                py -= cy
        action = background_action(event.clickCount(), px, py, controls, control_size)
        if action == "reset":
            delegate = window.delegate()
            if delegate is not None:
                delegate.resetMiniBarPosition_(self)
            return
        if action == "resize":
            down = NSEvent.mouseLocation()
            frame = window.frame()
            start = (float(down.x), float(down.y))
            delegate = window.delegate()
            if delegate is not None and not getattr(delegate, "pillCollapsed", False):
                comp_size = getattr(delegate, "_expanded_size", None) or default_size()
                original = (0.0, 0.0, float(comp_size[0]), float(comp_size[1]))
                edges = resize_edges(px, py, control_size)
                mask = NSEventMaskLeftMouseDragged | NSEventMaskLeftMouseUp
                while True:
                    nxt = window.nextEventMatchingMask_(mask)
                    if nxt is None or nxt.type() == NSEventTypeLeftMouseUp:
                        break
                    now = NSEvent.mouseLocation()
                    _x, _y, w, h = resize_frame(original, edges, start, (float(now.x), float(now.y)))
                    delegate._expanded_size = (w, h)
                    delegate._apply_pill_presentation()
                return
            original = (float(frame.origin.x), float(frame.origin.y),
                        float(frame.size.width), float(frame.size.height))
            edges = resize_edges(px, py, control_size)
            mask = NSEventMaskLeftMouseDragged | NSEventMaskLeftMouseUp
            while True:
                nxt = window.nextEventMatchingMask_(mask)
                if nxt is None or nxt.type() == NSEventTypeLeftMouseUp:
                    break
                now = NSEvent.mouseLocation()
                x, y, w, h = resize_frame(original, edges, start, (float(now.x), float(now.y)))
                window.setFrame_display_animate_(NSMakeRect(x, y, w, h), True, False)
                delegate = window.delegate()
                if delegate is not None:
                    delegate.layoutMiniBar_(self)
            return
        if action != "drag":
            return
        down = NSEvent.mouseLocation()
        frame = window.frame()
        start = (float(down.x), float(down.y))
        origin = (float(frame.origin.x), float(frame.origin.y))
        mask = NSEventMaskLeftMouseDragged | NSEventMaskLeftMouseUp
        while True:
            nxt = window.nextEventMatchingMask_(mask)
            if nxt is None or nxt.type() == NSEventTypeLeftMouseUp:
                break
            now = NSEvent.mouseLocation()
            x, y = drag_origin(origin, start, (float(now.x), float(now.y)))
            window.setFrameOrigin_(NSMakePoint(x, y))
        delegate = window.delegate()
        if delegate is not None and hasattr(delegate, "_finalize_mini_bar_drag"):
            delegate._finalize_mini_bar_drag(window)


class PillButton(NSButton):
    """Symbol button with a quiet hover and press tint. System colors follow light and dark."""

    def updateTrackingAreas(self):
        objc.super(PillButton, self).updateTrackingAreas()
        areas = self.trackingAreas()
        if areas is not None:
            for area in list(areas):
                self.removeTrackingArea_(area)
        options = NSTrackingMouseEnteredAndExited | NSTrackingActiveAlways | NSTrackingInVisibleRect
        area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(NSMakeRect(0, 0, 0, 0), options, self, None)
        self.addTrackingArea_(area)
        self._apply_pill_tint()

    def mouseEntered_(self, _event):
        self._pill_hover = True
        self._apply_pill_tint()

    def mouseExited_(self, _event):
        self._pill_hover = False
        self._apply_pill_tint()

    def mouseDown_(self, event):
        self._pill_pressed = True
        self._apply_pill_tint()
        try:
            objc.super(PillButton, self).mouseDown_(event)
        finally:
            self._pill_pressed = False
            self._apply_pill_tint()

    def _apply_pill_tint(self):
        if not hasattr(self, "setContentTintColor_"):
            return
        # Right Option (push to talk) paints the mic blue until the key is released.
        if getattr(self, "speakingTint", False):
            self.setContentTintColor_(NSColor.systemBlueColor())
            return
        if getattr(self, "_pill_pressed", False):
            color = NSColor.tertiaryLabelColor()
        elif getattr(self, "_pill_hover", False):
            color = NSColor.secondaryLabelColor()
        else:
            color = NSColor.labelColor()
        self.setContentTintColor_(color)


class GreetingBubbleView(NSView):
    """Small speech bubble beside the orb."""

    def drawRect_(self, _rect):
        try:
            bounds = self.bounds()
            width = float(bounds.size.width)
            height = float(bounds.size.height)
            if width < 4.0 or height < 4.0:
                return
            inset = 0.75
            radius = min(14.0, height / 2.0 - inset)
            rect = NSMakeRect(inset, inset, width - inset * 2.0, height - inset * 2.0)
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, radius, radius)
            solid = bool(getattr(self, "solidFill", False))
            if solid:
                NSColor.windowBackgroundColor().setFill()
            else:
                NSColor.colorWithCalibratedWhite_alpha_(0.12, 0.88).setFill()
            path.fill()
            NSColor.separatorColor().colorWithAlphaComponent_(0.55).setStroke()
            path.setLineWidth_(0.75)
            path.stroke()
        except Exception as exc:
            print(f"  greeting bubble draw failed: {exc}")


class MicLevelView(NSView):
    """Live mic level over the glyph: a ring and four bars.

    Amplitude is the smoothed unit raised to 0.7. Clicks fall through to the
    mic button. An idle amplitude draws nothing, so the glyph stays put until
    the key is held.
    """

    def hitTest_(self, _point):
        return None

    def setAmplitude_(self, unit):
        try:
            value = float(unit)
        except (TypeError, ValueError):
            value = 0.0
        if value < 0.0:
            value = 0.0
        elif value > 1.0:
            value = 1.0
        self.amplitude = value
        self.setNeedsDisplay_(True)

    def drawRect_(self, _rect):
        try:
            self._draw_level()
        except Exception as exc:
            print(f"  mic level draw failed: {exc}")

    @objc.python_method
    def _draw_level(self):
        amp = float(getattr(self, "amplitude", 0.0) or 0.0)
        if amp <= 0.02:
            return
        bounds = self.bounds()
        width = float(bounds.size.width)
        height = float(bounds.size.height)
        if width < 8.0 or height < 8.0:
            return
        color = NSColor.systemBlueColor()
        inset = 1.0
        radius = min(width, height) / 2.0 - inset
        oval = NSMakeRect(width / 2.0 - radius, height / 2.0 - radius, radius * 2.0, radius * 2.0)
        ring = NSBezierPath.bezierPathWithOvalInRect_(oval)
        color.colorWithAlphaComponent_(0.35 + 0.65 * amp).setStroke()
        ring.setLineWidth_(1.0 + 1.5 * amp)
        ring.stroke()
        shapes = (0.55, 0.9, 1.0, 0.7)
        gap = max(1.0, width * 0.05)
        bar_w = max(1.5, (width * 0.46 - gap * (len(shapes) - 1)) / len(shapes))
        total = bar_w * len(shapes) + gap * (len(shapes) - 1)
        left = (width - total) / 2.0
        max_h = height * 0.46
        for index, shape in enumerate(shapes):
            bar_h = max(2.0, max_h * amp * shape)
            x = left + index * (bar_w + gap)
            y = (height - bar_h) / 2.0
            rect = NSMakeRect(x, y, bar_w, bar_h)
            bar = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, bar_w / 2.0, bar_w / 2.0)
            color.colorWithAlphaComponent_(0.9).setFill()
            bar.fill()


class PopoverChipButton(NSButton):
    """Wrapping quick-action chip under the orb composer."""

    def initWithFrame_(self, frame):
        self = objc.super(PopoverChipButton, self).initWithFrame_(frame)
        if self is None:
            return None
        self.setBordered_(False)
        self.setTitle_("")
        self.setTarget_(None)
        self.setAction_("miniChip:")
        self.chipId = ""
        self.chipTitle = ""
        self.chipSubtitle = ""
        return self

    @objc.python_method
    def configure(self, chip_id, title, subtitle):
        self.chipId = str(chip_id or "")
        self.chipTitle = str(title or "")
        self.chipSubtitle = str(subtitle or "")
        self.setTitle_("")
        self.setAccessibilityLabel_(self.chipTitle)
        self.setToolTip_(self.chipSubtitle or self.chipTitle)
        self.setNeedsDisplay_(True)

    def drawRect_(self, _rect):
        """Full capsule with the complete title (and subtitle), vector only."""
        try:
            b = self.bounds()
            w, h = float(b.size.width), float(b.size.height)
            if w < 4.0 or h < 4.0:
                return
            r = min(12.0, h / 2.0)
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(0.5, 0.5, w - 1.0, h - 1.0), r, r)
            pressed = self.isHighlighted()
            NSColor.labelColor().colorWithAlphaComponent_(0.16 if pressed else 0.08).setFill()
            path.fill()
            NSColor.separatorColor().setStroke()
            path.setLineWidth_(0.75)
            path.stroke()
            title = getattr(self, "chipTitle", "") or ""
            sub = getattr(self, "chipSubtitle", "") or ""
            tf = NSFont.systemFontOfSize_weight_(12.5, 0.23)
            ta = {NSFontAttributeName: tf, NSForegroundColorAttributeName: NSColor.labelColor()}
            ts = NSString.stringWithString_(title)
            tsz = ts.sizeWithAttributes_(ta)
            if sub:
                sf = NSFont.systemFontOfSize_(10.5)
                sa = {NSFontAttributeName: sf, NSForegroundColorAttributeName: NSColor.secondaryLabelColor()}
                ss = NSString.stringWithString_(sub)
                ssz = ss.sizeWithAttributes_(sa)
                total = tsz.height + ssz.height
                y0 = (h - total) / 2.0
                # NSButton is flipped: the title goes on top, the subtitle below.
                ts.drawAtPoint_withAttributes_(NSMakePoint(12.0, y0), ta)
                ss.drawAtPoint_withAttributes_(NSMakePoint(12.0, y0 + tsz.height), sa)
            else:
                ts.drawAtPoint_withAttributes_(
                    NSMakePoint((w - tsz.width) / 2.0, (h - tsz.height) / 2.0), ta)
        except Exception as exc:
            print(f"  chip draw failed: {exc}")


class HoldMicButton(PillButton):
    """Mouse down and up map to the same press and release as right Option.

    When the symbol is the send arrow, the click submits the field instead.
    """

    def mouseDown_(self, event):
        target = self.target()
        if getattr(self, "pillRole", "mic") == "expand":
            if target is not None and hasattr(target, "expandMiniBar_"):
                target.expandMiniBar_(self)
            return
        if getattr(self, "pillRole", "mic") == "send":
            self._pill_pressed = True
            self._apply_pill_tint()
            try:
                if target is not None:
                    target.miniSubmit_(self)
            finally:
                self._pill_pressed = False
                self._apply_pill_tint()
            return
        if target is not None:
            target.miniMicDown_(self)
        window = self.window()
        if window is None:
            target.miniMicUp_(self) if target is not None else None
            return
        mask = NSEventMaskLeftMouseDragged | NSEventMaskLeftMouseUp
        try:
            while True:
                nxt = window.nextEventMatchingMask_(mask)
                if nxt is None or nxt.type() == NSEventTypeLeftMouseUp:
                    break
        finally:
            if target is not None:
                target.miniMicUp_(self)


class PillTextField(NSTextField):
    """The first click focuses the pill and shows a caret.

    acceptsFirstMouse so that click is not swallowed just to activate the app.
    """

    def acceptsFirstMouse_(self, _event):
        return True

    def mouseDown_(self, event):
        window = self.window()
        delegate = window.delegate() if window is not None else None
        if delegate is not None and hasattr(delegate, "pillFieldClicked_"):
            delegate.pillFieldClicked_(self)
        objc.super(PillTextField, self).mouseDown_(event)


def set_action_fill(layer, alpha):
    """Animate a round action button's white fill to `alpha` over MENU_HOVER_SECONDS, easeOut (PR 5a hover)."""
    from Quartz import CAMediaTimingFunction, CATransaction
    if layer is None:
        return
    CATransaction.begin()
    CATransaction.setAnimationDuration_(MENU_HOVER_SECONDS)
    CATransaction.setAnimationTimingFunction_(CAMediaTimingFunction.functionWithName_("easeOut"))
    layer.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(1.0, alpha).CGColor())
    CATransaction.commit()


class ActionMenuButton(NSView):
    """One row of the action menu: a round circle with its symbol, and the label beside it.

    A plain NSView, not NSButton, so the circle is a layer we control. hitTest_ answers every point inside the
    row with the row itself, so the symbol and label never take the click. Hover fills the circle only.
    """

    circle_layer = None
    pick_target = None  # the delegate; its actionMenuPick_ takes this view, and identifier() is the action id

    def acceptsFirstMouse_(self, _event):
        return True  # the panel never becomes key, so a first click must still count

    def hitTest_(self, point):
        from AppKit import NSMouseInRect
        superview = self.superview()
        if superview is None:
            return None
        return self if NSMouseInRect(point, self.frame(), superview.isFlipped()) else None

    def mouseDown_(self, _event):
        if self.pick_target is not None:
            self.pick_target.actionMenuPick_(self)

    def updateTrackingAreas(self):
        objc.super(ActionMenuButton, self).updateTrackingAreas()
        areas = self.trackingAreas()
        if areas is not None:
            for area in list(areas):
                self.removeTrackingArea_(area)
        options = NSTrackingMouseEnteredAndExited | NSTrackingActiveAlways | NSTrackingInVisibleRect
        area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(NSMakeRect(0, 0, 0, 0), options, self, None)
        self.addTrackingArea_(area)

    def mouseEntered_(self, _event):
        set_action_fill(self.circle_layer, MENU_FILL_HOVER)

    def mouseExited_(self, _event):
        set_action_fill(self.circle_layer, MENU_FILL_REST)


class HintClickView(NSView):
    """Covers the Find Image hint. A click on it dismisses the hint."""

    dismiss_target = None

    def acceptsFirstMouse_(self, _event):
        return True

    def mouseDown_(self, _event):
        if self.dismiss_target is not None:
            self.dismiss_target.hintDismiss_(self)


def result_pill(title, frame, scale, target, action):
    """Copy and Close on the result panel: a small rounded pill with a faint white fill."""
    pill = NSButton.alloc().initWithFrame_(NSMakeRect(*frame))
    pill.setBordered_(False)
    pill.setTitle_(title)
    pill.setFont_(NSFont.systemFontOfSize_weight_(12, 0.4))
    pill.setContentTintColor_(NSColor.whiteColor())
    pill.setWantsLayer_(True)
    pill.layer().setCornerRadius_(frame[3] / 2.0)
    pill.layer().setContentsScale_(scale)
    pill.layer().setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.14).CGColor())
    pill.setTarget_(target)
    pill.setAction_(action)
    pill.setAccessibilityLabel_(title)
    return pill


class ClickAwayView(NSView):
    def mouseDown_(self, event):
        self.window().makeFirstResponder_(None)  # clicking empty space takes focus out of the search and text boxes
        objc.super(ClickAwayView, self).mouseDown_(event)

    def setFrameSize_(self, size):
        objc.super(ClickAwayView, self).setFrameSize_(size)
        on_resize = getattr(self, "onResize", None)
        if on_resize is not None:
            on_resize()


class AppDelegate(NSObject):
    # PR 3b peek-dock state. _peek_edge is None when the orb is not tucked.
    _peek_edge = None  # "left" or "right"
    _peek_screen = None  # visible frame the orb is tucked against
    _peek_inset = None  # window origin (x, y) at the 12 pt inset: the position that is saved
    _peek_showing = True  # target state: True = inset, False = tucked at the rest
    _peek_anim = None  # {from, to, k, c, t0} while sliding
    _peek_fading = False  # Reduce Motion fade in progress
    _peek_fade_token = None
    _peek_timer = None
    _peek_interval = None
    _peek_outside = 0.0  # seconds the cursor has been far from the orb
    _peek_last = None  # monotonic time of the last tick, or None after a pause
    _peek_latched = False  # tucked while the cursor was already at the edge: wait for it to leave first
    # PR 5a action menu, opened after a real drop (R3). Closed by a click, Esc, a click away or CHOICE_SECONDS.
    _action_menu_open = False
    _action_menu_panel = None
    _action_menu_buttons = ()  # (button, centre in the panel's own coordinates), one per row
    _action_menu_monitors = ()
    _action_menu_observing = False  # the workspace activation observer is registered
    # Summarize and Translate answer in a dark panel beside the orb, not in the Jev window.
    _result_panel = None
    _result_open = False
    _result_heading = ""
    _result_text = ""
    # PR 5a: the Find Image hint bubble. Nonactivating; closes on its own, on Esc, or on a click on it.
    _hint_panel = None
    _hint_open = False
    _hint_shown_at = 0.0
    _action_menu_shown_at = 0.0
    _orb_dragging = False

    def applicationDidFinishLaunching_(self, _notification):
        self.controls = queue.Queue()
        self.option_down = False
        self.ptt = PushToTalk()
        self.worker_started = False
        defaults = NSUserDefaults.standardUserDefaults()
        self.mode = defaults.stringForKey_("mode") or "ptt"
        if self.mode not in MODES:
            self.mode = "ptt"
        self.mic = defaults.stringForKey_("mic") or ""
        style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
                 | NSWindowStyleMaskResizable | NSWindowStyleMaskFullSizeContentView)
        self.panel = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, DEFAULT_W, DEFAULT_H), style, NSBackingStoreBuffered, False
        )
        self.panel.setTitle_("Hey Jev - Fish Audio")
        self.panel.setTitleVisibility_(1)  # hidden, the sidebar says it
        self.panel.setTitlebarAppearsTransparent_(True)
        self.panel.setMovableByWindowBackground_(True)
        self.panel.setReleasedWhenClosed_(False)  # closing just hides it, the Dock icon brings it back
        self.panel.setContentMinSize_(NSMakeSize(MIN_W, MIN_H))
        self.panel.setMinSize_(NSMakeSize(MIN_W, MIN_H))
        self.panel.setDelegate_(self)
        self._update_checking = False
        self._main_closing = False
        self.bar = BarController(enabled=enabled_from_pref(defaults.objectForKey_(PREF_KEY)))
        self.on_top = defaults.boolForKey_("keep_on_top")
        self.panel.setLevel_(FLOATING if self.on_top else NORMAL)
        self._add_window_menu()
        self._wire_update_menu()
        root = ClickAwayView.alloc().initWithFrame_(NSMakeRect(0, 0, DEFAULT_W, DEFAULT_H))
        self.panel.setContentView_(root)
        self.backdrop = NSBox.alloc().initWithFrame_(NSMakeRect(SIDEBAR, 0, DEFAULT_W - SIDEBAR, DEFAULT_H))
        self.backdrop.setBoxType_(4)  # custom, filled with the normal window colour
        self.backdrop.setBorderWidth_(0)
        self.backdrop.setFillColor_(NSColor.windowBackgroundColor())
        root.addSubview_(self.backdrop)
        self.bubble = Bubble()
        self._build_mini_bar()

        self.page_titles, self.page_subs = {}, {}
        self.page_docs, self.page_scrolls = {}, {}
        self._build_sidebar(root)
        self._build_header(root)
        self._build_home()
        self._build_dictionary()
        self._build_apps()
        self._build_history()
        self._build_privacy()
        self._build_settings()
        self._build_keys()
        self.pages = self.page_scrolls
        for page in self.pages.values():
            root.addSubview_(page)
        self._select_tab("keys" if missing_secrets() else "home")
        root.onResize = self._layout_window
        self._place_main_window()
        self._layout_window()
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(0.5, self, "tick:", None, True)

        self.panel.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        self.global_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSEventMaskFlagsChanged, self._global_flags_changed
        )
        self.local_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskFlagsChanged, self._local_flags_changed
        )
        self.key_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown, self._local_key
        )
        self.type_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown, self._global_type_key
        )
        # Control-Option-Command-W: Carbon hotkey, so it works from any app with no Accessibility or Input Monitoring grant.
        self.area_hotkey = AreaCaptureHotKey(self._area_hotkey_pressed)
        _ok, hotkey_detail = self.area_hotkey.register()
        print("  area hotkey: {0}".format(hotkey_detail))
        self._sync_mini_bar()
        self._hold_option_blocked = self.global_monitor is None or not self._accessibility_trusted()
        if missing_secrets():
            self.updateStatus_({"state": "Starting", "detail": "Add your API keys to begin"})
        else:
            self._start_worker()
        if self._hold_option_blocked:
            self.updateStatus_({"state": "Starting", "detail": "Hold-Option needs Accessibility"})

    # ------------------------------------------------------------------ layout
    @objc.python_method
    def _build_sidebar(self, root):
        side = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, SIDEBAR, DEFAULT_H))
        side.setMaterial_(SIDEBAR_MATERIAL)
        side.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        side.setState_(NSVisualEffectStateFollowsWindowActiveState)
        root.addSubview_(side)
        self.sidebar = side
        self.sidebar_title = label("Hey Jev", NSMakeRect(20, DEFAULT_H - 82, 170, 22), 15, weight=0.6)
        side.addSubview_(self.sidebar_title)
        self.tab_rows = {}
        for i, (key, title) in enumerate(TABS):
            box = NSBox.alloc().initWithFrame_(NSMakeRect(10, 0, SIDEBAR - 20, 30))
            box.setBoxType_(4)  # custom, so it can be filled
            box.setBorderWidth_(0)
            box.setCornerRadius_(7)
            box.setTitlePosition_(0)  # no title
            side.addSubview_(box)
            tab = NSButton.buttonWithTitle_target_action_(title, self, "tabClicked:")
            tab.setFrame_(NSMakeRect(20, 0, SIDEBAR - 40, 24))
            tab.setBordered_(False)
            tab.setAlignment_(0)  # left
            tab.setTag_(i)
            side.addSubview_(tab)
            self.tab_rows[key] = (box, tab)
        self.timer_rows = []
        for _i in range(3):  # up to 3 timers, soonest on top
            name_view = label("", NSMakeRect(20, 0, 110, 20), 12, NSColor.secondaryLabelColor())
            time_view = label("", NSMakeRect(130, 0, 60, 20), 13, NSColor.systemTealColor())
            time_view.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(13, 0.4))
            time_view.setAlignment_(2)  # right
            for v in (name_view, time_view):
                v.setHidden_(True)
                side.addSubview_(v)
            self.timer_rows.append((name_view, time_view))
        self.hint = NSTextField.wrappingLabelWithString_(HINTS[self.mode])
        self.hint.setFrame_(NSMakeRect(20, 10, SIDEBAR - 36, 32))
        self.hint.setFont_(NSFont.systemFontOfSize_(11))
        self.hint.setTextColor_(NSColor.tertiaryLabelColor())
        side.addSubview_(self.hint)

    @objc.python_method
    def _build_header(self, root):
        self.dot = label("●", NSMakeRect(0, 0, 20, 24), 15, NSColor.systemOrangeColor())
        self.status = label("Starting", NSMakeRect(0, 0, 300, 24), 17, weight=0.6)
        self.detail = label("Loading Whisper…", NSMakeRect(0, 0, 440, 20), 13, NSColor.secondaryLabelColor(), 0.0)
        for v in (self.dot, self.status, self.detail):
            root.addSubview_(v)
        self.mode_switch = NSSegmentedControl.segmentedControlWithLabels_trackingMode_target_action_(
            ["Hold Option", "Hey Jev"], 0, self, "modeChanged:"
        )
        self.mode_switch.setSelectedSegment_(MODES.index(self.mode))
        root.addSubview_(self.mode_switch)
        self.header_line = NSBox.alloc().initWithFrame_(NSMakeRect(SIDEBAR, DEFAULT_H - HEADER, DEFAULT_W - SIDEBAR, 1))
        self.header_line.setBoxType_(2)  # separator
        root.addSubview_(self.header_line)

    @objc.python_method
    def _page(self, key, title, subtitle):
        """A scrolling page. The scroll view is what gets shown and hidden."""
        page = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        title_view = label(title, NSMakeRect(0, 0, 10, 10), 22, weight=0.6)
        sub_view = NSTextField.wrappingLabelWithString_(subtitle)
        sub_view.setFont_(NSFont.systemFontOfSize_(13))
        sub_view.setTextColor_(NSColor.secondaryLabelColor())
        page.addSubview_(title_view)
        page.addSubview_(sub_view)
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        scroll.setDrawsBackground_(False)
        scroll.setHasVerticalScroller_(True)
        scroll.setHasHorizontalScroller_(False)
        scroll.setAutohidesScrollers_(True)
        scroll.setBorderType_(0)
        scroll.setDocumentView_(page)
        self.page_titles[key] = title_view
        self.page_subs[key] = sub_view
        self.page_docs[key] = page
        self.page_scrolls[key] = scroll
        return page

    @objc.python_method
    def _table(self, page, frame, columns, editable=True):
        scroll = NSScrollView.alloc().initWithFrame_(frame)
        table = NSTableView.alloc().initWithFrame_(scroll.bounds())
        for ident, title, width in columns:
            col = NSTableColumn.alloc().initWithIdentifier_(ident)
            col.setWidth_(width)
            col.headerCell().setStringValue_(title)
            col.setEditable_(editable)
            table.addTableColumn_(col)
        table.setRowHeight_(24)
        table.setUsesAlternatingRowBackgroundColors_(True)
        table.setDataSource_(self)
        table.setDelegate_(self)
        scroll.setDocumentView_(table)
        scroll.setHasVerticalScroller_(True)
        scroll.setHasHorizontalScroller_(False)
        scroll.setAutohidesScrollers_(True)
        scroll.setBorderType_(2)  # bezel
        page.addSubview_(scroll)
        return table, scroll

    @objc.python_method
    def _build_home(self):
        page = self._page("home", "Your Jev stats", "Everything since you started using Jev. Refreshes each time you open this tab.")
        self.stat_cards = []
        self.stat_boxes = []
        for _i in range(6):
            card = NSBox.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
            card.setBoxType_(4)
            card.setBorderWidth_(0)
            card.setCornerRadius_(12)
            card.setFillColor_(NSColor.quaternaryLabelColor().colorWithAlphaComponent_(0.12))
            page.addSubview_(card)
            value = label("", NSMakeRect(0, 0, 10, 10), 30, weight=0.6)
            title = label("", NSMakeRect(0, 0, 10, 10), 13, NSColor.labelColor(), 0.2)
            sub = label("", NSMakeRect(0, 0, 10, 10), 11, NSColor.secondaryLabelColor(), 0.0)
            # Captions wrap onto a second line instead of ending in an ellipsis.
            sub.setLineBreakMode_(0)  # word wrap
            sub.setMaximumNumberOfLines_(2)
            sub.setUsesSingleLineMode_(False)
            cell = sub.cell()
            if cell is not None:
                cell.setWraps_(True)
                cell.setScrollable_(False)
            for v in (value, title, sub):
                page.addSubview_(v)
            self.stat_boxes.append(card)
            self.stat_cards.append((value, title, sub))
        self.most_label = label("Most used", NSMakeRect(0, 0, 10, 10), 14, weight=0.6)
        page.addSubview_(self.most_label)
        self.top_actions = NSTextField.wrappingLabelWithString_("")
        self.top_actions.setFont_(NSFont.systemFontOfSize_(13))
        self.top_actions.setTextColor_(NSColor.secondaryLabelColor())
        page.addSubview_(self.top_actions)
        self.how_label = label("How to use", NSMakeRect(0, 0, 10, 10), 14, weight=0.6)
        page.addSubview_(self.how_label)
        self.how_text = NSTextField.wrappingLabelWithString_(HOW_TO)
        self.how_text.setFont_(NSFont.systemFontOfSize_(13))
        self.how_text.setTextColor_(NSColor.secondaryLabelColor())
        page.addSubview_(self.how_text)
        self.typed = TypedHistory()
        self.home_field = text_field(NSMakeRect(0, 0, 10, 10), PLACEHOLDER)
        self.home_field.setTarget_(self)
        self.home_field.setAction_("homeSubmit:")
        self.home_field.setDelegate_(self)
        self.home_send = button("Send", self, "homeSubmit:", NSMakeRect(0, 0, 10, 10))
        self.home_captures = button("Captures", self, "openCaptures:", NSMakeRect(0, 0, 10, 10))
        self.home_history = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.home_history.setEditable_(False)
        self.home_history.setSelectable_(True)
        self.home_history.setDrawsBackground_(False)
        self.home_history.setFont_(NSFont.systemFontOfSize_(12))
        self.home_history.setTextColor_(NSColor.secondaryLabelColor())
        self.home_history_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.home_history_scroll.setDrawsBackground_(False)
        self.home_history_scroll.setHasVerticalScroller_(True)
        self.home_history_scroll.setAutohidesScrollers_(True)
        self.home_history_scroll.setBorderType_(1)
        self.home_history_scroll.setDocumentView_(self.home_history)
        for view in (self.home_field, self.home_send, self.home_captures, self.home_history_scroll):
            page.addSubview_(view)
        return page

    @objc.python_method
    def _load_stats(self):
        words = dictations = words_today = dictations_today = 0
        today = __import__("time").strftime("%Y-%m-%d")
        if os.path.exists(HISTORY):
            with open(HISTORY, encoding="utf-8") as f:
                for line in f:
                    try:
                        item = json.loads(line)
                    except ValueError:
                        continue
                    n = len(item.get("text", "").split())
                    words += n
                    dictations += 1
                    if item.get("time", "").startswith(today):
                        words_today += n
                        dictations_today += 1
        heard, actions, cost, opened = 0, {}, 0.0, {}
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("> heard:"):
                        heard += 1
                    elif line.startswith("  action: "):
                        parts = line.split()
                        actions[parts[1]] = actions.get(parts[1], 0) + 1
                        if parts[1] == "app_open" and len(parts) > 2:
                            opened[parts[2]] = opened.get(parts[2], 0) + 1
                    elif line.startswith("  jev ") and "$" in line:
                        try:
                            cost += float(line.rsplit("$", 1)[1])
                        except ValueError:
                            pass
        saved = words / TYPING_WPM - words / SPEAKING_WPM
        saved_text = f"{int(saved // 60)} h {int(saved % 60)} min" if saved >= 60 else f"{saved:.0f} min" if saved >= 1 else f"{saved * 60:.0f} sec"
        names = {row[0]: row[1] for row in getattr(self, "apps", [])}
        fav = max(opened, key=opened.get) if opened else None
        cards = (
            (saved_text, "Time saved", f"vs typing at {TYPING_WPM} words a minute"),
            (f"{words:,}", "Words dictated", f"{words_today:,} today"),
            (f"{dictations:,}", "Dictations", f"{dictations_today:,} today"),
            (f"{sum(actions.values()):,}", "Commands done", f"from {heard:,} things she heard"),
            (names.get(fav, fav or "None yet"), "Most opened app", f"opened {opened[fav]} times" if fav else "Say \u201cHey Jev, open Spotify\u201d"),
            (f"${cost:.4f}", "Spent on Jev", "TypeSafe, all time"),
        )
        for (value, title, sub), (v, t, s) in zip(self.stat_cards, cards):
            value.setStringValue_(v)
            title.setStringValue_(t)
            sub.setStringValue_(s)
        top = sorted(actions.items(), key=lambda kv: -kv[1])[:6]
        self.top_actions.setStringValue_("   \u00b7   ".join(f"{ACTION_NAMES.get(a, a.replace('_', ' ').capitalize())}  {n}" for a, n in top)
                                         or "Nothing yet. Say \u201cHey Jev\u201d and a command to get started.")

    @objc.python_method
    def _build_dictionary(self):
        page = self._page("dict", "Dictionary", "Words the transcriber gets wrong. Anything under “heard as” is swapped for the word.")
        self.search = NSSearchField.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.search.setPlaceholderString_("Search")
        self.search.setTarget_(self)
        self.search.setAction_("searchChanged:")
        page.addSubview_(self.search)

        self.new_word = text_field(NSMakeRect(0, 0, 10, 10), "Correct word")
        self.new_alts = text_field(NSMakeRect(0, 0, 10, 10), "Heard as, comma separated")
        self.new_alts.setTarget_(self)
        self.new_alts.setAction_("addWord:")  # Return in the second box adds it
        for v in (self.new_word, self.new_alts):
            page.addSubview_(v)
        self.add_word_button = button("Add word", self, "addWord:", NSMakeRect(0, 0, 10, 10))
        page.addSubview_(self.add_word_button)

        self.table, self.table_scroll = self._table(
            page, NSMakeRect(0, 0, 10, 10),
            (("word", "Word", 170), ("heard", "Heard as (double-click to edit)", 440)),
        )

        self.remove_word_button = button("Remove", self, "removeWord:", NSMakeRect(0, 0, 10, 10))
        page.addSubview_(self.remove_word_button)
        self.dict_message = label("", NSMakeRect(0, 0, 10, 10), 12, NSColor.secondaryLabelColor(), 0.0)
        page.addSubview_(self.dict_message)
        self.vocab = [[w, list(alts)] for w, alts in read_vocab().items()]
        self._filter_vocab()
        return page

    @objc.python_method
    def _build_apps(self):
        page = self._page("apps", "Apps", "What Jev can open, quit, hide, minimise or switch to. Restart Jev after changes (Cmd+Q, reopen).")
        self.new_say = text_field(NSMakeRect(0, 0, 10, 10), "Name you say")
        self.new_app = text_field(NSMakeRect(0, 0, 10, 10), "App name")
        self.new_heard = text_field(NSMakeRect(0, 0, 10, 10), "Heard as (optional)")
        self.new_heard.setTarget_(self)
        self.new_heard.setAction_("addApp:")
        for v in (self.new_say, self.new_app, self.new_heard):
            page.addSubview_(v)
        self.add_app_button = button("Add app", self, "addApp:", NSMakeRect(0, 0, 10, 10))
        page.addSubview_(self.add_app_button)
        self.apps_table, self.apps_scroll = self._table(
            page, NSMakeRect(0, 0, 10, 10),
            (("say", "Name you say", 130), ("app", "App", 170), ("heard", "Heard as (double-click to edit)", 310)),
        )
        self.remove_app_button = button("Remove", self, "removeApp:", NSMakeRect(0, 0, 10, 10))
        page.addSubview_(self.remove_app_button)
        self.apps_message = label("", NSMakeRect(0, 0, 10, 10), 12, NSColor.secondaryLabelColor(), 0.0)
        page.addSubview_(self.apps_message)
        with open(APPS_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        # each row is [name you say (the key), app, heard as, spoken name in replies or None]
        self.apps = [[k, v, [], None] if isinstance(v, str) else [k, v["app"], list(v.get("heard_as", [])), v.get("say")]
                     for k, v in raw.items()]
        return page

    @objc.python_method
    def _build_history(self):
        page = self._page("hist", "Dictation history", "Everything you\u2019ve dictated, newest first. Kept on this Mac only.")
        self.hist_table, self.hist_scroll = self._table(
            page, NSMakeRect(0, 0, 10, 10),
            (("time", "When", 130), ("text", "Text", 480)), editable=False,
        )
        self.copy_button = button("Copy", self, "copyHistory:", NSMakeRect(0, 0, 10, 10))
        page.addSubview_(self.copy_button)
        self.hist_message = label("", NSMakeRect(0, 0, 10, 10), 12, NSColor.secondaryLabelColor(), 0.0)
        page.addSubview_(self.hist_message)
        self.history = []
        return page

    @objc.python_method
    def _build_privacy(self):
        page = self._page("priv", "Privacy", "In Hey Jev mode the mic is always on, but it\u2019s heard on your Mac first. Only this ever leaves it.")
        self.privacy_blocks = []
        for title, body in PRIVACY:
            title_view = label(title, NSMakeRect(0, 0, 10, 10), 14, weight=0.6)
            text = NSTextField.wrappingLabelWithString_(body)
            text.setFont_(NSFont.systemFontOfSize_(13))
            text.setTextColor_(NSColor.secondaryLabelColor())
            page.addSubview_(title_view)
            page.addSubview_(text)
            self.privacy_blocks.append((title_view, text))
        return page

    @objc.python_method
    def _build_settings(self):
        page = self._page("settings", "Settings", "Pick the microphone and the Claude model. Both switch straight away.")
        self.settings_name = label("Microphone", NSMakeRect(0, 0, 10, 10), 14, weight=0.6)
        self.settings_hint = label("Plugged in a new one? Restart Jev to see it here.", NSMakeRect(0, 0, 10, 10), 11,
                                   NSColor.secondaryLabelColor(), 0.0)
        page.addSubview_(self.settings_name)
        page.addSubview_(self.settings_hint)
        self.mic_menu = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(0, 0, 10, 10), False)
        self.mic_menu.setTarget_(self)
        self.mic_menu.setAction_("micChanged:")
        page.addSubview_(self.mic_menu)
        self.mic_message = label("", NSMakeRect(0, 0, 10, 10), 12, NSColor.secondaryLabelColor(), 0.0)
        page.addSubview_(self.mic_message)
        self.model_name = label("Claude model", NSMakeRect(0, 0, 10, 10), 14, weight=0.6)
        self.model_hint = label("Questions and Ask Jev. Blank keeps Claude Haiku 5.5.", NSMakeRect(0, 0, 10, 10), 11,
                                NSColor.secondaryLabelColor(), 0.0)
        page.addSubview_(self.model_name)
        page.addSubview_(self.model_hint)
        self.model_field = text_field(NSMakeRect(0, 0, 10, 10), CLAUDE_MODEL)
        self.model_field.setDelegate_(self)
        page.addSubview_(self.model_field)
        self._load_model()
        self.mini_name = label("Mini bar", NSMakeRect(0, 0, 10, 10), 14, weight=0.6)
        self.mini_hint = label("On when this window is minimized or closed. Esc hides it.", NSMakeRect(0, 0, 10, 10), 11,
                               NSColor.secondaryLabelColor(), 0.0)
        page.addSubview_(self.mini_name)
        page.addSubview_(self.mini_hint)
        self.mini_toggle = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.mini_toggle.setButtonType_(3)  # switch
        self.mini_toggle.setTitle_("Show the mini bar")
        self.mini_toggle.setTarget_(self)
        self.mini_toggle.setAction_("miniBarChanged:")
        self.mini_toggle.setState_(1 if self.bar.enabled else 0)
        page.addSubview_(self.mini_toggle)
        self.update_name = label("Updates", NSMakeRect(0, 0, 10, 10), 14, weight=0.6)
        self.update_hint = label("Checks henryklunaris/hey-jev. Nothing is downloaded.", NSMakeRect(0, 0, 10, 10), 11,
                                 NSColor.secondaryLabelColor(), 0.0)
        page.addSubview_(self.update_name)
        page.addSubview_(self.update_hint)
        self.update_button = button("Check for updates", self, "checkForUpdates:", NSMakeRect(0, 0, 10, 10))
        page.addSubview_(self.update_button)
        return page

    @objc.python_method
    def _load_mics(self):
        try:
            import sounddevice as sd
            names = list(dict.fromkeys(d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0))
            default = sd.query_devices(kind="input")["name"]
        except Exception:
            names, default = [], "none found"
        self.mic_menu.removeAllItems()
        self.mic_menu.addItemWithTitle_(f"System default ({default})")
        self.mic_menu.addItemsWithTitles_(names)
        if self.mic in names:
            self.mic_menu.selectItemWithTitle_(self.mic)
            self.mic_message.setStringValue_(f"Now using: {self.mic}")
        else:
            self.mic_menu.selectItemAtIndex_(0)
            gone = f"{self.mic} isn’t plugged in, so " if self.mic else ""
            self.mic_message.setStringValue_(f"{gone}Now using: {default}")

    def micChanged_(self, sender):
        self.mic = "" if sender.indexOfSelectedItem() == 0 else str(sender.titleOfSelectedItem())
        NSUserDefaults.standardUserDefaults().setObject_forKey_(self.mic, "mic")
        self.controls.put(("mic", self.mic))
        self._load_mics()

    @objc.python_method
    def _load_model(self):
        saved = " ".join(str(NSUserDefaults.standardUserDefaults().stringForKey_(MODEL_PREF) or "").split())
        if saved == CLAUDE_MODEL:
            saved = ""
        self.model_field.setStringValue_(saved)

    @objc.python_method
    def _save_model(self):
        raw = " ".join(str(self.model_field.stringValue() or "").split())
        if raw == CLAUDE_MODEL:
            raw = ""
        NSUserDefaults.standardUserDefaults().setObject_forKey_(raw, MODEL_PREF)

    @objc.python_method
    def _build_keys(self):
        page = self._page("keys", "Keys", "Saved in your Mac Keychain. A key in .env wins over these. Existing keys stay hidden.")
        self.key_fields = {}
        self.key_rows = []
        for title, key_name, use in KEY_ROWS:
            title_view = label(title, NSMakeRect(0, 0, 10, 10), 14, weight=0.6)
            use_view = label(use, NSMakeRect(0, 0, 10, 10), 11, NSColor.secondaryLabelColor(), 0.0)
            placeholder = "Already configured" if get_secret(key_name) else ("Optional" if key_name in OPTIONAL else "Paste key")
            field = text_field(NSMakeRect(0, 0, 10, 10), placeholder, secure=True)
            for view in (title_view, use_view, field):
                page.addSubview_(view)
            self.key_fields[key_name] = field
            self.key_rows.append((title_view, use_view, field))
        self.save_keys_button = button("Save keys", self, "saveSettings:", NSMakeRect(0, 0, 10, 10))
        page.addSubview_(self.save_keys_button)
        self.settings_message = label("", NSMakeRect(0, 0, 10, 10), 12, NSColor.systemRedColor(), 0.0)
        page.addSubview_(self.settings_message)
        return page

    @objc.python_method
    def _place_main_window(self):
        """Center on first launch, and again when the saved frame is offscreen or the uncentered default.

        The window is created at (0, 0). AppKit then nudges it to the visible
        frame's bottom-left (on a MacBook Air that was "0 70 720 460") and
        frame autosave can store that before anyone centers it. A frame the
        user actually moved or resized is left where they put it.
        """
        screens = []
        for screen in NSScreen.screens() or []:
            rect = screen.visibleFrame()
            screens.append((float(rect.origin.x), float(rect.origin.y),
                            float(rect.size.width), float(rect.size.height)))
        self.panel.center()
        restored = bool(self.panel.setFrameAutosaveName_(FRAME_AUTOSAVE_NAME))
        rect = self.panel.frame()
        current = (float(rect.origin.x), float(rect.origin.y),
                   float(rect.size.width), float(rect.size.height))
        if not frame_is_usable(current, screens):
            self.panel.center()
            self.panel.saveFrameUsingName_(FRAME_AUTOSAVE_NAME)
        elif not restored:
            self.panel.saveFrameUsingName_(FRAME_AUTOSAVE_NAME)

    @objc.python_method
    def _layout_window(self):
        """Reflow every tab to the current content size. Safe to call during a live resize."""
        if not getattr(self, "page_scrolls", None):
            return
        size = self.panel.contentView().frame().size
        spec = layout_window(
            size.width, size.height, how_to=HOW_TO, privacy=tuple(body for _title, body in PRIVACY),
        )
        chrome = spec["chrome"]
        _place(self.sidebar, chrome["sidebar"])
        _place(self.backdrop, chrome["backdrop"])
        _place(self.dot, chrome["dot"])
        _place(self.status, chrome["status"])
        _place(self.detail, chrome["detail"])
        _place(self.mode_switch, chrome["mode"])
        _place(self.header_line, chrome["separator"])
        side = spec["sidebar"]
        _place(self.sidebar_title, side["title"])
        _place(self.hint, side["hint"])
        for (key, _title), frames in zip(TABS, side["tabs"]):
            box, tab = self.tab_rows[key]
            _place(box, frames[0])
            _place(tab, frames[1])
        for views, frames in zip(self.timer_rows, side["timers"]):
            _place(views[0], frames[0])
            _place(views[1], frames[1])
        for key, page in spec_pages(spec):
            self._place_page(key, chrome["page_frame"], page)

    @objc.python_method
    def _place_page(self, key, frame, page):
        scroll = self.page_scrolls[key]
        offset = _scroll_from_top(scroll)
        _place(scroll, frame)
        _place(self.page_docs[key], page["document"])
        _place(self.page_titles[key], page["title"])
        _place(self.page_subs[key], page["subtitle"])
        if key == "home":
            for box, card in zip(self.stat_boxes, page["cards"]):
                _place(box, card["box"])
            for (value, title, sub), card in zip(self.stat_cards, page["cards"]):
                _place(value, card["value"])
                _place(title, card["title"])
                _place(sub, card["sub"])
                value.setFont_(NSFont.systemFontOfSize_weight_(card["value_font"], 0.6))
                sub.setFont_(NSFont.systemFontOfSize_(card["sub_font"]))
            _place(self.most_label, page["most_label"])
            _place(self.top_actions, page["top_actions"])
            _place(self.how_label, page["how_label"])
            _place(self.how_text, page["how"])
            _place(self.home_field, page["composer"])
            _place(self.home_send, page["composer_send"])
            _place(self.home_captures, page["composer_folder"])
            _place(self.home_history_scroll, page["history"])
            self.home_history.setFrame_(NSMakeRect(0, 0, page["history"][2], max(page["history"][3], 40)))
        elif key == "dict":
            _place(self.search, page["search"])
            _place(self.new_word, page["fields"][0])
            _place(self.new_alts, page["fields"][1])
            _place(self.add_word_button, page["button"])
            _place_table(self.table_scroll, page["table"], self.table, page["columns"])
            _place(self.remove_word_button, page["remove"])
            _place(self.dict_message, page["message"])
        elif key == "apps":
            for view, rect in zip((self.new_say, self.new_app, self.new_heard), page["fields"]):
                _place(view, rect)
            _place(self.add_app_button, page["button"])
            _place_table(self.apps_scroll, page["table"], self.apps_table, page["columns"])
            _place(self.remove_app_button, page["remove"])
            _place(self.apps_message, page["message"])
        elif key == "hist":
            _place_table(self.hist_scroll, page["table"], self.hist_table, page["columns"])
            _place(self.copy_button, page["remove"])
            _place(self.hist_message, page["message"])
        elif key == "priv":
            for (title, body), frames in zip(self.privacy_blocks, page["blocks"]):
                _place(title, frames[0])
                _place(body, frames[1])
        elif key == "settings":
            _place(self.settings_name, page["name"])
            _place(self.settings_hint, page["hint"])
            _place(self.mic_menu, page["popup"])
            _place(self.mic_message, page["message"])
            _place(self.model_name, page["model_name"])
            _place(self.model_hint, page["model_hint"])
            _place(self.model_field, page["model_field"])
            _place(self.mini_name, page["mini_name"])
            _place(self.mini_hint, page["mini_hint"])
            _place(self.mini_toggle, page["mini_toggle"])
            _place(self.update_name, page["update_name"])
            _place(self.update_hint, page["update_hint"])
            _place(self.update_button, page["update_button"])
        elif key == "keys":
            for views, frames in zip(self.key_rows, page["rows"]):
                for view, rect in zip(views, frames):
                    _place(view, rect)
            _place(self.save_keys_button, page["save"])
            _place(self.settings_message, page["message"])
        _restore_scroll_from_top(scroll, offset)

    # ------------------------------------------------------------------ tabs
    def tabClicked_(self, sender):
        self._select_tab(TABS[sender.tag()][0])

    @objc.python_method
    def _select_tab(self, key):
        if key == "hist":
            self._load_history()
        if key == "home":
            self._load_stats()
        if key == "settings":
            self._load_mics()
            self._load_model()
        for name, page in self.pages.items():
            page.setHidden_(name != key)
        for name, (box, tab) in self.tab_rows.items():
            on = name == key
            box.setFillColor_(NSColor.quaternaryLabelColor() if on else NSColor.clearColor())
            tab.setFont_(NSFont.systemFontOfSize_weight_(13, 0.5 if on else 0.0))

    def showSettings_(self, _sender):
        self.showMain_(None)
        self._select_tab("keys")

    # ------------------------------------------------------------------ dictionary
    @objc.python_method
    def _filter_vocab(self):
        q = self.search.stringValue().strip().lower()
        self.visible = [i for i, (w, alts) in enumerate(self.vocab)
                        if not q or q in w.lower() or any(q in a.lower() for a in alts)]
        self.table.reloadData()

    @objc.python_method
    def _save_vocab(self, message):
        try:
            save_vocab({w: alts for w, alts in self.vocab})
            self.dict_message.setStringValue_(message)
        except Exception as exc:
            self.dict_message.setStringValue_(f"Couldn't save: {exc}")
        self._filter_vocab()

    def numberOfRowsInTableView_(self, table):
        if table == getattr(self, "apps_table", None):
            return len(self.apps)
        if table == getattr(self, "hist_table", None):
            return len(self.history)
        return len(getattr(self, "visible", []))

    def tableView_objectValueForTableColumn_row_(self, table, column, row):
        ident = column.identifier()
        if table == getattr(self, "apps_table", None):
            key, app, heard, _ = self.apps[row]
            return {"say": key.replace("_", " "), "app": app}.get(ident, ", ".join(heard))
        if table == getattr(self, "hist_table", None):
            return self.history[row][ident]
        word, alts = self.vocab[self.visible[row]]
        return word if ident == "word" else ", ".join(alts)

    def tableView_setObjectValue_forTableColumn_row_(self, table, value, column, row):
        value = str(value or "").strip()
        if table == getattr(self, "apps_table", None):
            entry, ident = self.apps[row], column.identifier()
            if ident == "heard":
                entry[2] = [a.strip() for a in value.split(",") if a.strip()]
            elif ident == "say" and app_key(value):
                entry[0] = app_key(value)
            elif ident == "app" and value:
                entry[1] = value
            self._save_apps("Saved, restart Jev to use it")
            return
        entry = self.vocab[self.visible[row]]
        if column.identifier() == "word":
            if value:
                entry[0] = value
        else:
            entry[1] = [a.strip() for a in value.split(",") if a.strip()]
        self._save_vocab("Saved, used straight away")

    def searchChanged_(self, _sender):
        self._filter_vocab()

    def addWord_(self, _sender):
        word = self.new_word.stringValue().strip()
        alts = [a.strip() for a in self.new_alts.stringValue().split(",") if a.strip()]
        if not word or not alts:
            self.dict_message.setStringValue_("Add the word and at least one way it gets misheard")
            return
        for entry in self.vocab:
            if entry[0].lower() == word.lower():  # already there, just add the new spellings
                entry[1] += [a for a in alts if a.lower() not in (x.lower() for x in entry[1])]
                break
        else:
            self.vocab.insert(0, [word, alts])
        self.new_word.setStringValue_("")
        self.new_alts.setStringValue_("")
        self.search.setStringValue_("")
        self._save_vocab(f"Added {word}, used straight away")
        self.panel.makeFirstResponder_(self.new_word)

    def removeWord_(self, _sender):
        row = self.table.selectedRow()
        if row < 0:
            self.dict_message.setStringValue_("Pick a word in the list first")
            return
        word = self.vocab.pop(self.visible[row])[0]
        self._save_vocab(f"Removed {word}")

    # ------------------------------------------------------------------ apps
    @objc.python_method
    def _save_apps(self, message):
        lines = []
        for key, app, heard, say in self.apps:
            if heard or say:
                value = {"app": app, **({"say": say} if say else {}), **({"heard_as": heard} if heard else {})}
            else:
                value = app
            lines.append(f"  {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)}")
        try:
            with open(APPS_FILE, "w", encoding="utf-8") as f:
                f.write("{\n" + ",\n".join(lines) + "\n}\n")  # one app per line, like the file you'd write by hand
            self.apps_message.setStringValue_(message)
        except Exception as exc:
            self.apps_message.setStringValue_(f"Couldn't save: {exc}")
        self.apps_table.reloadData()

    def addApp_(self, _sender):
        say, app = self.new_say.stringValue().strip(), self.new_app.stringValue().strip()
        heard = [a.strip() for a in self.new_heard.stringValue().split(",") if a.strip()]
        if not say or not app:
            self.apps_message.setStringValue_("Add the name you say and the app\u2019s name")
            return
        key = app_key(say)
        if any(row[0] == key for row in self.apps):
            self.apps_message.setStringValue_(f"{say} is already in the list")
            return
        self.apps.append([key, app, heard, None])
        for v in (self.new_say, self.new_app, self.new_heard):
            v.setStringValue_("")
        self._save_apps(f"Added {say}, restart Jev to use it")
        self.panel.makeFirstResponder_(self.new_say)

    def removeApp_(self, _sender):
        row = self.apps_table.selectedRow()
        if row < 0:
            self.apps_message.setStringValue_("Pick an app in the list first")
            return
        name = self.apps.pop(row)[0].replace("_", " ")
        self._save_apps(f"Removed {name}, restart Jev to finish")

    # ------------------------------------------------------------------ history
    @objc.python_method
    def _load_history(self):
        self.history = []
        if os.path.exists(HISTORY):
            with open(HISTORY, encoding="utf-8") as f:
                for line in f:
                    try:
                        item = json.loads(line)
                        self.history.append({"time": item["time"][:16], "text": item["text"]})
                    except (ValueError, KeyError):
                        continue  # skip a half-written line
        self.history.reverse()
        self.hist_table.reloadData()
        self.hist_message.setStringValue_("" if self.history else "Nothing yet. Say \u201cHey Jev, transcribe\u201d to start.")

    def copyHistory_(self, _sender):
        row = self.hist_table.selectedRow()
        if row < 0:
            self.hist_message.setStringValue_("Pick one in the list first")
            return
        board = NSPasteboard.generalPasteboard()
        board.clearContents()
        board.setString_forType_(self.history[row]["text"], NSPasteboardTypeString)
        self.hist_message.setStringValue_("Copied")

    # ------------------------------------------------------------------ keys
    def saveSettings_(self, _sender):
        try:
            for key_name in KEY_NAMES:
                value = self.key_fields[key_name].stringValue()
                if value:
                    save_secret(key_name, value)
                    self.key_fields[key_name].setStringValue_("")
                    self.key_fields[key_name].setPlaceholderString_("Already configured")
            still_missing = missing_secrets()
            if still_missing:
                names = ", ".join(name.replace("_API_KEY", "").replace("_", " ").title() for name in still_missing)
                self.settings_message.setTextColor_(NSColor.systemRedColor())
                self.settings_message.setStringValue_(f"Still needed: {names}")
                return
            from siri import reload_keys
            reload_keys()
            self.settings_message.setTextColor_(NSColor.secondaryLabelColor())
            self.settings_message.setStringValue_("Saved")
            self._start_worker()
        except Exception as exc:
            self.settings_message.setTextColor_(NSColor.systemRedColor())
            self.settings_message.setStringValue_(str(exc))

    # ------------------------------------------------------------------ assistant
    @objc.python_method
    def _global_flags_changed(self, event):
        self._handle_flags(event)

    @objc.python_method
    def _local_flags_changed(self, event):
        self._handle_flags(event)
        return event

    @objc.python_method
    def _local_key(self, event):
        if type_focus_hotkey(event.keyCode(), event.modifierFlags()):
            self.focusTypeField_(None)
            return None

        if event.keyCode() == 53:
            if self._hint_open:
                self._close_hint()
                return None
            if self._result_open:
                self._close_result_panel()
                return None
            if self._action_menu_open:
                self._close_action_menu()
                return None
            choices = getattr(self, "choice_panel", None)
            if choices is not None and choices.isVisible():
                self._close_capture_choices()
                return None
            panel = getattr(self, "mini_panel", None)
            if panel is not None and panel.isKeyWindow():
                self.miniDismiss_(None)
                return None
        if getattr(self, "ptt", None) is not None and self.ptt.on_key(event.keyCode(), time.monotonic()) == "cancel":
            self._cancel_ptt()
            return None
        return event

    def _global_type_key(self, event):
        if event.keyCode() == 53 and self._hint_open:
            self._close_hint()  # PR 5a: Esc closes the hint even while Chrome has focus
        if event.keyCode() == 53 and self._action_menu_open:
            self._close_action_menu()  # PR 5a: Esc closes the action menu even while another app is active
        flags = event.modifierFlags()
        if control_option_command_held(flags) and not event.isARepeat():
            # Diagnostic: proves the global monitor receives chords from other apps. Key code and flags only.
            print("  global key: keyCode={0} flags=0x{1:x} control+option+command".format(
                event.keyCode(), int(flags)))
        if type_focus_hotkey(event.keyCode(), event.modifierFlags()):
            self.performSelectorOnMainThread_withObject_waitUntilDone_("focusTypeField:", None, False)
            return
        if getattr(self, "ptt", None) is not None and self.ptt.on_key(event.keyCode(), time.monotonic()) == "cancel":
            self._cancel_ptt()

    @objc.python_method
    def _handle_flags(self, event):
        ptt = getattr(self, "ptt", None)
        if ptt is None:
            return
        token = ptt.on_flags(event.keyCode(), event.modifierFlags(), time.monotonic())
        if not token:
            return
        self.controls.put(token)
        is_down = token == "press"
        if is_down != self.option_down:
            self.option_down = is_down
            if hasattr(self, "pill"):
                self.pill.option_changed(is_down)
                self._apply_mic_tint()
        self._sync_level_meter(is_down or self._is_listening())

    @objc.python_method
    def _cancel_ptt(self):
        """A typing key inside the interrupt window: release the hold and drop the audio."""
        self.option_down = False
        if hasattr(self, "pill"):
            self.pill.option_changed(False)
            self._apply_mic_tint()
        self._sync_level_meter(False)
        self.controls.put("discard")
        self.controls.put("release")

    @objc.python_method
    def _release_ptt(self, token):
        if token != "release":
            return
        self.option_down = False
        self.controls.put(token)
        if hasattr(self, "pill"):
            self.pill.option_changed(False)
            self._apply_mic_tint()
        self._sync_level_meter(False)

    @objc.python_method
    def _force_ptt_release(self, reason):
        ptt = getattr(self, "ptt", None)
        if ptt is None:
            return
        token = ptt.force_release(reason)
        if token:
            self._release_ptt(token)

    def workspaceWillSleep_(self, _notification):
        self._force_ptt_release("sleep")

    def activeSpaceDidChange_(self, _notification):
        self._force_ptt_release("space")

    @objc.python_method
    def _accessibility_trusted(self):
        """False only when the Accessibility check itself says so.

        A missing binding is not a failed check. The global monitor returning
        None is the other signal, handled by the caller.
        """
        try:
            from ApplicationServices import AXIsProcessTrusted
        except Exception:
            return True
        try:
            return bool(AXIsProcessTrusted())
        except Exception:
            return True

    @objc.python_method
    def _start_worker(self):
        if self.worker_started:
            return
        self.worker_started = True
        threading.Thread(target=self._run_assistant, daemon=True).start()

    @objc.python_method
    def _run_assistant(self):
        from siri import run_voice_assistant
        try:
            run_voice_assistant(self.notify, self.controls, self.mode, self.mic)
        except Exception as exc:
            self.notify("Something went wrong", str(exc))

    @objc.python_method
    def _add_window_menu(self):
        item = NSMenuItem.alloc().init()
        NSApp.mainMenu().addItem_(item)
        menu = NSMenu.alloc().initWithTitle_("Window")
        menu.addItemWithTitle_action_keyEquivalent_("Minimize", "performMiniaturize:", "m")
        self.on_top_item = menu.addItemWithTitle_action_keyEquivalent_("Keep on Top", "toggleOnTop:", "t")
        self.on_top_item.setTarget_(self)
        self.on_top_item.setState_(1 if self.on_top else 0)
        menu.addItemWithTitle_action_keyEquivalent_("Show Hey Jev", "showMain:", "1").setTarget_(self)
        type_item = menu.addItemWithTitle_action_keyEquivalent_("Type to Jev\u2026", "focusTypeField:", "j")
        type_item.setKeyEquivalentModifierMask_(NSEventModifierFlagControl | NSEventModifierFlagOption)
        type_item.setTarget_(self)
        menu.addItemWithTitle_action_keyEquivalent_("Hide Mini Bar", "hideMiniBar:", "").setTarget_(self)
        self.zoe_item = menu.addItemWithTitle_action_keyEquivalent_("Zoe Mode", "zoeModeMenu:", "")
        self.zoe_item.setTarget_(self)
        self.peek_item = menu.addItemWithTitle_action_keyEquivalent_("Tuck Jev into the edge", "peekDockMenu:", "")
        self.peek_item.setTarget_(self)
        self.peek_item.setState_(1 if peek_enabled_from_pref(NSUserDefaults.standardUserDefaults().objectForKey_(PEEK_PREF_KEY)) else 0)
        menu.addItemWithTitle_action_keyEquivalent_("Reset Mini Bar Position", "resetMiniBarPosition:", "").setTarget_(self)
        menu.addItemWithTitle_action_keyEquivalent_("Reset Mini Bar Size", "resetMiniBarSize:", "").setTarget_(self)
        # Magic wand (PR 4): Command-W while Jev is the active app. A menu key equivalent only fires there, so it
        # never takes Command-W from other apps. It is not a global hotkey, because Command-W closes windows everywhere.
        wand = menu.addItemWithTitle_action_keyEquivalent_("Capture Area", "captureAreaWand:", "w")
        wand.setKeyEquivalentModifierMask_(NSEventModifierFlagCommand)
        wand.setImage_(NSImage.imageWithSystemSymbolName_accessibilityDescription_("wand.and.stars", "Capture Area"))
        wand.setTarget_(self)
        item.setSubmenu_(menu)
        NSApp.setWindowsMenu_(menu)

    @objc.python_method
    def _wire_update_menu(self):
        menu = NSApp.mainMenu()
        app_item = menu.itemAtIndex_(0) if menu is not None and menu.numberOfItems() else None
        submenu = app_item.submenu() if app_item is not None else None
        if submenu is None:
            return
        found = submenu.itemWithTitle_("Check for Updates\u2026")
        if found is not None:
            found.setTarget_(self)

    @objc.python_method
    def _area_hotkey_pressed(self):
        print("  area hotkey fired: control+option+command+W")
        self.captureAreaWand_(None)

    def captureAreaWand_(self, _sender):
        """Command-W: the same area capture the orb menu runs today. The crosshair appears, and the usual choices follow."""
        threading.Thread(target=self._capture_for_bar, args=("area",), daemon=True).start()

    def toggleOnTop_(self, _sender):
        self.on_top = not self.on_top
        NSUserDefaults.standardUserDefaults().setBool_forKey_(self.on_top, "keep_on_top")
        self.panel.setLevel_(FLOATING if self.on_top else NORMAL)
        self.on_top_item.setState_(1 if self.on_top else 0)

    def showMain_(self, _sender):
        self._main_closing = False
        self.panel.deminiaturize_(None)
        self.panel.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        self._sync_mini_bar()

    def hideMiniBar_(self, _sender):
        self.bar.dismiss()
        self._apply_bar_visibility()

    def resetMiniBarPosition_(self, _sender):
        """Bottom-center of the main screen, at the default size, remembered."""
        panel = getattr(self, "mini_panel", None)
        if panel is None:
            return
        x, y = reset_origin(self._visible_screens())
        w, h = default_size()
        self._expanded_origin = (x, y)
        self._expanded_size = (w, h)
        self._suppress_size_save = True
        try:
            panel.setFrame_display_(NSMakeRect(x, y, w, h), True)
            self.layoutMiniBar_(self)
        finally:
            self._suppress_size_save = False
        self._pill_frame_collapsed = False
        defaults = NSUserDefaults.standardUserDefaults()
        defaults.setObject_forKey_(format_origin(x, y), ORIGIN_KEY)
        defaults.setObject_forKey_(format_size(w, h), SIZE_KEY)
        self._apply_pill_presentation()

    def resetMiniBarSize_(self, _sender):
        """Default width and height. The pill stays where it was dragged."""
        panel = getattr(self, "mini_panel", None)
        if panel is None:
            return
        frame = panel.frame()
        w, h = default_size()
        if getattr(self, "pillCollapsed", False):
            right = float(frame.origin.x) + float(frame.size.width)
            center_y = float(frame.origin.y) + float(frame.size.height) / 2.0
            self._expanded_size = (w, h)
            self._expanded_origin = (right - w, center_y - (h / 2.0))
            NSUserDefaults.standardUserDefaults().setObject_forKey_(format_size(w, h), SIZE_KEY)
            return
        panel.setFrame_display_(NSMakeRect(float(frame.origin.x), float(frame.origin.y), w, h), True)
        self.layoutMiniBar_(self)
        self._expanded_origin = (float(frame.origin.x), float(frame.origin.y))
        self._expanded_size = (w, h)
        self._pill_frame_collapsed = False
        NSUserDefaults.standardUserDefaults().setObject_forKey_(format_size(w, h), SIZE_KEY)

    def miniBarChanged_(self, sender):
        enabled = sender.state() == 1
        NSUserDefaults.standardUserDefaults().setBool_forKey_(enabled, PREF_KEY)
        self.bar.set_enabled(enabled)
        self._sync_mini_bar()

    @objc.python_method
    def _build_mini_bar(self):
        """Always-on-top pill. Nonactivating until the field is clicked.

        Showing it does not steal the keyboard or raise the main window. A click
        in the field, or Control-Option-J, makes this panel key. It never becomes
        the main window. Return and Esc give the keyboard back.
        """
        self.pill_keys = PillKeyFocus()
        self.pill = PillPresentation()
        self.pillCollapsed = False
        self._pill_frame_collapsed = False
        self._suppress_size_save = False
        size = remembered_size(NSUserDefaults.standardUserDefaults().stringForKey_(SIZE_KEY))
        self._expanded_size = size
        self._expanded_origin = (0.0, 0.0)
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        self.mini_panel = KeyablePanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, size[0], size[1]), style, NSBackingStoreBuffered, False
        )
        self.mini_panel.setLevel_(BAR_LEVEL)
        self.mini_panel.setOpaque_(False)
        self.mini_panel.setBackgroundColor_(NSColor.clearColor())
        self.mini_panel.setHasShadow_(True)
        self.mini_panel.setFloatingPanel_(True)
        self.mini_panel.setHidesOnDeactivate_(False)
        self.mini_panel.setBecomesKeyOnlyIfNeeded_(PILL_BECOMES_KEY_ONLY_IF_NEEDED)
        self.mini_panel.setMovableByWindowBackground_(True)
        # Every Space, including over full-screen apps. The numeric mask matches
        # these AppKit flags; Stationary stops the pill hopping between Spaces.
        self.mini_panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
            | NSWindowCollectionBehaviorStationary
        )
        if BAR_COLLECTION != (
            int(NSWindowCollectionBehaviorCanJoinAllSpaces)
            | int(NSWindowCollectionBehaviorFullScreenAuxiliary)
            | int(NSWindowCollectionBehaviorStationary)
        ):
            self.mini_panel.setCollectionBehavior_(BAR_COLLECTION)
        self.mini_panel.setReleasedWhenClosed_(False)
        self.mini_panel.setRestorable_(False)
        # No forced Dark Aqua. Label colors and the glass follow light and dark.
        self.mini_panel.setDelegate_(self)
        root = MiniBarBackground.alloc().initWithFrame_(NSMakeRect(0, 0, size[0], size[1]))
        root.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self.mini_panel.setContentView_(root)
        self.orb_view = make_orb_view(NSMakeRect(0, 0, 72, 72))
        root.addSubview_(self.orb_view)
        self.greeting_bubble = GreetingBubbleView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.greeting_bubble.setHidden_(True)
        root.addSubview_(self.greeting_bubble)
        self.greeting_label = NSTextField.labelWithString_(greeting_text())
        self.greeting_label.setFont_(NSFont.systemFontOfSize_weight_(13, 0.2))
        self.greeting_label.setTextColor_(NSColor.labelColor())
        self.greeting_label.setHidden_(True)
        root.addSubview_(self.greeting_label)
        self.mini_plus = PillButton.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.mini_plus.setBordered_(False)
        self.mini_plus.setTarget_(self)
        self.mini_plus.setAction_("miniPlus:")
        self.mini_plus.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        self._set_button_symbol(self.mini_plus, "plus", "More")
        root.addSubview_(self.mini_plus)
        self.mini_field = PillTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.mini_field.setCell_(CenteredFieldCell.alloc().initTextCell_(""))
        self.mini_field.setBezeled_(True)
        self.mini_field.setBezelStyle_(1)
        self.mini_field.setDrawsBackground_(True)
        self.mini_field.setFocusRingType_(0)  # default ring, so a click shows the field is focused
        self.mini_field.setEditable_(True)
        self.mini_field.setSelectable_(True)
        self.mini_field.setFont_(NSFont.systemFontOfSize_(14))
        self.mini_field.setTextColor_(NSColor.labelColor())
        self.mini_field.setPlaceholderString_(PLACEHOLDER)
        self.mini_field.setTarget_(self)
        self.mini_field.setAction_("miniSubmit:")
        self.mini_field.setDelegate_(self)
        root.addSubview_(self.mini_field)
        self.mini_mic = HoldMicButton.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.mini_mic.setBordered_(False)
        self.mini_mic.setTarget_(self)
        self.mini_mic.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        self.mini_mic.pillRole = "mic"
        self._set_button_symbol(self.mini_mic, "mic.fill", "Listen")
        root.addSubview_(self.mini_mic)
        self.mini_expand = PillButton.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.mini_expand.setBordered_(False)
        self.mini_expand.setTarget_(self)
        self.mini_expand.setAction_("miniExpandHome:")
        self.mini_expand.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        self.mini_expand.setHidden_(True)
        self._set_button_symbol(self.mini_expand, "arrow.up.left.and.arrow.down.right", "Expand to Jev Home")
        root.addSubview_(self.mini_expand)
        self._popover_refresh_index = 0
        self._popover_history_open = False
        self.popover_history_btn = PopoverChipButton.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.popover_history_btn.configure("", "History", "")
        self.popover_history_btn.setTarget_(self)
        self.popover_history_btn.setAction_("miniToggleHistory:")
        self.popover_history_btn.setHidden_(True)
        root.addSubview_(self.popover_history_btn)
        self.popover_refresh_btn = PopoverChipButton.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.popover_refresh_btn.configure("", "Refresh", "")
        self.popover_refresh_btn.setTarget_(self)
        self.popover_refresh_btn.setAction_("miniRefreshChips:")
        self.popover_refresh_btn.setHidden_(True)
        root.addSubview_(self.popover_refresh_btn)
        self.popover_history = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.popover_history.setEditable_(False)
        self.popover_history.setSelectable_(True)
        self.popover_history.setDrawsBackground_(True)
        self.popover_history.setBackgroundColor_(NSColor.quaternaryLabelColor().colorWithAlphaComponent_(0.12))
        self.popover_history.setFont_(NSFont.systemFontOfSize_(11))
        self.popover_history.setTextColor_(NSColor.secondaryLabelColor())
        self.popover_history_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.popover_history_scroll.setDrawsBackground_(False)
        self.popover_history_scroll.setHasVerticalScroller_(True)
        self.popover_history_scroll.setAutohidesScrollers_(True)
        self.popover_history_scroll.setBorderType_(1)
        self.popover_history_scroll.setDocumentView_(self.popover_history)
        self.popover_history_scroll.setHidden_(True)
        root.addSubview_(self.popover_history_scroll)
        self.popover_chips = []
        for _index in range(4):
            chip = PopoverChipButton.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
            chip.setTarget_(self)
            chip.setHidden_(True)
            root.addSubview_(chip)
            self.popover_chips.append(chip)
        self.mic_level_view = MicLevelView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.mic_level_view.setAmplitude_(0.0)
        root.addSubview_(self.mic_level_view)
        self.rec_label = NSTextField.labelWithString_("")
        self.rec_label.setTextColor_(NSColor.systemRedColor())
        self.rec_label.setFont_(NSFont.systemFontOfSize_weight_(13, 0.6))
        self.rec_label.setHidden_(True)
        root.addSubview_(self.rec_label)
        self.rec_stop = PillButton.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.rec_stop.setBordered_(False)
        self.rec_stop.setTarget_(self)
        self.rec_stop.setAction_("miniStopRecording:")
        self.rec_stop.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        self._set_button_symbol(self.rec_stop, "stop.circle.fill", "Stop Recording")
        self.rec_stop.setHidden_(True)
        root.addSubview_(self.rec_stop)
        self.zoe_label = NSTextField.labelWithString_("")
        self.zoe_label.setFont_(NSFont.systemFontOfSize_weight_(13, 0.6))
        self.zoe_label.setHidden_(True)
        try:
            self.zoe_label.setTextColor_(NSColor.systemPinkColor())
        except Exception:
            self.zoe_label.setTextColor_(NSColor.systemOrangeColor())
        root.addSubview_(self.zoe_label)
        self._mini_mic_held = False
        self._layout_mini_bar(size[0], size[1])
        self._install_pill_chrome()
        self._watch_display_options()
        self._refresh_trailing_symbol()

    @objc.python_method
    def _main_on_screen(self):
        if self.bar.quitting or self._main_closing:
            return False
        return bool(self.panel.isVisible()) and not bool(self.panel.isMiniaturized())

    @objc.python_method
    def _sync_mini_bar(self):
        if not hasattr(self, "bar"):
            return
        self.bar.main_window_changed(self._main_on_screen())
        self._apply_bar_visibility()

    @objc.python_method
    def _apply_bar_visibility(self):
        panel = getattr(self, "mini_panel", None)
        if panel is None:
            return
        if self.bar.should_show():
            if not panel.isVisible():
                self._order_bar_front()
        elif panel.isVisible():
            self._hide_bar()
        self._sync_orb()

    @objc.python_method
    def _hide_bar(self):
        self._peek_disengage(move=False)
        panel = self.mini_panel
        orb = getattr(self, "orb_view", None)
        if orb is not None:
            orb.stop()
        motion = self._pill_flags().get("motion", True)
        if self.bar.quitting or not motion:
            panel.setAlphaValue_(1.0)
            panel.orderOut_(None)
            return

        def done():
            if panel.isVisible():
                panel.orderOut_(None)
            panel.setAlphaValue_(1.0)
            view = panel.contentView()
            layer = view.layer() if view is not None else None
            if layer is not None:
                layer.setOpacity_(1.0)

        self._fade_bar(0.0, done)

    @objc.python_method
    def _fade_bar(self, target, completion):
        """Spring when Quartz can build one. Otherwise a short fade. Reduce Motion never calls this."""
        panel = self.mini_panel
        pending = getattr(self, "_fade_timer", None)
        if pending is not None:
            pending.invalidate()
            self._fade_timer = None
        self._bar_fade_done = None
        try:
            from Quartz import CASpringAnimation
            view = panel.contentView()
            layer = None
            if view is not None:
                view.setWantsLayer_(True)
                layer = view.layer()
            if layer is None:
                raise RuntimeError("no layer")
            anim = CASpringAnimation.animationWithKeyPath_("opacity")
            anim.setFromValue_(float(panel.alphaValue()))
            anim.setToValue_(float(target))
            anim.setDamping_(20.0)
            anim.setStiffness_(180.0)
            anim.setMass_(1.0)
            duration = min(0.8, max(0.2, float(anim.settlingDuration())))
            anim.setDuration_(duration)
            layer.addAnimation_forKey_(anim, "pillAppear")
            layer.setOpacity_(float(target))
            panel.setAlphaValue_(1.0)
            if completion is not None:
                self._bar_fade_done = completion
                self._fade_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    duration, self, "finishBarFade:", None, False)
            return
        except Exception:
            pass
        NSAnimationContext.beginGrouping()
        ctx = NSAnimationContext.currentContext()
        ctx.setDuration_(0.45)
        if completion is not None:
            ctx.setCompletionHandler_(completion)
        panel.animator().setAlphaValue_(float(target))
        NSAnimationContext.endGrouping()

    def finishBarFade_(self, _timer):
        self._fade_timer = None
        done = getattr(self, "_bar_fade_done", None)
        self._bar_fade_done = None
        if done is not None:
            done()

    @objc.python_method
    def _visible_screens(self):
        """Visible frames, main screen first, then any other display."""
        main = NSScreen.mainScreen()
        screens = list(NSScreen.screens() or [])
        if main is not None:
            screens = [main] + [screen for screen in screens if screen != main]
        frames = []
        for screen in screens:
            rect = screen.visibleFrame()
            frames.append((float(rect.origin.x), float(rect.origin.y),
                           float(rect.size.width), float(rect.size.height)))
        return frames

    @objc.python_method
    def _finalize_mini_bar_drag(self, window):
        """Clamp and snap when a drag ends. Dragging never opens the typing pill."""
        self._orb_dragging = False
        self._peek_disengage(move=False)
        frame = window.frame()
        origin = finish_drag(
            (float(frame.origin.x), float(frame.origin.y)),
            (float(frame.size.width), float(frame.size.height)),
            self._visible_screens(),
        )
        window.setFrameOrigin_(NSMakePoint(origin[0], origin[1]))
        self._sync_expanded_from_window()
        saved = getattr(self, "_expanded_origin", None)
        if saved is not None:
            NSUserDefaults.standardUserDefaults().setObject_forKey_(
                format_origin(saved[0], saved[1]), ORIGIN_KEY)
        self._peek_consider()
        # PR 5a (R3): this runs only after a real drag has landed on its snap target. A drop that tucked the orb
        # into the edge does not open the menu.
        if self._peek_edge is None and menu_on_drop(True):
            self._open_action_menu()

    # PR 5a: action menu. A panel beside the orb, fanned out after a drop. Its buttons reuse the post-capture ids.
    @objc.python_method
    def _build_action_menu(self):
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 200, 200), style, NSBackingStoreBuffered, False)
        panel.setLevel_(BAR_LEVEL)
        panel.setFloatingPanel_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setBecomesKeyOnlyIfNeeded_(True)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setCollectionBehavior_(BAR_COLLECTION)
        panel.setReleasedWhenClosed_(False)
        panel.setAccessibilityLabel_("Jev actions")
        self._action_menu_panel = panel
        return panel

    @objc.python_method
    def _fill_action_menu(self, layout):
        panel = self._action_menu_panel
        px, py, pw, ph = layout["panel"]
        panel.setFrame_display_(NSMakeRect(px, py, pw, ph), False)
        scale = float(panel.backingScaleFactor())
        if NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceTransparency():
            content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, pw, ph))
            content.setWantsLayer_(True)
            content.layer().setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.12, 0.96).CGColor())
        else:
            content = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, pw, ph))
            content.setMaterial_(NSVisualEffectMaterialHUDWindow)
            content.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
            content.setState_(NSVisualEffectStateActive)
            content.setWantsLayer_(True)
        # The rounded corners clip the material. contentsScale matches the window on this screen.
        content.layer().setCornerRadius_(MENU_CORNER_RADIUS)
        content.layer().setMasksToBounds_(True)
        content.layer().setContentsScale_(scale)
        panel.setContentView_(content)
        from Quartz import CALayer
        buttons = []
        for row, action in enumerate(orb_action_menu()):
            bx, by, bw, bh = layout["buttons"][row]
            lx, ly, lw, lh = layout["labels"][row]
            x0 = min(bx, lx)
            x1 = max(bx + bw, lx + lw)
            item = ActionMenuButton.alloc().initWithFrame_(NSMakeRect(x0 - px, by - py, x1 - x0, bh))
            item.setWantsLayer_(True)
            item.layer().setContentsScale_(scale)
            circle = CALayer.layer()
            circle.setFrame_(NSMakeRect(bx - x0, 0.0, bw, bh))
            circle.setCornerRadius_(bw / 2.0)
            circle.setContentsScale_(scale)
            circle.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(1.0, MENU_FILL_REST).CGColor())
            item.layer().addSublayer_(circle)
            item.circle_layer = circle
            image = None
            try:
                image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(action["symbol"], action["title"])
            except Exception:
                image = None
            if image is not None:
                icon = NSImageView.alloc().initWithFrame_(NSMakeRect(bx - x0 + 10.0, 10.0, bw - 20.0, bh - 20.0))
                icon.setImage_(image)
                icon.setImageScaling_(NSImageScaleProportionallyUpOrDown)
                icon.setContentTintColor_(NSColor.whiteColor())
                item.addSubview_(icon)
            text = label(action["title"], NSMakeRect(lx - x0, (bh - lh) / 2.0, lw, lh), 13, NSColor.whiteColor(), weight=0.5)
            text.setAlignment_(2 if layout["side"] == "left" else 0)  # labels sit away from the orb
            item.addSubview_(text)
            item.setIdentifier_(action["id"])
            item.pick_target = self
            item.setAccessibilityElement_(True)
            item.setAccessibilityRole_("AXButton")
            item.setAccessibilityLabel_(action["title"])
            item.setToolTip_(action["title"])
            content.addSubview_(item)
            end = (x0 - px + (x1 - x0) / 2.0, by - py + bh / 2.0)
            buttons.append((item, end))
        self._action_menu_buttons = tuple(buttons)

    @objc.python_method
    def _animate_action_menu_button(self, layer, start, end, delay):
        """Scale 0.6 and alpha 0 at the orb's centre, to the slot on CASpring SPRING_MENU_FAN, after `delay` seconds."""
        from Quartz import CABasicAnimation, CACurrentMediaTime, CASpringAnimation
        from Foundation import NSValue
        begin = CACurrentMediaTime() + float(delay)
        stiffness, damping = SPRING_MENU_FAN
        move = CASpringAnimation.animationWithKeyPath_("position")
        move.setStiffness_(stiffness)
        move.setDamping_(damping)
        move.setMass_(1.0)
        move.setFromValue_(NSValue.valueWithPoint_(NSMakePoint(start[0], start[1])))
        move.setToValue_(NSValue.valueWithPoint_(NSMakePoint(end[0], end[1])))
        move.setDuration_(move.settlingDuration())
        move.setBeginTime_(begin)
        move.setFillMode_("backwards")
        grow = CASpringAnimation.animationWithKeyPath_("transform.scale")
        grow.setStiffness_(stiffness)
        grow.setDamping_(damping)
        grow.setMass_(1.0)
        grow.setFromValue_(MENU_FAN_START_SCALE)
        grow.setToValue_(1.0)
        grow.setDuration_(grow.settlingDuration())
        grow.setBeginTime_(begin)
        grow.setFillMode_("backwards")
        fade = CABasicAnimation.animationWithKeyPath_("opacity")
        fade.setFromValue_(0.0)
        fade.setToValue_(1.0)
        fade.setDuration_(0.18)
        fade.setBeginTime_(begin)
        fade.setFillMode_("backwards")
        for anim, key in ((move, "menuFanMove"), (grow, "menuFanScale"), (fade, "menuFanFade")):
            layer.addAnimation_forKey_(anim, key)

    @objc.python_method
    def _open_action_menu(self):
        from AppKit import NSEventMaskLeftMouseDown, NSEventMaskRightMouseDown
        window = getattr(self, "mini_panel", None)
        if window is None or not window.isVisible():
            return
        self._close_action_menu()
        frame = window.frame()
        orb = (float(frame.origin.x), float(frame.origin.y), float(frame.size.width), float(frame.size.height))
        screens = self._visible_screens() or [(0.0, 0.0, 1440.0, 900.0)]
        screen = screen_for_frame(orb, screens) or screens[0]
        layout = menu_layout(orb, screen)
        if self._action_menu_panel is None:
            self._build_action_menu()
        self._fill_action_menu(layout)
        self._action_menu_open = True
        self._action_menu_shown_at = time.time()
        # Clicks in Jev are seen by a local monitor. A click in any other app activates that app, so the
        # workspace notification closes the menu. No global event monitor, so no new permission.
        mask = NSEventMaskLeftMouseDown | NSEventMaskRightMouseDown
        self._action_menu_monitors = (
            NSEvent.addLocalMonitorForEventsMatchingMask_handler_(mask, self._action_menu_mouse_down),
        )
        NSWorkspace.sharedWorkspace().notificationCenter().addObserver_selector_name_object_(
            self, "actionMenuAppActivated:", "NSWorkspaceDidActivateApplicationNotification", None)
        self._action_menu_observing = True
        orb_view = getattr(self, "orb_view", None)
        if orb_view is None or not bool(getattr(orb_view, "reduceMotion", False)):
            px, py = layout["panel"][0], layout["panel"][1]
            start = (orb[0] + orb[2] / 2.0 - px, orb[1] + orb[3] / 2.0 - py)  # the orb's centre, in panel coordinates
            for row, (item, end) in enumerate(self._action_menu_buttons):
                self._animate_action_menu_button(item.layer(), start, end, layout["delays"][row])
        self._action_menu_panel.orderFrontRegardless()

    @objc.python_method
    def _close_action_menu(self):
        """Closes at once: no animation, so a click on an action never waits on the menu."""
        for monitor in self._action_menu_monitors:
            NSEvent.removeMonitor_(monitor)
        self._action_menu_monitors = ()
        if self._action_menu_observing:
            NSWorkspace.sharedWorkspace().notificationCenter().removeObserver_name_object_(
                self, "NSWorkspaceDidActivateApplicationNotification", None)
            self._action_menu_observing = False
        panel = self._action_menu_panel
        if panel is not None and panel.isVisible():
            panel.orderOut_(None)
        self._action_menu_open = False
        self._action_menu_shown_at = 0.0
        self._action_menu_buttons = ()

    @objc.python_method
    def _action_menu_pointer_inside(self):
        panel = self._action_menu_panel
        if panel is None or not panel.isVisible():
            return False
        loc = NSEvent.mouseLocation()
        frame = panel.frame()
        return pointer_inside(
            (float(loc.x), float(loc.y)),
            (float(frame.origin.x), float(frame.origin.y), float(frame.size.width), float(frame.size.height)),
        )

    def _action_menu_mouse_down(self, event):
        """A click in Jev outside the menu closes it. The click still goes on to whatever it hit."""
        if self._action_menu_open and not self._action_menu_pointer_inside():
            self._close_action_menu()
        return event

    def actionMenuAppActivated_(self, _notification):
        """Another app came forward, so the click was away from the menu."""
        if self._action_menu_open:
            self._close_action_menu()

    @objc.python_method
    def _sync_action_menu_dismiss(self):
        if not self._action_menu_open:
            return
        if choice_due(self._action_menu_shown_at, time.time(), self._action_menu_pointer_inside()):
            self._close_action_menu()

    def actionMenuPick_(self, sender):
        ident = "" if sender is None else str(sender.identifier() or "")
        self._close_action_menu()
        if ident:
            threading.Thread(target=self._run_action_menu_capture, args=(ident,), daemon=True).start()

    @objc.python_method
    def _run_action_menu_capture(self, ident):
        """Every menu action starts here, with take_screenshot(mode="area") on the captures book. Off the main thread.

        Esc or a zero-size selection is "cancelled" and does nothing. Each action then runs on its own path. Find Image
        and Copy Image use the same functions as the Jev commands, and none of them opens the Jev window. Ask and the
        two text actions go back to the main thread, because they show a panel.
        """
        print(f"  action menu: {ident} clicked")
        try:
            from commands.captures import BOOK, ask_plan, execute_ask, run_capture_menu, take_screenshot
            print("  action menu: capture started (area)")
            sentence = take_screenshot("area", book=BOOK)
            outcome = capture_outcome(sentence)
            if outcome != "saved":
                print(f"  action menu: capture {outcome}")
                return
            path = str((BOOK.last or {}).get("path") or "")
            print(f"  action menu: capture saved {os.path.basename(path)}")
            if ident == "markup":
                subprocess.run(["open", "-a", "Preview", path], check=False)  # until PR 5b's mark up overlay
                print("  action menu: markup opened in Preview")
                return
            if ident == "share_copy":
                print(f"  action menu: copy image: {run_capture_menu('share_copy', book=BOOK)}")
                return
            if ident == "ask_google":
                # ask_plan + execute_ask: the copy and the Lens open each raise on failure, so no exception = both worked.
                execute_ask(ask_plan("google", "capture", path=path))
                print("  action menu: find image copied and opened Lens")
                self.performSelectorOnMainThread_withObject_waitUntilDone_("findImageHint:", "", False)
                return
        except Exception as exc:
            print(f"  action menu: {ident} failed: {exc}")
            return
        payload = json.dumps({"id": ident, "path": path})
        self.performSelectorOnMainThread_withObject_waitUntilDone_("actionMenuCaptured:", payload, False)

    def actionMenuCaptured_(self, payload):
        try:
            data = json.loads(str(payload))
        except ValueError:
            return
        ident = str(data.get("id") or "")
        if ident in TEXT_ACTIONS:
            self._start_text_action(ident)
            return
        if ident == "ask_jev":
            self._show_capture_choices()  # the usual thumbnail panel, with its question field open
            self._open_choice_question()
            return
        print(f"  action menu: no handler for {ident}")

    # PR 5a: the Find Image hint. The same dark style as the result panel; nonactivating so Chrome keeps focus.
    @objc.python_method
    def _build_hint_panel(self):
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 300, 52), style, NSBackingStoreBuffered, False)
        panel.setLevel_(BAR_LEVEL)
        panel.setFloatingPanel_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setBecomesKeyOnlyIfNeeded_(True)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setCollectionBehavior_(BAR_COLLECTION)
        panel.setReleasedWhenClosed_(False)
        panel.setAccessibilityLabel_("Jev hint")
        self._hint_panel = panel
        return panel

    @objc.python_method
    def _show_hint(self, text):
        if self._hint_panel is None:
            self._build_hint_panel()
        window = getattr(self, "mini_panel", None)
        if window is None:
            return
        frame = window.frame()
        orb = (float(frame.origin.x), float(frame.origin.y), float(frame.size.width), float(frame.size.height))
        screens = self._visible_screens() or [(0.0, 0.0, 1440.0, 900.0)]
        screen = screen_for_frame(orb, screens) or screens[0]
        layout = hint_layout(orb, screen)
        px, py, pw, ph = layout["panel"]
        panel = self._hint_panel
        panel.setFrame_display_(NSMakeRect(px, py, pw, ph), False)
        scale = float(panel.backingScaleFactor())
        if NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceTransparency():
            content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, pw, ph))
            content.setWantsLayer_(True)
            content.layer().setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.12, 0.96).CGColor())
        else:
            content = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, pw, ph))
            content.setMaterial_(NSVisualEffectMaterialHUDWindow)
            content.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
            content.setState_(NSVisualEffectStateActive)
            content.setWantsLayer_(True)
        content.layer().setCornerRadius_(MENU_CORNER_RADIUS)
        content.layer().setMasksToBounds_(True)
        content.layer().setContentsScale_(scale)
        inset = HINT_TEXT_INSET
        body = NSTextField.wrappingLabelWithString_(text)
        body.setFrame_(NSMakeRect(inset, 10.0, pw - 2.0 * inset, ph - 20.0))
        body.setFont_(NSFont.systemFontOfSize_(13))
        body.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.92, 1.0))
        content.addSubview_(body)
        click = HintClickView.alloc().initWithFrame_(NSMakeRect(0, 0, pw, ph))
        click.dismiss_target = self
        content.addSubview_(click)  # on top: a click on the hint dismisses it
        panel.setContentView_(content)
        self._hint_open = True
        self._hint_shown_at = time.time()
        panel.orderFrontRegardless()
        orb_view = getattr(self, "orb_view", None)
        if not bool(getattr(orb_view, "reduceMotion", False)):
            self._animate_result_in(content.layer())

    @objc.python_method
    def _close_hint(self):
        panel = self._hint_panel
        if panel is not None and panel.isVisible():
            panel.orderOut_(None)
        self._hint_open = False
        self._hint_shown_at = 0.0

    def findImageHint_(self, _payload):
        self._show_hint(FIND_IMAGE_HINT)
        print("  action menu: find image hint shown")

    def hintDismiss_(self, _sender):
        self._close_hint()

    @objc.python_method
    def _sync_hint_dismiss(self):
        if self._hint_open and time.time() - self._hint_shown_at >= HINT_SECONDS:
            self._close_hint()

    # PR 5a (extra direction): Summarize and Translate. A dark rounded panel beside the orb, calm fade and scale.
    @objc.python_method
    def _build_result_panel(self):
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 300, 200), style, NSBackingStoreBuffered, False)
        panel.setLevel_(BAR_LEVEL)
        panel.setFloatingPanel_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setBecomesKeyOnlyIfNeeded_(True)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setCollectionBehavior_(BAR_COLLECTION)
        panel.setReleasedWhenClosed_(False)
        panel.setAccessibilityLabel_("Jev result")
        self._result_panel = panel
        return panel

    @objc.python_method
    def _fill_result_panel(self, heading, text):
        panel = self._result_panel
        frames = result_frames(text)
        pw, ph = frames["panel"]
        scale = float(panel.backingScaleFactor())
        if NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceTransparency():
            content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, pw, ph))
            content.setWantsLayer_(True)
            content.layer().setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.12, 0.96).CGColor())
        else:
            content = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, pw, ph))
            content.setMaterial_(NSVisualEffectMaterialHUDWindow)
            content.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
            content.setState_(NSVisualEffectStateActive)
            content.setWantsLayer_(True)
        content.layer().setCornerRadius_(MENU_CORNER_RADIUS)
        content.layer().setMasksToBounds_(True)
        content.layer().setContentsScale_(scale)
        head = label(heading, NSMakeRect(*frames["heading"]), 14, NSColor.whiteColor(), weight=0.8)
        body = NSTextField.wrappingLabelWithString_(text)
        body.setFrame_(NSMakeRect(*frames["body"]))
        body.setFont_(NSFont.systemFontOfSize_(13))
        body.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.86, 1.0))
        copy = result_pill("Copy", frames["copy"], scale, self, "resultCopy:")
        close = result_pill("Close", frames["close"], scale, self, "resultClose:")
        for view in (head, body, copy, close):
            content.addSubview_(view)
        panel.setContentView_(content)

    @objc.python_method
    def _present_result(self, heading, text, animate):
        if self._result_panel is None:
            self._build_result_panel()
        window = getattr(self, "mini_panel", None)
        if window is None:
            return
        frame = window.frame()
        orb = (float(frame.origin.x), float(frame.origin.y), float(frame.size.width), float(frame.size.height))
        screens = self._visible_screens() or [(0.0, 0.0, 1440.0, 900.0)]
        screen = screen_for_frame(orb, screens) or screens[0]
        layout = result_layout(orb, screen, text)
        self._result_heading = heading
        self._result_text = text
        self._fill_result_panel(heading, text)
        px, py, pw, ph = layout["panel"]
        self._result_panel.setFrame_display_(NSMakeRect(px, py, pw, ph), True)
        self._result_open = True
        self._result_panel.orderFrontRegardless()
        orb_view = getattr(self, "orb_view", None)
        if animate and not bool(getattr(orb_view, "reduceMotion", False)):
            self._animate_result_in(self._result_panel.contentView().layer())

    @objc.python_method
    def _animate_result_in(self, layer):
        """Fade in and scale 0.96 to 1 over RESULT_FADE_SECONDS, easeOut. No spring: the result panel stays calm."""
        from Quartz import CABasicAnimation, CAMediaTimingFunction
        grow = CABasicAnimation.animationWithKeyPath_("transform.scale")
        grow.setFromValue_(RESULT_SCALE_FROM)
        grow.setToValue_(1.0)
        grow.setDuration_(RESULT_FADE_SECONDS)
        grow.setTimingFunction_(CAMediaTimingFunction.functionWithName_("easeOut"))
        fade = CABasicAnimation.animationWithKeyPath_("opacity")
        fade.setFromValue_(0.0)
        fade.setToValue_(1.0)
        fade.setDuration_(RESULT_FADE_SECONDS)
        fade.setTimingFunction_(CAMediaTimingFunction.functionWithName_("easeOut"))
        layer.addAnimation_forKey_(grow, "resultScale")
        layer.addAnimation_forKey_(fade, "resultFade")

    @objc.python_method
    def _close_result_panel(self):
        panel = self._result_panel
        if panel is not None and panel.isVisible():
            panel.orderOut_(None)
        self._result_open = False

    def resultClose_(self, _sender):
        self._close_result_panel()

    def resultCopy_(self, _sender):
        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.setString_forType_(self._result_text, NSPasteboardTypeString)
        self._close_result_panel()

    @objc.python_method
    def _start_text_action(self, ident):
        """The capture is saved. Show the panel at once, then ask Jev about the picture on the existing path."""
        heading = TEXT_ACTIONS[ident][0]
        self._present_result(heading, "Reading the capture...", True)
        threading.Thread(target=self._run_text_action, args=(ident,), daemon=True).start()

    @objc.python_method
    def _run_text_action(self, ident):
        _heading, prompt = TEXT_ACTIONS[ident]
        try:
            from commands.captures import ask_jev_from_text
            answer = ask_jev_from_text("ask jev about this", question=prompt)
        except Exception as exc:
            answer = "I couldn't do that."
            print(f"  text action failed: {exc}")
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "resultReady:", json.dumps({"text": str(answer or "")}), False)

    def resultReady_(self, payload):
        try:
            text = str(json.loads(str(payload)).get("text") or "")
        except ValueError:
            return
        if self._result_open:
            self._present_result(self._result_heading, text, False)

    # PR 3b: peek-dock. A snapped orb on a free screen edge tucks most of itself off-screen, and slides back
    # in when the cursor comes near. Reduce Motion fades in place instead of sliding. A tucked orb is never busy.

    @objc.python_method
    def _peek_enabled(self):
        return peek_enabled_from_pref(NSUserDefaults.standardUserDefaults().objectForKey_(PEEK_PREF_KEY))

    @objc.python_method
    def _peek_is_busy(self):
        """Popover, menu, drag, listening, thinking or speaking. Busy keeps the orb out."""
        if not getattr(self, "pillCollapsed", False) or self._orb_dragging:
            return True
        if getattr(self, "_pill_menu_open", False) or self._action_menu_open:
            return True  # PR 5a: a tuck waits while the action menu is open
        pill = getattr(self, "pill", None)
        if pill is not None and pill.busy:
            return True
        status = getattr(self, "status", None)
        text = str(status.stringValue()) if status is not None else "Ready"
        return orb_state(text, bool(getattr(self, "option_down", False))) in ("listening", "thinking", "speaking")

    @objc.python_method
    def _peek_frame_is_not_inset(self):
        """True while a peek is engaged and the window is tucked or moving, so it is not at the saved inset."""
        if self._peek_edge is None:
            return False
        return bool(self._peek_anim is not None or self._peek_fading or not self._peek_showing)

    @objc.python_method
    def _peek_position(self, showing):
        """Window x at the inset (showing) or at the tucked rest, for the current window size."""
        size = self.mini_panel.frame().size
        rest = peek_frame(self._peek_inset, (float(size.width), float(size.height)), self._peek_screen, self._peek_edge)
        return float(self._peek_inset[0]) if showing else float(rest[0])

    @objc.python_method
    def _peek_frame_x(self, default_x):
        """The x the presentation should use: the inset or rest, or wherever a move has got to."""
        if self._peek_edge is None:
            return default_x
        if self._peek_anim is not None or self._peek_fading:
            return float(self.mini_panel.frame().origin.x)
        return self._peek_position(self._peek_showing)

    @objc.python_method
    def _peek_consider(self):
        """Tuck the orb when it sits on an allowed edge, the pref is on, and nothing is busy."""
        if self._peek_edge is not None:
            return
        panel = getattr(self, "mini_panel", None)
        if panel is None or not panel.isVisible() or not self.bar.should_show():
            return
        if not self._peek_enabled() or self._peek_is_busy():
            return
        frame = panel.frame()
        origin = (float(frame.origin.x), float(frame.origin.y))
        size = (float(frame.size.width), float(frame.size.height))
        screens = self._visible_screens()
        screen = screen_for_frame((origin[0], origin[1], size[0], size[1]), screens)
        plan = peek_plan(origin, size, screen, screens)
        if plan is None:
            return
        self._peek_edge = plan[0]
        self._peek_screen = screen
        self._peek_inset = origin  # the snapped inset; never overwritten while tucked
        self._peek_outside = 0.0
        self._peek_latched = True  # the drop may leave the cursor in the hot zone; it must leave before the orb comes back
        self._peek_move(False)

    @objc.python_method
    def _peek_move(self, showing):
        """Slide to the inset (showing) or the rest. Reduce Motion fades in place instead."""
        panel = self.mini_panel
        self._peek_showing = bool(showing)
        self._peek_outside = 0.0
        target_x = self._peek_position(self._peek_showing)
        if not self._pill_flags().get("motion", True):
            self._peek_fade_to(target_x)
            self._peek_ensure_timer(CURSOR_POLL_SECONDS)
            return
        start_x = float(panel.frame().origin.x)
        if abs(start_x - target_x) < 0.01:
            self._peek_anim = None
        else:
            k, c = SPRING_PEEK_IN if showing else SPRING_PEEK_OUT
            self._peek_anim = {"from": start_x, "to": target_x, "k": k, "c": c, "t0": time.monotonic()}
        self._peek_ensure_timer(DRAG_TICK_SECONDS if self._peek_anim is not None else CURSOR_POLL_SECONDS)

    @objc.python_method
    def _peek_fade_to(self, target_x):
        """Reduce Motion: fade out, move, fade back in. Two halves of PEEK_FADE_SECONDS, no sliding."""
        panel = self.mini_panel
        token = object()
        self._peek_fade_token = token
        self._peek_fading = True
        self._peek_anim = None
        half = PEEK_FADE_SECONDS / 2.0
        y = float(self._peek_inset[1])

        def fade(alpha, completion):
            NSAnimationContext.beginGrouping()
            ctx = NSAnimationContext.currentContext()
            ctx.setDuration_(half)
            ctx.setCompletionHandler_(completion)
            panel.animator().setAlphaValue_(alpha)
            NSAnimationContext.endGrouping()

        def moved():
            if self._peek_fade_token is not token:
                return
            panel.setFrameOrigin_(NSMakePoint(target_x, y))
            fade(1.0, finished)

        def finished():
            if self._peek_fade_token is token:
                self._peek_fade_token = None
                self._peek_fading = False

        fade(0.0, moved)

    @objc.python_method
    def _peek_show_now(self):
        """Put a tucked orb at its inset at once, with no motion. A press on the orb does this first."""
        if self._peek_edge is None:
            return
        self._peek_fade_token = None
        self._peek_fading = False
        self._peek_anim = None
        self._peek_showing = True
        self._peek_outside = 0.0
        panel = self.mini_panel
        panel.setAlphaValue_(1.0)
        panel.setFrameOrigin_(NSMakePoint(self._peek_inset[0], self._peek_inset[1]))

    @objc.python_method
    def _peek_before_drag(self):
        self._orb_dragging = True
        self._peek_show_now()

    @objc.python_method
    def _peek_disengage(self, move):
        """Stop peeking. With move, a tucked orb goes straight back to its inset (no motion)."""
        was_edge = self._peek_edge
        inset = self._peek_inset
        was_fading = self._peek_fading
        self._peek_stop_timer()
        self._peek_edge = None
        self._peek_screen = None
        self._peek_inset = None
        self._peek_showing = True
        self._peek_anim = None
        self._peek_fade_token = None
        self._peek_fading = False
        self._peek_outside = 0.0
        self._peek_latched = False
        panel = getattr(self, "mini_panel", None)
        if was_edge is not None and move and inset is not None and panel is not None:
            if was_fading:
                panel.setAlphaValue_(1.0)
            if getattr(self, "pillCollapsed", False):
                panel.setFrameOrigin_(NSMakePoint(inset[0], inset[1]))

    @objc.python_method
    def _peek_cursor_and_center(self, panel):
        loc = NSEvent.mouseLocation()
        frame = panel.frame()
        width, height = float(frame.size.width), float(frame.size.height)
        center = (float(frame.origin.x) + width / 2.0, float(frame.origin.y) + height / 2.0)
        return (float(loc.x), float(loc.y)), center

    @objc.python_method
    def _peek_ensure_timer(self, seconds):
        if self._peek_timer is None or self._peek_interval != seconds:
            self._peek_stop_timer()
            self._peek_interval = seconds
            self._peek_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                seconds, self, "peekTick:", None, True)

    @objc.python_method
    def _peek_stop_timer(self):
        timer = self._peek_timer
        self._peek_timer = None
        self._peek_interval = None
        if timer is not None:
            timer.invalidate()

    def peekTick_(self, _timer):
        self._peek_tick()

    @objc.python_method
    def _peek_tick(self):
        """Runs at the cursor rate while tucked and at the drag rate while sliding. Decides where the orb should be."""
        if self._peek_edge is None:
            self._peek_stop_timer()
            return
        panel = getattr(self, "mini_panel", None)
        if panel is None or not panel.isVisible() or not getattr(self, "pillCollapsed", False) or self._peek_fading:
            self._peek_last = None  # a pause must not count toward the retract timer
            return
        now = time.monotonic()
        dt = 0.0 if self._peek_last is None else now - self._peek_last
        self._peek_last = now
        point, center = self._peek_cursor_and_center(panel)
        if self._peek_is_busy():
            want = True
            self._peek_outside = 0.0
        else:
            hot = in_hot_zone(point, self._peek_edge, self._peek_screen, center[1])
            far = not hot and math.hypot(point[0] - center[0], point[1] - center[1]) > PEEK_RETRACT_DISTANCE
            self._peek_outside = self._peek_outside + dt if far else 0.0
            if self._peek_showing:
                want = not should_retract(point, center, self._peek_outside, False)
            else:
                if not hot:
                    self._peek_latched = False
                want = hot and not self._peek_latched
        if want != self._peek_showing:
            self._peek_move(want)
        anim = self._peek_anim
        if anim is not None:
            x, v = spring(now - anim["t0"], anim["from"], anim["to"], anim["k"], anim["c"])
            if spring_done(x, v, anim["to"]):
                x = anim["to"]
                self._peek_anim = None
            panel.setFrameOrigin_(NSMakePoint(x, self._peek_inset[1]))
        self._peek_ensure_timer(DRAG_TICK_SECONDS if self._peek_anim is not None else CURSOR_POLL_SECONDS)

    def peekDockMenu_(self, sender):
        """Window menu: Tuck Jev into the edge. On by default, remembered across launches."""
        enabled = not self._peek_enabled()
        NSUserDefaults.standardUserDefaults().setBool_forKey_(enabled, PEEK_PREF_KEY)
        sender.setState_(1 if enabled else 0)
        if enabled:
            self._peek_consider()
        else:
            self._peek_disengage(move=True)

    @objc.python_method
    def _order_bar_front(self):
        screens = self._visible_screens()
        if not screens:
            return
        defaults = NSUserDefaults.standardUserDefaults()
        saved = parse_origin(defaults.stringForKey_(ORIGIN_KEY))
        size = remembered_size(defaults.stringForKey_(SIZE_KEY))
        x, y = migrate_saved_origin(saved, screens, size)
        self._expanded_origin = (x, y)
        self._expanded_size = size
        if hasattr(self, "pill") and not self.pill.busy:
            self.pill.expanded = False
        self._apply_pill_presentation()
        defaults.setObject_forKey_(format_size(size[0], size[1]), SIZE_KEY)
        motion = self._pill_flags().get("motion", True)
        if motion:
            self.mini_panel.setAlphaValue_(0.0)
        else:
            self.mini_panel.setAlphaValue_(1.0)
        self.mini_panel.orderFrontRegardless()
        if motion:
            self._fade_bar(1.0, None)
        self._peek_consider()

    @objc.python_method
    def _show_bar_reply(self, text):
        self.bar.note_reply(text, time.time())
        self.mini_field.setStringValue_(text)
        self._refresh_trailing_symbol()

    def miniSubmit_(self, _sender):
        # Runs the line where it was typed. Does not deminiaturize or order the main window front.
        plan = submission(self.mini_field.stringValue(), self.bar.reply)
        if plan is None:
            return
        self.bar.reply = ""
        self.mini_field.setStringValue_("")
        self._dispatch_text_plan(plan)

    def miniChip_(self, sender):
        chip_id = getattr(sender, "chipId", "") or ""
        plan = chip_command_plan(chip_id)
        if plan is None or plan.get("kind") != "run":
            return
        self._dispatch_text_plan(plan)

    def miniRefreshChips_(self, _sender):
        self._popover_refresh_index = refresh_chip_suggestions(getattr(self, "_popover_refresh_index", 0))
        self._apply_pill_presentation()

    def miniToggleHistory_(self, _sender):
        self._popover_history_open = not bool(getattr(self, "_popover_history_open", False))
        self._refresh_popover_history()
        self._apply_pill_presentation()

    @objc.python_method
    def _dispatch_text_plan(self, plan):
        local_reply = False
        if plan["kind"] == "run":
            phrase = plan["control"][1]
            if hasattr(self, "typed"):
                self.typed.note_request(phrase)
                self._refresh_home_history()
                self._refresh_popover_history()
            if hasattr(self, "pill"):
                self.pill.command_started()
            if not self.worker_started:
                if hasattr(self, "typed"):
                    self.typed.note_reply("Add your API keys in the main window first.")
                    self._refresh_home_history()
                    self._refresh_popover_history()
                self._show_bar_reply("Add your API keys in the main window first.")
                local_reply = True
            else:
                self.controls.put(plan["control"])
        self._refresh_trailing_symbol()
        self._restore_front_app()
        if local_reply and hasattr(self, "pill"):
            self.pill.hold_local_reply()

    def miniMicDown_(self, _sender):
        if self._mini_mic_held:
            return
        self._mini_mic_held = True
        self.controls.put(mic_event("down"))
        self._sync_level_meter(True)
        self._refresh_trailing_symbol()

    def miniMicUp_(self, _sender):
        if not self._mini_mic_held:
            return
        self._mini_mic_held = False
        self.controls.put(mic_event("up"))
        self._sync_level_meter(self._is_listening())
        self._refresh_trailing_symbol()

    def miniDismiss_(self, _sender):
        """Esc collapses the typing pill and hands the keyboard back.

        Hide Mini Bar still hides the pill. Esc leaves the mic capsule up.
        """
        if hasattr(self, "pill"):
            self.pill.escape()
        self._restore_front_app()
        self._apply_pill_presentation()

    def control_textView_doCommandBySelector_(self, control, _view, selector):
        if control == getattr(self, "model_field", None) and str(selector) == "insertNewline:":
            self._save_model()
            return True
        if control == getattr(self, "mini_field", None) and str(selector) == "cancelOperation:":
            self.miniDismiss_(control)
            return True
        return False

    def controlTextDidChange_(self, notification):
        if notification is not None and notification.object() == getattr(self, "mini_field", None):
            self._refresh_trailing_symbol()

    def controlTextDidEndEditing_(self, notification):
        if notification is not None and notification.object() == getattr(self, "model_field", None):
            self._save_model()

    def windowDidMiniaturize_(self, notification):
        if notification.object() == self.panel:
            self._sync_mini_bar()

    def windowDidDeminiaturize_(self, notification):
        if notification.object() == self.panel:
            self._main_closing = False
            self._sync_mini_bar()

    def windowWillClose_(self, notification):
        if notification.object() == getattr(self, "full_window", None):
            # Closing the full window hands back to the orb; nothing else changes.
            self._sync_mini_bar()
            return
        if notification.object() == self.panel:
            self._main_closing = True
            self._sync_mini_bar()

    def windowDidBecomeKey_(self, notification):
        if notification.object() == self.panel:
            self._main_closing = False
            self._sync_mini_bar()

    def windowDidMove_(self, notification):
        panel = getattr(self, "mini_panel", None)
        if panel is None or notification.object() != panel or not panel.isVisible():
            return
        if getattr(self, "_suppress_size_save", False):
            return
        self._sync_expanded_from_window()
        origin = getattr(self, "_expanded_origin", None)
        if origin is None:
            point = panel.frame().origin
            origin = (point.x, point.y)
        NSUserDefaults.standardUserDefaults().setObject_forKey_(format_origin(origin[0], origin[1]), ORIGIN_KEY)

    def windowDidResize_(self, notification):
        if notification.object() == getattr(self, "full_window", None):
            self._layout_full_window()
            return
        panel = getattr(self, "mini_panel", None)
        if panel is None or notification.object() != panel:
            return
        size = panel.frame().size
        self._layout_mini_bar(float(size.width), float(size.height))
        if getattr(self, "_suppress_size_save", False) or not panel.isVisible():
            return
        if getattr(self, "_pill_frame_collapsed", False):
            return
        self._sync_expanded_from_window()
        NSUserDefaults.standardUserDefaults().setObject_forKey_(
            format_size(float(size.width), float(size.height)), SIZE_KEY)

    def windowDidResignKey_(self, notification):
        panel = getattr(self, "mini_panel", None)
        if notification is None or panel is None or notification.object() != panel:
            return
        if getattr(self, "_pill_menu_open", False):
            return
        pill = getattr(self, "pill", None)
        if pill is None or not pill.expanded:
            return
        pill.focus_lost()
        if pill.collapsed:
            self._apply_pill_presentation()

    def layoutMiniBar_(self, _sender):
        panel = getattr(self, "mini_panel", None)
        if panel is None or not hasattr(self, "mini_field"):
            return
        size = panel.frame().size
        self._layout_mini_bar(float(size.width), float(size.height))

    @objc.python_method
    def _composer_rect(self):
        origin = getattr(self, "_expanded_origin", None) or (0.0, 0.0)
        size = getattr(self, "_expanded_size", None) or default_size()
        return (float(origin[0]), float(origin[1]), float(size[0]), float(size[1]))

    @objc.python_method
    def _layout_mini_bar(self, width, height):
        """Place the orb popover, or the idle mic capsule."""
        if not hasattr(self, "mini_field"):
            return
        if getattr(self, "pillCollapsed", False):
            self._layout_collapsed_capsule(width, height)
            return
        composer_rect = self._composer_rect()
        screens = self._visible_screens()
        screen = screen_for_frame(composer_rect, screens) if screens else None
        if screen is None and screens:
            screen = screens[0]
        layout = popover_subframes(
            composer_rect,
            screen or (0.0, 0.0, float(width), float(height)),
            refresh_index=getattr(self, "_popover_refresh_index", 0),
            history_open=getattr(self, "_popover_history_open", False),
        )
        ox, oy, ow, oh = layout["orb"]
        _place(self.orb_view, (ox, oy, ow, oh))
        gx, gy, gw, gh = layout["greeting"]
        bubble = getattr(self, "greeting_bubble", None)
        label = getattr(self, "greeting_label", None)
        if bubble is not None:
            bubble.setHidden_(True)
            _place(bubble, (gx, gy, gw, gh))
            chrome = getattr(self, "_pill_chrome", {})
            bubble.solidFill = chrome.get("material") == "solid"
            bubble.setNeedsDisplay_(True)
        if label is not None:
            label.setHidden_(False)
            label.setStringValue_(greeting_text())
            _place(label, (gx + 8.0, gy + 6.0, max(40.0, gw - 16.0), max(16.0, gh - 12.0)))
        cx, cy, cw, ch = layout["composer"]
        self.mini_plus.setHidden_(False)
        self.mini_field.setHidden_(False)
        self.mini_expand.setHidden_(False)
        frames = popover_controls((cw, ch))
        metrics = bar_metrics(cw, ch)
        on = self._apply_zoe_badge()
        _place(self.mini_plus, (cx + frames["plus"][0], cy + frames["plus"][1], frames["plus"][2], frames["plus"][3]))
        self.mini_plus.setFont_(NSFont.systemFontOfSize_weight_(metrics["plus_font"], 0.3))
        field = frames["field"]
        badge = 48.0 if on else 0.0
        _place(
            self.mini_field,
            (cx + field[0], cy + field[1], max(40.0, field[2] - badge), field[3]),
        )
        self.mini_field.setFont_(NSFont.systemFontOfSize_(metrics["field_font"]))
        expand = frames["expand"]
        _place(self.mini_expand, (cx + expand[0], cy + expand[1], expand[2], expand[3]))
        mic = frames["mic"]
        _place(self.mini_mic, (cx + mic[0], cy + mic[1], mic[2], mic[3]))
        self._place_mic_level((cx + mic[0], cy + mic[1], mic[2], mic[3]))
        if hasattr(self, "rec_stop"):
            _place(self.rec_stop, (cx + mic[0], cy + mic[1], mic[2], mic[3]))
            _place(self.rec_label, (cx + field[0], cy + field[1], min(88.0, field[2]), field[3]))
        if hasattr(self, "zoe_label"):
            _place(self.zoe_label, (cx + field[0] + field[2] - 46.0, cy + field[1], 44.0, field[3]))
        self._layout_popover_footer(layout)
        self._sync_capsule(width, height, popover=True, panel_rect=layout.get("panel"))
        self._sync_recording_ui()
        self._style_pill_field()
        self._refresh_trailing_symbol()

    @objc.python_method
    def _sync_orb(self):
        orb = getattr(self, "orb_view", None)
        panel = getattr(self, "mini_panel", None)
        if orb is None or panel is None:
            return
        collapsed = bool(getattr(self, "pillCollapsed", False))
        flags = getattr(self, "_pill_chrome", {})
        status = getattr(self, "status", None)
        state = str(status.stringValue()) if status is not None else "Ready"
        visible = panel.isVisible() and self.bar.should_show()
        full = getattr(self, "full_window", None)
        docked = full is not None and bool(full.isVisible())
        orb.configure(state, bool(getattr(self, "option_down", False)),
                      getattr(self, "_meter_unit", 0.0), visible,
                      flags.get("motion", True), flags.get("material") == "solid",
                      docked=docked, popover=not collapsed)
        # The orb layer draws its own shadow. A window shadow on the orb-only panel would add a second one.
        panel.setHasShadow_(not collapsed)
        backing = getattr(self, "pill_backing", None)
        if backing is not None:
            backing.setHidden_(collapsed)
        overlay = getattr(self, "pill_overlay", None)
        if overlay is not None:
            # The orb popover draws its own rounded panel; the old capsule
            # hairline poked out of the panel corners.
            overlay.setHidden_(True)
        meter = getattr(self, "mic_level_view", None)
        if meter is not None:
            meter.setHidden_(collapsed)
        # Screen recording retains its existing stop control above the orb.
        stop = getattr(self, "rec_stop", None)
        recording = stop is not None and not stop.isHidden()
        self.mini_mic.setHidden_(collapsed or recording)

    @objc.python_method
    def _place_mic_level(self, mic_frame):
        view = getattr(self, "mic_level_view", None)
        if view is None:
            return
        _place(view, mic_frame)

    @objc.python_method
    def _layout_collapsed_capsule(self, width, height):
        """Mic only, centered in the idle capsule. The typing controls stay hidden."""
        frames = capsule_controls((width, height))
        self.mini_plus.setHidden_(True)
        self.mini_field.setHidden_(True)
        if hasattr(self, "mini_expand"):
            self.mini_expand.setHidden_(True)
        for name in ("greeting_bubble", "greeting_label"):
            view = getattr(self, name, None)
            if view is not None:
                view.setHidden_(True)
        for name in ("popover_history_btn", "popover_refresh_btn", "popover_history_scroll"):
            view = getattr(self, name, None)
            if view is not None:
                view.setHidden_(True)
        for chip in getattr(self, "popover_chips", []):
            chip.setHidden_(True)
        _place(self.orb_view, (0.0, 0.0, width, height))
        _place(self.mini_mic, frames["mic"])
        self._place_mic_level(frames["mic"])
        self.mini_mic.pillRole = "expand"
        if hasattr(self, "rec_stop"):
            _place(self.rec_stop, frames["mic"])
        self._sync_recording_ui()
        if hasattr(self, "rec_label"):
            self.rec_label.setHidden_(True)
        if hasattr(self, "zoe_label"):
            self.zoe_label.setHidden_(True)
        self.mini_plus.setHidden_(True)
        self.mini_field.setHidden_(True)
        recording = hasattr(self, "rec_stop") and not bool(self.rec_stop.isHidden())
        if not recording:
            self._set_button_symbol(self.mini_mic, "mic.fill", "Open Jev")
        self._apply_mic_tint()
        self._sync_capsule(width, height, popover=False)

    @objc.python_method
    def _sync_expanded_from_window(self):
        """Keep the remembered typing-pill rect in step with a drag or a resize.

        A collapsed window is the right-hand end of that rect, so its origin is
        not the origin saved for the next launch.
        """
        panel = getattr(self, "mini_panel", None)
        if panel is None:
            return
        if self._peek_frame_is_not_inset():
            return  # a tucked or sliding orb is not at the saved inset, so it must not overwrite it
        frame = panel.frame()
        box = (
            float(frame.origin.x),
            float(frame.origin.y),
            float(frame.size.width),
            float(frame.size.height),
        )
        if getattr(self, "_pill_frame_collapsed", False):
            size = getattr(self, "_expanded_size", None) or default_size()
            restored = expanded_frame_from_capsule(box, size)
            self._expanded_origin = (restored[0], restored[1])
            self._expanded_size = (restored[2], restored[3])
            return
        composer_rect = self._composer_rect()
        screens = self._visible_screens()
        screen = screen_for_frame(composer_rect, screens) if screens else None
        if screen is None and screens:
            screen = screens[0]
        layout = popover_subframes(composer_rect, screen or box)
        cr = layout["composer_rect"]
        self._expanded_origin = (cr[0], cr[1])
        size = getattr(self, "_expanded_size", None) or default_size()
        self._expanded_size = (float(size[0]), float(size[1]))

    @objc.python_method
    def _target_pill_frame(self):
        composer_rect = self._composer_rect()
        screens = self._visible_screens()
        screen = screen_for_frame(composer_rect, screens) if screens else (0.0, 0.0, 1440.0, 900.0)
        if screen is None and screens:
            screen = screens[0]
        expanded = getattr(self, "pill", None) is not None and self.pill.expanded
        return window_frame_for_presentation(
            composer_rect,
            expanded,
            screen or (0.0, 0.0, 1440.0, 900.0),
            refresh_index=getattr(self, "_popover_refresh_index", 0),
            history_open=getattr(self, "_popover_history_open", False),
        )

    @objc.python_method
    def _apply_pill_presentation(self, animate_open=False):
        """Resize to the orb capsule or the anchored popover."""
        panel = getattr(self, "mini_panel", None)
        if panel is None or not hasattr(self, "pill"):
            return
        self.pillCollapsed = bool(self.pill.collapsed)
        target = self._target_pill_frame()
        if self.pillCollapsed:
            target = (self._peek_frame_x(target[0]), target[1], target[2], target[3])
        else:
            self._peek_disengage(move=False)  # the popover opens at the inset, so the peek ends here
        self._suppress_size_save = True
        self._pill_frame_collapsed = self.pillCollapsed
        flags = self._pill_flags()
        motion = flags.get("motion", True)
        anim = popover_open_animation(not motion) if animate_open and not self.pillCollapsed else {"duration": 0.0, "offset": 0.0}
        try:
            if anim["duration"] > 0.0:
                panel.setAlphaValue_(0.0)
            panel.setFrame_display_(NSMakeRect(target[0], target[1], target[2], target[3]), True)
            self._layout_mini_bar(target[2], target[3])
        finally:
            self._suppress_size_save = False
        if anim["duration"] > 0.0:
            NSAnimationContext.beginGrouping()
            ctx = NSAnimationContext.currentContext()
            ctx.setDuration_(anim["duration"])
            panel.animator().setAlphaValue_(1.0)
            NSAnimationContext.endGrouping()
        else:
            panel.setAlphaValue_(1.0)
        self._apply_mic_tint()
        self._sync_orb()
        if self.pillCollapsed:
            self._peek_consider()

    @objc.python_method
    def _place_expanded_on_main_screen(self):
        """The typing pill opens on the main screen. An origin already there stays."""
        screen = NSScreen.mainScreen()
        if screen is None:
            return
        rect = screen.visibleFrame()
        visible = (
            float(rect.origin.x),
            float(rect.origin.y),
            float(rect.size.width),
            float(rect.size.height),
        )
        size = getattr(self, "_expanded_size", None) or default_size()
        origin = getattr(self, "_expanded_origin", None)
        self._expanded_origin = place_bar(origin, visible, size)

    @objc.python_method
    def _apply_mic_tint(self):
        mic = getattr(self, "mini_mic", None)
        if mic is None or not hasattr(self, "pill"):
            return
        mic.speakingTint = self.pill.mic_tint() == "blue"
        if hasattr(mic, "_apply_pill_tint"):
            mic._apply_pill_tint()
        self._sync_orb()

    def expandMiniBar_(self, _sender):
        """A click on the idle capsule opens the typing pill and shows the caret."""
        if not hasattr(self, "pill"):
            return
        if self.pill.expanded and not getattr(self, "pillCollapsed", False):
            self._focus_pill_field()
            return
        self.pill.click()
        self._apply_pill_presentation(animate_open=True)
        self._focus_pill_field()

    def miniExpandHome_(self, _sender):
        """Expand the popover into the full Jev window, keeping the draft."""
        draft = home_draft_from_popover(getattr(self, "mini_field", None).stringValue() if hasattr(self, "mini_field") else "")
        if hasattr(self, "pill"):
            self.pill.escape()
        self._apply_pill_presentation()
        self._show_full_window(draft)

    def fullOpenHome_(self, _sender):
        """The old expand target: Jev Home in the main window."""
        draft = self.full_field.stringValue() if hasattr(self, "full_field") else ""
        self.showMain_(None)
        self._select_tab("home")
        field = getattr(self, "home_field", None)
        if field is not None:
            field.setStringValue_(draft)
            self.panel.makeFirstResponder_(field)

    @objc.python_method
    def _fw_color(self, name, alpha=1.0):
        dark = False
        try:
            appearance = self.full_window.effectiveAppearance().name()
            dark = "Dark" in str(appearance)
        except Exception:
            pass
        r, g, b = fw.token(name, dark)
        return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, alpha)

    @objc.python_method
    def _build_full_window(self):
        w, h = fw.FULL_DEFAULT
        style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
                 | NSWindowStyleMaskResizable | NSWindowStyleMaskFullSizeContentView)
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, w, h), style, NSBackingStoreBuffered, False)
        win.setTitle_("Jev")
        win.setTitleVisibility_(1)
        win.setTitlebarAppearsTransparent_(True)
        win.setMovableByWindowBackground_(True)
        win.setReleasedWhenClosed_(False)
        win.setMinSize_(NSMakeSize(*fw.FULL_MIN))
        win.setContentMinSize_(NSMakeSize(*fw.FULL_MIN))
        win.setDelegate_(self)
        win.center()
        win.setFrameAutosaveName_(fw.FULL_AUTOSAVE)  # remembers size and position
        self.full_window = win
        root = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
        win.setContentView_(root)
        self.full_solid = SolidFullView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
        root.addSubview_(self.full_solid)
        self.full_effect = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
        self.full_effect.setMaterial_(SIDEBAR_MATERIAL)
        self.full_effect.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        self.full_effect.setState_(NSVisualEffectStateFollowsWindowActiveState)
        root.addSubview_(self.full_effect)
        self.full_main = SolidFullView.alloc().initWithFrame_(NSMakeRect(fw.SIDEBAR_W, 0, w - fw.SIDEBAR_W, h))
        self.full_main.fill = "page"
        root.addSubview_(self.full_main)

        def label(text, size, weight, color):
            f = NSTextField.labelWithString_(text)
            f.setFont_(NSFont.systemFontOfSize_weight_(size, weight))
            f.setTextColor_(color)
            root.addSubview_(f)
            return f

        self.full_side_title = label("History", 11, 0.4, NSColor.secondaryLabelColor())
        self.full_header = label("Jev", 17, 0.4, NSColor.labelColor())
        self.full_home_btn = NSButton.buttonWithTitle_target_action_("Jev Home", self, "fullOpenHome:")
        self.full_home_btn.setBezelStyle_(14 if hasattr(self.full_home_btn, "setBezelStyle_") else 1)
        self.full_home_btn.setBordered_(False)
        self.full_home_btn.setContentTintColor_(NSColor.secondaryLabelColor())
        self.full_home_btn.setFont_(NSFont.systemFontOfSize_(12))
        root.addSubview_(self.full_home_btn)

        def scrolled(font, card):
            tv = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 100))
            tv.setEditable_(False)
            tv.setSelectable_(True)
            tv.setDrawsBackground_(False)
            tv.setFont_(font)
            tv.setTextContainerInset_(NSMakeSize(10, 10) if card else NSMakeSize(4, 6))
            tv.setAutoresizingMask_(NSViewWidthSizable)
            tv.setVerticallyResizable_(True)
            tv.setHorizontallyResizable_(False)
            tv.textContainer().setWidthTracksTextView_(True)
            sc = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 100))
            sc.setDrawsBackground_(False)
            sc.setHasVerticalScroller_(True)
            sc.setAutohidesScrollers_(True)
            sc.setDocumentView_(tv)
            root.addSubview_(sc)
            return tv, sc

        self.full_card = SolidFullView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.full_card.fill = "soft"
        self.full_card.radius = 12.0
        self.full_card.stroke = "line"
        root.addSubview_(self.full_card)
        self.full_result_title = label("Result", 11, 0.4, NSColor.secondaryLabelColor())
        self.full_divider = SolidFullView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 10))
        self.full_divider.fill = "line"
        root.addSubview_(self.full_divider)
        self.full_history, self.full_history_scroll = scrolled(NSFont.systemFontOfSize_(12.5), False)
        self.full_convo, self.full_convo_scroll = scrolled(NSFont.systemFontOfSize_(13.5), False)
        self.full_result, self.full_result_scroll = scrolled(
            NSFont.monospacedSystemFontOfSize_weight_(12, 0.0), True)
        self.full_input_bg = SolidFullView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.full_input_bg.fill = "soft"
        self.full_input_bg.radius = fw.INPUT_H / 2.0
        root.addSubview_(self.full_input_bg)
        self.full_field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.full_field.setBezeled_(False)
        self.full_field.setDrawsBackground_(False)
        self.full_field.setFocusRingType_(1)
        self.full_field.setFont_(NSFont.systemFontOfSize_(14))
        self.full_field.setPlaceholderString_("Ask Jev anything…")
        self.full_field.setTarget_(self)
        self.full_field.setAction_("fullSubmit:")
        root.addSubview_(self.full_field)
        self.full_mic = HoldMicButton.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.full_mic.setBordered_(False)
        self.full_mic.setTarget_(self)
        self.full_mic.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        self.full_mic.pillRole = "mic"
        self._set_button_symbol(self.full_mic, "mic.fill", "Hold to talk")
        root.addSubview_(self.full_mic)
        self.full_chips = []
        for chip_id in popover_chip_ids(0):
            info = POPOVER_CHIPS.get(chip_id, {})
            btn = PopoverChipButton.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
            btn.configure(chip_id, info.get("title", chip_id), info.get("subtitle", ""))
            btn.setTarget_(self)
            root.addSubview_(btn)
            self.full_chips.append(btn)
        self._apply_full_chrome()
        self._layout_full_window()

    @objc.python_method
    def _apply_full_chrome(self):
        ws = NSWorkspace.sharedWorkspace()
        try:
            reduce_t = bool(ws.accessibilityDisplayShouldReduceTransparency())
        except Exception:
            reduce_t = False
        chrome = fw.full_chrome(reduce_t)
        self.full_effect.setHidden_(chrome["backing"] == "solid")
        self.full_solid.fill = "soft"
        self.full_solid.setHidden_(chrome["backing"] != "solid")
        for view in (self.full_solid, self.full_main, self.full_input_bg):
            view.setNeedsDisplay_(True)
        self.full_card.setNeedsDisplay_(True)
        self.full_result_title.setTextColor_(self._fw_color("muted"))
        self.full_header.setTextColor_(self._fw_color("ink"))
        self.full_side_title.setTextColor_(self._fw_color("muted"))

    @objc.python_method
    def _layout_full_window(self):
        win = getattr(self, "full_window", None)
        if win is None:
            return
        size = win.contentView().frame().size
        lay = fw.full_layout(size.width, size.height)
        R = lambda r: NSMakeRect(*r)
        cw, ch = lay["size"]
        self.full_solid.setFrame_(R((0, 0, cw, ch)))
        self.full_effect.setFrame_(R(lay["sidebar"]))
        self.full_main.setFrame_(R((fw.SIDEBAR_W, 0, cw - fw.SIDEBAR_W, ch)))
        self.full_side_title.setFrame_(R(lay["sidebar_title"]))
        self.full_history_scroll.setFrame_(R(lay["history"]))
        hx, hy, hw, hh = lay["header"]
        self.full_header.setFrame_(R((hx, hy, hw - 90, hh)))
        self.full_home_btn.setFrame_(R((hx + hw - 84, hy, 84, hh)))
        self.full_convo_scroll.setFrame_(R(lay["conversation"]))
        self.full_divider.setFrame_(R((fw.SIDEBAR_W, 0, 1, ch)))
        if lay["result"]:
            rx, ry, rw, rh = lay["result"]
            self.full_card.setFrame_(R((rx, ry, rw, rh - 18)))
            self.full_result_scroll.setFrame_(R((rx + 1, ry + 1, rw - 2, rh - 20)))
            self.full_result_title.setFrame_(R((rx + 2, ry + rh - 16, rw, 16)))
        self.full_input_bg.setFrame_(R(lay["field"]))
        fx, fy, fwid, fh = lay["field"]
        self.full_field.setFrame_(R((fx + 16, fy + (fh - 20) / 2.0, fwid - 32, 20)))
        mx, my, mw, mh = lay["mic"]
        self.full_mic.setFrame_(R((mx + 8, my + 8, mw - 16, mh - 16)))
        widths = {b.chipId: chip_width(b.chipId) for b in self.full_chips}
        placed = {c["id"]: c["frame"] for c in fw.chip_frames([b.chipId for b in self.full_chips], widths, lay["chips"])}
        for b in self.full_chips:
            frame = placed.get(b.chipId)
            b.setHidden_(frame is None)
            if frame is not None:
                b.setFrame_(R(frame))

    @objc.python_method
    def _refresh_full_window(self):
        if getattr(self, "full_window", None) is None or not hasattr(self, "typed"):
            return
        rows = list(self.typed.rows)
        items = fw.history_items(rows)
        self.full_history.setString_("\n\n".join(items) if items else "Nothing yet.")
        self.full_history.setTextColor_(self._fw_color("ink"))
        text = NSMutableAttributedString.alloc().init()
        for who, line in fw.conversation_lines(rows):
            name_attrs = {NSFontAttributeName: NSFont.systemFontOfSize_weight_(12, 0.4),
                          NSForegroundColorAttributeName: self._fw_color("accent" if who == "Jev" else "muted")}
            body_attrs = {NSFontAttributeName: NSFont.systemFontOfSize_(13.5),
                          NSForegroundColorAttributeName: self._fw_color("ink")}
            text.appendAttributedString_(NSAttributedString.alloc().initWithString_attributes_(who + "\n", name_attrs))
            text.appendAttributedString_(NSAttributedString.alloc().initWithString_attributes_(line + "\n\n", body_attrs))
        if not rows:
            text = NSAttributedString.alloc().initWithString_attributes_(
                "Hi, I'm Jev. Type below, tap a chip, or hold the mic to talk.",
                {NSFontAttributeName: NSFont.systemFontOfSize_(13.5),
                 NSForegroundColorAttributeName: self._fw_color("muted")})
        self.full_convo.textStorage().setAttributedString_(text)
        self.full_convo.scrollToEndOfDocument_(None)
        result = fw.last_result(rows) or "Results and tool output show here."
        self.full_result.setString_(result)
        self.full_result.setTextColor_(self._fw_color("ink" if fw.last_result(rows) else "muted"))

    @objc.python_method
    def _show_full_window(self, draft=""):
        if getattr(self, "full_window", None) is None:
            self._build_full_window()
        self._apply_full_chrome()
        self._layout_full_window()
        self._refresh_full_window()
        if draft:
            self.full_field.setStringValue_(draft)
        NSApp.activateIgnoringOtherApps_(True)
        self.full_window.makeKeyAndOrderFront_(None)
        self.full_window.makeFirstResponder_(self.full_field)

    def fullSubmit_(self, _sender):
        plan = submission(self.full_field.stringValue(), "")
        if plan is None:
            return
        self.full_field.setStringValue_("")
        self._dispatch_text_plan(plan)
        self._refresh_full_window()

    @objc.python_method
    def _pill_flags(self):
        # Vibrancy, not NSGlassEffectView: glass refracted the orb and the
        # greeting into low-resolution blobs in the borderless popover.
        glass = False
        ws = NSWorkspace.sharedWorkspace()
        try:
            reduce_t = bool(ws.accessibilityDisplayShouldReduceTransparency())
        except Exception:
            reduce_t = False
        try:
            increase_c = bool(ws.accessibilityDisplayShouldIncreaseContrast())
        except Exception:
            increase_c = False
        try:
            reduce_m = bool(ws.accessibilityDisplayShouldReduceMotion())
        except Exception:
            reduce_m = False
        return pill_chrome(glass, reduce_t, increase_c, reduce_m)

    @objc.python_method
    def _install_pill_chrome(self):
        panel = getattr(self, "mini_panel", None)
        if panel is None:
            return
        root = panel.contentView()
        if root is None:
            return
        bounds = root.bounds()
        chrome = self._pill_flags()
        self._pill_chrome = chrome
        old = getattr(self, "pill_backing", None)
        if old is not None:
            old.removeFromSuperview()
            self.pill_backing = None
        backing = self._make_backing(bounds, chrome)
        self.pill_backing = backing
        overlay = getattr(self, "pill_overlay", None)
        if overlay is None:
            overlay = PillChromeOverlay.alloc().initWithFrame_(bounds)
            overlay.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
            overlay.passesClicks = True
            self.pill_overlay = overlay
            anchor = getattr(self, "mini_plus", None)
            if anchor is not None:
                root.addSubview_positioned_relativeTo_(overlay, NSWindowBelow, anchor)
            else:
                root.addSubview_(overlay)
        else:
            overlay.setFrame_(bounds)
            overlay.passesClicks = True
        if backing is not None:
            backing.passesClicks = True
            # Bottom of the stack, so the greeting, chips and orb draw on it.
            root.addSubview_positioned_relativeTo_(backing, NSWindowBelow, None)
        overlay.solidFill = chrome.get("material") == "solid"
        overlay.contrastBorder = bool(chrome.get("contrast_border"))
        overlay.setNeedsDisplay_(True)
        self._sync_capsule(float(bounds.size.width), float(bounds.size.height))
        self._style_pill_field()
        self._sync_orb()

    @objc.python_method
    def _make_backing(self, bounds, chrome):
        material = chrome.get("material")
        if material == "solid":
            view = SolidPanelView.alloc().initWithFrame_(bounds)
            return view
        if material == "glass":
            glass = self._make_glass_backing(bounds)
            if glass is not None:
                return glass
        # vibrancy when NSGlassEffectView is missing, or when glass could not be built
        return self._make_vibrancy_backing(bounds)

    @objc.python_method
    def _make_glass_backing(self, bounds):
        cls = _glass_pass_through()
        if cls is None:
            return None
        try:
            view = cls.alloc().initWithFrame_(bounds)
        except Exception:
            return None
        if view is None:
            return None
        radius = float(bounds.size.height) / 2.0
        if hasattr(view, "setCornerRadius_"):
            view.setCornerRadius_(radius)
        _capsule_layer(view, radius, True)
        view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        return view

    @objc.python_method
    def _make_vibrancy_backing(self, bounds):
        view = PassThroughEffect.alloc().initWithFrame_(bounds)
        view.setMaterial_(NSVisualEffectMaterialHUDWindow)
        view.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        view.setState_(NSVisualEffectStateActive)
        view.setMaskImage_(_corner_mask(POPOVER_PANEL_RADIUS))
        view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        return view

    @objc.python_method
    def _sync_capsule(self, width, height, popover=False, panel_rect=None):
        """Transparent window. Only the popover column gets a rounded panel."""
        frame = NSMakeRect(0, 0, float(width), float(height))
        if panel_rect is not None:
            frame = NSMakeRect(*(float(v) for v in panel_rect))
        panel = getattr(self, "mini_panel", None)
        if panel is not None:
            _capsule_layer(panel.contentView(), 0.0, False)
        backing = getattr(self, "pill_backing", None)
        if backing is not None:
            backing.setFrame_(frame)
            backing.setHidden_(not popover)
        solid = getattr(self, "pill_solid", None)
        if solid is not None:
            solid.setFrame_(frame)
            solid.setHidden_(not popover)
        if panel is not None:
            panel.invalidateShadow()
        overlay = getattr(self, "pill_overlay", None)
        if overlay is not None:
            overlay.setFrame_(frame)
            overlay.setNeedsDisplay_(True)

    @objc.python_method
    def _style_pill_field(self):
        field = getattr(self, "mini_field", None)
        if field is None:
            return
        field.setTextColor_(NSColor.labelColor())
        field.setDrawsBackground_(True)
        field.setBackgroundColor_(NSColor.textBackgroundColor().colorWithAlphaComponent_(0.72))
        font = field.font() or NSFont.systemFontOfSize_(14)
        attrs = {
            NSForegroundColorAttributeName: NSColor.secondaryLabelColor(),
            NSFontAttributeName: font,
        }
        field.setPlaceholderAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(PLACEHOLDER, attrs)
        )
        for button in (getattr(self, "mini_plus", None), getattr(self, "mini_mic", None)):
            if button is not None and hasattr(button, "_apply_pill_tint"):
                button._apply_pill_tint()

    @objc.python_method
    def _watch_display_options(self):
        if getattr(self, "_pill_watched", False):
            return
        center = NSWorkspace.sharedWorkspace().notificationCenter()
        center.addObserver_selector_name_object_(
            self,
            "refreshPillChrome:",
            "NSWorkspaceAccessibilityDisplayOptionsDidChangeNotification",
            None,
        )
        center.addObserver_selector_name_object_(
            self,
            "workspaceWillSleep:",
            "NSWorkspaceWillSleepNotification",
            None,
        )
        center.addObserver_selector_name_object_(
            self,
            "activeSpaceDidChange:",
            "NSWorkspaceActiveSpaceDidChangeNotification",
            None,
        )
        self._pill_watched = True

    def refreshPillChrome_(self, _sender):
        if getattr(self, "_pill_refreshing", False):
            return
        self._pill_refreshing = True
        try:
            self._install_pill_chrome()
            self._sync_listen_pulse(self._is_listening())
        finally:
            self._pill_refreshing = False

    @objc.python_method
    def _set_button_symbol(self, button, name, label):
        image = None
        try:
            image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, label)
        except Exception:
            image = None
        if image is not None:
            image.setTemplate_(True)
            button.setImage_(image)
            button.setImagePosition_(1)  # image only
            button.setTitle_("")
            return
        button.setImage_(None)
        button.setTitle_(label)

    @objc.python_method
    def _is_listening(self):
        if getattr(self, "_mini_mic_held", False):
            return True
        status = getattr(self, "status", None)
        if status is None:
            return False
        try:
            return str(status.stringValue()) == "Listening"
        except Exception:
            return False

    @objc.python_method
    def _refresh_trailing_symbol(self):
        mic = getattr(self, "mini_mic", None)
        field = getattr(self, "mini_field", None)
        if mic is None or field is None:
            return
        if getattr(self, "pillCollapsed", False):
            mic.pillRole = "expand"
            self._set_button_symbol(mic, "mic.fill", "Type to Jev")
            self._apply_mic_tint()
            self._sync_listen_pulse(False)
            return
        listening = self._is_listening()
        reply = self.bar.reply if hasattr(self, "bar") else ""
        name = trailing_symbol(listening, field.stringValue(), reply)
        mic.pillRole = "send" if name == "arrow.up.circle.fill" else "mic"
        label = "Send" if mic.pillRole == "send" else "Listen"
        self._set_button_symbol(mic, name, label)
        self._sync_listen_pulse(listening and name == "waveform")
        self._apply_mic_tint()

    @objc.python_method
    def _sync_listen_pulse(self, active):
        mic = getattr(self, "mini_mic", None)
        timer = getattr(self, "_listen_timer", None)
        motion = self._pill_flags().get("motion", True)
        if active and motion:
            if timer is None:
                self._listen_dim = False
                self._listen_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    0.9, self, "pulseListen:", None, True)
            return
        if timer is not None:
            timer.invalidate()
            self._listen_timer = None
        if mic is not None:
            mic.setAlphaValue_(1.0)

    def pulseListen_(self, _timer):
        mic = getattr(self, "mini_mic", None)
        if mic is None:
            return
        self._listen_dim = not getattr(self, "_listen_dim", False)
        mic.setAlphaValue_(0.55 if self._listen_dim else 1.0)

    @objc.python_method
    def _sync_level_meter(self, active):
        """30 fps while Listening or held. A final status, and leaving that state, stops it."""
        timer = getattr(self, "_meter_timer", None)
        if active:
            if timer is None:
                self._meter_unit = 0.0
                self._meter_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    1.0 / 30.0, self, "pulseMeter:", None, True)
            return
        if timer is not None:
            timer.invalidate()
            self._meter_timer = None
        self._meter_unit = 0.0
        view = getattr(self, "mic_level_view", None)
        if view is not None:
            view.setAmplitude_(0.0)

    def pulseMeter_(self, _timer):
        siri = sys.modules.get("siri")
        mic = getattr(siri, "live_mic", None) if siri is not None else None
        if mic is None or not hasattr(mic, "level"):
            return
        try:
            db = mic.level()
        except Exception:
            return
        unit = smooth(getattr(self, "_meter_unit", 0.0), level_to_unit(db))
        self._meter_unit = unit
        orb = getattr(self, "orb_view", None)
        if orb is not None:
            orb.level = unit
            orb.followLevel()
        amplitude = unit ** 0.7
        view = getattr(self, "mic_level_view", None)
        if view is not None:
            view.setAmplitude_(amplitude)
        button = getattr(self, "mini_mic", None)
        if button is not None:
            button.amplitude = amplitude

    @objc.python_method
    def _hazard_alerts_on(self):
        """Saved hazard-alert choice. Off when that file cannot be read."""
        try:
            import commands
            return bool(commands.hazard_alerts_enabled())
        except Exception:
            return False

    def miniPlus_(self, sender):
        menu = NSMenu.alloc().initWithTitle_("Message Jev")
        recording = False
        entries = ()
        paused = False
        zoe_on = False
        hazard_on = False
        try:
            import commands
            recording = bool(commands.is_recording())
            entries = commands.clipboard_menu_entries()
            paused = commands.clipboard_is_paused()
            zoe_on = bool(commands.zoe_mode_active())
            hazard_on = bool(commands.hazard_alerts_enabled())
        except Exception:
            recording = False
            entries = ()
            paused = False
            zoe_on = False
            hazard_on = False
        self._fill_plus_menu(menu, plus_menu(recording=recording, zoe_mode=zoe_on, clipboard_entries=entries, clipboard_paused=paused, hazard_alerts=hazard_on))
        if sender is None:
            return
        height = float(sender.bounds().size.height)
        self._pill_menu_open = True
        try:
            menu.popUpMenuPositioningItem_atLocation_inView_(None, NSMakePoint(0.0, height + 6.0), sender)
        finally:
            self._pill_menu_open = False

    @objc.python_method
    def _menu_symbol(self, name, label):
        if not name:
            return None
        try:
            image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, label)
        except Exception:
            return None
        if image is None:
            return None
        image.setTemplate_(True)
        return image

    @objc.python_method
    def _fill_plus_menu(self, menu, items):
        menu.setAutoenablesItems_(False)
        for spec in items:
            kind = spec.get("kind")
            if kind == "separator":
                menu.addItem_(NSMenuItem.separatorItem())
                continue
            title = spec.get("title") or ""
            if kind == "submenu":
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
                image = self._menu_symbol(spec.get("symbol") or "", title)
                if image is not None:
                    item.setImage_(image)
                sub = NSMenu.alloc().initWithTitle_(title)
                self._fill_plus_menu(sub, spec.get("items") or ())
                item.setSubmenu_(sub)
                menu.addItem_(item)
                continue
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                title, "miniPlusItem:", spec.get("key") or "")
            item.setTarget_(self)
            item.setEnabled_(kind not in ("clipboard_empty", "games_empty"))
            item.setRepresentedObject_(spec.get("id") or "")
            item.setState_(1 if spec.get("checked") else 0)
            image = self._menu_symbol(spec.get("symbol") or "", title)
            if image is not None:
                item.setImage_(image)
            menu.addItem_(item)

    def miniPlusItem_(self, sender):
        raw = sender.representedObject() if sender is not None else None
        item_id = "" if raw is None else str(raw)
        # History rows are an index, not a phrase. The preview is the title only.
        index = clipboard_item_index(item_id)
        if index:
            paste = self._clipboard_option_paste()
            threading.Thread(
                target=self._activate_clipboard_from_menu, args=(index, paste), daemon=True).start()
            return
        phrase = clipboard_menu_phrase(item_id)
        if phrase:
            self._queue_bar_phrase(phrase)
            return
        # The alert title depends on the saved choice. Look that row up with
        # the same flag the menu was built from, then type its phrase.
        if item_id == "hazard_alerts":
            spec = plus_item(item_id, plus_menu(hazard_alerts=self._hazard_alerts_on()))
        else:
            spec = plus_item(item_id)
        if not spec:
            return
        kind = spec.get("kind")
        if item_id == "tutor":
            from commands.tutor import tutor_command
            field = ""
            reply = ""
            mini = getattr(self, "mini_field", None)
            if mini is not None:
                field = mini.stringValue()
            bar = getattr(self, "bar", None)
            if bar is not None:
                reply = getattr(bar, "reply", "") or ""
            self._queue_bar_phrase(tutor_command(field, reply))
            return
        if kind == "text":
            self._queue_bar_phrase(spec.get("phrase") or "")
            return
        if kind == "game_launch":
            threading.Thread(target=self._run_game_launch, args=(dict(spec),), daemon=True).start()
            return
        if kind == "zoe_mode":
            self._toggle_zoe_mode()
            return
        if str(kind).startswith("screenshot"):
            mode = {"screenshot_area": "area", "screenshot_window": "window"}.get(kind, "full")
            threading.Thread(target=self._capture_for_bar, args=(mode,), daemon=True).start()
            return
        if kind == "video_choose":
            self.chooseVideoFile_(sender)
            return
        if str(kind).startswith("video_"):
            threading.Thread(target=self._run_video_kind, args=(str(kind),), daemon=True).start()
            return
        if kind in ("record_start", "record_stop", "share_notes", "share_email", "share_imessage",
                    "share_finder", "share_copy", "share_delete", "captures_open", "ask_jev") or str(kind).startswith("ask_"):
            threading.Thread(target=self._run_capture_kind, args=(str(kind),), daemon=True).start()
            return
        if kind == "window":
            self.showMain_(sender)
            return
        if kind == "settings":
            self.showMain_(sender)
            self._select_tab("settings")
            return
        if kind == "updates":
            self.checkForUpdates_(sender)
            return
        if kind == "reset_position":
            self.resetMiniBarPosition_(sender)
            return
        if kind == "reset_size":
            self.resetMiniBarSize_(sender)
            return

    @objc.python_method
    def _clipboard_option_paste(self):
        """Option-click pastes. A plain click only copies the item back."""
        try:
            return option_held(NSEvent.modifierFlags(), NSEventModifierFlagOption)
        except Exception:
            return False

    @objc.python_method
    def _clipboard_status_line(self, status):
        """A pill line that does not include the clipboard text."""
        if status == "copied":
            return "Copied."
        if status == "pasted":
            return "Pasted."
        if status == "paste_failed":
            return "Copied, but I couldn't paste it."
        return "No clipboard item there."

    @objc.python_method
    def _activate_clipboard_from_menu(self, index, paste):
        try:
            import commands
            status, _speech = commands.activate_clipboard_index(index, paste=bool(paste))
        except Exception:
            status = "missing"
        line = self._clipboard_status_line(status)
        self.performSelectorOnMainThread_withObject_waitUntilDone_("showBarSentence:", line, False)

    def clipboardMenuItem_(self, sender):
        raw = sender.representedObject() if sender is not None else None
        index = clipboard_item_index("" if raw is None else str(raw))
        if not index:
            return
        paste = self._clipboard_option_paste()
        threading.Thread(
            target=self._activate_clipboard_from_menu, args=(index, paste), daemon=True).start()

    def clipboardMenuPhrase_(self, sender):
        raw = sender.representedObject() if sender is not None else None
        phrase = clipboard_menu_phrase("" if raw is None else str(raw))
        if phrase:
            self._queue_bar_phrase(phrase)

    @objc.python_method
    def _queue_bar_phrase(self, phrase):
        phrase = " ".join(str(phrase or "").split())
        if not phrase:
            return
        if not self.worker_started:
            self._show_bar_reply("Add your API keys in the main window first.")
            return
        self.bar.reply = ""
        self.mini_field.setStringValue_("")
        self.controls.put(("text", phrase))
        self._refresh_trailing_symbol()

    @objc.python_method
    def _capture_for_bar(self, mode="full"):
        try:
            import commands
            sentence = commands.take_screenshot(mode)
        except Exception as exc:
            sentence = "Couldn't take a screenshot."
            print(f"  mini bar screenshot failed: {exc}")
        self.performSelectorOnMainThread_withObject_waitUntilDone_("showCaptureResult:", str(sentence or ""), False)

    def _run_capture_kind(self, kind):
        try:
            import commands
            sentence = commands.run_capture_menu(kind)
        except Exception as exc:
            sentence = "Couldn't do that."
            print(f"  mini bar capture failed: {exc}")
        self.performSelectorOnMainThread_withObject_waitUntilDone_("showCaptureResult:", str(sentence or ""), False)

    def _run_game_launch(self, spec):
        """Open a scanned game in its emulator, then show the short result."""
        try:
            from commands.games import launch_rom
            sentence = launch_rom(spec.get("console") or "", spec.get("path") or "", spec.get("title") or "")
        except Exception as exc:
            sentence = "Couldn't open that game."
            print(f"  mini bar game launch failed: {exc}")
        self.performSelectorOnMainThread_withObject_waitUntilDone_("showCaptureResult:", str(sentence or ""), False)

    def _run_video_kind(self, kind):
        """Export on this background thread, then show the finished sentence."""
        try:
            import commands
            sentence = commands.video_from_text(str(kind), "")
        except Exception as exc:
            sentence = "Couldn't do that."
            print(f"  mini bar video failed: {exc}")
        self.performSelectorOnMainThread_withObject_waitUntilDone_("showCaptureResult:", str(sentence or ""), False)

    def chooseVideoFile_(self, _sender):
        """Open panel on the main thread. The picker itself lives in commands.video."""
        try:
            import commands
            sentence = commands.choose_video()
            from commands.captures import BOOK
            chosen = getattr(BOOK, "video", None)
        except Exception as exc:
            sentence = "I couldn't open the video picker."
            chosen = None
            print(f"  mini bar video picker failed: {exc}")
        self._show_bar_reply(str(sentence or ""))
        if chosen:
            self._show_capture_choices()

    def showCaptureResult_(self, sentence):
        self._show_bar_reply(str(sentence or ""))
        self._sync_recording_ui()
        self._maybe_show_choices(sentence)

    def showBarSentence_(self, sentence):
        self._show_bar_reply(str(sentence or ""))

    def miniStopRecording_(self, _sender):
        threading.Thread(target=self._run_capture_kind, args=("record_stop",), daemon=True).start()

    @objc.python_method
    def _maybe_show_choices(self, sentence):
        if not capture_saved(sentence):
            return
        self._show_capture_choices()

    @objc.python_method
    def _capture_anchor(self):
        panel = getattr(self, "mini_panel", None)
        if panel is not None and panel.isVisible():
            frame = panel.frame()
            return (
                float(frame.origin.x), float(frame.origin.y),
                float(frame.size.width), float(frame.size.height),
            )
        screens = self._visible_screens() or [(0.0, 0.0, 1440.0, 900.0)]
        defaults = NSUserDefaults.standardUserDefaults()
        size = remembered_size(defaults.stringForKey_(SIZE_KEY))
        saved = parse_origin(defaults.stringForKey_(ORIGIN_KEY))
        x, y = place_bar(saved, screens, size)
        return (x, y, size[0], size[1])

    @objc.python_method
    def _show_capture_choices(self):
        """Floating thumbnail and actions. Shown even when the main window is up and the pill is hidden."""
        import commands
        from commands.captures import BOOK
        last = BOOK.last or {}
        path = last.get("path") or ""
        if not path:
            return
        from commands.vision import offer_ask_jev
        from commands.video import is_video_extension
        ask = offer_ask_jev(path, bool(commands.find_ffmpeg()))
        video = is_video_extension(path)
        actions = capture_choice_actions(ask_jev=ask, video=video)
        box = choice_panel_box(actions)
        panel = getattr(self, "choice_panel", None)
        if panel is not None and panel.isVisible() and getattr(self, "_choice_path", "") == path:
            return
        self._choice_path = path
        self._choice_shown_at = time.time()
        if panel is None:
            panel = self._build_choice_panel()
        screens = self._visible_screens() or [(0.0, 0.0, 1440.0, 900.0)]
        size = box["size"]
        origin = choice_origin(self._capture_anchor(), screens[0], size)
        panel.setFrame_display_(NSMakeRect(origin[0], origin[1], size[0], size[1]), True)
        self._fill_choice_panel(path, ask, box)
        panel.orderFrontRegardless()

    @objc.python_method
    def _build_choice_panel(self):
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 300, 420), style, NSBackingStoreBuffered, False)
        panel.setLevel_(BAR_LEVEL)
        panel.setFloatingPanel_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setBecomesKeyOnlyIfNeeded_(True)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.windowBackgroundColor())
        panel.setHasShadow_(True)
        panel.setCollectionBehavior_(BAR_COLLECTION)
        panel.setReleasedWhenClosed_(False)
        root = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 300, 420))
        panel.setContentView_(root)
        self.choice_name = label("", NSMakeRect(12, 388, 276, 20), 13, weight=0.6)
        self.choice_image = NSImageView.alloc().initWithFrame_(NSMakeRect(12, 300, 276, 82))
        self.choice_image.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        self.choice_question = text_field(NSMakeRect(12, 12, 200, 26), "What do you want to know?")
        self.choice_question.setTarget_(self)
        self.choice_question.setAction_("choiceAsk:")
        self.choice_ask = button("Ask", self, "choiceAsk:", NSMakeRect(218, 12, 70, 26))
        self.choice_question.setHidden_(True)
        self.choice_ask.setHidden_(True)
        self.choice_answer = label("", NSMakeRect(12, 44, 276, 36), 12, NSColor.secondaryLabelColor())
        self.choice_buttons = NSView.alloc().initWithFrame_(NSMakeRect(0, 84, 300, 210))
        for view in (self.choice_name, self.choice_image, self.choice_buttons,
                     self.choice_answer, self.choice_question, self.choice_ask):
            root.addSubview_(view)
        self.choice_panel = panel
        return panel

    @objc.python_method
    def _fill_choice_panel(self, path, ask_jev, box=None):
        self.choice_name.setStringValue_(os.path.basename(path))
        image = NSImage.alloc().initWithContentsOfFile_(path)
        if image is not None:
            self.choice_image.setImage_(image)
            self.choice_image.setHidden_(False)
        else:
            self.choice_image.setImage_(None)
            self.choice_image.setHidden_(True)
        self.choice_question.setHidden_(True)
        self.choice_ask.setHidden_(True)
        self.choice_answer.setStringValue_("")
        for view in list(self.choice_buttons.subviews()):
            view.removeFromSuperview()
        if box is None:
            from commands.video import is_video_extension
            actions = capture_choice_actions(ask_jev=ask_jev, video=is_video_extension(path))
            box = choice_panel_box(actions)
        panel = getattr(self, "choice_panel", None)
        if panel is not None:
            frame = panel.frame()
            width, height = box["size"]
            panel.setFrame_display_(
                NSMakeRect(float(frame.origin.x), float(frame.origin.y), width, height), False)
            root = panel.contentView()
            if root is not None:
                root.setFrame_(NSMakeRect(0, 0, width, height))
        name = box["name"]
        image_box = box["image"]
        buttons = box["buttons"]
        self.choice_name.setFrame_(NSMakeRect(name[0], name[1], name[2], name[3]))
        self.choice_image.setFrame_(NSMakeRect(image_box[0], image_box[1], image_box[2], image_box[3]))
        self.choice_buttons.setFrame_(NSMakeRect(buttons[0], buttons[1], buttons[2], buttons[3]))
        frames = box["frames"]
        host_h = float(self.choice_buttons.frame().size.height)
        for action, x, top, width, height in frames:
            y = host_h - top - height
            if y < 0:
                continue
            item = button(action["title"], self, "captureChoice:", NSMakeRect(x, y, width, height))
            item.setIdentifier_(action["id"])
            if action.get("primary"):
                item.setFont_(NSFont.boldSystemFontOfSize_(13))
            self.choice_buttons.addSubview_(item)

    def captureChoice_(self, sender):
        ident = "" if sender is None else str(sender.identifier() or "")
        if ident == "ask_jev":
            self._open_choice_question()
            return
        self._queue_choice(ident)

    @objc.python_method
    def _open_choice_question(self):
        """Ask Jev on the post-capture panel: reveal the question field and focus it."""
        if getattr(self, "choice_panel", None) is None or not hasattr(self, "choice_question"):
            return
        self.choice_question.setHidden_(False)
        self.choice_ask.setHidden_(False)
        panel = self.choice_panel
        panel.makeKeyAndOrderFront_(None)
        panel.makeFirstResponder_(self.choice_question)
        self._choice_shown_at = time.time()

    def choiceAsk_(self, _sender):
        question = self.choice_question.stringValue() if hasattr(self, "choice_question") else ""
        if not self.worker_started:
            self.choice_answer.setStringValue_("Add your API keys in the main window first.")
            return
        self.controls.put(("ask_jev", question))
        self._choice_shown_at = time.time()

    @objc.python_method
    def _queue_choice(self, ident):
        if str(ident).startswith("video_"):
            threading.Thread(target=self._run_video_kind, args=(str(ident),), daemon=True).start()
            return
        actions = {row["id"]: row for row in capture_choice_actions(ask_jev=True)}
        action = actions.get(ident)
        if not action or not action.get("phrase"):
            return
        if ident == "share_delete":
            self._close_capture_choices()
        if self.worker_started:
            self.controls.put(("text", action["phrase"]))
            return
        threading.Thread(target=self._run_capture_kind, args=(ident,), daemon=True).start()

    @objc.python_method
    def _close_capture_choices(self):
        panel = getattr(self, "choice_panel", None)
        if panel is not None and panel.isVisible():
            panel.orderOut_(None)
        self._choice_shown_at = 0.0

    @objc.python_method
    def _choice_pointer_inside(self):
        panel = getattr(self, "choice_panel", None)
        if panel is None or not panel.isVisible():
            return False
        loc = NSEvent.mouseLocation()
        frame = panel.frame()
        return pointer_inside(
            (float(loc.x), float(loc.y)),
            (float(frame.origin.x), float(frame.origin.y), float(frame.size.width), float(frame.size.height)),
        )

    def homeSubmit_(self, _sender):
        field = getattr(self, "home_field", None)
        if field is None:
            return
        plan = submission(field.stringValue(), "")
        if plan is None:
            return
        field.setStringValue_("")
        if plan["kind"] != "run":
            return
        phrase = plan["control"][1]
        self.typed.note_request(phrase)
        if not self.worker_started:
            self.typed.note_reply("Add your API keys in the main window first.")
            self._refresh_home_history()
            return
        self.controls.put(plan["control"])
        self._refresh_home_history()

    def openCaptures_(self, _sender):
        if self.worker_started:
            self.controls.put(("text", "open my screenshots"))
            return
        threading.Thread(target=self._run_capture_kind, args=("captures_open",), daemon=True).start()

    def pillFieldClicked_(self, _sender):
        self._focus_pill_field()

    @objc.python_method
    def _focus_pill_field(self):
        """Click or Control-Option-J. Caret in the field, main window stays put."""
        panel = getattr(self, "mini_panel", None)
        field = getattr(self, "mini_field", None)
        if panel is None or field is None:
            return
        main = self.panel
        was_visible = bool(main.isVisible())
        was_mini = bool(main.isMiniaturized())
        front, own = self._front_application()
        if not hasattr(self, "pill_keys"):
            self.pill_keys = PillKeyFocus()
        caret = self.pill_keys.focus_field(panel, field, NSApp, front, own)
        self._place_pill_caret(field, caret)
        fix = undo_main_reveal(was_visible, was_mini, bool(main.isVisible()), bool(main.isMiniaturized()))
        if fix == "miniaturize":
            main.miniaturize_(None)
        elif fix == "orderOut":
            main.orderOut_(None)
        if self.bar.should_show() and not panel.isVisible():
            panel.orderFrontRegardless()

    @objc.python_method
    def _place_pill_caret(self, field, caret):
        editor = None
        try:
            editor = field.currentEditor()
        except Exception:
            editor = None
        if editor is None:
            try:
                editor = self.mini_panel.fieldEditor_forObject_(True, field)
            except Exception:
                editor = None
        if editor is None:
            return
        try:
            editor.setSelectedRange_(caret if caret is not None else caret_range(field.stringValue()))
        except Exception:
            pass

    @objc.python_method
    def _front_application(self):
        try:
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
        except Exception:
            return None, False
        if app is None:
            return None, False
        return app, is_our_app(app, os.getpid())

    @objc.python_method
    def _restore_front_app(self):
        keys = getattr(self, "pill_keys", None)
        if keys is None:
            return
        keys.release(NSApp, getattr(self, "mini_panel", None))

    def focusTypeField_(self, _sender):
        panel = getattr(self, "mini_panel", None)
        if self.bar.should_show() and panel is not None and panel.isVisible():
            if getattr(self, "pillCollapsed", False):
                self.expandMiniBar_(None)
                return
            self._focus_pill_field()
            return
        self.showMain_(None)
        self._select_tab("home")
        field = getattr(self, "home_field", None)
        if field is not None:
            self.panel.makeFirstResponder_(field)

    @objc.python_method
    def _refresh_home_history(self):
        view = getattr(self, "home_history", None)
        if view is None or not hasattr(self, "typed"):
            return
        view.setString_(self.typed.text())
        self._refresh_popover_history()

    @objc.python_method
    def _refresh_popover_history(self):
        view = getattr(self, "popover_history", None)
        if view is None or not hasattr(self, "typed"):
            return
        view.setString_(self.typed.text())
        self._refresh_full_window()

    @objc.python_method
    def _layout_popover_footer(self, layout):
        cx, cy, cw, ch = layout["composer"]
        gx, _gy, gw, _gh = layout["greeting"]
        content_w = max(cw, gw)
        content_x = cx - (content_w - cw) / 2.0
        footer = layout.get("footer") or {}
        toolbar = footer.get("toolbar") or {}
        for key, btn_name in (("history", "popover_history_btn"), ("refresh", "popover_refresh_btn")):
            frame = toolbar.get(key)
            btn = getattr(self, btn_name, None)
            if btn is None or not frame:
                continue
            btn.setHidden_(False)
            _place(btn, (content_x + frame[0], frame[1], frame[2], frame[3]))
        scroll = getattr(self, "popover_history_scroll", None)
        hist = footer.get("history")
        if scroll is not None:
            if hist and getattr(self, "_popover_history_open", False):
                scroll.setHidden_(False)
                _place(scroll, (content_x + hist[0], hist[1], hist[2], hist[3]))
                self.popover_history.setFrame_(NSMakeRect(0, 0, hist[2], max(hist[3], 40)))
            else:
                scroll.setHidden_(True)
        chips = footer.get("chips") or []
        pool = getattr(self, "popover_chips", [])
        for index, chip_btn in enumerate(pool):
            if index >= len(chips):
                chip_btn.setHidden_(True)
                continue
            spec = chips[index]
            chip_id = spec.get("id")
            info = POPOVER_CHIPS.get(chip_id, {})
            chip_btn.configure(chip_id, info.get("title", ""), info.get("subtitle", ""))
            fx, fy, fw, fh = spec["frame"]
            chip_btn.setHidden_(False)
            _place(chip_btn, (content_x + fx, fy, fw, fh))

    @objc.python_method
    def _sync_recording_ui(self):
        label = getattr(self, "rec_label", None)
        stop = getattr(self, "rec_stop", None)
        mic = getattr(self, "mini_mic", None)
        if label is None or stop is None or mic is None:
            return
        status = None
        try:
            import commands
            status = commands.recording_status()
        except Exception:
            status = None
        active = bool(status)
        label.setHidden_(not active)
        stop.setHidden_(not active)
        mic.setHidden_(active or getattr(self, "pillCollapsed", False))
        if active:
            label.setStringValue_("\u25cf  " + str(status.get("clock") or ""))
            label.setTextColor_(NSColor.systemRedColor())

    def applicationShouldHandleReopen_hasVisibleWindows_(self, _app, _visible):
        self.showMain_(None)
        return True

    def modeChanged_(self, sender):
        self.mode = MODES[sender.selectedSegment()]
        NSUserDefaults.standardUserDefaults().setObject_forKey_(self.mode, "mode")
        self.hint.setStringValue_(HINTS[self.mode])
        self.controls.put(("mode", self.mode))

    @objc.python_method
    def notify(self, state, detail=""):
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "updateStatus:", {"state": state, "detail": detail}, False
        )

    @objc.python_method
    def _apply_zoe_badge(self):
        """Pink Zoe badge, placeholder, and the Window menu check. Returns whether the mode is on."""
        on = False
        try:
            import commands
            on = bool(commands.zoe_mode_active())
        except Exception:
            on = False
        label = getattr(self, "zoe_label", None)
        if label is not None:
            label.setHidden_(not on)
            if on:
                try:
                    import commands
                    label.setStringValue_(commands.zoe_pill_label(True))
                except Exception:
                    label.setStringValue_("Zoe")
        field = getattr(self, "mini_field", None)
        if field is not None:
            field.setPlaceholderString_("Zoe mode" if on else PLACEHOLDER)
        item = getattr(self, "zoe_item", None)
        if item is not None:
            try:
                import commands
                plan = commands.menu_toggle_plan(on)
            except Exception:
                plan = {"title": "Zoe Mode", "action": "enter", "checked": False}
            title = plan.get("title") or "Zoe Mode"
            if plan.get("action") == "confirm_exit" and not title.endswith("\u2026"):
                title = title + "\u2026"
            item.setTitle_(title)
            item.setState_(1 if plan.get("checked") else 0)
        return on

    @objc.python_method
    def _sync_zoe_ui(self):
        label = getattr(self, "zoe_label", None)
        before = False if label is None else (not bool(label.isHidden()))
        on = self._apply_zoe_badge()
        if on == before or not hasattr(self, "mini_field"):
            return
        panel = getattr(self, "mini_panel", None)
        if panel is None:
            return
        size = panel.frame().size
        self._layout_mini_bar(float(size.width), float(size.height))

    def zoeModeMenu_(self, _sender):
        self._toggle_zoe_mode()

    @objc.python_method
    def _toggle_zoe_mode(self):
        """Enter immediately. Leave only after the confirmation dialog."""
        import commands
        plan = commands.menu_toggle_plan()
        if plan.get("action") == "enter":
            if getattr(self, "worker_started", False):
                self._queue_bar_phrase("zoe mode")
            else:
                line = commands.enter_zoe_mode()
                self._show_zoe_line(line)
            self._sync_zoe_ui()
            return
        if plan.get("action") != "confirm_exit":
            return
        if not self._zoe_exit_dialog(plan):
            self._show_zoe_line(commands.ZOE_STAY_LINE)
            return
        line = commands.leave_zoe_mode()
        self._show_zoe_line(line)
        self._sync_zoe_ui()

    @objc.python_method
    def _zoe_exit_dialog(self, plan):
        """Default button keeps Zoe mode. Only the second button turns it off."""
        alert = NSAlert.alloc().init()
        alert.setMessageText_(plan.get("title") or "Turn Off Zoe Mode")
        alert.setInformativeText_(plan.get("message") or "")
        alert.addButtonWithTitle_(plan.get("cancel") or "Keep Zoe Mode")
        alert.addButtonWithTitle_(plan.get("confirm") or "Turn Off Zoe Mode")
        try:
            alert.buttons()[1].setKeyEquivalent_("")
        except Exception:
            pass
        return int(alert.runModal()) == 1001

    @objc.python_method
    def _show_zoe_line(self, line):
        try:
            import commands
            shown = commands.zoe_plain(line)
        except Exception:
            shown = str(line or "")
        if getattr(self, "mini_field", None) is not None and getattr(self, "mini_panel", None) is not None:
            try:
                if self.mini_panel.isVisible():
                    self._show_bar_reply(shown)
                    return
            except Exception:
                pass
        detail = getattr(self, "detail", None)
        if detail is not None:
            detail.setStringValue_(shown)

    def tick_(self, _timer):
        ptt = getattr(self, "ptt", None)
        if ptt is not None:
            flags_now = hid_modifier_flags()
            token = ptt.watchdog(time.monotonic(), flags_now) if flags_now is not None else None
            if token:
                self._release_ptt(token)
        siri = sys.modules.get("siri")
        timers = siri.timer_snapshot()[:3] if hasattr(siri, "timer_snapshot") else []  # siri may still be loading
        for i, (name_view, time_view) in enumerate(self.timer_rows):
            name_view.setHidden_(i >= len(timers))
            time_view.setHidden_(i >= len(timers))
            if i < len(timers):
                name, left = timers[i]
                m, sec = divmod(int(left + 0.999), 60)
                h, m = divmod(m, 60)
                name_view.setStringValue_(name)
                time_view.setStringValue_(f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}")
        field = getattr(self, "mini_field", None)
        if field is not None and hasattr(self, "bar"):
            had_reply = bool(self.bar.reply)
            if self.bar.reply_due_clear(time.time(), field.stringValue()):
                field.setStringValue_("")
                self._refresh_trailing_symbol()
                # The timer clears text. It collapses only a reply that already
                # reached a terminal status. A slow turn stays open.
                if hasattr(self, "pill") and self.pill.display_cleared() == "collapsed":
                    self._apply_pill_presentation()
            elif had_reply and not self.bar.reply and hasattr(self, "pill") and (
                self.pill.busy or self.pill.showing_reply
            ):
                self.pill.keep_typing()
        self._sync_recording_ui()
        self._sync_choice_dismiss()
        self._sync_action_menu_dismiss()
        self._sync_hint_dismiss()
        self._sync_zoe_ui()
        self._sync_orb()

    @objc.python_method
    def _sync_choice_dismiss(self):
        panel = getattr(self, "choice_panel", None)
        shown = getattr(self, "_choice_shown_at", 0.0)
        if panel is None or not panel.isVisible() or not shown:
            return
        if choice_due(shown, time.time(), self._choice_pointer_inside()):
            self._close_capture_choices()

    def updateStatus_(self, payload):
        state = str(payload["state"])
        detail = str(payload.get("detail", ""))
        self.status.setStringValue_(state)
        self.detail.setStringValue_(_hold_option_detail(self, state, detail))
        self.dot.setTextColor_(STATUS_COLORS.get(state, NSColor.labelColor()))
        if state in ("Dictating", "Finishing"):
            self.bubble.show(working=state == "Finishing")
        else:
            self.bubble.hide()
        shown = reply_text(state, detail)
        if shown and getattr(self, "typed", None) is not None and self.typed.pending:
            self.typed.note_reply(shown)
            self._refresh_home_history()
            self._refresh_full_window()
        option_down = bool(getattr(self, "option_down", False))
        show_line = bool(shown) and status_shows_in_pill(state, option_down)
        displayed = False
        if show_line and getattr(self, "mini_panel", None) is not None and self.mini_panel.isVisible():
            displayed = True
            if hasattr(self, "pill") and self.pill.collapsed:
                self.pill.reveal_reply()
                self._apply_pill_presentation(animate_open=True)
            elif hasattr(self, "pill"):
                self.pill.reveal_reply()
            self._show_bar_reply(shown)
        elif getattr(self, "mini_mic", None) is not None:
            self._refresh_trailing_symbol()
        if hasattr(self, "pill") and self.pill.busy:
            if self.pill.note_status(state, displayed) == "collapsed":
                self._apply_pill_presentation()
        held = bool(getattr(self, "option_down", False) or getattr(self, "_mini_mic_held", False))
        if meter_active(state, held):
            self._sync_level_meter(True)
        else:
            self._sync_level_meter(False)
        if shown and getattr(self, "choice_answer", None) is not None:
            panel = getattr(self, "choice_panel", None)
            if panel is not None and panel.isVisible() and not capture_saved(shown):
                self.choice_answer.setStringValue_(shown)
        self._maybe_show_choices(detail)
        self._sync_orb()

    def applicationShouldTerminateAfterLastWindowClosed_(self, _application):
        return False  # keep listening with the window closed, the Dock icon reopens it

    def applicationShouldTerminate_(self, _sender):
        if hasattr(self, "bar"):
            self.bar.quit()
            self._apply_bar_visibility()
        return 1  # NSTerminateNow. Closing the window is not quitting.

    def applicationWillTerminate_(self, _notification):
        orb = getattr(self, "orb_view", None)
        if orb is not None:
            orb.stop()
        timer = getattr(self, "_listen_timer", None)
        if timer is not None:
            timer.invalidate()
            self._listen_timer = None
        meter = getattr(self, "_meter_timer", None)
        if meter is not None:
            meter.invalidate()
            self._meter_timer = None
        fade = getattr(self, "_fade_timer", None)
        if fade is not None:
            fade.invalidate()
            self._fade_timer = None
        self._bar_fade_done = None
        if getattr(self, "_pill_watched", False):
            NSWorkspace.sharedWorkspace().notificationCenter().removeObserver_(self)
            self._pill_watched = False
        if hasattr(self, "bar"):
            self.bar.quit()
            self._apply_bar_visibility()
        if getattr(self, "global_monitor", None):
            NSEvent.removeMonitor_(self.global_monitor)
        if getattr(self, "local_monitor", None):
            NSEvent.removeMonitor_(self.local_monitor)
        if getattr(self, "key_monitor", None):
            NSEvent.removeMonitor_(self.key_monitor)
        if getattr(self, "type_monitor", None) is not None:
            NSEvent.removeMonitor_(self.type_monitor)
        if getattr(self, "area_hotkey", None) is not None:
            self.area_hotkey.unregister()


    def checkForUpdates_(self, _sender):
        """One read of the public compare API. Does not download or apply anything."""
        if getattr(self, "_update_checking", False):
            return
        self._update_checking = True
        button = getattr(self, "update_button", None)
        if button is not None:
            button.setEnabled_(False)
            button.setTitle_("Checking\u2026")
        threading.Thread(target=self._fetch_updates, daemon=True).start()

    @objc.python_method
    def _fetch_updates(self):
        try:
            result = check_upstream()
        except Exception:
            result = {
                "kind": "network",
                "title": "Couldn't check",
                "body": "Couldn't reach GitHub. Check the network and try again.",
                "open_url": "",
            }
        self.performSelectorOnMainThread_withObject_waitUntilDone_("showUpdateResult:", result, False)

    def showUpdateResult_(self, result):
        self._update_checking = False
        button = getattr(self, "update_button", None)
        if button is not None:
            button.setEnabled_(True)
            button.setTitle_("Check for updates")
        try:
            title = str(result["title"] or "")
        except Exception:
            title = "Couldn't check"
        try:
            body = str(result["body"] or "")
        except Exception:
            body = ""
        try:
            open_url = safe_browser_url(result["open_url"])
        except Exception:
            open_url = ""
        alert = NSAlert.alloc().init()
        alert.setMessageText_(title or "Couldn't check")
        alert.setInformativeText_(body)
        alert.addButtonWithTitle_("OK")
        if open_url:
            alert.addButtonWithTitle_("Open on GitHub")
        response = alert.runModal()
        if open_url and int(response) == 1001:
            NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(open_url))


class ClipboardMenuController(NSObject):
    """Fills the Clipboard History menu when it opens. Titles are previews only."""

    def menuNeedsUpdate_(self, menu):
        self._refill(menu)

    @objc.python_method
    def _refill(self, menu):
        while menu.numberOfItems() > 0:
            menu.removeItemAtIndex_(0)
        entries = ()
        paused = False
        try:
            import commands
            entries = commands.clipboard_menu_entries()
            paused = commands.clipboard_is_paused()
        except Exception:
            entries = ()
            paused = False
        spec = clipboard_menu(entries, paused)
        delegate = NSApp.delegate()
        for item in spec.get("items") or ():
            kind = item.get("kind")
            if kind == "separator":
                menu.addItem_(NSMenuItem.separatorItem())
                continue
            title = item.get("title") or ""
            entry = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
            entry.setEnabled_(kind != "clipboard_empty")
            if kind == "clipboard_item":
                entry.setAction_("clipboardMenuItem:")
                entry.setRepresentedObject_(item.get("id") or "")
            elif kind == "text":
                entry.setAction_("clipboardMenuPhrase:")
                entry.setRepresentedObject_(item.get("id") or "")
            if delegate is not None and entry.action():
                entry.setTarget_(delegate)
            menu.addItem_(entry)


_clipboard_menu_controller = None


def build_menu():
    """App, Clipboard History, and Edit menus, so Cmd+Q works and Cmd+V pastes into the key fields."""
    global _clipboard_menu_controller
    bar = NSMenu.alloc().init()
    app_item = NSMenuItem.alloc().init()
    bar.addItem_(app_item)
    app_menu = NSMenu.alloc().init()
    app_menu.addItemWithTitle_action_keyEquivalent_("Check for Updates\u2026", "checkForUpdates:", "")
    app_menu.addItemWithTitle_action_keyEquivalent_("Quit Hey Jev", "terminate:", "q")
    app_item.setSubmenu_(app_menu)
    clip_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Clipboard History", None, "")
    bar.addItem_(clip_item)
    clip = NSMenu.alloc().initWithTitle_("Clipboard History")
    clip.setAutoenablesItems_(False)
    _clipboard_menu_controller = ClipboardMenuController.alloc().init()
    clip.setDelegate_(_clipboard_menu_controller)
    clip_item.setSubmenu_(clip)
    edit_item = NSMenuItem.alloc().init()
    bar.addItem_(edit_item)
    edit = NSMenu.alloc().initWithTitle_("Edit")
    for title, action, key in (("Undo", "undo:", "z"), ("Cut", "cut:", "x"), ("Copy", "copy:", "c"),
                               ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")):
        edit.addItemWithTitle_action_keyEquivalent_(title, action, key)
    edit_item.setSubmenu_(edit)
    NSApp.setMainMenu_(bar)


def run_app():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)  # shows in the Dock with a menu bar
    build_menu()
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()
