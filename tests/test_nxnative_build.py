import io
import signal
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from commands.nxnative_build import Builder, find_python, scrub


@pytest.fixture
def setup(tmp_path):
    repo = tmp_path / 'repo'
    (repo / 'scripts').mkdir(parents=True)
    (repo / 'scripts/build_ipa_from_nsp.py').touch()
    keys = tmp_path / 'prod.keys'
    keys.touch()
    proc = Mock(pid=123, stdout=io.StringIO('hello\n'))
    proc.wait.return_value = 0
    builder = Builder(tmp_path / 'games', repo, tmp_path / 'logs', keys,
                      python=lambda: 'python3.12', disk=lambda p: SimpleNamespace(free=100 * 1024**3),
                      popen=Mock(return_value=proc), killpg=Mock())
    builder.discover()
    return builder, proc


def game(builder, name='Game'):
    path = builder.root / 'Inbox' / name
    path.mkdir()
    (path / 'base.NSP').write_bytes(b'game')
    return path


def test_discovery(setup):
    b, _ = setup
    assert b.discover() == []
    a = game(b)
    assert b.discover() == [a]
    c = game(b, 'Other')
    (b.root / 'Inbox' / 'empty').mkdir()
    assert b.discover() == [a, c]


@pytest.mark.parametrize('failure', ['python', 'disk', 'keys'])
def test_prechecks(setup, failure):
    b, _ = setup
    g = game(b)
    if failure == 'python':
        b.python = Mock(side_effect=ValueError('Python 3.12 missing'))
    elif failure == 'disk':
        b.disk = lambda p: SimpleNamespace(free=0)
    else:
        b.keys.unlink()
    assert 'Cannot start' in b.start(g, Mock(), platform='darwin')
    b.popen.assert_not_called()


@pytest.mark.parametrize('code', [0, 1])
def test_build_result_and_no_key_reads(setup, code):
    b, proc = setup
    proc.wait.return_value = code
    g = game(b)
    done = threading.Event()
    results = []
    original = io.open
    def guarded(path, *args, **kwargs):
        assert str(path) != str(b.keys)
        return original(path, *args, **kwargs)
    with patch('io.open', guarded), patch('builtins.open', side_effect=AssertionError('unexpected open')):
        b.start(g, lambda r: (results.append(r), done.set()), platform='darwin')
        assert done.wait(3)
    argv = b.popen.call_args.args[0]
    assert argv[argv.index('-k') + 1] == str(b.keys)
    assert 'shell' not in b.popen.call_args.kwargs
    assert b.popen.call_args.kwargs['start_new_session']
    assert results[0]['success'] == (code == 0)
    assert 'IPA ready' in results[0]['message'] if code == 0 else 'failed' in results[0]['message']
    assert 'hello' in results[0]['tail']
    run = Mock()
    b.fix_prompt(results[0], run)
    prompt = (b.repo / 'claude-fix-prompt.md').read_text()
    assert str(results[0]['log']) in prompt
    assert 'never push to main' in prompt
    assert 'new branch with tests' in prompt
    assert run.call_args_list[-1].args[0] == ['open', '-a', 'Terminal', str(b.repo)]


def test_lock_cancel_and_commands(setup):
    b, proc = setup
    b.active = dict(game='Game', at=b.now(), proc=proc, cancelled=False)
    assert 'Building Game' in b.start('unused', Mock(), platform='darwin')
    b.popen.assert_not_called()
    assert 'Cancelling' in b.cancel()
    b.killpg.assert_called_with(123, signal.SIGTERM)
    from mini_bar import quick_command_leaves
    with patch('commands.nxnative_build.BUILD', b):
        ids = [r['id'] for r in quick_command_leaves()]
        assert 'nx_build' in ids and 'nx_cancel' in ids
        b.active = None
        assert 'nx_cancel' not in [r['id'] for r in quick_command_leaves()]


def test_python_and_scrub():
    with pytest.raises(ValueError, match='Python 3.12'):
        find_python(Mock(side_effect=FileNotFoundError()))
    assert find_python(Mock(return_value=SimpleNamespace(returncode=0, stdout='3.12'))) 
    assert 'redacted' in scrub('key = ' + 'a' * 32)
    assert scrub('normal output\n') == 'normal output\n'


def test_gates(setup):
    b, _ = setup
    assert 'Mac only' in b.start('', Mock(), platform='linux')
    assert 'grown-up' in b.start('', Mock(), platform='darwin', zoe=True)
    b.popen.assert_not_called()


@pytest.mark.parametrize('success', [True, False])
def test_result_ui_actions(setup, success):
    from commands import nxnative_build_ui as ui
    b, _ = setup
    result = dict(success=success, cancelled=False, message='result', tail='last log lines',
                  output=b.root / 'Builds' / 'Game', log=b.logs / 'Game.log', game='Game')
    host = Mock()
    with patch.object(ui, 'BUILD', b), patch.object(ui, 'dialog', return_value=(True, 0)) as dialog, patch.object(ui.subprocess, 'Popen') as popen, patch.object(b, 'fix_prompt', return_value='copied') as fix:
        ui.finished(host, result)
        host._show_bar_reply.assert_any_call('result')
        assert dialog.call_args.args[2] == ('Show in Finder' if success else 'Ask Claude Code to fix')
        if success:
            popen.assert_called_once_with(['open', str(result['output'])])
            fix.assert_not_called()
        else:
            assert dialog.call_args.args[1] == 'last log lines'
            fix.assert_called_once_with(result)


def test_no_shell_or_listeners():
    import ast
    from pathlib import Path
    for name in ('nxnative_build.py', 'nxnative_build_ui.py'):
        tree = ast.parse((Path(__file__).parents[1] / 'commands' / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                assert not any(k.arg == 'shell' and isinstance(k.value, ast.Constant) and k.value.value for k in node.keywords)
                assert getattr(node.func, 'attr', '') not in ('bind', 'listen')
