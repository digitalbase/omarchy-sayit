"""One family-specific Python process. JSON lines on stdout; logs on stderr."""
import contextlib
import json
import hashlib
import io
import os
from pathlib import Path
import sys
import traceback
from sayit.artifacts import verify_model


class Engine:
    def __init__(self, spec, folder, device):
        verify_model(spec, folder)
        import torch
        self.torch = torch
        self.spec, self.folder = spec, Path(folder)
        self.device = ("cuda" if torch.cuda.is_available() else "cpu") if device == "auto" else device
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        family = spec["engine"]
        if family == "kokoro":
            from kokoro import KModel
            self.model = KModel(repo_id=spec["repository"], config=str(self.folder / "config.json"),
                                model=str(self.folder / "kokoro-v1_0.pth")).to(self.device).eval()
            self.pipelines = {}
            self.voices = {}

    def generate(self, request):
        import numpy as np
        import soundfile as sf
        self.torch.manual_seed(request.get("seed", 42))
        family = self.spec["engine"]
        text, voice = request["text"], request.get("voice") or self.spec.get("defaultVoice")
        language = request.get("language") or self.spec.get("defaultLanguage") or "en"
        pace = request.get("pace", 1.)
        if family == "kokoro":
            if voice not in self.spec["voices"]:
                raise ValueError("Voice is not declared in the verified model manifest")
            if language not in self.spec["languages"] and language != "en":
                raise ValueError("Language is not supported by the locked engine")
            from kokoro import KPipeline
            lang = {"en": "a", "en-US": "a", "en-GB": "b", "es": "e", "fr": "f", "hi": "h",
                    "it": "i", "ja": "j", "pt": "p", "cmn": "z", "zh": "z"}[language]
            if lang not in self.pipelines:
                self.pipelines[lang] = KPipeline(lang_code=lang, repo_id=self.spec["repository"], model=self.model)
            path = self.folder / "voices" / f"{voice}.pt"
            if not path.is_file():
                raise ValueError(f"Voice is not installed: {voice}")
            if voice not in self.voices:
                payload = path.read_bytes()
                if hashlib.sha256(payload).hexdigest() != self.spec["artifacts"][f"voices/{voice}.pt"]:
                    raise ValueError("Voice artifact changed after model verification")
                self.voices[voice] = self.torch.load(io.BytesIO(payload), map_location="cpu", weights_only=True)
            chunks = [a.cpu().numpy() for _, _, a in self.pipelines[lang](text, voice=self.voices[voice], speed=pace)]
            if not chunks:
                raise ValueError("Kokoro produced no audio")
            audio, sr = np.concatenate(chunks), 24000
        audio = np.asarray(audio).reshape(-1)
        if not len(audio) or not np.isfinite(audio).all():
            raise ValueError("The model produced invalid audio")
        sf.write(request["output"], audio, sr, subtype="PCM_16")
        return {"duration": len(audio) / sr, "sampleRate": sr}


def deny_network(event, args):
    # Acquisition happens in the stdlib parent, before model code is imported.
    # Fail closed if a library tries to obtain another model or tokenizer.
    if event == "subprocess.Popen" and len(args) >= 2 and args[1] == ["/sbin/ldconfig", "-p"]:
        return  # ctypes reads the system library cache; this installs nothing.
    if event in {"socket.connect", "socket.getaddrinfo", "subprocess.Popen",
                 "os.system", "os.exec", "os.posix_spawn"}:
        raise RuntimeError("Model workers cannot download or execute additional dependencies")


def main():
    sys.addaudithook(deny_network)
    protocol = sys.stdout
    engine = None
    for line in sys.stdin:
        try:
            req = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                if req["command"] == "load":
                    engine = Engine(req["model"], req["folder"], req.get("device", "auto"))
                    result = {"loaded": True}
                else:
                    if engine is None:
                        raise ValueError("Load a model first")
                    result = engine.generate(req)
            print(json.dumps({"ok": True, "result": result}), file=protocol, flush=True)
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            print(json.dumps({"ok": False, "error": str(exc)}), file=protocol, flush=True)


if __name__ == "__main__":
    main()

