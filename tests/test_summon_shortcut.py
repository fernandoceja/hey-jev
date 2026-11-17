"""Executable validation and dispatch regressions, without registering real hotkeys."""
import ast
import ctypes
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import area_hotkey as ah

ROOT = Path(__file__).resolve().parents[1]


class ShortcutTests(unittest.TestCase):
    def test_default_and_canonical_order(self):
        self.assertEqual(ah.summon_shortcut(), ('ctrl+alt+j', 38, 0x1800))
        self.assertEqual(ah.summon_shortcut(' ALT+CTRL+K '), ('ctrl+alt+k', 40, 0x1800))

    def test_reserved_and_malformed_shortcuts(self):
        for value in ('ctrl+alt+cmd+w', '', 'j', 'ctrl+ctrl+j', 'hyper+j', 'ctrl+', 'ctrl+alt+jj'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ah.summon_shortcut(value)
        self.assertEqual(ah.summon_shortcut('ctrl+alt+w')[1:], (13, 0x1800))

    def test_carbon_dispatch_checks_signature_id_and_parameter_failure(self):
        carbon = SimpleNamespace(**{name: Mock(return_value=0) for name in (
            'GetApplicationEventTarget', 'GetEventParameter', 'InstallEventHandler',
            'RegisterEventHotKey', 'RemoveEventHandler', 'UnregisterEventHotKey')})
        pressed = Mock()
        hotkey = ah.CarbonHotKey(pressed, 38, 0x1800, 'summon', 2)
        with patch.object(ah.ctypes.cdll, 'LoadLibrary', return_value=carbon):
            self.assertTrue(hotkey.register()[0])
        def event(signature, key_id, status=0):
            def read(*args):
                value = ctypes.cast(args[-1], ctypes.POINTER(ah._EventHotKeyID)).contents
                value.signature, value.id = signature, key_id
                return status
            carbon.GetEventParameter.side_effect = read
            return hotkey._handler(None, None, None)
        self.assertEqual(event(ah._HOTKEY_SIGNATURE, 1), ah._EVENT_NOT_HANDLED)
        self.assertEqual(event(0, 2), ah._EVENT_NOT_HANDLED)
        self.assertEqual(event(ah._HOTKEY_SIGNATURE, 2, -1), ah._EVENT_NOT_HANDLED)
        pressed.assert_not_called()
        self.assertEqual(event(ah._HOTKEY_SIGNATURE, 2), 0)
        pressed.assert_called_once()

    def test_registration_conflict_removes_handler(self):
        carbon = SimpleNamespace(**{name: Mock(return_value=0) for name in (
            'GetApplicationEventTarget', 'GetEventParameter', 'InstallEventHandler',
            'RegisterEventHotKey', 'RemoveEventHandler', 'UnregisterEventHotKey')})
        carbon.RegisterEventHotKey.return_value = -9878
        with patch.object(ah.ctypes.cdll, 'LoadLibrary', return_value=carbon):
            hotkey = ah.CarbonHotKey(Mock(), 38, 0x1800, 'summon', 2)
            ok, detail = hotkey.register()
        self.assertFalse(ok)
        self.assertIn('-9878', detail)
        carbon.RemoveEventHandler.assert_called_once()
        self.assertIsNone(hotkey._handler_ref)

    def handler(self):
        tree = ast.parse((ROOT / 'assistant_ui.py').read_text())
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'focusTypeField_')
        node.decorator_list = []
        namespace = {}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), '<handler>', 'exec'), namespace)
        return namespace['focusTypeField_']

    def test_expanded_panel_from_other_app_refocuses_but_key_panel_hides(self):
        for focused in (False, True):
            app = Mock()
            app._spotlight = None
            app._orb_docked_now.return_value = False
            app._tuck_active.return_value = False
            app.bar.should_show.return_value = True
            app.pill.expanded = True
            app.pillCollapsed = False
            app.mini_panel.isKeyWindow.return_value = focused
            self.handler()(app, None)
            if focused:
                app.pill.escape.assert_called_once()
                app.expandMiniBar_.assert_not_called()
            else:
                app.pill.escape.assert_not_called()
                app.expandMiniBar_.assert_called_once()

    def test_docked_window_collapses_before_deferred_input(self):
        app = Mock()
        app._spotlight = None
        app._orb_docked_now.return_value = True
        self.handler()(app, None)
        app._collapse_orb_from_full.assert_called_once()
        app.performSelector_withObject_afterDelay_.assert_called_once_with("hotkeyAfterClear:", None, 0.7)
        app.expandMiniBar_.assert_not_called()

    def test_helper_cannot_fall_back_to_launch_services(self):
        source = (ROOT / 'helper/JevHotkey/main.swift').read_text()
        self.assertNotIn('urlForApplication', source)
        self.assertIn('Bundle(url: url)?.bundleIdentifier == jevBundleID', source)
        self.assertIn('UnregisterEventHotKey(ref)', source)
        self.assertNotIn('rm ', (ROOT / 'scripts/build_hotkey_helper.sh').read_text())


if __name__ == '__main__':
    unittest.main()
