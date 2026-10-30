"""Full Jev window (PR 5): layout, chrome and wiring. No AppKit."""
import os
import unittest

import full_window as fw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ui():
    return open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8").read()


def _func(source, name):
    start = source.index(f"def {name}")
    end = source.find("\n    def ", start + 10)
    return source[start:end]


def _inside(inner, outer):
    x, y, w, h = inner
    ox, oy, ow, oh = outer
    return x >= ox - 0.01 and y >= oy - 0.01 and x + w <= ox + ow + 0.01 and y + h <= oy + oh + 0.01


class FullWindowLayoutTests(unittest.TestCase):
    def test_size_is_clamped(self):
        self.assertEqual(fw.clamp_full_size(100, 100), fw.FULL_MIN)
        self.assertEqual(fw.clamp_full_size(9999, 9999), fw.FULL_MAX)
        self.assertEqual(fw.clamp_full_size(800, 600), (800.0, 600.0))

    def test_regions_fit_and_do_not_overlap_at_every_size(self):
        for size in (fw.FULL_MIN, fw.FULL_DEFAULT, (1200.0, 900.0), fw.FULL_MAX):
            lay = fw.full_layout(*size)
            box = (0.0, 0.0) + lay["size"]
            for key in ("sidebar", "history", "header", "conversation", "result", "chips", "input", "field", "mic"):
                self.assertTrue(_inside(lay[key], box), (size, key))
            c, r, ch, i = lay["conversation"], lay["result"], lay["chips"], lay["input"]
            self.assertGreaterEqual(c[1], r[1] + r[3])
            self.assertGreaterEqual(r[1], ch[1] + ch[3])
            self.assertGreaterEqual(ch[1], i[1] + i[3])
            self.assertGreaterEqual(lay["mic"][0], lay["field"][0] + lay["field"][2])
            self.assertGreaterEqual(c[0], lay["sidebar"][2])

    def test_conversation_grows_with_window(self):
        small = fw.full_layout(*fw.FULL_MIN)["conversation"]
        big = fw.full_layout(1200, 900)["conversation"]
        self.assertGreater(big[2], small[2])
        self.assertGreater(big[3], small[3])

    def test_chips_never_clipped(self):
        frames = fw.chip_frames(["a", "b", "c"], {"a": 150, "b": 150, "c": 150}, (0, 0, 320, 40))
        self.assertEqual([f["id"] for f in frames], ["a", "b"])
        for f in frames:
            self.assertLessEqual(f["frame"][0] + f["frame"][2], 320.01)


class FullWindowContentTests(unittest.TestCase):
    ROWS = [("you", "weather"), ("jev", "Sunny, 72."), ("you", "eta home"), ("jev", "18 minutes.")]

    def test_history_newest_first(self):
        self.assertEqual(fw.history_items(self.ROWS), ["eta home", "weather"])

    def test_last_result(self):
        self.assertEqual(fw.last_result(self.ROWS), "18 minutes.")
        self.assertEqual(fw.last_result([]), "")

    def test_conversation_lines(self):
        self.assertEqual(fw.conversation_lines(self.ROWS[:2]), [("You", "weather"), ("Jev", "Sunny, 72.")])

    def test_reduce_transparency_is_solid(self):
        self.assertEqual(fw.full_chrome(True)["backing"], "solid")
        self.assertEqual(fw.full_chrome(False)["backing"], "vibrancy")

    def test_rea_tokens(self):
        self.assertEqual(fw.token("ink"), (round(0x20 / 255, 4), round(0x25 / 255, 4), round(0x2B / 255, 4)))
        self.assertNotEqual(fw.token("page"), fw.token("page", dark=True))


class HeardEchoTests(unittest.TestCase):
    def test_echo_of_request_is_not_the_reply(self):
        from mini_bar import TypedHistory
        h = TypedHistory()
        h.note_request("what time is it")
        self.assertEqual(h.note_reply("What time is it?"), "")
        self.assertEqual(h.note_reply("It's 7:03 PM."), "It's 7:03 PM.")
        self.assertEqual(fw.last_result(h.rows), "It's 7:03 PM.")


class FullWindowWiringTests(unittest.TestCase):
    def test_expand_opens_full_window_with_draft(self):
        expand = _func(_ui(), "miniExpandHome_")
        self.assertIn("_show_full_window(draft)", expand)
        self.assertNotIn("_dispatch_text_plan", expand)

    def test_reuses_backend(self):
        ui = _ui()
        submit = _func(ui, "fullSubmit_")
        self.assertIn("self._dispatch_text_plan(plan)", submit)
        self.assertNotIn("controls.put", submit)
        build = _func(ui, "_build_full_window")
        self.assertIn("HoldMicButton", build)
        self.assertIn("PopoverChipButton", build)
        self.assertIn("setFrameAutosaveName_(fw.FULL_AUTOSAVE)", build)
        self.assertIn("NSWindowStyleMaskResizable", build)
        self.assertIn("self._refresh_full_window()", _func(ui, "_refresh_popover_history"))

    def test_respects_reduce_transparency(self):
        chrome = _func(_ui(), "_apply_full_chrome")
        self.assertIn("accessibilityDisplayShouldReduceTransparency", chrome)
        self.assertIn("fw.full_chrome", chrome)

    def test_close_returns_to_orb_and_resize_relayouts(self):
        ui = _ui()
        self.assertIn("full_window", _func(ui, "windowWillClose_"))
        self.assertIn("_layout_full_window", _func(ui, "windowDidResize_"))

    def test_no_sockets_or_secrets(self):
        src = open(os.path.join(ROOT, "full_window.py"), encoding="utf-8").read()
        for bad in ("socket", "Keychain", "bridge_secret", "subprocess"):
            self.assertNotIn(bad, src)


if __name__ == "__main__":
    unittest.main()
