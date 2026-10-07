"""Show and hide rules for the floating command bar.

No AppKit. The window asks this before it orders the pill on or off, and before
a Return press is handed to the assistant. A typed line is queued as a normal
turn, the same path as something she heard. Size and position are plain
numbers the window stores. Nothing here opens a socket.
"""

BAR_W = 420.0
BAR_H = 44.0
# Wide enough for +, a short command, and the mic. Tall enough that the
# buttons stay clear of the resize grip. The max keeps a tall pill a pill.
BAR_MIN_W = 280.0
BAR_MIN_H = 40.0
BAR_MAX_W = 720.0
BAR_MAX_H = 64.0
# Outer band of the pill. A drag here resizes. Just inside it, the background
# still moves the pill. The text field and the buttons are inset past this.
BAR_GRIP = 6.0
# Visible-frame origin is already above the Dock. The extra gap leaves room
# for the dictation bubble, which sits in that same bottom-center spot.
DOCK_GAP = 72.0
PLACEHOLDER = "Type to Jev\u2026"
# Control-Option-J. Works while another app is in front, so he can type without speaking.
TYPE_KEY_CODE = 38
TYPE_FLAG_CONTROL = 1 << 18
TYPE_FLAG_OPTION = 1 << 19
TYPE_FLAG_COMMAND = 1 << 20
CHOICE_SECONDS = 20.0
REPLY_SECONDS = 4.0
PREF_KEY = "mini_bar_enabled"
ORIGIN_KEY = "mini_bar_origin"
SIZE_KEY = "mini_bar_size"

# Status lines worth putting in the field. Idle "ready" lines are not a reply.
_SHOW_STATES = {
    "Speaking",
    "Ready",
    "Something went wrong",
    "Listening",
    "Transcribing",
    "Thinking",
    "Doing it",
    "Time's up",
    "Dictating",
    "Finishing",
}
_IDLE_READY = {
    "Say \u201cHey Jev\u201d and your command",
    "Ready when you are",
}


def enabled_from_pref(value):
    """Missing preference is on. An explicit 0 is off."""
    if value is None:
        return True
    try:
        return bool(int(value))
    except (TypeError, ValueError):
        return True


def parse_origin(text):
    """'x y' from preferences, or None."""
    if text is None:
        return None
    parts = str(text).split()
    if len(parts) != 2:
        return None
    try:
        return (float(parts[0]), float(parts[1]))
    except ValueError:
        return None


def format_origin(x, y):
    return f"{float(x):.1f} {float(y):.1f}"


def default_size():
    return (BAR_W, BAR_H)


def clamp_size(width, height):
    """Width and height pulled inside the min and max. The default already is."""
    return (
        min(BAR_MAX_W, max(BAR_MIN_W, float(width))),
        min(BAR_MAX_H, max(BAR_MIN_H, float(height))),
    )


def parse_size(text):
    """'w h' from preferences, clamped, or None when it is not two numbers."""
    if text is None:
        return None
    parts = str(text).split()
    if len(parts) != 2:
        return None
    try:
        return clamp_size(float(parts[0]), float(parts[1]))
    except ValueError:
        return None


def format_size(width, height):
    w, h = clamp_size(width, height)
    return f"{w:.1f} {h:.1f}"


def remembered_size(text):
    """Saved size, or the default pill. An out-of-range save is clamped."""
    size = parse_size(text)
    if size is None:
        return default_size()
    return size


def _intersection_area(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    return (x2 - x1) * (y2 - y1)


def default_origin(visible, size=None):
    """Bottom-center of a screen's visible frame (x, y, w, h)."""
    width, _height = clamp_size(*(size or default_size()))
    vx, vy, vw, _vh = visible
    return (vx + (vw - width) / 2.0, vy + DOCK_GAP)


def _as_screens(visible):
    """One (x, y, w, h) frame, or a list of them. The first is the fallback screen."""
    if not visible:
        return []
    first = visible[0]
    if isinstance(first, (int, float)):
        return [tuple(float(v) for v in visible)]
    return [tuple(float(v) for v in screen) for screen in visible]


def place_bar(saved, visible, size=None):
    """Remembered origin when most of the pill is still on any screen.

    `visible` is one screen's visible frame, or several (a second display
    included). An origin that misses every screen is bottom-center of the first.
    `size` is the pill's width and height. A missing size is the default pill.
    """
    screens = _as_screens(visible)
    width, height = clamp_size(*(size or default_size()))
    if not screens:
        return (0.0, DOCK_GAP)
    fallback = default_origin(screens[0], (width, height))
    if not saved:
        return fallback
    frame = (float(saved[0]), float(saved[1]), width, height)
    needed = 0.5 * width * height
    if any(_intersection_area(frame, screen) >= needed for screen in screens):
        return (frame[0], frame[1])
    return fallback


def drag_origin(origin, start, now):
    """Window origin after a drag. All three are screen points (x, y). No clamping."""
    return (float(origin[0]) + float(now[0]) - float(start[0]),
            float(origin[1]) + float(now[1]) - float(start[1]))


def reset_origin(visible):
    """Bottom-center of the main screen. `visible` is that screen, or main first."""
    return place_bar(None, visible)


def resize_edges(x, y, size=None):
    """Outer edges under the pointer: 'left', 'right', 'bottom', 'top'.

    A corner is two of those. Empty when the pointer is inside the grip, on a
    control, or the caller has not asked yet. Width and height are the pill.
    """
    width, height = clamp_size(*(size or default_size()))
    edges = set()
    if width > BAR_GRIP * 2.0:
        if x < BAR_GRIP:
            edges.add("left")
        elif x >= width - BAR_GRIP:
            edges.add("right")
    if height > BAR_GRIP * 2.0:
        if y < BAR_GRIP:
            edges.add("bottom")
        elif y >= height - BAR_GRIP:
            edges.add("top")
    return frozenset(edges)


def resize_frame(frame, edges, start, now):
    """Pill frame (x, y, w, h) after dragging `edges`. Screen points, y up.

    The edge that was not grabbed stays put. Width and height are clamped, so
    a hard pull cannot save a size outside the min and max.
    """
    x, y, w, h = (float(v) for v in frame)
    grabbed = set(edges or ())
    dx = float(now[0]) - float(start[0])
    dy = float(now[1]) - float(start[1])
    left, right = x, x + w
    bottom, top = y, y + h
    if "left" in grabbed:
        left += dx
    if "right" in grabbed:
        right += dx
    if "bottom" in grabbed:
        bottom += dy
    if "top" in grabbed:
        top += dy
    width, height = clamp_size(right - left, top - bottom)
    if "left" in grabbed and "right" not in grabbed:
        left = right - width
    else:
        right = left + width
    if "bottom" in grabbed and "top" not in grabbed:
        bottom = top - height
    else:
        top = bottom + height
    return (left, bottom, width, height)


def background_action(click_count, x, y, controls=None, size=None):
    """What a click on the pill does.

    The outer grip resizes, including a double-click there. A double-click on
    the background inside that grip recenters the pill and restores its default
    size. A single click on that background drags. The text field and the
    buttons keep their own clicks.
    """
    frames = controls if controls is not None else bar_controls(size)
    if hit_control(x, y, frames) is not None:
        return "control"
    if resize_edges(x, y, size):
        return "resize"
    try:
        count = int(click_count)
    except (TypeError, ValueError):
        count = 1
    if count >= 2:
        return "reset"
    return "drag"


# NSWindowCollectionBehaviorCanJoinAllSpaces | FullScreenAuxiliary | Stationary.
# Stationary keeps the pill from hopping when Spaces change; the other two put
# it on every Space, including over a full-screen app.
CAN_JOIN_ALL_SPACES = 1
FULL_SCREEN_AUXILIARY = 256
BAR_COLLECTION = CAN_JOIN_ALL_SPACES | FULL_SCREEN_AUXILIARY | 16


def attachments_supported():
    """False. A typed turn is one string, so a picture or a file cannot ride along.

    The + menu therefore saves a screenshot and says so, and it does not offer
    Attach File. Nothing here calls the network or the Keychain.
    """
    return False


def pill_chrome(glass_available, reduce_transparency, increase_contrast=False, reduce_motion=False):
    """Backing for the pill.

    glass: NSGlassEffectView on macOS 26 and later.
    vibrancy: NSVisualEffectView HUD material, behind the window, when that
    class is missing.
    solid: Reduce Transparency. Increase Contrast thickens the hairline.
    motion is off when Reduce Motion is on, so the pulse and the fade stay still.
    """
    if reduce_transparency:
        material = "solid"
    elif glass_available:
        material = "glass"
    else:
        material = "vibrancy"
    return {
        "material": material,
        "highlight": True,
        "contrast_border": bool(increase_contrast),
        "motion": not bool(reduce_motion),
    }


def trailing_symbol(listening, field_text, shown_reply=""):
    """SF Symbol for the button on the right of the field.

    Waveform while the mic is down. A send arrow when the field has a command
    that is not the reply already showing. Otherwise the mic.
    """
    if listening:
        return "waveform"
    cleaned = " ".join(str(field_text or "").split())
    reply = " ".join(str(shown_reply or "").split())
    if cleaned and cleaned != reply:
        return "arrow.up.circle.fill"
    return "mic.fill"


def _menu_text(item_id, title, phrase, symbol):
    return {"id": item_id, "title": title, "kind": "text", "phrase": phrase, "symbol": symbol, "key": ""}


def _menu_action(item_id, title, kind, symbol, key=""):
    return {"id": item_id, "title": title, "kind": kind, "phrase": "", "symbol": symbol, "key": key}


def capture_saved(sentence):
    """True for a new screenshot or recording, not for a later Notes save."""
    text = " ".join(str(sentence or "").split())
    return text.startswith("Saved a ") or text.startswith("Saved the recording")


def choice_due(shown_at, now, hovered):
    """The choices panel closes after CHOICE_SECONDS unless the pointer is over it."""
    if hovered:
        return False
    return float(now) - float(shown_at) >= CHOICE_SECONDS


def pointer_inside(point, frame):
    x, y = point
    fx, fy, fw, fh = frame
    return fx <= x < fx + fw and fy <= y < fy + fh


def choice_origin(anchor, screen, panel_size, gap=8.0):
    """Put the panel above the pill, clamped to the visible screen."""
    px, py, pw, ph = anchor
    sx, sy, sw, sh = screen
    width, height = panel_size
    x = px + (pw - width) / 2.0
    y = py + ph + gap
    if y + height > sy + sh - 8.0:
        y = py - gap - height
    x = min(max(x, sx + 8.0), sx + sw - width - 8.0)
    y = min(max(y, sy + 8.0), sy + sh - height - 8.0)
    return (x, y)


def capture_choice_actions(ask_jev=True):
    """Buttons on the post-capture panel. Ask Jev is first and highlighted."""
    rows = []
    if ask_jev:
        rows.append({
            "id": "ask_jev", "title": "Ask Jev", "primary": True, "phrase": "",
        })
    rows.extend((
        {"id": "share_notes", "title": "Save to Notes", "primary": False, "phrase": "save it to notes"},
        {"id": "share_email", "title": "Email draft", "primary": False, "phrase": "email it"},
        {"id": "share_imessage", "title": "iMessage draft", "primary": False, "phrase": "text it"},
        {"id": "share_finder", "title": "Show in Finder", "primary": False, "phrase": "show it in finder"},
        {"id": "share_copy", "title": "Copy", "primary": False, "phrase": "copy the screenshot"},
        {"id": "share_delete", "title": "Delete", "primary": False, "phrase": "delete the screenshot"},
        {"id": "ask_siri", "title": "Ask Siri", "primary": False, "phrase": "ask siri about this"},
        {"id": "ask_google", "title": "Ask Google", "primary": False, "phrase": "google this"},
        {"id": "ask_gemini", "title": "Ask Gemini", "primary": False, "phrase": "ask gemini about this"},
        {"id": "ask_chatgpt", "title": "Ask ChatGPT", "primary": False, "phrase": "ask chatgpt about this"},
        {"id": "ask_claude", "title": "Ask Claude", "primary": False, "phrase": "ask claude about this"},
        {"id": "captures_open", "title": "Open Captures Folder", "primary": False, "phrase": "open my screenshots"},
    ))
    return rows


def choice_button_frames(actions, width=300.0, margin=12.0):
    """(action, x, top, w, h) from the top of the button stack. Ask Jev is full width."""
    frames = []
    top = 0.0
    col_w = (width - 2.0 * margin - 8.0) / 2.0
    rest = []
    for action in actions:
        if action.get("primary"):
            frames.append((action, margin, top, width - 2.0 * margin, 28.0))
            top += 34.0
        else:
            rest.append(action)
    index = 0
    while index < len(rest):
        action = rest[index]
        if action["id"] == "captures_open":
            frames.append((action, margin, top, width - 2.0 * margin, 26.0))
            top += 32.0
            index += 1
            continue
        frames.append((action, margin, top, col_w, 24.0))
        nxt = index + 1
        if nxt < len(rest) and rest[nxt]["id"] != "captures_open":
            frames.append((rest[nxt], margin + col_w + 8.0, top, col_w, 24.0))
            index += 2
        else:
            index += 1
        top += 28.0
    return frames, top


def type_focus_hotkey(key_code, flags):
    """Control-Option-J, without Command, focuses the type field."""
    try:
        code = int(key_code)
        bits = int(flags)
    except (TypeError, ValueError):
        return False
    if code != TYPE_KEY_CODE:
        return False
    if not (bits & TYPE_FLAG_CONTROL) or not (bits & TYPE_FLAG_OPTION):
        return False
    if bits & TYPE_FLAG_COMMAND:
        return False
    return True


class TypedHistory:
    """A short list of typed lines and the replies that came back."""

    def __init__(self, limit=8):
        self.limit = int(limit)
        self.rows = []
        self.pending = ""

    def note_request(self, text):
        cleaned = " ".join(str(text or "").split())
        if not cleaned:
            return ""
        self.pending = cleaned
        self.rows.append(("you", cleaned))
        self._trim()
        return cleaned

    def note_reply(self, text):
        """Record one reply for the open request. A second status line does not duplicate it."""
        if not self.pending:
            return ""
        cleaned = " ".join(str(text or "").split())
        if not cleaned:
            return ""
        self.rows.append(("jev", cleaned))
        self.pending = ""
        self._trim()
        return cleaned

    def text(self):
        lines = []
        for who, line in self.rows:
            prefix = "You" if who == "you" else "Jev"
            lines.append("{0}: {1}".format(prefix, line))
        return "\n".join(lines)

    def _trim(self):
        extra = len(self.rows) - self.limit
        if extra > 0:
            self.rows = self.rows[extra:]


def _capture_follow_rows():
    """Share and Ask rows for the capture that was just saved."""
    return (
        _menu_action("ask_jev", "Ask Jev", "ask_jev", "sparkles"),
        _menu_action("share_notes", "Save to Notes", "share_notes", "note.text"),
        _menu_action("share_email", "Email\u2026", "share_email", "envelope"),
        _menu_action("share_imessage", "iMessage\u2026", "share_imessage", "message"),
        _menu_action("share_finder", "Show in Finder", "share_finder", "folder"),
        _menu_action("share_copy", "Copy", "share_copy", "doc.on.doc"),
        _menu_action("share_delete", "Delete", "share_delete", "trash"),
        {"kind": "separator"},
        {
            "id": "ask_capture",
            "title": "Ask\u2026",
            "kind": "submenu",
            "symbol": "questionmark.circle",
            "items": _ask_items("ask_capture"),
        },
    )


def _ask_items(prefix):
    return (
        _menu_action(prefix + "_chatgpt", "Ask ChatGPT", prefix + "_chatgpt", "bubble.left"),
        _menu_action(prefix + "_claude", "Ask Claude", prefix + "_claude", "bubble.left"),
        _menu_action(prefix + "_gemini", "Ask Gemini", prefix + "_gemini", "sparkle"),
        _menu_action(prefix + "_siri", "Ask Siri", prefix + "_siri", "waveform"),
        _menu_action(prefix + "_google", "Ask Google", prefix + "_google", "magnifyingglass"),
    )


def capture_follow_up_items():
    """The glass menu under the pill after a screenshot or recording is saved."""
    return _capture_follow_rows()


def plus_menu(can_attach=None, recording=False):
    """Items for the + button. Only commands the app already runs.

    `can_attach` defaults to attachments_supported(). Attach File is included
    only when that is true. Screenshot does not pretend to send the picture.
    No item sends money or reads My Love. Mail and Messages stay unsent.
    """
    if can_attach is None:
        can_attach = attachments_supported()
    shots = (
        _menu_action("screenshot_full", "Full Screen", "screenshot_full", "camera.viewfinder"),
        _menu_action("screenshot_area", "Area", "screenshot_area", "selection.pin.in.out"),
        _menu_action("screenshot_window", "Window", "screenshot_window", "macwindow"),
    )
    if recording:
        record = _menu_action("record_stop", "Stop Screen Recording", "record_stop", "stop.circle.fill")
    else:
        record = _menu_action("record_start", "Start Screen Recording", "record_start", "record.circle")
    quick = (
        _menu_text("brief", "Brief Me", "brief me", "newspaper"),
        _menu_text("next_shift", "Next Shift", "what's my next shift", "calendar"),
        _menu_text("leave", "When Should I Leave", "when should I leave", "car.fill"),
        _menu_text("payday", "Payday Check", "payday check", "bell"),
        {"kind": "separator"},
        _menu_text("blue_pill", "Blue Pill", "blue pill", "play.rectangle"),
        _menu_text("red_pill", "Red Pill", "red pill", "stop.rectangle"),
        _menu_text("silence", "Silence Notifications", "silence notifications", "bell.slash.fill"),
        {"kind": "separator"},
        {
            "id": "volume", "title": "Volume", "kind": "submenu", "symbol": "speaker.wave.2.fill",
            "items": (
                _menu_text("volume_30", "Volume 30", "volume to 30", "speaker.wave.1.fill"),
                _menu_text("volume_50", "Volume 50", "volume to 50", "speaker.wave.2.fill"),
                _menu_text("volume_100", "Volume 100", "volume to 100", "speaker.wave.3.fill"),
                _menu_text("mute", "Mute", "mute", "speaker.slash.fill"),
            ),
        },
        {
            "id": "brightness", "title": "Brightness", "kind": "submenu", "symbol": "sun.max.fill",
            "items": (
                _menu_text("brightness_40", "Brightness 40", "brightness to 40", "sun.min.fill"),
                _menu_text("brightness_70", "Brightness 70", "brightness to 70", "sun.max.fill"),
                _menu_text("brightness_100", "Brightness 100", "brightness to 100", "sun.max.fill"),
            ),
        },
    )
    items = [
        {"id": "shots", "title": "Screenshot", "kind": "submenu", "symbol": "camera.viewfinder", "items": shots},
        record,
        _menu_action("captures_open", "Open Captures Folder", "captures_open", "folder"),
        {"id": "recent", "title": "Recent Captures", "kind": "submenu", "symbol": "clock", "items": _capture_follow_rows()},
        {
            "id": "ask_question",
            "title": "Ask About the Last Question",
            "kind": "submenu",
            "symbol": "questionmark.bubble",
            "items": _ask_items("ask_question"),
        },
    ]
    if can_attach:
        items.append(_menu_action("attach", "Attach File\u2026", "attach", "paperclip"))
    items.extend((
        {"kind": "separator"},
        {"id": "quick", "title": "Quick Commands", "kind": "submenu", "symbol": "bolt.fill", "items": quick},
        {"kind": "separator"},
        _menu_action("window", "Open Jev Window", "window", "macwindow", "1"),
        _menu_action("updates", "Check for Updates\u2026", "updates", "arrow.clockwise"),
        _menu_action("reset_position", "Reset Mini Bar Position", "reset_position", "arrow.uturn.backward"),
        _menu_action("reset_size", "Reset Mini Bar Size", "reset_size", "arrow.up.left.and.arrow.down.right"),
        _menu_action("settings", "Settings\u2026", "settings", "gearshape"),
    ))
    return tuple(items)


def walk_menu(items=None):
    """Every real item, with submenu children and without separators."""
    if items is None:
        items = plus_menu()
    found = []
    for item in items:
        if item.get("kind") == "separator":
            continue
        if item.get("kind") == "submenu":
            found.extend(walk_menu(item.get("items") or ()))
            continue
        found.append(item)
    return found


def plus_item(item_id, items=None):
    for item in walk_menu(items if items is not None else plus_menu()):
        if item.get("id") == item_id:
            return item
    return None


def bar_metrics(width, height):
    """Button, padding, and font sizes for a pill of this size.

    Height scales the type and the padding. Width gives the extra room to the
    text field. The default height keeps the original 14pt field and 24pt buttons.
    """
    _w, h = clamp_size(width, height)
    scale = h / BAR_H
    button = min(30.0, max(20.0, 24.0 * scale))
    edge = min(14.0, max(8.0, 10.0 * scale))
    gap = min(10.0, max(6.0, 8.0 * scale))
    field_h = min(button, max(18.0, 22.0 * scale))
    return {
        "button": button,
        "edge": edge,
        "gap": gap,
        "field_h": field_h,
        "field_font": min(18.0, max(12.0, 14.0 * scale)),
        "plus_font": min(26.0, max(16.0, 20.0 * scale)),
    }


def bar_controls(size=None):
    """Plus, field, and mic inside the pill. Origin is the pill's bottom left.

    The controls sit inset past the resize grip, so the rounded ends and the
    bands above and below them are background. Those bands are what a drag
    grabs. The outer grip resizes. The field is one line, centered, so the
    placeholder sits in the middle. A wider pill lengthens the field.
    """
    width, height = clamp_size(*(size or default_size()))
    metrics = bar_metrics(width, height)
    button = metrics["button"]
    edge = metrics["edge"]
    gap = metrics["gap"]
    y = (height - button) / 2.0
    plus = (edge, y, button, button)
    mic = (width - edge - button, y, button, button)
    field_h = metrics["field_h"]
    field_x = edge + button + gap
    field = (field_x, (height - field_h) / 2.0, mic[0] - gap - field_x, field_h)
    return {"plus": plus, "field": field, "mic": mic}


def hit_control(x, y, controls=None):
    """'plus', 'field', or 'mic' when a click lands on that control. Else None.

    None means the pill background or an edge. A single click there drags, and a double-click recenters.
    """
    frames = controls or bar_controls()
    for name in ("plus", "field", "mic"):
        rx, ry, rw, rh = frames[name]
        if rx <= x < rx + rw and ry <= y < ry + rh:
            return name
    return None


def mic_event(phase):
    """The same control-queue tokens as holding and releasing right Option."""
    if phase == "down":
        return "press"
    if phase == "up":
        return "release"
    raise ValueError(phase)


def submission(text, shown_reply=""):
    """What Return does with the field.

    Empty input is ignored. The line currently showing as a reply is cleared,
    not run again. A real command is queued for the same turn as a voice
    command, including TypeSafe or the LLM when nothing local matches, and
    must not bring the main window back.
    """
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return None
    if shown_reply and cleaned == " ".join(str(shown_reply).split()):
        return {"kind": "clear", "reveal_main": False}
    return {
        "kind": "run",
        "control": ("text", cleaned),
        "reveal_main": False,
    }


def reply_text(state, detail):
    """The status line to show in the pill, or None.

    Callers pass the notify() detail only. Message bodies are not a separate
    argument: a My Love read arrives as "Spoken on this Mac only".
    """
    text = " ".join(str(detail or "").split())
    if state not in _SHOW_STATES or not text:
        return None
    if state == "Ready" and text in _IDLE_READY:
        return None
    return text


class BarController:
    """Whether the pill is on screen. Default is on, but only while the main window is hidden."""

    def __init__(self, enabled=True):
        self.enabled = bool(enabled)
        self.main_on_screen = True
        self.dismissed = False
        self.quitting = False
        self.reply = ""
        self.reply_at = 0.0

    def should_show(self):
        return bool(self.enabled) and not self.quitting and not self.main_on_screen and not self.dismissed

    def main_window_changed(self, on_screen):
        """on_screen means ordered in and not miniaturized. Restoring clears a one-shot Esc hide."""
        self.main_on_screen = bool(on_screen)
        if self.main_on_screen:
            self.dismissed = False
        return self.should_show()

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if self.enabled:
            self.dismissed = False
        return self.should_show()

    def dismiss(self):
        """Esc or Hide Mini Bar, while the pill is up.

        Stays down until the main window is shown again. Doing it while the
        main window is already on screen does not block the next minimize.
        """
        if self.main_on_screen or not self.enabled or self.quitting:
            return self.should_show()
        self.dismissed = True
        return self.should_show()

    def quit(self):
        """App quit is not window-close. The pill stays hidden."""
        self.quitting = True
        return self.should_show()

    def note_reply(self, text, now):
        self.reply = str(text or "")
        self.reply_at = float(now)
        return self.reply

    def reply_due_clear(self, now, field_text):
        """True when the brief reply should be wiped. Typing over it cancels the timer."""
        if not self.reply:
            return False
        if " ".join(str(field_text or "").split()) != " ".join(self.reply.split()):
            self.reply = ""
            return False
        if float(now) - self.reply_at >= REPLY_SECONDS:
            self.reply = ""
            return True
        return False
