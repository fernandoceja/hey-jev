"""PR 8c: Start my day. Phrase matching, the bridge and Zoe staying unchanged, and the chip and Today row. Headless."""
import os
import unittest

import commands
import mini_bar
import full_window as fw
from commands.start_my_day import START_MY_DAY_KEY, start_my_day_action

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PhraseTests(unittest.TestCase):
    def test_the_aliases_resolve_to_the_brief_action(self):
        self.assertEqual(START_MY_DAY_KEY, "info_brief")
        for phrase in ("start my day", "start my morning", "morning brief", "morning briefing", "the morning brief"):
            self.assertEqual(start_my_day_action(phrase), "info_brief", phrase)

    def test_case_spacing_and_punctuation_do_not_matter(self):
        for phrase in ("Start my day", "START MY DAY", "  start   my   day  ", "start my day!", "Start my day.",
                       "Morning Brief?", "start my day please", "please start my day", "hey jev, start my day",
                       "Hey Jev start my day"):
            self.assertEqual(start_my_day_action(phrase), "info_brief", repr(phrase))

    def test_other_sentences_are_not_aliases(self):
        for phrase in ("start my car", "start my day tomorrow", "play my morning brief", "plan my day",
                       "what's my day", "brief me", "start", "", "   ", "start my day and open mail"):
            self.assertIsNone(start_my_day_action(phrase), repr(phrase))

    def test_non_text_input_is_not_an_alias(self):
        for value in (None, 7, b"start my day", ["start my day"]):
            self.assertIsNone(start_my_day_action(value), repr(value))

    def test_play_my_morning_brief_keeps_its_own_route(self):
        self.assertEqual(commands.route_before_api("play my morning brief"), "brief_play")
        self.assertIsNone(start_my_day_action("play my morning brief"))


class BridgeAndZoeTests(unittest.TestCase):
    def test_the_aliases_are_not_in_the_bridge_router(self):
        """route_before_api feeds the iPhone bridge. The aliases must not reach it, so the phone gains no phrase."""
        for phrase in ("start my day", "start my morning", "morning brief", "Start my day!"):
            self.assertIsNone(commands.route_before_api(phrase), phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)

    def test_brief_me_still_routes_as_before(self):
        self.assertEqual(commands.route_before_api("brief me"), "info_brief")
        self.assertEqual(commands.bridge_allowed("brief me"), "info_brief")

    def test_the_brief_action_is_unchanged_for_zoe_and_the_bridge(self):
        import commands.zoe_mode  # noqa: F401  (Zoe still loads with the same brief group)
        self.assertIn("info_brief", commands.BRIDGE_ALLOW)
        self.assertNotIn("brief_play", commands.BRIDGE_ALLOW)
        self.assertNotIn("brief_stop", commands.BRIDGE_ALLOW)


class ChipAndTodayTests(unittest.TestCase):
    def test_the_popover_chip_is_start_my_day_and_replaces_plan_my_day(self):
        chip = mini_bar.POPOVER_CHIPS["start_day"]
        self.assertEqual(chip["title"], "Start my day")
        self.assertEqual(chip["phrase"], "start my day")
        first_page = mini_bar.POPOVER_CHIP_PAGES[0]
        self.assertIn("start_day", first_page)
        self.assertNotIn("plan_day", first_page)

    def test_the_full_window_today_section_has_start_my_day(self):
        today = dict((name, rows) for name, rows in fw.CATEGORIES)["Today"]
        self.assertEqual(today[0], ("start_day", "Start my day", "start my day"))

    def test_plan_my_day_is_still_on_the_full_window_get_started_list(self):
        self.assertIn(("plan", "Plan my day", "brief me"), fw.GET_STARTED)


if __name__ == "__main__":
    unittest.main()


class HookWiringTests(unittest.TestCase):
    def test_the_alias_is_checked_only_after_the_routes_on_the_mac_path(self):
        import ast as _ast
        with open(os.path.join(ROOT, "siri.py"), encoding="utf-8") as handle:
            source = handle.read()
        decide = next(n for n in _ast.walk(_ast.parse(source))
                      if isinstance(n, _ast.FunctionDef) and n.name == "decide")
        text = _ast.get_source_segment(source, decide)
        self.assertLess(text.index("route_before_api(text)"), text.index("start_my_day_action(text)"))

    def test_the_bridge_module_does_not_call_the_alias(self):
        with open(os.path.join(ROOT, "commands", "bridge.py"), encoding="utf-8") as handle:
            self.assertNotIn("start_my_day", handle.read())
