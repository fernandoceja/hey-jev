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

        cynthia = "check my messages from Cynthia"
        self.assertIsNone(commands.route_before_api(cynthia))
        self.assertIsNone(commands.bridge_allowed(cynthia))
        calls, path = self._process(cynthia, "cynthia1", name="cynthia.json")
        self.assertEqual(calls, [])
        self.assertFalse(os.path.exists(path))
        self.assertIn("phone", self._reply("cynthia1")["reply"].lower())
