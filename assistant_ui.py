"""Native macOS window for the Jev voice assistant: status on top, sidebar tabs for the dictionary, apps, history and keys.

The window is resizable. Frames come from assistant_layout so a smaller window
reflows instead of clipping. The frame is saved under HeyJevMainWindow, and a
missing or offscreen frame is centered.
"""
import json
import os
import re
import queue
import sys
import threading
import time

import objc
from AppKit import (
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
    NSEventModifierFlagOption,
    NSEventMaskLeftMouseDragged,
    NSEventMaskLeftMouseUp,
    NSEventTypeLeftMouseUp,
    NSFont,
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
    NSView,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectStateFollowsWindowActiveState,
    NSVisualEffectView,
    NSWindow,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskFullSizeContentView,
    NSWindowStyleMaskMiniaturizable,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskNonactivatingPanel,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeSize, NSObject, NSTimer, NSUserDefaults
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
    BAR_H,
    BAR_W,
    ORIGIN_KEY,
    PLACEHOLDER,
    PREF_KEY,
    BarController,
    BAR_COLLECTION,
    bar_controls,
    drag_origin,
    enabled_from_pref,
    format_origin,
    mic_event,
    parse_origin,
    place_bar,
    reply_text,
    submission,
)
from secrets_store import KEY_NAMES, OPTIONAL, get_secret, missing_secrets, save_secret


NORMAL, FLOATING = 0, 3  # NSNormalWindowLevel, NSFloatingWindowLevel
BAR_LEVEL = 25  # NSStatusWindowLevel, above the main window even when that one floats
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
          "Say “stop transcribing” and it pastes where your cursor is.")
PRIVACY = (
    ("Stays on your Mac", "Everything the mic hears. Whisper listens for \u201cHey Jev\u201d on your Mac and throws away anything that isn't for her. Your dictionary, dictation history and logs stay in this folder and ~/Library/Logs."),
    ("TypeSafe (Jev)  \u00b7  text", "Only the words after \u201cHey Jev\u201d, like \u201copen Spotify\u201d, to work out what to do."),
    ("OpenRouter or OpenAI  \u00b7  audio", "Dictation audio, only between \u201ctranscribe\u201d and \u201cstop transcribing\u201d. It goes to OpenAI directly if you added that key, otherwise through OpenRouter. Questions that aren't commands go to Claude Haiku on OpenRouter as text."),
    ("Fish Audio  \u00b7  text", "The text of her replies, to turn into her voice. Scripted replies are saved after the first time, so most are never sent again."),
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


class MiniBarBackground(NSView):
    """Dark rounded pill. A click on the background or an edge drags it.

    The + button, the text field, and the mic sit on top and keep their own clicks.
    A nonactivating panel ignores the normal title-bar drag, so this tracks the
    mouse in screen coordinates and moves the frame itself. That works across displays.
    """

    def drawRect_(self, _rect):
        try:
            bounds = self.bounds()
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bounds, bounds.size.height / 2, bounds.size.height / 2)
            NSColor.colorWithCalibratedWhite_alpha_(0.10, 0.94).setFill()
            path.fill()
            NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.18).setStroke()
            path.setLineWidth_(1.0)
            path.stroke()
        except Exception as exc:
            print(f"  mini bar draw failed: {exc}")

    def mouseDown_(self, event):
        window = self.window()
        if window is None:
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


class HoldMicButton(NSButton):
    """Mouse down and up map to the same press and release as right Option."""

    def mouseDown_(self, event):
        target = self.target()
        if target is not None:
            target.miniMicDown_(self)
        try:
            objc.super(HoldMicButton, self).mouseDown_(event)
        finally:
            if target is not None:
                target.miniMicUp_(self)


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
    def applicationDidFinishLaunching_(self, _notification):
        self.controls = queue.Queue()
        self.option_down = False
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
        self._main_closing = False
        self.bar = BarController(enabled=enabled_from_pref(defaults.objectForKey_(PREF_KEY)))
        self.on_top = defaults.boolForKey_("keep_on_top")
        self.panel.setLevel_(FLOATING if self.on_top else NORMAL)
        self._add_window_menu()
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
        self._sync_mini_bar()
        if missing_secrets():
            self.updateStatus_({"state": "Starting", "detail": "Add your API keys to begin"})
        else:
            self._start_worker()

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
        page = self._page("settings", "Settings", "Pick the microphone Jev listens with. It switches straight away.")
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
            _place(self.mini_name, page["mini_name"])
            _place(self.mini_hint, page["mini_hint"])
            _place(self.mini_toggle, page["mini_toggle"])
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
        panel = getattr(self, "mini_panel", None)
        if event.keyCode() == 53 and panel is not None and panel.isKeyWindow():
            self.miniDismiss_(None)
            return None
        return event

    @objc.python_method
    def _handle_flags(self, event):
        if event.keyCode() != 61:
            return
        is_down = bool(event.modifierFlags() & NSEventModifierFlagOption)
        if is_down != self.option_down:
            self.option_down = is_down
            self.controls.put("press" if is_down else "release")

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
        menu.addItemWithTitle_action_keyEquivalent_("Hide Mini Bar", "hideMiniBar:", "").setTarget_(self)
        item.setSubmenu_(menu)
        NSApp.setWindowsMenu_(menu)

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

    def miniBarChanged_(self, sender):
        enabled = sender.state() == 1
        NSUserDefaults.standardUserDefaults().setBool_forKey_(enabled, PREF_KEY)
        self.bar.set_enabled(enabled)
        self._sync_mini_bar()

    @objc.python_method
    def _build_mini_bar(self):
        """Always-on-top pill. Nonactivating, so typing in it does not raise the main window."""
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        self.mini_panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, BAR_W, BAR_H), style, NSBackingStoreBuffered, False
        )
        self.mini_panel.setLevel_(BAR_LEVEL)
        self.mini_panel.setOpaque_(False)
        self.mini_panel.setBackgroundColor_(NSColor.clearColor())
        self.mini_panel.setHasShadow_(True)
        self.mini_panel.setFloatingPanel_(True)
        self.mini_panel.setHidesOnDeactivate_(False)
        self.mini_panel.setBecomesKeyOnlyIfNeeded_(True)
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
        appearance = NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua")
        if appearance is not None:
            self.mini_panel.setAppearance_(appearance)
        self.mini_panel.setDelegate_(self)
        root = MiniBarBackground.alloc().initWithFrame_(NSMakeRect(0, 0, BAR_W, BAR_H))
        self.mini_panel.setContentView_(root)
        frames = bar_controls()
        self.mini_plus = NSButton.buttonWithTitle_target_action_("+", self, "showMain:")
        self.mini_plus.setBordered_(False)
        self.mini_plus.setFont_(NSFont.systemFontOfSize_weight_(20, 0.3))
        if hasattr(self.mini_plus, "setContentTintColor_"):
            self.mini_plus.setContentTintColor_(NSColor.whiteColor())
        root.addSubview_(self.mini_plus)
        _place(self.mini_plus, frames["plus"])
        self.mini_field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.mini_field.setCell_(CenteredFieldCell.alloc().initTextCell_(""))
        self.mini_field.setBezeled_(False)
        self.mini_field.setDrawsBackground_(False)
        self.mini_field.setFocusRingType_(1)  # none
        self.mini_field.setEditable_(True)
        self.mini_field.setSelectable_(True)
        self.mini_field.setPlaceholderString_(PLACEHOLDER)
        self.mini_field.setFont_(NSFont.systemFontOfSize_(14))
        self.mini_field.setTextColor_(NSColor.whiteColor())
        self.mini_field.setTarget_(self)
        self.mini_field.setAction_("miniSubmit:")
        self.mini_field.setDelegate_(self)
        root.addSubview_(self.mini_field)
        _place(self.mini_field, frames["field"])
        self.mini_mic = HoldMicButton.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.mini_mic.setBordered_(False)
        self.mini_mic.setTarget_(self)
        symbol = None
        try:
            symbol = NSImage.imageWithSystemSymbolName_accessibilityDescription_("mic.fill", "Listen")
        except Exception:
            symbol = None
        if symbol is not None:
            self.mini_mic.setImage_(symbol)
            self.mini_mic.setImagePosition_(1)  # image only
            if hasattr(self.mini_mic, "setContentTintColor_"):
                self.mini_mic.setContentTintColor_(NSColor.whiteColor())
        else:
            self.mini_mic.setTitle_("Mic")
        root.addSubview_(self.mini_mic)
        _place(self.mini_mic, frames["mic"])
        self._mini_mic_held = False

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
        else:
            panel.orderOut_(None)

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
    def _order_bar_front(self):
        screens = self._visible_screens()
        if not screens:
            return
        saved = parse_origin(NSUserDefaults.standardUserDefaults().stringForKey_(ORIGIN_KEY))
        x, y = place_bar(saved, screens)
        self.mini_panel.setFrameOrigin_(NSMakePoint(x, y))
        self.mini_panel.orderFrontRegardless()

    @objc.python_method
    def _show_bar_reply(self, text):
        self.bar.note_reply(text, time.time())
        self.mini_field.setStringValue_(text)

    def miniSubmit_(self, _sender):
        # Runs the line where it was typed. Does not deminiaturize or order the main window front.
        plan = submission(self.mini_field.stringValue(), self.bar.reply)
        if plan is None:
            return
        self.bar.reply = ""
        self.mini_field.setStringValue_("")
        if plan["kind"] != "run":
            return
        if not self.worker_started:
            self._show_bar_reply("Add your API keys in the main window first.")
            return
        self.controls.put(plan["control"])

    def miniMicDown_(self, _sender):
        if self._mini_mic_held:
            return
        self._mini_mic_held = True
        self.controls.put(mic_event("down"))

    def miniMicUp_(self, _sender):
        if not self._mini_mic_held:
            return
        self._mini_mic_held = False
        self.controls.put(mic_event("up"))

    def miniDismiss_(self, _sender):
        self.bar.dismiss()
        self._apply_bar_visibility()

    def control_textView_doCommandBySelector_(self, control, _view, selector):
        if control == getattr(self, "mini_field", None) and str(selector) == "cancelOperation:":
            self.miniDismiss_(control)
            return True
        return False

    def windowDidMiniaturize_(self, notification):
        if notification.object() == self.panel:
            self._sync_mini_bar()

    def windowDidDeminiaturize_(self, notification):
        if notification.object() == self.panel:
            self._main_closing = False
            self._sync_mini_bar()

    def windowWillClose_(self, notification):
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
        origin = panel.frame().origin
        NSUserDefaults.standardUserDefaults().setObject_forKey_(format_origin(origin.x, origin.y), ORIGIN_KEY)

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

    def tick_(self, _timer):
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
        if field is not None and self.bar.reply_due_clear(time.time(), field.stringValue()):
            field.setStringValue_("")

    def updateStatus_(self, payload):
        state = str(payload["state"])
        detail = str(payload.get("detail", ""))
        self.status.setStringValue_(state)
        self.detail.setStringValue_(detail)
        self.dot.setTextColor_(STATUS_COLORS.get(state, NSColor.labelColor()))
        if state in ("Dictating", "Finishing"):
            self.bubble.show(working=state == "Finishing")
        else:
            self.bubble.hide()
        shown = reply_text(state, detail)
        if shown and getattr(self, "mini_panel", None) is not None and self.mini_panel.isVisible():
            self._show_bar_reply(shown)

    def applicationShouldTerminateAfterLastWindowClosed_(self, _application):
        return False  # keep listening with the window closed, the Dock icon reopens it

    def applicationShouldTerminate_(self, _sender):
        if hasattr(self, "bar"):
            self.bar.quit()
            self._apply_bar_visibility()
        return 1  # NSTerminateNow. Closing the window is not quitting.

    def applicationWillTerminate_(self, _notification):
        if hasattr(self, "bar"):
            self.bar.quit()
            self._apply_bar_visibility()
        if getattr(self, "global_monitor", None):
            NSEvent.removeMonitor_(self.global_monitor)
        if getattr(self, "local_monitor", None):
            NSEvent.removeMonitor_(self.local_monitor)
        if getattr(self, "key_monitor", None):
            NSEvent.removeMonitor_(self.key_monitor)


def build_menu():
    """App and Edit menus, so Cmd+Q works and Cmd+V pastes into the key fields."""
    bar = NSMenu.alloc().init()
    app_item = NSMenuItem.alloc().init()
    bar.addItem_(app_item)
    app_menu = NSMenu.alloc().init()
    app_menu.addItemWithTitle_action_keyEquivalent_("Quit Hey Jev", "terminate:", "q")
    app_item.setSubmenu_(app_menu)
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
