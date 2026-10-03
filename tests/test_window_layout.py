"""Window geometry. No AppKit, so this runs in CI."""
import unittest

from assistant_layout import (
    COLUMN_BREAK,
    DEFAULT_H,
    DEFAULT_W,
    FRAME_AUTOSAVE_NAME,
    HEADER,
    MIN_H,
    MIN_W,
    OLD_H,
    OLD_W,
    SIDEBAR,
    clamp_size,
    layout_window,
    rects_inside,
    visible_on_first_screen,
    wrapped_height,
)

HOW = (
    "Hey Jev, open Spotify runs a command.\n"
    "Hey Jev, transcribe starts dictating, with a bubble at the bottom of the screen."
)
PRIVACY = (
    "Everything the mic hears stays on this Mac. Whisper listens locally and throws away anything that is not for her.",
    "Only the words after Hey Jev go to TypeSafe, like open Spotify, to work out what to do.",
    "Dictation audio leaves only between transcribe and stop transcribing, and only if you use that.",
    "The text of her replies goes to Fish Audio to turn into her voice. Scripted replies are saved.",
)


def _overlaps(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    separate = ax + aw <= bx + 0.5 or bx + bw <= ax + 0.5 or ay + ah <= by + 0.5 or by + bh <= ay + 0.5
    return not separate


class TestWindowSize(unittest.TestCase):
    def test_default_is_about_a_fifth_smaller_than_the_old_fixed_window(self):
        self.assertEqual((OLD_W, OLD_H), (900, 600))
        self.assertGreaterEqual(DEFAULT_W / OLD_W, 0.75)
        self.assertLessEqual(DEFAULT_W / OLD_W, 0.80)
        self.assertGreaterEqual(DEFAULT_H / OLD_H, 0.75)
        self.assertLessEqual(DEFAULT_H / OLD_H, 0.80)
        self.assertEqual((MIN_W, MIN_H), (640, 420))
        self.assertLess(MIN_W, DEFAULT_W)
        self.assertLess(MIN_H, DEFAULT_H)
        self.assertTrue(FRAME_AUTOSAVE_NAME)

    def test_clamp_never_goes_under_the_minimum(self):
        self.assertEqual(clamp_size(100, 100), (float(MIN_W), float(MIN_H)))
        self.assertEqual(clamp_size(800, 500), (800.0, 500.0))


class TestHomeCards(unittest.TestCase):
    def _spec(self, width, height):
        return layout_window(width, height, how_to=HOW, privacy=PRIVACY)

    def test_cards_fit_on_the_first_screen_at_the_minimum_and_the_default(self):
        for width, height in ((MIN_W, MIN_H), (DEFAULT_W, DEFAULT_H), (OLD_W, OLD_H)):
            spec = self._spec(width, height)
            page_w, page_h = spec["page"]
            doc_h = spec["home"]["document"][3]
            page_bounds = (0.0, 0.0, page_w, doc_h)
            boxes = []
            for card in spec["home"]["cards"]:
                self.assertTrue(visible_on_first_screen(card["box"], doc_h, page_h), (width, height, card["box"]))
                self.assertTrue(rects_inside(card["box"], page_bounds))
                parts = (card["value"], card["title"], card["sub"])
                for part in parts:
                    self.assertTrue(rects_inside(part, card["box"]), part)
                self.assertFalse(_overlaps(parts[0], parts[1]))
                self.assertFalse(_overlaps(parts[1], parts[2]))
                boxes.append(card["box"])
            self.assertEqual(len(boxes), 6)
            for i, box in enumerate(boxes):
                for other in boxes[i + 1:]:
                    self.assertFalse(_overlaps(box, other))

    def test_narrow_window_uses_two_columns_and_a_wide_one_uses_three(self):
        narrow = self._spec(MIN_W, MIN_H)
        wide = self._spec(DEFAULT_W, DEFAULT_H)
        self.assertLess(narrow["page"][0], COLUMN_BREAK)
        self.assertGreaterEqual(wide["page"][0], COLUMN_BREAK)
        self.assertEqual(narrow["home"]["columns"], 2)
        self.assertEqual(wide["home"]["columns"], 3)
        # Two columns means the first and second cards share a row.
        first, second, third = [card["box"] for card in narrow["home"]["cards"][:3]]
        self.assertEqual(first[1], second[1])
        self.assertNotEqual(first[1], third[1])

    def test_wider_window_gives_the_cards_more_width(self):
        small = self._spec(MIN_W, MIN_H)["home"]["cards"][0]["box"][2]
        large = self._spec(1000, 700)["home"]["cards"][0]["box"][2]
        self.assertGreater(large, small)


class TestChrome(unittest.TestCase):
    def test_sidebar_stays_clear_of_itself_at_the_minimum_height(self):
        spec = layout_window(MIN_W, MIN_H, how_to=HOW, privacy=PRIVACY)
        side = spec["sidebar"]
        boxes = [side["title"], side["hint"]]
        boxes.extend(box for box, _button in side["tabs"])
        boxes.extend(name for name, _time in side["timers"])
        for i, box in enumerate(boxes):
            self.assertTrue(rects_inside(box, (0, 0, SIDEBAR, MIN_H)), box)
            for other in boxes[i + 1:]:
                self.assertFalse(_overlaps(box, other), (box, other))
        self.assertEqual(spec["chrome"]["sidebar"][2], SIDEBAR)
        self.assertEqual(spec["chrome"]["page_frame"][0], SIDEBAR)

    def test_header_keeps_the_mode_switch_inside_the_window(self):
        spec = layout_window(MIN_W, MIN_H, how_to=HOW, privacy=PRIVACY)
        chrome = spec["chrome"]
        window = (0, 0, float(MIN_W), float(MIN_H))
        for key in ("dot", "status", "detail", "mode", "separator"):
            self.assertTrue(rects_inside(chrome[key], window), key)
        self.assertFalse(_overlaps(chrome["status"], chrome["mode"]))
        self.assertFalse(_overlaps(chrome["detail"], chrome["mode"]))
        self.assertEqual(chrome["separator"][1], MIN_H - HEADER)


class TestPagesReflow(unittest.TestCase):
    def test_editor_rows_stay_inside_a_narrow_page(self):
        spec = layout_window(MIN_W, MIN_H, how_to=HOW, privacy=PRIVACY)
        page_w, page_h = spec["page"]
        for name in ("dictionary", "apps", "history", "keys", "settings", "privacy"):
            page = spec[name]
            bounds = page["document"]
            self.assertGreaterEqual(bounds[2], page_w - 0.1)
            self.assertGreaterEqual(bounds[3], page_h - 0.1)
            rects = [page["title"], page["subtitle"]]
            if name in ("dictionary", "apps", "history"):
                rects.append(page["table"])
                rects.append(page["remove"])
                rects.append(page["message"])
                rects.extend(page["fields"])
                if page["button"]:
                    rects.append(page["button"])
                if page["search"]:
                    rects.append(page["search"])
            if name == "keys":
                for title, use, field in page["rows"]:
                    rects.extend((title, use, field))
                rects.extend((page["save"], page["message"]))
            if name == "settings":
                rects.extend((page["name"], page["hint"], page["popup"], page["message"]))
            if name == "privacy":
                for title, body in page["blocks"]:
                    rects.extend((title, body))
            for rect in rects:
                self.assertTrue(rects_inside(rect, bounds), (name, rect, bounds))

    def test_a_long_privacy_page_grows_and_scrolls(self):
        short = layout_window(MIN_W, MIN_H, how_to=HOW, privacy=PRIVACY)
        doc_h = short["privacy"]["document"][3]
        self.assertGreater(doc_h, short["page"][1])
        wide = layout_window(1100, 800, how_to=HOW, privacy=PRIVACY)
        self.assertGreater(wide["privacy"]["blocks"][0][1][2], short["privacy"]["blocks"][0][1][2])

    def test_table_tracks_the_page_width(self):
        narrow = layout_window(MIN_W, MIN_H, how_to=HOW, privacy=())
        wide = layout_window(1000, 600, how_to=HOW, privacy=())
        self.assertGreater(wide["dictionary"]["table"][2], narrow["dictionary"]["table"][2])
        self.assertGreater(wide["history"]["table"][2], narrow["history"]["table"][2])

    def test_wrapped_text_grows_when_the_line_is_narrow(self):
        text = "word " * 40
        self.assertGreater(wrapped_height(text, 120), wrapped_height(text, 500))


if __name__ == "__main__":
    unittest.main()
