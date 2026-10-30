"""Orb popover chips, history, and refresh. No AppKit."""
import os
import unittest
from unittest import mock

import commands
from commands import cleanmymac as cmm
from commands.routing import route_before_api
from mini_bar import (
    POPOVER_CHIPS,
    POPOVER_CHIP_PAGES,
    chip_command_plan,
    home_draft_from_popover,
    popover_chip_ids,
    popover_footer_layout,
    popover_layout,
    popover_subframes,
    refresh_chip_suggestions,
    submission,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AIR = (0.0, 70.0, 1440.0, 806.0)
COMPOSER = (900.0, 200.0, 420.0, 44.0)


def _func(source, name):
    start = source.index(f"def {name}")
    line_start = source.rfind("\n", 0, start) + 1
    indent = start - line_start
    marker = "\n" + (" " * indent) + "def "
    nxt = source.find(marker, start + 1)
    if nxt < 0:
        nxt = len(source)
    return source[start:nxt]


class TestChipRouting(unittest.TestCase):
    EXPECTED = (
        ("eta_home", "eta home", "info_eta_home"),
        ("hazard_check", "hazard check", "info_hazards"),
        ("plan_day", "brief me", "info_brief"),
        ("mac_health", "cleanmymac scan", "cleanmymac_scan"),
    )

    def test_default_page_chip_phrases_and_routes(self):
        self.assertEqual(popover_chip_ids(0), POPOVER_CHIP_PAGES[0])
        for chip_id, phrase, route in self.EXPECTED:
            info = POPOVER_CHIPS[chip_id]
            self.assertEqual(info["phrase"], phrase, chip_id)
            plan = chip_command_plan(chip_id)
            self.assertIsNotNone(plan)
            self.assertEqual(plan["kind"], "run")
            self.assertEqual(plan["control"], ("text", phrase))
            self.assertEqual(route_before_api(phrase), route, phrase)

    def test_hazard_chip_does_not_enable_background_alerts(self):
        plan = chip_command_plan("hazard_check")
        phrase = plan["control"][1]
        self.assertEqual(route_before_api(phrase), "info_hazards")
        self.assertNotEqual(route_before_api(phrase), "hazard_alerts_on")

    def test_brief_chip_is_not_scheduling(self):
        plan = chip_command_plan("plan_day")
        self.assertEqual(plan["control"][1], "brief me")
        self.assertEqual(route_before_api("brief me"), "info_brief")

    def test_cleanmymac_chip_scan_only_script(self):
        plan = chip_command_plan("mac_health")
        self.assertEqual(plan["control"][1], "cleanmymac scan")
        for word in cmm.FORBIDDEN_BUTTONS:
            self.assertNotIn('"%s"' % word, cmm.SMART_CARE_SCRIPT, word)


class TestChipDispatch(unittest.TestCase):
    def test_single_control_tuple_per_chip(self):
        for chip_id in popover_chip_ids(0):
            plan = chip_command_plan(chip_id)
            self.assertEqual(len(plan["control"]), 2)
            self.assertEqual(plan["control"][0], "text")

    def test_refresh_rotates_pages_without_queueing(self):
        start = 0
        nxt = refresh_chip_suggestions(start)
        self.assertNotEqual(popover_chip_ids(start), popover_chip_ids(nxt))
        self.assertEqual(refresh_chip_suggestions(nxt), 0)

    def test_refresh_does_not_build_a_run_plan(self):
        with mock.patch("mini_bar.submission") as submit:
            refresh_chip_suggestions(0)
            submit.assert_not_called()


class TestMissingKeys(unittest.TestCase):
    def test_chip_plan_still_routes_when_keys_missing(self):
        plan = chip_command_plan("eta_home")
        self.assertEqual(plan["control"][1], "eta home")
        self.assertEqual(route_before_api(plan["control"][1]), "info_eta_home")

    def test_ui_shows_local_reply_without_worker(self):
        ui = open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8").read()
        dispatch = _func(ui, "_dispatch_text_plan")
        self.assertIn("worker_started", dispatch)
        self.assertIn("Add your API keys", dispatch)
        self.assertIn("note_reply", dispatch)


class TestHistoryAndDraft(unittest.TestCase):
    def test_popover_layout_includes_footer(self):
        layout = popover_subframes(COMPOSER, AIR)
        self.assertIn("footer", layout)
        self.assertIn("chips", layout["footer"])
        self.assertGreater(len(layout["footer"]["chips"]), 0)

    def test_history_open_grows_popover(self):
        closed = popover_layout(COMPOSER, AIR, history_open=False)
        opened = popover_layout(COMPOSER, AIR, history_open=True)
        self.assertGreater(opened["frame"][3], closed["frame"][3])
        self.assertIsNotNone(opened["footer"]["history"])

    def test_expand_carries_draft_without_submit(self):
        draft = "  still typing  "
        self.assertEqual(home_draft_from_popover(draft), draft)
        ui = open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8").read()
        expand = _func(ui, "miniExpandHome_")
        self.assertIn("home_draft_from_popover", expand)
        self.assertNotIn("miniSubmit_", expand)
        self.assertNotIn("_dispatch_text_plan", expand)

    def test_shared_typed_history_wiring(self):
        ui = open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8").read()
        dispatch = _func(ui, "_dispatch_text_plan")
        self.assertIn("self.typed.note_request", dispatch)
        refresh = _func(ui, "_refresh_popover_history")
        self.assertIn("self.typed.text()", refresh)
        home = _func(ui, "_refresh_home_history")
        self.assertIn("_refresh_popover_history", home)


class TestRefreshWiring(unittest.TestCase):
    def test_refresh_handler_only_relayouts(self):
        ui = open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8").read()
        refresh = _func(ui, "miniRefreshChips_")
        self.assertIn("refresh_chip_suggestions", refresh)
        self.assertIn("_apply_pill_presentation", refresh)
        self.assertNotIn("controls.put", refresh)
        self.assertNotIn("_dispatch_text_plan", refresh)
        self.assertNotIn("chip_command_plan", refresh)


if __name__ == "__main__":
    unittest.main()
