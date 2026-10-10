"""Hazard watch. Network, Keychain, and MapKit are faked. No street address."""
import hashlib
import hmac
import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

import commands
from commands import bridge
from commands import hazards as hazard_mod
from commands.stt import is_hotword_echo
from mini_bar import submission

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = (commands.UPLAND_LAT, commands.UPLAND_LON)
NOW = datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc)
NOW_TS = NOW.timestamp()
SECRET = "super-secret-map-key"
HOME_LINE = "HOME-LINE-NOT-A-STREET"
BRIDGE_NOW = 1_700_000_000
BRIDGE_SECRET = "bridge-test-secret"
HAZARD_KEYS = (
    "info_hazards",
    "info_hazards_fires",
    "info_hazards_quakes",
    "hazard_alerts_on",
    "hazard_alerts_off",
)
SHAPE = ("type", "time", "lat", "lon", "magnitude", "brightness", "distance_mi", "source")
EXAMPLE = "No fires within 25 miles. One magnitude 3.8 quake 31 miles east, 2 hours ago."


def _sign(cmd, ts, nonce, secret=BRIDGE_SECRET):
    payload = "{0}|{1}|{2}".format(cmd, ts, nonce).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _quake(lat, lon, mag, when_ts, ident):
    return {
        "type": "Feature",
        "id": ident,
        "properties": {
            "mag": mag,
            "time": int(when_ts * 1000),
            "place": "somewhere public",
        },
        "geometry": {"type": "Point", "coordinates": [lon, lat, 8.0]},
    }


def _fire(lat, lon, when_ts, bright="341.2", ident=None):
    moment = datetime.fromtimestamp(when_ts, timezone.utc)
    row = {
        "latitude": "{0:.5f}".format(lat),
        "longitude": "{0:.5f}".format(lon),
        "bright_ti4": bright,
        "acq_date": moment.strftime("%Y-%m-%d"),
        "acq_time": moment.strftime("%H%M"),
        "confidence": "nominal",
    }
    if ident:
        row["id"] = ident
    return row


def _east(miles):
    return hazard_mod.move_miles(HOME[0], HOME[1], miles, 90)


def _north(miles):
    return hazard_mod.move_miles(HOME[0], HOME[1], miles, 0)


class TestRouting(unittest.TestCase):
    def test_voice_phrases_and_the_ones_that_must_stay_put(self):
        fires = (
            "any fires near me",
            "any fire near me",
            "fires near me",
            "any wildfires near me",
            "any wildfire near me",
            "are there any fires near me",
            "are there fires nearby",
            "any fires around me",
            "any fires around here",
            "check for fires",
            "check for wildfires",
            "fire check",
            "Any fires near me?",
            "please any fires near me",
            "any fires near me please",
            "hey jev any fires near me",
            "hey jev, any fires near me",
            "hey jev, please check for fires",
        )
        quakes = (
            "any earthquakes near me",
            "any earthquake near me",
            "earthquakes near me",
            "any quakes near me",
            "any quake nearby",
            "are there any earthquakes near me",
            "check for earthquakes",
            "check for quakes",
            "earthquake check",
            "quake check",
            "please any earthquakes near me",
            "hey jev, any earthquakes near me",
        )
        both = (
            "hazard check",
            "hazard watch",
            "any hazards near me",
            "any hazard near me",
            "hazards near me",
            "are there any hazards near me",
            "check hazards",
            "check for hazards",
            "check hazard",
            "Hazard check.",
            "please hazard check",
            "hey jev, any hazards near me",
            "hey jev hazard check",
        )
        on = (
            "turn on hazard alerts",
            "enable hazard alerts",
            "hazard alerts on",
            "please turn on hazard alerts",
            "turn on hazard alerts please",
            "hey jev, turn on hazard alerts",
        )
        off = (
            "turn off hazard alerts",
            "disable hazard alerts",
            "hazard alerts off",
            "please turn off hazard alerts",
            "hey jev, turn off hazard alerts",
        )
        expected = (
            (fires, "info_hazards_fires"),
            (quakes, "info_hazards_quakes"),
            (both, "info_hazards"),
            (on, "hazard_alerts_on"),
            (off, "hazard_alerts_off"),
        )
        for phrases, key in expected:
            for phrase in phrases:
                self.assertEqual(commands.route_before_api(phrase), key, phrase)
                self.assertIsNone(commands.bridge_allowed(phrase), phrase)
                self.assertFalse(is_hotword_echo(phrase), phrase)
        for key in HAZARD_KEYS:
            self.assertNotIn(key, commands.BRIDGE_ALLOW, key)
        self.assertEqual(len(commands.BRIDGE_ALLOW), 30)
        self.assertFalse(commands.HAZARD_ALERTS_ENABLED)
        self.assertEqual(commands.HAZARD_FIRE_MILES, 25)
        self.assertEqual(commands.HAZARD_QUAKE_MILES, 50)
        self.assertEqual(commands.HAZARD_QUAKE_MIN_MAG, 3.5)
        self.assertEqual(commands.HAZARD_WINDOW_HOURS, 24)
        self.assertEqual(commands.HAZARD_CACHE_TTL_SECONDS, 15 * 60)
        kept = {
            "what's the weather": "info_weather",
            "any new orders": "site_open",
            "any reminders today": "info_payday_check",
            "turn on leave reminders": "leave_reminders_on",
            "turn off leave reminders": "leave_reminders_off",
            "when should I leave for work": "info_leave",
            "open home": "app_open",
        }
        for phrase, key in kept.items():
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
        for phrase in (
            "any fires in the news",
            "earthquakes in japan",
            "hazard",
            "fire",
            "check",
            "any fires near me and what's the weather",
            "turn on hazard alerts then mute",
        ):
            self.assertNotIn(commands.route_before_api(phrase), HAZARD_KEYS, phrase)
        self.assertIn("fires and earthquakes", commands.speak_help())

    def test_the_typed_field_uses_the_same_route(self):
        plan = submission("hazard check", "")
        self.assertEqual(plan["kind"], "run")
        self.assertEqual(commands.route_before_api(plan["control"][1]), "info_hazards")
        plan = submission("  hey jev, any fires near me? ", "")
        self.assertEqual(commands.route_before_api(plan["control"][1]), "info_hazards_fires")

    def test_siri_wires_the_actions_and_the_bridge_files_are_untouched(self):
        siri = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        bridge_source = open(os.path.join(ROOT, "commands", "bridge.py"), encoding="utf-8").read()
        secrets = open(os.path.join(ROOT, "secrets_store.py"), encoding="utf-8").read()
        hazards = open(os.path.join(ROOT, "commands", "hazards.py"), encoding="utf-8").read()
        readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
        self.assertIn('"info_hazards": lambda _arg, _text: commands.speak_hazards()', siri)
        self.assertIn('"info_hazards_fires": lambda _arg, _text: commands.speak_fires()', siri)
        self.assertIn('"info_hazards_quakes": lambda _arg, _text: commands.speak_quakes()', siri)
        self.assertIn('"hazard_alerts_on": lambda _arg, _text: commands.set_hazard_alerts(True)', siri)
        self.assertIn('"hazard_alerts_off": lambda _arg, _text: commands.set_hazard_alerts(False)', siri)
        self.assertIn("start_hazard_thread", siri)
        for key in HAZARD_KEYS:
            self.assertNotIn(key, bridge_source, key)
            self.assertNotIn(key, secrets, key)
        for needle in ("FIRMS_MAP_KEY", "firms.modaps", "USGS_DAY_FEED", SECRET, HOME_LINE):
            self.assertNotIn(needle, secrets, needle)
            self.assertNotIn(needle, bridge_source, needle)
        self.assertNotIn(SECRET, hazards)
        self.assertNotIn(SECRET, readme)
        self.assertNotIn(HOME_LINE, hazards)
        self.assertIn("FIRMS_MAP_KEY", readme)
        self.assertIn(
            "security add-generic-password -U -a FIRMS_MAP_KEY -s com.jevsiri.keys",
            readme,
        )
        self.assertNotIn("socket.socket", hazards)
        self.assertNotIn(".listen(", hazards)
        self.assertNotIn(".bind(", hazards)
        self.assertNotIn("os.getenv", hazards)
        self.assertNotIn("get_secret", hazards)
        self.assertIn("keychain_value", hazards)
        self.assertNotIn("\nimport requests\n", "\n" + hazards)


class TestNormalizeAndFilter(unittest.TestCase):
    def test_usgs_and_firms_share_one_shape(self):
        lat, lon = _east(31)
        feature = _quake(lat, lon, 3.8, NOW_TS - 7200, "ci38001")
        event = hazard_mod.normalize_quake(feature, HOME)
        for field in SHAPE:
            self.assertIn(field, event, field)
        self.assertEqual(event["type"], "earthquake")
        self.assertEqual(event["source"], "usgs")
        self.assertEqual(event["id"], "ci38001")
        self.assertIsNone(event["brightness"])
        self.assertEqual(event["magnitude"], 3.8)
        self.assertAlmostEqual(event["time"], NOW_TS - 7200, delta=1)
        self.assertAlmostEqual(event["distance_mi"], 31, delta=0.05)
        self.assertEqual(event["direction"], "east")
        self.assertAlmostEqual(event["lat"], lat, places=4)
        self.assertAlmostEqual(event["lon"], lon, places=4)

        flat, flon = _north(12)
        fire = hazard_mod.normalize_fire(_fire(flat, flon, NOW_TS - 3600, ident="f12"), HOME)
        for field in SHAPE:
            self.assertIn(field, fire, field)
        self.assertEqual(fire["type"], "fire")
        self.assertEqual(fire["source"], "nasa_firms")
        self.assertEqual(fire["id"], "f12")
        self.assertIsNone(fire["magnitude"])
        self.assertAlmostEqual(fire["brightness"], 341.2)
        self.assertAlmostEqual(fire["distance_mi"], 12, delta=0.05)
        self.assertEqual(fire["direction"], "north")

        geo = {
            "type": "Feature",
            "id": "geo-fire",
            "geometry": {"type": "Point", "coordinates": [flon, flat]},
            "properties": {
                "brightness": 300,
                "acq_date": "2026-10-10",
                "acq_time": "1500",
            },
        }
        other = hazard_mod.normalize_fire(geo, HOME)
        self.assertEqual(other["type"], "fire")
        self.assertEqual(other["source"], "nasa_firms")
        self.assertEqual(other["id"], "geo-fire")
        self.assertAlmostEqual(other["brightness"], 300.0)
        self.assertIsNone(hazard_mod.normalize_quake({"type": "Feature"}, HOME))
        self.assertIsNone(hazard_mod.normalize_fire({"latitude": "nope"}, HOME))

    def test_distance_magnitude_and_age_limits(self):
        def row(**kwargs):
            event = {
                "type": "fire",
                "time": NOW_TS - 3600,
                "lat": HOME[0],
                "lon": HOME[1],
                "magnitude": None,
                "brightness": 10,
                "distance_mi": 10,
                "direction": "north",
                "source": "nasa_firms",
                "id": "x",
            }
            event.update(kwargs)
            return event

        self.assertTrue(hazard_mod.passes_limits(row(distance_mi=25), NOW))
        self.assertFalse(hazard_mod.passes_limits(row(distance_mi=25.01), NOW))
        self.assertTrue(hazard_mod.passes_limits(row(
            type="earthquake", source="usgs", magnitude=3.5, distance_mi=50, brightness=None,
        ), NOW))
        self.assertFalse(hazard_mod.passes_limits(row(
            type="earthquake", source="usgs", magnitude=3.5, distance_mi=50.01, brightness=None,
        ), NOW))
        self.assertFalse(hazard_mod.passes_limits(row(
            type="earthquake", source="usgs", magnitude=3.49, distance_mi=1, brightness=None,
        ), NOW))
        self.assertTrue(hazard_mod.passes_limits(row(time=NOW_TS - 24 * 3600), NOW))
        self.assertFalse(hazard_mod.passes_limits(row(time=NOW_TS - 24 * 3600 - 1), NOW))
        near = hazard_mod.normalize_fire(_fire(*_north(10), NOW_TS - 1800), HOME)
        far = hazard_mod.normalize_fire(_fire(*_north(40), NOW_TS - 1800), HOME)
        self.assertTrue(hazard_mod.passes_limits(near, NOW))
        self.assertFalse(hazard_mod.passes_limits(far, NOW))
        self.assertGreater(far["distance_mi"], commands.HAZARD_FIRE_MILES)
        small = hazard_mod.normalize_quake(_quake(*_east(10), 3.4, NOW_TS - 600, "small"), HOME)
        self.assertFalse(hazard_mod.passes_limits(small, NOW))
        old = hazard_mod.normalize_quake(
            _quake(*_east(8), 4.2, NOW_TS - 25 * 3600, "old"), HOME)
        self.assertFalse(hazard_mod.passes_limits(old, NOW))


class TestSpeechCacheAndKey(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = os.path.join(self.tmp.name, "hazard-cache.json")
        self.alerts = os.path.join(self.tmp.name, "hazard-alerts.json")
        self.home_file = os.path.join(self.tmp.name, "home-address.txt")

    def _feed(self):
        lat, lon = _east(31)
        far_lat, far_lon = _north(80)
        old_lat, old_lon = _north(8)
        fire_lat, fire_lon = _north(40)
        features = [
            _quake(lat, lon, 3.8, NOW_TS - 7200, "ci38001"),
            _quake(*_east(5), 2.1, NOW_TS - 1000, "too-small"),
            _quake(far_lat, far_lon, 5.1, NOW_TS - 1000, "too-far"),
            _quake(old_lat, old_lon, 4.4, NOW_TS - 25 * 3600, "too-old"),
        ]
        fires = [_fire(fire_lat, fire_lon, NOW_TS - 4000, ident="far-fire")]
        return {"type": "FeatureCollection", "features": features}, fires

    def _get(self, quakes, fires, calls, secret=SECRET):
        def get(url, timeout):
            calls.append(url)
            self.assertEqual(timeout, commands.HAZARD_TIMEOUT)
            if "earthquake.usgs.gov" in url:
                self.assertNotIn(secret, url)
                return quakes
            if "firms.modaps.eosdis.nasa.gov" in url:
                return fires
            raise AssertionError(url)
        return get

    def _speak(self, get, read_key, now=None, **extra):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            spoken = commands.speak_hazards(
                now=NOW if now is None else now,
                home=HOME,
                locate=False,
                cache_path=self.cache,
                read_key=read_key,
                get=get,
                **extra,
            )
        self.logs = out.getvalue() + err.getvalue()
        return spoken

    def test_the_example_sentence_filters_and_caches(self):
        quakes, fires = self._feed()
        calls = []
        spoken = self._speak(self._get(quakes, fires, calls), lambda: SECRET)
        self.assertEqual(spoken, EXAMPLE)
        self.assertNotIn(SECRET, spoken)
        self.assertNotIn(SECRET, self.logs)
        self.assertNotIn("34.0975", spoken)
        cached = open(self.cache, encoding="utf-8").read()
        self.assertNotIn(SECRET, cached)
        self.assertNotIn(HOME_LINE, cached)
        mode = stat.S_IMODE(os.stat(self.cache).st_mode)
        self.assertEqual(mode, 0o600)
        firms = [url for url in calls if "firms" in url]
        usgs = [url for url in calls if "usgs" in url]
        self.assertEqual(len(usgs), 1)
        self.assertEqual(len(firms), 1)
        self.assertIn(SECRET, firms[0])
        again = self._speak(self._get(quakes, fires, calls), lambda: SECRET)
        self.assertEqual(again, EXAMPLE)
        self.assertEqual(len(calls), 2)

        later = NOW + timedelta(seconds=commands.HAZARD_CACHE_TTL_SECONDS + 1)
        self._speak(self._get(quakes, fires, calls), lambda: SECRET, now=later)
        self.assertEqual(len(calls), 4)

    def test_a_missing_key_skips_fires_and_still_says_the_quake(self):
        quakes, fires = self._feed()
        calls = []

        def get(url, timeout):
            calls.append(url)
            if "firms" in url:
                raise AssertionError("FIRMS was called without a key")
            return quakes

        spoken = self._speak(get, lambda: None)
        self.assertEqual(
            spoken,
            "I can't check fires yet. Add a FIRMS map key to the Keychain, "
            "account FIRMS_MAP_KEY. One magnitude 3.8 quake 31 miles east, 2 hours ago.",
        )
        self.assertNotIn("No fires within 25 miles", spoken)
        self.assertNotIn(SECRET, spoken)
        self.assertEqual(len(calls), 1)
        self.assertIn("usgs", calls[0])
        again = self._speak(get, lambda: None)
        self.assertEqual(again, spoken)
        self.assertEqual(len(calls), 1)
        quake_only = commands.speak_quakes(
            now=NOW, home=HOME, locate=False, cache_path=self.cache,
            read_key=lambda: None, get=get,
        )
        self.assertEqual(quake_only, "One magnitude 3.8 quake 31 miles east, 2 hours ago.")
        self.assertNotIn("FIRMS", quake_only)
        self.assertEqual(len(calls), 1)

    def test_a_new_key_fetches_fires_without_refetching_quakes(self):
        quakes, fires = self._feed()
        held = {"key": None}
        calls = []
        close = _fire(*_north(8), NOW_TS - 5400, ident="close-fire")

        def get(url, timeout):
            calls.append(url)
            if "usgs" in url:
                return quakes
            return [close]

        def read_key():
            return held["key"]

        first = self._speak(get, read_key)
        self.assertIn("I can't check fires yet", first)
        self.assertEqual(len(calls), 1)
        held["key"] = SECRET
        second = self._speak(get, read_key)
        self.assertEqual(
            second,
            "One fire 8 miles north, 2 hours ago. "
            "One magnitude 3.8 quake 31 miles east, 2 hours ago.",
        )
        self.assertEqual(len([url for url in calls if "usgs" in url]), 1)
        self.assertEqual(len([url for url in calls if "firms" in url]), 1)
        self.assertNotIn(SECRET, second)
        cached = open(self.cache, encoding="utf-8").read()
        self.assertNotIn(SECRET, cached)

    def test_a_firms_failure_does_not_leak_the_key(self):
        quakes, _fires = self._feed()
        calls = []

        def get(url, timeout):
            calls.append(url)
            if "firms" in url:
                raise RuntimeError("request failed for " + url)
            return quakes

        spoken = self._speak(get, lambda: SECRET)
        self.assertIn("I couldn't check fires just now.", spoken)
        self.assertIn("One magnitude 3.8 quake 31 miles east", spoken)
        self.assertNotIn(SECRET, spoken)
        self.assertNotIn(SECRET, self.logs)
        self.assertNotIn(SECRET, open(self.cache, encoding="utf-8").read())
        self.assertIn("hazards: RuntimeError", self.logs)

    def test_the_key_comes_from_the_keychain_and_not_the_environment(self):
        # A stand-in module so this test never imports the real Keychain helper,
        # which loads dotenv. CI does not install that package.
        import sys
        import types
        fake = types.ModuleType("secrets_store")
        seen = []

        def keychain_value(name):
            seen.append(name)
            return "  " + SECRET + "  "

        fake.keychain_value = keychain_value

        def refuse_env(*_args, **_kwargs):
            raise AssertionError("the FIRMS key must not be read from the environment")

        with mock.patch.dict(sys.modules, {"secrets_store": fake}), \
                mock.patch("os.getenv", side_effect=refuse_env):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                found = hazard_mod.default_read_key()
        self.assertEqual(found, SECRET)
        self.assertEqual(seen, [commands.FIRMS_MAP_KEY_ACCOUNT])
        self.assertNotIn(SECRET, out.getvalue() + err.getvalue())
        fake.keychain_value = lambda _name: None
        with mock.patch.dict(sys.modules, {"secrets_store": fake}):
            self.assertIsNone(hazard_mod.default_read_key())

        def broken(_name):
            raise OSError("down")

        fake.keychain_value = broken
        with mock.patch.dict(sys.modules, {"secrets_store": fake}):
            self.assertIsNone(hazard_mod.default_read_key())

    def test_a_saved_home_line_is_a_point_and_is_not_stored(self):
        with open(self.home_file, "w", encoding="utf-8") as handle:
            handle.write(HOME_LINE + "\n")
        seen = []

        def geocode(address):
            seen.append(address)
            return (34.2, -117.7)

        point = hazard_mod.home_point(self.home_file, geocode=geocode, locate=True)
        self.assertEqual(seen, [HOME_LINE])
        self.assertEqual(point, (34.2, -117.7))
        fallback = hazard_mod.home_point(
            self.home_file,
            geocode=lambda _address: (_ for _ in ()).throw(RuntimeError("no")),
            locate=True,
        )
        self.assertEqual(fallback, HOME)
        untouched = hazard_mod.home_point(self.home_file, locate=False)
        self.assertEqual(untouched, HOME)
        # 22 miles north of the geocoded point is inside 25 miles of that point
        # and outside 25 miles of Upland, so the sentence only works if the
        # saved line was placed.
        near_home = hazard_mod.move_miles(34.2, -117.7, 22, 0)
        self.assertLess(hazard_mod.distance_miles(34.2, -117.7, near_home[0], near_home[1]), 25)
        self.assertGreater(hazard_mod.distance_miles(HOME[0], HOME[1], near_home[0], near_home[1]), 25)
        calls = []

        def get(url, timeout):
            calls.append(url)
            if "usgs" in url:
                return {"features": []}
            return [_fire(near_home[0], near_home[1], NOW_TS - 1200, ident="by-home")]

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            spoken = commands.speak_fires(
                now=NOW,
                home_path=self.home_file,
                geocode=geocode,
                locate=True,
                cache_path=self.cache,
                read_key=lambda: SECRET,
                get=get,
            )
        self.assertEqual(spoken, "One fire 22 miles north, 20 minutes ago.")
        self.assertNotIn(HOME_LINE, spoken)
        placed = len(seen)
        again = commands.speak_fires(
            now=NOW,
            home_path=self.home_file,
            geocode=geocode,
            locate=True,
            cache_path=self.cache,
            read_key=lambda: SECRET,
            get=get,
        )
        self.assertEqual(again, spoken)
        self.assertEqual(len(seen), placed)
        self.assertNotIn(HOME_LINE, out.getvalue() + err.getvalue())
        self.assertNotIn(HOME_LINE, open(self.cache, encoding="utf-8").read())
        self.assertNotIn(SECRET, spoken)


class TestAlerts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = os.path.join(self.tmp.name, "hazard-cache.json")
        self.alerts = os.path.join(self.tmp.name, "hazard-alerts.json")

    def test_alerts_are_off_until_asked_and_each_event_is_spoken_once(self):
        self.assertFalse(commands.hazard_alerts_enabled(self.alerts))
        calls = []
        lat, lon = _east(31)

        def get(url, timeout):
            calls.append(url)
            if "usgs" in url:
                return {"features": [_quake(lat, lon, 3.8, NOW_TS - 7200, "ci38001")]}
            return []

        kwargs = dict(
            home=HOME, locate=False, cache_path=self.cache,
            read_key=lambda: SECRET, get=get, state_path=self.alerts,
        )
        heard = []

        def hear(line):
            heard.append(line)
            return True

        quiet = commands.run_hazard_alerts_once(hear, now=NOW, **kwargs)
        self.assertEqual(heard, [])
        self.assertEqual(calls, [])
        self.assertEqual(quiet, commands.HAZARD_POLL_SECONDS)
        spoken = commands.set_hazard_alerts(True, path=self.alerts, now=NOW)
        self.assertIn("on", spoken.lower())
        self.assertTrue(commands.hazard_alerts_enabled(self.alerts))
        commands.run_hazard_alerts_once(hear, now=NOW, **kwargs)
        self.assertEqual(heard, [
            "Hazard alert. One magnitude 3.8 quake 31 miles east, 2 hours ago.",
        ])
        commands.run_hazard_alerts_once(hear, now=NOW, **kwargs)
        self.assertEqual(len(heard), 1)
        self.assertEqual(len([url for url in calls if "usgs" in url]), 1)

        def refused(_line):
            return False

        later = NOW + timedelta(seconds=commands.HAZARD_CACHE_TTL_SECONDS + 5)
        second = _quake(*_north(20), 4.1, later.timestamp() - 600, "ci41002")

        def get_two(url, timeout):
            calls.append(url)
            if "usgs" in url:
                return {"features": [
                    _quake(lat, lon, 3.8, NOW_TS - 7200, "ci38001"),
                    second,
                ]}
            return []

        kwargs["get"] = get_two
        commands.run_hazard_alerts_once(refused, now=later, **kwargs)
        self.assertEqual(len(heard), 1)
        commands.run_hazard_alerts_once(hear, now=later, **kwargs)
        self.assertEqual(len(heard), 2)
        self.assertIn("magnitude 4.1", heard[-1])
        self.assertNotIn("3.8", heard[-1])
        off = commands.set_hazard_alerts(False, path=self.alerts, now=later)
        self.assertIn("off", off.lower())
        self.assertFalse(commands.hazard_alerts_enabled(self.alerts))
        before = len(calls)
        commands.run_hazard_alerts_once(hear, now=later, **kwargs)
        self.assertEqual(len(calls), before)
        self.assertEqual(len(heard), 2)

    def test_a_quiet_mac_does_not_mark_the_event_spoken(self):
        lat, lon = _east(31)

        def get(url, timeout):
            if "usgs" in url:
                return {"features": [_quake(lat, lon, 3.8, NOW_TS - 7200, "ci38001")]}
            return []

        commands.set_hazard_alerts(True, path=self.alerts, now=NOW)
        heard = []

        def hear(line):
            heard.append(line)
            return True

        commands.run_hazard_alerts_once(
            hear, now=NOW, home=HOME, locate=False, cache_path=self.cache,
            read_key=lambda: SECRET, get=get, state_path=self.alerts, quiet=True,
        )
        self.assertEqual(heard, [])
        commands.run_hazard_alerts_once(
            hear, now=NOW, home=HOME, locate=False, cache_path=self.cache,
            read_key=lambda: SECRET, get=get, state_path=self.alerts, quiet=False,
        )
        self.assertEqual(len(heard), 1)

    def test_the_scheduler_starts_only_on_mac(self):
        with mock.patch.object(hazard_mod.sys, "platform", "linux"):
            self.assertIsNone(hazard_mod.start_hazard_thread(lambda _line: True))
        started = []

        def fake_start(thread):
            started.append(thread.name)

        with mock.patch.object(hazard_mod.sys, "platform", "darwin"), \
                mock.patch.object(hazard_mod.threading.Thread, "start", fake_start):
            thread = hazard_mod.start_hazard_thread(lambda _line: True, quiet_check=lambda: False)
        self.assertEqual(started, ["jev-hazard-watch"])
        self.assertTrue(thread.daemon)


class TestBridgeRefusal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.outbox = os.path.join(self.tmp.name, "outbox")
        self.nonce_log = os.path.join(self.tmp.name, "nonces.json")
        os.makedirs(self.outbox)
        patches = [
            mock.patch.object(bridge, "BRIDGE_OUTBOX", self.outbox),
            mock.patch.object(bridge, "NONCE_LOG", self.nonce_log),
            mock.patch.object(bridge, "_bridge_secret", return_value=BRIDGE_SECRET),
            mock.patch.object(bridge.time, "time", return_value=BRIDGE_NOW),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _process(self, cmd, nonce):
        path = os.path.join(self.tmp.name, nonce + ".json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({
                "cmd": cmd,
                "ts": BRIDGE_NOW,
                "nonce": nonce,
                "sig": _sign(cmd, BRIDGE_NOW, nonce),
            }, handle)
        calls = []

        def run_text(text):
            calls.append(text)
            return "should not run"

        bridge._process_bridge_file(path, run_text)
        with open(os.path.join(self.outbox, nonce + ".json"), encoding="utf-8") as handle:
            reply = json.load(handle)
        return calls, path, reply

    def test_signed_hazard_commands_are_refused(self):
        phrases = (
            ("any fires near me", "hazfire01", "info_hazards_fires"),
            ("any earthquakes near me", "hazquake1", "info_hazards_quakes"),
            ("hazard check", "hazcheck1", "info_hazards"),
            ("any hazards near me", "hazcheck2", "info_hazards"),
            ("turn on hazard alerts", "hazalert1", "hazard_alerts_on"),
            ("turn off hazard alerts", "hazalert2", "hazard_alerts_off"),
            ("hey jev, hazard check", "hazcheck3", "info_hazards"),
            ("please any fires near me", "hazfire02", "info_hazards_fires"),
        )
        self.assertEqual(len(commands.BRIDGE_ALLOW), 30)
        self.assertIsInstance(commands.BRIDGE_ALLOW, frozenset)
        for phrase, nonce, key in phrases:
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
            self.assertNotIn(key, commands.BRIDGE_ALLOW, phrase)
            calls, path, reply = self._process(phrase, nonce)
            self.assertEqual(calls, [], phrase)
            self.assertFalse(os.path.exists(path), phrase)
            self.assertFalse(reply["ok"], phrase)
            self.assertIn("can't do that from your phone", reply["reply"])
