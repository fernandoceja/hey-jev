"""PR 8c follow-up: every brief section has a hard timeout, and one that never returns cannot hold the brief.

The stubs here never return (a threading.Event that is never set), like a stalled EventKit or osascript call.
The timeouts are shrunk for the tests so they run in well under a second each.
"""
import contextlib
import io
import threading
import time
import unittest

import commands.brief as brief


def _never_returns(*_args, **_kwargs):
    threading.Event().wait()  # never set: this call does not come back


class _Stubs:
    """Replace every brief section with an instant empty stub, restore them after."""

    NAMES = ("speak_date", "speak_weather", "speak_today_schedule", "speak_next_shift", "speak_due",
             "sweep_reminder_line", "gmail_brief_line")

    def __init__(self):
        self._saved = {name: getattr(brief, name) for name in self.NAMES}
        self._saved_limits = (brief.BRIEF_SECTION_SECONDS, brief.BRIEF_TOTAL_SECONDS)

    def __enter__(self):
        brief.speak_date = lambda: "Today is Saturday."
        brief.speak_weather = lambda: "It's 61 degrees."
        brief.speak_today_schedule = lambda: "Your calendar is clear today."
        brief.speak_next_shift = lambda: "No shift in the next two weeks."
        brief.speak_due = lambda limit=3: "Nothing is due in the next 7 days."
        brief.sweep_reminder_line = lambda today=None: None
        brief.gmail_brief_line = lambda: None
        brief.BRIEF_SECTION_SECONDS, brief.BRIEF_TOTAL_SECONDS = 0.3, 2.0
        return self

    def __exit__(self, *exc):
        for name, value in self._saved.items():
            setattr(brief, name, value)
        brief.BRIEF_SECTION_SECONDS, brief.BRIEF_TOTAL_SECONDS = self._saved_limits
        return False


def _brief_with_log():
    out = io.StringIO()
    started = time.monotonic()
    with contextlib.redirect_stdout(out):
        line = brief.speak_brief()
    return line, out.getvalue(), time.monotonic() - started


class SectionTimeoutTests(unittest.TestCase):
    def test_a_calendar_that_never_returns_is_skipped_and_the_brief_still_speaks(self):
        with _Stubs():
            brief.speak_today_schedule = _never_returns
            line, log, elapsed = _brief_with_log()
        self.assertIn("I couldn't check your calendar just now.", line)
        self.assertIn("It's 61 degrees.", line)  # the other sections still speak
        self.assertIn("No shift in the next two weeks.", line)
        self.assertIn("brief: calendar timeout", log)
        self.assertLess(elapsed, 2.0)

    def test_every_section_that_never_returns_gets_its_fallback_within_the_cap(self):
        with _Stubs():
            for name in ("speak_weather", "speak_today_schedule", "speak_next_shift", "speak_due"):
                setattr(brief, name, _never_returns)
            line, log, elapsed = _brief_with_log()
        self.assertIn("I couldn't check the weather just now.", line)
        self.assertIn("I couldn't check your calendar just now.", line)
        self.assertIn("I couldn't check your shifts just now.", line)
        self.assertIn("I couldn't check your due list just now.", line)
        for name in ("weather", "calendar", "next_shift", "due"):
            self.assertIn("brief: {0} timeout".format(name), log)
        self.assertLess(elapsed, brief.BRIEF_TOTAL_SECONDS)

    def test_a_stalled_mail_or_sweep_is_left_out_without_a_fallback(self):
        with _Stubs():
            brief.gmail_brief_line = _never_returns
            brief.sweep_reminder_line = _never_returns
            line, log, _elapsed = _brief_with_log()
        self.assertNotIn("mail", line.lower())
        self.assertIn("brief: mail timeout", log)
        self.assertIn("brief: sweep timeout", log)
        self.assertIn("Your calendar is clear today.", line)

    def test_a_section_that_raises_gets_its_fallback_and_says_why_in_the_log(self):
        def broken():
            raise OSError("no calendar store")

        with _Stubs():
            brief.speak_today_schedule = broken
            line, log, _elapsed = _brief_with_log()
        self.assertIn("I couldn't check your calendar just now.", line)
        self.assertIn("brief: calendar failed: OSError", log)


class OrderAndCapTests(unittest.TestCase):
    def test_sections_keep_their_order_in_the_spoken_line(self):
        with _Stubs():
            line, _log, _elapsed = _brief_with_log()
        self.assertLess(line.index("Today is"), line.index("61 degrees"))
        self.assertLess(line.index("61 degrees"), line.index("calendar is clear"))
        self.assertLess(line.index("calendar is clear"), line.index("No shift"))
        self.assertLess(line.index("No shift"), line.index("Nothing is due"))

    def test_each_healthy_section_logs_its_time(self):
        with _Stubs():
            _line, log, _elapsed = _brief_with_log()
        for name in ("date", "weather", "calendar", "next_shift", "due", "sweep", "mail"):
            self.assertIn("brief: {0} ok in ".format(name), log, name)
            self.assertIn("ms", log)

    def test_the_whole_brief_is_capped_even_when_every_section_stalls(self):
        with _Stubs():
            brief.BRIEF_SECTION_SECONDS, brief.BRIEF_TOTAL_SECONDS = 0.5, 0.8
            for name in ("speak_date", "speak_weather", "speak_today_schedule", "speak_next_shift", "speak_due",
                         "sweep_reminder_line", "gmail_brief_line"):
                setattr(brief, name, _never_returns)
            _line, _log, elapsed = _brief_with_log()
        self.assertLess(elapsed, 0.8 + 0.5)

    def test_the_real_limits_are_six_seconds_per_section_and_twenty_in_total(self):
        self.assertEqual(brief.BRIEF_SECTION_SECONDS, 6.0)
        self.assertEqual(brief.BRIEF_TOTAL_SECONDS, 20.0)

    def test_the_sections_run_through_the_timed_gather(self):
        import inspect
        source = inspect.getsource(brief.speak_brief)
        self.assertIn("_gather(sections)", source)
        self.assertNotIn("speak_weather()", source)  # no bare calls that could block the caller


if __name__ == "__main__":
    unittest.main()
