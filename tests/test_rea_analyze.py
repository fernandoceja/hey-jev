"""REA analyze: allowlist, blocklist, timeout, cap, redaction, kids app, logs.

The subprocess is mocked. Node and REA are not required.
"""
import json
import os
import stat
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import commands
import commands.rea_analyze as rea
from commands.config import (
    BRIDGE_ALLOW,
    REA_BLOCKLIST_PATH,
    REA_LOG_RETENTION_DAYS,
    REA_NODE_VERSION,
    REA_OUTPUT_CAP,
    REA_SPOKEN_CAP,
    REA_TIMEOUT_MAX,
    REA_TIMEOUT_MIN,
    REA_VERSION,
)
from commands.routing import route_before_api

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
SECRET_NAME = "UniqueSecretAppName"
SECRET_BUNDLE = "com.unique.secret.bundle"
SECRET_PATH = "/Applications/UniqueSecretAppName.app"
SECRET_SITE = "unique-secret.example"


class Result(object):
    def __init__(self, code, out, err=""):
        self.returncode = code
        self.stdout = out
        self.stderr = err


class Runner(object):
    def __init__(self, stdout='{"modules": ["core"]}', code=0, node_version=None, boom=None):
        self.stdout = stdout
        self.code = code
        self.node_version = "v{0}\n".format(REA_NODE_VERSION) if node_version is None else node_version
        self.boom = boom
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        self.assert_no_shell(kwargs)
        if list(argv)[-1:] == ["--version"]:
            return Result(0, self.node_version, "")
        if self.boom == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
        if self.boom == "missing":
            raise FileNotFoundError(argv[0])
        return Result(self.code, self.stdout, "err-line")

    @staticmethod
    def assert_no_shell(kwargs):
        if "shell" in kwargs:
            raise AssertionError("shell was passed to the subprocess")
        if kwargs.get("shell"):
            raise AssertionError("shell=True")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.logs = os.path.join(self.root, "logs")
        self.block = os.path.join(self.root, "blocklist.json")
        self.node = os.path.join(self.root, "node")
        self.script = os.path.join(self.root, "scripts", "rea.mjs")
        os.makedirs(os.path.dirname(self.script))
        with open(self.node, "w", encoding="utf-8") as handle:
            handle.write("node\n")
        with open(self.script, "w", encoding="utf-8") as handle:
            handle.write("// rea\n")
        self.write_version(REA_VERSION)
        self.write_blocklist({
            "blocked_bundle_ids": [
                "com.example.work",
                "com.example.child.device",
                SECRET_BUNDLE,
            ],
            "blocked_names": ["Example Work App"],
            "blocked_sites": ["work.example"],
            "kids_app_ids": ["com.example.kids.learning"],
        })

    def write_version(self, version):
        with open(os.path.join(self.root, "package.json"), "w", encoding="utf-8") as handle:
            json.dump({"name": "rea-agents", "version": version}, handle)

    def write_blocklist(self, payload):
        with open(self.block, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def front(self, **kwargs):
        found = {
            "name": "Notes",
            "bundle_id": "com.example.notes",
            "path": "/Applications/Notes.app",
        }
        found.update(kwargs)
        return found

    def run_app(self, runner, text="analyze this app", front=None, timeout=60, output_cap=None,
                platform="darwin", screenshot=None, blocklist_path=None, money=None):
        return rea.analyze_front_app(
            text,
            front=self.front() if front is None else front,
            screenshot=screenshot,
            run=runner,
            platform=platform,
            blocklist_path=self.block if blocklist_path is None else blocklist_path,
            log_dir=self.logs,
            now=NOW,
            timeout=timeout,
            output_cap=output_cap,
            node_path=self.node,
            script_path=self.script,
            money=money,
        )

    def log_files(self):
        if not os.path.isdir(self.logs):
            return []
        return [
            os.path.join(self.logs, name)
            for name in os.listdir(self.logs)
            if name.endswith(".json")
        ]

    def read_logs(self):
        found = []
        for path in self.log_files():
            with open(path, encoding="utf-8") as handle:
                found.append((path, handle.read(), json.load(open(path, encoding="utf-8"))))
        return found


class PhraseTests(unittest.TestCase):
    def test_phrases_route_and_stay_off_the_bridge(self):
        phrases = (
            "analyze this app",
            "analyse this app",
            "analyze the front app",
            "Analyze this app.",
            "please analyze this app",
            "hey jev, analyze this app",
            "hey jev please analyze the front app",
            "analyze this app for modules",
        )
        for phrase in phrases:
            self.assertEqual(rea.rea_action(phrase), "rea_analyze", phrase)
            self.assertEqual(route_before_api(phrase), "rea_analyze", phrase)
            self.assertNotIn("rea_analyze", BRIDGE_ALLOW, phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
        self.assertEqual(rea.requested_field("analyze this app for modules"), "modules")
        self.assertEqual(rea.requested_field("analyze this app"), "")
        self.assertEqual(len(BRIDGE_ALLOW), 30)
        self.assertIsInstance(BRIDGE_ALLOW, frozenset)
        self.assertNotIn("rea_analyze", commands.ZOE_ALLOW)
        self.assertIn("rea_analyze", commands.ZOE_BLOCKED["system"])
        self.assertFalse(commands.zoe_allows("rea_analyze"))
        for phrase in (
            "what is this app",
            "analyze my mail",
            "analyze this app and mute",
            "open notes",
        ):
            self.assertNotEqual(route_before_api(phrase), "rea_analyze", phrase)

    def test_siri_wires_the_action_and_the_bridge_file_is_untouched(self):
        siri = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        bridge = open(os.path.join(ROOT, "commands", "bridge.py"), encoding="utf-8").read()
        source = open(os.path.join(ROOT, "commands", "rea_analyze.py"), encoding="utf-8").read()
        self.assertIn('"rea_analyze": lambda _arg, text: commands.analyze_front_app(text)', siri)
        self.assertNotIn("rea_analyze", bridge)
        self.assertNotIn("rea-blocklist", bridge)
        for banned in (
            "shell=True",
            "os.system",
            "socket.socket",
            ".listen(",
            ".bind(",
            "urllib",
            "requests",
            "BRIDGE_ALLOW",
        ):
            self.assertNotIn(banned, source, banned)
        self.assertNotIn("subprocess.run", bridge)


class AllowlistTests(unittest.TestCase):
    def test_only_analyze_is_spawned_and_the_path_is_one_argument(self):
        self.assertEqual(rea.ALLOWED_COMMANDS, frozenset({"analyze"}))
        self.assertTrue(rea.command_allowed("analyze"))
        node = "/opt/homebrew/opt/node@24/bin/node"
        script = "/Users/example/Developer/rea/scripts/rea.mjs"
        path = "/Applications/My App.app"
        argv = rea.build_argv(node, script, "analyze", path)
        self.assertEqual(argv, [node, script, "analyze", path, "--json"])
        self.assertEqual(argv[3], path)
        self.assertNotIn(" ", argv[0])
        for command in (
            "capabilities",
            "analyze-javascript-application",
            "setup",
            "mcp",
            "update",
            "decompile",
            "doctor",
            "extract-artifact",
            "",
            "analyze; rm",
        ):
            self.assertIsNone(rea.build_argv(node, script, command, path), command)
            self.assertFalse(rea.command_allowed(command), command)


class BlocklistTests(Base):
    def test_finance_work_and_child_entries_refuse_before_spawn(self):
        cases = (
            {"bundle_id": "com.example.banking", "name": "Example Finance", "path": "/Applications/Example Finance.app"},
            {"bundle_id": "com.example.finance", "name": "Example Finance", "path": "/Applications/Example Finance.app"},
            {"bundle_id": "com.example.wallet", "name": "Example Finance", "path": "/Applications/Example Finance.app"},
            {"bundle_id": "com.example.work", "name": "Roster", "path": "/Applications/Roster.app"},
            {"name": "Example Work App", "bundle_id": "com.example.roster", "path": "/Applications/Roster.app"},
            {"bundle_id": "com.example.child.device", "name": "Tablet", "path": "/Applications/Tablet.app"},
            {"bundle_id": "com.example.browser", "name": "Browser", "site": "work.example", "path": "/Applications/Browser.app"},
        )
        for front in cases:
            runner = Runner()
            spoken = self.run_app(runner, front=self.front(**front))
            self.assertIsInstance(spoken, commands.LocalSpeech)
            self.assertEqual(spoken.text, rea.REFUSAL, front)
            self.assertEqual(runner.calls, [], front)

    def test_example_file_has_placeholders_only(self):
        path = os.path.join(ROOT, "rea-blocklist.example.json")
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        ids = data["blocked_bundle_ids"] + data["kids_app_ids"]
        sites = data["blocked_sites"]
        names = data["blocked_names"]
        self.assertTrue(ids)
        self.assertTrue(sites)
        self.assertTrue(names)
        for bundle in ids:
            self.assertRegex(bundle, r"^com\.example\.[a-z0-9]+(?:\.[a-z0-9]+)*$")
        for site in sites:
            self.assertRegex(site, r"^[a-z0-9-]+(?:\.[a-z0-9-]+)*\.example$")
        for name in names:
            self.assertRegex(name, r"^Example(?: [A-Za-z]+){1,4}$")
        gitignore = open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
        self.assertIn("rea-blocklist.json", gitignore)
        self.assertIn("rea-money-ids.local.json", gitignore)
        self.assertIn("rea-logs/", gitignore)

    def test_a_normal_app_is_analyzed(self):
        runner = Runner(stdout='{"modules": ["core"], "format": "app"}')
        spoken = self.run_app(runner)
        self.assertIn('modules: ["core"]', spoken.text)
        self.assertIn('format: "app"', spoken.text)
        self.assertEqual(len(runner.calls), 2)
        version_argv = runner.calls[0][0]
        analyze_argv, analyze_kwargs = runner.calls[1]
        self.assertEqual(version_argv[-1], "--version")
        self.assertEqual(analyze_argv[2], "analyze")
        self.assertEqual(analyze_argv[3], "/Applications/Notes.app")
        self.assertEqual(analyze_kwargs["timeout"], 60)
        self.assertNotIn("shell", analyze_kwargs)


class TimeoutCapTests(Base):
    def test_timeout_is_only_30_to_60_and_a_hang_is_reported(self):
        for bad in (29, 61, 0, "soon"):
            runner = Runner()
            spoken = self.run_app(runner, timeout=bad)
            self.assertEqual(spoken.text, rea.BAD_TIMEOUT, bad)
            self.assertEqual(runner.calls, [], bad)
        runner = Runner(boom="timeout")
        spoken = self.run_app(runner, timeout=30)
        self.assertEqual(spoken.text, "REA timed out after 30 seconds.")
        self.assertEqual(runner.calls[1][1]["timeout"], 30)
        self.assertEqual(REA_TIMEOUT_MIN, 30)
        self.assertEqual(REA_TIMEOUT_MAX, 60)
        self.assertEqual(runner.calls[1][0][2], "analyze")

    def test_output_is_capped_before_it_leaves(self):
        payload = {"modules": ["x" * 200], "format": "app"}
        runner = Runner(stdout=json.dumps(payload))
        spoken = self.run_app(runner, output_cap=80)
        self.assertLessEqual(len(spoken.text), 80)
        self.assertIn("[trimmed]", spoken.text)
        logs = self.read_logs()
        self.assertEqual(len(logs), 1)
        _path, _raw, body = logs[0]
        self.assertLessEqual(len(body["output"]), 80)
        self.assertLessEqual(len(body["answer"]), 80)
        self.assertIn("[trimmed]", body["output"])
        self.assertLess(80, REA_OUTPUT_CAP)


class FailureTests(Base):
    def test_nonzero_missing_binary_bad_json_and_version_mismatch(self):
        runner = Runner(code=3, stdout="")
        spoken = self.run_app(runner)
        self.assertEqual(spoken.text, "REA analyze exited with status 3.")

        runner = Runner(stdout="not json")
        spoken = self.run_app(runner)
        self.assertEqual(spoken.text, rea.BAD_JSON)

        runner = Runner(boom="missing")
        spoken = self.run_app(runner)
        self.assertEqual(spoken.text, rea.MISSING_NODE)

        runner = Runner()
        spoken = rea.analyze_front_app(
            "analyze this app",
            front=self.front(),
            run=runner,
            platform="darwin",
            blocklist_path=self.block,
            log_dir=self.logs,
            now=NOW,
            timeout=60,
            node_path=os.path.join(self.root, "missing-node"),
            script_path=self.script,
        )
        self.assertEqual(spoken.text, rea.MISSING_NODE)
        self.assertEqual(runner.calls, [])

        runner = Runner()
        spoken = rea.analyze_front_app(
            "analyze this app",
            front=self.front(),
            run=runner,
            platform="darwin",
            blocklist_path=self.block,
            log_dir=self.logs,
            now=NOW,
            timeout=60,
            node_path=self.node,
            script_path=os.path.join(self.root, "missing", "rea.mjs"),
        )
        self.assertEqual(spoken.text, rea.MISSING_REA)
        self.assertEqual(runner.calls, [])

        runner = Runner(node_version="v24.0.0\n")
        spoken = self.run_app(runner)
        self.assertIn(REA_NODE_VERSION, spoken.text)
        self.assertIn("24.0.0", spoken.text)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0][0][-1], "--version")

        self.write_version("0.0.1")
        runner = Runner()
        spoken = self.run_app(runner)
        self.assertIn(REA_VERSION, spoken.text)
        self.assertIn("0.0.1", spoken.text)
        self.assertEqual(len(runner.calls), 1)

    def test_not_mac_does_not_spawn(self):
        runner = Runner()
        spoken = self.run_app(runner, platform="linux")
        self.assertEqual(spoken.text, rea.NOT_MAC)
        self.assertEqual(runner.calls, [])
        self.assertEqual(self.log_files(), [])


class QuoteAndRedactTests(Base):
    def test_answers_quote_fields_and_do_not_guess(self):
        runner = Runner(stdout='{"modules": ["core"], "format": "app"}')
        spoken = self.run_app(runner, text="analyze this app for modules")
        self.assertEqual(spoken.text, 'modules: ["core"]')
        runner = Runner(stdout='{"modules": ["core"], "format": "app"}')
        spoken = self.run_app(runner, text="analyze this app for entry")
        self.assertEqual(spoken.text, rea.MISSING_FIELD)
        self.assertNotIn("version", spoken.text)
        self.assertNotIn("core", spoken.text)

    def test_personal_data_is_redacted_before_the_answer_and_the_log(self):
        payload = {
            "modules": ["core"],
            "note": "ada@example.com 555-010-1234 sk-abcDEF123456 Bearer abcdefghijklmnop /Users/someone/notes",
        }
        runner = Runner(stdout=json.dumps(payload))
        spoken = self.run_app(runner)
        for secret in (
            "ada@example.com",
            "555-010-1234",
            "sk-abcDEF123456",
            "Bearer abcdefghijklmnop",
            "/Users/someone",
        ):
            self.assertNotIn(secret, spoken.text, secret)
        self.assertIn("[redacted]", spoken.text)
        self.assertIn("core", spoken.text)
        _path, raw, body = self.read_logs()[0]
        for secret in (
            "ada@example.com",
            "555-010-1234",
            "sk-abcDEF123456",
            "Bearer abcdefghijklmnop",
            "/Users/someone",
        ):
            self.assertNotIn(secret, raw, secret)
            self.assertNotIn(secret, body["output"], secret)
            self.assertNotIn(secret, body["answer"], secret)
        mode = os.stat(_path).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_screenshot_identity_is_used_and_pixels_are_not(self):
        runner = Runner(stdout='{"modules": ["core"]}')
        pixels = b"\x89PNG" + b"not-an-app"
        spoken = self.run_app(
            runner,
            front={},
            screenshot={
                "name": "Notes",
                "bundle_id": "com.example.notes",
                "path": "/Applications/My App.app",
                "pixels": pixels,
                "image": "do-not-read",
            },
        )
        self.assertIn("core", spoken.text)
        analyze_argv = runner.calls[1][0]
        self.assertEqual(analyze_argv[3], "/Applications/My App.app")
        joined = " ".join(analyze_argv)
        self.assertNotIn("do-not-read", joined)
        self.assertNotIn("PNG", joined)


class KidsTests(Base):
    def test_kids_app_is_structure_only(self):
        payload = {
            "modules": ["lesson"],
            "imports": ["ui"],
            "progress": {"level": 4, "email": "learner@example.com"},
            "user": {"name": "Student Name"},
        }
        front = self.front(
            name="Learning",
            bundle_id="com.example.kids.learning",
            path="/Applications/Learning.app",
        )
        runner = Runner(stdout=json.dumps(payload))
        spoken = self.run_app(runner, front=front)
        self.assertTrue(spoken.text.startswith("Structure only."))
        self.assertIn('modules: ["lesson"]', spoken.text)
        self.assertIn('imports: ["ui"]', spoken.text)
        for secret in ("learner@example.com", "Student Name", "progress", "level"):
            self.assertNotIn(secret, spoken.text, secret)
        _path, raw, body = self.read_logs()[0]
        self.assertNotIn("learner@example.com", raw)
        self.assertNotIn("Student Name", body["output"])
        self.assertEqual(runner.calls[1][0][2], "analyze")

        runner = Runner(stdout=json.dumps(payload))
        spoken = self.run_app(runner, text="analyze this app for progress", front=front)
        self.assertEqual(spoken.text, rea.MISSING_FIELD)
        self.assertNotIn("learner@example.com", spoken.text)


class RetentionTests(Base):
    def test_cleanup_deletes_files_older_than_seven_days(self):
        self.assertEqual(REA_LOG_RETENTION_DAYS, 7)
        os.makedirs(self.logs)
        old = os.path.join(self.logs, "old.json")
        boundary = os.path.join(self.logs, "boundary.json")
        fresh = os.path.join(self.logs, "fresh.json")
        for path, age in ((old, 8), (boundary, 7), (fresh, 6)):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{}\n")
            stamp = (NOW - timedelta(days=age)).timestamp()
            os.utime(path, (stamp, stamp))
        removed = rea.cleanup_logs(self.logs, NOW)
        self.assertIn(old, removed)
        self.assertIn(boundary, removed)
        self.assertFalse(os.path.exists(old))
        self.assertFalse(os.path.exists(boundary))
        self.assertTrue(os.path.exists(fresh))

    def test_each_command_cleans_old_logs(self):
        os.makedirs(self.logs)
        old = os.path.join(self.logs, "old.json")
        fresh = os.path.join(self.logs, "fresh.json")
        with open(old, "w", encoding="utf-8") as handle:
            handle.write('{"answer": "old"}\n')
        with open(fresh, "w", encoding="utf-8") as handle:
            handle.write('{"answer": "fresh"}\n')
        os.utime(old, ((NOW - timedelta(days=8)).timestamp(),) * 2)
        os.utime(fresh, ((NOW - timedelta(days=6)).timestamp(),) * 2)
        runner = Runner()
        self.run_app(runner, front=self.front(
            name=SECRET_NAME,
            bundle_id=SECRET_BUNDLE,
            path=SECRET_PATH,
            site=SECRET_SITE,
        ))
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(fresh))
        self.assertEqual(runner.calls, [])

    def test_a_refused_log_is_only_a_timestamp_and_refused(self):
        runner = Runner()
        spoken = self.run_app(runner, front=self.front(
            name=SECRET_NAME,
            bundle_id=SECRET_BUNDLE,
            path=SECRET_PATH,
            site=SECRET_SITE,
        ))
        self.assertEqual(spoken.text, rea.REFUSAL)
        self.assertEqual(runner.calls, [])
        logs = self.read_logs()
        self.assertEqual(len(logs), 1)
        _path, raw, body = logs[0]
        self.assertEqual(set(body.keys()), {"timestamp", "refused"})
        self.assertEqual(body["refused"], "refused")
        self.assertEqual(body["timestamp"], "2026-10-27T12:00:00Z")
        for secret in (SECRET_NAME, SECRET_BUNDLE, SECRET_PATH, SECRET_SITE, "output", "input", "answer", "modules"):
            self.assertNotIn(secret, raw, secret)


class FailClosedTests(Base):
    def test_a_missing_file_refuses_every_run(self):
        missing = os.path.join(self.root, "missing-blocklist.json")
        runner = Runner()
        spoken = self.run_app(runner, blocklist_path=missing, front=self.front(
            name=SECRET_NAME,
            bundle_id=SECRET_BUNDLE,
            path=SECRET_PATH,
            site=SECRET_SITE,
        ))
        self.assertEqual(spoken.text, rea.REFUSAL)
        self.assertEqual(runner.calls, [])
        _path, raw, body = self.read_logs()[0]
        self.assertEqual(set(body.keys()), {"timestamp", "refused"})
        self.assertEqual(body["refused"], "refused")
        for secret in (SECRET_NAME, SECRET_BUNDLE, SECRET_PATH, SECRET_SITE):
            self.assertNotIn(secret, raw)

    def test_invalid_files_refuse_before_spawn(self):
        samples = (
            "",
            "{",
            "[]",
            "null",
            '"nope"',
            '{"blocked_bundle_ids": "UNIQUE_INVALID_TOKEN"}',
            '{"blocked_bundle_ids": [1]}',
            '{"kids_app_ids": {"id": "com.example.kids"}}',
        )
        for sample in samples:
            for path in self.log_files():
                os.remove(path)
            with open(self.block, "w", encoding="utf-8") as handle:
                handle.write(sample)
            runner = Runner()
            spoken = self.run_app(runner, front=self.front(
                name=SECRET_NAME,
                bundle_id=SECRET_BUNDLE,
                path=SECRET_PATH,
            ))
            self.assertEqual(spoken.text, rea.REFUSAL, sample)
            self.assertEqual(runner.calls, [], sample)
            _path, raw, body = self.read_logs()[0]
            self.assertEqual(set(body.keys()), {"timestamp", "refused"}, sample)
            self.assertNotIn("UNIQUE_INVALID_TOKEN", raw, sample)
            self.assertNotIn(SECRET_BUNDLE, raw, sample)

    def test_an_unreadable_file_refuses(self):
        from unittest import mock
        real_open = open

        def guarded(path, *args, **kwargs):
            if path == self.block:
                raise OSError("denied")
            return real_open(path, *args, **kwargs)

        runner = Runner()
        with mock.patch("builtins.open", guarded):
            spoken = self.run_app(runner, front=self.front(
                name=SECRET_NAME,
                bundle_id=SECRET_BUNDLE,
                path=SECRET_PATH,
            ))
        self.assertEqual(spoken.text, rea.REFUSAL)
        self.assertEqual(runner.calls, [])
        _path, raw, body = self.read_logs()[0]
        self.assertEqual(set(body.keys()), {"timestamp", "refused"})
        self.assertNotIn(SECRET_NAME, raw)

    def test_an_incomplete_file_still_applies_builtin_rules(self):
        self.write_blocklist({})
        runner = Runner(stdout='{"modules": ["core"]}')
        spoken = self.run_app(runner)
        self.assertIn('modules: ["core"]', spoken.text)
        self.assertEqual(len(runner.calls), 2)
        for front in (
            {"bundle_id": "com.example.loanapp", "name": "Desk", "path": "/Applications/Desk.app"},
            {"bundle_id": "com.example.credittool", "name": "Desk", "path": "/Applications/Desk.app"},
            {"bundle_id": "com.example.investing", "name": "Desk", "path": "/Applications/Desk.app"},
            {"bundle_id": "com.example.brokerage", "name": "Desk", "path": "/Applications/Desk.app"},
            {"bundle_id": "com.example.payroll", "name": "Desk", "path": "/Applications/Desk.app"},
            {"name": "Safari", "bundle_id": "com.apple.Safari", "path": "/Applications/Safari.app"},
            {"name": "Google Chrome", "bundle_id": "com.google.Chrome", "path": "/Applications/Google Chrome.app", "site": "notes.example"},
            {"name": "Firefox", "bundle_id": "org.mozilla.firefox", "path": "/Applications/Firefox.app"},
            {"name": "Microsoft Edge", "bundle_id": "com.microsoft.edgemac", "path": "/Applications/Microsoft Edge.app"},
            {"name": "Arc", "bundle_id": "company.thebrowser.Browser", "path": "/Applications/Arc.app"},
            {"name": "Brave", "bundle_id": "com.brave.Browser", "path": "/Applications/Brave Browser.app"},
            {"name": "TextEdit", "bundle_id": "com.apple.TextEdit", "path": "/Applications/TextEdit.app"},
            {"name": "Messages", "bundle_id": "COM.APPLE.MobileSMS", "path": "/Applications/Messages.app"},
        ):
            for path in self.log_files():
                os.remove(path)
            runner = Runner()
            spoken = self.run_app(runner, front=self.front(**front))
            self.assertEqual(spoken.text, rea.REFUSAL, front["bundle_id"])
            self.assertEqual(runner.calls, [], front["bundle_id"])
            _path, raw, body = self.read_logs()[0]
            self.assertEqual(set(body.keys()), {"timestamp", "refused"}, front["bundle_id"])
            self.assertNotIn(front["bundle_id"], raw)
            self.assertNotIn(front["name"], raw)


class MoneyHashTests(Base):
    def test_a_hashed_fixture_matches_a_prefix_and_a_domain(self):
        salt = "ab" * 16
        hashes = rea.hash_money_ids(
            ["com.fixturevendor.app"],
            ["fixture-money.example"],
            salt,
        )
        table = {"salt": salt, "hashes": hashes}
        self.assertNotIn("fixturevendor", "".join(hashes))
        self.assertNotIn("ca.gov", rea.money_forms("timesheet.benefits.ca.gov"))
        self.assertIn("benefits.ca.gov", rea.money_forms("timesheet.benefits.ca.gov"))
        runner = Runner()
        spoken = self.run_app(runner, money=table, front=self.front(
            name="Desk",
            bundle_id="com.fixturevendor.desktop",
            path="/Applications/Desk.app",
        ))
        self.assertEqual(spoken.text, rea.REFUSAL)
        self.assertEqual(runner.calls, [])
        runner = Runner()
        spoken = self.run_app(runner, money=table, front=self.front(
            name="Notes",
            bundle_id="com.example.notes",
            path="/Applications/Notes.app",
            site="https://login.fixture-money.example/start",
        ))
        self.assertEqual(spoken.text, rea.REFUSAL)
        self.assertEqual(runner.calls, [])
        state = {"salt": salt, "hashes": [rea.hash_money_value("benefits.ca.gov", salt)]}
        self.assertTrue(rea.is_builtin_money({
            "bundle_id": "com.example.notes",
            "name": "Notes",
            "site": "https://portal.benefits.ca.gov/login",
        }, state))
        self.assertFalse(rea.is_builtin_money({
            "bundle_id": "com.example.notes",
            "name": "Notes",
            "site": "https://other.ca.gov/",
        }, state))
        runner = Runner(stdout='{"modules": ["core"]}')
        spoken = self.run_app(runner, money=table)
        self.assertIn('modules: ["core"]', spoken.text)
        self.assertEqual(runner.calls[1][0][2], "analyze")

    def test_shipped_hashes_are_digests_and_do_not_block_notes(self):
        path = rea.money_hash_path()
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
        data = json.loads(raw)
        self.assertEqual(set(data), {"salt", "hashes"})
        self.assertRegex(data["salt"], r"^[0-9a-f]{32}$")
        self.assertGreaterEqual(len(data["hashes"]), 1)
        for item in data["hashes"]:
            self.assertRegex(item, r"^[0-9a-f]{64}$")
        self.assertNotIn(".", raw)
        self.assertFalse(rea.is_builtin_money({
            "name": "Notes",
            "bundle_id": "com.example.notes",
            "path": "/Applications/Notes.app",
            "site": "notes.example",
        }))

    def test_the_hash_script_prints_digests_without_ids(self):
        import importlib.util
        import io
        import sys
        path = os.path.join(self.root, "ids.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({
                "bundle_ids": ["com.fixturevendor.app"],
                "domains": ["fixture-money.example"],
            }, handle)
        spec = importlib.util.spec_from_file_location(
            "rea_money_hashes_script",
            os.path.join(ROOT, "scripts", "rea_money_hashes.py"),
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        stdout = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = stdout
            code = module.main(["rea_money_hashes.py", path])
        finally:
            sys.stdout = old
        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertNotIn("fixturevendor", text)
        self.assertNotIn("fixture-money", text)
        payload = json.loads(text)
        self.assertEqual(set(payload), {"salt", "hashes"})
        self.assertTrue(payload["hashes"])
        self.assertRegex(payload["hashes"][0], r"^[0-9a-f]{64}$")

    def test_spoken_answer_is_short_and_the_log_keeps_the_rest(self):
        self.assertEqual(REA_SPOKEN_CAP, 300)
        payload = {"modules": ["m" * 800]}
        runner = Runner(stdout=json.dumps(payload))
        spoken = self.run_app(runner)
        self.assertLessEqual(len(spoken.text), 300)
        self.assertGreater(len(spoken.text), 200)
        self.assertIn("[trimmed]", spoken.text)
        _path, _raw, body = self.read_logs()[0]
        self.assertGreater(len(body["answer"]), len(spoken.text))
        self.assertIn("m" * 400, body["answer"])
        self.assertNotIn("m" * 400, spoken.text)


class LocalBlocklistTests(Base):
    def test_each_local_blocklist_entry_is_refused(self):
        if not os.path.isfile(REA_BLOCKLIST_PATH):
            self.skipTest("local blocklist is not on this machine")
        rules = rea.load_blocklist(REA_BLOCKLIST_PATH)
        self.assertIsNotNone(rules, "local blocklist is invalid")
        kids = {item.lower() for item in rules["kids_app_ids"]}
        fronts = []
        for bundle in rules["blocked_bundle_ids"]:
            if bundle.lower() in kids:
                continue
            fronts.append(self.front(
                name="Desk",
                bundle_id=bundle,
                path="/Applications/Desk.app",
                site="",
            ))
        for name in rules["blocked_names"]:
            fronts.append(self.front(
                name=name,
                bundle_id="com.example.desk",
                path="/Applications/Desk.app",
                site="",
            ))
        for site in rules["blocked_sites"]:
            fronts.append(self.front(
                name="Desk",
                bundle_id="com.example.desk",
                path="/Applications/Desk.app",
                site=site,
            ))
        for front in fronts:
            for path in self.log_files():
                os.remove(path)
            runner = Runner()
            spoken = self.run_app(runner, blocklist_path=REA_BLOCKLIST_PATH, front=front)
            self.assertEqual(spoken.text, rea.REFUSAL)
            self.assertEqual(runner.calls, [])
            _path, _raw, body = self.read_logs()[0]
            self.assertEqual(set(body.keys()), {"timestamp", "refused"})
