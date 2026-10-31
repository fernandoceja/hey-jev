"""Action menu capture (PR 5a hand-test fix): the menu's real module path, run on Linux CI with a fake screencapture.

The bug was `commands.BOOK`, which does not exist: the capture book lives on `commands.captures`. These tests import
that real path and run the same calls the menu makes, so the reference can't drift again.
"""
import commands.captures as captures
from mini_bar import capture_outcome


def _fake_screencapture(path_to_write=None):
    """A runner that behaves like `screencapture -i -x <path>` after a selection: it writes the file."""
    calls = []

    def run(argv, timeout=None, **_kwargs):
        calls.append(list(argv))
        if argv[0] == "screencapture" and path_to_write is None:
            with open(argv[-1], "wb") as handle:
                handle.write(b"png")
        return ""

    run.calls = calls
    return run


def test_the_capture_book_is_on_the_captures_module():
    assert isinstance(captures.BOOK, captures.CaptureBook)


def test_an_area_capture_saves_and_remembers_the_file_on_the_captures_book(tmp_path):
    book = captures.CaptureBook()
    run = _fake_screencapture()
    sentence = captures.take_screenshot("area", folder=str(tmp_path), book=book, run=run)
    assert capture_outcome(sentence) == "saved"
    assert book.last is not None and book.last["path"].startswith(str(tmp_path))
    assert run.calls[0][:3] == ["screencapture", "-i", "-x"]  # the crosshair, as today


def test_an_esc_cancelled_area_capture_remembers_nothing(tmp_path):
    book = captures.CaptureBook()

    def cancelled(argv, timeout=None, **_kwargs):
        raise RuntimeError("cancelled")  # what an Esc at the crosshair looks like to the runner

    sentence = captures.take_screenshot("area", folder=str(tmp_path), book=book, run=cancelled)
    assert capture_outcome(sentence) == "cancelled"
    assert book.last is None


def test_copy_image_uses_the_capture_the_menu_just_saved(tmp_path):
    book = captures.CaptureBook()
    captures.take_screenshot("area", folder=str(tmp_path), book=book, run=_fake_screencapture())
    run = _fake_screencapture()
    reply = captures.run_capture_menu("share_copy", book=book, run=run)
    assert reply == "Copied the capture."
    assert run.calls and run.calls[0][0] == "osascript"  # the clipboard, not the Jev window


def test_find_image_opens_lens_with_the_saved_capture_and_never_submits(tmp_path):
    book = captures.CaptureBook()
    captures.take_screenshot("area", folder=str(tmp_path), book=book, run=_fake_screencapture())
    run = _fake_screencapture()
    captures.ask_from_text("ask google about this", book=book, run=run)
    opened = [argv for argv in run.calls if argv[0] == "open"]
    assert any("https://lens.google.com/upload" in argv for argv in opened)
    assert all(argv[0] != "osascript" or "return" not in " ".join(argv) for argv in run.calls)  # no keypress


def test_capture_outcome_names_the_three_ends():
    assert capture_outcome("Cancelled.") == "cancelled"
    assert capture_outcome("Saved an area screenshot to your Captures folder.") == "saved"
    assert capture_outcome("Couldn't take a screenshot.") == "failed"


def test_the_find_image_plan_copies_then_opens_lens_and_returns_the_speech(tmp_path):
    from commands.captures import ask_plan, execute_ask
    book = captures.CaptureBook()
    captures.take_screenshot("area", folder=str(tmp_path), book=book, run=_fake_screencapture())
    run = _fake_screencapture()
    plan = ask_plan("google", "capture", path=book.last["path"])
    speech = execute_ask(plan, run=run)
    assert speech == plan["speech"]
    assert run.calls[0][0] == "osascript"  # the copy first
    assert any("https://lens.google.com/upload" in argv for argv in run.calls)


def test_a_failed_copy_raises_so_the_hint_is_never_shown(tmp_path):
    import pytest
    from commands.captures import ask_plan, execute_ask
    book = captures.CaptureBook()
    captures.take_screenshot("area", folder=str(tmp_path), book=book, run=_fake_screencapture())

    def failing(argv, timeout=None, **_kwargs):
        raise RuntimeError("osascript failed")

    with pytest.raises(RuntimeError):
        execute_ask(ask_plan("google", "capture", path=book.last["path"]), run=failing)


def test_a_failed_lens_open_raises_so_the_hint_is_never_shown(tmp_path):
    import pytest
    from commands.captures import ask_plan, execute_ask
    book = captures.CaptureBook()
    captures.take_screenshot("area", folder=str(tmp_path), book=book, run=_fake_screencapture())

    def copy_ok_open_fails(argv, timeout=None, **_kwargs):
        if argv[0] == "open":
            raise RuntimeError("open failed")
        return ""

    with pytest.raises(RuntimeError):
        execute_ask(ask_plan("google", "capture", path=book.last["path"]), run=copy_ok_open_fails)
