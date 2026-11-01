"""Regression: unmatched input must reach the normal reply, not a raw Python error.

A typo such as "idy my downloads" matches no local command, so the turn ends as a clarify, a canned reply or an LLM
answer. Those paths never run an action, so `done` used to be read before it was set (UnboundLocalError). The test
pulls the real _handle_turn out of siri.py and runs it with stubs, so it fails on the old code. Headless: siri.py's
Mac-only imports are not loaded.
"""
import ast
import os
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _siri_source():
    with open(os.path.join(ROOT, "siri.py"), encoding="utf-8") as handle:
        return handle.read()


def _extract(source, name):
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("no " + name + " in siri.py")


def _assigned_constant(source, name):
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("no " + name + " in siri.py")


class Harness:
    """Runs the real _handle_turn with every outside call stubbed. decide_result is what decide(ans, text) returns."""

    def __init__(self, decide_result, llm_answer="A helpful answer.", actions=None):
        self.delivered = []
        self.events = []
        self.decide_result = decide_result
        source = _siri_source()
        module = ast.Module(body=[_extract(source, "_handle_turn")], type_ignores=[])
        commands = types.SimpleNamespace(
            is_password_lookup=lambda text: False,
            zoe_claims=lambda text: False,
            clear_confirmation=lambda: None,
            confirmation_status=lambda text: None,
            is_private_message_request=lambda text: False,
            note_question=lambda text: None,
            isolate_confirmations=lambda payload: payload,
            CONFIRM=set(),
            PASSWORD_KEYS=set(),
            LocalSpeech=type("LocalSpeech", (), {}),
            BriefPlayback=type("BriefPlayback", (), {}),
        )
        brief_offer = types.SimpleNamespace(answer=lambda text: (None, False))
        self.ns = {
            "misses": 0,
            "fix_names": lambda text: text,
            "commands": commands,
            "brief_offer": brief_offer,
            "emit": lambda notify, state, text: self.events.append((state, text)),
            "_deliver": self._deliver,
            "decide": self._decide,
            "jev": lambda text: ({}, 0, 0.0),
            "ask_llm": lambda text: (llm_answer, 1, 0.0),
            "openrouter_model": lambda model: "model",
            "active_model": lambda: "model",
            "say_line": lambda key, **fmt: "[line:" + key + "]",
            "say": lambda line, notify: None,
            "split_actions": lambda text, ans: [],
            "SPEAK_FIRST": set(),
            "ACTIONS": actions or {},
            "_log_action_failure": lambda action, exc, private=False: self.events.append(("logged", action)),
            "_arm_prompt": lambda action, arg, text, reply_key, fmt: ("prompt", False),
            "_picked": lambda key: key,
            "direct_speech": None,
            "BRIEF_AUDIO": None,
            "BRIEF_OFFER_LINE": "",
            "OFFER_WINDOW_SECONDS": 60,
            "traceback": None,
            "LAST_REPLY_TEXT": "",
            "_remember_reply": lambda line: None,
            "_direct_speech_on": lambda: True,
            "print": lambda *args, **kwargs: None,
            "REPLIES": {},
            "ready_text": lambda wake: "Ready",
        }
        exec(compile(module, "siri-extract", "exec"), self.ns)
        self.handle = self.ns["_handle_turn"]

    def _decide(self, ans, text=""):
        if ans is None:
            return None  # the early local-phrase check finds nothing
        return self.decide_result

    def _deliver(self, line, notify, reply_sink=None, private=False, failed=False):
        self.delivered.append({"line": line, "failed": failed})

    def run(self, text):
        return self.handle(text, None, None)


class UnmatchedInputTests(unittest.TestCase):
    def test_a_typo_clarifies_without_an_error(self):
        h = Harness(("clarify", None))
        h.run("idy my downloads")  # used to raise UnboundLocalError: done
        self.assertEqual(h.delivered, [{"line": "[line:clarify]", "failed": False}])

    def test_a_canned_reply_is_delivered_as_a_normal_reply(self):
        h = Harness(("reply", "info_time"))
        h.run("what's the time")
        self.assertEqual(h.delivered, [{"line": "[line:info_time]", "failed": False}])

    def test_an_llm_answer_is_delivered_as_a_normal_reply(self):
        h = Harness(("llm", None), llm_answer="Paris is the capital.")
        h.run("what is the capital of france")
        self.assertEqual(h.delivered, [{"line": "Paris is the capital.", "failed": False}])

    def test_a_failed_action_still_reports_failure_not_a_reply(self):
        def boom(arg, text):
            raise RuntimeError("secret detail that must not reach the user")

        payload = [(1.0, "boom", None, "unsupported", {})]
        h = Harness(("actions", payload), actions={"boom": boom})
        h.run("open the thing")
        self.assertEqual(h.delivered, [{"line": "[line:unsupported]", "failed": True}])
        self.assertIn(("logged", "boom"), h.events)
        self.assertNotIn("secret detail", str(h.delivered))

    def test_a_successful_action_is_not_a_failure(self):
        payload = [(1.0, "ok", None, "ok", {})]
        h = Harness(("actions", payload), actions={"ok": lambda arg, text: "Done it."})
        h.run("do the thing")
        self.assertEqual(h.delivered, [{"line": "Done it.", "failed": False}])


class RawErrorTextTests(unittest.TestCase):
    def test_no_user_facing_message_is_the_raw_exception(self):
        source = _siri_source()
        self.assertNotIn('"Something went wrong", str(exc)', source)

    def test_the_friendly_failure_line_has_no_error_text(self):
        line = _assigned_constant(_siri_source(), "FRIENDLY_FAILURE")
        self.assertTrue(line)
        for word in ("Error", "Exception", "referenced", "UnboundLocal", "{", "}"):
            self.assertNotIn(word, line)


if __name__ == "__main__":
    unittest.main()
