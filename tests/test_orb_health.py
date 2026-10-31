"""The orb window can be on screen and still draw nothing. These checks find out why. No AppKit."""
import os
import unittest

from orb_health import render_problems, render_summary
from tests.test_pill_collapse import _func

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def healthy(**changes):
    snap = {
        "content_hidden": False,
        "content_alpha": 1.0,
        "content_layer_opacity": 1.0,
        "content_bounds": (0.0, 0.0, 64.0, 64.0),
        "orb_hidden": False,
        "orb_frame": (0.0, 0.0, 64.0, 64.0),
        "tree_attached": True,
        "layers": {"root": (1.0, 72.0, 72.0), "squash": (1.0, 72.0, 72.0),
                   "body_group": (1.0, 72.0, 72.0), "body": (1.0, 56.0, 56.0)},
    }
    snap.update(changes)
    return snap


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


class TestRenderProblems(unittest.TestCase):
    def test_healthy_orb_has_no_problems(self):
        self.assertEqual(render_problems(healthy()), [])
        self.assertEqual(render_problems(healthy(content_layer_opacity=None)), [])

    def test_hidden_or_transparent_content(self):
        self.assertIn("content_hidden", render_problems(healthy(content_hidden=True)))
        self.assertIn("content_alpha", render_problems(healthy(content_alpha=0.0)))
        self.assertIn("content_layer_opacity", render_problems(healthy(content_layer_opacity=0.0)))

    def test_orb_view_hidden_empty_or_outside_the_window(self):
        self.assertIn("orb_hidden", render_problems(healthy(orb_hidden=True)))
        self.assertIn("orb_frame_empty", render_problems(healthy(orb_frame=(0.0, 0.0, 0.0, 0.0))))
        # The expanded popover layout left the orb at x=380 in a 64x64 window.
        self.assertIn("orb_frame_outside", render_problems(healthy(orb_frame=(380.0, 120.0, 72.0, 72.0))))

    def test_detached_tree_and_layers(self):
        self.assertIn("tree_detached", render_problems(healthy(tree_attached=False)))
        layers = dict(healthy()["layers"], squash=(0.0, 72.0, 72.0), body=(1.0, 0.0, 0.0))
        problems = render_problems(healthy(layers=layers))
        self.assertIn("squash_opacity", problems)
        self.assertIn("body_bounds", problems)

    def test_summary_has_every_value_for_the_log(self):
        text = render_summary(healthy(), [])
        for key in ("contentHidden=False", "contentAlpha=1.00", "contentLayerOpacity=1.00", "orbHidden=False",
                    "orbFrame=0,0,64x64", "contentBounds=0,0,64x64", "treeAttached=True",
                    "root=1.00@72x72", "squash=1.00@72x72", "body_group=1.00@72x72", "body=1.00@56x56",
                    "problems=none"):
            self.assertIn(key, text)
        self.assertIn("problems=orb_hidden", render_summary(healthy(orb_hidden=True), ["orb_hidden"]))


class TestRenderWiring(unittest.TestCase):
    def test_every_reshow_checks_and_logs_render_state(self):
        ui = _read("assistant_ui.py")
        ensure = _func(ui, "_ensure_orb_window_flags")
        self.assertIn("render_problems(snapshot)", ensure)
        self.assertIn("render_summary(snapshot, problems)", ensure)
        self.assertIn("self._heal_orb_render(problems)", ensure)
        self.assertLess(ensure.index("render_summary"), ensure.index("_heal_orb_render"))  # log before heal
        self.assertIn('_ensure_orb_window_flags("tick", quiet=True)', _func(ui, "tick_"))

    def test_heal_restores_content_view_layout_and_layers(self):
        heal = _func(_read("assistant_ui.py"), "_heal_orb_render")
        for call in ("content.setHidden_(False)", "content.setAlphaValue_(1.0)", "layer.setOpacity_(1.0)",
                     "self._layout_mini_bar(", "orb.healRender()", "self._sync_orb()"):
            self.assertIn(call, heal)

    def test_orb_view_reattaches_tree_without_touching_motion(self):
        view = _read("orb_view.py")
        heal = _func(view, "healRender")
        self.assertIn("host.addSublayer_(tree.root)", heal)
        self.assertIn("setOpacity_(1.0)", heal)
        for motion in ("setTransform_", "removeAnimationForKey_", "addAnimation_", "squash_to", "press_squash"):
            self.assertNotIn(motion, heal)
        self.assertIn("tree.root.superlayer() is host", _func(view, "renderLayers"))


if __name__ == "__main__":
    unittest.main()
