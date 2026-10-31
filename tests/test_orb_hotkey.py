"""PR 8 follow-up: Control-Option-J shows the orb and the input pill. It never opens the full window."""
import ast
import os
import unittest

from mini_bar import BarController

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return handle.read()


def _func(source, name):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError("no function named " + name)


class RevealTests(unittest.TestCase):
    def test_reveal_shows_a_hidden_orb_again(self):
        bar = BarController()
        bar.main_window_changed(False)  # the main window is hidden, so the orb may show
        self.assertTrue(bar.should_show())
        bar.dismiss()
        self.assertFalse(bar.should_show())
        self.assertTrue(bar.reveal())
        self.assertTrue(bar.should_show())

    def test_reveal_does_not_show_an_orb_that_is_disabled(self):
        bar = BarController()
        bar.set_enabled(False)
        self.assertFalse(bar.reveal())

    def test_reveal_keeps_the_orb_hidden_while_the_main_window_is_on_screen(self):
        bar = BarController()
        bar.main_window_changed(True)
        self.assertFalse(bar.reveal())


class HotkeyWiringTests(unittest.TestCase):
    def setUp(self):
        self.ui = _source("assistant_ui.py")
        self.handler = _func(self.ui, "focusTypeField_")

    def test_the_hotkey_never_opens_or_focuses_the_full_window(self):
        for banned in ("showMain_", "_select_tab", "home_field", "self.panel.makeFirstResponder_",
                       "_show_full_window", "_expand_orb_to_full", "expandOrbToFull_"):
            self.assertNotIn(banned, self.handler, banned)

    def test_the_hotkey_logs_the_orb_state_it_found(self):
        self.assertIn('"orb hotkey: show orb (tucked={0}, hidden={1})"', self.handler)

    def test_hidden_orb_is_revealed_and_a_tuck_is_taken_out(self):
        self.assertIn("self.bar.reveal()", self.handler)
        self.assertIn("self._apply_bar_visibility()", self.handler)
        self.assertIn('self._tuck_untuck("hotkey", instant=True)', self.handler)

    def test_the_input_pill_opens_with_its_field_focused(self):
        self.assertIn("self.expandMiniBar_(None)", self.handler)
        self.assertIn("self._focus_pill_field", _func(self.ui, "expandMiniBar_"))

    def test_pressing_again_while_the_pill_is_open_hides_it(self):
        self.assertIn('print("orb hotkey: hide pill"', self.handler)
        self.assertIn("self.pill.escape()", self.handler)
        self.assertIn("self._restore_front_app()", self.handler)

    def test_a_docked_window_is_left_alone(self):
        self.assertIn("if docked:", self.handler)
        self.assertLess(self.handler.index("if docked:"), self.handler.index("self.expandMiniBar_(None)"))

    def test_the_full_window_still_opens_from_the_orb_click_open_jev_and_settings(self):
        self.assertIn("expandOrbToFull_", _func(_source("assistant_ui.py"), "_collapsed_click_or_drag")
                      + _func(self.ui, "orbMenuOpen_"))
        self.assertIn("def orbMenuOpen_", self.ui)
        self.assertIn("def showSettings_", self.ui)
        self.assertIn('"showSettings:"', _source("orb_spotlight.py"))

    def test_the_menu_item_still_routes_to_the_same_handler(self):
        self.assertIn("focusTypeField:", self.ui)

    def test_the_hotkey_is_a_carbon_registration_not_an_app_only_binding(self):
        self.assertIn("CarbonHotKey(self._type_hotkey_pressed, TYPE_KEY_CODE", self.ui)
        self.assertIn('"Control-Option-J", hotkey_id=2', self.ui)
        self.assertIn('"orb hotkey: registered ctrl-opt-J"', self.ui)
        self.assertIn("self.focusTypeField_(None)", _func(self.ui, "_type_hotkey_pressed"))
        self.assertIn("self.type_hotkey.unregister()", self.ui)

    def test_the_app_only_bindings_for_control_option_j_are_gone(self):
        local = _func(self.ui, "_local_key")
        global_key = _func(self.ui, "_global_type_key")
        self.assertNotIn("type_focus_hotkey", local)
        self.assertNotIn("type_focus_hotkey", global_key)

    def test_the_hotkey_is_registered_with_its_own_id_and_the_right_chord(self):
        import area_hotkey
        self.assertEqual(area_hotkey.CARBON_CONTROL | area_hotkey.CARBON_OPTION, 0x1800)
        self.assertEqual(area_hotkey.AreaCaptureHotKey.__mro__[1], area_hotkey.CarbonHotKey)

    def test_the_spotlight_activates_before_it_becomes_key_and_logs_one_tick_later(self):
        opener = _func(self.ui, "_open_orb_spotlight")
        self.assertLess(opener.index("NSApp.activateIgnoringOtherApps_(True)"), opener.index("makeKeyAndOrderFront_"))
        self.assertIn("orderFrontRegardless", opener)
        self.assertIn("setHidesOnDeactivate_(False)", opener)
        self.assertIn('"orb spotlight: after open key={0} visible={1} occlusion={2}"', _func(self.ui, "spotlightAfterOpen_"))

    def test_every_drop_logs_its_roughness(self):
        self.assertIn('"orb drag: end reversals={0} fast_s={1:.2f} rough={2}"', _func(self.ui, "_finalize_mini_bar_drag"))


if __name__ == "__main__":
    unittest.main()
