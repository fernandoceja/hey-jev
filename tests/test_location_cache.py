"""A granted location fix has to reach ETA home without holding the turn.

CoreLocation is faked. The fix shows up only once the keeper pumps its run
loop, which is what a cold Wi-Fi positioning fix needs. Coordinates stay out
of the log and out of the reply. The home line is not a street.
"""
import io
import os
import tempfile
import threading
import time
import types
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

import commands
from commands import leave as leave_mod
from commands import travel as travel_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = ZoneInfo("America/Los_Angeles")
HOME_LINE = "HOME-LINE-NOT-A-STREET"
FRESH = (33.75, -117.91)
LATE = (33.81, -117.65)


class _Point:
    def __init__(self, lat, lon):
        self.latitude = lat
        self.longitude = lon

    def coordinate(self):
        return self


def _core(manager):
    core = types.ModuleType("CoreLocation")
    core.CLLocationManager = manager
    return core


def _quiet_keeper():
    travel_mod.reset_location_state()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        live = [
            thread for thread in threading.enumerate()
            if thread.name == "jev-location" and thread.is_alive()
        ]
        if not live:
            break
        for thread in live:
            thread.join(timeout=0.1)


class _Authorized:
    """Status is already granted. A fix exists only after the run loop pumps."""

    calls = []
    started = []

    @classmethod
    def alloc(cls):
        return cls()

    def init(self):
        return self

    @staticmethod
    def locationServicesEnabled():
        return True

    @staticmethod
    def authorizationStatus():
        return 3

    def location(self):
        return None

    def requestWhenInUseAuthorization(self):
        raise AssertionError("an authorized Mac should not be asked again")

    def requestAlwaysAuthorization(self):
        raise AssertionError("an authorized Mac should not be asked again")

    def startUpdatingLocation(self):
        _Authorized.started.append(threading.current_thread().name)

    def stopUpdatingLocation(self):
        pass


class TestWarmLocationCache(unittest.TestCase):
    def setUp(self):
        _quiet_keeper()
        _Authorized.calls = []
        _Authorized.started = []
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home_path = os.path.join(self.tmp.name, "home-address.txt")
        with open(self.home_path, "w", encoding="utf-8") as handle:
            handle.write(HOME_LINE + "\n")
        self.now = datetime(2026, 10, 5, 21, 27, tzinfo=TZ)

    def tearDown(self):
        _quiet_keeper()

    def test_a_pumped_fix_is_the_eta_origin_and_the_turn_does_not_wait_it_out(self):
        origins = []

        def fake_travel(start, destination, when, depart=False):
            origins.append((start, destination, when, depart))
            return 31 * 60

        def pump(_seconds):
            self.assertFalse(travel_mod.location_lookup_busy())
            self.assertEqual(threading.current_thread().name, "jev-location")
            travel_mod._on_locations(None, [_Point(*FRESH)])

        modules = {
            "CoreLocation": _core(_Authorized),
            "Foundation": types.ModuleType("Foundation"),
            "MapKit": types.ModuleType("MapKit"),
        }
        out = io.StringIO()
        started = time.monotonic()
        with mock.patch.object(travel_mod, "LOCATION_WAIT_SECONDS", 3), \
                mock.patch.object(travel_mod, "LOCATION_FIX_SECONDS", 8), \
                mock.patch.object(travel_mod, "_runloop_pump", pump), \
                mock.patch.dict("sys.modules", modules), \
                mock.patch.object(leave_mod, "expected_travel_seconds", side_effect=fake_travel), \
                redirect_stdout(out):
            spoken = commands.speak_eta_home(now=self.now, home_path=self.home_path)
        elapsed = time.monotonic() - started
        logs = out.getvalue()
        self.assertLess(elapsed, 1.5)
        self.assertLess(elapsed, 8)
        self.assertIn("  location: fresh fix", logs)
        self.assertNotIn("33.75", logs)
        self.assertNotIn("-117.91", logs)
        self.assertNotIn(HOME_LINE, logs)
        self.assertIn("About 31 minutes to get home right now.", spoken)
        self.assertNotIn("Brea store", spoken)
        self.assertNotIn("33.75", spoken)
        self.assertNotIn("-117.91", spoken)
        self.assertNotIn(HOME_LINE, spoken)
        self.assertEqual(origins[0][0], FRESH)
        self.assertEqual(origins[0][1], HOME_LINE)
        self.assertTrue(origins[0][3])
        self.assertEqual(_Authorized.started, ["jev-location"])

        out = io.StringIO()
        started = time.monotonic()
        with mock.patch.object(travel_mod, "LOCATION_WAIT_SECONDS", 3), \
                mock.patch.dict("sys.modules", modules), \
                mock.patch.object(leave_mod, "expected_travel_seconds", side_effect=fake_travel), \
                redirect_stdout(out):
            again = commands.speak_eta_home(now=self.now, home_path=self.home_path)
        self.assertLess(time.monotonic() - started, 0.4)
        self.assertIn("  location: cached fix", out.getvalue())
        self.assertNotIn("33.75", out.getvalue())
        self.assertNotIn("-117.91", out.getvalue())
        self.assertNotIn("Brea store", again)
        self.assertEqual(origins[1][0], FRESH)

    def test_a_fix_that_lands_after_the_fallback_is_cached_for_the_next_call(self):
        release = threading.Event()
        box = {}

        class Manager(_Authorized):
            def startUpdatingLocation(self):
                box["started"] = threading.current_thread().name

        def pump(seconds):
            time.sleep(min(seconds, 0.05))
            if release.is_set():
                travel_mod._on_locations(None, [_Point(*LATE)])

        modules = {"CoreLocation": _core(Manager)}
        out = io.StringIO()
        started = time.monotonic()
        with mock.patch.object(travel_mod, "LOCATION_WAIT_SECONDS", 0.3), \
                mock.patch.object(travel_mod, "LOCATION_FIX_SECONDS", 3), \
                mock.patch.object(travel_mod, "_runloop_pump", pump), \
                mock.patch.dict("sys.modules", modules), \
                redirect_stdout(out):
            missed = travel_mod.current_coordinate()
        self.assertIsNone(missed)
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertIn("  location: no fix, Brea store", out.getvalue())
        self.assertNotIn("33.81", out.getvalue())
        self.assertNotIn("-117.65", out.getvalue())
        release.set()
        deadline = time.monotonic() + 2
        while travel_mod._cached_pair() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(travel_mod._cached_pair(), LATE)

        out = io.StringIO()
        started = time.monotonic()
        with mock.patch.object(travel_mod, "LOCATION_WAIT_SECONDS", 3), \
                mock.patch.dict("sys.modules", modules), \
                redirect_stdout(out):
            found = travel_mod.current_coordinate()
        self.assertEqual(found, LATE)
        self.assertLess(time.monotonic() - started, 0.4)
        self.assertIn("  location: cached fix", out.getvalue())
        self.assertNotIn("33.81", out.getvalue())
        self.assertNotIn("-117.65", out.getvalue())
        self.assertEqual(box.get("started"), "jev-location")

    def test_no_fix_falls_back_to_brea_without_waiting_out_the_attempt(self):
        def pump(seconds):
            time.sleep(min(seconds, 0.05))

        def fake_travel(start, destination, when, depart=False):
            return 31 * 60

        modules = {
            "CoreLocation": _core(_Authorized),
            "Foundation": types.ModuleType("Foundation"),
        }
        out = io.StringIO()
        started = time.monotonic()
        with mock.patch.object(travel_mod, "LOCATION_WAIT_SECONDS", 0.25), \
                mock.patch.object(travel_mod, "LOCATION_FIX_SECONDS", 4), \
                mock.patch.object(travel_mod, "_runloop_pump", pump), \
                mock.patch.dict("sys.modules", modules), \
                mock.patch.object(leave_mod, "expected_travel_seconds", side_effect=fake_travel), \
                redirect_stdout(out):
            spoken = commands.speak_eta_home(now=self.now, home_path=self.home_path)
        elapsed = time.monotonic() - started
        logs = out.getvalue()
        self.assertLess(elapsed, 1.0)
        self.assertIn("  location: no fix, Brea store", logs)
        self.assertNotIn("33.75", logs)
        self.assertNotIn(HOME_LINE, logs)
        self.assertNotIn(HOME_LINE, spoken)
        self.assertIn(
            "I'm starting from the Brea store, since I can't see where this Mac is.",
            spoken,
        )
        self.assertNotIn("estimate", spoken)
        self.assertTrue(_Authorized.started)

    def test_a_delegate_error_is_not_logged(self):
        out = io.StringIO()
        with redirect_stdout(out):
            travel_mod._on_location_error(None, "33.75,-117.91")
            travel_mod._on_locations(None, [_Point(0.0, 0.0)])
        self.assertEqual(out.getvalue(), "")
        self.assertIsNone(travel_mod._cached_pair())

    def test_the_keeper_does_not_start_off_mac(self):
        before = {
            thread.name for thread in threading.enumerate() if thread.is_alive()
        }
        with mock.patch.object(travel_mod.sys, "platform", "linux"):
            self.assertIsNone(travel_mod.start_location_keeper())
        after = {
            thread.name for thread in threading.enumerate() if thread.is_alive()
        }
        self.assertNotIn("jev-location", after - before)

    def test_siri_starts_the_keeper_with_the_assistant(self):
        siri = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        self.assertLess(
            siri.index("start_hazard_thread"),
            siri.index("start_location_keeper"),
        )
