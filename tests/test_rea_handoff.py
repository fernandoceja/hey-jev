import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from commands.rea_handoff import create, load, validate, copy_spec
from commands.rea_builder import send_nxnative, start_new_app
from commands.rea_modes import KINDS
from tests.test_rea_study import study


@pytest.fixture
def rea_request(tmp_path):
    folder = tmp_path / 'rea_request'
    folder.mkdir()
    for name in ('findings.md', 'build-plan.md'):
        (folder / name).write_text('Evidence /Applications/Secret.app and original plan')
    create(folder, 'research', 'folder', 'Switch port', '/Applications/Secret.app')
    return folder


def test_schema_and_copy(rea_request, tmp_path):
    data = load(rea_request)
    assert data['files']['review'] is None
    for key in data:
        bad = dict(data)
        del bad[key]
        with pytest.raises((ValueError, TypeError)):
            validate(bad)
    for change in ({'clean_room': False}, {'feature': '/Applications/Foo.app'}, {'target_path': '/secret'}, {'feature': 3}, {'files': {}}, {'mode': 'build'}):
        with pytest.raises(ValueError):
            validate(dict(data, **change))
    (rea_request / 'spec/secret.txt').write_text('never copy')
    copy_spec(rea_request, tmp_path / 'copy')
    assert {p.name for p in (tmp_path / 'copy').iterdir()} == {'findings.md', 'build-plan.md', 'handoff.json'}
    assert '/Applications/' not in (tmp_path / 'copy/findings.md').read_text()


def test_nxnative(rea_request, tmp_path):
    inbox = tmp_path / 'Inbox'
    game = inbox / 'Example'
    game.mkdir(parents=True)
    assert send_nxnative(rea_request, game, inbox, platform='darwin') == game
    assert (game / 'rea-spec/handoff.json').is_file()
    assert not (game / 'rea-spec/request.md').exists()
    for key, value in [('suggested_builder', 'new_app'), ('target_kind', 'app')]:
        data = load(rea_request)
        data[key] = value
        (rea_request / 'spec/handoff.json').write_text(json.dumps(data))
        with pytest.raises(ValueError, match='Switch'):
            send_nxnative(rea_request, game, inbox, platform='darwin')
        data[key] = 'none' if key == 'suggested_builder' else 'folder'
        (rea_request / 'spec/handoff.json').write_text(json.dumps(data))


def test_builder(rea_request, study, tmp_path):
    runner, target, proc = study
    import threading
    done = threading.Event()
    results = []
    line = start_new_app(rea_request, 'My App', lambda r: (results.append(r), done.set()), tmp_path / 'dev', runner, platform='darwin')
    assert 'REA New App' in line
    assert done.wait(3)
    assert results[0]['success']
    argv = runner.popen.call_args.args[0]
    repo = tmp_path / 'dev/my-app'
    assert runner.popen.call_args.kwargs['cwd'] == str(repo)
    assert 'mcp__rea__*' not in argv
    assert 'Write(/{}/**)'.format(repo) in argv
    assert 'Edit(/{}/**)'.format(repo) in argv
    assert runner.run.call_args.args[0] == ['git', 'init']
    assert str(target) not in argv[2]
    for file in repo.rglob('*'):
        if file.is_file():
            assert '/Applications/Secret.app' not in file.read_text()
    with pytest.raises(ValueError, match='already exists'):
        start_new_app(rea_request, 'My App', Mock(), tmp_path / 'dev', runner, platform='darwin')
    runner.active = dict(feature='x', at=0, proc=proc)
    assert 'REA Research' in start_new_app(rea_request, 'Other', Mock(), tmp_path / 'dev', runner, platform='darwin')


@pytest.mark.parametrize('platform,zoe', [('linux', False), ('darwin', True)])
def test_refusals_all_modes(rea_request, platform, zoe):
    from commands import rea_study_ui as ui
    from commands.config import BRIDGE_ALLOW
    assert not set(KINDS) & BRIDGE_ALLOW
    for kind in KINDS:
        with patch.object(ui.sys, 'platform', platform), patch('commands.zoe_mode_active', return_value=zoe), patch.object(ui, 'form') as form:
            ui.click(Mock(), kind)
            form.assert_not_called()
    with pytest.raises(ValueError):
        send_nxnative(rea_request, '/unused', platform=platform, zoe=zoe)
    with pytest.raises(ValueError):
        start_new_app(rea_request, 'x', Mock(), platform=platform, zoe=zoe)


def test_menu():
    from mini_bar import quick_commands, quick_command_leaves
    rea = next(row for row in quick_commands() if row['id'] == 'rea')
    assert [r['title'] for r in rea['items']] == ['Add to Wishlist', 'Wishlist', 'Research', 'Review', 'Replicate Plan', 'Send to Builder']
    assert any(r['title'] == 'REA / Research' for r in quick_command_leaves())


@pytest.mark.parametrize('mode', ['replicate', 'review'])
def test_modes(study, mode):
    runner, target, proc = study
    import threading
    prior = None
    if mode == 'review':
        prior = runner.root / 'prior'
        prior.mkdir(parents=True)
        for name in ('findings.md', 'build-plan.md'):
            (prior / name).write_text('Original requirements')
    def launch(*args, **kwargs):
        folder = prior or next(runner.root.iterdir())
        for name in ('findings.md', 'build-plan.md', 'review.md'):
            (folder / name).write_text('Original acceptance criteria')
        return proc
    runner.popen.side_effect = launch
    done = threading.Event()
    results = []
    runner.start(target, 'Feature', lambda r: (results.append(r), done.set()), platform='darwin', mode=mode, request=prior)
    assert done.wait(3)
    assert results[0]['success']
    assert load(results[0]['output'])['mode'] == mode


def test_invalid_and_linked_spec(rea_request, tmp_path):
    (rea_request / 'spec/findings.md').unlink()
    outside = tmp_path / 'outside'
    outside.write_text('must not copy')
    (rea_request / 'spec/findings.md').symlink_to(outside)
    with pytest.raises(ValueError, match='linked'):
        copy_spec(rea_request, tmp_path / 'copy')
    (rea_request / 'spec/handoff.json').write_text('{}')
    with pytest.raises(ValueError):
        send_nxnative(rea_request, tmp_path, tmp_path, platform='darwin')


def test_builder_flags_refusal_and_cancel(rea_request, study, tmp_path):
    runner, _, proc = study
    runner.run.return_value.stdout = '--tools'
    with pytest.raises(ValueError, match='scoped'):
        start_new_app(rea_request, 'test', Mock(), tmp_path / 'dev', runner, platform='darwin')
    assert not (tmp_path / 'dev/test').exists()
    runner.popen.assert_not_called()
    runner.active = dict(mode='builder', label='New App', feature='test', at=0,
                         proc=proc, cancelled=False)
    assert 'Cancelling' in runner.cancel()
    assert runner.active['cancelled']
    runner.killpg.assert_called()


def test_nonzero_is_failure(study):
    runner, target, proc = study
    proc.wait.return_value = 1
    import threading
    done = threading.Event()
    results = []
    def launch(*args, **kwargs):
        folder = next(runner.root.iterdir())
        for name in ('findings.md', 'build-plan.md'):
            (folder / name).write_text('partial')
        return proc
    runner.popen.side_effect = launch
    runner.start(target, 'Feature', lambda r: (results.append(r), done.set()), platform='darwin')
    assert done.wait(3)
    assert not results[0]['success']
    assert not (results[0]['output'] / 'spec/handoff.json').exists()
