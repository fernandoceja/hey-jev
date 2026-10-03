"""Show and hide rules for the floating command bar.

No AppKit. The window asks this before it orders the pill on or off, and before
a Return press is handed to the assistant. A typed line is queued as a normal
turn, the same path as something she heard. Nothing here opens a socket.
"""

BAR_W = 420.0
BAR_H = 44.0
# Visible-frame origin is already above the Dock. The extra gap leaves room
# for the dictation bubble, which sits in that same bottom-center spot.
DOCK_GAP = 72.0
PLACEHOLDER = "Message Jev"
REPLY_SECONDS = 4.0
PREF_KEY = "mini_bar_enabled"
ORIGIN_KEY = "mini_bar_origin"

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


def _intersection_area(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    return (x2 - x1) * (y2 - y1)


def default_origin(visible):
    """Bottom-center of a screen's visible frame (x, y, w, h)."""
    vx, vy, vw, _vh = visible
    return (vx + (vw - BAR_W) / 2.0, vy + DOCK_GAP)


def _as_screens(visible):
    """One (x, y, w, h) frame, or a list of them. The first is the fallback screen."""
    if not visible:
        return []
    first = visible[0]
    if isinstance(first, (int, float)):
        return [tuple(float(v) for v in visible)]
    return [tuple(float(v) for v in screen) for screen in visible]


def place_bar(saved, visible):
    """Remembered origin when most of the pill is still on any screen.

    `visible` is one screen's visible frame, or several (a second display
    included). An origin that misses every screen is bottom-center of the first.
    """
    screens = _as_screens(visible)
    if not screens:
        return (0.0, DOCK_GAP)
    fallback = default_origin(screens[0])
    if not saved:
        return fallback
    frame = (float(saved[0]), float(saved[1]), BAR_W, BAR_H)
    needed = 0.5 * BAR_W * BAR_H
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


def background_action(click_count, x, y, controls=None):
    """What a click on the pill does.

    A double-click on the background or an edge recenters the pill. A single
    click there is a drag. The text field and the buttons keep their own clicks.
    """
    if hit_control(x, y, controls) is not None:
        return "control"
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


def bar_controls():
    """Plus, field, and mic inside the pill. Origin is the pill's bottom left.

    The controls sit inset, so the rounded ends and the bands above and below
    them are background. Those bands are what a drag grabs. The field is only
    as tall as one line and is centered, so the placeholder sits in the middle.
    """
    button = 24.0
    edge = 10.0
    gap = 8.0
    y = (BAR_H - button) / 2.0
    plus = (edge, y, button, button)
    mic = (BAR_W - edge - button, y, button, button)
    field_h = 22.0
    field_x = edge + button + gap
    field = (field_x, (BAR_H - field_h) / 2.0, mic[0] - gap - field_x, field_h)
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
