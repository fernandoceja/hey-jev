"""Personal-use native provider. All inference stays in a disposable process."""
import atexit
import json
import os
from pathlib import Path
import selectors
import subprocess
import tempfile
import threading
import time
import wave

MAX_MESSAGE = 65536


def runtime_python():
    configured = os.environ.get("JEV_OMNIVOICE_PYTHON")
    if configured:
        return configured
    # Candidate locations only, never inspect the app's source or internals.
    candidates = [Path.home() / "Library/Application Support/VoiceStudio/.venv/bin/python",
                  Path.home() / "Library/Application Support/OmniVoice/.venv/bin/python"]
    for path in candidates:
        if path.is_file():
            return str(path)
    raise RuntimeError("Set JEV_OMNIVOICE_PYTHON to the existing VoiceStudio runtime Python")


def validate_wav(path):
    with wave.open(str(path), "rb") as wav:
        if not wav.getnframes():
            raise ValueError("Empty WAV")
        return wav.getnframes() / wav.getframerate()


class Worker:
    def __init__(self, timeout=None, idle=None):
        self.timeout = float(timeout if timeout is not None else os.environ.get("JEV_OMNIVOICE_TIMEOUT", 180))
        self.idle = float(idle if idle is not None else os.environ.get("JEV_OMNIVOICE_IDLE", 120))
        if not 0 < self.timeout <= 1800 or not 0 < self.idle <= 3600:
            raise ValueError("Worker timeout/idle outside bounds")
        self.process = None
        self.timer = None
        self.lock = threading.RLock()
        self.disabled = False
        self.generation = 0

    def _stop(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None
        process, self.process = self.process, None
        if process:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=2)
            finally:
                process.stdin.close()
                process.stdout.close()

    def close(self):
        with self.lock:
            self._stop()

    def reset(self):
        with self.lock:
            self._stop()
            self.disabled = False

    def _expire(self, generation=None):
        with self.lock:
            if generation is not None and generation != self.generation:
                return
            self._stop()  # exiting the process releases model and accelerator RAM

    def render(self, text, output, voice="default", description=None,
               reference=None, settings=None, cancel=None):
        request = {"model": "omnivoice", "input": text, "voice": voice,
                   "response_format": "wav", "output": str(Path(output).absolute()),
                   "description": description, "reference": reference, "settings": settings or {}}
        message = (json.dumps(request) + "\n").encode()
        if len(message) > MAX_MESSAGE or not isinstance(text, str) or not 0 < len(text) <= 4096:
            raise ValueError("Request exceeds protocol bounds")
        destination = Path(output).expanduser().absolute()
        if destination.suffix.lower() != ".wav":
            raise ValueError("Explicit .wav output path required")
        with self.lock:
            if self.disabled:
                raise RuntimeError("OmniVoice disabled for this session; reset explicitly to retry")
            temporary = None
            try:
                self.generation += 1
                if self.timer:
                    self.timer.cancel()
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("Cancelled")
                if self.process is None:
                    env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
                    self.process = subprocess.Popen(
                        [runtime_python(), "-m", "commands.omnivoice_worker"],
                        cwd=str(Path(__file__).resolve().parents[1]), env=env,
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                destination.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(suffix=".wav", dir=str(destination.parent))
                os.close(fd)
                request["output"] = temporary
                message = (json.dumps(request) + "\n").encode()
                if len(message) > MAX_MESSAGE:
                    raise ValueError("Request exceeds protocol bounds")
                started = time.monotonic()
                # Nonblocking writes are bounded too: a hung child may never
                # read stdin, even before it loads the model.
                os.set_blocking(self.process.stdin.fileno(), False)
                sent = 0
                with selectors.DefaultSelector() as sender:
                    sender.register(self.process.stdin, selectors.EVENT_WRITE)
                    while sent < len(message):
                        if cancel is not None and cancel.is_set():
                            raise InterruptedError("Cancelled")
                        if time.monotonic() - started >= self.timeout:
                            raise TimeoutError("OmniVoice request write timed out")
                        if sender.select(min(.1, self.timeout)):
                            try:
                                sent += os.write(self.process.stdin.fileno(), message[sent:])
                            except BlockingIOError:
                                continue
                reply = bytearray()
                with selectors.DefaultSelector() as selector:
                    selector.register(self.process.stdout, selectors.EVENT_READ)
                    while b"\n" not in reply:
                        if cancel is not None and cancel.is_set():
                            raise InterruptedError("Cancelled")
                        if time.monotonic() - started >= self.timeout:
                            raise TimeoutError("OmniVoice timed out")
                        if selector.select(min(.1, self.timeout)):
                            chunk = os.read(self.process.stdout.fileno(), 4096)
                            if not chunk:
                                raise RuntimeError("OmniVoice worker exited")
                            reply.extend(chunk)
                            if len(reply) > MAX_MESSAGE:
                                raise ValueError("Oversized worker response")
                result = json.loads(reply)
                if not result.get("ok"):
                    raise RuntimeError("OmniVoice engine error: " + result.get("error", "unknown"))
                validate_wav(temporary)
                os.replace(temporary, destination)
                self.timer = threading.Timer(self.idle, self._expire, args=(self.generation,))
                self.timer.daemon = True
                self.timer.start()
                return str(destination), int((time.monotonic() - started) * 1000), False
            except BaseException:
                self.disabled = True
                self._stop()
                raise
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)


_worker = None
_worker_lock = threading.Lock()


def worker():
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = Worker()
        return _worker


def close():
    if _worker is not None:
        _worker.close()


atexit.register(close)


def fetch_speech(text, cache_dir):
    from .fish_voice import strip_fish_cues
    import hashlib
    text = strip_fish_cues(text)
    # Native selection deliberately defaults to the unconditioned engine voice.
    path = Path(cache_dir) / "omnivoice" / (hashlib.sha256(text.encode()).hexdigest() + ".wav")
    if path.is_file():
        validate_wav(path)
        return str(path), 0, True
    return worker().render(text, path)
