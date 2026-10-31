"""PR 8: the Spotlight-style panel. Rows, arrow keys and placement on the screen, headless."""
import unittest

import orb_spotlight as sp


class RowTests(unittest.TestCase):
    def test_rows_are_the_menu_items_in_order_with_their_hints(self):
        titles = [row[0] for row in sp.SPOTLIGHT_ROWS]
        self.assertEqual(titles, ["Open Jev", "New Chat", "Capture Area", "Mark Up", "Type to Jev", "Settings", "Quit"])
        hints = {row[0]: row[3] for row in sp.SPOTLIGHT_ROWS}
        self.assertEqual(hints["Capture Area"], "⌘W")
        self.assertEqual(hints["Type to Jev"], "⌃⌥J")
        self.assertEqual(hints["Quit"], "⌘Q")

    def test_every_row_has_a_symbol_and_a_unique_selector(self):
        selectors = [row[1] for row in sp.SPOTLIGHT_ROWS]
        self.assertEqual(len(selectors), len(set(selectors)))
        self.assertTrue(all(row[2] for row in sp.SPOTLIGHT_ROWS))

    def test_panel_height_fits_the_field_and_every_row(self):
        expected = sp.SPOTLIGHT_PAD + sp.SPOTLIGHT_FIELD_H + sp.SPOTLIGHT_PAD + 7 * sp.SPOTLIGHT_ROW_H + sp.SPOTLIGHT_PAD
        self.assertEqual(sp.panel_height(), expected)


class KeyTests(unittest.TestCase):
    def test_key_codes_match_macos(self):
        self.assertEqual((sp.KEY_RETURN, sp.KEY_ESCAPE, sp.KEY_DOWN, sp.KEY_UP), (36, 53, 125, 126))

    def test_down_from_nothing_highlights_the_first_row_and_wraps(self):
        self.assertEqual(sp.next_index(None, sp.KEY_DOWN, 7), 0)
        self.assertEqual(sp.next_index(-1, sp.KEY_DOWN, 7), 0)
        self.assertEqual(sp.next_index(6, sp.KEY_DOWN, 7), 0)
        self.assertEqual(sp.next_index(2, sp.KEY_DOWN, 7), 3)

    def test_up_from_nothing_highlights_the_last_row_and_wraps(self):
        self.assertEqual(sp.next_index(None, sp.KEY_UP, 7), 6)
        self.assertEqual(sp.next_index(0, sp.KEY_UP, 7), 6)
        self.assertEqual(sp.next_index(4, sp.KEY_UP, 7), 3)

    def test_other_keys_leave_the_highlight_alone(self):
        self.assertEqual(sp.next_index(3, 36, 7), 3)
        self.assertEqual(sp.next_index(None, 36, 7), -1)

    def test_no_rows_means_no_highlight(self):
        self.assertEqual(sp.next_index(0, sp.KEY_DOWN, 0), -1)


class PlacementTests(unittest.TestCase):
    """Spotlight placement: centred horizontally on the screen with the mouse, top edge a quarter down."""
    SCREEN = (0.0, 0.0, 1440.0, 900.0)

    def _inside(self, frame, bounds):
        x, y, w, h = frame
        bx, by, bw, bh = bounds
        return x >= bx - 1e-6 and y >= by - 1e-6 and x + w <= bx + bw + 1e-6 and y + h <= by + bh + 1e-6

    def test_the_panel_is_centred_horizontally(self):
        x, _y, w, _h = sp.spotlight_frame(self.SCREEN)
        self.assertAlmostEqual(x + w / 2.0, 720.0)

    def test_its_top_edge_is_a_quarter_of_the_height_down_from_the_top(self):
        _x, y, _w, h = sp.spotlight_frame(self.SCREEN)
        self.assertAlmostEqual(y + h, 900.0 * 0.75)

    def test_it_is_placed_on_the_visible_frame_it_is_given(self):
        visible = (1440.0, 60.0, 1920.0, 1000.0)  # a second screen with a non-zero origin
        x, y, w, h = sp.spotlight_frame(visible)
        self.assertAlmostEqual(x + w / 2.0, 1440.0 + 960.0)
        self.assertAlmostEqual(y + h, 60.0 + 1000.0 * 0.75)

    def test_it_stays_inside_a_small_visible_frame(self):
        small = (0.0, 0.0, 600.0, 400.0)  # smaller than the screen, but tall enough for the panel
        self.assertTrue(self._inside(sp.spotlight_frame(small), small))

    def test_default_size_is_the_panel_width_and_height(self):
        _x, _y, w, h = sp.spotlight_frame(self.SCREEN)
        self.assertEqual((w, h), (sp.SPOTLIGHT_WIDTH, sp.panel_height()))

    def test_a_given_size_is_used(self):
        _x, _y, w, h = sp.spotlight_frame(self.SCREEN, size=(500.0, 300.0))
        self.assertEqual((w, h), (500.0, 300.0))


class AnimationTests(unittest.TestCase):
    def test_fade_and_scale_match_the_spec(self):
        self.assertEqual(sp.SPOTLIGHT_START_SCALE, 0.96)
        self.assertEqual(sp.SPOTLIGHT_FADE_SECONDS, 0.15)
        self.assertEqual(sp.SPOTLIGHT_RADIUS, 26.0)


if __name__ == "__main__":
    unittest.main()
