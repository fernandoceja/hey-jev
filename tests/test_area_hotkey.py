"""Control-Option-Command-W: the global area-capture hotkey (PR 4). No AppKit, so the key rule is pure and the wiring is read from source."""
import os
import re

from mini_bar import area_capture_hotkey, type_focus_hotkey

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, J = 13, 38
CONTROL, OPTION, COMMAND, SHIFT = 1 << 18, 1 << 19, 1 << 20, 1 << 17


def _ui():
    with open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8") as f:
        return f.read()


def _body(source, header):
    start = source.index(header)
    indent = len(header) - len(header.lstrip())
    rest = source[start + len(header):]
    match = re.search(r"\n {%d}(def |@)" % indent, rest)
    return rest[:match.start()] if match else rest


def test_control_option_command_w_fires_the_hotkey():
    assert area_capture_hotkey(W, CONTROL | OPTION | COMMAND)


def test_every_modifier_is_required():
    assert not area_capture_hotkey(W, OPTION | COMMAND)
    assert not area_capture_hotkey(W, CONTROL | COMMAND)
    assert not area_capture_hotkey(W, CONTROL | OPTION)
    assert not area_capture_hotkey(W, COMMAND)


def test_shift_or_other_keys_do_not_fire_it():
    assert not area_capture_hotkey(W, CONTROL | OPTION | COMMAND | SHIFT)
    assert not area_capture_hotkey(J, CONTROL | OPTION | COMMAND)


def test_extra_bits_such_as_caps_lock_do_not_block_it():
    caps = 1 << 16
    assert area_capture_hotkey(W, CONTROL | OPTION | COMMAND | caps)


def test_bad_input_never_fires():
    assert not area_capture_hotkey(None, CONTROL | OPTION | COMMAND)
    assert not area_capture_hotkey(W, "x")


def test_it_does_not_collide_with_control_option_j_or_plain_command_w():
    assert type_focus_hotkey(J, CONTROL | OPTION)
    assert not area_capture_hotkey(J, CONTROL | OPTION)
    assert not area_capture_hotkey(W, COMMAND)  # Command-W stays the in-app menu key equivalent
    assert not type_focus_hotkey(W, CONTROL | OPTION | COMMAND)


def test_both_key_monitors_route_the_hotkey_to_the_existing_area_capture():
    ui = _ui()
    local = _body(ui, "    def _local_key(self, event):")
    assert "area_capture_hotkey(event.keyCode(), event.modifierFlags())" in local
    assert "self.captureAreaWand_(None)" in local
    global_key = _body(ui, "    def _global_type_key(self, event):")
    assert "area_capture_hotkey(event.keyCode(), event.modifierFlags())" in global_key
    assert 'performSelectorOnMainThread_withObject_waitUntilDone_("captureAreaWand:", None, False)' in global_key


def test_no_new_monitor_or_permission_was_added():
    ui = _ui()
    # Only the two existing global monitors (flags and key down) are registered, so no new permission is needed.
    assert ui.count("addGlobalMonitorForEventsMatchingMask_handler_") == 2
    assert "NSEventMaskKeyDown, self._global_type_key" in ui
    assert not re.search(r"RegisterEventHotKey|CGEventTapCreate|CGEventSourceKeyState|socket\.socket", ui)
