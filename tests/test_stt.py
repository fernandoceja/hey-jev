"""Whisper hotwords. No model, no microphone, no network."""
import os
import unittest

import commands
from commands.stt import (
    NO_SPEECH_MAX,
    WHISPER_HOTWORDS,
    is_hotword_echo,
    transcript_from_segments,
    whisper_transcribe_kwargs,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAMES = (
    "ChatGPT", "Claude", "Grok", "Gemini", "Perplexity", "CapCut",
    "WorkJam", "UKG", "Spotify", "YouTube TV", "iMessage",
    "password", "passwords",
    "earthquake", "earthquakes", "hazard", "hazards", "wildfire", "fires",
)


class _Seg(object):
    def __init__(self, text, no_speech_prob=0.0):
        self.text = text
        self.no_speech_prob = no_speech_prob


class TestHotwords(unittest.TestCase):
    def test_hotwords_are_not_the_prompt(self):
        wake = whisper_transcribe_kwargs(None)
        self.assertIsNone(wake["initial_prompt"])
        self.assertEqual(wake["hotwords"], WHISPER_HOTWORDS)
        self.assertFalse(wake["condition_on_previous_text"])
        self.assertTrue(wake["vad_filter"])
        self.assertEqual(wake["language"], "en")
        for name in NAMES:
            self.assertIn(name, wake["hotwords"])
        # The hint is a name list, not a command the model can echo as "Open ...".
        self.assertNotIn("Open ", wake["hotwords"])
        self.assertNotEqual(wake["initial_prompt"], wake["hotwords"])

        prompt = "Open Spotify. Open ChatGPT."
        ptt = whisper_transcribe_kwargs(prompt)
        self.assertEqual(ptt["initial_prompt"], prompt)
        self.assertNotIn(WHISPER_HOTWORDS, ptt["initial_prompt"])
        self.assertEqual(ptt["hotwords"], WHISPER_HOTWORDS)

    def test_silence_and_a_hotword_echo_are_blank(self):
        self.assertEqual(NO_SPEECH_MAX, 0.6)
        silence = _Seg("ChatGPT, Claude, Grok, Gemini, Perplexity, CapCut, WorkJam, UKG, Spotify, YouTube TV, iMessage", 0.95)
        self.assertEqual(transcript_from_segments([silence], drop_noise=True), "")
        # A confident echo of the hint, with no command word, is still dropped.
        echo = _Seg("ChatGPT Claude Grok", 0.1)
        self.assertTrue(is_hotword_echo(echo.text))
        self.assertEqual(transcript_from_segments([echo], drop_noise=True), "")
        self.assertEqual(transcript_from_segments([echo], drop_noise=False), "")
        self.assertEqual(transcript_from_segments([_Seg("YouTube TV", 0.2)], drop_noise=True), "")
        # The score Whisper already uses: at the threshold the words are kept.
        borderline = _Seg("Open ChatGPT.", NO_SPEECH_MAX)
        self.assertEqual(transcript_from_segments([borderline], drop_noise=True), "Open ChatGPT.")

    def test_a_real_command_is_kept_and_silence_around_it_is_not(self):
        segments = (
            _Seg("Open ChatGPT.", 0.91),
            _Seg("Open ChatGPT.", 0.2),
            _Seg("Spotify", 0.99),
        )
        self.assertEqual(transcript_from_segments(segments, drop_noise=True), "Open ChatGPT.")
        self.assertEqual(
            transcript_from_segments([_Seg("Open YouTube TV.", 0.05)], drop_noise=True),
            "Open YouTube TV.",
        )
        self.assertFalse(is_hotword_echo("Open ChatGPT."))

    def test_siri_passes_the_hint_and_drops_silence_on_push_to_talk(self):
        source = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        self.assertIn("whisper_transcribe_kwargs", source)
        self.assertIn("transcript_from_segments", source)
        self.assertIn("transcribe(audio, COMMAND_PROMPT, drop_noise=True)", source)
        self.assertIn("WAKE_PROMPT = None", source)
        self.assertNotIn("initial_prompt=prompt)", source)
