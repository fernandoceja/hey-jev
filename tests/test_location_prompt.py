"""A macOS location panel must not freeze the command turn.

CoreLocation is faked. The permission call blocks until this test releases
it. The home line is not a street.
"""
import os
import tempfile
import threading
import time
import types
import unittest
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

import commands
from commands import hazards as hazard_mod
from commands import leave as leave_mod
from commands import travel as travel_mod

TZ = ZoneInfo("America/Los_Angeles")
HOME_LINE = "HOME-LINE-NOT-A-STREET"
# Longer than a mistaken full wait, short enough that the suite stays quick.
WAIT = 1.0
FAST = 0.45


class _Book:
    def remember(self, path, kind):
        self.remembered = (path, kind)


def _frameworks(manager, geocoder):
    core = types.ModuleType("CoreLocation")
    core.CLLocationManager = manager
    core.CLGeocoder = geocoder
    return {
        "CoreLocation": core,
        "MapKit": types.ModuleType("MapKit"),
        "Foundation": types.ModuleType("Foundation"),
    }


class TestLocationPrompt(unittest.TestCase):
    def setUp(self):
        travel_mod.reset_location_state()
        with hazard_mod._geocode_lock:
            hazard_mod._geocode_running = False
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home_path = os.path.join(self.tmp.name, "home-address.txt")
        with open(self.home_path, "w", encoding="utf-8") as handle:
            handle.write(HOME_LINE + "\n")
        self.captures = os.path.join(self.tmp.name, "captures")
        self.hang = threading.Event()
        self.asked = threading.Event()
        self.geocode_entered = threading.Event()
        self.ask_threads = []
        self.geocode_calls = []
        self.started_updates = []
        self.now = datetime(2026, 10, 5, 21, 27, tzinfo=TZ)
        hang = self.hang
        asked = self.asked
        geocode_entered = self.geocode_entered
        ask_threads = self.ask_threads
        geocode_calls = self.geocode_calls
        started_updates = self.started_updates

        class Manager:
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
                return 0

            def location(self):
                return None

            def requestWhenInUseAuthorization(self):
                ask_threads.append(threading.current_thread().name)
                asked.set()
                hang.wait()

            def startUpdatingLocation(self):
                started_updates.append(threading.current_thread().name)

            def stopUpdatingLocation(self):
                pass

        class Geocoder:
            @classmethod
            def alloc(cls):
                return cls()

            def init(self):
                return self

            def geocodeAddressString_completionHandler_(self, address, handler):
                geocode_calls.append(address)
                geocode_entered.set()
                hang.wait()
                handler(None, None)

        self.modules = _frameworks(Manager, Geocoder)

    def tearDown(self):
        self.hang.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            live = [
                thread for thread in threading.enumerate()
                if thread.name in ("jev-location", "jev-geocode") and thread.is_alive()
            ]
            if not live:
                break
            for thread in live:
                thread.join(timeout=0.2)
        travel_mod.reset_location_state()
        with hazard_mod._geocode_lock:
            hazard_mod._geocode_running = False

    def _join_location_threads(self):
        for thread in threading.enumerate():
            if thread.name == "jev-location" and thread.is_alive():
                thread.join(timeout=2)

    def test_a_hanging_prompt_lets_queued_commands_run_and_falls_back(self):
        busy = threading.Lock()
        results = {}
        origins = []
        order = []

        def turn(name, fn):
            with busy:
                order.append(name)
                results[name] = fn()

        def fake_travel(start, destination, when, depart=False):
            origins.append((start, destination, when, depart))
            return 31 * 60

        def eta():
            turn("eta", lambda: commands.speak_eta_home(
                now=self.now, home_path=self.home_path))

        book = _Book()

        def shot():
            turn("shot", lambda: commands.take_screenshot(
                folder=self.captures,
                run=lambda *_args, **_kwargs: None,
                book=book,
            ))

        with mock.patch.object(travel_mod, "LOCATION_WAIT_SECONDS", WAIT), \
                mock.patch.dict("sys.modules", self.modules), \
                mock.patch.object(leave_mod, "expected_travel_seconds", side_effect=fake_travel):
            worker = threading.Thread(target=eta, name="jev-command-worker")
            worker.start()
            self.assertTrue(self.asked.wait(2), "the location panel did not open")
            self.assertEqual(self.ask_threads, ["jev-location"])
            self.assertNotIn("jev-command-worker", self.ask_threads)
            self.assertNotIn(threading.main_thread().name, self.ask_threads)
            self.assertFalse(self.hang.is_set())

            # The saved line still places when something other than CoreLocation does it.
            placed = hazard_mod.home_point(
                self.home_path, geocode=lambda _address: (34.2, -117.7), locate=True)
            self.assertEqual(placed, (34.2, -117.7))

            # MapKit and the hazard geocoder must not enter CoreLocation while it is open.
            probed = {}

            def upland():
                with mock.patch.object(hazard_mod.sys, "platform", "darwin"):
                    probed["point"] = hazard_mod.home_point(self.home_path, locate=True)

            def mapkit():
                probed["seconds"] = travel_mod.expected_travel_seconds(
                    "Upland, CA", commands.BREA_STORE_ADDRESS, self.now)

            hazard = threading.Thread(target=upland, name="jev-hazard-probe")
            mapper = threading.Thread(target=mapkit, name="jev-mapkit-probe")
            hazard.start()
            mapper.start()
            hazard.join(1)
            mapper.join(1)
            self.assertFalse(hazard.is_alive(), "hazard home point waited on the location panel")
            self.assertFalse(mapper.is_alive(), "MapKit waited on the location panel")
            self.assertEqual(probed["point"], (commands.UPLAND_LAT, commands.UPLAND_LON))
            self.assertIsNone(probed["seconds"])
            self.assertEqual(self.geocode_calls, [])

            queued = threading.Thread(target=shot, name="jev-command-worker")
            queued.start()
            queued.join(3)
            worker.join(3)
            self.assertFalse(queued.is_alive(), "the screenshot was still waiting on the location panel")
            self.assertFalse(worker.is_alive(), "ETA home was still inside the location panel")
            self.assertFalse(self.hang.is_set())
            self.assertEqual(order, ["eta", "shot"])
            self.assertIn(
                "I'm starting from the Brea store, since I can't see where this Mac is.",
                results["eta"],
            )
            self.assertNotIn("estimate", results["eta"])
            self.assertNotIn(HOME_LINE, results["eta"])
            self.assertNotIn("HOME-LINE", results["eta"])
            self.assertEqual(origins[0][0], commands.BREA_STORE_ADDRESS)
            self.assertEqual(origins[0][1], HOME_LINE)
            self.assertTrue(origins[0][3])
            self.assertIn("Saved a full screen screenshot", results["shot"])
            self.assertEqual(book.remembered[1], "screenshot")
            self.assertEqual(self.ask_threads, ["jev-location"])
            self.assertEqual(self.started_updates, [])

            started = time.monotonic()
            again = commands.speak_eta_home(now=self.now, home_path=self.home_path)
            self.assertLess(time.monotonic() - started, FAST)
            self.assertIn("Brea store", again)
            self.assertNotIn(HOME_LINE, again)
            self.assertEqual(self.ask_threads, ["jev-location"])

        self.hang.set()
        self._join_location_threads()
        self.asked.clear()
        with mock.patch.object(travel_mod, "LOCATION_WAIT_SECONDS", WAIT), \
                mock.patch.dict("sys.modules", self.modules), \
                mock.patch.object(leave_mod, "expected_travel_seconds", side_effect=fake_travel):
            started = time.monotonic()
            third = commands.speak_eta_home(now=self.now, home_path=self.home_path)
            self.assertLess(time.monotonic() - started, FAST)
        self.assertIn("Brea store", third)
        self.assertNotIn(HOME_LINE, third)
        self.assertEqual(self.ask_threads, ["jev-location"])
        self.assertFalse(self.asked.is_set())
        self.assertEqual(self.started_updates, [])

    def test_a_hanging_home_geocode_uses_upland_and_the_next_command_runs(self):
        busy = threading.Lock()
        results = {}
        order = []

        def turn(name, fn):
            with busy:
                order.append(name)
                results[name] = fn()

        def hazards():
            def run():
                with mock.patch.object(hazard_mod.sys, "platform", "darwin"), \
                        mock.patch.object(hazard_mod, "GEOCODE_WAIT_SECONDS", 0.3):
                    return hazard_mod.home_point(self.home_path, locate=True)
            turn("home", run)

        def clock():
            turn("time", commands.speak_time)

        with mock.patch.dict("sys.modules", self.modules):
            worker = threading.Thread(target=hazards, name="jev-command-worker")
            worker.start()
            self.assertTrue(self.geocode_entered.wait(2), "the geocoder did not run")
            self.assertEqual(self.geocode_calls, [HOME_LINE])
            queued = threading.Thread(target=clock, name="jev-command-worker")
            queued.start()
            queued.join(2)
            worker.join(2)
        self.assertFalse(self.hang.is_set())
        self.assertFalse(queued.is_alive(), "the clock waited on the geocoder")
        self.assertFalse(worker.is_alive(), "the home point waited on the geocoder")
        self.assertEqual(order, ["home", "time"])
        self.assertEqual(results["home"], (commands.UPLAND_LAT, commands.UPLAND_LON))
        self.assertTrue(results["time"].startswith("It's "))
        self.assertNotIn(HOME_LINE, results["time"])
        self.assertEqual(self.ask_threads, [])
