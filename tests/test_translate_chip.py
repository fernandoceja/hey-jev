"""PR 8b: the Translate chip. Pure logic only: no AppKit, no network, no audio. The clock is a fake."""
import unittest
from unittest import mock

import mini_bar
from commands import translate_chip as tc
from commands.clipboard_history import ClipboardHistory, Snapshot
from commands.translate_chip import (
    TRANSLATE_COMMAND,
    TRANSLATE_WINDOW_SECONDS,
    TranslateChip,
    classify_copy,
    log_line,
    translate_command,
)

SPANISH = "El informe trimestral está listo y necesitamos tu revisión antes del viernes."


class FakeClock(object):
    def __init__(self, start=100.0):
        self.now = float(start)

    def __call__(self):
        return self.now


def _chip(clock=None):
    clock = FakeClock() if clock is None else clock
    return TranslateChip(clock=clock), clock


class LanguageHeuristicTests(unittest.TestCase):
    def test_english_is_not_offered(self):
        self.assertEqual(
            classify_copy("The quarterly report is ready, and we need your review before Friday."),
            (False, "english"),
        )

    def test_common_european_languages_are_offered(self):
        samples = [
            SPANISH,
            "Le rapport trimestriel est prêt et nous avons besoin de votre avis avant vendredi.",
            "Der Quartalsbericht ist fertig und wir brauchen deine Prüfung bis Freitag.",
            "O relatório trimestral está pronto e precisamos da sua revisão até sexta.",
            "Il rapporto trimestrale è pronto e abbiamo bisogno della tua revisione entro venerdì.",
        ]
        for text in samples:
            self.assertEqual(classify_copy(text), (True, "non_english"), text)

    def test_non_latin_scripts_are_offered(self):
        self.assertEqual(classify_copy("这份季度报告已经准备好了，我们需要你在周五前审阅。"), (True, "non_english"))
        self.assertEqual(classify_copy("Квартальный отчёт готов, нам нужна ваша проверка до пятницы."),
                         (True, "non_english"))

    def test_mixed_text_with_both_languages_is_not_offered(self):
        # Two common English words and two common Spanish words: neither side clearly wins, so no chip.
        self.assertEqual(classify_copy("The team says el informe and la plan"), (False, "mixed"))

    def test_mostly_foreign_text_with_an_english_word_is_offered(self):
        self.assertEqual(
            classify_copy("Mira esta página https://es.wikipedia.org/wiki/Gato para más info sobre gatos"),
            (True, "non_english"),
        )

    def test_parentheses_in_prose_are_not_code(self):
        self.assertEqual(
            classify_copy("Esto (por ejemplo) es (muy) útil (sin duda) para (nosotros) hoy."),
            (True, "non_english"),
        )

    def test_short_strings_are_skipped(self):
        self.assertEqual(classify_copy("hola amigo"), (False, "short"))
        self.assertEqual(classify_copy("Hi there"), (False, "short"))
        self.assertEqual(classify_copy("12345 67890 11111 22222"), (False, "short"))

    def test_empty_strings_are_skipped(self):
        self.assertEqual(classify_copy(""), (False, "empty"))
        self.assertEqual(classify_copy("   \n\t "), (False, "empty"))
        self.assertEqual(classify_copy(None), (False, "empty"))

    def test_urls_are_skipped(self):
        self.assertEqual(classify_copy("https://example.com/some/path/here"), (False, "url"))
        self.assertEqual(classify_copy("www.example.org/a/b/c"), (False, "url"))

    def test_code_is_skipped(self):
        python = "def total(items):\n    return sum(i.price for i in items)"
        javascript = "const x = items.map((i) => i.price);\nconsole.log(x);"
        json_text = '{"name": "jev", "items": [1, 2, 3]}'
        for text in (python, javascript, json_text):
            self.assertEqual(classify_copy(text), (False, "code"), text)


class ChipWindowTests(unittest.TestCase):
    def test_non_english_copy_shows_the_chip(self):
        chip, _clock = _chip()
        result = chip.on_observation(1, "stored", SPANISH)
        self.assertEqual(result, ("shown", "non_english"))
        self.assertTrue(chip.visible())

    def test_chip_lasts_twenty_seconds_from_the_copy(self):
        self.assertEqual(TRANSLATE_WINDOW_SECONDS, 20.0)
        chip, clock = _chip()
        chip.on_observation(1, "stored", SPANISH)
        clock.now += 19.9
        self.assertTrue(chip.visible())
        self.assertIsNone(chip.expire_if_due())
        clock.now += 0.1  # now exactly 20 s after the copy
        self.assertFalse(chip.visible())
        self.assertEqual(chip.expire_if_due(), ("expired", "timeout"))
        self.assertIsNone(chip.expire_if_due())  # logged once

    def test_expiry_is_measured_from_the_copy_not_from_later_checks(self):
        chip, clock = _chip()
        chip.on_observation(1, "stored", SPANISH)
        self.assertTrue(chip.visible())
        for _ in range(40):  # 40 ticks of 0.5 s is 20 s: ticks do not extend the window
            clock.now += 0.5
            chip.expire_if_due()
        self.assertFalse(chip.visible())

    def test_pausing_hides_an_open_offer(self):
        chip, _clock = _chip()
        chip.on_observation(1, "stored", SPANISH)
        self.assertFalse(chip.visible(paused=True))
        self.assertEqual(chip.expire_if_due(paused=True), ("expired", "paused"))
        self.assertFalse(chip.visible())

    def test_a_newer_copy_replaces_the_offer(self):
        chip, _clock = _chip()
        chip.on_observation(1, "stored", SPANISH)
        result = chip.on_observation(2, "stored", "Just a normal English sentence about the weather today.")
        self.assertEqual(result, ("skipped", "english"))
        self.assertFalse(chip.visible())

    def test_same_observation_twice_is_ignored(self):
        chip, _clock = _chip()
        self.assertEqual(chip.on_observation(1, "stored", SPANISH), ("shown", "non_english"))
        self.assertIsNone(chip.on_observation(1, "stored", SPANISH))

    def test_duplicate_and_unchanged_do_not_change_the_offer(self):
        chip, _clock = _chip()
        chip.on_observation(1, "stored", SPANISH)
        self.assertIsNone(chip.on_observation(2, "duplicate", SPANISH))
        self.assertIsNone(chip.on_observation(3, "unchanged", ""))
        self.assertTrue(chip.visible())

    def test_initial_observation_without_status_is_ignored(self):
        chip, _clock = _chip()
        self.assertIsNone(chip.on_observation(0, None, ""))
        self.assertFalse(chip.visible())


class SkipTests(unittest.TestCase):
    def test_paused_history_never_shows_a_chip(self):
        chip, _clock = _chip()
        self.assertEqual(chip.on_observation(1, "paused", SPANISH), ("skipped", "paused"))
        self.assertFalse(chip.visible())

    def test_paused_flag_skips_even_a_stored_copy(self):
        chip, _clock = _chip()
        self.assertEqual(chip.on_observation(1, "stored", SPANISH, paused=True), ("skipped", "paused"))
        self.assertFalse(chip.visible())

    def test_password_manager_copies_never_reach_the_heuristic(self):
        chip, _clock = _chip()
        with mock.patch.object(tc, "classify_copy") as classify:
            self.assertEqual(chip.on_observation(1, "manager", SPANISH), ("skipped", "manager"))
            self.assertEqual(chip.on_observation(2, "concealed", SPANISH), ("skipped", "concealed"))
            self.assertEqual(chip.on_observation(3, "secret", SPANISH), ("skipped", "secret"))
            classify.assert_not_called()
        self.assertFalse(chip.visible())

    def test_a_password_copy_hides_an_open_offer(self):
        chip, _clock = _chip()
        chip.on_observation(1, "stored", SPANISH)
        chip.on_observation(2, "manager", "something copied from a vault")
        self.assertFalse(chip.visible())

    def test_log_lines_name_the_reason_and_never_the_text(self):
        chip, _clock = _chip()
        for seq, status, text in ((1, "manager", SPANISH), (2, "stored", "hola amigo")):
            line = log_line(chip.on_observation(seq, status, text))
            self.assertTrue(line.startswith("translate chip: skipped "), line)
            self.assertNotIn("informe", line)
            self.assertNotIn("hola", line)


class ClickTests(unittest.TestCase):
    def test_click_inside_the_window_returns_the_translate_turn(self):
        chip, clock = _chip()
        chip.on_observation(1, "stored", "El informe\n   trimestral está listo.")
        clock.now += 5.0
        command, outcome, reason = chip.click()
        self.assertEqual(command, "translate this to English: El informe trimestral está listo.")
        self.assertEqual((outcome, reason), ("clicked", ""))
        self.assertFalse(chip.visible())

    def test_a_second_click_does_nothing(self):
        chip, _clock = _chip()
        chip.on_observation(1, "stored", SPANISH)
        chip.click()
        self.assertEqual(chip.click(), (None, "skipped", "no_offer"))

    def test_click_after_twenty_seconds_does_nothing(self):
        chip, clock = _chip()
        chip.on_observation(1, "stored", SPANISH)
        clock.now += TRANSLATE_WINDOW_SECONDS
        self.assertEqual(chip.click(), (None, "expired", "timeout"))

    def test_click_while_paused_does_nothing(self):
        chip, _clock = _chip()
        chip.on_observation(1, "stored", SPANISH)
        self.assertEqual(chip.click(paused=True), (None, "skipped", "paused"))
        self.assertFalse(chip.visible())

    def test_nothing_runs_without_a_click(self):
        chip, clock = _chip()
        with mock.patch.object(tc, "translate_command") as build:
            chip.on_observation(1, "stored", SPANISH)
            self.assertTrue(chip.visible())
            for _ in range(60):  # a minute of ticks, expiry included
                clock.now += 0.5
                chip.visible()
                chip.expire_if_due()
            build.assert_not_called()
        self.assertFalse(chip.visible())

    def test_translate_command_is_one_line_and_keeps_the_text(self):
        command = translate_command("  Hola,\n  ¿cómo estás?  ")
        self.assertEqual(command, TRANSLATE_COMMAND + ": Hola, ¿cómo estás?")
        self.assertNotIn("\n", command)


class ClipboardSourceTests(unittest.TestCase):
    """The chip reads ClipboardHistory.last_observation, so the history's own rules apply first."""

    def test_stored_copy_carries_its_text_to_the_chip(self):
        history = ClipboardHistory()
        status = history.observe(Snapshot(1, text=SPANISH, frontmost="Safari"))
        seq, last_status, text = history.last_observation()
        self.assertEqual((seq, last_status, text), (1, "stored", SPANISH))
        self.assertEqual(status, "stored")

    def test_password_manager_copy_is_not_stored_or_carried(self):
        history = ClipboardHistory()
        history.observe(Snapshot(1, text=SPANISH, frontmost="1Password"))
        seq, status, text = history.last_observation()
        self.assertEqual((seq, status, text), (1, "manager", None))
        self.assertEqual(history.texts(), [])

    def test_paused_copy_is_not_stored_or_carried(self):
        history = ClipboardHistory()
        history.set_paused(True)
        history.observe(Snapshot(1, text=SPANISH, frontmost="Safari"))
        self.assertEqual(history.last_observation(), (1, "paused", None))

    def test_end_to_end_password_copy_never_shows_the_chip(self):
        history = ClipboardHistory()
        chip, _clock = _chip()
        history.observe(Snapshot(1, text=SPANISH, frontmost="Safari"))
        chip.on_observation(*history.last_observation(), paused=history.is_paused())
        self.assertTrue(chip.visible())
        chip.on_observation(*_obs(history, 2, SPANISH, "Bitwarden"), paused=history.is_paused())
        self.assertFalse(chip.visible())


def _obs(history, count, text, front):
    history.observe(Snapshot(count, text=text, frontmost=front))
    return history.last_observation()


class MiniBarChipTests(unittest.TestCase):
    def tearDown(self):
        mini_bar.set_translate_chip(False)

    def test_default_popover_page_is_unchanged(self):
        mini_bar.set_translate_chip(False)
        self.assertEqual(mini_bar.popover_chip_ids(0), mini_bar.POPOVER_CHIP_PAGES[0])

    def test_chip_takes_the_first_slot_and_keeps_the_count(self):
        base = mini_bar.popover_chip_ids(0)
        mini_bar.set_translate_chip(True)
        shown = mini_bar.popover_chip_ids(0)
        self.assertEqual(shown[0], mini_bar.TRANSLATE_CHIP_ID)
        self.assertEqual(len(shown), len(base))
        self.assertEqual(shown[1:], base[:-1])

    def test_footer_layout_keeps_the_same_chip_count(self):
        mini_bar.set_translate_chip(False)
        off = mini_bar.popover_footer_layout(300.0, 200.0)
        mini_bar.set_translate_chip(True)
        on = mini_bar.popover_footer_layout(300.0, 200.0)
        self.assertEqual(len(on["chips"]), len(off["chips"]))
        self.assertIn(mini_bar.TRANSLATE_CHIP_ID, [spec["id"] for spec in on["chips"]])
        self.assertEqual(on["footer_bottom"], off["footer_bottom"])

    def test_chip_has_a_title_and_a_width(self):
        self.assertEqual(mini_bar.POPOVER_CHIPS[mini_bar.TRANSLATE_CHIP_ID]["title"], "Translate")
        self.assertGreater(mini_bar.chip_width(mini_bar.TRANSLATE_CHIP_ID), 0)

    def test_chip_has_no_fixed_phrase(self):
        # The click builds its command from the copied text in the app, so there is no phrase to queue here.
        self.assertIsNone(mini_bar.chip_command_plan(mini_bar.TRANSLATE_CHIP_ID))

    def test_set_translate_chip_reports_its_state(self):
        self.assertTrue(mini_bar.set_translate_chip(True))
        self.assertTrue(mini_bar.translate_chip_on())
        self.assertFalse(mini_bar.set_translate_chip(False))


if __name__ == "__main__":
    unittest.main()
