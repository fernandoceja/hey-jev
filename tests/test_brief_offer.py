"""PR 8c: the brief as text, with an offer to read it aloud. Offer state machine, yes/no phrases, sentence splitter,
and the wiring in siri and the popover. Headless: the audio and the network are not touched."""
import ast
import os
import unittest

from commands.brief_offer import (BRIEF_OFFER_LINE, OFFER_WINDOW_SECONDS, BriefOffer, answer_kind, speech_chunks,
                                  split_sentences)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class OfferStateTests(unittest.TestCase):
    def test_no_offer_means_no_outcome_and_nothing_consumed(self):
        offer = BriefOffer(FakeClock())
        self.assertEqual(offer.answer("yes"), (None, False))
        self.assertFalse(offer.pending())

    def test_a_yes_within_the_window_is_accepted_and_consumed(self):
        clock = FakeClock()
        offer = BriefOffer(clock)
        offer.offer()
        clock.now += 10
        self.assertTrue(offer.pending())
        self.assertEqual(offer.answer("yes"), ("accepted", True))
        self.assertEqual(offer.answer("yes"), (None, False))  # one answer only

    def test_a_no_is_declined_and_consumed(self):
        clock = FakeClock()
        offer = BriefOffer(clock)
        offer.offer()
        self.assertEqual(offer.answer("no thanks"), ("declined", True))

    def test_any_other_reply_dismisses_the_offer_but_is_not_consumed(self):
        clock = FakeClock()
        offer = BriefOffer(clock)
        offer.offer()
        self.assertEqual(offer.answer("what's the weather"), ("declined", False))
        self.assertFalse(offer.pending())

    def test_the_offer_expires_after_sixty_seconds_with_no_answer(self):
        clock = FakeClock()
        offer = BriefOffer(clock)
        offer.offer()
        clock.now += OFFER_WINDOW_SECONDS - 0.1
        self.assertIsNone(offer.expire_if_due())
        clock.now += 0.2
        self.assertEqual(offer.expire_if_due(), "expired")
        self.assertIsNone(offer.expire_if_due())  # reported once

    def test_an_answer_after_the_window_is_expired_not_a_yes(self):
        clock = FakeClock()
        offer = BriefOffer(clock)
        offer.offer()
        clock.now += OFFER_WINDOW_SECONDS + 1
        self.assertEqual(offer.answer("yes"), ("expired", False))  # the yes runs as a request, not as audio

    def test_a_new_brief_restarts_the_window(self):
        clock = FakeClock()
        offer = BriefOffer(clock)
        offer.offer()
        clock.now += 50
        offer.offer()
        clock.now += 50
        self.assertTrue(offer.pending())

    def test_the_window_is_sixty_seconds(self):
        self.assertEqual(OFFER_WINDOW_SECONDS, 60.0)

    def test_the_offer_line_is_the_one_the_user_sees(self):
        self.assertEqual(BRIEF_OFFER_LINE, "Want me to read it out loud?")


class YesNoPhraseTests(unittest.TestCase):
    def test_yes_phrases_by_voice_or_typing(self):
        for phrase in ("yes", "Yes!", "yeah", "yep", "sure", "read it", "Read it out loud.", "read it aloud",
                       "play it", "Play it.", "play audio", "Play audio", "yes please", "play it out loud"):
            self.assertEqual(answer_kind(phrase), "yes", phrase)

    def test_no_phrases(self):
        for phrase in ("no", "No thanks", "no thank you", "nope", "not now"):
            self.assertEqual(answer_kind(phrase), "no", phrase)

    def test_anything_else_is_other(self):
        for phrase in ("what's the weather", "yes and open mail", "read the mail", "", None, "yesterday",
                       "play my morning brief"):
            self.assertEqual(answer_kind(phrase), "other", repr(phrase))


class SentenceSplitterTests(unittest.TestCase):
    def test_a_decimal_number_does_not_end_a_sentence(self):
        self.assertEqual(split_sentences("G 05.72 hrs on the clock. Next up at 11 AM."),
                         ["G 05.72 hrs on the clock.", "Next up at 11 AM."])

    def test_a_time_with_no_punctuation_stays_whole(self):
        self.assertEqual(split_sentences("Shift starts at 11 AM and runs late"), ["Shift starts at 11 AM and runs late"])

    def test_an_em_dash_does_not_split(self):
        self.assertEqual(split_sentences("Pay day — tomorrow. Done."), ["Pay day — tomorrow.", "Done."])

    def test_an_abbreviation_does_not_split(self):
        self.assertEqual(split_sentences("It is 9 a.m. Next up is the trash."), ["It is 9 a.m. Next up is the trash."])

    def test_voice_tags_stay_with_their_sentence(self):
        self.assertEqual(split_sentences("[chuckling] Hi there. Bye now."), ["[chuckling] Hi there.", "Bye now."])

    def test_a_lowercase_continuation_does_not_split(self):
        self.assertEqual(split_sentences("Pay day is on the 1st. and then it resets."),
                         ["Pay day is on the 1st. and then it resets."])

    def test_the_brief_splits_into_its_sentences_in_order(self):
        brief = "Today is Saturday. It's 61 degrees. Your calendar is clear today. Nothing is due."
        self.assertEqual(split_sentences(brief), ["Today is Saturday.", "It's 61 degrees.",
                                                  "Your calendar is clear today.", "Nothing is due."])

    def test_no_words_are_lost(self):
        brief = "G 05.72 hrs. 11 AM — shift. [chuckling] Done at 9 a.m. Bye."
        self.assertEqual(" ".join(split_sentences(brief)), brief)

    def test_chunks_are_the_sentences_when_they_are_short(self):
        brief = "Today is Saturday. It's 61 degrees. Next up at 11 AM."
        self.assertEqual(speech_chunks(brief), split_sentences(brief))

    def test_a_long_sentence_is_cut_near_150_characters_without_losing_words(self):
        long_one = "word " * 80 + "end."
        chunks = speech_chunks(long_one)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 150 for chunk in chunks))
        self.assertEqual(" ".join(chunks), long_one.strip())

    def test_the_first_chunk_is_the_first_sentence_when_it_is_short_enough(self):
        self.assertEqual(speech_chunks("Hello there. Then a long rest of the brief " + "more " * 60)[0], "Hello there.")

    def test_empty_input_gives_no_pieces(self):
        for value in ("", "   ", None):
            self.assertEqual(split_sentences(value), [])


def _source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return handle.read()


def _func(source, name):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError("no function " + name)


class SiriWiringTests(unittest.TestCase):
    def setUp(self):
        self.siri = _source("siri.py")

    def test_the_brief_is_delivered_as_text_not_spoken(self):
        deliver = _func(self.siri, "_deliver_brief")
        self.assertNotIn("say(", deliver)
        self.assertIn('emit(notify, "Ready", text + " " + BRIEF_OFFER_LINE)', deliver)
        self.assertIn('print("brief: text shown", flush=True)', deliver)
        self.assertIn("BRIEF_AUDIO.prefetch(speech_chunks(text))", deliver)

    def test_the_local_runner_sends_info_brief_to_text_first(self):
        run_local = _func(self.siri, "_run_local")
        self.assertIn('if action == "info_brief" and isinstance(result, str):', run_local)
        self.assertIn("_deliver_brief(result, notify, reply_sink)", run_local)

    def test_a_reply_to_the_offer_is_checked_before_routing(self):
        handle = _func(self.siri, "handle")
        self.assertLess(handle.index("brief_offer.answer(text)"), handle.index("decide(None, text)"))
        self.assertIn('print(f"brief: audio offer {outcome}", flush=True)', handle)
        self.assertIn("BRIEF_AUDIO.play(notify)", handle)

    def test_the_offer_expires_on_a_timer_and_discards_the_audio(self):
        expire = _func(self.siri, "_expire_brief_offer")
        self.assertIn('print("brief: audio offer expired", flush=True)', expire)
        self.assertIn("BRIEF_AUDIO.discard()", expire)
        self.assertIn("threading.Timer(OFFER_WINDOW_SECONDS + 0.5", _func(self.siri, "_deliver_brief"))

    def test_only_the_first_chunk_is_made_when_the_text_is_shown(self):
        audio = _func(self.siri, "BriefAudio")
        prefetch = _func(audio, "prefetch")
        self.assertIn("fetch_tts(first_chunk)", prefetch)
        self.assertNotIn("range(1", prefetch)
        self.assertIn('"brief: first sentence ready in', prefetch)

    def test_the_rest_is_made_only_when_playback_starts_and_logs_separately(self):
        audio = _func(self.siri, "BriefAudio")
        play = _func(audio, "play")
        self.assertIn("rest()", play)
        rest = _func(audio, "rest")
        self.assertIn("range(1, len(chunks))", rest)
        self.assertIn("fetch_tts(chunks[index])", rest)
        self.assertIn('"brief: rest of the brief ready in', rest)

    def test_the_audio_logs_its_first_sound_and_is_not_played_unasked(self):
        audio = _func(self.siri, "BriefAudio")
        self.assertIn('"tts: first audio in', audio)
        self.assertIn('subprocess.run(["afplay", path])', audio)
        self.assertNotIn("afplay", _func(self.siri, "_deliver_brief"))

    def test_fish_calls_still_go_through_the_cached_fetch(self):
        audio = _func(self.siri, "BriefAudio")
        self.assertIn("fetch_tts(", audio)
        self.assertNotIn("commands.synthesize_speech", audio)

    def test_a_declined_offer_clears_its_buttons(self):
        handle = _func(self.siri, "handle")
        self.assertIn('emit(notify, "Ready", "")  # clears the offer', handle)

    def test_zoe_and_the_bridge_do_not_get_the_brief_offer(self):
        self.assertNotIn("_deliver_brief", _func(self.siri, "_run_zoe_allowed"))
        self.assertNotIn("brief_offer", _source("commands/bridge.py"))


class PopoverWiringTests(unittest.TestCase):
    def test_the_offer_buttons_send_the_phrase_through_the_text_path(self):
        ui = _source("assistant_ui.py")
        self.assertIn('self._answer_brief_offer("play it")', _func(ui, "briefPlayAudio_"))
        self.assertIn('self._answer_brief_offer("no thanks")', _func(ui, "briefNoThanks_"))
        answer = _func(ui, "_answer_brief_offer")
        self.assertIn('self._dispatch_text_plan({"kind": "run", "control": ("text", phrase), "reveal_main": False})',
                      answer)

    def test_the_buttons_show_for_the_offer_line_and_hide_on_other_updates(self):
        update = _func(_source("assistant_ui.py"), "updateStatus_")
        self.assertIn("detail.rstrip().endswith(BRIEF_OFFER_LINE)", update)
        self.assertIn("self._show_brief_offer_buttons(True)", update)
        self.assertIn("self._show_brief_offer_buttons(False)", update)

    def test_the_buttons_are_on_the_full_window_too(self):
        ui = _source("assistant_ui.py")
        show = _func(ui, "_show_brief_offer_buttons")
        self.assertIn("self._offer_full_pair()", show)
        self.assertIn("self._place_full_offer_buttons()", show)
        self.assertIn("full_input_bg", _func(ui, "_offer_full_pair"))

    def test_the_buttons_hide_when_the_window_runs_out(self):
        show = _func(_source("assistant_ui.py"), "_show_brief_offer_buttons")
        self.assertIn('self.performSelector_withObject_afterDelay_("hideBriefOfferButtons:", None, OFFER_WINDOW_SECONDS)',
                      show)


if __name__ == "__main__":
    unittest.main()
