"""Mini command bar. No AppKit, so this runs in CI."""
import os
import unittest

import commands
from assistant_layout import DEFAULT_H, DEFAULT_W, MIN_H, MIN_W, layout_window, rects_inside
from mini_bar import (
    BAR_COLLECTION,
    BAR_H,
    BAR_W,
    CAN_JOIN_ALL_SPACES,
    DOCK_GAP,
    FULL_SCREEN_AUXILIARY,
    PLACEHOLDER,
    REPLY_SECONDS,
    BarController,
    bar_controls,
    drag_origin,
    enabled_from_pref,
    format_origin,
    hit_control,
    mic_event,
    parse_origin,
    place_bar,
    reply_text,
    submission,
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
        self.assertIn('buttonWithTitle_target_action_("+", self, "showMain:")', ui)

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
        self.assertIn("place_bar(saved, screens)", order)

    def test_settings_toggle_sits_under_the_microphone_row(self):
        for width, height in ((MIN_W, MIN_H), (DEFAULT_W, DEFAULT_H)):
            page = layout_window(width, height)["settings"]
            bounds = page["document"]
            rows = (page["name"], page["hint"], page["popup"], page["message"],
                    page["mini_name"], page["mini_hint"], page["mini_toggle"])
            for rect in rows:
                self.assertTrue(rects_inside(rect, bounds), (width, rect))
            self.assertFalse(_overlaps(page["popup"], page["mini_toggle"]))
            self.assertFalse(_overlaps(page["message"], page["mini_name"]))
            # AppKit origin is the bottom, so a lower row has a smaller y.
            self.assertLess(page["mini_toggle"][1], page["popup"][1])
