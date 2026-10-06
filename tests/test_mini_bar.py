"""Mini command bar. No AppKit, so this runs in CI."""
import os
import unittest

import commands
from assistant_layout import DEFAULT_H, DEFAULT_W, MIN_H, MIN_W, layout_window, rects_inside
from mini_bar import (
    BAR_COLLECTION,
    BAR_GRIP,
    BAR_H,
    BAR_MAX_H,
    BAR_MAX_W,
    BAR_MIN_H,
    BAR_MIN_W,
    BAR_W,
    CAN_JOIN_ALL_SPACES,
    DOCK_GAP,
    FULL_SCREEN_AUXILIARY,
    PLACEHOLDER,
    REPLY_SECONDS,
    SIZE_KEY,
    BarController,
    background_action,
    bar_controls,
    bar_metrics,
    default_size,
    drag_origin,
    enabled_from_pref,
    format_origin,
    format_size,
    hit_control,
    mic_event,
    attachments_supported,
    parse_origin,
    parse_size,
    pill_chrome,
    place_bar,
    plus_item,
    plus_menu,
    remembered_size,
    reply_text,
    reset_origin,
    resize_edges,
    resize_frame,
    submission,
    trailing_symbol,
    walk_menu,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# A MacBook Air visible frame: Dock about 70pt, menu bar already excluded.
AIR = (0.0, 70.0, 1440.0, 806.0)
# A display to the right, and one whose origin is left of the main screen.
RIGHT = (1440.0, 0.0, 1920.0, 1080.0)
LEFT = (-1920.0, 0.0, 1920.0, 1080.0)


def _overlaps(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    separate = ax + aw <= bx + 0.5 or bx + bw <= ax + 0.5 or ay + ah <= by + 0.5 or by + bh <= ay + 0.5
    return not separate


def _func(source, name):
    """The body of a top-level function, or of a method indented four spaces."""
    start = source.index(f"def {name}")
    line_start = source.rfind("\n", 0, start) + 1
    indent = start - line_start
    marker = "\n" + (" " * indent) + "def "
    nxt = source.find(marker, start + 1)
    if nxt < 0:
        nxt = len(source)
    return source[start:nxt]


class TestVisibility(unittest.TestCase):
    def test_hidden_until_the_main_window_is_minimized_or_closed(self):
        bar = BarController()
        self.assertTrue(bar.enabled)
        self.assertFalse(bar.should_show())
        self.assertTrue(bar.main_window_changed(False))
        self.assertFalse(bar.quitting)

    def test_restoring_the_window_hides_the_bar_and_clears_esc(self):
        bar = BarController()
        bar.main_window_changed(False)
        self.assertFalse(bar.dismiss())
        self.assertFalse(bar.should_show())
        bar.main_window_changed(True)
        self.assertFalse(bar.should_show())
        self.assertTrue(bar.main_window_changed(False))

    def test_esc_while_the_window_is_open_does_not_block_the_next_minimize(self):
        bar = BarController()
        self.assertFalse(bar.dismiss())
        self.assertTrue(bar.main_window_changed(False))

    def test_the_settings_switch_defaults_on_and_can_turn_it_off(self):
        self.assertTrue(enabled_from_pref(None))
        self.assertTrue(enabled_from_pref(1))
        self.assertTrue(enabled_from_pref(True))
        self.assertFalse(enabled_from_pref(0))
        self.assertFalse(enabled_from_pref(False))
        bar = BarController()
        bar.main_window_changed(False)
        self.assertFalse(bar.set_enabled(False))
        self.assertTrue(bar.set_enabled(True))

    def test_quit_hides_the_bar_and_closing_the_window_does_not(self):
        closed = BarController()
        closed.main_window_changed(False)
        self.assertTrue(closed.should_show())
        quitting = BarController()
        quitting.main_window_changed(False)
        self.assertFalse(quitting.quit())
        quitting.main_window_changed(False)
        self.assertFalse(quitting.should_show())


class TestSubmit(unittest.TestCase):
    def test_return_queues_the_same_turn_as_voice_and_does_not_reveal_the_window(self):
        plan = submission("  open   Spotify  ")
        self.assertEqual(plan["kind"], "run")
        self.assertEqual(plan["control"], ("text", "open Spotify"))
        self.assertFalse(plan["reveal_main"])
        self.assertNotIn("local_only", plan)
        self.assertIsNone(submission("   "))
        self.assertIsNone(submission(""))
        echo = submission("It's 3:45.", shown_reply="It's 3:45.")
        self.assertEqual(echo["kind"], "clear")
        self.assertFalse(echo["reveal_main"])
        self.assertNotIn("control", echo)

    def test_a_non_local_phrase_is_still_queued_for_the_voice_path(self):
        """'what time is it in Tokyo' is not a local command. Voice sends it on. Typing does too."""
        phrase = "what time is it in Tokyo"
        self.assertIsNone(commands.route_before_api(phrase))
        plan = submission(phrase)
        self.assertEqual(plan["control"], ("text", phrase))
        self.assertFalse(plan["reveal_main"])
        self.assertNotIn("local_only", plan)

    def test_known_commands_stay_on_the_local_router(self):
        self.assertEqual(commands.route_before_api("what time is it"), "info_time")
        self.assertEqual(commands.route_before_api("open Spotify"), "app_open")
        self.assertEqual(commands.route_before_api("check my messages from My Love"), "info_messages")
        self.assertNotIn("info_messages", commands.BRIDGE_ALLOW)

    def test_the_mic_button_uses_the_option_key_tokens(self):
        self.assertEqual(mic_event("down"), "press")
        self.assertEqual(mic_event("up"), "release")
        ui = open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8").read()
        self.assertIn('self.controls.put("press" if is_down else "release")', ui)
        submit = _func(ui, "miniSubmit_")
        for banned in ("deminiaturize_", "makeKeyAndOrderFront_", "activateIgnoringOtherApps_", "showMain_"):
            self.assertNotIn(banned, submit)
        self.assertIn("NSWindowStyleMaskNonactivatingPanel", ui)
        build = _func(ui, "_build_mini_bar")
        self.assertIn('setAction_("miniPlus:")', build)
        self.assertIn('_set_button_symbol(self.mini_plus, "plus", "More")', build)
        self.assertNotIn("showMain:", build)
        self.assertNotIn("NSAppearanceNameDarkAqua", ui)

    def test_reply_is_the_status_line_and_only_for_a_moment(self):
        self.assertEqual(reply_text("Speaking", "Spoken on this Mac only"), "Spoken on this Mac only")
        self.assertNotIn("love", reply_text("Speaking", "Spoken on this Mac only").lower())
        self.assertEqual(reply_text("Ready", "It's 3:45."), "It's 3:45.")
        self.assertIsNone(reply_text("Ready", "Ready when you are"))
        self.assertIsNone(reply_text("Starting", "Loading Whisper\u2026"))
        bar = BarController()
        bar.main_window_changed(False)
        bar.note_reply("It's 3:45.", 10.0)
        self.assertFalse(bar.reply_due_clear(10.0 + REPLY_SECONDS - 0.1, "It's 3:45."))
        self.assertTrue(bar.reply_due_clear(10.0 + REPLY_SECONDS, "It's 3:45."))
        bar.note_reply("It's 3:45.", 10.0)
        self.assertFalse(bar.reply_due_clear(30.0, "open Spotify"))
        self.assertEqual(bar.reply, "")

    def test_typed_text_calls_the_same_turn_as_voice(self):
        source = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        self.assertNotIn("local_only", source)
        self.assertNotIn("TYPED_REFUSAL", source)
        start = source.index('command[0] == "text"')
        branch = source[start:source.index("if rec.wake:", start)]
        self.assertIn("target=run_turn, args=(typed, None)", branch)
        handle = _func(source, "handle")
        self.assertIn('emit(notify, "Thinking"', handle)
        self.assertNotIn("local_only", handle)


class TestPlacement(unittest.TestCase):
    def test_default_is_bottom_center_above_the_dock(self):
        self.assertEqual((BAR_W, BAR_H), (420.0, 44.0))
        self.assertEqual(PLACEHOLDER, "Message Jev")
        x, y = place_bar(None, AIR)
        self.assertEqual(x, AIR[0] + (AIR[2] - BAR_W) / 2)
        self.assertEqual(y, AIR[1] + DOCK_GAP)
        self.assertGreater(y, AIR[1])

    def test_a_remembered_on_screen_spot_is_kept_and_an_offscreen_one_is_not(self):
        self.assertEqual(place_bar((120.0, 400.0), AIR), (120.0, 400.0))
        self.assertEqual(parse_origin(format_origin(120, 400)), (120.0, 400.0))
        fallback = place_bar(None, AIR)
        self.assertEqual(place_bar((-800.0, -800.0), AIR), fallback)
        self.assertEqual(place_bar(parse_origin("nope"), AIR), fallback)
        self.assertIsNone(parse_origin(None))
        self.assertIsNone(parse_origin(""))

    def test_a_spot_on_another_display_is_kept_and_one_off_every_screen_is_not(self):
        screens = (AIR, RIGHT, LEFT)
        fallback = place_bar(None, screens)
        self.assertEqual(fallback, place_bar(None, AIR))
        self.assertEqual(place_bar((1600.0, 200.0), screens), (1600.0, 200.0))
        self.assertEqual(place_bar((-1800.0, 100.0), screens), (-1800.0, 100.0))
        self.assertEqual(place_bar((9000.0, 9000.0), screens), fallback)
        self.assertEqual(place_bar(None, []), (0.0, DOCK_GAP))
        # Half the pill still on a screen stays. Less than that goes back to the bottom.
        kept_x = AIR[2] - BAR_W / 2.0
        self.assertEqual(place_bar((kept_x, 400.0), AIR)[0], kept_x)
        self.assertEqual(place_bar((kept_x + 1.0, 400.0), AIR), fallback)

    def test_a_drag_follows_the_mouse_onto_any_screen(self):
        self.assertEqual(drag_origin((510.0, 142.0), (100.0, 200.0), (1600.0, 400.0)), (2010.0, 342.0))
        self.assertEqual(drag_origin((0.0, 70.0), (50.0, 80.0), (-400.0, 90.0)), (-450.0, 80.0))
        self.assertEqual(CAN_JOIN_ALL_SPACES, 1)
        self.assertEqual(FULL_SCREEN_AUXILIARY, 256)
        self.assertEqual(BAR_COLLECTION & CAN_JOIN_ALL_SPACES, CAN_JOIN_ALL_SPACES)
        self.assertEqual(BAR_COLLECTION & FULL_SCREEN_AUXILIARY, FULL_SCREEN_AUXILIARY)

    def test_plus_field_and_mic_fit_in_the_pill(self):
        frames = list(bar_controls().values())
        self.assertEqual(len(frames), 3)
        bounds = (0.0, 0.0, BAR_W, BAR_H)
        for rect in frames:
            self.assertTrue(rects_inside(rect, bounds), rect)
            self.assertGreater(rect[2], 20)
        for i, rect in enumerate(frames):
            for other in frames[i + 1:]:
                self.assertFalse(_overlaps(rect, other))

    def test_edges_drag_and_the_controls_do_not(self):
        frames = bar_controls()
        plus, field, mic = frames["plus"], frames["field"], frames["mic"]
        self.assertEqual(hit_control(plus[0], plus[1]), "plus")
        self.assertEqual(hit_control(field[0] + 4, field[1] + 4), "field")
        self.assertEqual(hit_control(mic[0] + 1, mic[1] + 1), "mic")
        # Rounded ends and the bands above and below the controls are background.
        self.assertGreaterEqual(plus[0], 8.0)
        self.assertGreaterEqual(plus[1], 8.0)
        self.assertGreaterEqual(BAR_W - (mic[0] + mic[2]), 8.0)
        self.assertGreaterEqual(BAR_H - (plus[1] + plus[3]), 8.0)
        self.assertGreaterEqual(field[1], 8.0)
        self.assertEqual(field[1] + field[3] / 2.0, BAR_H / 2.0)
        self.assertIsNone(hit_control(1.0, BAR_H / 2.0))
        self.assertIsNone(hit_control(BAR_W - 1.0, BAR_H / 2.0))
        self.assertIsNone(hit_control(BAR_W / 2.0, 1.0))
        self.assertIsNone(hit_control(BAR_W / 2.0, BAR_H - 1.0))
        self.assertIsNone(hit_control(field[0] + field[2] + 2.0, field[1] + 4.0))
        # Just inside the grip is still a drag. The outer pixels resize.
        self.assertEqual(background_action(1, BAR_GRIP + 2.0, BAR_H / 2.0), "drag")
        self.assertEqual(background_action(1, 1.0, BAR_H / 2.0), "resize")

    def test_the_panel_drags_from_its_background_and_joins_every_space(self):
        ui = open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8").read()
        self.assertNotIn("performWindowDragWithEvent_", ui)
        self.assertIn("setMovableByWindowBackground_(True)", ui)
        self.assertIn("NSWindowCollectionBehaviorCanJoinAllSpaces", ui)
        self.assertIn("NSWindowCollectionBehaviorFullScreenAuxiliary", ui)
        self.assertIn("self.mini_panel.setLevel_(BAR_LEVEL)", ui)
        drag = _func(ui, "mouseDown_")
        self.assertIn("class MiniBarBackground", ui[:ui.index("def mouseDown_")])
        self.assertIn("drag_origin", drag)
        self.assertIn("setFrameOrigin_", drag)
        self.assertIn("NSEvent.mouseLocation()", drag)
        self.assertIn("CenteredFieldCell", ui)
        cell = _func(ui, "drawingRectForBounds_")
        self.assertIn("ascender", cell)
        self.assertIn("descender", cell)
        self.assertIn("setEditable_(True)", ui)
        self.assertIn("setSelectable_(True)", ui)
        moved = _func(ui, "windowDidMove_")
        self.assertIn("ORIGIN_KEY", moved)
        order = _func(ui, "_order_bar_front")
        self.assertIn("place_bar(saved, screens, size)", order)

    def test_double_click_on_the_background_recenters_on_the_main_screen(self):
        screens = (AIR, RIGHT, LEFT)
        home = place_bar(None, screens)
        self.assertEqual(reset_origin(screens), home)
        self.assertEqual(reset_origin(AIR), home)
        self.assertNotEqual(home, (1600.0, 200.0))
        self.assertEqual(reset_origin([]), (0.0, DOCK_GAP))
        frames = bar_controls()
        field, plus, mic = frames["field"], frames["plus"], frames["mic"]
        self.assertEqual(background_action(1, BAR_GRIP + 2.0, BAR_H / 2.0), "drag")
        self.assertEqual(background_action(2, BAR_GRIP + 2.0, BAR_H / 2.0), "reset")
        self.assertEqual(background_action(2, BAR_W / 2.0, BAR_GRIP + 2.0), "reset")
        self.assertEqual(background_action(2, BAR_W - BAR_GRIP - 2.0, BAR_H / 2.0), "reset")
        self.assertEqual(background_action(2, field[0] + 4, field[1] + 4), "control")
        self.assertEqual(background_action(1, field[0] + 4, field[1] + 4), "control")
        self.assertEqual(background_action(2, plus[0], plus[1]), "control")
        self.assertEqual(background_action(2, mic[0] + 1, mic[1] + 1), "control")

    def test_the_window_menu_resets_the_same_saved_position(self):
        ui = open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8").read()
        self.assertIn(
            'addItemWithTitle_action_keyEquivalent_("Reset Mini Bar Position", "resetMiniBarPosition:", "")',
            ui,
        )
        self.assertIn(
            'addItemWithTitle_action_keyEquivalent_("Reset Mini Bar Size", "resetMiniBarSize:", "")',
            ui,
        )
        reset = _func(ui, "resetMiniBarPosition_")
        self.assertIn("reset_origin", reset)
        self.assertIn("default_size", reset)
        self.assertIn("ORIGIN_KEY", reset)
        self.assertIn("SIZE_KEY", reset)
        self.assertIn("setFrame_display_", reset)
        size_reset = _func(ui, "resetMiniBarSize_")
        self.assertIn("default_size", size_reset)
        self.assertIn("SIZE_KEY", size_reset)
        self.assertNotIn("reset_origin", size_reset)
        self.assertIn("frame.origin", size_reset)
        drag = _func(ui, "mouseDown_")
        self.assertIn("background_action", drag)
        self.assertIn("resetMiniBarPosition_", drag)
        self.assertIn("resize_frame", drag)
        self.assertIn("setFrameOrigin_", drag)
        self.assertLess(drag.index("resetMiniBarPosition_"), drag.index("resize_frame"))
        self.assertLess(drag.index("resize_frame"), drag.index("drag_origin"))
        self.assertIn("return", drag[:drag.index("drag_origin")])
        resized = _func(ui, "windowDidResize_")
        self.assertIn("SIZE_KEY", resized)
        self.assertIn("_layout_mini_bar", resized)
        ordered = _func(ui, "_order_bar_front")
        self.assertIn("remembered_size", ordered)
        self.assertIn("SIZE_KEY", ordered)

    def test_settings_toggle_sits_under_the_microphone_row(self):
        for width, height in ((MIN_W, MIN_H), (DEFAULT_W, DEFAULT_H)):
            page = layout_window(width, height)["settings"]
            bounds = page["document"]
            rows = (page["name"], page["hint"], page["popup"], page["message"],
                    page["mini_name"], page["mini_hint"], page["mini_toggle"],
                    page["update_name"], page["update_hint"], page["update_button"])
            for rect in rows:
                self.assertTrue(rects_inside(rect, bounds), (width, rect))
            self.assertFalse(_overlaps(page["popup"], page["mini_toggle"]))
            self.assertFalse(_overlaps(page["message"], page["mini_name"]))
            self.assertFalse(_overlaps(page["mini_toggle"], page["update_name"]))
            self.assertFalse(_overlaps(page["update_hint"], page["update_button"]))
            # AppKit origin is the bottom, so a lower row has a smaller y.
            self.assertLess(page["mini_toggle"][1], page["popup"][1])
            self.assertLess(page["update_button"][1], page["mini_toggle"][1])


class TestSize(unittest.TestCase):
    def test_a_saved_size_is_clamped_and_a_missing_one_is_the_default(self):
        self.assertEqual(default_size(), (BAR_W, BAR_H))
        self.assertEqual(remembered_size(None), default_size())
        self.assertEqual(remembered_size(""), default_size())
        self.assertEqual(remembered_size("nope"), default_size())
        self.assertEqual(remembered_size("420"), default_size())
        self.assertEqual(parse_size("10 10"), (BAR_MIN_W, BAR_MIN_H))
        self.assertEqual(remembered_size("10 10"), (BAR_MIN_W, BAR_MIN_H))
        self.assertEqual(remembered_size("9999 9999"), (BAR_MAX_W, BAR_MAX_H))
        self.assertEqual(parse_size("-40 50"), (BAR_MIN_W, 50.0))
        self.assertEqual(remembered_size(format_size(500, 50)), (500.0, 50.0))
        self.assertEqual(format_size(10, 10), format_size(BAR_MIN_W, BAR_MIN_H))
        self.assertEqual(SIZE_KEY, "mini_bar_size")

    def test_reset_restores_the_default_size(self):
        widened = remembered_size("600 60")
        self.assertNotEqual(widened, default_size())
        self.assertEqual(default_size(), (BAR_W, BAR_H))
        self.assertEqual(remembered_size(format_size(*default_size())), default_size())
        ui = open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8").read()
        position = _func(ui, "resetMiniBarPosition_")
        size_only = _func(ui, "resetMiniBarSize_")
        self.assertIn("default_size()", position)
        self.assertIn("default_size()", size_only)
        drag = _func(ui, "mouseDown_")
        self.assertIn("resetMiniBarPosition_", drag)

    def test_edges_and_corners_resize_and_the_field_does_not(self):
        self.assertEqual(resize_edges(1.0, BAR_H / 2.0), frozenset({"left"}))
        self.assertEqual(resize_edges(BAR_W - 1.0, BAR_H / 2.0), frozenset({"right"}))
        self.assertEqual(resize_edges(BAR_W / 2.0, 1.0), frozenset({"bottom"}))
        self.assertEqual(resize_edges(BAR_W / 2.0, BAR_H - 1.0), frozenset({"top"}))
        self.assertEqual(resize_edges(1.0, 1.0), frozenset({"left", "bottom"}))
        self.assertEqual(resize_edges(BAR_W - 1.0, BAR_H - 1.0), frozenset({"right", "top"}))
        self.assertEqual(resize_edges(BAR_GRIP + 2.0, BAR_H / 2.0), frozenset())
        wide = (BAR_MAX_W, BAR_MAX_H)
        field = bar_controls(wide)["field"]
        self.assertEqual(background_action(1, field[0] + 4.0, field[1] + 4.0, None, wide), "control")
        self.assertEqual(background_action(2, 1.0, wide[1] / 2.0, None, wide), "resize")
        self.assertEqual(background_action(1, BAR_GRIP + 2.0, wide[1] / 2.0, None, wide), "drag")

    def test_a_resize_keeps_the_opposite_edge_and_clamps(self):
        frame = (100.0, 200.0, BAR_W, BAR_H)
        right = resize_frame(frame, {"right"}, (0.0, 0.0), (50.0, 0.0))
        self.assertEqual(right, (100.0, 200.0, BAR_W + 50.0, BAR_H))
        left = resize_frame(frame, {"left"}, (0.0, 0.0), (-40.0, 0.0))
        self.assertEqual(left, (60.0, 200.0, BAR_W + 40.0, BAR_H))
        self.assertEqual(left[0] + left[2], frame[0] + frame[2])
        huge = resize_frame(frame, {"right"}, (0.0, 0.0), (5000.0, 0.0))
        self.assertEqual(huge, (100.0, 200.0, BAR_MAX_W, BAR_H))
        shrunk = resize_frame(frame, {"left"}, (0.0, 0.0), (400.0, 0.0))
        self.assertEqual(shrunk[2], BAR_MIN_W)
        self.assertEqual(shrunk[0] + shrunk[2], frame[0] + frame[2])
        taller = resize_frame(frame, {"top"}, (0.0, 0.0), (0.0, 30.0))
        self.assertEqual(taller, (100.0, 200.0, BAR_W, BAR_MAX_H))
        lower = resize_frame(frame, {"bottom"}, (0.0, 0.0), (0.0, -10.0))
        self.assertEqual(lower, (100.0, 190.0, BAR_W, BAR_H + 10.0))
        self.assertEqual(lower[1] + lower[3], frame[1] + frame[3])
        corner = resize_frame(frame, {"left", "bottom"}, (0.0, 0.0), (-20.0, -8.0))
        self.assertEqual(corner, (80.0, 192.0, BAR_W + 20.0, BAR_H + 8.0))

    def test_type_follows_height_and_width_goes_to_the_field(self):
        base = bar_metrics(BAR_W, BAR_H)
        self.assertEqual(base["field_font"], 14.0)
        self.assertEqual(base["plus_font"], 20.0)
        self.assertEqual(base["button"], 24.0)
        self.assertEqual(bar_metrics(BAR_MAX_W, BAR_H)["field_font"], base["field_font"])
        self.assertGreater(bar_metrics(BAR_W, BAR_MAX_H)["field_font"], base["field_font"])
        self.assertGreater(bar_metrics(BAR_W, BAR_MIN_H)["button"], 0.0)
        self.assertLess(bar_metrics(BAR_W, BAR_MIN_H)["field_font"], base["field_font"])
        self.assertGreater(bar_controls((BAR_MAX_W, BAR_H))["field"][2], bar_controls()["field"][2])

    def test_controls_stay_inside_the_grip_at_the_min_and_the_max(self):
        for size in ((BAR_MIN_W, BAR_MIN_H), (BAR_W, BAR_H), (BAR_MAX_W, BAR_MAX_H), (500.0, 50.0)):
            frames = list(bar_controls(size).values())
            bounds = (0.0, 0.0, size[0], size[1])
            self.assertGreaterEqual(bar_controls(size)["field"][2], 120.0)
            for rect in frames:
                self.assertTrue(rects_inside(rect, bounds), (size, rect))
                self.assertGreaterEqual(rect[0], BAR_GRIP)
                self.assertGreaterEqual(rect[1], BAR_GRIP)
                self.assertLessEqual(rect[0] + rect[2], size[0] - BAR_GRIP)
                self.assertLessEqual(rect[1] + rect[3], size[1] - BAR_GRIP)
            for i, rect in enumerate(frames):
                for other in frames[i + 1:]:
                    self.assertFalse(_overlaps(rect, other))

    def test_a_wide_pill_uses_its_own_width_when_deciding_it_is_on_screen(self):
        wide = (BAR_MAX_W, BAR_H)
        fallback = place_bar(None, AIR, wide)
        self.assertAlmostEqual(fallback[0], AIR[0] + (AIR[2] - BAR_MAX_W) / 2.0)
        self.assertEqual(fallback[1], AIR[1] + DOCK_GAP)
        self.assertEqual(place_bar((120.0, 400.0), AIR, wide), (120.0, 400.0))
        self.assertEqual(place_bar((AIR[2] - 100.0, 400.0), AIR, wide), fallback)
        self.assertEqual(place_bar((100.0, 200.0), AIR, (10.0, 10.0)), (100.0, 200.0))


# Phrases the + menu types, and the local command each one already routes to.
_MENU_ROUTES = {
    "brief": "info_brief",
    "next_shift": "info_next_shift",
    "leave": "info_leave",
    "payday": "info_payday_check",
    "blue_pill": "matrix_on",
    "red_pill": "matrix_off",
    "silence": "notify_off",
    "volume_30": "volume_set",
    "volume_50": "volume_set",
    "volume_100": "volume_set",
    "mute": "volume_mute",
    "brightness_40": "brightness_set",
    "brightness_70": "brightness_set",
    "brightness_100": "brightness_set",
}
_MENU_ACTIONS = {
    "window": "window",
    "updates": "updates",
    "reset_position": "reset_position",
    "reset_size": "reset_size",
    "settings": "settings",
}
_CAPTURE_MENU_IDS = (
    "screenshot_full",
    "screenshot_area",
    "screenshot_window",
    "record_start",
    "share_notes",
    "share_email",
    "share_imessage",
    "share_finder",
    "share_copy",
    "share_delete",
    "ask_capture_chatgpt",
    "ask_capture_claude",
    "ask_capture_gemini",
    "ask_capture_siri",
    "ask_capture_google",
    "ask_question_chatgpt",
    "ask_question_claude",
    "ask_question_gemini",
    "ask_question_siri",
    "ask_question_google",
)


class TestGlass(unittest.TestCase):
    def test_glass_vibrancy_and_reduce_transparency(self):
        glass = pill_chrome(True, False)
        self.assertEqual(glass["material"], "glass")
        self.assertTrue(glass["highlight"])
        self.assertTrue(glass["motion"])
        self.assertFalse(glass["contrast_border"])
        missing = pill_chrome(False, False, increase_contrast=True)
        self.assertEqual(missing["material"], "vibrancy")
        self.assertTrue(missing["contrast_border"])
        self.assertTrue(missing["motion"])
        solid = pill_chrome(True, True, increase_contrast=True, reduce_motion=True)
        self.assertEqual(solid["material"], "solid")
        self.assertTrue(solid["contrast_border"])
        self.assertFalse(solid["motion"])
        self.assertEqual(pill_chrome(False, True)["material"], "solid")

    def test_trailing_symbol_follows_listen_text_and_reply(self):
        self.assertEqual(trailing_symbol(True, "open Spotify"), "waveform")
        self.assertEqual(trailing_symbol(False, "  open   Spotify  "), "arrow.up.circle.fill")
        self.assertEqual(trailing_symbol(False, "   "), "mic.fill")
        self.assertEqual(trailing_symbol(False, "", ""), "mic.fill")
        self.assertEqual(trailing_symbol(False, "It's 3:45.", "It's 3:45."), "mic.fill")
        self.assertEqual(trailing_symbol(True, "It's 3:45.", "It's 3:45."), "waveform")

    def test_plus_menu_routes_to_commands_that_already_exist(self):
        self.assertFalse(attachments_supported())
        items = walk_menu()
        ids = [item["id"] for item in items]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIsNone(plus_item("attach"))
        attached = plus_menu(can_attach=True)
        self.assertEqual(plus_item("attach", attached)["kind"], "attach")
        self.assertEqual(plus_item("attach", attached)["title"], "Attach File\u2026")
        routed = {}
        for item in items:
            self.assertTrue(item["symbol"])
            phrase = item.get("phrase") or ""
            self.assertNotIn("my love", phrase.lower())
            self.assertNotIn("transfer", phrase.lower())
            self.assertNotIn("send money", phrase.lower())
            if item["id"] == "window":
                self.assertEqual(item["key"], "1")
            else:
                self.assertEqual(item["key"], "")
            if item["kind"] == "text":
                key = commands.route_before_api(phrase)
                self.assertEqual(key, _MENU_ROUTES[item["id"]], phrase)
                self.assertNotEqual(key, "info_messages")
                if key in ("matrix_on", "matrix_off", "notify_off", "volume_set", "volume_mute", "brightness_set"):
                    self.assertNotIn(key, commands.BRIDGE_ALLOW)
                routed[item["id"]] = key
            else:
                if item["id"] in _MENU_ACTIONS:
                    self.assertEqual(item["kind"], _MENU_ACTIONS[item["id"]])
                else:
                    self.assertEqual(item["kind"], item["id"])
                self.assertEqual(phrase, "")
        self.assertEqual(set(routed), set(_MENU_ROUTES))
        self.assertEqual(plus_item("payday")["phrase"], "payday check")
        self.assertNotIn("info_messages", [item["id"] for item in items])
        for item_id in _CAPTURE_MENU_IDS:
            self.assertEqual(plus_item(item_id)["kind"], item_id)
        recording = [item["id"] for item in walk_menu(plus_menu(recording=True))]
        self.assertIn("record_stop", recording)
        self.assertNotIn("record_start", recording)
        self.assertIsNone(plus_item("screenshot"))

    def test_the_pill_source_uses_glass_or_the_hud_fallback(self):
        ui = open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8").read()
        flags = _func(ui, "_pill_flags")
        self.assertIn('lookUpClass("NSGlassEffectView")', flags)
        self.assertIn("pill_chrome(", flags)
        self.assertIn("accessibilityDisplayShouldReduceTransparency", flags)
        self.assertIn("accessibilityDisplayShouldIncreaseContrast", flags)
        self.assertIn("accessibilityDisplayShouldReduceMotion", flags)
        backing = _func(ui, "_make_backing")
        self.assertIn('material == "solid"', backing)
        self.assertIn('material == "glass"', backing)
        self.assertIn("vibrancy", backing)
        vibrancy = _func(ui, "_make_vibrancy_backing")
        self.assertIn("NSVisualEffectMaterialHUDWindow", vibrancy)
        self.assertIn("NSVisualEffectBlendingModeBehindWindow", vibrancy)
        self.assertIn("NSVisualEffectStateActive", vibrancy)
        fade = _func(ui, "_fade_bar")
        self.assertIn("CASpringAnimation", fade)
        self.assertIn("setDamping_", fade)
        self.assertIn("setStiffness_", fade)
        self.assertIn("NSAnimationContext", fade)
        hide = _func(ui, "_hide_bar")
        self.assertIn("motion", hide)
        self.assertIn("orderOut_", hide)
        self.assertIn("secondaryLabelColor", _func(ui, "_style_pill_field"))
        self.assertIn("labelColor", _func(ui, "_style_pill_field"))
        refresh = _func(ui, "_refresh_trailing_symbol")
        self.assertIn("trailing_symbol(", refresh)
        self.assertIn('"arrow.up.circle.fill"', refresh)
        self.assertIn('"waveform"', open(os.path.join(ROOT, "mini_bar.py"), encoding="utf-8").read())
        self.assertIn('"mic.fill"', ui)
        menu = _func(ui, "miniPlusItem_")
        self.assertIn("_queue_bar_phrase", menu)
        self.assertIn("_capture_for_bar", menu)
        self.assertIn("showMain_", menu)
        self.assertIn('_select_tab("settings")', menu)
        self.assertIn("checkForUpdates_", menu)
        self.assertIn("resetMiniBarPosition_", menu)
        self.assertIn("resetMiniBarSize_", menu)
        self.assertIn('("text", phrase)', _func(ui, "_queue_bar_phrase"))
        self.assertIn("take_screenshot", _func(ui, "_capture_for_bar"))
        self.assertIn("run_capture_menu", _func(ui, "_run_capture_kind"))
        self.assertIn("showCaptureResult_", ui)
        self.assertIn("stop.circle.fill", ui)
        self.assertIn("systemRedColor", ui)
        self.assertIn("capture_follow_up_items", ui)
        self.assertNotIn("NSOpenPanel", ui)
        self.assertIn('setCornerCurve_("continuous")', ui)
        self.assertIn("plus_menu(recording=", ui)
