"""Proactive leave nudges. Fake clock, fake events, no Mac, no network."""
import inspect
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

import commands
from commands import leave as leave_mod
from commands import leave_nudge

TZ = ZoneInfo("America/Los_Angeles")
NOW_LINE = "Leave now for your 9:00 AM start at Brea — drive ~32 min + 15 min buffer"
PRE_LINE = "Leave in 10 minutes for your 9:00 AM start at Brea — drive ~32 min + 15 min buffer"


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


class _Result:
    def __init__(self, code):
        self.returncode = code


class TestLeaveNudge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = os.path.join(self.tmp.name, "leave-reminders.json")
        self.overrides = os.path.join(self.tmp.name, "shift-overrides.json")
        leave_nudge.hold_leave_nudges(False)
        leave_nudge.set_leave_quiet_probe(None)
        leave_nudge._thread = None

    def tearDown(self):
        leave_nudge.hold_leave_nudges(False)
        leave_nudge.set_leave_quiet_probe(None)
        leave_nudge._thread = None

    def _deliver(self, now, events, travel=32 * 60, quiet=False, prewarn=10):
        spoken = []

        def deliver(line):
            spoken.append(line)
            return True

        with mock.patch.object(leave_mod, "expected_travel_seconds", return_value=travel):
            lines = leave_nudge.deliver_due_nudges(
                now, deliver, path=self.overrides, events=events,
                state_path=self.state, quiet=quiet, prewarn_minutes=prewarn)
        return lines, spoken

    def test_leave_now_fires_once_at_the_leave_time(self):
        start = _at(2026, 10, 8, 9, 0)
        events = [_shift("R156 Brea", start)]
        early, _spoken = self._deliver(_at(2026, 10, 8, 8, 12), events, prewarn=0)
        self.assertEqual(early, [])
        first, spoken = self._deliver(_at(2026, 10, 8, 8, 13), events, prewarn=0)
        self.assertEqual(first, [NOW_LINE])
        self.assertEqual(spoken, [NOW_LINE])
        again, _spoken = self._deliver(_at(2026, 10, 8, 8, 20), events, prewarn=0)
        self.assertEqual(again, [])
        with open(self.state, encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertTrue(saved["fired"][leave_nudge.shift_key(events[0])]["now"])

    def test_prewarning_then_leave_now_each_once(self):
        events = [_shift("Shift at Brea", _at(2026, 10, 8, 9, 0), place="Brea")]
        before, _spoken = self._deliver(_at(2026, 10, 8, 8, 2), events)
        self.assertEqual(before, [])
        pre, _spoken = self._deliver(_at(2026, 10, 8, 8, 3), events)
        self.assertEqual(pre, [PRE_LINE])
        pre_again, _spoken = self._deliver(_at(2026, 10, 8, 8, 12), events)
        self.assertEqual(pre_again, [])
        now_line, _spoken = self._deliver(_at(2026, 10, 8, 8, 13), events)
        self.assertEqual(now_line, [NOW_LINE])
        now_again, _spoken = self._deliver(_at(2026, 10, 8, 8, 40), events)
        self.assertEqual(now_again, [])

    def test_a_late_wake_skips_the_prewarning(self):
        events = [_shift("Shift at Brea", _at(2026, 10, 8, 9, 0), place="Brea")]
        lines, _spoken = self._deliver(_at(2026, 10, 8, 8, 13), events, prewarn=10)
        self.assertEqual(lines, [NOW_LINE])

    def test_started_shift_and_non_shift_do_not_fire(self):
        calls = []

        def travel(*_args, **_kwargs):
            calls.append(True)
            return 32 * 60

        started = [_shift("Shift at Brea", _at(2026, 10, 8, 9, 0), place="Brea")]
        lunch = [_shift("Lunch with Zoe", _at(2026, 10, 8, 12, 0))]
        with mock.patch.object(leave_mod, "expected_travel_seconds", side_effect=travel):
            started_lines = leave_nudge.due_leave_nudges(
                _at(2026, 10, 8, 10, 0), events=started, state_path=self.state,
                path=self.overrides)
            lunch_lines = leave_nudge.due_leave_nudges(
                _at(2026, 10, 8, 11, 0), events=lunch, state_path=self.state,
                path=self.overrides)
        self.assertEqual(started_lines, [])
        self.assertEqual(lunch_lines, [])
        self.assertEqual(calls, [])
        self.assertFalse(os.path.exists(self.state))

    def test_a_non_brea_shift_does_not_fire(self):
        other = [_shift("R345 - Promenade Temecula", _at(2026, 10, 8, 9, 0))]
        with mock.patch.object(leave_mod, "expected_travel_seconds", return_value=32 * 60) as travel:
            lines = leave_nudge.due_leave_nudges(
                _at(2026, 10, 8, 8, 0), events=other, state_path=self.state,
                path=self.overrides)
        self.assertEqual(lines, [])
        travel.assert_not_called()

    def test_a_later_brea_shift_still_nudges_after_one_has_started(self):
        events = [
            _shift("Shift at Brea", _at(2026, 10, 8, 9, 0), place="Brea"),
            _shift("R156 Brea", _at(2026, 10, 8, 17, 0)),
        ]
        early, _spoken = self._deliver(_at(2026, 10, 8, 12, 0), events, prewarn=0)
        self.assertEqual(early, [])
        # 17:00 minus 32 minutes minus 15 minutes is 16:13.
        lines, _spoken = self._deliver(_at(2026, 10, 8, 16, 13), events, prewarn=0)
        self.assertEqual(len(lines), 1)
        self.assertIn("5:00 PM", lines[0])
        self.assertIn("Leave now", lines[0])

    def test_fallback_drive_time_when_eta_fails(self):
        events = [_shift("Shift at Brea", _at(2026, 10, 8, 9, 0), place="Brea")]
        # 35 minute typical drive plus the 15 minute buffer. Leave at 8:10.
        too_soon, _spoken = self._deliver(_at(2026, 10, 8, 8, 9), events, travel=None, prewarn=0)
        self.assertEqual(too_soon, [])
        lines, _spoken = self._deliver(_at(2026, 10, 8, 8, 10), events, travel=None, prewarn=0)
        self.assertEqual(len(lines), 1)
        self.assertIn("~35 min estimate", lines[0])
        self.assertIn("15 min buffer", lines[0])
        self.assertIn("Leave now", lines[0])
        self.assertIn("9:00 AM", lines[0])

        def boom(*_args, **_kwargs):
            raise RuntimeError("mapkit")

        fresh = os.path.join(self.tmp.name, "other-state.json")
        with mock.patch.object(leave_mod, "expected_travel_seconds", side_effect=boom):
            failed = leave_nudge.due_leave_nudges(
                _at(2026, 10, 8, 8, 10), events=events, state_path=fresh,
                path=self.overrides, prewarn_minutes=0)
        self.assertIn("estimate", failed[0]["line"])
        self.assertIn("~35 min", failed[0]["line"])

    def test_a_traffic_change_moves_the_nudge(self):
        events = [_shift("Shift at Brea", _at(2026, 10, 8, 9, 0), place="Brea")]
        early, _spoken = self._deliver(_at(2026, 10, 8, 7, 50), events, travel=20 * 60, prewarn=0)
        self.assertEqual(early, [])
        lines, _spoken = self._deliver(_at(2026, 10, 8, 7, 55), events, travel=80 * 60, prewarn=0)
        self.assertEqual(len(lines), 1)
        self.assertIn("~80 min", lines[0])
        self.assertTrue(lines[0].startswith("Leave now"))

    def test_override_wins_over_the_calendar_shift(self):
        commands.set_shift_override(
            "my shift Thursday is 9:30 to 6:30 at Brea",
            today=_at(2026, 10, 8).date(),
            path=self.overrides,
        )
        calendar = [_shift("R345 - Promenade Temecula", _at(2026, 10, 8, 8, 0))]
        # 9:30 minus 32 minutes minus 15 minutes is 8:43.
        lines, _spoken = self._deliver(_at(2026, 10, 8, 8, 43), calendar, prewarn=0)
        self.assertEqual(len(lines), 1)
        self.assertIn("9:30 AM", lines[0])
        self.assertIn("Brea", lines[0])
        self.assertNotIn("Temecula", lines[0])
        self.assertNotIn("8:00 AM", lines[0])

    def test_quiet_and_a_failed_delivery_do_not_mark_the_shift(self):
        events = [_shift("Shift at Brea", _at(2026, 10, 8, 9, 0), place="Brea")]
        when = _at(2026, 10, 8, 8, 13)
        quiet, _spoken = self._deliver(when, events, prewarn=0, quiet=True)
        self.assertEqual(quiet, [])
        self.assertFalse(os.path.exists(self.state))

        def refuse(_line):
            return False

        with mock.patch.object(leave_mod, "expected_travel_seconds", return_value=32 * 60):
            refused = leave_nudge.deliver_due_nudges(
                when, refuse, events=events, state_path=self.state,
                path=self.overrides, quiet=False, prewarn_minutes=0)
        self.assertEqual(refused, [])
        self.assertFalse(os.path.exists(self.state))

        def explode(_line):
            raise RuntimeError("speaker")

        with mock.patch.object(leave_mod, "expected_travel_seconds", return_value=32 * 60):
            exploded = leave_nudge.deliver_due_nudges(
                when, explode, events=events, state_path=self.state,
                path=self.overrides, quiet=False, prewarn_minutes=0)
        self.assertEqual(exploded, [])
        lines, _spoken = self._deliver(when, events, prewarn=0)
        self.assertEqual(lines, [NOW_LINE])

    def test_silence_notifications_holds_the_nudge_until_cleared(self):
        events = [_shift("Shift at Brea", _at(2026, 10, 8, 9, 0), place="Brea")]
        when = _at(2026, 10, 8, 8, 13)
        leave_nudge.hold_leave_nudges(True)
        held, _spoken = self._deliver(when, events, prewarn=0, quiet=None)
        self.assertEqual(held, [])
        self.assertFalse(os.path.exists(self.state))
        leave_nudge.hold_leave_nudges(False)
        lines, _spoken = self._deliver(when, events, prewarn=0, quiet=None)
        self.assertEqual(lines, [NOW_LINE])

    def test_toggle_persists_and_blocks_the_nudge(self):
        events = [_shift("Shift at Brea", _at(2026, 10, 8, 9, 0), place="Brea")]
        when = _at(2026, 10, 8, 8, 13)
        self.assertTrue(commands.leave_reminders_enabled(self.state))
        spoken = commands.set_leave_reminders(False, path=self.state)
        self.assertIn("off", spoken)
        self.assertFalse(commands.leave_reminders_enabled(self.state))
        blocked, _lines = self._deliver(when, events, prewarn=0)
        self.assertEqual(blocked, [])
        spoken = commands.set_leave_reminders(True, path=self.state)
        self.assertIn("on", spoken)
        lines, _spoken = self._deliver(when, events, prewarn=0)
        self.assertEqual(lines, [NOW_LINE])
        with open(self.state, encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertTrue(saved["enabled"])
        self.assertTrue(saved["fired"][leave_nudge.shift_key(events[0])]["now"])

    def test_poll_interval_shrinks_as_the_shift_approaches(self):
        soon = {"leave": _at(2026, 10, 8, 9, 0), "brea": True, "started": False}
        self.assertEqual(
            leave_nudge.leave_poll_seconds(_at(2026, 10, 8, 4, 0), soon),
            commands.LEAVE_POLL_FAR_SECONDS)
        self.assertEqual(
            leave_nudge.leave_poll_seconds(_at(2026, 10, 8, 7, 0), soon),
            commands.LEAVE_POLL_NEAR_SECONDS)
        self.assertEqual(
            leave_nudge.leave_poll_seconds(_at(2026, 10, 8, 8, 30), soon),
            commands.LEAVE_POLL_CLOSE_SECONDS)
        self.assertEqual(
            leave_nudge.leave_poll_seconds(_at(2026, 10, 8, 8, 0), None),
            commands.LEAVE_POLL_FAR_SECONDS)
        self.assertEqual(
            leave_nudge.leave_poll_seconds(_at(2026, 10, 8, 8, 0), soon, enabled=False),
            commands.LEAVE_POLL_CLOSE_SECONDS)
        self.assertGreaterEqual(commands.LEAVE_POLL_CLOSE_SECONDS, 60)
        self.assertGreater(commands.LEAVE_POLL_FAR_SECONDS, commands.LEAVE_POLL_CLOSE_SECONDS)

    def test_one_pass_asks_mapkit_once(self):
        events = [_shift("Shift at Brea", _at(2026, 10, 8, 9, 0), place="Brea")]
        calls = []

        def travel(*_args, **_kwargs):
            calls.append(True)
            return 32 * 60

        with mock.patch.object(leave_mod, "expected_travel_seconds", side_effect=travel):
            delay = leave_nudge.run_leave_nudge_once(
                lambda _line: True, now=_at(2026, 10, 8, 8, 13),
                path=self.overrides, events=events, state_path=self.state,
                quiet=False, prewarn_minutes=0)
        self.assertEqual(calls, [True])
        self.assertEqual(delay, commands.LEAVE_POLL_CLOSE_SECONDS)

    def test_muted_read_and_notification_stay_on_argument_lists(self):
        calls = []

        def run(args):
            calls.append(tuple(args))
            return "true\n"

        self.assertTrue(commands.mac_output_muted(runner=run))
        self.assertEqual(calls, [(
            "osascript", "-e", "output muted of (get volume settings)",
        )])
        self.assertFalse(commands.mac_output_muted(runner=lambda _args: "false"))

        def boom(_args):
            raise RuntimeError("no volume")

        self.assertFalse(commands.mac_output_muted(runner=boom))

        posted = []

        def notify(args):
            posted.append(list(args))
            return _Result(0)

        self.assertTrue(commands.post_leave_notification(NOW_LINE, runner=notify))
        self.assertEqual(posted[0][0], "osascript")
        self.assertEqual(posted[0][1], "-e")
        self.assertIn("item 1 of argv", posted[0][2])
        self.assertNotIn(NOW_LINE, posted[0][2])
        self.assertEqual(posted[0][3], NOW_LINE)
        self.assertFalse(commands.post_leave_notification(NOW_LINE, runner=lambda _args: _Result(1)))
        self.assertFalse(commands.post_leave_notification("", runner=notify))

    def test_scheduler_starts_only_on_mac(self):
        started = []

        def fake_start(thread):
            started.append(thread.name)

        with mock.patch.object(leave_nudge.sys, "platform", "linux"):
            self.assertIsNone(leave_nudge.start_leave_nudge_thread(lambda _line: True))
        self.assertEqual(started, [])

        def probe():
            return False

        with mock.patch.object(leave_nudge.sys, "platform", "darwin"), \
                mock.patch.object(leave_nudge.threading.Thread, "start", fake_start):
            thread = leave_nudge.start_leave_nudge_thread(lambda _line: True, quiet_check=probe)
        self.assertEqual(started, ["jev-leave-nudge"])
        self.assertTrue(thread.daemon)
        self.assertIs(leave_nudge._quiet_probe, probe)

    def test_routes_and_the_keys_stay_off_the_bridge(self):
        phrases = {
            "turn on leave reminders": "leave_reminders_on",
            "turn off leave reminders": "leave_reminders_off",
            "leave reminders on": "leave_reminders_on",
            "leave reminders off": "leave_reminders_off",
            "enable leave reminders": "leave_reminders_on",
            "disable leave reminders": "leave_reminders_off",
            "please turn on leave reminders": "leave_reminders_on",
            "turn off leave reminders.": "leave_reminders_off",
        }
        for phrase, key in phrases.items():
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
            self.assertNotIn(key, commands.BRIDGE_ALLOW, phrase)
        self.assertEqual(commands.route_before_api("when should I leave for work"), "info_leave")
        self.assertEqual(commands.bridge_allowed("when should I leave for work"), "info_leave")
        self.assertIn("info_leave", commands.BRIDGE_ALLOW)
        self.assertEqual(commands.route_before_api("turn on voiceover"), "voiceover_on")
        self.assertEqual(commands.route_before_api("turn off do not disturb"), "notify_on")
        self.assertEqual(commands.route_before_api("silence notifications"), "notify_off")
        self.assertIsNone(commands.route_before_api("turn on leave reminders and mute"))

    def test_nudge_source_has_no_socket_secret_or_bridge_edit(self):
        source = inspect.getsource(leave_nudge).lower()
        self.assertNotIn("secrets_store", source)
        self.assertNotIn("keychain_value", source)
        self.assertNotIn("socket.socket", source)
        self.assertNotIn("bridge_allow", source)
        self.assertNotIn("import requests", source)
        self.assertNotIn(".listen(", source)
        self.assertIn("describe_leave", source)


class TestQuietProbe(unittest.TestCase):
    def tearDown(self):
        leave_nudge.hold_leave_nudges(False)
        leave_nudge.set_leave_quiet_probe(None)

    def test_a_probe_can_hold_the_nudge_and_a_probe_error_does_not(self):
        leave_nudge.set_leave_quiet_probe(lambda: True)
        self.assertTrue(leave_nudge.quiet_now())
        leave_nudge.set_leave_quiet_probe(lambda: False)
        self.assertFalse(leave_nudge.quiet_now())

        def boom():
            raise RuntimeError("focus")

        leave_nudge.set_leave_quiet_probe(boom)
        self.assertFalse(leave_nudge.quiet_now())
        leave_nudge.hold_leave_nudges(True)
        self.assertTrue(leave_nudge.quiet_now())
