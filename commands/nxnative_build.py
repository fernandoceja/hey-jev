"""Click-only local NXNative builds. Never inspect keys or modify game dumps."""
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

ROOT = Path('~/Documents/Fernando Ceja/Emulation/NXNATIVE').expanduser()
REPO = Path('~/Developer/nxnative').expanduser()
DEFAULT_KEYS = '~/Library/Application Support/Ryujinx/system/prod.keys'
LOGS = Path('~/Library/Logs/Hey Jev NXNative').expanduser()
PYTHONS = ('/opt/homebrew/bin/python3.12', '/opt/homebrew/bin/python3.13',
           '/opt/homebrew/bin/python3.14', 'python3.12', 'python3.13', 'python3')


def scrub(line):
    # Drop entire lines containing key-looking hex values, including wrapped values.
    if re.search(r'(?i)(?<![0-9a-f])[0-9a-f]{32,}(?![0-9a-f])', line):
        return '[redacted key-like output]\n'
    return line


def find_python(run=subprocess.run):
    for candidate in PYTHONS:
        try:
            result = run([candidate, '-c', 'import sys; print("%d.%d" % sys.version_info[:2])'],
                         capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and tuple(map(int, result.stdout.strip().split('.'))) >= (3, 12):
                return candidate
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    raise ValueError('Python 3.12 or newer is required. Install it yourself, then try again.')


class Builder:
    def __init__(self, root=ROOT, repo=REPO, logs=LOGS, keys=None,
                 python=find_python, disk=shutil.disk_usage, popen=subprocess.Popen,
                 killpg=os.killpg, now=time.monotonic):
        self.root, self.repo, self.logs = Path(root), Path(repo), Path(logs)
        self.keys = Path(keys or os.environ.get('JEV_NXNATIVE_KEYS', DEFAULT_KEYS)).expanduser()
        self.python, self.disk, self.popen, self.killpg, self.now = python, disk, popen, killpg, now
        self.lock = threading.RLock()
        self.active = None

    def discover(self):
        for folder in ('Inbox', 'Builds'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        return sorted((p for p in (self.root / 'Inbox').iterdir()
                       if p.is_dir() and self.dumps(p)), key=lambda p: p.name.lower())

    def dumps(self, game):
        return [p for p in game.rglob('*') if p.is_file() and p.suffix.lower() in ('.nsp', '.xci')]

    def status(self):
        with self.lock:
            if self.active:
                return 'Building {}… {} min elapsed'.format(
                    self.active['game'], int((self.now() - self.active['at']) / 60))
        return ''

    def start(self, game, callback, platform=None, zoe=False):
        if (platform or sys.platform) != 'darwin':
            return 'NXNative builds run on this Mac only.'
        if zoe:
            return 'NXNative builds are grown-up work. Leave Zoe mode first.'
        with self.lock:
            if self.active:
                return self.status()
            try:
                games = self.discover()
                game = Path(game)
                if game not in games:
                    raise ValueError('That Inbox game folder is no longer available.')
                python = self.python()
                needed = 2 * sum(p.stat().st_size for p in self.dumps(game)) + 10 * 1024**3
                if self.disk(self.root / 'Builds').free < needed:
                    raise ValueError('Not enough disk space: need twice the dump size plus 10 GB free.')
                if not self.keys.is_file():
                    raise ValueError('prod.keys is missing at {}. Set JEV_NXNATIVE_KEYS to your keys path.'.format(self.keys))
                if not (self.repo / 'scripts/build_ipa_from_nsp.py').is_file():
                    raise ValueError('NXNative build script is missing in {}.'.format(self.repo))
                output = self.root / 'Builds' / game.name
                output.mkdir(exist_ok=True)
                self.logs.mkdir(parents=True, exist_ok=True)
                safe = re.sub(r'[^\w .-]', '_', game.name)
                log = self.logs / ('{}-{}.log'.format(safe, time.time_ns()))
                stream = log.open('w', encoding='utf-8')
                try:
                    proc = self.popen([python, 'scripts/build_ipa_from_nsp.py', str(game),
                                       '-k', str(self.keys), '-o', str(output), '--app-name', game.name],
                                      cwd=str(self.repo), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, errors='replace', start_new_session=True)
                except Exception:
                    stream.close()
                    raise
                state = dict(game=game.name, at=self.now(), proc=proc, log=log,
                             output=output, cancelled=False)
                self.active = state
                line = self.status()
                threading.Thread(target=self._watch, args=(state, stream, callback), daemon=True).start()
                return line
            except Exception as exc:
                return 'Cannot start NXNative build: {}'.format(exc)

    def _watch(self, state, stream, callback):
        tail = deque(maxlen=20)
        try:
            with stream:
                for line in state['proc'].stdout:
                    line = scrub(line)
                    stream.write(line)
                    stream.flush()
                    tail.append(line.rstrip())
            code = state['proc'].wait()
            message = ('Cancelled {}.' if state['cancelled'] else
                       'Built {}, IPA ready' if code == 0 else 'Build failed for {}.').format(state['game'])
        except Exception:
            code, message = -1, 'Build monitoring failed. Check the local log.'
        finally:
            with self.lock:
                self.active = None
        callback(dict(state, success=code == 0 and not state['cancelled'], message=message,
                      tail='\n'.join(tail)))

    def cancel(self):
        with self.lock:
            state = self.active
            if not state:
                return 'No NXNative build is running.'
            state['cancelled'] = True
            try:
                self.killpg(state['proc'].pid, signal.SIGTERM)
                threading.Thread(target=self._reap_cancel, args=(state,), daemon=True).start()
            except ProcessLookupError:
                pass
            except OSError:
                return 'Could not cancel the build. Try again.'
            return 'Cancelling {}…'.format(state['game'])

    def _reap_cancel(self, state):
        try:
            state['proc'].wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                self.killpg(state['proc'].pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def fix_prompt(self, result, run=subprocess.run):
        prompt = ('Read the NXNative build log at {} for {}.\n'
                  'Propose a fix on a new branch with tests; never push to main.\n'
                  'Do not read key contents or download keys, firmware, or games.\n'
                  'Ask before running another build. Do not push any branch.\n').format(result['log'], result['game'])
        path = self.repo / 'claude-fix-prompt.md'
        path.write_text(prompt, encoding='utf-8')
        run(['pbcopy'], input=prompt, text=True, check=True)
        run(['open', '-a', 'Terminal', str(self.repo)], check=True)
        return 'Prompt copied and saved to {}. Paste it into Claude Code when ready.'.format(path)


BUILD = Builder()
