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
        # Apple Silicon GPU was faster than CPU on the Mac (Nov 8 2026).
        # JEV_OMNIVOICE_DEVICE=cpu opts out; any MPS failure stays on CPU.
        if os.environ.get("JEV_OMNIVOICE_DEVICE", "auto") != "cpu":
            try:
                import torch
                if torch.backends.mps.is_available():
                    self.model = self.model.to("mps")
            except Exception:
                pass

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
        seed = options.pop("seed", None)
        if seed is not None:
            # OmniVoice.generate has no seed argument; seed torch globally.
            import torch
            torch.manual_seed(int(seed))
        # Verified on Mac Nov 8 2026: generate returns a list of float32
        # torch tensors shaped (1, samples); rate comes from the model.
        audio = self.model.generate(text=request["input"], **options)
        samples = audio[0]
        if hasattr(samples, "detach"):
            samples = samples.detach().cpu().float().numpy()
        samples = samples.reshape(-1)
        rate = int(getattr(self.model, "sampling_rate", None) or 24000)
        sf.write(str(output), samples, rate, subtype="PCM_16")
