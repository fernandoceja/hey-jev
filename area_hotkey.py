"""Control-Option-Command-W as a system-wide hotkey, registered with Carbon RegisterEventHotKey.

Carbon hotkeys need no Accessibility or Input Monitoring grant. A global NSEvent key monitor does need one, and
without it the chord never reaches Jev from another app. Carbon is loaded lazily, so this module imports on any
platform and CI can test the constants. It opens no listening endpoint and asks for no grant.
"""
import ctypes

AREA_CAPTURE_KEY_CODE = 13  # kVK_ANSI_W
CARBON_CONTROL = 0x1000  # controlKey
CARBON_OPTION = 0x0800  # optionKey
CARBON_COMMAND = 0x0100  # cmdKey
AREA_CAPTURE_MODIFIERS = CARBON_CONTROL | CARBON_OPTION | CARBON_COMMAND

_EVENT_CLASS_KEYBOARD = 0x6B657962  # 'keyb'
_EVENT_HOT_KEY_PRESSED = 5  # kEventHotKeyPressed
_HOTKEY_SIGNATURE = 0x4A455657  # 'JEVW'
_NO_ERROR = 0
_CARBON = "/System/Library/Frameworks/Carbon.framework/Carbon"


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)


_EVENT_PARAM_DIRECT_OBJECT = 0x2D2D2D2D  # kEventParamDirectObject '----'
_TYPE_EVENT_HOT_KEY_ID = 0x686B6964  # typeEventHotKeyID 'hkid'
_EVENT_NOT_HANDLED = -9874  # eventNotHandledErr: another hotkey's handler should see this press


class CarbonHotKey:
    """Registers one chord with Carbon and calls on_press() each time it is pressed. on_press runs on the main thread.

    Each hotkey has its own id. Several can share the application target, so a press is handled only by the
    handler whose id it carries. Other presses are passed on with eventNotHandledErr.
    """

    def __init__(self, on_press, key_code, modifiers, label, hotkey_id=1):
        self._on_press = on_press
        self._key_code = int(key_code)
        self._modifiers = int(modifiers)
        self._label = str(label)
        self._id = int(hotkey_id)
        self._handler = None
        self._handler_ref = None
        self._hotkey_ref = None
        self._carbon = None

    def register(self):
        """(registered, detail). A failed registration is reported, never raised, so the app still starts."""
        try:
            carbon = ctypes.cdll.LoadLibrary(_CARBON)
        except OSError as exc:
            return False, "Carbon not available: {0}".format(exc)
        self._carbon = carbon
        carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
        carbon.GetApplicationEventTarget.argtypes = []
        carbon.GetEventParameter.restype = ctypes.c_int32
        carbon.GetEventParameter.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p,
        ]
        carbon.InstallEventHandler.restype = ctypes.c_int32
        carbon.InstallEventHandler.argtypes = [
            ctypes.c_void_p, _HANDLER, ctypes.c_uint32, ctypes.POINTER(_EventTypeSpec),
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
        ]
        carbon.RegisterEventHotKey.restype = ctypes.c_int32
        carbon.RegisterEventHotKey.argtypes = [
            ctypes.c_uint32, ctypes.c_uint32, _EventHotKeyID, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p),
        ]
        carbon.RemoveEventHandler.restype = ctypes.c_int32
        carbon.RemoveEventHandler.argtypes = [ctypes.c_void_p]
        carbon.UnregisterEventHotKey.restype = ctypes.c_int32
        carbon.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]

        def handle(_call, event, _user):
            try:
                pressed = _EventHotKeyID(0, 0)
                status = carbon.GetEventParameter(
                    event, _EVENT_PARAM_DIRECT_OBJECT, _TYPE_EVENT_HOT_KEY_ID, None,
                    ctypes.sizeof(pressed), None, ctypes.byref(pressed))
                if status != _NO_ERROR or pressed.signature != _HOTKEY_SIGNATURE or pressed.id != self._id:
                    return _EVENT_NOT_HANDLED
                self._on_press()
            except Exception as exc:  # a hotkey must never raise into Carbon
                print("  {0} hotkey failed: {1}".format(self._label, exc))
            return _NO_ERROR

        self._handler = _HANDLER(handle)  # keep a reference: Carbon calls it later
        target = carbon.GetApplicationEventTarget()
        spec = _EventTypeSpec(_EVENT_CLASS_KEYBOARD, _EVENT_HOT_KEY_PRESSED)
        handler_ref = ctypes.c_void_p()
        status = carbon.InstallEventHandler(
            target, self._handler, 1, ctypes.pointer(spec), None, ctypes.byref(handler_ref))
        if status != _NO_ERROR:
            return False, "{0} handler not installed (status {1})".format(self._label, status)
        self._handler_ref = handler_ref.value
        hotkey_id = _EventHotKeyID(_HOTKEY_SIGNATURE, self._id)
        hotkey_ref = ctypes.c_void_p()
        status = carbon.RegisterEventHotKey(
            self._key_code, self._modifiers, hotkey_id, target, 0, ctypes.byref(hotkey_ref))
        if status != _NO_ERROR:
            # -9878 is eventHotKeyExistsErr: another app already holds the chord. Drop the handler we installed.
            carbon.RemoveEventHandler(ctypes.c_void_p(self._handler_ref))
            self._handler_ref = None
            return False, "{0} not registered (status {1})".format(self._label, status)
        self._hotkey_ref = hotkey_ref.value
        return True, "{0} registered".format(self._label)

    def unregister(self):
        carbon = self._carbon
        if carbon is None:
            return
        if self._hotkey_ref is not None:
            carbon.UnregisterEventHotKey(ctypes.c_void_p(self._hotkey_ref))
            self._hotkey_ref = None
        if self._handler_ref is not None:
            carbon.RemoveEventHandler(ctypes.c_void_p(self._handler_ref))
            self._handler_ref = None


class AreaCaptureHotKey(CarbonHotKey):
    """Control-Option-Command-W: area capture from any app."""

    def __init__(self, on_press):
        super().__init__(on_press, AREA_CAPTURE_KEY_CODE, AREA_CAPTURE_MODIFIERS,
                         "Control-Option-Command-W", hotkey_id=1)


SUMMON_PREF = "summon_shortcut"
SUMMON_DEFAULT = "ctrl+alt+j"
# Physical ANSI key codes; identical table is used by the tiny Swift helper.
LETTER_CODES = dict(zip("abcdefghijklmnopqrstuvwxyz",
                        (0, 11, 8, 2, 14, 3, 5, 4, 34, 38, 40, 37, 46,
                         45, 31, 35, 12, 15, 1, 17, 32, 9, 13, 7, 16, 6)))


def summon_shortcut(value=None):
    """Return canonical preference, key code and Carbon modifiers, or reject invalid/conflicting input."""
    text = SUMMON_DEFAULT if value is None else str(value).strip().lower()
    parts = text.split("+")
    flags = {"ctrl": CARBON_CONTROL, "alt": CARBON_OPTION, "cmd": CARBON_COMMAND, "shift": 0x0200}
    if (len(parts) < 2 or parts[-1] not in LETTER_CODES or
            any(p not in flags for p in parts[:-1]) or len(set(parts[:-1])) != len(parts[:-1])):
        raise ValueError("Use modifiers ctrl, alt, cmd, shift plus a letter, e.g. ctrl+alt+j")
    modifiers = sum(flags[p] for p in parts[:-1])
    code = LETTER_CODES[parts[-1]]
    if code == AREA_CAPTURE_KEY_CODE and modifiers == AREA_CAPTURE_MODIFIERS:
        raise ValueError("Control-Option-Command-W is reserved for area capture")
    return "+".join(p for p in flags if p in parts[:-1]) + "+" + parts[-1], code, modifiers
