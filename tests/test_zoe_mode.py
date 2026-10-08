"""Zoe mode: kid-safe allowlist, a two-step exit, and a flag that survives a relaunch."""
import os
import tempfile
import unittest
from unittest import mock

import commands
import commands.zoe_mode as zoe
from mini_bar import plus_item, plus_menu

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ENTER_PHRASES = (
    "zoe mode",
    "kid mode",
    "kid mode on",
    "turn on zoe mode",
    "turn on kid mode",
    "start zoe mode",
    "enter zoe mode",
    "zoe mode on",
    "please zoe mode",
    "zoe mode please",
)
EXIT_PHRASES = (
    "exit zoe mode",
    "leave zoe mode",
    "turn off zoe mode",
    "turn off kid mode",
    "kid mode off",
    "stop zoe mode",
    "end zoe mode",
    "leave kid mode",
    "stop kid mode",
    "please exit zoe mode",
)
JOKE_PHRASES = (
    "joke",
    "tell a joke",
    "tell me a joke",
    "tell zoe a joke",
    "fun fact",
    "a fun fact",
    "tell me a fun fact",
)
ALLOWED = (
    ("what time is it", "info_time"),
    ("what's the date", "info_date"),
    ("what's the weather", "info_weather"),
    ("weather", "info_weather"),
    ("start a 5 minute timer for Zoe", "zoe_timer"),
    ("open Princess Academy", "zoe_academy"),
    ("play", "media_play"),
    ("pause", "media_pause"),
    ("what's Zoe got tomorrow", "info_zoe"),
)
# One spoken line for each blocked category, plus the action key it already routes to.
BLOCKED_PHRASES = (
    ("quit_close_hide", "quit Safari", "app_quit"),
    ("quit_close_hide", "close Notes", "app_quit"),
    ("quit_close_hide", "hide Safari", "app_hide"),
    ("quit_close_hide", "focus Safari", "app_focus"),
    ("quit_close_hide", "open Safari", "app_open"),
    ("quit_close_hide", "quit all the apps", None),
    ("messages", "check my messages from My Love", "info_messages"),
    ("money", "when's rent due", "info_rent"),
    ("money", "what bills are coming up", "info_bills"),
    ("money", "how long until payday", "info_payday"),
    ("money", "payday check", "info_payday_check"),
    ("money", "what's due today", "info_payday_check"),
    ("money", "move $600 to Zoe", None),
    ("email", "email it", "capture_email"),
    ("captures", "take a screenshot", "screenshot"),
    ("captures", "start screen recording", "record_start"),
    ("captures", "delete the screenshot", "capture_delete"),
    ("captures", "text it", "capture_imessage"),
    ("captures", "save it to notes", "capture_note"),
    ("shortcuts", "run shortcut Leaving for work", "shortcut_run"),
    ("shortcuts", "start focus mode", "focus_on"),
    ("shell", "execute a shell command", None),
    ("system", "volume to 100", "volume_set"),
    ("system", "brightness to 50", "brightness_set"),
    ("system", "mute", "volume_mute"),
    ("system", "lock the screen", "system_lock"),
    ("system", "empty the trash", "empty_trash"),
    ("system", "silence notifications", "notify_off"),
    ("system", "turn on voiceover", "voiceover_on"),
    ("llm", "why is the sky blue", None),
    ("reminders", "remind me to buy milk", "remind_add"),
    ("reminders", "remind me to submit my timesheet", "ihss_remind"),
    ("leave", "turn on leave reminders", "leave_reminders_on"),
    ("leave", "turn off leave reminders", "leave_reminders_off"),
    ("leave", "when should I leave for work", "info_leave"),
    ("brief", "play my brief", "brief_play"),
    ("brief", "stop", "brief_stop"),
    ("brief", "brief me", "info_brief"),
    ("video", "convert the recording to mp4", "video_mp4"),
    ("video", "trim the recording from 0:05 to 0:30", "video_trim"),
    ("video", "compress the recording", "video_compress"),
    ("video", "extract the audio from the recording", "video_audio"),
    ("video", "choose a video", "video_choose"),
)


class TestZoeMode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "zoe-mode.txt")
        commands.set_zoe_mode_path(self.path)
        self.addCleanup(commands.clear_confirmation)
        self.addCleanup(commands.clear_zoe_exit)
        self.addCleanup(commands.set_zoe_mode_path, None)

    def _refuse(self, phrase):
        guard = commands.zoe_guard(phrase)
        self.assertIsNotNone(guard, phrase)
        self.assertEqual(guard["kind"], "speak", phrase)
        self.assertNotIn("action", guard)
        self.assertIn("grown-up", guard["line"].lower(), phrase)
        self.assertTrue(commands.zoe_mode_active(), phrase)
        return guard

    def test_routes_enter_exit_and_jokes_without_stealing_old_phrases(self):
        for phrase in ENTER_PHRASES:
            self.assertEqual(commands.route_before_api(phrase), "zoe_mode_on", phrase)
        for phrase in EXIT_PHRASES:
            self.assertEqual(commands.route_before_api(phrase), "zoe_mode_off", phrase)
        for phrase in JOKE_PHRASES:
            self.assertEqual(commands.route_before_api(phrase), "zoe_joke", phrase)
        self.assertEqual(commands.route_before_api("what's Zoe got tomorrow"), "info_zoe")
        self.assertEqual(commands.route_before_api("open Princess Academy"), "zoe_academy")
        self.assertEqual(commands.route_before_api("start a 5 minute timer for Zoe"), "zoe_timer")
        self.assertEqual(commands.route_before_api("play"), "media_play")
        self.assertEqual(commands.route_before_api("pause the music"), "media_pause")
        self.assertEqual(commands.route_before_api("remind me to buy milk"), "remind_add")
        self.assertEqual(commands.route_before_api("remind me to submit my timesheet"), "ihss_remind")
        self.assertEqual(commands.route_before_api("turn on leave reminders"), "leave_reminders_on")
        self.assertEqual(commands.route_before_api("turn off leave reminders"), "leave_reminders_off")
        self.assertEqual(commands.route_before_api("play my brief"), "brief_play")
        self.assertEqual(commands.route_before_api("stop"), "brief_stop")
        self.assertEqual(commands.route_before_api("stop recording"), "record_stop")
        self.assertEqual(commands.route_before_api("stop zoe mode"), "zoe_mode_off")
        self.assertEqual(commands.route_before_api("stop kid mode"), "zoe_mode_off")
        self.assertEqual(commands.route_before_api("convert the recording to mp4"), "video_mp4")
        self.assertEqual(commands.route_before_api("trim the recording from 0:05 to 0:30"), "video_trim")
        self.assertEqual(commands.route_before_api("compress the recording"), "video_compress")
        self.assertEqual(commands.route_before_api("extract the audio from the recording"), "video_audio")
        self.assertEqual(commands.route_before_api("choose a video"), "video_choose")
        self.assertEqual(commands.route_before_api("blue pill"), "matrix_on")
        self.assertEqual(commands.route_before_api("red pill"), "matrix_off")
        self.assertEqual(commands.route_before_api("what time is it"), "info_time")
        self.assertIsNone(commands.route_before_api("grown ups only"))
        self.assertIsNone(commands.route_before_api("yes"))
        self.assertIsNone(commands.route_before_api("tell me a joke about the rent"))

    def test_new_keys_stay_off_the_bridge_allowlist(self):
        for key in ("zoe_mode_on", "zoe_mode_off", "zoe_joke"):
            self.assertNotIn(key, commands.BRIDGE_ALLOW, key)
            self.assertIn(key, commands.ZOE_ALLOW, key)
        self.assertEqual(len(commands.BRIDGE_ALLOW), 30)
        self.assertIsNone(commands.bridge_allowed("zoe mode"))
        self.assertIsNone(commands.bridge_allowed("exit zoe mode"))
        self.assertIsNone(commands.bridge_allowed("tell me a joke"))

    def test_adult_commands_are_unchanged_while_the_mode_is_off(self):
        self.assertFalse(commands.zoe_mode_active())
        self.assertIsNone(commands.zoe_guard("what time is it"))
        self.assertIsNone(commands.zoe_guard("payday check"))
        self.assertIsNone(commands.zoe_guard("quit Safari"))
        self.assertIsNone(commands.zoe_guard("why is the sky blue"))
        self.assertIsNone(commands.zoe_guard("remind me to buy milk"))
        self.assertIsNone(commands.zoe_guard("turn on leave reminders"))
        self.assertIsNone(commands.zoe_guard("play my brief"))
        self.assertIsNone(commands.zoe_guard("stop"))
        self.assertIsNone(commands.zoe_guard("convert the recording to mp4"))
        entered = commands.zoe_guard("zoe mode")
        self.assertEqual(entered["kind"], "speak")
        self.assertIn("Zoe mode is on", entered["line"])
        self.assertTrue(commands.zoe_mode_active())
        self.assertEqual(open(self.path, encoding="utf-8").read(), "on\n")

    def test_allowlist_runs_and_every_blocked_category_is_refused(self):
        commands.enter_zoe_mode()
        seen = set()
        for phrase, key in ALLOWED:
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertTrue(commands.zoe_allows(key), key)
            guard = commands.zoe_guard(phrase)
            self.assertEqual(guard, {"kind": "run", "action": key}, phrase)
            seen.add(key)
        self.assertEqual(seen, {
            "info_time", "info_date", "info_weather", "zoe_timer",
            "zoe_academy", "media_play", "media_pause", "info_zoe",
        })
        joke = commands.zoe_guard("tell me a joke")
        self.assertEqual(joke["kind"], "speak")
        self.assertIn(joke["line"], commands.JOKES)
        categories = set()
        for category, phrase, key in BLOCKED_PHRASES:
            categories.add(category)
            if key is None:
                self.assertNotEqual(commands.route_before_api(phrase), "zoe_joke", phrase)
            else:
                self.assertEqual(commands.route_before_api(phrase), key, phrase)
                self.assertIn(key, commands.ZOE_BLOCKED[category], key)
                self.assertNotIn(key, commands.ZOE_ALLOW, key)
                self.assertFalse(commands.zoe_allows(key), key)
            self._refuse(phrase)
        self.assertEqual(categories, set(commands.ZOE_BLOCKED))
        for category, keys in commands.ZOE_BLOCKED.items():
            for key in keys:
                self.assertNotIn(key, commands.ZOE_ALLOW, (category, key))
                self.assertFalse(commands.zoe_allows(key), key)
        self.assertIn("app_minimise", commands.ZOE_BLOCKED["quit_close_hide"])
        self.assertFalse(commands.zoe_allows("app_minimise"))
        self._refuse("play and pause")
        self._refuse("play and open Safari")

    def test_exit_needs_the_adult_phrase_and_yes_does_not_leave(self):
        commands.enter_zoe_mode()
        asked = commands.zoe_guard("exit zoe mode")
        self.assertIn("grown ups only", asked["line"].lower())
        self.assertTrue(commands.zoe_mode_active())
        self.assertTrue(commands.zoe_exit_pending())
        self.assertEqual(open(self.path, encoding="utf-8").read(), "on\n")
        yes = commands.zoe_guard("yes")
        self.assertTrue(commands.zoe_mode_active())
        self.assertIn("grown-up", yes["line"].lower())
        self.assertFalse(commands.zoe_exit_pending())
        commands.zoe_guard("kid mode off")
        stayed = commands.zoe_guard("no")
        self.assertIn("stays on", stayed["line"].lower())
        self.assertTrue(commands.zoe_mode_active())
        commands.zoe_guard("leave zoe mode")
        left = commands.zoe_guard("grown ups only")
        self.assertIn("Zoe mode is off", left["line"])
        self.assertFalse(commands.zoe_mode_active())
        self.assertFalse(os.path.exists(self.path))
        commands.enter_zoe_mode()
        commands.zoe_guard("stop zoe mode")
        stayed_stop = commands.zoe_guard("stop")
        self.assertIn("stays on", stayed_stop["line"].lower())
        self.assertTrue(commands.zoe_mode_active())
        self.assertFalse(commands.zoe_exit_pending())
        self._refuse("stop")
        for phrase in ("grown-ups only", "GROWNUPS ONLY"):
            commands.enter_zoe_mode()
            commands.zoe_guard("exit zoe mode")
            commands.zoe_guard(phrase)
            self.assertFalse(commands.zoe_mode_active(), phrase)
        stray = commands.zoe_guard("grown ups only")
        self.assertIsNone(stray)
        self.assertFalse(commands.zoe_mode_active())

    def test_an_expired_exit_prompt_does_not_leave(self):
        commands.enter_zoe_mode()
        clock = {"now": 1_000.0}

        def fake_time():
            return clock["now"]

        with mock.patch.object(zoe.time, "time", side_effect=fake_time):
            commands.zoe_guard("exit zoe mode")
            self.assertTrue(commands.zoe_exit_pending())
            clock["now"] = 1_000.0 + commands.ZOE_EXIT_SECONDS + 1
            late = commands.zoe_guard("grown ups only")
        self.assertTrue(commands.zoe_mode_active())
        self.assertIn("grown-up", late["line"].lower())
        self.assertFalse(commands.zoe_exit_pending())

    def test_the_flag_is_read_from_disk_so_a_relaunch_keeps_it(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("on\n")
        self.assertTrue(commands.zoe_mode_active())
        self.assertTrue(commands.zoe_claims("what time is it"))
        os.remove(self.path)
        self.assertFalse(commands.zoe_mode_active())
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("hello\n")
        self.assertFalse(commands.zoe_mode_active())
        commands.enter_zoe_mode()
        commands.clear_zoe_exit()
        self.assertTrue(commands.zoe_mode_active())
        self.assertEqual(commands.ZOE_MODE_PATH, os.path.expanduser(
            "~/Library/Application Support/Hey Jev/zoe-mode.txt"
        ))

    def test_the_menu_enters_immediately_and_leaves_only_after_confirm(self):
        off = commands.menu_toggle_plan(False)
        self.assertEqual(off["action"], "enter")
        self.assertFalse(off["checked"])
        self.assertFalse(commands.zoe_mode_active())
        on = commands.menu_toggle_plan(True)
        self.assertEqual(on["action"], "confirm_exit")
        self.assertEqual(on["cancel"], "Keep Zoe Mode")
        self.assertEqual(on["confirm"], "Turn Off Zoe Mode")
        self.assertTrue(on["checked"])
        commands.enter_zoe_mode()
        self.assertEqual(commands.menu_toggle_plan()["action"], "confirm_exit")
        commands.zoe_guard("exit zoe mode")
        self.assertTrue(commands.zoe_exit_pending())
        line = commands.leave_zoe_mode()
        self.assertIn("off", line.lower())
        self.assertFalse(commands.zoe_mode_active())
        self.assertFalse(commands.zoe_exit_pending())

    def test_the_pill_and_plus_menu_show_the_mode(self):
        self.assertEqual(commands.zoe_pill_label(False), "")
        self.assertEqual(commands.zoe_pill_label(True), "Zoe")
        idle = plus_item("zoe_mode")
        self.assertEqual(idle["kind"], "zoe_mode")
        self.assertEqual(idle["title"], "Zoe Mode")
        self.assertFalse(idle.get("checked"))
        self.assertEqual(idle["phrase"], "")
        active = plus_item("zoe_mode", plus_menu(zoe_mode=True))
        self.assertTrue(active["checked"])
        self.assertIn("Turn Off Zoe Mode", active["title"])
        ui = open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8").read()
        self.assertIn("zoeModeMenu:", ui)
        self.assertIn("Keep Zoe Mode", ui)
        self.assertIn("Turn Off Zoe Mode", ui)
        self.assertIn("zoe_label", ui)
        self.assertIn("plus_menu(recording=recording, zoe_mode=zoe_on)", ui)
        siri = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        start = siri.index("def handle(")
        end = siri.index("\ndef ", start + 10)
        body = siri[start:end]
        self.assertLess(body.index("zoe_claims"), body.index("confirmation_status"))
        self.assertLess(body.index("zoe_guard"), body.index("jev("))
        self.assertIn("_run_zoe_allowed", siri)
        runner = siri.split("def _run_zoe_allowed", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("zoe_allows", runner)
        source = open(os.path.join(ROOT, "commands", "zoe_mode.py"), encoding="utf-8").read()
        for banned in ("requests", "urllib", "socket", "openrouter", "subprocess"):
            self.assertNotIn(banned, source)

    def test_replies_use_the_cheerful_voice_and_jokes_stay_local(self):
        self.assertTrue(commands.zoe_friendly("[sighing] Closing Mail.", "app_quit").startswith("[cheerful] "))
        self.assertNotIn("sighing", commands.zoe_friendly("[sighing] Closing Mail."))
        self.assertEqual(
            commands.zoe_friendly("Playing.", "media_play"),
            "[cheerful] The music is playing.",
        )
        self.assertEqual(
            commands.zoe_friendly("Paused.", "media_pause"),
            "[cheerful] The music is paused.",
        )
        first = commands.tell_zoe_joke()
        second = commands.tell_zoe_joke()
        self.assertIn(first, commands.JOKES)
        self.assertIn(second, commands.JOKES)
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("[cheerful] "))

    def test_a_phone_allowlisted_command_cannot_bypass_the_mode(self):
        commands.enter_zoe_mode()
        self.assertIn("info_payday_check", commands.BRIDGE_ALLOW)
        self.assertEqual(commands.bridge_allowed("payday check"), "info_payday_check")
        self.assertEqual(commands.bridge_allowed("what time is it"), "info_time")
        self._refuse("payday check")
        self._refuse("check my messages from My Love")
        self._refuse("brief me")
        guard = commands.zoe_guard("what time is it")
        self.assertEqual(guard["action"], "info_time")
        self.assertIsNone(commands.bridge_allowed("exit zoe mode"))
        self.assertIsNone(commands.bridge_allowed("kid mode off"))


if __name__ == "__main__":
    unittest.main()
