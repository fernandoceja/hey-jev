"""Outbox reply files expire on the Mac. No iCloud and no macOS tools."""
import os
import tempfile
import time
import unittest
from unittest import mock

import commands
from commands import bridge


class TestOutboxSweep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.outbox = os.path.join(self.tmp.name, "outbox")
        self.elsewhere = os.path.join(self.tmp.name, "elsewhere")
        os.makedirs(self.outbox)
        os.makedirs(self.elsewhere)
        self.now = 1_700_000_000
        patch = mock.patch.object(bridge, "BRIDGE_OUTBOX", self.outbox)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self._clear_thread)

    def _clear_thread(self):
        bridge._bridge_thread = None

    def _plant(self, directory, name, age):
        path = os.path.join(directory, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('{"ok": true, "reply": "shift at 9"}\n')
        os.utime(path, (self.now - age, self.now - age))
        return path

    def test_ttl_is_ten_minutes(self):
        self.assertEqual(commands.OUTBOX_TTL_SECONDS, 10 * 60)
        self.assertEqual(bridge.OUTBOX_TTL_SECONDS, 10 * 60)

    def test_old_reply_is_deleted_and_a_fresh_one_stays(self):
        ttl = bridge.OUTBOX_TTL_SECONDS
        old = self._plant(self.outbox, "nonce1234.json", ttl + 1)
        fresh = self._plant(self.outbox, "nonce5678.json", ttl - 1)
        exact = self._plant(self.outbox, "nonce9012.json", ttl)
        self.assertEqual(bridge.sweep_outbox(self.now), 1)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(fresh))
        self.assertTrue(os.path.exists(exact))

    def test_only_nonce_json_names_in_the_outbox_are_removed(self):
        ttl = bridge.OUTBOX_TTL_SECONDS
        kept = [
            self._plant(self.outbox, "short.json", ttl + 30),
            self._plant(self.outbox, "notes.txt", ttl + 30),
            self._plant(self.outbox, ".nonce1234.json", ttl + 30),
            self._plant(self.outbox, "nonce1234.json.tmp", ttl + 30),
            self._plant(self.outbox, "has space1.json", ttl + 30),
            self._plant(self.elsewhere, "nonce1234.json", ttl + 30),
        ]
        nested = os.path.join(self.outbox, "nested")
        os.makedirs(nested)
        kept.append(self._plant(nested, "nonce1234.json", ttl + 30))
        outside = os.path.join(self.elsewhere, "secret.txt")
        with open(outside, "w", encoding="utf-8") as handle:
            handle.write("leave me")
        link_target = self._plant(self.elsewhere, "target.json", ttl + 30)
        link = os.path.join(self.outbox, "nonceabcd.json")
        os.symlink(link_target, link)
        self.assertEqual(bridge.sweep_outbox(self.now), 0)
        for path in kept + [outside, link, link_target]:
            self.assertTrue(os.path.exists(path), path)

    def test_poll_and_startup_both_sweep(self):
        ttl = bridge.OUTBOX_TTL_SECONDS
        inbox = os.path.join(self.tmp.name, "inbox")
        # poll and startup call sweep with the real clock, not self.now.
        self.now = time.time()
        old = self._plant(self.outbox, "nonce1234.json", ttl + 5)
        with mock.patch.object(bridge, "BRIDGE_INBOX", inbox):
            bridge.poll_bridge(lambda text: "unused")
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.isdir(inbox))

        again = self._plant(self.outbox, "nonce5678.json", ttl + 5)
        with mock.patch.object(bridge.threading, "Thread") as thread_cls:
            bridge.start_bridge_thread(lambda text: "unused")
        self.assertFalse(os.path.exists(again))
        thread_cls.return_value.start.assert_called_once()
        # A second start still sweeps, and it does not start another thread
        # once the first one is recorded as alive.
        bridge._bridge_thread = mock.Mock()
        bridge._bridge_thread.is_alive.return_value = True
        third = self._plant(self.outbox, "nonce9012.json", ttl + 5)
        with mock.patch.object(bridge.threading, "Thread") as thread_cls:
            bridge.start_bridge_thread(lambda text: "unused")
        self.assertFalse(os.path.exists(third))
        thread_cls.assert_not_called()

    def test_missing_outbox_is_a_no_op(self):
        os.rmdir(self.outbox)
        self.assertEqual(bridge.sweep_outbox(self.now), 0)
        self.assertFalse(os.path.exists(self.outbox))
