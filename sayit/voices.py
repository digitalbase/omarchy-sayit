import array
import math
import re
import subprocess
import tempfile
import uuid
import wave
from pathlib import Path
from .paths import atomic_json, data_dir, private_dir, read_json


def voices():
    return read_json(data_dir() / "voices.json", [])


def inspect_sample(path):
    with wave.open(str(path)) as wav:
        if wav.getsampwidth() != 2 or wav.getnchannels() != 1:
            raise ValueError("Expected a mono PCM16 WAV")
        duration = wav.getnframes() / wav.getframerate()
        samples = array.array("h", wav.readframes(wav.getnframes()))
    if not 3 <= duration <= 30:
        raise ValueError("Use a reference recording between 3 and 30 seconds")
    rms = math.sqrt(sum(x*x for x in samples) / len(samples)) / 32768
    clipped = sum(abs(x) >= 32760 for x in samples) / len(samples)
    if rms < .002:
        raise ValueError("The recording is too quiet or silent")
    warnings = []
    if clipped > .001:
        warnings.append("The recording clips; lower microphone gain and record again")
    if duration > 15:
        warnings.append("Some models require a shorter sample; 6 to 10 seconds is a useful default")
    return {"duration": duration, "rms": rms, "clipping": clipped, "warnings": warnings}


def transcribe(path):
    # Force local Whisper even if the user has configured a remote Voxtype engine.
    result = subprocess.run(["voxtype", "--engine", "whisper", "--whisper-mode", "local",
                             "transcribe", str(path)], text=True, capture_output=True, timeout=300, check=True)
    # Voxtype 1.0.1 writes progress lines, then a blank line and the transcript.
    parts = re.split(r"\r?\n\s*\r?\n", result.stdout.strip(), maxsplit=1)
    if len(parts) != 2 or not parts[1].strip():
        raise ValueError("Voxtype returned no transcript. Enter the sample transcript manually.")
    return parts[1].strip()


def add_voice(name, sample, transcript="", auto_transcribe=False):
    if not name.strip():
        raise ValueError("Provide a voice name")
    identifier = uuid.uuid4().hex
    folder = private_dir(data_dir() / "voices")
    output = folder / f"{identifier}.wav"
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(Path(sample).resolve()),
                        "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(output)], check=True, timeout=60)
        quality = inspect_sample(output)
        if auto_transcribe:
            with tempfile.TemporaryDirectory(dir=folder) as tmp:
                wav = Path(tmp) / "asr.wav"
                subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(output),
                                "-ar", "16000", str(wav)], check=True, timeout=60)
                transcript = transcribe(wav)
        profile = {"id": identifier, "name": name.strip(), "reference": str(output),
                   "transcript": transcript.strip(), **quality}
        atomic_json(data_dir() / "voices.json", voices() + [profile])
        return profile
    except BaseException:
        output.unlink(missing_ok=True)
        raise

