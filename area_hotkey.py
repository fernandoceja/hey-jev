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


class AreaCaptureHotKey:
    """Registers the chord and calls on_press() each time it is pressed. on_press runs on the main thread."""

    def __init__(self, on_press):
        self._on_press = on_press
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

        def handle(_call, _event, _user):
            try:
                self._on_press()
            except Exception as exc:  # a hotkey must never raise into Carbon
                print("  area hotkey failed: {0}".format(exc))
            return _NO_ERROR

        self._handler = _HANDLER(handle)  # keep a reference: Carbon calls it later
        target = carbon.GetApplicationEventTarget()
        spec = _EventTypeSpec(_EVENT_CLASS_KEYBOARD, _EVENT_HOT_KEY_PRESSED)
        handler_ref = ctypes.c_void_p()
        status = carbon.InstallEventHandler(
            target, self._handler, 1, ctypes.pointer(spec), None, ctypes.byref(handler_ref))
        if status != _NO_ERROR:
            return False, "handler not installed (status {0})".format(status)
        self._handler_ref = handler_ref.value
        hotkey_id = _EventHotKeyID(_HOTKEY_SIGNATURE, 1)
        hotkey_ref = ctypes.c_void_p()
        status = carbon.RegisterEventHotKey(
            AREA_CAPTURE_KEY_CODE, AREA_CAPTURE_MODIFIERS, hotkey_id, target, 0, ctypes.byref(hotkey_ref))
        if status != _NO_ERROR:
            # -9878 is eventHotKeyExistsErr: another app already holds the chord. Drop the handler we installed.
            carbon.RemoveEventHandler(ctypes.c_void_p(self._handler_ref))
            self._handler_ref = None
            return False, "Control-Option-Command-W not registered (status {0})".format(status)
        self._hotkey_ref = hotkey_ref.value
        return True, "Control-Option-Command-W registered"

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
