"""Heads-up alerts. Calendar, hazards, and MapKit are faked."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import commands
from commands import config
from commands import heads_up as hu
from commands import zoe_mode

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = timezone(timedelta(hours=-7))
NOON = datetime(2026, 10, 19, 12, 0, tzinfo=TZ)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "heads-up.json")
        self.log = os.path.join(self.tmp.name, "log.jsonl")
        self.heard = []
        hu.set_heads_up(True, path=self.state, now=NOON)

    def tearDown(self):
        self.tmp.cleanup()

    def hear(self, line):
        self.heard.append(line)
        return True

    def run_once(self, checks, now=NOON, **kw):
        return hu.run_heads_up_once(self.hear, now=now, checks=checks,
                                    state_path=self.state, log_path=self.log,
                                    quiet=kw.pop("quiet", False), **kw)

    def logs(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return [json.loads(x) for x in f if x.strip()]


def fixed(alerts):
    return lambda now: list(alerts)


A = {"id": "a", "kind": "calendar", "line": "Dentist starts in 30 minutes."}
B = {"id": "b", "kind": "hazard", "line": "Hazard alert. One quake nearby."}


class EngineTests(Base):
    def test_speaks_once_and_logs(self):
        self.assertEqual(self.run_once([fixed([A])]), A["line"])
        self.assertEqual(self.heard, [A["line"]])
        later = NOON + timedelta(hours=2)
        self.assertIsNone(self.run_once([fixed([A])], now=later))
        self.assertEqual(len(self.heard), 1)
        logs = self.logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["result"], "spoken")
        self.assertEqual(logs[0]["id"], "a")

    def test_once_survives_restart(self):
        self.run_once([fixed([A])])
        hu.set_heads_up(True, path=self.state, now=NOON)
        self.assertIsNone(self.run_once([fixed([A])], now=NOON + timedelta(days=1)))

    def test_off_by_default_and_toggle(self):
        os.remove(self.state)
        self.assertFalse(hu.heads_up_enabled(self.state))
        self.assertIsNone(self.run_once([fixed([A])]))
        self.assertIn("on", hu.set_heads_up(True, path=self.state, now=NOON))
        self.assertTrue(hu.heads_up_enabled(self.state))
        self.assertEqual(hu.set_heads_up(False, path=self.state, now=NOON), "Heads-up alerts are off.")
        self.assertIsNone(self.run_once([fixed([A])]))
        self.assertEqual(self.heard, [])

    def test_quiet_hours(self):
        for hour in (22, 23, 0, 3, 6):
            now = NOON.replace(hour=hour)
            self.assertTrue(hu.in_quiet_hours(now), hour)
            self.assertIsNone(self.run_once([fixed([A])], now=now))
        for hour in (7, 12, 21):
            self.assertFalse(hu.in_quiet_hours(NOON.replace(hour=hour)), hour)
        self.assertEqual(self.heard, [])
        self.assertEqual(self.run_once([fixed([A])], now=NOON.replace(hour=7)), A["line"])

    def test_quiet_probe_holds(self):
        self.assertIsNone(self.run_once([fixed([A])], quiet=True))
        self.assertEqual(self.run_once([fixed([A])]), A["line"])

    def test_rate_limit(self):
        self.run_once([fixed([A, B])])
        self.assertIsNone(self.run_once([fixed([A, B])], now=NOON + timedelta(minutes=5)))
        gap = int(config.HEADS_UP_MIN_GAP_MINUTES)
        self.assertEqual(self.run_once([fixed([A, B])], now=NOON + timedelta(minutes=gap)), B["line"])
        self.assertEqual(self.heard, [A["line"], B["line"]])

    def test_failed_delivery_not_marked(self):
        told = hu.run_heads_up_once(lambda line: False, now=NOON, checks=[fixed([A])],
                                    state_path=self.state, log_path=self.log, quiet=False)
        self.assertIsNone(told)
        self.assertEqual(self.run_once([fixed([A])]), A["line"])

    def test_broken_check_skipped(self):
        def boom(now):
            raise RuntimeError("x")
        self.assertEqual(self.run_once([boom, fixed([A])]), A["line"])

    def test_money_never_spoken(self):
        money = [
            {"id": "m1", "kind": "calendar", "line": "Your balance is $1,200."},
            {"id": "m2", "kind": "calendar", "line": "Rent bill due in 30 minutes."},
            {"id": "m3", "kind": "calendar", "line": "Pay Affirm starts in 10 minutes."},
            {"id": "m4", "kind": "calendar", "line": "Transfer 450.00 starts soon."},
        ]
        self.assertEqual(self.run_once([fixed(money + [A])]), A["line"])
        self.assertEqual(self.heard, [A["line"]])
        logs = self.logs()
        suppressed = [x for x in logs if x["result"] == "suppressed_money"]
        self.assertEqual(len(suppressed), 4)
        for entry in suppressed:
            self.assertNotIn("line", entry)
        self.assertNotIn("$", open(self.log).read())

    def test_mentions_money(self):
        for line in ("$5", "your bills", "payday today", "Discover card", "1,234", "12.50 left"):
            self.assertTrue(hu.mentions_money(line), line)
        for line in ("Your shift at Brea starts in 45 minutes and traffic adds 10.",
                     "Hazard alert. One magnitude 3.8 quake 31 miles east, 2 hours ago."):
            self.assertFalse(hu.mentions_money(line), line)

    def test_state_file_private(self):
        self.run_once([fixed([A])])
        self.assertEqual(os.stat(self.state).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.log).st_mode & 0o777, 0o600)


def shift(start, hours=8, title="Apple Brea shift"):
    return {"title": title, "start": start, "end": start + timedelta(hours=hours),
            "all_day": False, "place": "Brea"}


class CheckTests(unittest.TestCase):
    def test_calendar_brea_with_traffic(self):
        ev = shift(NOON + timedelta(minutes=45))
        with mock.patch.object(hu, "_is_shift", return_value=True):
            out = hu.calendar_check(NOON, events=[ev], travel=lambda o, d, w: 45)
        self.assertEqual(out[0]["line"], "Your shift at Brea starts in 45 minutes and traffic adds 10.")
        self.assertEqual(out[0]["kind"], "calendar")

    def test_calendar_brea_light_traffic(self):
        ev = shift(NOON + timedelta(minutes=30))
        with mock.patch.object(hu, "_is_shift", return_value=True):
            out = hu.calendar_check(NOON, events=[ev], travel=lambda o, d, w: 36)
        self.assertEqual(out[0]["line"], "Your shift at Brea starts in 30 minutes.")

    def test_calendar_plain_event_and_window(self):
        ev = {"title": "Dentist", "start": NOON + timedelta(minutes=20),
              "end": NOON + timedelta(hours=1), "all_day": False}
        far = {"title": "Later", "start": NOON + timedelta(hours=3),
               "end": NOON + timedelta(hours=4), "all_day": False}
        allday = {"title": "Holiday", "start": NOON + timedelta(minutes=5),
                  "end": NOON + timedelta(days=1), "all_day": True}
        out = hu.calendar_check(NOON, events=[far, allday, ev], travel=lambda *a: None)
        self.assertEqual([x["line"] for x in out], ["Dentist starts in 20 minutes."])
        self.assertEqual(hu.calendar_check(NOON, events=[far], travel=lambda *a: None), [])

    def test_hazard_check_uses_collect(self):
        def collect(now, locate):
            self.assertTrue(locate)
            return {"events": [{"id": "q1", "type": "earthquake"}]}
        with mock.patch("commands.hazards.alert_line", return_value="Hazard alert. Quake."):
            out = hu.hazard_check(NOON, collect=collect)
        self.assertEqual(out, [{"id": "hazard|q1", "kind": "hazard", "line": "Hazard alert. Quake."}])

    def test_hazard_check_failure_is_empty(self):
        def collect(now, locate):
            raise OSError("offline")
        self.assertEqual(hu.hazard_check(NOON, collect=collect), [])

    def test_eta_home_after_shift(self):
        ev = shift(NOON - timedelta(hours=8, minutes=10))
        with mock.patch.object(hu, "_is_shift", return_value=True):
            out = hu.eta_home_check(NOON, events=[ev], travel=lambda o, d, w: 50, origin=(34.0, -117.0))
            self.assertEqual(out[0]["kind"], "eta_home")
            self.assertIn("Traffic adds 15", out[0]["line"])
            self.assertEqual(hu.eta_home_check(NOON, events=[ev], travel=lambda *a: 38, origin=(1, 1)), [])
            self.assertEqual(hu.eta_home_check(NOON + timedelta(hours=2), events=[ev],
                                               travel=lambda *a: 60, origin=(1, 1)), [])

    def test_lines_never_include_street(self):
        ev = shift(NOON + timedelta(minutes=45))
        with mock.patch.object(hu, "_is_shift", return_value=True):
            out = hu.calendar_check(NOON, events=[ev], travel=lambda *a: 50)
        self.assertNotIn(config.BREA_STORE_ADDRESS, out[0]["line"])
        self.assertNotIn(config.HOME_ADDRESS, out[0]["line"])


class WiringTests(unittest.TestCase):
    PHRASES_ON = ("turn on heads up alerts", "enable heads-up alerts", "heads up alerts on",
                  "hey jev, turn on heads up")
    PHRASES_OFF = ("turn off heads up alerts", "disable heads-up alerts", "heads up alerts off")

    def test_routing_and_not_on_bridge(self):
        for phrase in self.PHRASES_ON:
            self.assertEqual(commands.route_before_api(phrase), "heads_up_on", phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
        for phrase in self.PHRASES_OFF:
            self.assertEqual(commands.route_before_api(phrase), "heads_up_off", phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
        for key in ("heads_up_on", "heads_up_off"):
            self.assertNotIn(key, commands.BRIDGE_ALLOW)
            self.assertNotIn(key, zoe_mode.ZOE_ALLOW)
        self.assertEqual(len(commands.BRIDGE_ALLOW), 30)

    def test_no_sockets_or_secrets(self):
        with open(os.path.join(ROOT, "commands", "heads_up.py")) as f:
            src = f.read()
        for bad in ("import socket", "socket.socket", ".listen(", ".bind(", "keychain_value",
                    "get_secret", "os.getenv", "from .bridge", "import bridge", "urlopen",
                    "http://", "https://"):
            self.assertNotIn(bad, src, bad)

    def test_siri_wiring(self):
        with open(os.path.join(ROOT, "siri.py")) as f:
            siri = f.read()
        self.assertIn('"heads_up_on": lambda _arg, _text: commands.set_heads_up(True)', siri)
        self.assertIn("commands.start_heads_up_thread(_heads_up_deliver", siri)

    def test_thread_mac_only(self):
        with mock.patch.object(hu.sys, "platform", "linux"):
            self.assertIsNone(hu.start_heads_up_thread(lambda line: True))
