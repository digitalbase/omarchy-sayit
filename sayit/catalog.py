import json
import re
from pathlib import Path
from .paths import config_dir, data_dir, read_json


def models():
    builtins = json.loads(Path(__file__).with_name("models.json").read_text())
    custom = read_json(config_dir() / "models.json", [])
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
    return (model_path(model) / ".sayit-ready").exists()

