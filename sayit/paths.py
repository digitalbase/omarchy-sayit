import json
import os
from pathlib import Path
import tempfile


def private_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def data_dir():
    return private_dir(Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "sayit")


def config_dir():
    return private_dir(Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "sayit")


def runtime_dir():
    root = Path(os.environ.get("XDG_RUNTIME_DIR", f"/tmp/sayit-{os.getuid()}"))
    return private_dir(root / "sayit")


def atomic_json(path, value):
    path = Path(path)
    private_dir(path.parent)
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default

