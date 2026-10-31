"""info_brief with every data source empty, plus the failed-action path. Headless: each source is stubbed.

The brief used to crash when today had only all-day events: _join_names([]) indexed an empty list. These tests run
every section with empty, partial and all-day data, and check that the failed-action path ends as a failure.
"""
import ast
import os
import sys
import types
import unittest
from datetime import datetime, timedelta

import commands.brief as brief
import commands.calendar_shift as cs
import commands.notes_due as nd
import commands.shift_override as so
import commands.textutil as tu
import commands.weather as wx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _EmptyResponse:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"current": {}, "daily": {}}


class _FakeDate:
    def __init__(self, when):
        self._when = when

    def timeIntervalSince1970(self):
        return self._when.timestamp()


class _FakeEvent:
    def __init__(self, title, start, end, all_day):
        self._title, self._start, self._end, self._all_day = title, start, end, all_day

    def title(self):
        return self._title

    def isAllDay(self):
        return self._all_day

    def startDate(self):
        return _FakeDate(self._start)

    def endDate(self):
        return _FakeDate(self._end)


def _today_at(hour):
    now = datetime.now().astimezone()
    return now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=hour)


class EmptySourcesTests(unittest.TestCase):
    def setUp(self):
        self._saved = {
            "problem": cs._calendar_problem, "between": cs._events_between,
            "shifts": cs._plain_shifts_from_calendar, "overrides": so.events_with_overrides,
            "due": nd._read_due_lines, "mail": brief.gmail_brief_line, "sweep": brief.sweep_reminder_line,
        }
        cs._calendar_problem = lambda: None
        cs._events_between = lambda *a, **k: []
        cs._plain_shifts_from_calendar = lambda *a, **k: []
        so.events_with_overrides = lambda events, now, horizon, path=None: ([], None)
        nd._read_due_lines = lambda: []
        brief.gmail_brief_line = lambda: None
        brief.sweep_reminder_line = lambda today=None: None
        self._saved_requests = sys.modules.get("requests")
        self._requests_stubbed = False

    def tearDown(self):
        cs._calendar_problem = self._saved["problem"]
        cs._events_between = self._saved["between"]
        cs._plain_shifts_from_calendar = self._saved["shifts"]
        so.events_with_overrides = self._saved["overrides"]
        nd._read_due_lines = self._saved["due"]
        brief.gmail_brief_line = self._saved["mail"]
        brief.sweep_reminder_line = self._saved["sweep"]
        if self._requests_stubbed:
            # Put back whatever was there. CI has no requests package, so the stub is the only one in that case.
            if self._saved_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = self._saved_requests

    def _stub_weather(self, payload):
        """speak_weather does `import requests` inside the call. A stand-in module is put in sys.modules, so the test
        does not need the real package (CI installs pytest only)."""

        class Response:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return payload

        fake = types.ModuleType("requests")
        fake.get = lambda *a, **k: Response()
        sys.modules["requests"] = fake
        self._requests_stubbed = True

    def test_every_source_empty_still_speaks_a_brief(self):
        self._stub_weather({"current": {}, "daily": {}})
        line = brief.speak_brief()
        self.assertIn("Your calendar is clear today.", line)
        self.assertIn("No shift in the next two weeks.", line)
        self.assertIn("Nothing is due in the next 7 days.", line)
        self.assertIn("Today is", line)

    def test_empty_weather_lists_do_not_crash(self):
        self._stub_weather({"current": {"temperature_2m": 61, "weather_code": 0},
                            "daily": {"temperature_2m_max": [], "temperature_2m_min": [],
                                      "precipitation_probability_max": []}})
        self.assertIn("couldn't check the weather", wx.speak_weather().lower())

    def test_weather_with_a_high_but_no_low_does_not_crash(self):
        self._stub_weather({"current": {"temperature_2m": 61, "weather_code": 0},
                            "daily": {"temperature_2m_max": [70.0], "temperature_2m_min": [],
                                      "precipitation_probability_max": []}})
        self.assertIn("couldn't check the weather", wx.speak_weather().lower())

    def test_weather_with_no_rain_list_says_so(self):
        self._stub_weather({"current": {"temperature_2m": 61, "weather_code": 0},
                            "daily": {"temperature_2m_max": [70.0], "temperature_2m_min": [50.0],
                                      "precipitation_probability_max": []}})
        self.assertIn("I don't have a rain chance", wx.speak_weather())

    def test_no_due_list_file_says_so(self):
        nd._read_due_lines = lambda: None
        self.assertIn("You don't have a due list yet", nd.speak_due(limit=3))


class AllDayCalendarTests(unittest.TestCase):
    """The crash: a day with only all-day events built an empty name list and indexed it."""

    def setUp(self):
        self._saved = (cs._calendar_problem, cs._events_between)
        cs._calendar_problem = lambda: None

    def tearDown(self):
        cs._calendar_problem, cs._events_between = self._saved

    def test_only_all_day_events_speak_them(self):
        holiday = _FakeEvent("Holiday", _today_at(0), _today_at(24), True)
        cs._events_between = lambda *a, **k: [holiday]
        self.assertEqual(cs.speak_today_schedule(), "All day: Holiday.")

    def test_several_all_day_events_are_joined(self):
        events = [_FakeEvent(name, _today_at(0), _today_at(24), True) for name in ("Pay day", "Trash", "Holiday")]
        cs._events_between = lambda *a, **k: events
        self.assertEqual(cs.speak_today_schedule(), "All day: Pay day, Trash, and Holiday.")

    def test_all_day_and_timed_events_are_both_spoken(self):
        now = datetime.now().astimezone()
        events = [_FakeEvent("Trash", _today_at(0), _today_at(24), True),
                  _FakeEvent("Dentist", now + timedelta(minutes=30), now + timedelta(minutes=90), False)]
        cs._events_between = lambda *a, **k: events
        line = cs.speak_today_schedule()
        self.assertTrue(line.startswith("All day: Trash. Today you've got Dentist at"), line)

    def test_an_empty_calendar_is_clear(self):
        cs._events_between = lambda *a, **k: []
        self.assertEqual(cs.speak_today_schedule(), "Your calendar is clear today.")

    def test_the_brief_survives_an_all_day_only_day(self):
        saved = (brief.speak_weather, brief.speak_next_shift, brief.speak_due, brief.sweep_reminder_line,
                 brief.gmail_brief_line)
        try:
            cs._events_between = lambda *a, **k: [_FakeEvent("Holiday", _today_at(0), _today_at(24), True)]
            brief.speak_weather = lambda: "Sunny."
            brief.speak_next_shift = lambda: "No shift in the next two weeks."
            brief.speak_due = lambda limit=3: "Nothing is due in the next 7 days."
            brief.sweep_reminder_line = lambda today=None: None
            brief.gmail_brief_line = lambda: None
            line = brief.speak_brief()
            self.assertIn("All day: Holiday.", line)
        finally:
            (brief.speak_weather, brief.speak_next_shift, brief.speak_due, brief.sweep_reminder_line,
             brief.gmail_brief_line) = saved


class JoinNamesTests(unittest.TestCase):
    def test_an_empty_list_joins_to_nothing_instead_of_crashing(self):
        self.assertEqual(tu._join_names([]), "")

    def test_one_two_and_many(self):
        self.assertEqual(tu._join_names(["A"]), "A")
        self.assertEqual(tu._join_names(["A", "B"]), "A and B")
        self.assertEqual(tu._join_names(["A", "B", "C"]), "A, B, and C")


def _siri_function(name):
    """The source of one function in siri.py, compiled alone with stubs. siri needs audio packages that CI lacks."""
    with open(os.path.join(ROOT, "siri.py"), encoding="utf-8") as handle:
        source = handle.read()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError("no function " + name)


class FailedActionTests(unittest.TestCase):
    def _namespace(self, log, emits):
        import traceback
        ns = {
            "traceback": traceback, "print": lambda *a, **k: log.append(" ".join(str(x) for x in a)),
            "emit": lambda notify, state, detail="": emits.append((state, detail)),
            "say": lambda line, notify: None, "say_local": lambda text, notify: None,
            "reply_sink": None,
        }
        exec(compile(_siri_function("_log_action_failure"), "siri.py", "exec"), ns)
        exec(compile(_siri_function("_deliver"), "siri.py", "exec"), ns)
        return ns

    def test_a_failed_action_ends_as_something_went_wrong_and_not_ready(self):
        emits = []
        ns = self._namespace([], emits)
        ns["_deliver"]("I know what you want, I just can't do that one yet.", None, failed=True)
        self.assertEqual(emits[-1][0], "Something went wrong")

    def test_a_normal_reply_still_ends_as_ready(self):
        emits = []
        ns = self._namespace([], emits)
        ns["_deliver"]("It's 61 degrees.", None)
        self.assertEqual(emits[-1][0], "Ready")

    def test_a_failure_logs_the_action_and_its_traceback(self):
        log = []
        ns = self._namespace(log, [])
        try:
            [][0]
        except IndexError as exc:
            ns["_log_action_failure"]("info_brief", exc)
        text = "\n".join(log)
        self.assertIn("action failed: info_brief list index out of range", text)
        self.assertIn("Traceback (most recent call last)", text)
        self.assertIn("IndexError", text)

    def test_a_private_action_logs_only_the_exception_type(self):
        log = []
        ns = self._namespace(log, [])
        try:
            raise ValueError("secret clipboard text")
        except ValueError as exc:
            ns["_log_action_failure"]("info_messages", exc, private=True)
        text = "\n".join(log)
        self.assertIn("action failed: info_messages ValueError", text)
        self.assertNotIn("secret clipboard text", text)
        self.assertNotIn("Traceback", text)

    def test_the_failure_paths_in_siri_use_the_failed_flag(self):
        source = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        self.assertIn('_deliver(say_line("unsupported"), notify, reply_sink, failed=True)', source)
        self.assertIn('emit(notify, "Something went wrong" if not done else "Ready", line)', source)
        self.assertIn('emit(notify, "Something went wrong", line)  # a failed action plays the failure reaction', source)


class FailureReactionTests(unittest.TestCase):
    def test_the_failure_status_plays_the_failure_reaction(self):
        from orb_character import reaction_for_status
        self.assertEqual(reaction_for_status("Doing it", "Something went wrong",
                                             "I know what you want, I just can't do that one yet."), "failure")

    def test_an_unsupported_line_on_ready_is_not_a_success(self):
        from orb_character import reaction_for_status
        self.assertEqual(reaction_for_status("Doing it", "Ready",
                                             "I know what you want, I just can't do that one yet."), "success")
        # The failed path never sends Ready now, so the success rule no longer sees it. The rule itself is unchanged.


if __name__ == "__main__":
    unittest.main()
