import ast
import io
import signal
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from commands.rea_study import Study, RULES, find_node, find_claude


@pytest.fixture
def study(tmp_path):
    repo = tmp_path / 'rea'
    repo.mkdir()
    proc = Mock(pid=321, stdout=io.StringIO('evidence\n'))
    proc.wait.return_value = 0
    runner = Study(tmp_path / 'requests', repo, tmp_path / 'logs',
                   claude=lambda: '/claude', node=lambda: '/node/bin/node',
                   run=Mock(return_value=SimpleNamespace(returncode=0, stdout='--tools --allowedTools --permission-mode')),
                   popen=Mock(return_value=proc), killpg=Mock())
    target = tmp_path / 'Example.app'
    target.mkdir()
    return runner, target, proc


@pytest.mark.parametrize('findings', [True, False])
def test_request_argv_logs_and_result(study, findings):
    runner, target, proc = study
    def launch(*args, **kwargs):
        if findings:
            next(runner.root.iterdir()).joinpath('findings.md').write_text('Evidence')
        return proc
    runner.popen.side_effect = launch
    done, results = threading.Event(), []
    line = runner.start(target, 'Window search', lambda r: (results.append(r), done.set()), platform='darwin')
    assert 'Studying Window search' in line
    assert done.wait(3)
    result = results[0]
    request = (result['output'] / 'request.md').read_text()
    argv = runner.popen.call_args.args[0]
    assert str(target) in request and 'Window search' in request and 'Date: ' in request
    for rule in RULES.splitlines():
        assert rule in request and rule in argv[2]
    assert 'findings.md' in argv[2] and 'ORIGINAL' in argv[2]
    assert argv[:2] == ['/claude', '-p']
    assert '--permission-mode' in argv and 'default' in argv
    assert 'Write(/{}/**)'.format(result['output']) in argv
    assert argv[argv.index('--tools') + 1] == 'Read,Glob,Grep,Write,Edit'
    kwargs = runner.popen.call_args.kwargs
    assert kwargs['cwd'] == str(runner.repo) and kwargs['start_new_session']
    assert kwargs['env']['PATH'].startswith('/node/bin:')
    assert not kwargs.get('shell')
    assert (result['output'] / 'claude.log').read_text() == result['log'].read_text() == 'evidence\n'
    assert result['success'] == findings
    assert 'ready' in result['message'] if findings else 'failed' in result['message']
    assert 'evidence' in result['tail']
    assert not runner.status()


@pytest.mark.parametrize('failure', ['claude', 'repo', 'node', 'flags'])
def test_prechecks(study, failure):
    runner, target, _ = study
    if failure == 'repo':
        runner.repo.rmdir()
    elif failure == 'flags':
        runner.run.return_value.stdout = '--permission-mode'
    else:
        setattr(runner, failure, Mock(side_effect=ValueError(failure + ' missing')))
    assert 'Cannot start' in runner.start(target, 'search', Mock(), platform='darwin')
    runner.popen.assert_not_called()
    assert not runner.root.exists()


def test_discovery():
    with patch('commands.rea_study.shutil.which', return_value=None), patch.object(Path, 'is_file', return_value=False):
        with pytest.raises(ValueError, match='Claude Code CLI is missing'):
            find_claude()
    with pytest.raises(ValueError, match='Node 22'):
        find_node(Mock(side_effect=FileNotFoundError()))
    run = Mock(side_effect=[SimpleNamespace(returncode=0, stdout='v20.1'), SimpleNamespace(returncode=0, stdout='v22.0')])
    assert find_node(run).endswith('node@22/bin/node')


def test_lock_cancel_commands_and_bridge(study):
    runner, target, proc = study
    runner.active = dict(feature='Search', at=0, proc=proc, cancelled=False)
    assert 'Studying Search' in runner.start(target, 'Other', Mock(), platform='darwin')
    runner.popen.assert_not_called()
    assert 'Cancelling' in runner.cancel()
    runner.killpg.assert_called_with(321, signal.SIGTERM)
    assert runner.active['cancelled']
    proc.wait.side_effect = subprocess.TimeoutExpired('claude', 10)
    runner._reap_cancel(runner.active)
    runner.killpg.assert_called_with(321, signal.SIGKILL)
    from mini_bar import quick_command_leaves
    with patch('commands.rea_study.STUDY', runner):
        ids = {row['id'] for row in quick_command_leaves()}
        assert {'rea_study', 'rea_cancel'} <= ids
        runner.active = None
        assert 'rea_cancel' not in {row['id'] for row in quick_command_leaves()}
        assert 'No REA study' in runner.cancel()
    from commands.config import BRIDGE_ALLOW
    assert not {'rea_study', 'rea_cancel'} & BRIDGE_ALLOW


@pytest.mark.parametrize('platform,zoe', [('linux', False), ('darwin', True)])
def test_refusal(study, platform, zoe):
    runner, target, _ = study
    assert 'Mac only' in runner.start(target, 'Search', Mock(), platform=platform) if platform != 'darwin' else 'Zoe mode' in runner.start(target, 'Search', Mock(), platform=platform, zoe=zoe)
    runner.popen.assert_not_called()
    from commands import rea_study_ui as ui
    host = Mock()
    with patch.object(ui.sys, 'platform', platform), patch('commands.zoe_mode_active', return_value=zoe), patch.object(ui, 'form') as form:
        ui.click(host, 'rea_study')
        form.assert_not_called()
        host._show_bar_reply.assert_called_once()


@pytest.mark.parametrize('success', [True, False])
def test_result_ui(study, success):
    from commands import rea_study_ui as ui
    runner, _, _ = study
    result = dict(success=success, message='Study complete' if success else 'Study failed', tail='last lines', output=runner.root, log=runner.logs / 'test.log')
    with patch.object(ui, 'dialog', return_value=(True, 0)) as dialog, patch.object(ui.subprocess, 'Popen') as popen:
        ui.finished(Mock(), result)
        assert dialog.call_args.args[2] == ('Open Folder' if success else 'Open Log')
        assert dialog.call_args.args[1] == ('' if success else 'last lines')
        popen.assert_called_once_with(['open', str(result['output'] if success else result['log'])])


def test_second_click_shows_status(study):
    from commands import rea_study_ui as ui
    runner, _, proc = study
    runner.active = dict(feature='Search', at=0, proc=proc)
    with patch.object(ui, 'STUDY', runner), patch.object(ui.sys, 'platform', 'darwin'), patch('commands.zoe_mode_active', return_value=False), patch.object(ui, 'form') as form:
        host = Mock()
        ui.click(host, 'rea_study')
        form.assert_not_called()
        assert 'Studying Search' in host._show_bar_reply.call_args.args[0]


def test_no_shell_or_listeners():
    for name in ('rea_study.py', 'rea_study_ui.py'):
        tree = ast.parse((Path(__file__).parents[1] / 'commands' / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                assert not any(k.arg == 'shell' and isinstance(k.value, ast.Constant) and k.value.value for k in node.keywords)
                assert getattr(node.func, 'attr', '') not in ('bind', 'listen')


def test_cancelled_findings_are_not_success(study):
    runner, _, proc = study
    runner.root.mkdir()
    (runner.root / 'findings.md').touch()
    state = dict(feature='Search', proc=proc, cancelled=True, output=runner.root)
    results = []
    runner._watch(state, [io.StringIO()], results.append)
    assert not results[0]['success']
    assert results[0]['message'] == 'Study cancelled.'


def test_shared_surfaces():
    from orb_spotlight import search_rows
    from full_window import sidebar_items
    assert any(row[1] == 'menu:rea_study' for row in search_rows('Study a Feature', quick=True))
    # The Home sidebar shares the same non-phrase action as the mini-bar.
    rows, _ = sidebar_items()
    assert any(row.get('action') == ('quick', 'rea_study') for row in rows)
