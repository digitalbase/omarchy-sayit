import json
import re
from pathlib import Path
from .artifacts import fingerprint, validate_model
from .paths import config_dir, data_dir, read_json


def models():
    builtins = json.loads(Path(__file__).with_name("models.json").read_text())
    custom = read_json(config_dir() / "models.json", [])
    for model in custom:
        validate_model(model)
        if any(m["id"] == model["id"] for m in builtins):
            raise ValueError("Custom model IDs must not shadow built-in models")
    return builtins + custom


def model_by_id(identifier):
    for model in models():
        if model["id"] == identifier:
            return model
    raise ValueError(f"Unknown model: {identifier}")


def model_path(model):
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", model["id"]):
        raise ValueError("Invalid model ID")
    return data_dir() / "models" / model["id"]


def installed(model):
    try:
        return (model_path(model) / ".sayit-ready").read_text().strip() == fingerprint(model)
    except (OSError, ValueError):
        return False

