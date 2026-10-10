"""ETA to work. MapKit is faked. No Keychain, no network, no bridge allow."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

import commands
from commands import leave as leave_mod
from mini_bar import submission

TZ = ZoneInfo("America/Los_Angeles")


def _at(year, month, day, hour=9, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


def _shift(title, start, hours=8, place=""):
    return {
        "title": title,
        "start": start,
        "end": start + timedelta(hours=hours),
        "all_day": False,
        "place": place,
    }


class TestEtaRouting(unittest.TestCase):
    def test_every_phrase_routes_and_old_commands_stay_put(self):
        phrases = (
            "what's my ETA to work",
            "what is my ETA to work",
            "ETA to work",
            "ETA work",
            "work ETA",
            "my ETA to work",
            "my ETA work",
            "my work ETA",
            "what's my ETA work",
            "what's my work ETA",
            "E.T.A. to work",
            "E.T.A. work",
            "work E.T.A.",
            "E. T. A. to work",
            "e.t.a. to work",
            "eta work",
            "how long to get to work",
            "how long will it take me to get to work",
            "how long will it take to get to work",
            "how long is my drive to work",
            "how far am I from work",
            "What's my ETA to work?",
            "WHAT IS MY ETA TO WORK",
            "please what's my ETA to work",
            "what's my ETA to work please",
            "please ETA to work",
            "hey jev what's my ETA to work",
            "hey jev, what's my ETA to work",
            "Hey Jev, what is my ETA to work",
            "hey jev, ETA to work",
            "hey jev, ETA work",
            "hey jev work ETA",
            "hey jev, E.T.A. to work",
            "hey jev my ETA to work",
            "please hey jev how long to get to work",
            "hey jev please how long will it take me to get to work",
            "hey jev, how long is my drive to work",
            "hey jev how far am I from work",
        )
        for phrase in phrases:
            self.assertEqual(commands.route_before_api(phrase), "info_eta_work", phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
        self.assertNotIn("info_eta_work", commands.BRIDGE_ALLOW)
        kept = {
            "when should I leave for work": "info_leave",
            "what time should I leave for Brea": "info_leave",
            "when do I need to leave for work": "info_leave",
            "when do I need to leave for Brea": "info_leave",
            "turn on leave reminders": "leave_reminders_on",
            "turn off leave reminders": "leave_reminders_off",
            "leave reminders on": "leave_reminders_on",
            "leave reminders off": "leave_reminders_off",
            "enable leave reminders": "leave_reminders_on",
            "disable leave reminders": "leave_reminders_off",
            "please turn on leave reminders": "leave_reminders_on",
            "remind me to buy milk": "remind_add",
            "remind me to get to work": "remind_add",
            "how long until payday": "info_payday",
            "how long is my shift": "info_shift_length",
        }
        for phrase, key in kept.items():
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertNotEqual(key, "info_eta_work", phrase)
        self.assertEqual(commands.route_before_api("how far am I from home"), "info_eta_home")
        self.assertEqual(commands.route_before_api("open home"), "app_open")
        self.assertEqual(commands.route_before_api("open Home"), "app_open")
        self.assertEqual(commands.route_before_api("quit Home"), "app_quit")
        self.assertEqual(commands.route_before_api("open Maps"), "app_open")
        for phrase in (
            "how long until summer",
            "what's my ETA to the airport",
            "how long is my drive to the store",
            "ETA homework",
            "work ETA please and open notes",
            "open ETA",
            "eat a snack",
            "what's my ETA to the store",
        ):
            self.assertNotIn(
                commands.route_before_api(phrase),
                ("info_eta_work", "info_eta_home", "info_eta_which"),
                phrase,
            )

    def test_typed_field_and_pill_use_the_same_route(self):
        for raw in (
            "What's my ETA to work",
            "  hey jev, what's my ETA to work? ",
            "please how long to get to work",
            "How far am I from work.",
        ):
            plan = submission(raw, "")
            self.assertEqual(plan["kind"], "run", raw)
            self.assertFalse(plan["reveal_main"], raw)
            self.assertEqual(plan["control"][0], "text", raw)
            self.assertEqual(
                commands.route_before_api(plan["control"][1]), "info_eta_work", raw)


class TestEtaReply(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "shift-overrides.json")
        self.home_path = os.path.join(self.tmp.name, "home-address.txt")
        self.now = _at(2026, 10, 5, 12, 15)
        self.hint = " " + commands.HOME_EXACT_HINT

    def _speak(self, events, seconds=32 * 60, boom=False):
        calls = []

        def fake(origin, destination, when, depart=False):
            calls.append((origin, destination, when, depart))
            return seconds

        def refuse(*_args, **_kwargs):
            raise AssertionError("ETA tried to run a process")

        travel = mock.patch.object(leave_mod, "expected_travel_seconds", side_effect=fake)
        if boom:
            with travel, mock.patch.object(commands.subprocess, "run", refuse):
                spoken = commands.speak_eta_to_work(
                    now=self.now, path=self.path, events=events, home_path=self.home_path)
        else:
            with travel:
                spoken = commands.speak_eta_to_work(
                    now=self.now, path=self.path, events=events, home_path=self.home_path)
        return spoken, calls

    def test_early_shift_today(self):
        events = [_shift("Shift at Brea", _at(2026, 10, 5, 13, 0), place="Brea")]
        spoken, calls = self._speak(events, boom=True)
        self.assertEqual(
            spoken,
            "About 32 minutes to work right now. You'd get there around 12:47 PM. "
            "Your shift starts at 1 PM, so you'd be about 13 minutes early."
            + self.hint,
        )
        self.assertNotIn("estimate", spoken)
        self.assertEqual(calls, [(
            commands.HOME_ADDRESS, commands.BREA_STORE_ADDRESS, self.now, True)])

    def test_late_shift_today(self):
        events = [_shift("Shift at Brea", _at(2026, 10, 5, 12, 42), place="Brea")]
        spoken, calls = self._speak(events)
        self.assertEqual(
            spoken,
            "About 32 minutes to work right now. You'd get there around 12:47 PM. "
            "Your shift starts at 12:42 PM, so you'd be about 5 minutes late."
            + self.hint,
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2], self.now)
        self.assertTrue(calls[0][3])

    def test_no_shift_skips_the_comparison(self):
        spoken, calls = self._speak([])
        self.assertEqual(
            spoken,
            "About 32 minutes to work right now. You'd get there around 12:47 PM."
            + self.hint,
        )
        self.assertNotIn("early", spoken)
        self.assertNotIn("late", spoken)
        self.assertNotIn("shift", spoken.lower())
        self.assertEqual(len(calls), 1)

    def test_started_shift_skips_the_comparison(self):
        events = [_shift("Shift at Brea", _at(2026, 10, 5, 9, 30), place="Brea")]
        spoken, calls = self._speak(events)
        self.assertEqual(
            spoken,
            "About 32 minutes to work right now. You'd get there around 12:47 PM."
            + self.hint,
        )
        self.assertNotIn("already", spoken)
        self.assertNotIn("early", spoken)
        self.assertNotIn("late", spoken)
        self.assertEqual(calls[0][1], commands.BREA_STORE_ADDRESS)

    def test_tomorrow_does_not_count_as_today(self):
        events = [_shift("Shift at Brea", _at(2026, 10, 6, 13, 0), place="Brea")]
        spoken, calls = self._speak(events)
        self.assertEqual(
            spoken,
            "About 32 minutes to work right now. You'd get there around 12:47 PM."
            + self.hint,
        )
        self.assertNotIn("early", spoken)
        self.assertEqual(calls[0][2], self.now)

    def test_override_replaces_the_calendar_shift(self):
        commands.set_shift_override(
            "my shift Monday is 1:00 to 6:30 at Brea",
            today=self.now.date(),
            path=self.path,
        )
        calendar = [_shift("Shift at Brea", _at(2026, 10, 5, 8, 0), place="Brea")]
        spoken, _calls = self._speak(calendar)
        self.assertIn("1 PM", spoken)
        self.assertIn("13 minutes early", spoken)
        self.assertNotIn("8 AM", spoken)
        self.assertNotIn("8:00", spoken)

    def test_on_time_is_said_plainly(self):
        events = [_shift("Shift at Brea", _at(2026, 10, 5, 12, 47), place="Brea")]
        spoken, _calls = self._speak(events)
        self.assertIn("right on time", spoken)
        self.assertNotIn("early", spoken)
        self.assertNotIn("late", spoken)

    def test_mapkit_failure_uses_the_typical_drive(self):
        def refuse(*_args, **_kwargs):
            raise AssertionError("ETA tried to run a process")

        with mock.patch.object(leave_mod, "expected_travel_seconds", return_value=None), \
                mock.patch.object(commands.subprocess, "run", refuse):
            spoken = commands.speak_eta_to_work(
                now=self.now, path=self.path, events=[], home_path=self.home_path)
        self.assertEqual(
            spoken,
            "About 35 minutes to work right now. "
            "I'm using a typical drive of 35 minutes as an estimate. "
            "You'd get there around 12:50 PM."
            + self.hint,
        )
        with mock.patch.object(leave_mod, "expected_travel_seconds", side_effect=RuntimeError("mapkit")):
            raised = commands.speak_eta_to_work(
                now=self.now, path=self.path, events=[], home_path=self.home_path)
        self.assertIn("estimate", raised)
        self.assertIn("35 minutes", raised)
        self.assertIn("12:50 PM", raised)

    def test_other_store_still_drives_to_brea(self):
        events = [_shift("R345 - Promenade Temecula", _at(2026, 10, 5, 13, 0))]
        spoken, calls = self._speak(events)
        self.assertIn("13 minutes early", spoken)
        self.assertEqual(calls[0][0], commands.HOME_ADDRESS)
        self.assertEqual(calls[0][1], commands.BREA_STORE_ADDRESS)
        self.assertIn("1016C", calls[0][1])
        self.assertIn(commands.HOME_EXACT_HINT, spoken)
        self.assertNotIn("Upland", spoken)

    def test_a_saved_home_line_is_the_origin_and_is_not_spoken(self):
        street = "742 Evergreen Terrace, Springfield"
        with open(self.home_path, "w", encoding="utf-8") as handle:
            handle.write(street + "\nsecond line is ignored\n")
        events = [_shift("Shift at Brea", _at(2026, 10, 5, 13, 0), place="Brea")]
        spoken, calls = self._speak(events, boom=True)
        self.assertEqual(calls[0][0], street)
        self.assertEqual(calls[0][1], commands.BREA_STORE_ADDRESS)
        self.assertNotIn(street, spoken)
        self.assertNotIn("Evergreen", spoken)
        self.assertNotIn("Springfield", spoken)
        self.assertNotIn(commands.HOME_EXACT_HINT, spoken)
        self.assertNotIn("home", spoken.lower())
        self.assertTrue(spoken.startswith("About 32 minutes to work right now."))
