"""Offline coverage for native design, runtime, profiles and shared read-aloud."""
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import wave

import pytest
from commands.omnivoice_design import describe_to_tags
from commands.omnivoice_profiles import Profiles, transcribe_reference
from commands import omnivoice_voice as native
from commands.tts_chain import fetch_with_fallback


def wav(path):
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((1, 2, 24000, 0, 'NONE', 'none'))
        stream.writeframes(b'\0\0' * 240)


@pytest.mark.parametrize('description,tags,ignored', [
    ('Warm, gentle storybook narrator', 'low pitch', ['gentle', 'storybook', 'narrator']),
    ('female, elderly, low pitch, british accent', 'female, elderly, low pitch, british accent', []),
    ('a deep old british man whispering', 'low pitch, elderly, british accent, male, whisper', []),
    ('cheerful little girl', 'child, female', ['cheerful']),
    ('storybook', None, ['storybook']),
    (' FEMALE ， elderly, LOW   PITCH, female, british accent ', 'female, elderly, low pitch, british accent', []),
    ('very deep male female teen old very high', 'very low pitch, male, teenager', ['female', 'old', 'very', 'high']),
    ('gentle bright narrator', 'high pitch', ['gentle', 'narrator']),
    ('french spanish accent', None, ['french', 'spanish', 'accent']),
    ('human highway', None, ['human', 'highway']),
    ('moderate pitch, low pitch', 'moderate pitch', ['low', 'pitch']),
    ('young child soft-spoken', 'child, moderate pitch', []),
])
def test_mapping(description, tags, ignored):
    result = describe_to_tags(description)
    assert result.instruct == tags
    assert result.ignored == ignored
    assert ('default voice' in result.message) == (tags is None)


def test_non_string():
    with pytest.raises(TypeError):
        describe_to_tags(None)


def test_runtime_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.delenv('JEV_OMNIVOICE_PYTHON', raising=False)
    first = tmp_path / 'Library/Application Support/VoiceStudio/runtime/project/.venv/bin/python'
    second = tmp_path / 'Library/Application Support/VoiceStudio/.venv/bin/python'
    for path in (first, second):
        path.parent.mkdir(parents=True)
        path.write_text('fake')
        path.chmod(0o600)
    with pytest.raises(RuntimeError, match='Checked:') as error:
        native.runtime_python()
    assert str(first) in str(error.value) and 'OmniVoice' in str(error.value)
    second.chmod(0o700)
    assert native.runtime_python() == str(second)
    first.chmod(0o700)
    assert native.runtime_python() == str(first)
    monkeypatch.setenv('JEV_OMNIVOICE_PYTHON', '/override')
    assert native.runtime_python() == '/override'


def test_engine_mapping_rejection_no_retry():
    from commands.omnivoice_engine import Engine
    engine = Engine.__new__(Engine)
    engine.model = MagicMock()
    engine.model.generate.side_effect = ValueError('bad instruct')
    with patch.dict(sys.modules, {'soundfile': MagicMock()}):
        with pytest.raises(ValueError, match='rejected voice-design tags'):
            engine.render({'input': 'hello', 'description': 'warm narrator'}, 'out.wav')
    engine.model.generate.assert_called_once_with(text='hello', instruct='low pitch')


def test_profiles_transcription_and_guard(tmp_path):
    source = tmp_path / 'ref.wav'
    wav(source)
    transcriber = MagicMock(return_value=' Reference words. ')
    store = Profiles(tmp_path / 'profiles', transcriber=transcriber)
    store.create('auto', source, consent=True, auto_transcribe=True)
    assert store.load('auto')['settings']['ref_text'] == 'Reference words.'
    transcriber.assert_called_once_with(source)
    store.create('explicit', source, consent=True, ref_text='Provided', auto_transcribe=True)
    assert transcriber.call_count == 1
    transcriber.side_effect = RuntimeError('not cached')
    store.create('missing', source, consent=True, auto_transcribe=True)
    worker = MagicMock()
    with pytest.raises(ValueError, match='profile has no ref_text'):
        store.render('missing', 'hello', tmp_path / 'out.wav', worker)
    worker.render.assert_not_called()
    store.render('auto', 'hello', tmp_path / 'out.wav', worker)
    assert worker.render.call_args.kwargs['settings']['ref_text'] == 'Reference words.'


def test_transcriber_local_only(monkeypatch):
    model = MagicMock()
    model.return_value.transcribe.return_value = (iter([SimpleNamespace(text=' Hello ')]), None)
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=model))
    monkeypatch.setenv('HF_HUB_OFFLINE', '0')
    assert transcribe_reference('ref.wav') == 'Hello'
    model.assert_called_once_with('small.en', device='cpu', compute_type='int8', local_files_only=True)
    assert os.environ['HF_HUB_OFFLINE'] == '1'


def test_chain_default_order_and_logs(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv('JEV_TTS_PROVIDER', raising=False)
    fish = MagicMock(return_value=('fish.wav', 2, False))
    omni = MagicMock(side_effect=RuntimeError())
    vs = MagicMock(side_effect=ValueError())
    assert fetch_with_fallback('hi', tmp_path, fish, omni, vs)[3] == 'FISH'
    omni.assert_not_called()
    assert fetch_with_fallback('hi', tmp_path, fish, omni, vs, 'OMNIVOICE')[3] == 'FISH'
    assert capsys.readouterr().out == '  omnivoice failed: RuntimeError; trying VoiceStudio\n  voicestudio failed: ValueError; using Fish fallback\n'


def test_cache_identity(tmp_path):
    worker = MagicMock()
    def render(text, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        wav(path)
        return str(path), 1, False
    worker.render.side_effect = render
    with patch.object(native, 'worker', return_value=worker):
        first = native.fetch_speech('Hello', tmp_path)
        assert native.fetch_speech('Hello', tmp_path) == (first[0], 0, True)
        assert not native.fetch_speech('Other', tmp_path)[2]
    worker.render.assert_called()


def test_tags_only_cli(capsys):
    from scripts.omnivoice import main
    with patch('scripts.omnivoice.Worker') as worker:
        main(['design', '--description', 'warm', '--tags-only'])
        worker.assert_not_called()
    assert capsys.readouterr().out == 'Mapped to: low pitch\n'


@pytest.mark.parametrize('provider', ['OMNIVOICE', 'VOICESTUDIO'])
def test_readaloud_check(tmp_path, monkeypatch, provider):
    from scripts import omnivoice_readaloud_check as check
    cache = tmp_path / 'fresh'
    def fetch(text, cache_dir, fish):
        with pytest.raises(RuntimeError, match='forbidden'):
            fish(text, cache_dir)
        path = cache_dir / 'out.wav'
        wav(path)
        return str(path), 4, False, provider
    monkeypatch.setattr(check, 'fetch_with_fallback', fetch)
    monkeypatch.setattr(check, 'close', lambda: None)
    monkeypatch.setenv('JEV_TTS_PROVIDER', 'FISH')
    assert check.main(['--cache-dir', str(cache)]) == (0 if provider == 'OMNIVOICE' else 1)
    report = json.loads((cache / 'report.json').read_text())
    assert report['provider'] == provider and report['audio_seconds'] == .01
    assert report['seconds'] >= 0
