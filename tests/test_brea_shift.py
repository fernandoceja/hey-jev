"""Brea shift override and leave time. MapKit is faked. No Keychain, no network."""
import inspect
import json
import os
import tempfile
import types
import unittest
from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

import commands
from commands import leave as leave_mod
from commands import travel as travel_mod

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


class _Obj:
    @classmethod
    def alloc(cls):
        return cls()

    def init(self):
        return self


class _Placemark(_Obj):
    def initWithCoordinate_(self, coord):
        self.coord = coord
        return self

    def location(self):
        return self

    def coordinate(self):
        return self.coord


class _MapItem(_Obj):
    def initWithPlacemark_(self, placemark):
        self.placemark = placemark
        return self


class _Request(_Obj):
    def setSource_(self, item):
        self.source = item

    def setDestination_(self, item):
        self.destination = item

    def setTransportType_(self, kind):
        self.kind = kind

    def setArrivalDate_(self, when):
        self.arrival = when

    def setDepartureDate_(self, when):
        self.departure = when


class _Response:
    def __init__(self, seconds):
        self.seconds = seconds

    def expectedTravelTime(self):
        return self.seconds


class _Directions(_Obj):
    last_request = None
    result = (1800.0, None)

    def initWithRequest_(self, request):
        self.request = request
        return self

    def calculateETAWithCompletionHandler_(self, handler):
        _Directions.last_request = self.request
        seconds, error = _Directions.result
        handler(None if seconds is None else _Response(seconds), error)


class _Geocoder(_Obj):
    addresses = []
    fail = False

    def geocodeAddressString_completionHandler_(self, address, handler):
        _Geocoder.addresses.append(address)
        if _Geocoder.fail:
            handler(None, "no place")
            return
        handler([_Placemark.alloc().initWithCoordinate_((1.0, 2.0))], None)


def _frameworks():
    core = types.ModuleType("CoreLocation")
    core.CLGeocoder = _Geocoder
    maps = types.ModuleType("MapKit")
    maps.MKPlacemark = _Placemark
    maps.MKMapItem = _MapItem
    maps.MKDirectionsRequest = _Request
    maps.MKDirections = _Directions
    maps.MKDirectionsTransportTypeAutomobile = 1
    foundation = types.ModuleType("Foundation")

    class NSDate:
        @staticmethod
        def dateWithTimeIntervalSince1970_(stamp):
            return stamp

    foundation.NSDate = NSDate
    return {
        "CoreLocation": core,
        "MapKit": maps,
        "Foundation": foundation,
    }


class TestShiftOverride(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "shift-overrides.json")
        self.saturday = datetime(2026, 10, 3).date()
        self.monday = datetime(2026, 10, 5).date()

    def test_addresses_and_buffer_live_in_config(self):
        self.assertEqual(commands.HOME_ADDRESS, "Upland, CA")
        self.assertIn("1016C Brea Mall", commands.BREA_STORE_ADDRESS)
        self.assertIn("92821", commands.BREA_STORE_ADDRESS)
        self.assertNotIn("1065", commands.BREA_STORE_ADDRESS)
        self.assertEqual(commands.LEAVE_BUFFER_MINUTES, 15)
        self.assertEqual(commands.LEAVE_TYPICAL_DRIVE_MINUTES, 35)
        self.assertTrue(commands.SHIFT_OVERRIDE_PATH.endswith(
            "Library/Application Support/Hey Jev/shift-overrides.json"))

    def test_monday_example_is_saved_as_plain_json(self):
        spoken = commands.set_shift_override(
            "my shift Monday is 9:30 to 6:30 at Brea",
            today=self.saturday,
            path=self.path,
        )
        self.assertIn("October 5th", spoken)
        self.assertIn("9:30 AM", spoken)
        self.assertIn("6:30 PM", spoken)
        self.assertIn("calendar", spoken)
        with open(self.path, encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertEqual(list(saved), ["2026-10-05"])
        self.assertEqual(saved["2026-10-05"], {
            "start": "09:30",
            "end": "18:30",
            "place": "Brea",
        })
        raw = open(self.path, encoding="utf-8").read().lower()
        self.assertNotIn("keychain", raw)
        self.assertNotIn("secret", raw)
        self.assertNotIn("token", raw)

    def test_explicit_meridiem_matches_the_spoken_assumption(self):
        commands.set_shift_override(
            "my shift on Monday is 9:30 am to 6:30 pm at Brea",
            today=self.saturday,
            path=self.path,
        )
        saved = commands.load_shift_overrides(self.path)
        self.assertEqual(saved["2026-10-05"]["start"], "09:30")
        self.assertEqual(saved["2026-10-05"]["end"], "18:30")

    def test_clear_one_day_and_clear_all(self):
        commands.set_shift_override(
            "my shift Monday is 9:30 to 6:30 at Brea",
            today=self.saturday,
            path=self.path,
        )
        commands.set_shift_override(
            "my shift Tuesday is 10 to 7 at Brea",
            today=self.saturday,
            path=self.path,
        )
        missing = commands.clear_shift_override(
            "clear my shift Wednesday", today=self.saturday, path=self.path)
        self.assertIn("don't have", missing)
        self.assertEqual(len(commands.load_shift_overrides(self.path)), 2)
        cleared = commands.clear_shift_override(
            "clear my shift Monday", today=self.saturday, path=self.path)
        self.assertIn("October 5th", cleared)
        left = commands.load_shift_overrides(self.path)
        self.assertNotIn("2026-10-05", left)
        self.assertIn("2026-10-06", left)
        all_gone = commands.clear_shift_override(
            "clear my shift overrides", today=self.saturday, path=self.path)
        self.assertIn("Cleared your shift overrides", all_gone)
        self.assertEqual(commands.load_shift_overrides(self.path), {})
        again = commands.clear_shift_override(
            "clear my shift overrides", today=self.saturday, path=self.path)
        self.assertIn("don't have any", again)

    def test_override_replaces_the_calendar_that_day_only(self):
        now = _at(2026, 10, 3, 8, 0)
        monday = _at(2026, 10, 5, 8, 0)
        tuesday = _at(2026, 10, 6, 10, 0)
        calendar = [
            _shift("R345 - Promenade Temecula", monday),
            _shift("R345 - Promenade Temecula", tuesday),
        ]
        commands.set_shift_override(
            "my shift Monday is 9:30 to 6:30 at Brea",
            today=self.saturday,
            path=self.path,
        )
        merged = commands.merge_shift_overrides(
            calendar, now, now + timedelta(days=14), path=self.path)
        length = commands.describe_shift_length(merged, now)
        self.assertIn("Brea", length)
        self.assertIn("9:30 AM", length)
        self.assertIn("6:30 PM", length)
        self.assertNotIn("R345", length)
        self.assertNotIn("8:00 AM", length)

        later = commands.merge_shift_overrides(
            calendar, _at(2026, 10, 6, 7, 0), _at(2026, 10, 20, 7, 0), path=self.path)
        after = commands.describe_shift_length(later, _at(2026, 10, 6, 7, 0))
        self.assertIn("R345", after)
        self.assertNotIn("Brea", after)

        with mock.patch("commands.calendar_shift._plain_shifts_from_calendar", return_value=calendar):
            spoken = commands.speak_next_shift(now=now, path=self.path)
        self.assertIn("Shift at Brea", spoken)
        self.assertIn("9:30 AM", spoken)
        self.assertNotIn("R345", spoken)

        commands.clear_shift_override("clear my Monday shift", today=self.saturday, path=self.path)
        restored = commands.merge_shift_overrides(
            calendar, now, now + timedelta(days=14), path=self.path)
        again = commands.describe_shift_length(restored, now)
        self.assertIn("R345", again)
        self.assertNotIn("Brea", again)

    def test_saved_shift_still_answers_when_the_calendar_fails(self):
        now = _at(2026, 10, 3, 8, 0)
        commands.set_shift_override(
            "my shift Monday is 9:30 to 6:30 at Brea",
            today=self.saturday,
            path=self.path,
        )

        def broken(_now):
            return commands._CAL_FAILED

        with mock.patch("commands.calendar_shift._plain_shifts_from_calendar", side_effect=broken):
            spoken = commands.speak_next_shift(now=now, path=self.path)
        self.assertIn("Brea", spoken)
        self.assertNotIn("couldn't", spoken)

        with mock.patch("commands.calendar_shift._plain_shifts_from_calendar", side_effect=broken):
            quiet = commands.speak_next_shift(now=now, path=os.path.join(self.tmp.name, "missing.json"))
        self.assertEqual(quiet, commands._CAL_FAILED)

    def test_weekend_uses_the_saved_saturday(self):
        friday = _at(2026, 10, 2, 8, 0)
        saturday = _at(2026, 10, 3, 9, 0)
        calendar = [_shift("R345 - Promenade Temecula", saturday)]
        commands.set_shift_override(
            "my shift Saturday is 9:30 to 6:30 at Brea",
            today=datetime(2026, 10, 2).date(),
            path=self.path,
        )
        with mock.patch("commands.calendar_shift._load_plain_events", return_value=calendar):
            spoken = commands.speak_working_weekend(now=friday, path=self.path)
        self.assertIn("Brea", spoken)
        self.assertIn("Saturday", spoken)
        self.assertNotIn("R345", spoken)

    def test_brea_answer_prefers_the_saved_shift(self):
        now = _at(2026, 10, 3, 8, 0)
        monday = _at(2026, 10, 5, 8, 0)
        calendar = [_shift("Apple Brea", monday)]
        commands.set_shift_override(
            "my shift Monday is 9:30 to 6:30 at Brea",
            today=self.saturday,
            path=self.path,
        )
        with mock.patch("commands.money.brea_from_due", return_value=None):
            spoken = commands.speak_brea_start(now=now, path=self.path, events=calendar)
        self.assertIn("saved shift", spoken)
        self.assertIn("9:30 AM", spoken)
        self.assertNotIn("8:00 AM", spoken)


class TestLeaveTime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "shift-overrides.json")
        _Geocoder.addresses = []
        _Geocoder.fail = False
        _Directions.last_request = None
        _Directions.result = (1800.0, None)

    def _save_monday(self):
        commands.set_shift_override(
            "my shift Monday is 9:30 to 6:30 at Brea",
            today=datetime(2026, 10, 5).date(),
            path=self.path,
        )

    def test_mapkit_eta_sets_the_leave_time(self):
        self._save_monday()
        now = _at(2026, 10, 5, 7, 0)
        calls = []

        def fake(origin, destination, arrive_at):
            calls.append((origin, destination, arrive_at))
            return 30 * 60

        with mock.patch.object(leave_mod, "expected_travel_seconds", side_effect=fake):
            spoken = commands.speak_leave_time(now=now, path=self.path, events=[])
        self.assertEqual(
            spoken,
            "Leave by 8:45 AM for your 9:30 AM start at Brea. "
            "The drive is about 30 minutes, plus a buffer of 15 minutes.",
        )
        self.assertNotIn("estimate", spoken)
        self.assertEqual(calls[0][0], commands.HOME_ADDRESS)
        self.assertEqual(calls[0][1], commands.BREA_STORE_ADDRESS)
        self.assertEqual(calls[0][2], _at(2026, 10, 5, 9, 30))

    def test_override_wins_over_an_earlier_calendar_shift(self):
        self._save_monday()
        now = _at(2026, 10, 5, 7, 0)
        calendar = [_shift("R345 - Promenade Temecula", _at(2026, 10, 5, 8, 0))]
        with mock.patch.object(leave_mod, "expected_travel_seconds", return_value=30 * 60):
            spoken = commands.speak_leave_time(now=now, path=self.path, events=calendar)
        self.assertIn("9:30 AM", spoken)
        self.assertIn("8:45 AM", spoken)
        self.assertNotIn("R345", spoken)
        self.assertNotIn("8:00 AM", spoken)

    def test_fallback_says_it_is_an_estimate(self):
        self._save_monday()
        now = _at(2026, 10, 5, 7, 0)

        def boom(*_args, **_kwargs):
            raise AssertionError("leave time tried to run a process")

        with mock.patch.object(leave_mod, "expected_travel_seconds", return_value=None), \
                mock.patch.object(commands.subprocess, "run", boom):
            spoken = commands.speak_leave_time(now=now, path=self.path, events=[])
        self.assertEqual(
            spoken,
            "Leave by 8:40 AM for your 9:30 AM start at Brea. "
            "I'm using a typical drive of 35 minutes as an estimate, plus a buffer of 15 minutes.",
        )
        with mock.patch.object(leave_mod, "expected_travel_seconds", side_effect=RuntimeError("mapkit")):
            raised = commands.speak_leave_time(now=now, path=self.path, events=[])
        self.assertIn("estimate", raised)
        self.assertIn("8:40 AM", raised)

    def test_mocked_mapkit_drives_the_same_answer(self):
        self._save_monday()
        now = _at(2026, 10, 5, 7, 0)
        with mock.patch.dict("sys.modules", _frameworks()):
            seconds = travel_mod.expected_travel_seconds(
                commands.HOME_ADDRESS, commands.BREA_STORE_ADDRESS, _at(2026, 10, 5, 9, 30))
            spoken = commands.speak_leave_time(now=now, path=self.path, events=[])
        self.assertEqual(seconds, 1800.0)
        self.assertEqual(_Geocoder.addresses[:2], [commands.HOME_ADDRESS, commands.BREA_STORE_ADDRESS])
        self.assertEqual(_Directions.last_request.arrival, _at(2026, 10, 5, 9, 30).timestamp())
        self.assertEqual(_Directions.last_request.kind, 1)
        self.assertIn("8:45 AM", spoken)
        self.assertNotIn("estimate", spoken)

    def test_mocked_mapkit_failure_uses_the_estimate(self):
        self._save_monday()
        now = _at(2026, 10, 5, 7, 0)
        _Directions.result = (None, "no route")
        with mock.patch.dict("sys.modules", _frameworks()):
            seconds = travel_mod.expected_travel_seconds("Upland, CA", "Brea", now)
            spoken = commands.speak_leave_time(now=now, path=self.path, events=[])
        self.assertIsNone(seconds)
        self.assertIn("estimate", spoken)
        self.assertIn("8:40 AM", spoken)

    def test_a_coordinate_origin_is_not_geocoded(self):
        now = _at(2026, 10, 5, 12, 15)
        _Geocoder.addresses = []
        here = (33.916, -117.9)
        with mock.patch.dict("sys.modules", _frameworks()):
            seconds = travel_mod.expected_travel_seconds(
                here, commands.BREA_STORE_ADDRESS, now, depart=True)
        self.assertEqual(seconds, 1800.0)
        self.assertEqual(_Geocoder.addresses, [commands.BREA_STORE_ADDRESS])
        self.assertNotIn("33.916", _Geocoder.addresses)
        self.assertEqual(_Directions.last_request.source.placemark.coord, here)
        self.assertEqual(_Directions.last_request.departure, now.timestamp())

    def test_depart_now_sets_the_departure_date(self):
        now = _at(2026, 10, 5, 12, 15)
        with mock.patch.dict("sys.modules", _frameworks()):
            seconds = travel_mod.expected_travel_seconds(
                commands.HOME_ADDRESS, commands.BREA_STORE_ADDRESS, now, depart=True)
        self.assertEqual(seconds, 1800.0)
        self.assertEqual(_Directions.last_request.departure, now.timestamp())
        self.assertFalse(hasattr(_Directions.last_request, "arrival"))
        self.assertEqual(_Directions.last_request.kind, 1)

    def test_missing_mapkit_returns_none(self):
        blocked = {
            "MapKit": None,
            "CoreLocation": None,
        }
        with mock.patch.dict("sys.modules", blocked):
            seconds = travel_mod.expected_travel_seconds("Upland, CA", "Brea", _at(2026, 10, 5, 9, 30))
        self.assertIsNone(seconds)

    def test_started_shift_and_no_shift_and_other_store(self):
        now = _at(2026, 10, 5, 10, 0)
        started = [_shift("Shift at Brea", _at(2026, 10, 5, 9, 30), place="Brea")]
        calls = []

        def fake(*_args, **_kwargs):
            calls.append(True)
            return 1800

        with mock.patch.object(leave_mod, "expected_travel_seconds", side_effect=fake):
            spoken = commands.speak_leave_time(now=now, path=self.path, events=started)
        self.assertIn("already started", spoken)
        self.assertEqual(calls, [])
        with mock.patch.object(leave_mod, "expected_travel_seconds", side_effect=fake):
            empty = commands.speak_leave_time(now=now, path=self.path, events=[])
        self.assertEqual(empty, "I don't see a shift to leave for.")
        other = [_shift("R345 - Promenade Temecula", _at(2026, 10, 6, 9, 0))]
        with mock.patch.object(leave_mod, "expected_travel_seconds", side_effect=fake):
            elsewhere = commands.speak_leave_time(now=now, path=self.path, events=other)
        self.assertIn("Temecula", elsewhere)
        self.assertIn("only have a drive time", elsewhere)
        self.assertNotIn("estimate", elsewhere)
        self.assertEqual(calls, [])

    def test_leave_does_not_touch_keychain_or_workjam(self):
        source = "\n".join([
            inspect.getsource(commands.shift_override),
            inspect.getsource(commands.leave),
            inspect.getsource(commands.travel),
        ]).lower()
        self.assertNotIn("app.workjam", source)
        self.assertNotIn("keychain_value", source)
        self.assertNotIn("get_secret", source)
        self.assertNotIn("import requests", source)
        self.assertNotIn("secrets_store", source)


class TestAllowlist(unittest.TestCase):
    def test_each_command_is_named_and_money_and_my_love_stay_off(self):
        phrases = {
            "my shift Monday is 9:30 to 6:30 at Brea": "shift_set",
            "clear my shift Monday": "shift_clear",
            "when should I leave for work": "info_leave",
            "when do I need to leave for Brea": "info_leave",
        }
        for phrase, key in phrases.items():
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertEqual(commands.bridge_allowed(phrase), key, phrase)
            self.assertIn(key, commands.BRIDGE_ALLOW)
        self.assertNotIn("info_messages", commands.BRIDGE_ALLOW)
        self.assertIsNone(commands.bridge_allowed("check my messages from My Love"))
        self.assertIsNone(commands.bridge_allowed("move $600 to Zoe"))
        self.assertIsNone(commands.bridge_allowed("confirm the transfer"))
        for item in ("shift_set", "shift_clear", "info_leave"):
            self.assertNotIn("*", item)
