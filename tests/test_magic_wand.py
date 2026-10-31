"""Magic wand (PR 4): Command-W starts the area capture while Jev is the active app. No AppKit, so this reads source."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ui():
    with open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8") as f:
        return f.read()


def _body(source, header):
    """The text of the function that starts at `header`, up to the next def at the same indent."""
    start = source.index(header)
    indent = len(header) - len(header.lstrip())
    rest = source[start + len(header):]
    match = re.search(r"\n {%d}(def |@)" % indent, rest)
    return rest[:match.start()] if match else rest


def test_the_window_menu_has_capture_area_on_command_w():
    ui = _ui()
    menu = _body(ui, "    def _add_window_menu(self):")
    assert '"Capture Area", "captureAreaWand:", "w"' in menu
    assert "setKeyEquivalentModifierMask_(NSEventModifierFlagCommand)" in menu
    assert 'imageWithSystemSymbolName_accessibilityDescription_("wand.and.stars"' in menu


def test_the_wand_runs_the_existing_area_capture_path():
    ui = _ui()
    action = _body(ui, "    def captureAreaWand_(self, _sender):")
    assert '_capture_for_bar, args=("area",)' in action
    # That path ends in showCaptureResult:, which opens the usual post-capture choices.
    capture = _body(ui, "    def _capture_for_bar(self, mode=\"full\"):")
    assert "commands.take_screenshot(mode)" in capture
    assert "showCaptureResult:" in capture


def test_command_w_is_never_a_global_hotkey():
    ui = _ui()
    # Global monitors see every app's keys. Command-W is a menu key equivalent, which fires only in Jev.
    for handler in ("_global_type_key", "_global_flags_changed"):
        assert handler in ui
        body = _body(ui, "    def {0}(self, event):".format(handler))
        assert "keyCode() == 13" not in body  # 13 is W
    assert "addGlobalMonitorForEventsMatchingMask_handler_" in ui  # the existing monitors are still there
    assert not re.search(r"RegisterEventHotKey|CGEventTapCreate", ui)


def test_the_orb_panel_level_and_floating_flags_are_untouched():
    ui = _ui()
    assert "self.mini_panel.setLevel_(BAR_LEVEL)" in ui
    assert "self.mini_panel.setFloatingPanel_(True)" in ui
