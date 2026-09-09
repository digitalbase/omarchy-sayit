"""Pinned model acquisition. No model or dependency code runs in this module."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
import urllib.request

SUPPORTED_ENGINES = frozenset({"kokoro"})
# Reviewed against the pinned Kokoro files; see docs/runtime-locks.md.
# Custom models use the same limits and cannot override them.
CONFIG_MAX_BYTES = 64 * 1024
WEIGHTS_MAX_BYTES = 350 * 1024 * 1024
VOICE_MAX_BYTES = 1024 * 1024


def artifact_max_bytes(name):
    if name == "config.json":
        return CONFIG_MAX_BYTES
    if name == "kokoro-v1_0.pth":
        return WEIGHTS_MAX_BYTES
    return VOICE_MAX_BYTES


def validate_model(spec):
    if spec.get("engine") not in SUPPORTED_ENGINES:
        raise ValueError("This engine is disabled until its runtime sources are locked")
    if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", spec.get("repository", "")):
        raise ValueError("Invalid model repository")
    if not re.fullmatch(r"[0-9a-f]{40}", spec.get("revision", "")):
        raise ValueError("Model revision must be a full 40-character commit SHA")
    artifacts = spec.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError("Model must declare artifact SHA-256 hashes")
    for name, digest in artifacts.items():
        path = PurePosixPath(name)
        if (path.is_absolute() or str(path) != name or ".." in path.parts
                or not re.fullmatch(r"[A-Za-z0-9_./-]+", name)
                or not re.fullmatch(r"[0-9a-f]{64}", str(digest))):
            raise ValueError("Invalid artifact path or SHA-256 hash")
        if name not in {"config.json", "kokoro-v1_0.pth"} and not re.fullmatch(r"voices/[a-z0-9_]+\.pt", name):
            raise ValueError("Unsupported Kokoro artifact")
    if not {"config.json", "kokoro-v1_0.pth"} <= artifacts.keys():
        raise ValueError("Missing Kokoro config or weights hash")
    voices = spec.get("voices", [])
    if not voices or spec.get("defaultVoice") not in voices:
        raise ValueError("Declare voices and a default voice")
    for voice in voices:
        if not re.fullmatch(r"[a-z0-9_]+", voice) or f"voices/{voice}.pt" not in artifacts:
            raise ValueError("Every voice needs a pinned artifact hash")
    languages = spec.get("languages", ["en-US"])
    if not languages or any(v not in {"en", "en-US", "en-GB", "es", "fr", "it", "pt", "hi"} for v in languages):
        raise ValueError("Language dependencies are not locked")
    return artifacts


def digest_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fingerprint(spec):
    validate_model(spec)
    identity = {k: spec[k] for k in ("engine", "repository", "revision", "artifacts")}
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def artifact_path(folder, name):
    folder = Path(folder).resolve()
    path = folder / name
    if path.is_symlink() or not path.resolve().is_relative_to(folder):
        raise ValueError("Model artifacts must stay within their model directory")
    return path


def verify_model(spec, folder):
    for name, digest in validate_model(spec).items():
        path = artifact_path(folder, name)
        if not path.is_file() or digest_file(path) != digest:
            raise ValueError(f"Missing or modified model artifact: {name}. Run sayit download again.")
    return fingerprint(spec)


def download_model(spec, folder):
    artifacts = validate_model(spec)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ".sayit-ready").unlink(missing_ok=True)
    for name, digest in artifacts.items():
        target = artifact_path(folder, name)
        if target.is_file() and digest_file(target) == digest:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/{spec['repository']}/resolve/{spec['revision']}/{name}"
        temporary = None
        limit = artifact_max_bytes(name)
        try:
            with urllib.request.urlopen(url, timeout=60) as source, tempfile.NamedTemporaryFile(
                    dir=target.parent, delete=False) as output:
                temporary = Path(output.name)
                length = source.headers.get("Content-Length")
                if length is not None:
                    if not re.fullmatch(r"[0-9]+", length) or int(length) > limit:
                        raise ValueError(f"Invalid or oversized Content-Length for {name}; limit is {limit} bytes")
                actual = hashlib.sha256()
                received = 0
                while chunk := source.read(min(1024 * 1024, limit - received + 1)):
                    received += len(chunk)
                    if received > limit:
                        raise ValueError(f"Download exceeds {limit} byte limit for {name}")
                    output.write(chunk)
                    actual.update(chunk)
            if actual.hexdigest() != digest:
                raise ValueError(f"SHA-256 mismatch for {name}; downloaded artifact was rejected")
            temporary.replace(target)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
    (folder / ".sayit-ready").write_text(verify_model(spec, folder) + "\n")
    return {"ready": True}
