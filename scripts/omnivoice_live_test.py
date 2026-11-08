"""Real, offline Mac acceptance measurements. No playback and no fallback."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from commands.omnivoice_voice import Worker, runtime_python, validate_wav

SHORT = "The time is nine thirty. Your next appointment is at ten."
LONG = ("Here is your morning brief. Take a moment to plan the day, check your calendar, "
        "and leave time for a walk. The afternoon is free for reading and family. ") * 8


def rss(pid):
    # ps reports current resident memory in KiB on macOS and Linux.
    result = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True,
                            text=True, timeout=2, check=True)
    return int(result.stdout.strip()) * 1024


def measure(worker, text, path):
    samples, errors = [], []
    done = threading.Event()

    def sample():
        while not done.is_set():
            process = worker.process
            if process is not None:
                try:
                    samples.append(rss(process.pid))
                except Exception as exc:
                    errors.append(type(exc).__name__)
            done.wait(.05)

    thread = threading.Thread(target=sample, daemon=True)
    started = time.monotonic()
    thread.start()
    try:
        worker.render(text, path)
    finally:
        elapsed = time.monotonic() - started
        done.set()
        thread.join(timeout=3)
    return {"input": text, "output": str(path), "seconds": elapsed,
            "audio_seconds": validate_wav(path), "peak_worker_rss_bytes": max(samples) if samples else None,
            "rss_sample_errors": errors, "provider": "OMNIVOICE", "model": "k2-fsa/OmniVoice"}


def run(output, idle=120):
    output = Path(output).expanduser().absolute()
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "report.json"
    if report_path.exists() or any((output / (name + ".wav")).exists() for name in
                                 ("cold", "warm_short", "long", "recovered")):
        raise FileExistsError("Use a fresh output folder to preserve evidence")
    report = {"gate": "PENDING", "environment": platform.platform(), "jev_python": sys.version,
              "provider": "OMNIVOICE", "model": "k2-fsa/OmniVoice", "fallbacks": [],
              "measurements": {}, "rss_method": "ps rss KiB * 1024 sampled every 50ms; worker only, not system peak",
              "timing": "parent render start through validated WAV; cold includes process startup and model load",
              "baseline_seconds": {"cold": 15.01, "time": 6.281, "date": 7.349,
                                   "weather": 13.123, "brief": 32.618},
              "manual_pending": ["Default voice listening comparison", "Jev explicit read-aloud UI usability",
                                 "Voice Design A/B and consented profile audition"]}
    worker = Worker(idle=idle)
    try:
        report["runtime_python"] = runtime_python()
        report["offline"] = True
        for name, text in (("cold", SHORT), ("warm_short", SHORT), ("long", LONG)):
            report["measurements"][name] = measure(worker, text, output / (name + ".wav"))
        process = worker.process
        report["rss_before_idle_bytes"] = rss(process.pid)
        started = time.monotonic()
        deadline = started + idle + 5
        while worker.process is not None and time.monotonic() < deadline:
            time.sleep(.1)
        # _stop() clears worker.process before kill/wait finish on the timer
        # thread; give the exit a bounded moment so the check isn't racy.
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        report["idle_unload"] = {"seconds": time.monotonic() - started,
                                 "process_exited": process.poll() is not None,
                                 "process_released": worker.process is None}
        # Start a real worker again, then kill it. The next request must fail
        # boundedly, disable retries, and allow explicit reset/recovery.
        measure(worker, SHORT, output / "before_crash.wav")
        worker.process.kill()
        worker.process.wait(timeout=3)
        started = time.monotonic()
        try:
            worker.render(SHORT, output / "should_not_exist.wav")
            report["crash_detected"] = False
        except Exception as exc:
            report["crash_detected"] = worker.disabled
            report["expected_crash_error"] = type(exc).__name__
        report["crash_failure_seconds"] = time.monotonic() - started
        worker.reset()
        report["measurements"]["recovered"] = measure(worker, SHORT, output / "recovered.wav")
        report["automated_checks_passed"] = bool(
            report["crash_detected"] and report["idle_unload"]["process_exited"] and
            report["idle_unload"]["process_released"] and all(
                m["peak_worker_rss_bytes"] is not None for m in report["measurements"].values()))
        # Listening/UI checks are necessarily manual; mocks or this script alone
        # must never mark the actual Mac acceptance gate passed.
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
        report["automated_checks_passed"] = False
    finally:
        worker.close()
        report_path.write_text(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--idle-seconds", type=float, default=120)
    args = parser.parse_args()
    report = run(args.output, args.idle_seconds)
    print(json.dumps(report, indent=2))
    return 0 if report.get("automated_checks_passed") else 1


if __name__ == "__main__":
    sys.exit(main())
