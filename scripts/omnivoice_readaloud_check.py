"""Offline native read-aloud check; saves audio and report, never plays it."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from commands.tts_chain import fetch_with_fallback
from commands.omnivoice_voice import close, validate_wav


def no_fish(text, cache_dir):
    raise RuntimeError('Fish fallback forbidden in read-aloud check')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir', required=True)
    parser.add_argument('--text', default='Hello, Jev. This is the native read-aloud check.')
    args = parser.parse_args(argv)
    cache = Path(args.cache_dir)
    cache.mkdir(parents=True, exist_ok=False)
    os.environ['JEV_TTS_PROVIDER'] = 'OMNIVOICE'
    started = time.monotonic()
    report = {'provider': None, 'path': None, 'cached': False, 'audio_seconds': None}
    status = 1
    try:
        path, ms, cached, provider = fetch_with_fallback(args.text, cache, fish=no_fish)
        report.update(provider=provider, path=path, cached=cached)
        report['audio_seconds'] = validate_wav(path)
        status = 0 if provider == 'OMNIVOICE' else 1
    except Exception as exc:
        report['error'] = str(exc)
    finally:
        close()
        report['seconds'] = time.monotonic() - started
        destination = Path(report['path']).parent if report['path'] else cache
        (destination / 'report.json').write_text(json.dumps(report, indent=2))
    return status


if __name__ == '__main__':
    sys.exit(main())
