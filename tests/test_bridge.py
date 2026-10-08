"""iPhone bridge checks. No Keychain, no iCloud, no macOS."""
import hashlib
import hmac
import json
import os
import tempfile
import unittest
from unittest import mock

import commands
from commands import bridge

SECRET = "bridge-test-secret"
NOW = 1_700_000_000


def _sign(cmd, ts, nonce, secret=SECRET):
    payload = f"{cmd}|{ts}|{nonce}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


class TestBridgeValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.outbox = os.path.join(self.tmp.name, "outbox")
        self.nonce_log = os.path.join(self.tmp.name, "nonces.json")
        os.makedirs(self.outbox)
        patches = [
            mock.patch.object(bridge, "BRIDGE_OUTBOX", self.outbox),
            mock.patch.object(bridge, "NONCE_LOG", self.nonce_log),
            mock.patch.object(bridge, "_bridge_secret", return_value=SECRET),
            mock.patch.object(bridge.time, "time", return_value=NOW),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _process(self, cmd, nonce, ts=NOW, sig=None, name="cmd.json"):
        if sig is None:
            sig = _sign(cmd, ts, nonce)
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"cmd": cmd, "ts": ts, "nonce": nonce, "sig": sig}, handle)
        calls = []

        def run_text(text):
            calls.append(text)
            return "Handled on the Mac."

        bridge._process_bridge_file(path, run_text)
        return calls, path

    def _reply(self, nonce):
        with open(os.path.join(self.outbox, nonce + ".json"), encoding="utf-8") as handle:
            return json.load(handle)

    def test_forged_signature_is_rejected(self):
        calls, path = self._process("what time is it", "nonce1234", sig="0" * 64)
        self.assertEqual(calls, [])
        self.assertFalse(os.path.exists(path))
        reply = self._reply("nonce1234")
        self.assertFalse(reply["ok"])
        self.assertIn("verify", reply["reply"].lower())

    def test_replayed_nonce_is_rejected(self):
        first, _path = self._process("what time is it", "nonce1234")
        self.assertEqual(first, ["what time is it"])
        self.assertTrue(self._reply("nonce1234")["ok"])
        second, path = self._process("what time is it", "nonce1234", name="again.json")
        self.assertEqual(second, [])
        self.assertFalse(os.path.exists(path))
        reply = self._reply("nonce1234")
        self.assertFalse(reply["ok"])
        self.assertIn("already", reply["reply"].lower())

    def test_timestamp_outside_the_window_is_rejected(self):
        late = NOW - (commands.BRIDGE_MAX_AGE + 1)
        early = NOW + (commands.BRIDGE_MAX_AGE + 1)
        for nonce, ts in (("nonceold1", late), ("noncenew1", early)):
            calls, path = self._process("what time is it", nonce, ts=ts, name=nonce + ".json")
            self.assertEqual(calls, [], nonce)
            self.assertFalse(os.path.exists(path))
            reply = self._reply(nonce)
            self.assertFalse(reply["ok"])
            self.assertIn("too old", reply["reply"].lower())

    def test_open_and_close_stay_off_the_phone(self):
        """Typing and app open/close are Mac commands. A signed file still does not run."""
        phrases = (
            ("close imessage", "closeim1", "app_quit"),
            ("close iMessage.", "closeim2", "app_quit"),
            ("quit messages", "quitmsg1", "app_quit"),
            ("open imessage", "openimsg", "app_open"),
            ("hide messages", "hidemsg1", "app_hide"),
        )
        for phrase, nonce, key in phrases:
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
            calls, path = self._process(phrase, nonce, name=nonce + ".json")
            self.assertEqual(calls, [], phrase)
            self.assertFalse(os.path.exists(path))
            self.assertIn("phone", self._reply(nonce)["reply"].lower())
        for key in ("app_open", "app_quit", "app_hide", "app_focus"):
            self.assertNotIn(key, commands.BRIDGE_ALLOW)
        self.assertNotIn("info_messages", commands.BRIDGE_ALLOW)

    def test_disallowed_command_is_rejected(self):
        phrases = (
            ("empty the trash", "nonce1234"),
            ("run shortcut Leaving for work", "nonce5678"),
            ("quit all the apps", "nonce9012"),
        )
        for phrase, nonce in phrases:
            calls, path = self._process(phrase, nonce, name=nonce + ".json")
            self.assertEqual(calls, [], phrase)
            self.assertFalse(os.path.exists(path))
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
            reply = self._reply(nonce)
            self.assertFalse(reply["ok"])
            self.assertIn("phone", reply["reply"].lower())

    def test_oversized_command_is_rejected(self):
        cmd = "a" * (commands.BRIDGE_MAX_CMD + 1)
        calls, path = self._process(cmd, "nonce1234")
        self.assertEqual(calls, [])
        self.assertFalse(os.path.exists(path))
        reply = self._reply("nonce1234")
        self.assertFalse(reply["ok"])
        self.assertIn("too long", reply["reply"].lower())
        # The boundary stays where it was: 2000 characters is not rejected for length.
        exact = "b" * commands.BRIDGE_MAX_CMD
        calls, _path = self._process(exact, "nonce5678", name="exact.json")
        self.assertEqual(calls, [])
        self.assertNotIn("too long", self._reply("nonce5678")["reply"].lower())

    def test_my_love_and_cynthia_messages_are_rejected(self):
        """My Love is a real local command and is still blocked on the bridge.

        Cynthia is not a separate messages path. That phrase is not allowlisted,
        so the bridge refuses it before run_text, the same as any other command
        that is not on BRIDGE_ALLOW.
        """
        love = "check my messages from My Love"
        self.assertEqual(commands.route_before_api(love), "info_messages")
        self.assertIsNone(commands.bridge_allowed(love))
        calls, path = self._process(love, "nonce1234")
        self.assertEqual(calls, [])
        self.assertFalse(os.path.exists(path))
        self.assertIn("phone", self._reply("nonce1234")["reply"].lower())

        self.assertIsNone(commands.bridge_allowed("confirm the transfer"))
        self.assertIsNone(commands.bridge_allowed("move $600 to Zoe"))

        cynthia = "check my messages from Cynthia"
        self.assertIsNone(commands.route_before_api(cynthia))
        self.assertIsNone(commands.bridge_allowed(cynthia))
        calls, path = self._process(cynthia, "cynthia1", name="cynthia.json")
        self.assertEqual(calls, [])
        self.assertFalse(os.path.exists(path))
        self.assertIn("phone", self._reply("cynthia1")["reply"].lower())

    def test_payday_check_is_allowlisted_individually_and_my_love_stays_blocked(self):
        """Each payday-check phrase is one named allowlist entry. My Love is not.

        BRIDGE_ALLOW has no wildcard and no category prefix. info_payday_check
        is listed by itself. info_messages is absent, and a signed My Love
        file still never reaches run_text.
        """
        self.assertIn("info_payday_check", commands.BRIDGE_ALLOW)
        self.assertNotIn("info_messages", commands.BRIDGE_ALLOW)
        self.assertIsInstance(commands.BRIDGE_ALLOW, frozenset)
        for item in commands.BRIDGE_ALLOW:
            self.assertNotIn("*", item)
            self.assertNotIn("?", item)
            self.assertFalse(item.endswith("*"))

        phrases = (
            ("what's due today", "duetoday1"),
            ("payday check", "paydaychk"),
            ("any reminders today", "reminders"),
        )
        for phrase, nonce in phrases:
            self.assertEqual(commands.route_before_api(phrase), "info_payday_check", phrase)
            self.assertEqual(commands.bridge_allowed(phrase), "info_payday_check", phrase)
            calls, path = self._process(phrase, nonce, name=nonce + ".json")
            self.assertEqual(calls, [phrase], phrase)
            self.assertFalse(os.path.exists(path))
            reply = self._reply(nonce)
            self.assertTrue(reply["ok"], phrase)
            self.assertEqual(reply["reply"], "Handled on the Mac.")

        love = "check my messages from My Love"
        self.assertEqual(commands.route_before_api(love), "info_messages")
        self.assertIsNone(commands.bridge_allowed(love))
        calls, path = self._process(love, "lovecheck")
        self.assertEqual(calls, [])
        self.assertFalse(os.path.exists(path))
        self.assertIn("phone", self._reply("lovecheck")["reply"].lower())

    def test_shift_and_leave_are_allowlisted_individually(self):
        """Each new phrase is its own allowlist name. My Love and money stay off."""
        self.assertIn("shift_set", commands.BRIDGE_ALLOW)
        self.assertIn("shift_clear", commands.BRIDGE_ALLOW)
        self.assertIn("info_leave", commands.BRIDGE_ALLOW)
        self.assertNotIn("info_messages", commands.BRIDGE_ALLOW)
        self.assertIsInstance(commands.BRIDGE_ALLOW, frozenset)
        for item in commands.BRIDGE_ALLOW:
            self.assertNotIn("*", item)
            self.assertNotIn("?", item)

        phrases = (
            ("my shift Monday is 9:30 to 6:30 at Brea", "shiftmon1", "shift_set"),
            ("clear my shift Monday", "shiftclr1", "shift_clear"),
            ("when should I leave for work", "leavewrk1", "info_leave"),
        )
        for phrase, nonce, key in phrases:
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertEqual(commands.bridge_allowed(phrase), key, phrase)
            calls, path = self._process(phrase, nonce, name=nonce + ".json")
            self.assertEqual(calls, [phrase], phrase)
            self.assertFalse(os.path.exists(path))
            reply = self._reply(nonce)
            self.assertTrue(reply["ok"], phrase)
            self.assertEqual(reply["reply"], "Handled on the Mac.")

        self.assertIsNone(commands.bridge_allowed("check my messages from My Love"))
        self.assertIsNone(commands.bridge_allowed("move $600 to Zoe"))
        self.assertIsNone(commands.bridge_allowed("confirm the transfer"))

    def test_zoe_mode_cannot_be_entered_or_left_from_the_phone(self):
        """Zoe mode keys are not on BRIDGE_ALLOW. A signed file never reaches run_text."""
        phrases = (
            ("zoe mode", "zoemode1", "zoe_mode_on"),
            ("kid mode", "kidmode1", "zoe_mode_on"),
            ("kid mode on", "kidon001", "zoe_mode_on"),
            ("turn on zoe mode", "turnonz1", "zoe_mode_on"),
            ("turn on kid mode", "turnonk1", "zoe_mode_on"),
            ("start zoe mode", "startzo1", "zoe_mode_on"),
            ("enter zoe mode", "enterzo1", "zoe_mode_on"),
            ("zoe mode on", "zoemode2", "zoe_mode_on"),
            ("exit zoe mode", "exitzom1", "zoe_mode_off"),
            ("leave zoe mode", "leavezo1", "zoe_mode_off"),
            ("turn off zoe mode", "offfzoe1", "zoe_mode_off"),
            ("turn off kid mode", "offkidm1", "zoe_mode_off"),
            ("kid mode off", "kidoff01", "zoe_mode_off"),
            ("stop zoe mode", "stopzoe1", "zoe_mode_off"),
            ("end zoe mode", "endzoe01", "zoe_mode_off"),
            ("leave kid mode", "leavekd1", "zoe_mode_off"),
            ("stop kid mode", "stopkid1", "zoe_mode_off"),
            ("joke", "jokephr1", "zoe_joke"),
            ("tell a joke", "tellajk1", "zoe_joke"),
            ("tell me a joke", "telljok1", "zoe_joke"),
            ("tell zoe a joke", "zoejoke1", "zoe_joke"),
            ("fun fact", "funfact1", "zoe_joke"),
            ("a fun fact", "afunfact", "zoe_joke"),
            ("tell me a fun fact", "funfact2", "zoe_joke"),
        )
        self.assertIsInstance(commands.BRIDGE_ALLOW, frozenset)
        for key in ("zoe_mode_on", "zoe_mode_off", "zoe_joke"):
            self.assertNotIn(key, commands.BRIDGE_ALLOW, key)
        self.assertNotIn("info_messages", commands.BRIDGE_ALLOW)
        for phrase, nonce, key in phrases:
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
            calls, path = self._process(phrase, nonce, name=nonce + ".json")
            self.assertEqual(calls, [], phrase)
            self.assertFalse(os.path.exists(path))
            reply = self._reply(nonce)
            self.assertFalse(reply["ok"], phrase)
            self.assertIn("can't do that from your phone", reply["reply"].lower())
