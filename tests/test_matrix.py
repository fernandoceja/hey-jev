"""Blue pill and red pill. Terminal and osascript are mocked."""
import io
import os
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout

import commands
from mini_bar import submission
from commands.matrix import (
    INSTALL_LINE,
    MARKER,
    _run_logged,
    close_script,
    find_cmatrix,
    parse_report,
    plan_close,
    start_matrix,
    start_script,
    stop_matrix,
    terminal_running_script,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _present(path):
    return path in {
        "/opt/homebrew/bin/cmatrix",
        "/usr/local/bin/cmatrix",
        "/usr/bin/cmatrix",
    }


class TestPhrases(unittest.TestCase):
    def test_blue_pill_and_matrix_mode_stay_local(self):
        phrases = (
            "blue pill",
            "the blue pill",
            "take the blue pill",
            "take a blue pill",
            "please take the blue pill",
            "matrix mode",
            "enter the matrix",
            "start the matrix",
            "open the matrix",
        )
        for phrase in phrases:
            self.assertEqual(commands.route_before_api(phrase), "matrix_on", phrase)

    def test_red_pill_stays_local(self):
        phrases = (
            "red pill",
            "the red pill",
            "take the red pill",
            "take a red pill",
            "please red pill",
            "exit the matrix",
            "stop the matrix",
            "leave the matrix",
            "close the matrix",
        )
        for phrase in phrases:
            self.assertEqual(commands.route_before_api(phrase), "matrix_off", phrase)

    def test_nearby_sentences_are_not_the_matrix(self):
        for phrase in (
            "what is the blue pill",
            "blue pillow",
            "the red pill in the movie",
            "take the blue pill and open notes",
            "matrix",
            "who took the red pill",
        ):
            self.assertNotEqual(commands.route_before_api(phrase), "matrix_on", phrase)
            self.assertNotEqual(commands.route_before_api(phrase), "matrix_off", phrase)

    def test_typed_text_uses_the_same_local_route(self):
        plan = submission("  take the blue pill  ")
        self.assertEqual(plan["control"], ("text", "take the blue pill"))
        self.assertNotIn("local_only", plan)
        self.assertEqual(commands.route_before_api(plan["control"][1]), "matrix_on")
        self.assertEqual(commands.route_before_api("take the red pill"), "matrix_off")

    def test_the_phone_bridge_cannot_run_them(self):
        self.assertNotIn("matrix_on", commands.BRIDGE_ALLOW)
        self.assertNotIn("matrix_off", commands.BRIDGE_ALLOW)
        bridge = open(os.path.join(ROOT, "commands", "bridge.py"), encoding="utf-8").read()
        self.assertNotIn("matrix", bridge)
        source = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        self.assertIn('"matrix_on": lambda _arg, _text: commands.start_matrix()', source)
        self.assertIn('"matrix_off": lambda _arg, _text: commands.stop_matrix()', source)


class TestFindAndStart(unittest.TestCase):
    def test_homebrew_paths_are_used_when_path_misses(self):
        self.assertIsNone(find_cmatrix(which=lambda _name: None, isfile=lambda _path: False))
        self.assertEqual(
            find_cmatrix(which=lambda _name: None, isfile=lambda path: path == "/usr/local/bin/cmatrix"),
            "/usr/local/bin/cmatrix",
        )
        self.assertEqual(
            find_cmatrix(which=lambda _name: "/opt/homebrew/bin/cmatrix", isfile=_present),
            "/opt/homebrew/bin/cmatrix",
        )
        self.assertIsNone(find_cmatrix(which=lambda _name: "/tmp/cmatrix; rm -rf /", isfile=lambda _path: False))

    def test_a_missing_cmatrix_does_not_open_terminal(self):
        calls = []
        spoken = start_matrix(
            runner=lambda args: calls.append(list(args)),
            which=lambda _name: None,
            isfile=lambda _path: False,
            id_path=os.path.join(tempfile.gettempdir(), "no-matrix-id"),
        )
        self.assertEqual(spoken, INSTALL_LINE)
        self.assertIn("brew install cmatrix", spoken)
        self.assertEqual(calls, [])

    def test_start_uses_native_fullscreen_and_execs_cmatrix(self):
        calls = []

        def runner(args):
            calls.append(list(args))
            if "do script" in args[2]:
                return "id:482\nscreen:ok\n"
            return "running\n"

        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "matrix-window-id")
        spoken = start_matrix(
            runner=runner,
            which=lambda _name: "/opt/homebrew/bin/cmatrix",
            isfile=_present,
            shell="/bin/zsh",
            id_path=path,
        )
        self.assertEqual(spoken, "Matrix is on.")
        self.assertEqual(calls[0][2], terminal_running_script())
        self.assertNotIn('tell application "Terminal"', calls[0][2])
        script = next(call[2] for call in calls if "do script" in call[2])
        self.assertEqual(script, start_script("/opt/homebrew/bin/cmatrix", "/bin/zsh"))
        self.assertIn("/bin/zsh -c 'exec /opt/homebrew/bin/cmatrix'", script)
        self.assertIn('name contains "Hey Jev Matrix"', script)
        self.assertIn('attribute "AXFullScreen"', script)
        self.assertIn("delay 0.8", script)
        self.assertIn('keystroke "f" using {control down, command down}', script)
        self.assertIn("{0, 0, 0}", script)
        self.assertIn(MARKER, script)
        self.assertNotIn("bounds of window of desktop", script)
        self.assertNotIn("zoomed", script)
        self.assertNotIn("in selected tab of window 1", script)
        self.assertNotIn("brew install", script)
        self.assertNotIn("do shell script", script)
        self.assertEqual(open(path, encoding="utf-8").read(), "482")
        self.assertFalse(os.path.exists(os.path.join(folder, "matrix-terminal-launched")))

    def test_fullscreen_fallback_is_logged_and_still_speaks_on(self):
        calls = []

        def runner(args):
            calls.append(list(args))
            if "do script" in args[2]:
                return "id:482\nscreen:AX failed: no attribute; keystroke\n"
            return "running\n"

        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "matrix-window-id")
        buf = io.StringIO()
        with redirect_stdout(buf):
            spoken = start_matrix(
                runner=runner,
                which=lambda _name: "/opt/homebrew/bin/cmatrix",
                isfile=_present,
                shell="/bin/zsh",
                id_path=path,
            )
        self.assertEqual(spoken, "Matrix is on.")
        self.assertIn("  matrix: AX failed: no attribute; keystroke", buf.getvalue())
        script = next(call[2] for call in calls if "do script" in call[2])
        self.assertIn('keystroke "f" using {control down, command down}', script)
        self.assertEqual(open(path, encoding="utf-8").read(), "482")

    def test_a_fresh_terminal_reuses_the_startup_window(self):
        calls = []

        def runner(args):
            calls.append(list(args))
            if "do script" in args[2]:
                return "id:9\nscreen:ok\n"
            return "absent\n"

        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "matrix-window-id")
        spoken = start_matrix(
            runner=runner,
            which=lambda _name: "/usr/local/bin/cmatrix",
            isfile=_present,
            shell="/bin/zsh",
            id_path=path,
        )
        self.assertEqual(spoken, "Matrix is on.")
        script = next(call[2] for call in calls if "do script" in call[2])
        self.assertEqual(
            script,
            start_script("/usr/local/bin/cmatrix", "/bin/zsh", reuse_startup=True),
        )
        self.assertIn(
            'do script "/bin/zsh -c \'exec /usr/local/bin/cmatrix\'" in selected tab of window 1',
            script,
        )
        self.assertIn("busy of selected tab of window 1", script)
        self.assertIn("close (first window whose id is (extraId as integer))", script)
        launched = os.path.join(folder, "matrix-terminal-launched")
        self.assertEqual(open(launched, encoding="utf-8").read(), "1")

    def test_a_failed_probe_does_not_claim_jev_launched_terminal(self):
        def runner(args):
            if "do script" not in args[2]:
                raise RuntimeError("probe boom")
            return "id:4\nscreen:ok\n"

        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "matrix-window-id")
        buf = io.StringIO()
        with redirect_stdout(buf):
            spoken = start_matrix(
                runner=runner,
                which=lambda _name: "/opt/homebrew/bin/cmatrix",
                isfile=_present,
                shell="/bin/zsh",
                id_path=path,
            )
        self.assertEqual(spoken, "Matrix is on.")
        self.assertIn("terminal probe failed", buf.getvalue())
        self.assertFalse(os.path.exists(os.path.join(folder, "matrix-terminal-launched")))


class TestStop(unittest.TestCase):
    def test_only_the_matrix_window_is_closed(self):
        report = "\n".join((
            "482\t1\t/dev/ttys004\tHey Jev Matrix\tcmatrix",
            "100\t2\t/dev/ttys001\t\t-zsh",
            "100\t2\t/dev/ttys002\tshell\t-zsh",
        ))
        rows = parse_report(report)
        ps = "  99 ttys004 cmatrix\n  10 ttys001 -zsh\n"
        plan = plan_close(rows, ps)
        self.assertTrue(plan["running"])
        self.assertEqual(plan["close_windows"], [482])
        self.assertEqual(plan["close_ttys"], [])
        self.assertEqual(plan["pids"], [99])
        self.assertFalse(plan["quit_terminal"])
        self.assertNotIn(100, plan["close_windows"])
        script = close_script(plan["close_windows"], plan["close_ttys"])
        self.assertIn("whose id is 482", script)
        self.assertIn('attribute "AXFullScreen" of w to false', script)
        self.assertIn("delay 0.6", script)
        self.assertNotIn("close w", script)
        self.assertNotIn("quit", script.lower())

    def test_a_mixed_window_loses_only_the_matrix_tab(self):
        rows = parse_report("\n".join((
            "7\t2\t/dev/ttys008\tHey Jev Matrix\tcmatrix",
            "7\t2\t/dev/ttys009\twork\t-zsh",
        )))
        plan = plan_close(rows, "  55 ttys008 /opt/homebrew/bin/cmatrix\n")
        self.assertEqual(plan["close_windows"], [])
        self.assertEqual(plan["close_ttys"], ["/dev/ttys008"])
        self.assertEqual(plan["pids"], [55])
        self.assertFalse(plan["quit_terminal"])
        script = close_script(plan["close_windows"], plan["close_ttys"])
        self.assertIn("/dev/ttys008", script)
        self.assertNotIn("close w", script)
        self.assertNotIn("quit", script.lower())
        launched = plan_close(rows, "  55 ttys008 /opt/homebrew/bin/cmatrix\n", launched_by_jev=True)
        self.assertFalse(launched["quit_terminal"])
        self.assertEqual(launched["close_ttys"], ["/dev/ttys008"])

    def test_an_unrelated_saved_window_is_not_closed(self):
        rows = parse_report("50\t1\t/dev/ttys003\t\t-zsh")
        plan = plan_close(rows, "  3 ttys003 -zsh\n")
        self.assertFalse(plan["running"])
        self.assertEqual(plan["close_windows"], [])
        self.assertEqual(plan["pids"], [])

    def test_stop_kills_cmatrix_and_closes_that_window_by_id(self):
        calls = []
        report = "482\t1\t/dev/ttys004\tHey Jev Matrix\tcmatrix\n"

        def runner(args):
            calls.append(list(args))
            if args[0] == "ps":
                return "  99 ttys004 cmatrix\n  10 ttys001 -zsh\n"
            if args[0] == "osascript" and "whose id is" in args[2]:
                return "ok\n"
            if args[0] == "osascript":
                return report
            return ""

        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "matrix-window-id")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("482")
        spoken = stop_matrix(runner=runner, id_path=path)
        self.assertEqual(spoken, "Matrix is off.")
        self.assertIn(["kill", "-INT", "99"], calls)
        closing = next(call[2] for call in calls if call[0] == "osascript" and "whose id is" in call[2])
        self.assertIn("whose id is 482", closing)
        self.assertNotIn("100", closing)
        self.assertNotIn("close w", closing)
        self.assertNotIn("quit", closing.lower())
        self.assertFalse(os.path.exists(path))

    def test_quit_terminal_only_when_jev_launched_it(self):
        calls = []
        report = "482\t1\t/dev/ttys004\tHey Jev Matrix\tcmatrix\n"

        def runner(args):
            calls.append(list(args))
            if args[0] == "ps":
                return "  99 ttys004 cmatrix\n"
            if args[0] == "osascript" and "whose id is" in args[2]:
                return "ok\n"
            return report

        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "matrix-window-id")
        launched = os.path.join(folder, "matrix-terminal-launched")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("482")
        with open(launched, "w", encoding="utf-8") as handle:
            handle.write("1")
        rows = parse_report(report)
        plan = plan_close(rows, "  99 ttys004 cmatrix\n", launched_by_jev=True)
        self.assertTrue(plan["quit_terminal"])
        self.assertEqual(plan["close_windows"], [482])
        spoken = stop_matrix(runner=runner, id_path=path)
        self.assertEqual(spoken, "Matrix is off.")
        closing = next(call[2] for call in calls if "whose id is" in call[2])
        self.assertIn('tell application "Terminal" to quit', closing)
        self.assertIn("whose id is 482", closing)
        self.assertFalse(os.path.exists(path))
        self.assertFalse(os.path.exists(launched))

    def test_other_windows_block_quitting_terminal(self):
        report = "\n".join((
            "482\t1\t/dev/ttys004\tHey Jev Matrix\tcmatrix",
            "100\t1\t/dev/ttys001\t\t-zsh",
        ))
        plan = plan_close(
            parse_report(report),
            "  99 ttys004 cmatrix\n  10 ttys001 -zsh\n",
            launched_by_jev=True,
        )
        self.assertEqual(plan["close_windows"], [482])
        self.assertFalse(plan["quit_terminal"])
        script = close_script(plan["close_windows"], plan["close_ttys"], plan["quit_terminal"])
        self.assertIn("whose id is 482", script)
        self.assertNotIn("100", script)
        self.assertNotIn("quit", script.lower())

    def test_a_failed_close_is_not_called_off(self):
        calls = []
        report = "482\t1\t/dev/ttys004\tHey Jev Matrix\tcmatrix\n"

        def runner(args):
            calls.append(list(args))
            if args[0] == "ps":
                return "  99 ttys004 cmatrix\n"
            if args[0] == "osascript" and "whose id is" in args[2]:
                return "failed\nwindow 482: AppleEvent timed out\n"
            return report

        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "matrix-window-id")
        launched = os.path.join(folder, "matrix-terminal-launched")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("482")
        with open(launched, "w", encoding="utf-8") as handle:
            handle.write("1")
        buf = io.StringIO()
        with redirect_stdout(buf):
            spoken = stop_matrix(runner=runner, id_path=path)
        self.assertEqual(spoken, "I couldn't close the Matrix window.")
        self.assertNotIn("Matrix is off.", spoken)
        self.assertIn("window 482: AppleEvent timed out", buf.getvalue())
        self.assertTrue(os.path.exists(path))
        self.assertEqual(open(launched, encoding="utf-8").read(), "1")
        self.assertIn(["kill", "-INT", "99"], calls)

    def test_osascript_stderr_is_logged(self):
        class Result:
            def __init__(self, code, out, err):
                self.returncode = code
                self.stdout = out
                self.stderr = err

        def fake_run(args, capture_output=None, text=None, timeout=None):
            self.assertEqual(list(args)[:2], ["osascript", "-e"])
            return Result(1, "", "osascript error: window not found")

        buf = io.StringIO()
        with unittest.mock.patch("commands.matrix.subprocess.run", fake_run):
            with redirect_stdout(buf):
                with self.assertRaises(RuntimeError) as caught:
                    _run_logged(("osascript", "-e", "bad"))
        self.assertIn("osascript error: window not found", buf.getvalue())
        self.assertIn("  matrix:", buf.getvalue())
        self.assertIn("osascript error: window not found", str(caught.exception))

    def test_stop_when_terminal_is_not_running(self):
        calls = []

        def runner(args):
            calls.append(list(args))
            return "absent\n"

        spoken = stop_matrix(runner=runner, id_path=os.path.join(tempfile.mkdtemp(), "missing"))
        self.assertEqual(spoken, "The matrix isn't running.")
        self.assertEqual(len(calls), 1)
        self.assertIn('exists process "Terminal"', calls[0][2])
        self.assertNotIn(["kill"], [call[:1] for call in calls])


if __name__ == "__main__":
    unittest.main()
