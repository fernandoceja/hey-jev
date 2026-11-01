"""Polish for replies (PR 8D follow-up). Voice cues such as "[clear throat]" are kept for the audio and hidden on
screen. A clarify or retry reply shows its text with no read-aloud offer. Headless: the audio is a recording stub."""
import ast
import os
import threading
import unittest

from commands.brief_offer import display_text, speech_chunks

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _extract(name):
    with open(os.path.join(ROOT, "siri.py"), encoding="utf-8") as handle:
        source = handle.read()
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.Module(body=[node], type_ignores=[]), source
    raise AssertionError("no " + name)


class DisplayTextTests(unittest.TestCase):
    def test_voice_cues_are_removed_from_the_screen_text(self):
        self.assertEqual(display_text("[clear throat] Sorry, say that again?"), "Sorry, say that again?")
        self.assertEqual(display_text("[cheerful] Done. [chuckling] Both sorted."), "Done. Both sorted.")

    def test_any_bracketed_cue_is_removed(self):
        self.assertEqual(display_text("Ok [sighing] fine [whispers] really"), "Ok fine really")

    def test_text_without_cues_is_unchanged_apart_from_spacing(self):
        self.assertEqual(display_text("  Hello   there. "), "Hello there.")

    def test_empty_and_non_text_input(self):
        self.assertEqual(display_text(None), "")
        self.assertEqual(display_text(""), "")
        self.assertEqual(display_text("[clear throat]"), "")

    def test_the_audio_input_keeps_its_cues(self):
        chunks = speech_chunks("[clear throat] Sorry, say that again?")
        self.assertEqual(chunks, ["[clear throat] Sorry, say that again?"])


class OfferReplyTests(unittest.TestCase):
    """_offer_reply is extracted from siri.py and run with stubs, so the real branch logic is exercised."""

    def setUp(self):
        module, _ = _extract("_offer_reply")
        self.emitted = []
        self.prefetched = []
        self.offered = []
        self.timers = []

        class Audio:
            def prefetch(inner, chunks):
                self.prefetched.append(chunks)

        class Offer:
            def offer(inner):
                self.offered.append(True)

        class FakeTimer:
            def __init__(inner, *args):
                self.timers.append(args)

            daemon = False

            def start(inner):
                self.timers.append("started")

        class FakeThreading:
            Timer = FakeTimer

        namespace = {
            "emit": lambda notify, state, text: self.emitted.append((state, text)),
            "print": lambda *a, **k: None,
            "BRIEF_OFFER_LINE": "Want me to read it out loud?",
            "BRIEF_AUDIO": Audio(),
            "brief_offer": Offer(),
            "speech_chunks": speech_chunks,
            "display_text": display_text,
            "threading": FakeThreading,
            "OFFER_WINDOW_SECONDS": 60,
            "_expire_brief_offer": lambda: None,
        }
        exec(compile(module, "siri-extract", "exec"), namespace)
        self.offer_reply = namespace["_offer_reply"]

    def test_a_clarify_reply_shows_text_without_the_offer_or_audio(self):
        self.offer_reply("[clear throat] Sorry, say that again?", None, offer=False)
        self.assertEqual(self.emitted, [("Ready", "Sorry, say that again?")])
        self.assertEqual(self.prefetched, [])
        self.assertEqual(self.offered, [])
        self.assertEqual(self.timers, [])

    def test_a_normal_reply_keeps_the_offer_and_its_audio_cues(self):
        self.offer_reply("[cheerful] It's sunny.", None)
        self.assertEqual(self.emitted, [("Ready", "It's sunny. Want me to read it out loud?")])
        self.assertEqual(self.prefetched, [["[cheerful] It's sunny."]])
        self.assertEqual(self.offered, [True])

    def test_a_failure_still_shows_its_state_without_the_offer(self):
        self.offer_reply("Something went wrong on my end.", None, failed=True, offer=False)
        self.assertEqual(self.emitted, [("Something went wrong", "Something went wrong on my end.")])

    def test_no_visible_cue_text_reaches_the_screen(self):
        self.offer_reply("[sighing] Hm [chuckling] okay.", None)
        for state, text in self.emitted:
            self.assertNotIn("[", text)
            self.assertNotIn("]", text)


class WiringTests(unittest.TestCase):
    def test_clarify_lines_are_delivered_without_the_offer(self):
        with open(os.path.join(ROOT, "siri.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertEqual(source.count('offer=kind != "clarify"'), 2)

    def test_the_screen_line_on_the_direct_speech_path_is_display_text(self):
        module, _ = _extract("_deliver")
        self.assertIn("display_text(line)", ast.unparse(module))


if __name__ == "__main__":
    unittest.main()
