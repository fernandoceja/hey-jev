"""Entry point for the app bundle: same as `python siri.py --ui`, with output saved to ~/Library/Logs/Hey Jev.log."""
import os
import sys

log = open(os.path.expanduser("~/Library/Logs/Hey Jev.log"), "a", buffering=1, encoding="utf-8")
sys.stdout = sys.stderr = log

from assistant_ui import run_app  # noqa: E402

run_app()
