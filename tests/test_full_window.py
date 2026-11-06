"""Full Jev window (PR 5 and PR 6b): layout, chrome, sidebar and wiring. No AppKit."""
import os
import unittest

import full_window as fw
import mini_bar

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIZES = (fw.FULL_MIN, fw.FULL_DEFAULT, (1200.0, 900.0), fw.FULL_MAX)


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


def _overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _controls(lay):
    """Every on-window control rect for a full_layout result, in window coordinates."""
    rects = {"new_chat": lay["new_chat"], "sidebar_list": lay["sidebar_list"], "header": lay["header"],
             "input": lay["input"], "field": lay["field"], "mic": lay["mic"], "chips": lay["chips"]}
    if lay["greeting"]:
        rects["greeting"] = lay["greeting"]
    if lay["conversation"]:
        rects["conversation"] = lay["conversation"]
    return rects


class FullWindowLayoutTests(unittest.TestCase):
    def test_size_is_clamped(self):
        self.assertEqual(fw.clamp_full_size(100, 100), fw.FULL_MIN)
        self.assertEqual(fw.clamp_full_size(9999, 9999), fw.FULL_MAX)
        self.assertEqual(fw.clamp_full_size(800, 600), (800.0, 600.0))

    def test_regions_fit_inside_bounds_at_every_size(self):
        for size in SIZES:
            for has_conv in (False, True):
                lay = fw.full_layout(size[0], size[1], has_conversation=has_conv)
                box = (0.0, 0.0) + lay["size"]
                for key, rect in _controls(lay).items():
                    self.assertTrue(_inside(rect, box), (size, has_conv, key))
                self.assertTrue(_inside(lay["sidebar"], box))

    def test_controls_do_not_overlap_each_other(self):
        for size in SIZES:
            for has_conv in (False, True):
                rects = _controls(fw.full_layout(size[0], size[1], has_conversation=has_conv))
                # The field and mic sit inside the input pill on purpose; everything else must be separate.
                names = [k for k in rects if k not in ("input", "field", "mic")]
                for i, a in enumerate(names):
                    for b in names[i + 1:]:
                        self.assertFalse(_overlap(rects[a], rects[b]), (size, has_conv, a, b))

    def test_input_is_a_44_point_pill_with_mic_inside(self):
        lay = fw.full_layout(*fw.FULL_DEFAULT)
        x, y, w, h = lay["input"]
        self.assertEqual(h, 44.0)
        self.assertEqual(fw.INPUT_H / 2.0, 22.0)
        mx, my, mw, mh = lay["mic"]
        self.assertTrue(_inside(lay["mic"], lay["input"]))
        self.assertLessEqual(lay["field"][0] + lay["field"][2], mx)

    def test_greeting_high_and_chips_below_input(self):
        lay = fw.full_layout(*fw.FULL_DEFAULT)
        g, i, c = lay["greeting"], lay["input"], lay["chips"]
        self.assertGreater(g[1], i[1] + i[3])
        self.assertGreaterEqual(i[1], c[1] + c[3])

    def test_conversation_replaces_greeting_and_grows(self):
        lay = fw.full_layout(*fw.FULL_DEFAULT, has_conversation=True)
        self.assertIsNone(lay["greeting"])
        self.assertIsNotNone(lay["conversation"])
        small = fw.full_layout(*fw.FULL_MIN, has_conversation=True)["conversation"]
        big = fw.full_layout(1200, 900, has_conversation=True)["conversation"]
        self.assertGreater(big[2], small[2])
        self.assertGreater(big[3], small[3])
        self.assertGreater(lay["conversation"][1], lay["input"][1])

    def test_chips_never_clipped(self):
        frames = fw.chip_frames(["a", "b", "c"], {"a": 150, "b": 150, "c": 150}, (0, 0, 320, 40))
        self.assertEqual([f["id"] for f in frames], ["a", "b"])
        for f in frames:
            self.assertLessEqual(f["frame"][0] + f["frame"][2], 320.01)


class DockClearanceTests(unittest.TestCase):
    def test_dock_rect_clear_of_every_control_and_the_sidebar_list(self):
        for size in SIZES:
            for has_conv in (False, True):
                lay = fw.full_layout(size[0], size[1], has_conversation=has_conv)
                dock = fw.dock_rect(lay)
                for key, rect in _controls(lay).items():
                    if key == "sidebar_list":
                        continue  # the list is a container; its rows are checked against the dock below
                    self.assertFalse(_overlap(dock, rect), (size, has_conv, key, dock, rect))

    def test_sidebar_rows_stay_right_of_the_dock(self):
        dock = fw.dock_rect(fw.full_layout(*fw.FULL_DEFAULT))
        items, _height = fw.sidebar_items(("one", "two"))
        list_x = fw.full_layout(*fw.FULL_DEFAULT)["sidebar_list"][0]
        for item in items:
            x, _y, _w, _h = item["frame"]
            self.assertGreaterEqual(x + list_x, dock[0] + dock[2] + 7.9, item["label"])

    def test_dock_is_centred_on_the_left_edge_at_mid_height(self):
        lay = fw.full_layout(*fw.FULL_DEFAULT)
        w_, h = lay["size"]
        x, y, dw, dh = fw.dock_rect(lay)
        self.assertAlmostEqual(x + dw / 2.0, 0.0)
        self.assertAlmostEqual(y + dh / 2.0, h / 2.0)
        self.assertEqual((dw, dh), (fw.DOCK_ORB, fw.DOCK_ORB))


class SidebarTests(unittest.TestCase):
    def test_sections_in_order(self):
        items, _ = fw.sidebar_items()
        heads = [i["label"] for i in items if i["kind"] == "head"]
        self.assertEqual(heads, ["Get started", "Today", "Captures", "Games", "Mac", "Pages", "Recent"])

    def test_get_started_has_three_rows(self):
        self.assertEqual(len(fw.GET_STARTED), 3)
        self.assertEqual([label for _id, label, _p in fw.GET_STARTED],
                         ["Try a voice command", "Capture your screen", "Plan my day"])

    def test_every_sidebar_phrase_is_an_existing_command(self):
        phrases = [p for _id, _l, p in fw.GET_STARTED]
        for _title, rows in fw.CATEGORIES:
            phrases.extend(p for _id, _l, p in rows)
        for phrase in phrases:
            self.assertIsNotNone(mini_bar.submission(phrase), phrase)
        self.assertIn("brief me", phrases)
        self.assertIn("cleanmymac scan", phrases)
        self.assertIn("list games", phrases)

    def test_pages_cover_every_main_window_tab(self):
        import re
        tabs = re.search(r"^TABS = \((.*)\)$", _ui(), re.M).group(1)
        keys = set(re.findall(r'\("([a-z]+)", "', tabs)) - {"home"}
        self.assertEqual({key for key, _label in fw.PAGES}, keys)

    def test_recent_lists_history_and_is_capped(self):
        rows = [("you", f"ask {n}") for n in range(12)]
        items, _ = fw.sidebar_items(fw.history_items(rows))
        recent = [i["label"] for i in items if i["kind"] == "row" and i["action"][0] == "fill"]
        self.assertEqual(len(recent), fw.RECENT_MAX)
        self.assertEqual(recent[0], "ask 11")

    def test_empty_recent_says_nothing_yet(self):
        items, _ = fw.sidebar_items(())
        self.assertIn("Nothing yet.", [i["label"] for i in items if i["kind"] == "empty"])

    def test_long_labels_are_shortened(self):
        self.assertLessEqual(len(fw.short_label("x" * 100)), fw.LABEL_MAX)
        self.assertEqual(fw.short_label("  a   b "), "a b")

    def test_sidebar_list_height_covers_content(self):
        items, height = fw.sidebar_items(())
        self.assertGreaterEqual(height, max(i["frame"][1] + i["frame"][3] for i in items) - 0.01)


class FullWindowContentTests(unittest.TestCase):
    ROWS = [("you", "weather"), ("jev", "Sunny, 72."), ("you", "eta home"), ("jev", "18 minutes.")]

    def test_history_newest_first(self):
        self.assertEqual(fw.history_items(self.ROWS), ["eta home", "weather"])

    def test_last_result(self):
        self.assertEqual(fw.last_result(self.ROWS), "18 minutes.")
        self.assertEqual(fw.last_result([]), "")

    def test_conversation_lines(self):
        self.assertEqual(fw.conversation_lines(self.ROWS[:2]), [("You", "weather"), ("Jev", "Sunny, 72.")])

    def test_new_chat_hides_only_older_rows(self):
        h = mini_bar.TypedHistory()
        h.note_request("weather")
        h.note_reply("Sunny.")
        cut = h.added
        h.note_request("eta home")
        self.assertEqual(fw.chat_rows(h.rows, h.added, cut), [("you", "eta home")])
        self.assertEqual(len(h.rows), 3)  # the typed history itself is untouched

    def test_new_chat_survives_trimming(self):
        h = mini_bar.TypedHistory(limit=4)
        for n in range(4):
            h.note_request(f"old {n}")
            h.note_reply(f"reply {n}")
        cut = h.added
        h.note_request("fresh")
        h.note_reply("ok")
        self.assertEqual(fw.chat_rows(h.rows, h.added, cut), [("you", "fresh"), ("jev", "ok")])
        self.assertEqual(fw.chat_rows(h.rows, h.added, h.added), [])

    def test_reduce_transparency_is_solid(self):
        self.assertEqual(fw.full_chrome(True)["backing"], "solid")
        self.assertEqual(fw.full_chrome(False)["backing"], "vibrancy")

    def test_rea_tokens(self):
        self.assertEqual(fw.token("ink"), (round(0x20 / 255, 4), round(0x25 / 255, 4), round(0x2B / 255, 4)))
        self.assertNotEqual(fw.token("page"), fw.token("page", dark=True))
        for name in fw.PALETTE:
            self.assertNotEqual(fw.token(name), fw.token(name, dark=True), name)

    def test_placeholder_text(self):
        self.assertEqual(fw.PLACEHOLDER, "Ask Jev anything…")

    def test_greeting_text_is_the_popover_greeting(self):
        self.assertEqual(mini_bar.greeting_text("Jev"), "Hi, Jev. What can I help with?")


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
        self.assertIn("self._sync_full_chips()", build)  # PR 8b: the chip buttons are built there
        self.assertIn("PopoverChipButton", _func(ui, "_sync_full_chips"))
        self.assertIn("setFrameAutosaveName_(fw.FULL_AUTOSAVE)", build)
        self.assertIn("NSWindowStyleMaskResizable", build)
        self.assertIn("self._refresh_full_window()", _func(ui, "_refresh_popover_history"))

    def test_mic_and_chips_use_the_existing_paths(self):
        ui = _ui()
        self.assertIn("self.full_mic.setTarget_(self)", ui)
        self.assertIn("target.miniMicDown_(self)", ui)  # HoldMicButton presses and releases the mic
        self.assertIn("target.miniMicUp_(self)", ui)
        chip = _func(ui, "miniChip_")
        self.assertIn("chip_command_plan(chip_id)", chip)
        self.assertIn("self._dispatch_text_plan(plan)", chip)

    def test_sidebar_rows_send_or_open_or_fill(self):
        row = _func(_ui(), "fullRow_")
        self.assertIn("submission(payload", row)
        self.assertIn("self._dispatch_text_plan(plan)", row)
        self.assertIn("self._open_main_page(payload)", row)
        self.assertIn("self.full_field.setStringValue_(payload)", row)
        self.assertNotIn("controls.put", row)

    def test_open_main_page_selects_the_tab(self):
        opener = _func(_ui(), "_open_main_page")
        self.assertIn("self.showMain_(None)", opener)
        self.assertIn("self._select_tab(key)", opener)

    def test_new_chat_is_on_screen_only(self):
        new_chat = _func(_ui(), "fullNewChat_")
        self.assertIn("_full_chat_cut", new_chat)
        self.assertNotIn("controls", new_chat)
        self.assertNotIn("typed.rows", new_chat)
        self.assertNotIn("typed.rows.", new_chat)

    def test_placeholder_and_greeting_wired(self):
        ui = _ui()
        self.assertIn("setPlaceholderString_(fw.PLACEHOLDER)", ui)
        self.assertIn("greeting_text()", _func(ui, "_build_full_window"))

    def test_snapshot_uses_a_flat_stand_in_for_vibrancy(self):
        snap = _func(_ui(), "_snapshot_full_window")
        self.assertIn("self.full_effect.setHidden_(True)", snap)
        self.assertIn("finally:", snap)
        self.assertLess(snap.index("cacheDisplayInRect_toBitmapImageRep_"), snap.index("finally:"))

    def test_glass_covers_the_whole_window(self):
        ui = _ui()
        layout = _func(ui, "_layout_full_window")
        self.assertIn("self.full_effect.setFrame_(R((0, 0, cw, ch)))", layout)
        chrome = _func(ui, "_apply_full_chrome")
        self.assertIn('self.full_main.setHidden_(chrome["backing"] != "solid")', chrome)

    def test_respects_reduce_transparency(self):
        chrome = _func(_ui(), "_apply_full_chrome")
        self.assertIn("accessibilityDisplayShouldReduceTransparency", chrome)
        self.assertIn("fw.full_chrome", chrome)

    def test_close_returns_to_orb_and_resize_relayouts(self):
        ui = _ui()
        self.assertIn("full_window", _func(ui, "windowWillClose_"))
        self.assertIn("_layout_full_window", _func(ui, "windowDidResize_"))

    def test_palette_comes_from_tokens(self):
        ui = _ui()
        self.assertIn("fw.token(", ui)
        self.assertIn("_fw_color", ui)

    def test_no_sockets_or_secrets(self):
        src = open(os.path.join(ROOT, "full_window.py"), encoding="utf-8").read()
        for bad in ("socket", "Keychain", "bridge_secret", "subprocess"):
            self.assertNotIn(bad, src)


if __name__ == "__main__":
    unittest.main()
