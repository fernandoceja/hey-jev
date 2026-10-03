"""Payday sweep and IHSS timesheet dates. No bank, no network, no macOS."""
import os
import tempfile
import unittest
from datetime import date
from unittest import mock

import commands
from commands import brief as brief_mod
from commands import money as money_mod

ANCHOR = date(2026, 9, 25)
MOVE = "move $600 to Zoe \u20264157."
APPLE = "Apple payday today \u2014 " + MOVE
IHSS = "IHSS payday today \u2014 " + MOVE
BOTH = "Apple and IHSS payday today \u2014 " + MOVE
SHEET = "Time to submit your timesheet."


class TestSweepDates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.money = os.path.join(self.tmp.name, "missing-money.md")

    def line(self, today, path=None):
        return commands.sweep_reminder_line(today, path=path or self.money)

    def test_amount_anchor_and_account_live_in_config(self):
        self.assertEqual(commands.DEFAULT_APPLE_PAY_ANCHOR, "2026-09-25")
        self.assertEqual(commands.SWEEP_AMOUNT, 600)
        self.assertEqual(commands.SWEEP_ACCOUNT_LABEL, "Zoe \u20264157")
        self.assertIn("\u2026", commands.SWEEP_ACCOUNT_LABEL)
        schedule = commands.load_pay_schedule(self.money)
        self.assertEqual(schedule["anchor"], ANCHOR)
        self.assertEqual(schedule["amount"], 600)
        self.assertEqual(schedule["account"], commands.SWEEP_ACCOUNT_LABEL)
        self.assertTrue(schedule["default"])

    def test_apple_biweekly_anchor_includes_today_and_skips_the_friday_before(self):
        self.assertEqual(ANCHOR.strftime("%A"), "Friday")
        self.assertTrue(commands.is_apple_payday(ANCHOR, ANCHOR))
        self.assertTrue(commands.is_apple_payday(date(2026, 10, 9), ANCHOR))
        self.assertTrue(commands.is_apple_payday(date(2026, 10, 23), ANCHOR))
        self.assertFalse(commands.is_apple_payday(date(2026, 10, 2), ANCHOR))
        self.assertFalse(commands.is_apple_payday(date(2026, 10, 8), ANCHOR))
        # Fourteen days before the anchor is the same cadence, and it is not a payday.
        self.assertEqual((ANCHOR - date(2026, 9, 11)).days, 14)
        self.assertFalse(commands.is_apple_payday(date(2026, 9, 11), ANCHOR))
        self.assertEqual(self.line(date(2026, 9, 25)), APPLE)
        self.assertEqual(self.line(date(2026, 10, 9)), APPLE)
        self.assertEqual(self.line(date(2026, 10, 23)), APPLE)
        self.assertIsNone(self.line(date(2026, 9, 11)))
        self.assertIsNone(self.line(date(2026, 10, 2)))
        self.assertIsNone(self.line(date(2026, 10, 8)))
        self.assertIsNone(self.line(date(2026, 10, 10)))

    def test_ihss_fifteenth_and_last_day_including_february_and_leap_years(self):
        self.assertEqual(self.line(date(2026, 10, 15)), IHSS)
        self.assertEqual(self.line(date(2026, 4, 15)), IHSS)
        # 31-day and 30-day months. The last day is also a timesheet day.
        self.assertEqual(self.line(date(2026, 10, 31)), IHSS + " " + SHEET)
        self.assertEqual(self.line(date(2026, 9, 30)), IHSS + " " + SHEET)
        self.assertEqual(self.line(date(2026, 6, 30)), IHSS + " " + SHEET)
        # 2026 is not a leap year. February ends on the 28th.
        self.assertEqual(self.line(date(2026, 2, 15)), IHSS)
        self.assertEqual(self.line(date(2026, 2, 28)), IHSS + " " + SHEET)
        self.assertIsNone(self.line(date(2026, 2, 27)))
        # 2024 is a leap year. The 28th is an ordinary day. The 29th is the end.
        self.assertFalse(commands.is_ihss_payday(date(2024, 2, 28)))
        self.assertFalse(commands.is_timesheet_day(date(2024, 2, 28)))
        self.assertIsNone(self.line(date(2024, 2, 28)))
        self.assertEqual(self.line(date(2024, 2, 29)), IHSS + " " + SHEET)
        self.assertEqual(self.line(date(2024, 2, 15)), IHSS)
        # 2000 is a leap year. 2100 is not.
        self.assertIsNone(self.line(date(2000, 2, 28)))
        self.assertEqual(self.line(date(2000, 2, 29)), IHSS + " " + SHEET)
        self.assertEqual(self.line(date(2100, 2, 28)), IHSS + " " + SHEET)
        self.assertIsNone(self.line(date(2100, 2, 27)))

    def test_fourteenth_is_only_the_timesheet_nudge(self):
        self.assertTrue(commands.is_timesheet_day(date(2026, 10, 14)))
        self.assertFalse(commands.is_ihss_payday(date(2026, 10, 14)))
        self.assertFalse(commands.is_apple_payday(date(2026, 10, 14), ANCHOR))
        self.assertEqual(self.line(date(2026, 10, 14)), SHEET)
        self.assertEqual(self.line(date(2026, 2, 14)), SHEET)
        self.assertEqual(self.line(date(2024, 2, 14)), SHEET)
        self.assertIsNone(self.line(date(2026, 10, 13)))
        self.assertFalse(commands.is_timesheet_day(date(2026, 10, 15)))

    def test_combined_apple_and_ihss_days(self):
        fifteenth = date(2027, 1, 15)
        self.assertEqual(fifteenth.strftime("%A"), "Friday")
        self.assertEqual(self.line(fifteenth), BOTH)
        year_end = date(2027, 12, 31)
        self.assertEqual(year_end.strftime("%A"), "Friday")
        self.assertEqual(self.line(year_end), BOTH + " " + SHEET)
        fourteenth = date(2028, 1, 14)
        self.assertEqual(fourteenth.strftime("%A"), "Friday")
        self.assertEqual(self.line(fourteenth), APPLE + " " + SHEET)

    def test_quiet_days_return_nothing_and_do_not_run_a_process(self):
        def boom(*_args, **_kwargs):
            raise AssertionError("sweep tried to run a process")

        with mock.patch.object(commands.subprocess, "run", boom):
            self.assertIsNone(self.line(date(2026, 10, 8)))
            self.assertIsNone(self.line(date(2026, 10, 16)))
            self.assertIsNone(self.line(date(2026, 11, 1)))
            spoken = commands.speak_payday_check(date(2026, 10, 8), path=self.money)
        self.assertEqual(spoken, "Nothing to sweep today.")
        self.assertEqual(commands.speak_payday_check(date(2026, 10, 9), path=self.money), APPLE)
        self.assertEqual(commands.speak_payday_check(date(2026, 10, 14), path=self.money), SHEET)

    def test_money_md_changes_the_apple_anchor_and_not_the_amount(self):
        path = os.path.join(self.tmp.name, "money.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("# local only\napple: 2026-10-09\nihss: semi-monthly\n")
        self.assertIsNone(self.line(date(2026, 9, 25), path=path))
        self.assertEqual(self.line(date(2026, 10, 9), path=path), APPLE)
        self.assertEqual(self.line(date(2026, 10, 23), path=path), APPLE)
        self.assertEqual(self.line(date(2026, 10, 15), path=path), IHSS)
        schedule = commands.load_pay_schedule(path)
        self.assertFalse(schedule["default"])
        self.assertEqual(schedule["amount"], commands.SWEEP_AMOUNT)
        self.assertEqual(schedule["account"], commands.SWEEP_ACCOUNT_LABEL)

    def test_launch_reminder_is_once_per_sweep_day(self):
        stamp = os.path.join(self.tmp.name, "nested", "sweep-spoken.txt")
        first = commands.claim_daily_sweep(date(2026, 10, 9), state_path=stamp, path=self.money)
        self.assertEqual(first, APPLE)
        with open(stamp, encoding="utf-8") as handle:
            self.assertEqual(handle.read().strip(), "2026-10-09")
        self.assertIsNone(commands.claim_daily_sweep(date(2026, 10, 9), state_path=stamp, path=self.money))
        # Asking out loud still answers after the launch line was claimed.
        self.assertEqual(commands.speak_payday_check(date(2026, 10, 9), path=self.money), APPLE)
        later = commands.claim_daily_sweep(date(2026, 10, 23), state_path=stamp, path=self.money)
        self.assertEqual(later, APPLE)
        quiet = os.path.join(self.tmp.name, "quiet.txt")
        self.assertIsNone(commands.claim_daily_sweep(date(2026, 10, 8), state_path=quiet, path=self.money))
        self.assertFalse(os.path.exists(quiet))

    def test_brief_adds_the_sweep_line_only_when_today_has_one(self):
        with mock.patch.object(money_mod, "MONEY_PATH", self.money), \
                mock.patch.object(brief_mod, "speak_date", return_value="Today."), \
                mock.patch.object(brief_mod, "speak_weather", return_value="Clear."), \
                mock.patch.object(brief_mod, "speak_today_schedule", return_value="Clear calendar."), \
                mock.patch.object(brief_mod, "speak_next_shift", return_value="No shift."), \
                mock.patch.object(brief_mod, "speak_due", return_value="Nothing is due."), \
                mock.patch.object(brief_mod, "gmail_brief_line", return_value=None):
            payday = commands.speak_brief(today=date(2026, 10, 9))
            quiet = commands.speak_brief(today=date(2026, 10, 8))
            combined = commands.speak_brief(today=date(2027, 1, 15))
            month_end = commands.speak_brief(today=date(2026, 10, 31))
        self.assertIn(APPLE, payday)
        self.assertIn("Nothing is due.", payday)
        self.assertNotIn("payday today", quiet)
        self.assertNotIn("timesheet", quiet.lower())
        self.assertIn(BOTH, combined)
        self.assertIn(IHSS, month_end)
        self.assertIn(SHEET, month_end)

    def test_check_phrases_are_allowlisted_and_my_love_is_not(self):
        phrases = (
            "what's due today",
            "what is due today",
            "what's due today?",
            "payday check",
            "please payday check",
            "any reminders today",
            "any reminder today",
        )
        self.assertIn("info_payday_check", commands.BRIDGE_ALLOW)
        self.assertNotIn("info_messages", commands.BRIDGE_ALLOW)
        for item in commands.BRIDGE_ALLOW:
            self.assertNotIn("*", item)
        for phrase in phrases:
            self.assertEqual(commands.route_before_api(phrase), "info_payday_check", phrase)
            self.assertEqual(commands.bridge_allowed(phrase), "info_payday_check", phrase)
        love = "check my messages from My Love"
        self.assertEqual(commands.route_before_api(love), "info_messages")
        self.assertIsNone(commands.bridge_allowed(love))
        self.assertIsNone(commands.route_before_api("move $600 to Zoe"))
        self.assertIsNone(commands.bridge_allowed("confirm the transfer"))
        self.assertEqual(commands.route_before_api("how long until payday"), "info_payday")
        self.assertEqual(commands.route_before_api("what's due"), "info_due")
        self.assertEqual(commands.route_before_api("what's due this week"), "info_due")


if __name__ == "__main__":
    unittest.main()
