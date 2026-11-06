"""Offline workflow boundary tests; subprocesses and UI are mocked."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from commands.rea_workflows import Wishlist, intent, resolve_app, presets, diff_context
from commands.rea_existing import origin, slug_check, compare_url, push, start, discard
from tests.test_rea_handoff import rea_request
from tests.test_rea_study import study


@pytest.mark.parametrize('phrase,mode,app,feature', [
    ('study how Safari does tabs', 'research', 'Safari', 'tabs'),
    ('research tabs in Safari', 'research', 'Safari', 'tabs'),
    ('replicate tabs from Safari', 'replicate', 'Safari', 'tabs'),
    ('add tabs from Safari to the REA wishlist', 'wishlist', 'Safari', 'tabs')])
def test_intents(phrase, mode, app, feature):
    assert intent(phrase) == dict(mode=mode, app=app, feature=feature)
    assert intent('open safari') is None


def test_app_resolution(tmp_path):
    (tmp_path / 'Safari.app').mkdir()
    assert resolve_app('Safri', [tmp_path]).name == 'Safari.app'
    assert resolve_app('uninstalled', [tmp_path]) is None


def test_no_start_and_refusal():
    from commands.rea_study_ui import kickoff
    host = Mock()
    with patch('commands.rea_study_ui.sys.platform', 'darwin'), patch('commands.zoe_mode_active', return_value=False), patch('commands.rea_study_ui.click') as click, patch('commands.rea_workflows.resolve_app', return_value=None), patch('commands.rea_study.STUDY.start') as launch:
        assert kickoff(host, 'replicate tabs from Missing')
        assert click.call_args.args[2]['target'] is None
        assert click.call_args.args[2]['feature'] == 'tabs'
        launch.assert_not_called()
    with patch('commands.rea_study_ui.sys.platform', 'darwin'), patch('commands.zoe_mode_active', return_value=True), patch('commands.rea_study_ui.click') as click:
        assert kickoff(host, 'research tabs in Safari')
        click.assert_not_called()
    from commands.config import BRIDGE_ALLOW
    from commands.rea_modes import KINDS
    assert not set(KINDS) & BRIDGE_ALLOW


def test_wishlist(tmp_path):
    store = Wishlist(tmp_path / 'wishlist.json', tmp_path / 'requests')
    row = store.change('add', feature='tabs', source_app='Safari', notes='Original')
    folder = tmp_path / 'requests/one'
    folder.mkdir(parents=True)
    store.change('update', row['id'], status='planned', request_folder=str(folder))
    assert store.read()[0]['status'] == 'planned'
    store.change('update', row['id'], status='built')
    with pytest.raises(ValueError):
        store.change('update', row['id'], request_folder='/etc')
    assert store.read()[0]['status'] == 'built'
    store.change('remove', row['id'])
    assert store.read() == []
    assert not list(tmp_path.glob('.wishlist-*'))
    store.path.write_text('{broken')
    with pytest.raises(ValueError, match='preserved'):
        store.change('add', feature='never overwrite')
    assert store.path.read_text() == '{broken'
    assert list(tmp_path.glob('*.corrupt-*'))[0].read_text() == '{broken'


def test_atomic_failure(tmp_path):
    store = Wishlist(tmp_path / 'wishlist.json')
    store.change('add', feature='first')
    original = store.path.read_bytes()
    with patch('commands.rea_workflows.os.replace', side_effect=OSError('disk')):
        with pytest.raises(OSError):
            store.change('add', feature='second')
    assert store.path.read_bytes() == original


def test_presets_context(tmp_path):
    for name in ('hey-jev', 'nxnative', 'princess'):
        (tmp_path / name).mkdir()
    def run(argv, **kw):
        url = 'git@github.com:fernandoceja/Zoe-s-Princess-Academy.git' if argv[2].endswith('princess') else 'other'
        return SimpleNamespace(returncode=0, stdout=url)
    assert [label for label, _ in presets(tmp_path, run)] == ['Jev', 'NXNative', 'Zoe Princess Academy']
    run = Mock(return_value=SimpleNamespace(returncode=1, stdout=''))
    assert 'shallow' in diff_context(tmp_path, run)
    assert run.call_args_list[0].args[0][-3:] == ['diff', 'HEAD~1', '--stat']


def test_remote_slug_url():
    for url in ('https://evil/github.com/fernandoceja/a', 'https://github.com/other/a', 'git@github.com:fernandoceja/../a', 'https://github.com/fernandoceja/a?x'):
        with pytest.raises(ValueError):
            origin('/repo', Mock(return_value=SimpleNamespace(returncode=0, stdout=url)))
    for slug in ('../bad', '-bad', 'main/x', 'a;touch', ''):
        with pytest.raises(ValueError):
            slug_check(slug)
    assert compare_url(dict(repo_name='hey-jev', default='release/v1', branch='rea/tabs')) == 'https://github.com/fernandoceja/hey-jev/compare/release%2Fv1...rea%2Ftabs?expand=1'


@pytest.mark.parametrize('changed', [False, True])
def test_worktree_build(rea_request, study, tmp_path, changed):
    import threading
    runner, _, proc = study
    repo = tmp_path / 'source'
    repo.mkdir()
    root = tmp_path / 'worktrees'
    commands = []
    url = 'https://github.com/fernandoceja/hey-jev.git'
    def run(argv, **kwargs):
        commands.append(argv)
        args = argv[3:]
        value = ''
        if argv == ['/claude', '--help']:
            value = '--tools --allowedTools --permission-mode --setting-sources --strict-mcp-config --mcp-config --disallowedTools'
        elif args[:2] == ['remote', 'get-url']:
            value = url
        elif args == ['rev-parse', '--show-toplevel']:
            value = argv[2]
        elif args == ['symbolic-ref', 'refs/remotes/origin/HEAD']:
            value = 'refs/remotes/origin/main'
        elif args == ['symbolic-ref', '--short', 'HEAD']:
            value = 'rea/tabs'
        elif args == ['status', '--porcelain'] and argv[2].endswith('hey-jev-tabs') and changed:
            value = ' M app.py'
        elif args[:2] == ['worktree', 'add']:
            Path(args[4]).mkdir()
        return SimpleNamespace(returncode=0, stdout=value)
    runner.run = Mock(side_effect=run)
    done = threading.Event()
    results = []
    start(rea_request, repo, 'tabs', lambda r: (results.append(r), done.set()), runner=runner, root=root, platform='darwin')
    assert done.wait(3)
    assert results[0]['success']
    argv = runner.popen.call_args.args[0]
    destination = root / 'hey-jev-tabs'
    assert runner.popen.call_args.kwargs['cwd'] == str(destination)
    assert argv == ['/claude', '-p', argv[2], '--permission-mode', 'default', '--tools', 'Read,Glob,Grep,Write,Edit', '--allowedTools', 'Read', 'Glob', 'Grep', 'Write(/' + str(destination) + '/**)', 'Edit(/' + str(destination) + '/**)', '--disallowedTools', 'Bash', 'mcp__rea__*', '--setting-sources', '', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}']
    assert str(rea_request) not in argv[2]
    assert not any('push' in cmd for cmd in commands)
    assert (['git', '-C', str(destination), 'commit', '-m', 'Implement REA tabs'] in commands) == changed
    assert ['git', '-C', str(repo), 'worktree', 'add', '-b', 'rea/tabs', str(destination), 'origin/main'] in commands
    with pytest.raises(ValueError):
        start(rea_request, repo, 'tabs', Mock(), runner=runner, root=root, platform='darwin')


@pytest.mark.parametrize('branch', ['main', 'master', 'release'])
def test_protected_push(tmp_path, branch):
    state = dict(output=tmp_path, origin='https://github.com/fernandoceja/a.git', repo_name='a', branch=branch, default='release')
    def run(argv, **kw):
        value = branch if 'symbolic-ref' in argv else state['origin']
        return SimpleNamespace(returncode=0, stdout=value)
    runner = Mock(side_effect=run)
    with pytest.raises(ValueError):
        push(state, platform='darwin', run=runner)
    assert not any('push' in call.args[0] for call in runner.call_args_list)


@pytest.mark.parametrize('zoe,platform', [(True, 'darwin'), (False, 'linux')])
def test_existing_refuses(zoe, platform):
    with pytest.raises(ValueError):
        start('/unused', '/unused', 'test', Mock(), platform=platform, zoe=zoe)


@pytest.mark.parametrize('phrase', ['study how Safari does tabs', 'research tabs in Safari', 'replicate tabs from Safari', 'add tabs from Safari to the REA wishlist'])
def test_bridge_refuses_phrases(phrase):
    from commands.bridge import bridge_allowed
    from commands.routing import route_before_api
    assert route_before_api(phrase) == 'rea_kickoff'
    assert bridge_allowed(phrase) is None


@pytest.mark.parametrize('failure', ['dirty', 'origin'])
def test_existing_prechecks(rea_request, study, tmp_path, failure):
    runner, _, _ = study
    repo = tmp_path / 'source'
    repo.mkdir()
    def run(argv, **kwargs):
        args = argv[3:]
        value = ''
        if args == ['rev-parse', '--show-toplevel']:
            value = str(repo)
        elif args[:2] == ['remote', 'get-url']:
            value = 'https://github.com/' + ('other' if failure == 'origin' else 'fernandoceja') + '/hey-jev.git'
        elif args == ['status', '--porcelain']:
            value = ' M file'
        return SimpleNamespace(returncode=0, stdout=value)
    runner.run = Mock(side_effect=run)
    with pytest.raises(ValueError):
        start(rea_request, repo, 'tabs', Mock(), runner=runner, root=tmp_path / 'trees', platform='darwin')
    runner.popen.assert_not_called()
    assert not any('fetch' in call.args[0] for call in runner.run.call_args_list)


def test_push_explicit(tmp_path):
    state = dict(output=tmp_path, origin='git@github.com:fernandoceja/app.git', repo_name='app', branch='rea/tabs', default='main')
    def run(argv, **kwargs):
        args = argv[3:]
        value = 'refs/remotes/origin/main' if args == ['symbolic-ref', 'refs/remotes/origin/HEAD'] else state['origin'] if args[:2] == ['remote', 'get-url'] else 'rea/tabs' if 'symbolic-ref' in args else str(tmp_path) if 'rev-parse' in args else ''
        return SimpleNamespace(returncode=0, stdout=value)
    runner = Mock(side_effect=run)
    assert push(state, platform='darwin', run=runner).endswith('main...rea%2Ftabs?expand=1')
    assert runner.call_args.args[0] == ['git', '-C', str(tmp_path), 'push', '-u', 'origin', 'rea/tabs']
    assert state['pushed']


def test_discard_refuses_pushed(tmp_path):
    state = dict(output=tmp_path, origin='git@github.com:fernandoceja/app.git', repo_name='app', branch='rea/tabs', default='main', pushed=True)
    runner = Mock()
    with patch('commands.rea_existing.validate_live', return_value=tmp_path), patch('commands.rea_existing.git', return_value='') as git:
        with pytest.raises(ValueError):
            discard(state, platform='darwin', run=runner)
        assert not any('remove' in call.args for call in git.call_args_list)


def test_no_audio_or_generic_scope():
    import ast
    source = Path('siri.py').read_text()
    tree = ast.parse(source)
    turn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_handle_turn')
    first_if = turn.body[2]
    assert isinstance(first_if, ast.If)
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ('speak', '_deliver', 'say') for n in ast.walk(first_if))


def test_preparation_cancel(study):
    runner, _, _ = study
    runner.active = dict(proc=None, cancelled=False)
    assert 'preparation' in runner.cancel()
    assert runner.active['cancelled']
    runner.killpg.assert_not_called()


def test_live_default_push_refused(tmp_path):
    state = dict(output=tmp_path, origin='git@github.com:fernandoceja/app.git', repo_name='app', branch='rea/tabs', default='main')
    with patch('commands.rea_existing.validate_live', return_value=tmp_path), patch('commands.rea_existing.git') as git:
        git.side_effect = ['', '', 'refs/remotes/origin/rea/tabs', '']
        with pytest.raises(ValueError, match='protected'):
            push(state, platform='darwin')
        assert not any('push' in call.args for call in git.call_args_list)
