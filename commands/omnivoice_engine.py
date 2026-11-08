"""Only engine-dependent code. API assumptions require real Mac verification.

Independent implementation from Jev's behavior brief; no VoiceStudio sources.
"""
import os

MODEL = "k2-fsa/OmniVoice"


class Engine:
    def __init__(self):
        # Set before importing HF or model libraries; never use a custom cache.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from huggingface_hub import snapshot_download
        from omnivoice import OmniVoice
        # Resolving locally catches absent snapshots. Actual shard/tokenizer
        # completeness is checked by the loader, still offline.
        snapshot = snapshot_download(MODEL, cache_dir=os.path.expanduser(
            "~/.cache/huggingface/hub"), local_files_only=True)
        self.model = OmniVoice.from_pretrained(snapshot, local_files_only=True)

    def render(self, request, output):
        import soundfile as sf
        options = dict(request.get("settings", {}))
        allowed = {"ref_text", "seed", "speed"}
        if set(options) - allowed:
            raise ValueError("Unsupported engine settings")
        if request.get("reference"):
            options["ref_audio"] = request["reference"]
        if request.get("description"):
            # Assumption: voice-design conditioning uses instruct. Verify on Mac.
            options["instruct"] = request["description"]
        # Assumption: no conditioning matches the installed default voice;
        # output is a list of mono arrays at 24 kHz (upstream public example).
        audio = self.model.generate(text=request["input"], **options)
        sf.write(str(output), audio[0], 24000, subtype="PCM_16")
