import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from .catalog import model_path
from .paths import data_dir, private_dir

PACKAGES = {
    "kokoro": ["kokoro==0.9.4", "misaki[en,ja,zh]>=0.9.4,<1", "transformers<5", "soundfile", "espeakng-loader",
               "https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"],
    "qwen": ["qwen-tts==0.1.1", "soundfile"],
    "chatterbox": ["git+https://github.com/resemble-ai/chatterbox.git@" + "5de7a54aa4e5e2baadb0182dde554908b48b85c2", "soundfile"],
    "omnivoice": ["omnivoice==0.2.1", "soundfile"],
}


def python_for(family):
    if family not in PACKAGES:
        raise ValueError("This model family has not been ported")
    return data_dir() / "engines" / family / "bin/python"


def setup(family, cuda=False):
    python = python_for(family)
    uv = shutil.which("uv")
    if not uv:
        local = Path(__file__).resolve().parent.parent / ".tools/bin/uv"
        if local.exists():
            uv = str(local)
    if not uv:
        raise ValueError("Install uv, or run scripts/bootstrap.sh first")
    subprocess.run([uv, "venv", "--python", "3.11", str(python.parent.parent)], check=True)
    # Select CPU wheels by default to avoid multi-gigabyte CUDA dependencies.
    index = "https://download.pytorch.org/whl/cu126" if cuda else "https://download.pytorch.org/whl/cpu"
    subprocess.run([uv, "pip", "install", "--python", str(python), "torch==2.6.0", "torchaudio==2.6.0",
                    "--index-url", index], check=True)
    subprocess.run([uv, "pip", "install", "--python", str(python), *PACKAGES[family]], check=True)


class Worker:
    def __init__(self, model, online=False):
        self.model = model
        self.lock = threading.Lock()
        python = python_for(model["engine"])
        if not python.exists():
            raise ValueError(f"Run: sayit setup {model['engine']}")
        env = os.environ.copy()
        env.update(HF_HOME=str(private_dir(data_dir() / "huggingface")), HF_HUB_DISABLE_TELEMETRY="1",
                   HF_HUB_OFFLINE="0" if online else "1", TRANSFORMERS_OFFLINE="0" if online else "1")
        log = open(data_dir() / "engine.log", "a")
        try:
            self.process = subprocess.Popen([str(python), "-u", str(Path(__file__).with_name("worker.py"))],
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                            text=True, env=env, start_new_session=True)
        finally:
            log.close()

    def call(self, command, **kwargs):
        with self.lock:
            self.process.stdin.write(json.dumps({"command": command, **kwargs}) + "\n")
            self.process.stdin.flush()
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError(f"Model worker stopped. See {data_dir() / 'engine.log'}")
            response = json.loads(line)
            if not response["ok"]:
                raise RuntimeError(response["error"])
            return response["result"]

    def load(self, device="auto"):
        return self.call("load", model=self.model, folder=str(model_path(self.model)), device=device)

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()


def download(model):
    folder = private_dir(model_path(model))
    if (folder / ".sayit-ready").exists():
        return {"ready": True}
    worker = Worker(model, online=True)
    try:
        return worker.call("download", model=model, folder=str(folder))
    finally:
        worker.close()
