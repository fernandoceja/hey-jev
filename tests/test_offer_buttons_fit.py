"""The brief offer's Play audio / No thanks buttons must never be clipped to a fragment beside the orb. Headless."""
import ast
import os
import unittest

import mini_bar as mb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ui():
    with open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8") as handle:
        return handle.read()


def _func(source, name):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError("no function named " + name)


class OfferButtonOriginTests(unittest.TestCase):
    def test_a_collapsed_orb_window_cannot_hold_them_so_they_are_hidden(self):
        """The bug: on the 44 pt orb window the No thanks button landed at a negative x and only 'ks' showed."""
        self.assertIsNone(mb.offer_button_origins(44.0, 44.0))
        self.assertIsNone(mb.offer_button_origins(72.0, 72.0))
        self.assertIsNone(mb.offer_button_origins(200.0, 120.0))

    def test_an_open_pill_holds_both_buttons_wholly_inside_its_bounds(self):
        for width in (230.0, 300.0, 340.0, 480.0, 900.0):
            origins = mb.offer_button_origins(width, 200.0)
            self.assertIsNotNone(origins, width)
            for key in ("audio", "no_thanks"):
                x, y = origins[key]
                self.assertGreaterEqual(x, mb.OFFER_LEFT_INSET, (width, key))
                self.assertLessEqual(x + mb.OFFER_BUTTON_W, width - mb.OFFER_RIGHT_INSET + 1e-9, (width, key))
                self.assertGreaterEqual(y, 0.0)

    def test_the_two_buttons_do_not_overlap_and_audio_is_on_the_left(self):
        origins = mb.offer_button_origins(340.0, 200.0)
        audio_x, no_x = origins["audio"][0], origins["no_thanks"][0]
        self.assertLess(audio_x + mb.OFFER_BUTTON_W, no_x)
        self.assertAlmostEqual(no_x - (audio_x + mb.OFFER_BUTTON_W), mb.OFFER_BUTTON_GAP)

    def test_the_narrowest_panel_that_fits_is_the_edge_case(self):
        need = mb.OFFER_LEFT_INSET + 2 * mb.OFFER_BUTTON_W + mb.OFFER_BUTTON_GAP + mb.OFFER_RIGHT_INSET
        self.assertIsNotNone(mb.offer_button_origins(need, 100.0))
        self.assertIsNone(mb.offer_button_origins(need - 1.0, 100.0))

    def test_a_panel_too_short_or_bad_input_hides_them(self):
        self.assertIsNone(mb.offer_button_origins(340.0, 20.0))
        for bad in (None, "x"):
            self.assertIsNone(mb.offer_button_origins(bad, 100.0))


class GreetingOverlapTests(unittest.TestCase):
    """The bug: in the open popover "Play audio" sat under the greeting text at the top."""

    def _popover(self):
        layout = mb.popover_subframes((300.0, 400.0, 420.0, 44.0), (0.0, 0.0, 1710.0, 1107.0))
        _px, _py, pw, ph = layout["panel"]
        return layout, mb.offer_button_origins(pw, ph)

    def test_in_the_default_popover_the_offer_row_lands_on_the_greeting(self):
        layout, origins = self._popover()
        self.assertIsNotNone(origins)
        self.assertTrue(mb.offer_covers_greeting(origins, layout["greeting"]))  # the overlap that hid Play audio

    def test_so_the_greeting_must_step_aside_and_comes_back_after(self):
        wiring = _func(_ui(), "_place_mini_offer_buttons")
        self.assertIn("offer_covers_greeting(origins, self._greeting_frame_now())", wiring)
        self.assertIn("label.setHidden_(True)", wiring)
        self.assertIn("self._restore_greeting_after_offer()", wiring)
        restore = _func(_ui(), "_restore_greeting_after_offer")
        self.assertIn("self._greeting_hidden_for_offer = False", restore)
        self.assertIn("label.setHidden_(self._orb_bubble_docked())", restore)  # a docked orb still has no greeting

    def test_neither_layout_nor_the_orb_sync_brings_the_greeting_back_while_the_offer_shows(self):
        """The orb sync runs on every status update and also sets the greeting's visibility; both must respect the flag."""
        ui = _ui()
        for name in ("_layout_mini_bar", "_sync_orb"):
            body = _func(ui, name)
            self.assertIn('bool(getattr(self, "_greeting_hidden_for_offer", False))', body, name)

    def test_nothing_changes_when_there_are_no_buttons_or_no_greeting(self):
        self.assertFalse(mb.offer_covers_greeting(None, (0, 0, 10, 10)))
        self.assertFalse(mb.offer_covers_greeting({"audio": (0, 0), "no_thanks": (200, 0)}, None))

    def test_the_overlap_test_is_a_real_rectangle_test(self):
        self.assertTrue(mb.rects_overlap((0, 0, 10, 10), (5, 5, 10, 10)))
        self.assertFalse(mb.rects_overlap((0, 0, 10, 10), (10, 0, 10, 10)))  # touching edges do not overlap
        self.assertFalse(mb.rects_overlap((0, 0, 10, 10), (0, 20, 10, 10)))
        origins = {"audio": (232.0, 210.0), "no_thanks": (340.0, 210.0)}
        self.assertFalse(mb.offer_covers_greeting(origins, (0.0, 100.0, 200.0, 34.0)))  # greeting elsewhere: untouched


class WiringTests(unittest.TestCase):
    def setUp(self):
        self.ui = _ui()

    def test_the_orb_panel_buttons_are_placed_by_the_fit_rule_not_raw_math(self):
        body = _func(self.ui, "_place_mini_offer_buttons")
        self.assertIn("offer_button_origins(", body)
        self.assertIn("if origins is None:", body)
        self.assertIn("audio.setHidden_(True)", body)
        self.assertIn("no_thanks.setHidden_(True)", body)
        show = _func(self.ui, "_show_brief_offer_buttons")
        self.assertIn("self._place_mini_offer_buttons()", show)
        self.assertNotIn("right - 96.0", show)  # the old fixed offsets that left the fragment

    def test_they_are_hidden_unless_an_offer_is_showing(self):
        body = _func(self.ui, "_place_mini_offer_buttons")
        self.assertIn("if showing else None", body)

    def test_they_are_re_placed_when_the_pill_opens_collapses_tucks_or_docks(self):
        tick = _func(self.ui, "tick_")
        self.assertIn("_brief_offer_showing", tick)
        self.assertIn("self._place_mini_offer_buttons()", tick)

    def test_the_full_window_pair_is_untouched(self):
        self.assertIn("self._place_full_offer_buttons()", _func(self.ui, "_show_brief_offer_buttons"))


if __name__ == "__main__":
    unittest.main()
