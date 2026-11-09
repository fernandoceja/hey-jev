"""Shared read-aloud provider order; no UI or Keychain imports."""


def fetch_with_fallback(text, cache_dir, fish, omnivoice=None, voicestudio=None,
                        provider=None):
    from . import voicestudio_voice
    selected = provider if provider is not None else voicestudio_voice.provider
    selected = selected() if callable(selected) else selected
    if selected == 'OMNIVOICE':
        try:
            if omnivoice is None:
                from .omnivoice_voice import fetch_speech
                omnivoice = fetch_speech
            result = omnivoice(text, cache_dir)
            return (*result, 'OMNIVOICE')
        except Exception as exc:
            print('  omnivoice failed: {}; trying VoiceStudio'.format(type(exc).__name__), flush=True)
    if selected in ('VOICESTUDIO', 'OMNIVOICE'):
        try:
            result = (voicestudio or voicestudio_voice.fetch_speech)(text, cache_dir)
            if result is not None:
                return (*result, 'VOICESTUDIO')
        except Exception as exc:
            print('  voicestudio failed: {}; using Fish fallback'.format(type(exc).__name__), flush=True)
    result = fish(text, cache_dir)
    return (*(result if result is not None else (None, 0, False)), 'FISH')
