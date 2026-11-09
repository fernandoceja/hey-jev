"""Shared read-aloud provider order; no UI or Keychain imports."""

import time


def fetch_with_fallback(text, cache_dir, fish, omnivoice=None, voicestudio=None,
                        provider=None):
    started = time.monotonic()
    from . import voicestudio_voice
    selected = provider if provider is not None else voicestudio_voice.provider
    selected = selected() if callable(selected) else selected
    failures = []

    def finish(result, winner):
        path, ms, cached = result if result is not None else (None, 0, False)
        fallback = winner != selected
        reason = ' reason={}'.format(';'.join(failures)) if fallback and failures else ''
        print('tts: provider={} selected={} fallback={}{} elapsed={:.2f}s path={}'.format(
            winner, selected, 'yes' if fallback else 'no', reason,
            time.monotonic() - started, path if path is not None else 'none'), flush=True)
        return path, ms, cached, winner

    if selected == 'OMNIVOICE':
        try:
            if omnivoice is None:
                from .omnivoice_voice import fetch_speech
                omnivoice = fetch_speech
            result = omnivoice(text, cache_dir)
            return finish(result, 'OMNIVOICE')
        except Exception as exc:
            failures.append('omnivoice:{}'.format(type(exc).__name__))
            print('  omnivoice failed: {}; trying VoiceStudio'.format(type(exc).__name__), flush=True)
    if selected in ('VOICESTUDIO', 'OMNIVOICE'):
        try:
            result = (voicestudio or voicestudio_voice.fetch_speech)(text, cache_dir)
            if result is not None:
                return finish(result, 'VOICESTUDIO')
            failures.append('voicestudio:none')
        except Exception as exc:
            failures.append('voicestudio:{}'.format(type(exc).__name__))
            print('  voicestudio failed: {}; using Fish fallback'.format(type(exc).__name__), flush=True)
    result = fish(text, cache_dir)
    return finish(result, 'FISH')
