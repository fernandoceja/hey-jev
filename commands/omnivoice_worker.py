"""Bounded JSON-lines stdio worker. No services, playback, or eager model load."""
import contextlib
import json
import os
import sys

MAX_MESSAGE = 65536


def handle(request, engine_factory):
    if request.get("model") != "omnivoice" or request.get("response_format") != "wav":
        raise ValueError("Only OmniVoice WAV requests are supported")
    text = request.get("input")
    if not isinstance(text, str) or not 0 < len(text) <= 4096:
        raise ValueError("Input must contain 1-4096 characters")
    if request.get("voice", "default") != "default" and not request.get("reference"):
        raise ValueError("Named voices require a local reference")
    engine_factory().render(request, request["output"])
    return {"ok": True, "provider": "OMNIVOICE", "model": "k2-fsa/OmniVoice"}


def main():
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    engine = None

    def load():
        nonlocal engine
        if engine is None:
            from commands.omnivoice_engine import Engine
            engine = Engine()
        return engine

    while True:
        line = sys.stdin.buffer.readline(MAX_MESSAGE + 1)
        if not line:
            return
        if len(line) > MAX_MESSAGE or not line.endswith(b"\n"):
            return  # oversized/partial frames invalidate this process
        try:
            # Third-party progress output must never corrupt the protocol.
            with contextlib.redirect_stdout(sys.stderr):
                result = handle(json.loads(line), load)
        except Exception as exc:
            result = {"ok": False, "error": type(exc).__name__}
        sys.stdout.write(json.dumps(result) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
