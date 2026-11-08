"""Jev-owned local profiles. Import copies consented WAVs, never databases."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import uuid

from .omnivoice_voice import validate_wav


class Profiles:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else Path.home() / "Library/Application Support/hey-jev/omnivoice"

    def _path(self, name):
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,79}", name):
            raise ValueError("Profile name must be a simple local name")
        return self.root / (name + ".json")

    def load(self, name):
        return json.loads(self._path(name).read_text())

    def create(self, name, reference, consent=False, settings=None):
        if consent is not True:
            raise ValueError("Explicit consent required for your own or an authorized voice")
        target = self._path(name)
        if target.exists():
            raise FileExistsError("Profile exists")
        source = Path(reference).expanduser().resolve(strict=True)
        validate_wav(source)
        settings = settings or {}
        if not isinstance(settings, dict) or set(settings) - {"ref_text", "seed", "speed", "pronunciation"}:
            raise ValueError("Unsupported profile settings")
        pronunciation = settings.get("pronunciation", {})
        if not isinstance(pronunciation, dict) or not all(
                isinstance(k, str) and k and isinstance(v, str) for k, v in pronunciation.items()):
            raise ValueError("Pronunciation must map words to spoken replacements")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        copied = self.root / (uuid.uuid4().hex + ".wav")
        # Unique destination: source audio and VoiceStudio data remain untouched.
        with copied.open("xb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
        os.chmod(str(copied), 0o600)
        profile = {"name": name, "created": datetime.now(timezone.utc).isoformat(),
                   "reference_wav": str(copied.absolute()), "settings": settings,
                   "consent": True}
        with target.open("x") as output:
            json.dump(profile, output, indent=2)
        os.chmod(str(target), 0o600)
        return profile

    def import_voice(self, name, filename, consent=False, source_dir=None):
        directory = (Path(source_dir) if source_dir is not None else
                     Path.home() / "Library/Application Support/OmniVoice/voices").resolve()
        source = (directory / filename).resolve(strict=True)
        if source.parent != directory or source.suffix.lower() != ".wav":
            raise ValueError("Import requires a WAV directly in the voices folder")
        return self.create(name, source, consent=consent)

    def render(self, name, text, output, worker):
        profile = self.load(name)
        if profile.get("consent") is not True:
            raise ValueError("Profile lacks explicit consent")
        settings = dict(profile["settings"])
        for word, spoken in settings.pop("pronunciation", {}).items():
            text = re.sub(r"\b" + re.escape(word) + r"\b", lambda match: spoken, text)
        return worker.render(text, output, voice=name,
                             reference=profile["reference_wav"], settings=settings)
