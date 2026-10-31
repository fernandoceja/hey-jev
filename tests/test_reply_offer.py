"""Every command reply is text first, with the offer; explicit audio asks, Zoe, and bridge turns stay spoken (PR 8c)."""
import ast
import contextlib
import os
import threading
import unittest

from commands.brief_offer import answer_kind, audio_request_kind

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return handle.read()


def _func(source, name):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError("no function " + name)


class AudioAskTests(unittest.TestCase):
    def test_explicit_last_reply_asks_are_recognised(self):
        for text in ("read it", "Read it out loud.", "say it out loud", "read that aloud"):
            self.assertEqual(audio_request_kind(text), "last", text)

    def test_the_morning_brief_ask_is_recognised(self):
        for text in ("play my morning brief", "Play the morning brief."):
            self.assertEqual(audio_request_kind(text), "brief", text)

    def test_ordinary_requests_are_not_audio_asks(self):
        for text in ("what's the weather", "start my day", "read my messages", "", None):
            self.assertIsNone(audio_request_kind(text), text)

    def test_saying_it_out_loud_is_a_yes_while_the_offer_is_live(self):
        self.assertEqual(answer_kind("say it out loud"), "yes")
        self.assertEqual(answer_kind("read that aloud"), "yes")


class DirectSpeechTests(unittest.TestCase):
    """The flag is extracted from siri.py and run here, so the thread-local behaviour is checked for real."""

    @classmethod
    def setUpClass(cls):
        tree = ast.parse(_source("siri.py"))
        names = {"_DIRECT", "direct_speech", "_direct_speech_on"}
        body = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", None) in names for t in node.targets):
                body.append(node)
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names:
                body.append(node)
        namespace = {"threading": threading, "contextlib": contextlib}
        exec(compile(ast.Module(body=body, type_ignores=[]), "siri-extract", "exec"), namespace)
        cls.direct = staticmethod(namespace["direct_speech"])
        cls.is_direct = staticmethod(namespace["_direct_speech_on"])

    def test_replies_are_offered_unless_a_block_asks_for_direct_speech(self):
        self.assertFalse(self.is_direct())
        with self.direct():
            self.assertTrue(self.is_direct())
        self.assertFalse(self.is_direct())

    def test_the_flag_is_restored_after_an_error(self):
        with self.assertRaises(ValueError):
            with self.direct():
                raise ValueError("boom")
        self.assertFalse(self.is_direct())

    def test_the_flag_is_per_thread(self):
        seen = []
        with self.direct():
            worker = threading.Thread(target=lambda: seen.append(self.is_direct()))
            worker.start()
            worker.join()
        self.assertEqual(seen, [False])


class ReplyWiringTests(unittest.TestCase):
    def setUp(self):
        self.siri = _source("siri.py")

    def test_every_command_reply_goes_through_deliver(self):
        handle = _func(self.siri, "_handle_turn")
        self.assertNotIn("say(line, notify)\n    emit(notify, \"Ready\", line)", handle)
        self.assertIn('_deliver("Add an OpenRouter or OpenAI key first.", notify)', self.siri)
        self.assertIn("_deliver(line, notify)", _func(self.siri, "_ask_jev_turn"))
        finish = _func(self.siri, "_finish_confirmed")
        self.assertNotIn("say(", finish)
        self.assertIn("_deliver(line, notify, failed=True)", finish)

    def test_deliver_offers_unless_direct_speech_is_on(self):
        deliver = _func(self.siri, "_deliver")
        self.assertIn("if _direct_speech_on():", deliver)
        self.assertIn("say(line, notify)", deliver)
        self.assertIn("_offer_reply(line, notify, failed=failed)", deliver)
        self.assertLess(deliver.index("if _direct_speech_on():"), deliver.index("_offer_reply(line"))

    def test_the_bridge_and_zoe_stay_spoken(self):
        self.assertIn("with direct_speech():  # the phone's command is spoken on this Mac, as before",
                      _func(self.siri, "bridge_turn"))
        zoe = _func(self.siri, "_handle_turn")
        block = zoe[zoe.index("if commands.zoe_claims(text):"):zoe.index("# A pending yes/no is decided here")]
        self.assertIn("with direct_speech():  # Zoe keeps spoken replies", block)
        self.assertIn("_run_zoe_allowed(guard.get", block)

    def test_an_explicit_audio_ask_routes_before_the_turn_and_plays_directly(self):
        handle = _func(self.siri, "handle")
        self.assertIn('if kind == "last" and not brief_offer.pending():', handle)
        self.assertIn("return _read_last_reply(notify, reply_sink)", handle)
        self.assertIn('if kind == "brief":', handle)
        self.assertIn("with direct_speech():", handle)

    def test_the_memo_playback_stays_spoken(self):
        turn = _func(self.siri, "_handle_turn")
        self.assertIn("if brief_paths:  # a memo is playing", turn)
        self.assertIn("with direct_speech():\n            _deliver(line, notify, failed=not done)", turn)
        local = _func(self.siri, "_run_local")
        self.assertIn("with direct_speech():  # the memo plays its own audio", local)

    def test_speak_first_replies_stay_spoken(self):
        local = _func(self.siri, "_run_local")
        self.assertIn("with direct_speech():  # spoken before the action", local)

    def test_proactive_alerts_still_speak_directly(self):
        self.assertIn("say(timer_done_line(t), notify)", self.siri)
        self.assertIn("say(line, notify)\n            spoken = True", self.siri)

    def test_a_read_back_is_remembered_and_read_aloud_directly(self):
        self.assertIn("_remember_reply(line)", _func(self.siri, "_deliver"))
        read = _func(self.siri, "_read_last_reply")
        self.assertIn("with direct_speech():", read)
        self.assertIn("_deliver(LAST_REPLY_TEXT, notify, reply_sink)", read)


if __name__ == "__main__":
    unittest.main()
