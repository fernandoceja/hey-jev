"""Push-to-talk for the right Option key.

Pure Python. No AppKit, no event tap, no socket. The window feeds key codes
and modifier flags in. Right Option is virtual key 61 together with the
device-dependent bit NX_DEVICERALTKEYMASK (0x40). Left Option is a different
key and is ignored, including while the right key is already held.

A non-modifier key in the first INTERRUPT_MS after the press cancels the
hold, so a shortcut is not recorded as a command. Sleep, a Space change, and
a watchdog cover a release the flags stream never delivered.
"""

RIGHT_OPTION_KEY = 61
RIGHT_OPTION_BIT = 0x40  # NX_DEVICERALTKEYMASK
INTERRUPT_MS = 300

# Hardware key codes that change flags rather than typing. They must not cancel.
_MODIFIER_KEYS = frozenset({
    54,  # right command
    55,  # command
    56,  # shift
    57,  # caps lock
    58,  # left option
    59,  # control
    60,  # right shift
    61,  # right option
    62,  # right control
    63,  # function
})


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class PushToTalk:
    """Right Option down, up, or cancelled.

    `down` stays true after a cancel until the key actually comes up, so a
    repeat flags event is not a second press. `interrupted` is that cancel.
    """

    def __init__(self):
        self.down = False
        self.interrupted = False
        self.pressed_at = None

    def on_flags(self, keycode, flags, t):
        """'press' when right Option goes down, 'release' when that bit clears.

        Any other key, including left Option, returns None and leaves the hold
        as it was.
        """
        code = _as_int(keycode)
        bits = _as_int(flags)
        if code is None or bits is None or code != RIGHT_OPTION_KEY:
            return None
        held = bool(bits & RIGHT_OPTION_BIT)
        if held and not self.down:
            self.down = True
            self.interrupted = False
            self.pressed_at = float(t)
            return "press"
        if not held and self.down:
            self._up()
            return "release"
        return None

    def on_key(self, keycode, t):
        """'cancel' when a typing key lands inside the interrupt window.

        Modifier keys do not cancel. A key after the window, or a second key
        after a cancel, returns None. The hold stays down until the key comes up.
        """
        if not self.down or self.interrupted or self.pressed_at is None:
            return None
        code = _as_int(keycode)
        if code is None or code in _MODIFIER_KEYS:
            return None
        try:
            elapsed_ms = (float(t) - float(self.pressed_at)) * 1000.0
        except (TypeError, ValueError):
            return None
        # A hair over the integer window is still inside it. 10.0 + 0.3 is not exact.
        if elapsed_ms <= float(INTERRUPT_MS) + 1e-6:
            self.interrupted = True
            return "cancel"
        return None

    def force_release(self, reason):
        """'release' if the key is down. None when it is already up.

        `reason` is recorded for the caller (sleep, space). It does not change
        the token.
        """
        if not self.down:
            return None
        self.last_reason = reason
        self._up()
        return "release"

    def watchdog(self, t, flags_now):
        """'release' when we still think the key is down but the bit is gone.

        `t` is the same monotonic clock the window uses for the other calls.
        A held key, and an already-up key, return None.
        """
        if not self.down:
            return None
        bits = _as_int(flags_now)
        if bits is None:
            bits = 0
        if bits & RIGHT_OPTION_BIT:
            return None
        self._up()
        return "release"

    def _up(self):
        self.down = False
        self.interrupted = False
        self.pressed_at = None
