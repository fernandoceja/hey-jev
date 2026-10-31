"""PR 8: the orb's Spotlight-style panel. Rows, arrow keys and placement beside the orb, headless."""
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
    SCREEN = (0.0, 0.0, 1440.0, 900.0)

    def _inside(self, frame, bounds):
        x, y, w, h = frame
        bx, by, bw, bh = bounds
        return x >= bx - 1e-6 and y >= by - 1e-6 and x + w <= bx + bw + 1e-6 and y + h <= by + bh + 1e-6

    def test_panel_sits_to_the_right_of_the_orb_and_is_centred_on_it(self):
        orb = (600.0, 400.0, 72.0, 72.0)
        x, y, w, h = sp.spotlight_frame(orb, self.SCREEN)
        self.assertAlmostEqual(x, orb[0] + orb[2] + sp.SPOTLIGHT_GAP)
        self.assertAlmostEqual(y + h / 2.0, orb[1] + orb[3] / 2.0)

    def test_panel_flips_to_the_left_when_the_orb_is_at_the_right_edge(self):
        orb = (1400.0, 400.0, 72.0, 72.0)
        frame = sp.spotlight_frame(orb, self.SCREEN)
        self.assertTrue(self._inside(frame, self.SCREEN))
        self.assertLess(frame[0] + frame[2], orb[0])

    def test_panel_stays_on_screen_near_the_top_and_bottom_edges(self):
        for orb in [(600.0, 0.0, 72.0, 72.0), (600.0, 828.0, 72.0, 72.0), (1300.0, 0.0, 72.0, 72.0)]:
            self.assertTrue(self._inside(sp.spotlight_frame(orb, self.SCREEN), self.SCREEN), orb)

    def test_placement_is_inside_a_screen_with_a_nonzero_origin(self):
        screen = (-1440.0, 60.0, 1440.0, 800.0)
        orb = (-100.0, 300.0, 72.0, 72.0)
        self.assertTrue(self._inside(sp.spotlight_frame(orb, screen), screen))

    def test_size_is_the_panel_width_and_height_by_default(self):
        _x, _y, w, h = sp.spotlight_frame((600.0, 400.0, 72.0, 72.0), self.SCREEN)
        self.assertEqual((w, h), (sp.SPOTLIGHT_WIDTH, sp.panel_height()))


class AnimationTests(unittest.TestCase):
    def test_fade_and_scale_match_the_spec(self):
        self.assertEqual(sp.SPOTLIGHT_START_SCALE, 0.96)
        self.assertEqual(sp.SPOTLIGHT_FADE_SECONDS, 0.15)
        self.assertEqual(sp.SPOTLIGHT_RADIUS, 26.0)


if __name__ == "__main__":
    unittest.main()
