"""Ctrl-Option-J when Jev is closed: a tiny login-item helper owns the hotkey and launches Jev. Pure Python plus a thin
ServiceManagement wrapper (SMAppService, the sanctioned macOS login-item API; macOS 13 or later).

The helper app lives inside the Jev bundle at Contents/Library/LoginItems. Turning it on is the user's choice in
Settings, and macOS may ask for approval in System Settings > Login Items. Nothing here clicks or approves anything.
"""
import os

HELPER_ID = "com.heyjev.app.hotkey"
HELPER_NAME = "Jev Hotkey.app"
SHOW_ORB_NOTIFICATION = "com.heyjev.app.showOrb"  # posted by the helper when Jev is already running
SHOW_ORB_ARG = "--show-orb"  # passed by the helper when it has to launch Jev

# SMAppService.Status raw values.
NOT_REGISTERED, ENABLED, REQUIRES_APPROVAL, NOT_FOUND = 0, 1, 2, 3

_STATUS_TEXT = {
    NOT_REGISTERED: "Off",
    ENABLED: "On. Ctrl-Option-J opens Jev even when it is closed.",
    REQUIRES_APPROVAL: "Waiting for your approval: System Settings > General > Login Items & Extensions.",
    NOT_FOUND: "Not available in this build. Run scripts/build_hotkey_helper.sh, then rebuild and sign.",
}


def status_text(status):
    return _STATUS_TEXT.get(status, "Unknown")


def is_on(status):
    """The switch shows on when the helper is enabled or is only waiting for the user's approval."""
    return status in (ENABLED, REQUIRES_APPROVAL)


def show_orb_requested(argv):
    return SHOW_ORB_ARG in list(argv or [])


def helper_path(app_bundle_path):
    return os.path.join(str(app_bundle_path), "Contents", "Library", "LoginItems", HELPER_NAME)


class LoginItemHelper:
    """Thin wrapper over SMAppService for the helper. The service is injectable so tests never touch macOS."""

    def __init__(self, service=None):
        self._service = service

    def _svc(self):
        if self._service is None:
            import objc
            namespace = {}
            objc.loadBundle("ServiceManagement", namespace,
                            bundle_path="/System/Library/Frameworks/ServiceManagement.framework")
            self._service = objc.lookUpClass("SMAppService").loginItemServiceWithIdentifier_(HELPER_ID)
        return self._service

    def status(self):
        try:
            return int(self._svc().status())
        except Exception:
            return NOT_FOUND

    def set_enabled(self, enabled):
        """Register or unregister. Returns (status, error text or ''). Registering can need the user's approval."""
        try:
            svc = self._svc()
            if enabled:
                ok, error = svc.registerAndReturnError_(None)
            else:
                ok, error = svc.unregisterAndReturnError_(None)
            return self.status(), ("" if ok else str(error))
        except Exception as exc:
            return NOT_FOUND, str(exc)
