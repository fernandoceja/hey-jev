"""Offline brain: start/stop/status of `fm serve` on 127.0.0.1:1976 only. Subprocess mocked."""
import os
import pathlib
import signal
import tempfile
import unittest
from unittest import mock

from commands import fm_serve as fs
from commands.config import BRIDGE_ALLOW
from commands.routing import route_before_api

ROOT = pathlib.Path(__file__).resolve().parent.parent
KEYS = ("fm_serve_start", "fm_serve_stop", "fm_serve_status")


class FakeProc:
    def __init__(self, pid=4242, exit_code=None):
        self.pid, self.exit_code = pid, exit_code

    def poll(self):
        return self.exit_code


class FakePopen:
    def __init__(self, proc=None, write=b""):
        self.calls, self.proc, self.write = [], proc or FakeProc(), write

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw))
        if self.write:
            kw["stdout"].write(self.write)
            kw["stdout"].flush()
        return self.proc


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = os.path.join(self.tmp.name, "logs", "fm-serve.log")
        self.pid = os.path.join(self.tmp.name, "fm-serve.pid")

    def start(self, popen, health):
        return fs.start(platform="darwin", popen=popen, healthy=health, fm_path="/usr/bin/fm",
                        sleep=lambda _s: None, log_path=self.log, pid_path=self.pid)

    def write_pid(self, pid):
        with open(self.pid, "w") as f:
            f.write(str(pid))


class PhraseTests(unittest.TestCase):
    def test_phrases(self):
        for t in ("start offline brain", "Hey Jev, turn on the offline brain.", "offline brain on"):
            self.assertEqual(fs.offline_brain_action(t), "fm_serve_start", t)
        for t in ("stop offline brain", "turn off the offline brain", "offline brain off"):
            self.assertEqual(fs.offline_brain_action(t), "fm_serve_stop", t)
        for t in ("offline brain status", "is the offline brain on?", "is offline brain running"):
            self.assertEqual(fs.offline_brain_action(t), "fm_serve_status", t)
        for t in ("", "start brain", "what is an offline brain", "start zelda"):
            self.assertIsNone(fs.offline_brain_action(t), t)

    def test_routing(self):
        self.assertEqual(route_before_api("start offline brain"), "fm_serve_start")
        self.assertEqual(route_before_api("stop offline brain"), "fm_serve_stop")
        self.assertEqual(route_before_api("offline brain status"), "fm_serve_status")

    def test_handlers_wired_and_not_bridged(self):
        siri_src = (ROOT / "siri.py").read_text()
        for key in KEYS:
            self.assertIn(f'"{key}": lambda', siri_src)
            self.assertNotIn(key, BRIDGE_ALLOW)


class StartTests(Base):
    def test_binds_localhost_only_detached(self):
        popen = FakePopen()
        out = self.start(popen, mock.Mock(side_effect=[False, True]))
        self.assertEqual(out, fs.FM_STARTED)
        argv, kw = popen.calls[0]
        self.assertEqual(argv, ["/usr/bin/fm", "serve", "--host", "127.0.0.1", "--port", "1976"])
        for bad in ("0.0.0.0", "sudo", "license", "--socket"):
            self.assertNotIn(bad, argv)
        self.assertTrue(kw["start_new_session"])
        self.assertNotIn("shell", kw)
        with open(self.pid) as f:
            self.assertEqual(f.read(), "4242")

    def test_already_running_does_not_spawn(self):
        popen = FakePopen()
        self.assertEqual(self.start(popen, lambda: True), fs.FM_ALREADY)
        self.assertEqual(popen.calls, [])

    def test_missing_fm(self):
        popen = FakePopen()
        with mock.patch.object(fs, "find_fm", return_value=None):
            out = fs.start(platform="darwin", popen=popen, healthy=lambda: False)
        self.assertEqual(out, fs.FM_MISSING)
        self.assertEqual(popen.calls, [])

    def test_license_not_accepted(self):
        popen = FakePopen(FakeProc(exit_code=1), write=b"You must accept the license agreement\n")
        self.assertEqual(self.start(popen, lambda: False), fs.FM_LICENSE)
        self.assertFalse(os.path.exists(self.pid))

    def test_other_failure(self):
        popen = FakePopen(FakeProc(exit_code=1), write=b"boom\n")
        self.assertEqual(self.start(popen, lambda: False), fs.FM_FAILED)

    def test_slow_start(self):
        self.assertEqual(self.start(FakePopen(), lambda: False), fs.FM_STARTING)

    def test_not_mac(self):
        popen = FakePopen()
        self.assertEqual(fs.start(platform="linux", popen=popen), fs.FM_NOT_MAC)
        self.assertEqual(popen.calls, [])

    def test_find_fm_fallback_paths(self):
        self.assertEqual(fs.find_fm(which=lambda _n: None, exists=lambda p: p == "/opt/homebrew/bin/fm",
                                    access=lambda _p, _m: True), "/opt/homebrew/bin/fm")
        self.assertIsNone(fs.find_fm(which=lambda _n: None, exists=lambda _p: False))
        self.assertEqual(fs.find_fm(which=lambda _n: "/usr/bin/fm"), "/usr/bin/fm")


class StopStatusTests(Base):
    def test_stop_sigterms_only_our_pid(self):
        self.write_pid(4242)
        kill = mock.Mock()
        out = fs.stop(platform="darwin", kill=kill, healthy=lambda: False,
                      is_ours=lambda p: p == 4242, pid_path=self.pid, sleep=lambda _s: None)
        self.assertEqual(out, fs.FM_STOPPED)
        kill.assert_called_once_with(4242, signal.SIGTERM)
        self.assertFalse(os.path.exists(self.pid))

    def test_stop_leaves_foreign_server_alone(self):
        kill = mock.Mock()
        out = fs.stop(platform="darwin", kill=kill, healthy=lambda: True,
                      is_ours=lambda _p: False, pid_path=self.pid)
        self.assertEqual(out, fs.FM_NOT_OURS)
        kill.assert_not_called()

    def test_stop_stale_pid(self):
        self.write_pid(999)
        kill = mock.Mock()
        out = fs.stop(platform="darwin", kill=kill, healthy=lambda: False,
                      is_ours=lambda _p: False, pid_path=self.pid)
        self.assertEqual(out, fs.FM_NOT_RUNNING)
        kill.assert_not_called()
        self.assertFalse(os.path.exists(self.pid))

    def test_is_our_fm_checks_command(self):
        run = mock.Mock(return_value=mock.Mock(stdout="/usr/bin/fm serve --host 127.0.0.1 --port 1976\n"))
        self.assertTrue(fs._is_our_fm(4242, run=run))
        run = mock.Mock(return_value=mock.Mock(stdout="/usr/bin/python3 app.py\n"))
        self.assertFalse(fs._is_our_fm(4242, run=run))
        self.assertFalse(fs._is_our_fm(1, run=run))

    def test_status_uses_health(self):
        self.assertEqual(fs.status(platform="darwin", healthy=lambda: True), fs.FM_STATUS_ON)
        self.assertEqual(fs.status(platform="darwin", healthy=lambda: False), fs.FM_STATUS_OFF)
        self.assertEqual(fs.status(platform="linux"), fs.FM_NOT_MAC)

    def test_health_hits_localhost(self):
        self.assertEqual(fs.HEALTH_URL, "http://127.0.0.1:1976/health")
        seen = []

        class Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(url, timeout):
            seen.append(url)
            return Resp()

        self.assertTrue(fs.is_healthy(opener=opener))
        self.assertEqual(seen, [fs.HEALTH_URL])
        self.assertFalse(fs.is_healthy(opener=mock.Mock(side_effect=OSError("refused"))))


if __name__ == "__main__":
    unittest.main()
