"""Control-Option-Command-W as a Carbon hotkey (PR 4). No AppKit and no Carbon load: the constants, the diagnostic
chord check, and the wiring are checked directly, and the failure path is checked where Carbon is absent."""
import os
import re
from unittest import mock

from area_hotkey import (
    AREA_CAPTURE_KEY_CODE,
    AREA_CAPTURE_MODIFIERS,
    CARBON_COMMAND,
    CARBON_CONTROL,
    CARBON_OPTION,
    AreaCaptureHotKey,
)
from mini_bar import control_option_command_held, type_focus_hotkey

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, J = 13, 38
CONTROL, OPTION, COMMAND, SHIFT, CAPS = 1 << 18, 1 << 19, 1 << 20, 1 << 17, 1 << 16


def _source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def _body(source, header):
    start = source.index(header)
    indent = len(header) - len(header.lstrip())
    rest = source[start + len(header):]
    match = re.search(r"\n {%d}(def |@)" % indent, rest)
    return rest[:match.start()] if match else rest


def test_the_carbon_chord_is_w_with_control_option_and_command():
    assert AREA_CAPTURE_KEY_CODE == 13  # kVK_ANSI_W
    assert (CARBON_CONTROL, CARBON_OPTION, CARBON_COMMAND) == (0x1000, 0x0800, 0x0100)
    assert AREA_CAPTURE_MODIFIERS == 0x1000 | 0x0800 | 0x0100 == 6400


def test_the_diagnostic_fires_only_when_all_three_modifiers_are_held():
    assert control_option_command_held(CONTROL | OPTION | COMMAND)
    assert control_option_command_held(CONTROL | OPTION | COMMAND | SHIFT | CAPS)  # extra bits do not hide it
    assert not control_option_command_held(OPTION | COMMAND)
    assert not control_option_command_held(CONTROL | COMMAND)
    assert not control_option_command_held(CONTROL | OPTION)
    assert not control_option_command_held(COMMAND)
    assert not control_option_command_held("x")


def test_control_option_j_and_plain_command_w_are_unaffected():
    assert type_focus_hotkey(J, CONTROL | OPTION)
    assert not type_focus_hotkey(W, CONTROL | OPTION | COMMAND)


def test_registration_reports_a_missing_carbon_without_raising():
    # The test guard blocks real framework loads, so the missing-Carbon path is simulated with an OSError.
    hotkey = AreaCaptureHotKey(lambda: None)
    with mock.patch("area_hotkey.ctypes.cdll.LoadLibrary", side_effect=OSError("no Carbon")):
        registered, detail = hotkey.register()
    assert registered is False
    assert "Carbon not available" in detail


def test_unregister_is_a_no_op_when_nothing_was_registered():
    hotkey = AreaCaptureHotKey(lambda: None)
    hotkey.unregister()  # must not raise
    assert hotkey._hotkey_ref is None and hotkey._handler_ref is None


def test_the_hotkey_module_has_no_socket_or_event_tap():
    source = _source("area_hotkey.py")
    assert not re.search(r"^import socket|socket\.|CGEventTapCreate|CGEventSourceKeyState|addGlobalMonitor", source, re.M)


def test_the_app_registers_the_hotkey_at_launch_and_unregisters_it_on_quit():
    ui = _source("assistant_ui.py")
    launch = _body(ui, "    def applicationDidFinishLaunching_(self, _notification):")
    assert "AreaCaptureHotKey(self._area_hotkey_pressed)" in launch
    assert "self.area_hotkey.register()" in launch
    quit_body = _body(ui, "    def applicationWillTerminate_(self, _notification):")
    assert "self.area_hotkey.unregister()" in quit_body


def test_the_press_runs_the_existing_area_capture_action():
    ui = _source("assistant_ui.py")
    pressed = _body(ui, "    def _area_hotkey_pressed(self):")
    assert "self.captureAreaWand_(None)" in pressed
    action = _body(ui, "    def captureAreaWand_(self, _sender):")
    assert '_capture_for_bar, args=("area",)' in action


def test_the_area_chord_left_the_nsevent_monitors_and_the_global_log_is_diagnostic_only():
    ui = _source("assistant_ui.py")
    assert "area_capture_hotkey" not in ui  # the NSEvent helper is gone; Carbon owns the chord
    global_key = _body(ui, "    def _global_type_key(self, event):")
    assert "control_option_command_held(flags)" in global_key
    assert "keyCode={0} flags=0x{1:x}" in global_key  # key code and flags only, no characters
    assert "characters" not in global_key
    # Two global monitors: the key monitor, and the Spotlight's mouse-down monitor, which exists only while the panel is
    # open and watches mouse buttons only. Mouse events need no extra permission, unlike key events.
    assert ui.count("addGlobalMonitorForEventsMatchingMask_handler_") == 3


def test_the_orb_panel_level_and_floating_flags_are_untouched():
    ui = _source("assistant_ui.py")
    assert "self.mini_panel.setLevel_(BAR_LEVEL)" in ui
    assert "self.mini_panel.setFloatingPanel_(True)" in ui
