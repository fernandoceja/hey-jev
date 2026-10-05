"""The suite must fail before it can change a Mac, including under darwin."""
import ctypes
import os
import subprocess
import sys
import unittest
from unittest import mock

from commands.system import _CORE_GRAPHICS, _DISPLAY_SERVICES, change_brightness
from tests.mac_guard import RealHardwareCall


def _guarded(func):
    return getattr(func, "_mac_guard", False)


class TestHardwareGuard(unittest.TestCase):
    def setUp(self):
        if not _guarded(subprocess.run) or not _guarded(subprocess.Popen) or not _guarded(os.system):
            self.fail("the Mac hardware guard is not installed; refusing to call a process")
        if isinstance(ctypes.CDLL, type):
            self.fail("ctypes.CDLL is not guarded; refusing to load a framework")

    def test_osascript_defaults_brightness_shortcuts_and_terminal_are_blocked(self):
        blocked = (
            ["osascript", "-e", "beep"],
            ["defaults", "write", "com.apple.universalaccess", "invertColors", "-bool", "true"],
            ["/opt/homebrew/bin/brightness", "0.50"],
            ["shortcuts", "run", "Jev Focus On"],
            ["open", "-a", "Terminal"],
            ["pmset", "-g", "batt"],
            ["screencapture", "-x", "/tmp/hey-jev-should-not-exist.png"],
            ["/usr/bin/say", "hello"],
        )
        for args in blocked:
            with self.assertRaises(RealHardwareCall):
                subprocess.run(args)
            with self.assertRaises(RealHardwareCall):
                subprocess.Popen(args)
            with self.assertRaises(RealHardwareCall):
                os.system(" ".join(args))

    def test_display_frameworks_cannot_be_loaded(self):
        for path in (_DISPLAY_SERVICES, _CORE_GRAPHICS, "/System/Library/Frameworks/IOKit.framework/IOKit"):
            with self.assertRaises(RealHardwareCall) as caught:
                ctypes.CDLL(path)
            self.assertIn(path, str(caught.exception))
            with self.assertRaises(RealHardwareCall):
                ctypes.cdll.LoadLibrary(path)

    def test_a_non_framework_library_stays_loadable(self):
        ctypes.CDLL(None)
        for path in ("/lib/x86_64-linux-gnu/libc.so.6", "/usr/lib/libSystem.B.dylib"):
            if os.path.exists(path):
                ctypes.CDLL(path)
                break

    def test_a_stubbed_subprocess_is_still_allowed(self):
        def fake_run(args, **kwargs):
            return list(args)

        with mock.patch("subprocess.run", fake_run):
            self.assertEqual(subprocess.run(["osascript", "-e", "beep"]), ["osascript", "-e", "beep"])

    def test_unstubbed_brightness_raises_before_it_can_change_the_screen(self):
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertEqual(sys.platform, "darwin")
            with self.assertRaises(RealHardwareCall) as caught:
                change_brightness("up")
        self.assertIn("DisplayServices", str(caught.exception))
