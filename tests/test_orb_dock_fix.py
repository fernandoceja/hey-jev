"""PR 8: the docked orb sits above its full window, and minimizing the full window hands the orb back."""
import ast
import os
import unittest

import orb_motion as om

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return handle.read()


def _func(source, name):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError("no function named " + name)


class DockLevelTests(unittest.TestCase):
    def test_docked_level_is_one_above_the_full_window(self):
        for window_level in (0, 3, 5, 8):
            self.assertEqual(om.dock_panel_level(window_level), window_level + 1)
            self.assertGreater(om.dock_panel_level(window_level), window_level)

    def test_docked_level_accepts_numeric_strings_and_floats(self):
        self.assertEqual(om.dock_panel_level(2.0), 3)
        self.assertEqual(om.dock_panel_level("4"), 5)


class DockPanelWiringTests(unittest.TestCase):
    def test_landing_sets_the_docked_level_and_logs_it(self):
        land = _func(_source("assistant_ui.py"), "_land_orb_expand")
        self.assertIn("dock_panel_level(full.level())", land)
        self.assertIn("orb dock level:", land)
        self.assertLess(land.index("setLevel_"), land.index("orderFront_"))

    def test_the_floating_orb_level_is_still_bar_level_on_collapse(self):
        collapse = _func(_source("assistant_ui.py"), "_collapse_orb_from_full")
        self.assertIn("panel.setLevel_(BAR_LEVEL)", collapse)

    def test_the_docked_level_is_only_set_by_the_dock_path(self):
        ui = _source("assistant_ui.py")
        self.assertEqual(ui.count("dock_panel_level("), 1)  # the landing call; the import has no parenthesis


class MiniaturizeWiringTests(unittest.TestCase):
    def test_minimize_on_a_docked_window_runs_the_collapse_and_logs_it(self):
        will = _func(_source("assistant_ui.py"), "windowWillMiniaturize_")
        self.assertIn("ORB_STATE_OPEN", will)
        self.assertIn("orb window: miniaturize -> collapse", will)
        self.assertIn("_collapse_orb_from_full()", will)

    def test_a_minimized_window_after_collapse_is_kept_out_of_the_dock(self):
        did = _func(_source("assistant_ui.py"), "windowDidMiniaturize_")
        self.assertIn("ORB_STATE_IDLE", did)
        self.assertIn("orderOut_", did)
        self.assertIn("_orb_suppress_redock", did)

    def test_deminiaturize_redocks_unless_it_was_our_own_hand_back(self):
        did = _func(_source("assistant_ui.py"), "windowDidDeminiaturize_")
        self.assertIn("_orb_suppress_redock", did)
        self.assertIn("_expand_orb_to_full", did)
        self.assertLess(did.index("_orb_suppress_redock"), did.index("_expand_orb_to_full"))


if __name__ == "__main__":
    unittest.main()
