"""The orb and choice panels really run at level 28. No AppKit.

NSPanel.setFloatingPanel_ resets the window level to NSFloatingWindowLevel (3), so setLevel_ must come after
it. With the old order the live orb was a level-3 floating window that the reveal-desktop sweep took away.
"""
import os
import unittest

from tests.test_pill_collapse import _func

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ui():
    with open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8") as fh:
        return fh.read()


class TestPanelLevelOrder(unittest.TestCase):
    def test_orb_level_is_set_after_floating_panel(self):
        build = _func(_ui(), "_build_mini_bar")
        self.assertLess(build.index("self.mini_panel.setFloatingPanel_(True)"),
                        build.index("self.mini_panel.setLevel_(BAR_LEVEL)"))

    def test_every_floating_panel_sets_its_level_afterwards(self):
        ui = _ui()
        start = 0
        found = 0
        while True:
            at = ui.find("setFloatingPanel_(True)", start)
            if at < 0:
                break
            found += 1
            window_end = ui.find("\n\n", at)
            self.assertIn("setLevel_(BAR_LEVEL)", ui[at:window_end], ui[at - 80:at + 120])
            start = at + 1
        self.assertGreaterEqual(found, 2)

    def test_bar_level_is_above_status_level(self):
        self.assertIn("BAR_LEVEL = 28", _ui())


if __name__ == "__main__":
    unittest.main()
