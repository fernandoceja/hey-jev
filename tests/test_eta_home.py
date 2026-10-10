"""ETA home, and ETA by itself. MapKit and location are faked.

The home line is a temp file. Nothing here is a real street, and the reply
never includes that line.
"""
import io
import os
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

import commands
from commands import leave as leave_mod
from commands import travel as travel_mod
from mini_bar import submission

TZ = ZoneInfo("America/Los_Angeles")
STREET = "742 Evergreen Terrace, Springfield"
HERE = (33.92, -117.88)


def _at(hour, minute):
    return datetime(2026, 10, 5, hour, minute, tzinfo=TZ)


class TestEtaHomeRouting(unittest.TestCase):
    def test_home_and_bare_phrases_route_without_opening_an_app(self):
        home = (
            "ETA home",
            "ETA to home",
            "what's my ETA home",
            "what's my ETA to home",
            "what is my ETA home",
            "what is my ETA to home",
            "my ETA home",
            "my ETA to home",
            "home ETA",
            "my home ETA",
            "how long to get home",
            "how long will it take me to get home",
            "how long will it take to get home",
            "how long is my drive home",
            "how long is my drive to home",
            "how far am I from home",
            "What's my ETA home?",
            "ETA HOME",
            "please ETA home",
            "ETA to home please",
            "hey jev ETA home",
            "hey jev, ETA to home",
            "hey jev, what's my ETA home",
            "please hey jev how long to get home",
            "E.T.A. home",
            "E.T.A. to home",
            "e.t.a. home",
            "E. T. A. home",
            "home E.T.A.",
        )
        bare = (
            "ETA",
            "eta",
            "E.T.A.",
            "E.T.A",
            "E. T. A.",
            "what's my ETA",
            "what is my ETA",
            "my ETA",
            "What's my ETA?",
            "please ETA",
            "ETA please",
            "hey jev ETA",
            "hey jev, ETA",
            "hey jev, what's my ETA",
            "please hey jev my ETA",
        )
        for phrase in home:
            self.assertEqual(commands.route_before_api(phrase), "info_eta_home", phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
        for phrase in bare:
            self.assertEqual(commands.route_before_api(phrase), "info_eta_which", phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
        for key in ("info_eta_home", "info_eta_which", "info_eta_work"):
            self.assertNotIn(key, commands.BRIDGE_ALLOW, key)
            self.assertIn(key, commands.ZOE_ALLOW, key)
        self.assertEqual(len(commands.BRIDGE_ALLOW), 30)
        self.assertEqual(commands.route_before_api("ETA to work"), "info_eta_work")
        self.assertEqual(commands.route_before_api("ETA work"), "info_eta_work")
        self.assertEqual(commands.route_before_api("work ETA"), "info_eta_work")
        self.assertEqual(commands.route_before_api("open home"), "app_open")
        self.assertEqual(commands.route_before_api("open Home"), "app_open")
        self.assertEqual(commands.route_before_api("quit Home"), "app_quit")
        self.assertEqual(commands.route_before_api("open Maps"), "app_open")
        self.assertEqual(commands.route_before_api("when should I leave for work"), "info_leave")
        self.assertEqual(commands.route_before_api("how long until payday"), "info_payday")
        self.assertEqual(commands.speak_eta_choice(), "Work or home?")
        for phrase in (
            "what's my ETA to the airport",
            "how long is my drive to the store",
            "ETA homework",
            "eat a snack",
            "open ETA",
            "how long until summer",
            "home",
            "work",
        ):
            self.assertNotIn(
                commands.route_before_api(phrase),
                ("info_eta_home", "info_eta_which", "info_eta_work"),
                phrase,
            )

    def test_typed_field_and_pill_use_the_same_route(self):
        expected = {
            "ETA home": "info_eta_home",
            "  hey jev, ETA to home? ": "info_eta_home",
            "please how long to get home": "info_eta_home",
            "ETA": "info_eta_which",
            "E.T.A.": "info_eta_which",
            "work ETA": "info_eta_work",
        }
        for raw, key in expected.items():
            plan = submission(raw, "")
            self.assertEqual(plan["kind"], "run", raw)
            self.assertFalse(plan["reveal_main"], raw)
            self.assertEqual(plan["control"][0], "text", raw)
            self.assertEqual(commands.route_before_api(plan["control"][1]), key, raw)

    def test_the_action_is_wired_and_the_bridge_files_are_untouched(self):
        root = os.path.dirname(os.path.dirname(__file__))
        siri = open(os.path.join(root, "siri.py"), encoding="utf-8").read()
        bridge = open(os.path.join(root, "commands", "bridge.py"), encoding="utf-8").read()
        secrets = open(os.path.join(root, "secrets_store.py"), encoding="utf-8").read()
        self.assertIn('"info_eta_home": lambda _arg, _text: commands.speak_eta_home()', siri)
        self.assertIn('"info_eta_which": lambda _arg, _text: commands.speak_eta_choice()', siri)
        for key in ("info_eta_home", "info_eta_which"):
            self.assertNotIn(key, bridge, key)
        self.assertNotIn("home-address", secrets)
        self.assertNotIn("Evergreen", secrets)
        for dirpath, dirnames, files in os.walk(root):
            dirnames[:] = [name for name in dirnames if name != ".git"]
            self.assertNotIn("home-address.txt", files, dirpath)


class TestEtaHomeReply(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home_path = os.path.join(self.tmp.name, "home-address.txt")
        self.missing = os.path.join(self.tmp.name, "missing-home.txt")
        self.now = _at(21, 27)

    def _write_home(self, line=STREET):
        with open(self.home_path, "w", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def _speak(self, seconds=31 * 60, origin=HERE, locate=False, home_path=None, boom=False):
        calls = []

        def fake(start, destination, when, depart=False):
            calls.append((start, destination, when, depart))
            return seconds

        def refuse(*_args, **_kwargs):
            raise AssertionError("ETA home tried to run a process")

        if home_path is None:
            home_path = self.home_path
        out, err = io.StringIO(), io.StringIO()
        travel = mock.patch.object(leave_mod, "expected_travel_seconds", side_effect=fake)
        with travel, redirect_stdout(out), redirect_stderr(err):
            if boom:
                with mock.patch.object(commands.subprocess, "run", refuse):
                    spoken = commands.speak_eta_home(
                        now=self.now, home_path=home_path, origin=origin, locate=locate)
            else:
                spoken = commands.speak_eta_home(
                    now=self.now, home_path=home_path, origin=origin, locate=locate)
        self.logs = out.getvalue() + err.getvalue()
        return spoken, calls

    def test_the_file_is_one_line_outside_the_repo(self):
        self.assertTrue(commands.HOME_ADDRESS_PATH.endswith(
            "Library/Application Support/Hey Jev/home-address.txt"))
        self.assertEqual(commands.HOME_EXACT_HINT, "Set your home address to get an exact ETA.")
        missing, exact = commands.read_home_address(self.missing)
        self.assertEqual(missing, "Upland, CA")
        self.assertFalse(exact)
        self._write_home(STREET + "\nignore this line")
        found, exact = commands.read_home_address(self.home_path)
        self.assertEqual(found, STREET)
        self.assertTrue(exact)
        with open(self.home_path, "w", encoding="utf-8") as handle:
            handle.write("   \n")
        blank, exact = commands.read_home_address(self.home_path)
        self.assertEqual(blank, "Upland, CA")
        self.assertFalse(exact)

    def test_location_and_a_saved_home_match_the_example(self):
        self._write_home()
        spoken, calls = self._speak(boom=True)
        self.assertEqual(
            spoken,
            "About 31 minutes to get home right now. You'd get there around 9:58 PM.",
        )
        self.assertEqual(calls, [(HERE, STREET, self.now, True)])
        self.assertNotIn(STREET, spoken)
        self.assertNotIn("Evergreen", spoken)
        self.assertNotIn("Springfield", spoken)
        self.assertNotIn("33.92", spoken)
        self.assertNotIn(STREET, self.logs)
        self.assertNotIn("Evergreen", self.logs)
        self.assertNotIn(commands.HOME_EXACT_HINT, spoken)
        self.assertNotIn("Brea", spoken)
        self.assertNotIn("estimate", spoken)

    def test_no_location_starts_at_the_brea_store_and_says_so(self):
        self._write_home()
        spoken, calls = self._speak(origin=None, locate=False, boom=True)
        self.assertEqual(
            spoken,
            "About 31 minutes to get home right now. You'd get there around 9:58 PM. "
            "I'm starting from the Brea store, since I can't see where this Mac is.",
        )
        self.assertEqual(calls[0][0], commands.BREA_STORE_ADDRESS)
        self.assertEqual(calls[0][1], STREET)
        self.assertNotIn(STREET, spoken)
        self.assertNotIn("1016C", spoken)
        self.assertNotIn(commands.HOME_EXACT_HINT, spoken)

    def test_a_missing_file_uses_upland_and_says_to_set_it(self):
        spoken, calls = self._speak(home_path=self.missing, boom=True)
        self.assertEqual(
            spoken,
            "About 31 minutes to get home right now. You'd get there around 9:58 PM. "
            "Set your home address to get an exact ETA.",
        )
        self.assertEqual(calls[0][0], HERE)
        self.assertEqual(calls[0][1], "Upland, CA")
        self.assertNotIn("Evergreen", spoken)

    def test_no_location_and_no_file_says_both(self):
        spoken, calls = self._speak(origin=None, locate=False, home_path=self.missing)
        self.assertIn("Brea store", spoken)
        self.assertIn(commands.HOME_EXACT_HINT, spoken)
        self.assertEqual(calls[0][0], commands.BREA_STORE_ADDRESS)
        self.assertEqual(calls[0][1], commands.HOME_ADDRESS)
        self.assertNotIn("1016C", spoken)

    def test_mapkit_failure_uses_the_typical_drive(self):
        self._write_home()

        def refuse(*_args, **_kwargs):
            raise AssertionError("ETA home tried to run a process")

        with mock.patch.object(leave_mod, "expected_travel_seconds", return_value=None), \
                mock.patch.object(commands.subprocess, "run", refuse):
            spoken = commands.speak_eta_home(
                now=self.now, home_path=self.home_path, origin=HERE, locate=False)
        self.assertEqual(
            spoken,
            "About 35 minutes to get home right now. "
            "I'm using a typical drive of 35 minutes as an estimate. "
            "You'd get there around 10:02 PM.",
        )
        with mock.patch.object(leave_mod, "expected_travel_seconds", side_effect=RuntimeError(STREET)):
            raised = commands.speak_eta_home(
                now=self.now, home_path=self.home_path, origin=HERE, locate=False)
        self.assertIn("estimate", raised)
        self.assertIn("35 minutes", raised)
        self.assertNotIn(STREET, raised)
        self.assertNotIn("Evergreen", raised)

    def test_a_location_lookup_is_used_when_the_caller_does_not_pass_one(self):
        self._write_home()
        with mock.patch.object(leave_mod, "current_coordinate", return_value=HERE), \
                mock.patch.object(leave_mod, "expected_travel_seconds", return_value=31 * 60) as travel:
            spoken = commands.speak_eta_home(now=self.now, home_path=self.home_path)
        self.assertIn("9:58 PM", spoken)
        self.assertNotIn("Brea", spoken)
        self.assertEqual(travel.call_args.args[0], HERE)
        self.assertEqual(travel.call_args.args[1], STREET)
        with mock.patch.object(leave_mod, "current_coordinate", side_effect=RuntimeError("loc")), \
                mock.patch.object(leave_mod, "expected_travel_seconds", return_value=31 * 60) as travel:
            fallen = commands.speak_eta_home(now=self.now, home_path=self.home_path)
        self.assertIn("Brea store", fallen)
        self.assertEqual(travel.call_args.args[0], commands.BREA_STORE_ADDRESS)


class _Coord:
    def __init__(self, lat, lon):
        self.latitude = lat
        self.longitude = lon


class _Fix:
    def coordinate(self):
        return _Coord(33.92, -117.88)


class _Manager:
    @classmethod
    def alloc(cls):
        return cls()

    def init(self):
        return self

    @staticmethod
    def locationServicesEnabled():
        return True

    def location(self):
        return _Fix()


class _NoFix:
    started = False

    @classmethod
    def alloc(cls):
        return cls()

    def init(self):
        return self

    @staticmethod
    def locationServicesEnabled():
        return True

    def location(self):
        return None

    def startUpdatingLocation(self):
        _NoFix.started = True

    def stopUpdatingLocation(self):
        pass


class _Denied:
    @staticmethod
    def locationServicesEnabled():
        return True

    @staticmethod
    def authorizationStatus():
        return 2

    @classmethod
    def alloc(cls):
        raise AssertionError("a denied location should not start a manager")


def _core(manager):
    core = types.ModuleType("CoreLocation")
    core.CLLocationManager = manager
    return core


class TestCurrentLocation(unittest.TestCase):
    def test_a_cached_fix_is_a_coordinate_and_a_miss_is_none(self):
        with mock.patch.dict("sys.modules", {"CoreLocation": _core(_Manager)}):
            found = travel_mod.current_coordinate()
        self.assertEqual(found, HERE)
        with mock.patch.dict("sys.modules", {"CoreLocation": None}):
            self.assertIsNone(travel_mod.current_coordinate())
        with mock.patch.dict("sys.modules", {"CoreLocation": _core(_Denied)}):
            self.assertIsNone(travel_mod.current_coordinate())
        _NoFix.started = False
        with mock.patch.object(travel_mod, "LOCATION_WAIT_SECONDS", 0), \
                mock.patch.dict("sys.modules", {"CoreLocation": _core(_NoFix)}):
            self.assertIsNone(travel_mod.current_coordinate())
        self.assertTrue(_NoFix.started)
