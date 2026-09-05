"""One family-specific Python process. JSON lines on stdout; logs on stderr."""
import contextlib
import json
import os
from pathlib import Path
import sys
import traceback


class Engine:
    def __init__(self, spec, folder, device):
        import torch
        self.torch = torch
        self.spec, self.folder = spec, Path(folder)
        self.device = ("cuda" if torch.cuda.is_available() else "cpu") if device == "auto" else device
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        family = spec["engine"]
        dtype = torch.float32 if self.device == "cpu" else torch.bfloat16
        if family == "kokoro":
            from kokoro import KModel
            self.model = KModel(repo_id=spec["repository"], config=str(self.folder / "config.json"),
                                model=str(self.folder / "kokoro-v1_0.pth")).to(self.device).eval()
            self.pipelines = {}
        elif family == "qwen":
            from qwen_tts import Qwen3TTSModel
            self.model = Qwen3TTSModel.from_pretrained(str(self.folder), device_map=self.device,
                                                      dtype=dtype, attn_implementation="sdpa")
        elif family == "omnivoice":
            from omnivoice import OmniVoice
            self.model = OmniVoice.from_pretrained(str(self.folder), device_map=self.device, dtype=dtype)
        elif family == "chatterbox":
            if spec["mode"] == "turbo":
                from chatterbox.tts_turbo import ChatterboxTurboTTS as Model
            elif spec["mode"] == "multilingual":
                from chatterbox.mtl_tts import ChatterboxMultilingualTTS as Model
            else:
                from chatterbox.tts import ChatterboxTTS as Model
            kw = {"t3_model": "v3"} if spec["mode"] == "multilingual" else {}
            self.model = Model.from_local(self.folder, self.device, **kw)
        else:
            raise ValueError("This model family has not been ported")

    def generate(self, request):
        import numpy as np
        import soundfile as sf
        self.torch.manual_seed(request.get("seed", 42))
        family, mode = self.spec["engine"], self.spec["mode"]
        text, voice = request["text"], request.get("voice") or self.spec.get("defaultVoice")
        language = request.get("language") or self.spec.get("defaultLanguage") or "en"
        reference, transcript = request.get("reference"), request.get("transcript")
        description = request.get("description", "")
        pace = request.get("pace", 1.)
        if family == "kokoro":
            from kokoro import KPipeline
            lang = {"en": "a", "en-US": "a", "en-GB": "b", "es": "e", "fr": "f", "hi": "h",
                    "it": "i", "ja": "j", "pt": "p", "cmn": "z", "zh": "z"}[language]
            if lang not in self.pipelines:
                self.pipelines[lang] = KPipeline(lang_code=lang, repo_id=self.spec["repository"], model=self.model)
            path = self.folder / "voices" / f"{voice}.pt"
            if not path.is_file():
                raise ValueError(f"Voice is not installed: {voice}")
            chunks = [a.cpu().numpy() for _, _, a in self.pipelines[lang](text, voice=str(path), speed=pace)]
            if not chunks:
                raise ValueError("Kokoro produced no audio")
            audio, sr = np.concatenate(chunks), 24000
        elif family == "qwen":
            language = {"en": "English", "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "de": "German",
                        "fr": "French", "ru": "Russian", "pt": "Portuguese", "es": "Spanish", "it": "Italian"}.get(language, language)
            kwargs = {"text": text, "language": language}
            if mode == "clone":
                if not reference or not transcript:
                    raise ValueError("Qwen Base requires a reference sample and transcript on Linux")
                wavs, sr = self.model.generate_voice_clone(**kwargs, ref_audio=reference, ref_text=transcript)
            elif mode == "design":
                wavs, sr = self.model.generate_voice_design(**kwargs, instruct=description or voice or "Warm storyteller")
            else:
                wavs, sr = self.model.generate_custom_voice(**kwargs, speaker=voice, instruct=description)
            audio = wavs[0]
        elif family == "omnivoice":
            kwargs = {"text": text, "language": language, "speed": pace}
            if reference:
                if not transcript:
                    raise ValueError("Provide a transcript to avoid downloading an extra ASR model")
                kwargs.update(ref_audio=reference, ref_text=transcript)
            elif description:
                kwargs["instruct"] = description
            audio, sr = self.model.generate(**kwargs)[0], 24000
        else:
            kwargs = {}
            if reference:
                kwargs["audio_prompt_path"] = reference
            if mode == "multilingual":
                kwargs["language_id"] = language
            audio = self.model.generate(text, **kwargs).detach().cpu().numpy().reshape(-1)
            sr = self.model.sr
        audio = np.asarray(audio).reshape(-1)
        if not len(audio) or not np.isfinite(audio).all():
            raise ValueError("The model produced invalid audio")
        sf.write(request["output"], audio, sr, subtype="PCM_16")
        return {"duration": len(audio) / sr, "sampleRate": sr}


def download(spec, folder):
    from huggingface_hub import snapshot_download
    patterns = ["*.json", "*.safetensors", "*.pt", "*.pth", "*.model", "*.txt", "*.tiktoken", "*.yaml"]
    snapshot_download(spec["repository"], local_dir=folder, allow_patterns=patterns)
    # Dependencies such as tokenizers/codecs may live in separate repositories.
    # Load once while online, and mark ready only after a successful load.
    engine = Engine(spec, folder, "cpu")
    if spec["engine"] == "kokoro":
        engine.generate({"text": "Ready.", "output": str(Path(folder) / ".warmup.wav")})
        (Path(folder) / ".warmup.wav").unlink()
    (Path(folder) / ".sayit-ready").write_text("1\n")


def main():
    protocol = sys.stdout
    engine = None
    for line in sys.stdin:
        try:
            req = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                if req["command"] == "download":
                    download(req["model"], req["folder"])
                    result = {"ready": True}
                elif req["command"] == "load":
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

