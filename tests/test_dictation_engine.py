"""Scribe v2 as a dictation engine. No network, no microphone, no Whisper model."""
import importlib
import io
import os
import tempfile
import unittest
from concurrent.futures import Future
from contextlib import redirect_stdout
from unittest import mock

import commands
from commands.clipboard_history import Snapshot
from commands.dictation_engine import (
    FALLBACK_FAILED,
    FALLBACK_OPENAI,
    FALLBACK_WHISPER,
    OPENAI_MODEL,
    OPENAI_TRANSCRIPTIONS_URL,
    OPENROUTER_TRANSCRIPTIONS_URL,
    PROMPT,
    SCRIBE_MODEL,
    SCRIBE_USD_PER_SECOND,
    _post,
    scribe_body,
    transcribe_wav,
)
from commands.passwords import parse_password_query
from dictation import START, Dictation

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WAV = b"RIFF-fake-wav"
OA = "openai-key-not-for-scribe"
OR = "openrouter-key-for-scribe"
# Looks like a key to the clipboard filter. Not a real credential.
SECRET = "sk-proj-abcdefgH123456"


class Resp(object):
    def __init__(self, text="hello there", status=200, body=""):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._text = text
        self.text = body or text

    def json(self):
        if not self.ok:
            return {"error": self.text}
        return {"text": self._text}

    def raise_for_status(self):
        if not self.ok:
            err = Exception("http {0}".format(self.status_code))
            err.response = self
            raise err


class TestEngineSetting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "dictation-engine.txt")
        commands.set_dictation_engine_path(self.path)
        self.addCleanup(commands.set_dictation_engine_path, None)

    def test_openai_is_the_default_and_the_commands_persist(self):
        self.assertEqual(commands.dictation_engine(), "openai")
        self.assertFalse(os.path.exists(self.path))
        phrases = (
            ("use scribe for dictation", "dictation_scribe", "scribe", "Dictation will use Scribe."),
            ("use openai for dictation", "dictation_openai", "openai", "Dictation will use OpenAI."),
            ("Use Scribe for dictation.", "dictation_scribe", "scribe", "Dictation will use Scribe."),
            ("please use openai for dictation", "dictation_openai", "openai", "Dictation will use OpenAI."),
            ("use scribe for dictation please", "dictation_scribe", "scribe", "Dictation will use Scribe."),
            ("hey jev, use scribe for dictation", "dictation_scribe", "scribe", "Dictation will use Scribe."),
            ("hey jev, please use openai for dictation", "dictation_openai", "openai", "Dictation will use OpenAI."),
            ("use open ai for dictation", "dictation_openai", "openai", "Dictation will use OpenAI."),
        )
        for phrase, key, saved, line in phrases:
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertEqual(commands.set_dictation_engine(saved), line, phrase)
            self.assertEqual(commands.dictation_engine(), saved, phrase)
            self.assertEqual(open(self.path, encoding="utf-8").read().strip(), saved, phrase)
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("whisper\n")
        self.assertEqual(commands.dictation_engine(), "openai")
        self.assertNotIn("dictation_scribe", commands.BRIDGE_ALLOW)
        self.assertNotIn("dictation_openai", commands.BRIDGE_ALLOW)
        self.assertEqual(len(commands.BRIDGE_ALLOW), 30)

    def test_these_phrases_do_not_start_dictation_or_steal_password_or_clipboard(self):
        for phrase in ("use scribe for dictation", "use openai for dictation", "hey jev, use scribe for dictation"):
            self.assertIsNone(START.match(phrase), phrase)
            self.assertNotEqual(commands.route_before_api(phrase), "password_lookup", phrase)
            self.assertNotEqual(commands.route_before_api(phrase), "clipboard_history", phrase)
        self.assertIsNone(commands.route_before_api("transcribe"))
        self.assertIsNone(commands.route_before_api("stop transcribing"))
        self.assertEqual(commands.route_before_api("password for Netflix"), "password_lookup")
        self.assertEqual(commands.route_before_api("my password is hunter2"), "password_lookup")
        self.assertEqual(commands.route_before_api("clipboard history"), "clipboard_history")
        refused = parse_password_query("my password is hunter2")
        self.assertTrue(refused.refused)
        self.assertEqual(refused.term, "")
        self.assertNotIn("hunter2", refused.term)


class TestTranscription(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "dictation-engine.txt")
        commands.set_dictation_engine_path(self.path)
        self.addCleanup(commands.set_dictation_engine_path, None)
        self.calls = []
        self.sleeps = []
        self.local_calls = []
        self.saved = []

        def boom(*_args, **_kwargs):
            raise AssertionError("default poster was called")

        engine_module = importlib.import_module("commands.dictation_engine")
        patch = mock.patch.object(engine_module, "_post", boom)
        patch.start()
        self.addCleanup(patch.stop)

    def _post(self, url, headers, data=None, files=None, json_body=None, timeout=90, answers=None):
        self.calls.append({
            "url": url,
            "headers": headers,
            "data": data,
            "files": files,
            "json": json_body,
            "timeout": timeout,
        })
        return answers.pop(0)

    def _run(self, answers, engine="openai", keys=(OA, OR), local_text="from whisper", local_error=None):
        queue = list(answers)

        def post(url, headers, data=None, files=None, json_body=None, timeout=90):
            return self._post(url, headers, data, files, json_body, timeout, queue)

        def local():
            self.local_calls.append(True)
            if local_error is not None:
                raise local_error
            return local_text

        buf = io.StringIO()
        with redirect_stdout(buf):
            try:
                text = transcribe_wav(
                    WAV, lambda: keys, engine=engine, post=post, local=local,
                    sleep=self.sleeps.append, save_failed=lambda: self.saved.append(True),
                )
            except Exception as exc:
                return None, buf.getvalue(), exc
        return text, buf.getvalue(), None

    def test_openai_engine_keeps_the_current_request(self):
        text, log, err = self._run([Resp("noted")])
        self.assertIsNone(err)
        self.assertEqual(text, "noted")
        self.assertEqual(log, "")
        self.assertEqual(self.local_calls, [])
        self.assertEqual(self.saved, [])
        call = self.calls[0]
        self.assertEqual(call["url"], OPENAI_TRANSCRIPTIONS_URL)
        self.assertEqual(call["headers"]["Authorization"], "Bearer {0}".format(OA))
        self.assertNotIn(OR, call["headers"]["Authorization"])
        self.assertEqual(call["data"]["model"], "gpt-4o-mini-transcribe")
        self.assertEqual(call["data"]["prompt"], PROMPT)
        self.assertEqual(call["files"]["file"][0], "dictation.wav")
        self.assertEqual(call["files"]["file"][1], WAV)
        self.assertEqual(call["timeout"], 90)
        self.assertIsNone(call["json"])

    def test_openai_engine_uses_openrouter_when_there_is_no_openai_key(self):
        text, log, err = self._run([Resp("through the router")], keys=("", OR))
        self.assertIsNone(err)
        self.assertEqual(text, "through the router")
        self.assertEqual(log, "")
        call = self.calls[0]
        self.assertEqual(call["url"], OPENROUTER_TRANSCRIPTIONS_URL)
        self.assertEqual(call["headers"]["Authorization"], "Bearer {0}".format(OR))
        self.assertEqual(call["json"]["model"], OPENAI_MODEL)
        self.assertEqual(call["json"]["provider"]["options"]["openai"]["prompt"], PROMPT)
        self.assertEqual(call["json"]["input_audio"]["format"], "wav")
        self.assertNotIn("clipboard", str(call["json"]))

    def test_openai_retries_server_errors_and_stops_on_a_normal_client_error(self):
        text, _log, err = self._run([Resp(status=500, body="nope"), Resp(status=500, body="nope"), Resp("third")])
        self.assertIsNone(err)
        self.assertEqual(text, "third")
        self.assertEqual(self.sleeps, [1, 2])
        self.assertEqual(len(self.calls), 3)
        self.calls.clear()
        self.sleeps.clear()
        text, log, err = self._run([Resp(status=400, body="bad audio")])
        self.assertIsNone(text)
        self.assertIsNotNone(err)
        self.assertEqual(self.sleeps, [])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.saved, [True])
        self.assertIn("openai said: 400 bad audio", log)
        self.assertNotIn("scribe failed", log)
        self.calls.clear()
        self.saved.clear()
        text, _log, err = self._run([Resp(status=429, body="slow"), Resp("after")])
        self.assertEqual(text, "after")
        self.assertEqual(self.sleeps, [1])

    def test_scribe_posts_the_documented_request_with_the_openrouter_key(self):
        self.assertEqual(SCRIBE_MODEL, "elevenlabs/scribe-v2")
        self.assertEqual(OPENROUTER_TRANSCRIPTIONS_URL, "https://openrouter.ai/api/v1/audio/transcriptions")
        self.assertEqual(SCRIBE_USD_PER_SECOND, 0.000031)
        self.assertAlmostEqual(SCRIBE_USD_PER_SECOND * 60, 0.00186)
        body = scribe_body(WAV)
        self.assertEqual(body["model"], "elevenlabs/scribe-v2")
        self.assertEqual(body["language"], "en")
        self.assertEqual(body["input_audio"]["format"], "wav")
        self.assertNotIn("prompt", body)
        self.assertNotIn("provider", body)
        commands.set_dictation_engine("scribe")
        marker = "CLIPBOARD-ITEM-SHOULD-NOT-BE-IN-THE-REQUEST"
        commands.CLIPBOARD.clear_items()
        commands.CLIPBOARD.last_change = None

        def _reset_clip():
            commands.CLIPBOARD.clear_items()
            commands.CLIPBOARD.last_change = None

        self.addCleanup(_reset_clip)
        self.assertEqual(commands.CLIPBOARD.observe(Snapshot(1, marker)), "stored")
        text, log, err = self._run([Resp("scribed")], engine=commands.dictation_engine())
        self.assertIsNone(err)
        self.assertEqual(text, "scribed")
        self.assertEqual(log, "")
        self.assertEqual(self.local_calls, [])
        self.assertEqual(len(self.calls), 1)
        call = self.calls[0]
        self.assertEqual(call["url"], OPENROUTER_TRANSCRIPTIONS_URL)
        self.assertEqual(call["headers"]["Authorization"], "Bearer {0}".format(OR))
        self.assertNotIn(OA, str(call))
        self.assertEqual(call["json"]["model"], SCRIBE_MODEL)
        self.assertNotIn(marker, str(call))
        self.assertNotIn("prompt", call["json"])
        self.assertIsNone(call["files"])

    def test_scribe_falls_back_to_openai_then_local_whisper_with_one_line(self):
        text, log, err = self._run([Resp(status=503, body="upstream"), Resp("from openai")], engine="scribe")
        self.assertIsNone(err)
        self.assertEqual(text, "from openai")
        self.assertEqual(log, FALLBACK_OPENAI + "\n")
        self.assertEqual(self.local_calls, [])
        self.assertEqual(self.saved, [])
        self.assertEqual(self.calls[0]["json"]["model"], SCRIBE_MODEL)
        self.assertEqual(self.calls[1]["url"], OPENAI_TRANSCRIPTIONS_URL)
        self.assertNotIn("upstream", log)
        self.calls.clear()
        text, log, err = self._run(
            [Resp(status=500, body="scribe down"), Resp(status=400, body="openai down")],
            engine="scribe", local_text="whisper heard it",
        )
        self.assertIsNone(err)
        self.assertEqual(text, "whisper heard it")
        self.assertEqual(log, FALLBACK_WHISPER + "\n")
        self.assertEqual(self.local_calls, [True])
        self.assertEqual(self.saved, [])
        self.assertNotIn("scribe down", log)
        self.assertNotIn("openai down", log)
        self.calls.clear()
        self.local_calls.clear()
        text, log, err = self._run(
            [Resp(status=500, body="scribe down"), Resp(status=400, body="openai down")],
            engine="scribe", local_error=RuntimeError("whisper exploded"),
        )
        self.assertIsNone(text)
        self.assertIsInstance(err, RuntimeError)
        self.assertEqual(log, FALLBACK_FAILED + "\n")
        self.assertEqual(self.saved, [True])
        self.assertEqual(log.count("\n"), 1)

    def test_scribe_without_an_openrouter_key_uses_the_openai_path(self):
        text, log, err = self._run([Resp("direct")], engine="scribe", keys=(OA, ""))
        self.assertIsNone(err)
        self.assertEqual(text, "direct")
        self.assertEqual(log, FALLBACK_OPENAI + "\n")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["url"], OPENAI_TRANSCRIPTIONS_URL)

    def test_a_dictated_secret_stays_out_of_clipboard_history(self):
        """The words can still be pasted. Clipboard history drops a secret, as before."""
        commands.CLIPBOARD.clear_items()
        commands.CLIPBOARD.last_change = None

        def _reset_clip():
            commands.CLIPBOARD.clear_items()
            commands.CLIPBOARD.last_change = None

        self.addCleanup(_reset_clip)
        d = Dictation("jev|jeff", lambda: ("", OR), 16000)
        d.start()
        done = Future()
        done.set_result(SECRET + " stop transcribing")
        d.chunks = [done]
        d.buffer = []
        history = os.path.join(self.tmp.name, "history.jsonl")
        buf = io.StringIO()
        with redirect_stdout(buf):
            text, failed, total = d.finish(history_path=history)
        self.assertEqual(failed, 0)
        self.assertEqual(total, 1)
        self.assertIn(SECRET, text)
        self.assertNotIn("stop transcribing", text.lower())
        self.assertEqual(commands.CLIPBOARD.observe(Snapshot(7, text)), "secret")
        self.assertEqual(commands.CLIPBOARD.texts(), [])
        self.assertNotIn(SECRET, commands.CLIPBOARD.spoken())
        plain = Dictation("jev|jeff", lambda: ("", OR), 16000)
        plain.start()
        heard = Future()
        heard.set_result("buy milk and eggs")
        plain.chunks = [heard]
        plain.buffer = []
        plain_text, _failed, _total = plain.finish(history_path=os.path.join(self.tmp.name, "plain.jsonl"))
        self.assertEqual(plain_text, "buy milk and eggs")
        self.assertEqual(commands.CLIPBOARD.observe(Snapshot(8, plain_text)), "stored")
        self.assertEqual(commands.CLIPBOARD.texts(), ["buy milk and eggs"])
        self.assertIn(SECRET, open(history, encoding="utf-8").read())
        self.assertNotIn(SECRET, buf.getvalue())

    def test_wake_and_command_whisper_are_unchanged(self):
        source = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        self.assertIn('WHISPER_MODEL = "small.en"', source)
        self.assertIn("WAKE_PROMPT = None", source)
        self.assertIn("transcribe(audio, COMMAND_PROMPT, drop_noise=True)", source)
        self.assertIn("transcribe(audio, WAKE_PROMPT, drop_noise=True)", source)
        self.assertIn("transcribe(audio, None, drop_noise=True)", source)
        self.assertIn("local_transcribe=dictation_whisper", source)
        self.assertIn('"dictation_scribe"', source)
        self.assertIn('"dictation_openai"', source)
        bridge = open(os.path.join(ROOT, "commands", "bridge.py"), encoding="utf-8").read()
        secrets = open(os.path.join(ROOT, "secrets_store.py"), encoding="utf-8").read()
        self.assertNotIn("dictation_scribe", bridge)
        self.assertNotIn("elevenlabs", secrets)
        self.assertEqual(_post.__module__, "commands.dictation_engine")


if __name__ == "__main__":
    unittest.main()
