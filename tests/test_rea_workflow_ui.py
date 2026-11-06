"""Exercise modal clicks and launch boundaries without macOS."""
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from commands import rea_study_ui as ui


@pytest.fixture
def desktop(monkeypatch):
    import commands
    monkeypatch.setattr(ui.sys, 'platform', 'darwin')
    monkeypatch.setattr(commands, 'zoe_mode_active', lambda: False)
    study = SimpleNamespace(lock=threading.RLock(), active=None, status=lambda: '')
    study.start = Mock(return_value='Started')
    monkeypatch.setattr(ui, 'STUDY', study)
    # Run workers synchronously so launch/link assertions cover the entire click.
    monkeypatch.setattr(ui.threading, 'Thread', lambda target, **kw: SimpleNamespace(start=target))
    return study


@pytest.fixture
def dialogs(monkeypatch):
    import sys
    state = SimpleNamespace(choices=[], alerts=[], fields=[], index=0)
    class Widget:
        @classmethod
        def alloc(cls):
            return cls()
        def init(self):
            state.alerts.append(self)
            self.buttons = []
            return self
        def initWithFrame_(self, frame):
            self.value = ''
            state.fields.append(self)
            return self
        def initWithFrame_pullsDown_(self, *args):
            return self
        def runModal(self):
            return state.choices.pop(0)
        def addButtonWithTitle_(self, title):
            self.buttons.append(title)
        def setStringValue_(self, value):
            self.value = value
        def stringValue(self):
            return self.value
        def indexOfSelectedItem(self):
            return state.index
        def __getattr__(self, name):
            return lambda *args: None
    monkeypatch.setitem(sys.modules, 'AppKit', SimpleNamespace(**{name: Widget for name in ('NSAlert', 'NSTextField', 'NSView', 'NSPopUpButton')}))
    return state


@pytest.mark.parametrize('resolved', [True, False])
def test_wishlist_replicate_click(desktop, dialogs, monkeypatch, tmp_path, resolved):
    from commands import rea_workflows as workflows
    target = tmp_path / 'Source.app'
    target.mkdir()
    row = dict(id='item', feature='tabs', source_app='Source', status='idea')
    store = Mock()
    store.read.return_value = [row]
    monkeypatch.setattr(workflows, 'Wishlist', lambda: store)
    monkeypatch.setattr(workflows, 'resolve_app', lambda name: target if resolved else None)
    form = Mock(return_value=None)
    monkeypatch.setattr(ui, 'form', form)
    def start(*args, **kwargs):
        desktop.active = dict(output=tmp_path / 'request')
        return 'Started'
    desktop.start.side_effect = start
    dialogs.choices = [1001]
    ui.wishlist_list(Mock())
    if resolved:
        form.assert_not_called()
        assert desktop.start.call_args.args == (target, 'tabs')
        store.change.assert_called_once_with('update', 'item', status='planned', request_folder=str(tmp_path / 'request'))
    else:
        form.assert_called_once()
        desktop.start.assert_not_called()
        store.change.assert_not_called()


@pytest.mark.parametrize('confirm', [False, True])
def test_voice_resolved_still_requires_start(desktop, monkeypatch, tmp_path, confirm):
    monkeypatch.setattr('commands.rea_workflows.resolve_app', lambda name: tmp_path)
    form = Mock(return_value=(tmp_path, 'tabs') if confirm else None)
    monkeypatch.setattr(ui, 'form', form)
    assert ui.kickoff(Mock(), 'replicate tabs from Safari')
    form.assert_called_once()
    assert desktop.start.call_count == int(confirm)


@pytest.mark.parametrize('choice', [1001, 1002])
@pytest.mark.parametrize('confirm', [False, True])
def test_review_choices_require_start(desktop, dialogs, monkeypatch, tmp_path, choice, confirm):
    prior = tmp_path / 'prior'
    picker = Mock(return_value=prior)
    repo = Mock(return_value=tmp_path)
    monkeypatch.setattr(ui, 'pick_folder', picker)
    monkeypatch.setattr(ui, 'repo_picker', repo)
    form = Mock(return_value=(tmp_path, 'Review') if confirm else None)
    monkeypatch.setattr(ui, 'form', form)
    dialogs.choices = [choice]
    ui.click(Mock(), 'rea_review')
    assert dialogs.alerts[0].buttons == ['Cancel', 'Review against earlier study/spec', 'Review last change']
    assert desktop.start.call_count == int(confirm)
    if confirm:
        assert desktop.start.call_args.kwargs['request'] == (prior if choice == 1001 else None)
    assert picker.call_count == int(choice == 1001)
    assert repo.call_count == int(choice == 1002)
    assert ('earlier' if choice == 1001 else 'last change') in form.call_args.args[0]


def test_single_wishlist_save_keeps_unresolved_source(desktop, dialogs, monkeypatch):
    store = Mock()
    monkeypatch.setattr('commands.rea_workflows.Wishlist', lambda: store)
    monkeypatch.setattr('commands.rea_workflows.resolve_app', lambda name: None)
    dialogs.choices = [1001]
    assert ui.kickoff(Mock(), 'add tabs from Unknown App to the REA wishlist')
    store.change.assert_called_once_with('add', feature='tabs', source_app='Unknown App', notes='')
    assert len(dialogs.alerts) == 1
    assert dialogs.alerts[0].buttons == ['Cancel', 'Save']
    desktop.start.assert_not_called()
