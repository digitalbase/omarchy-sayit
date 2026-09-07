import json
import os
from pathlib import Path
import subprocess
import threading
from .catalog import model_path
from .paths import data_dir, private_dir

LOCKS = Path(__file__).resolve().parent / "locks"


def lock_identity():
    import hashlib
    return hashlib.sha256(b"".join((LOCKS / name).read_bytes() for name in
        ("kokoro-linux-x86_64.txt", "python-downloads.json", "bootstrap.txt"))).hexdigest()


def python_for(family):
    if family != "kokoro":
        raise ValueError("This engine is disabled until its runtime sources are locked")
    return data_dir() / "engines" / ("kokoro-" + lock_identity()[:16]) / "bin/python"


def setup(family, cuda=False):
    import platform
    if cuda or platform.system() != "Linux" or platform.machine() != "x86_64":
        raise ValueError("The reviewed lock currently supports Linux x86_64 CPU only")
    python = python_for(family)
    uv = LOCKS.parent.parent / ".tools/bin/uv"
    if not uv.is_file():
        raise ValueError("Run scripts/bootstrap.sh to install the hash-verified uv tool")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("UV_", "PIP_", "PYTHON"))}
    def run(args):
        subprocess.run([str(uv), "--no-config", "--no-cache", *args], check=True, env=env)
    version = subprocess.check_output([str(uv), "--version"], text=True).split()[1]
    if version != "0.12.10":
        raise ValueError("Run scripts/bootstrap.sh; setup requires uv 0.12.10")
    runtime = data_dir() / "runtimes" / lock_identity()[:16]
    run(["python", "install", "cpython-3.11.16-linux-x86_64-gnu",
         "--install-dir", str(runtime), "--no-bin", "--reinstall",
         "--python-downloads-json-url", (LOCKS / "python-downloads.json").as_uri()])
    interpreter = runtime / "cpython-3.11.16-linux-x86_64-gnu/bin/python3.11"
    ready = python.parent.parent / ".sayit-lock"
    ready.unlink(missing_ok=True)
    run(["venv", "--python", str(interpreter), "--no-python-downloads", "--allow-existing",
         str(python.parent.parent)])
    run(["pip", "sync", "--python", str(python), "--no-python-downloads",
         "--require-hashes", "--only-binary", ":all:", "--reinstall",
         "--index-url", "https://pypi.org/simple", str(LOCKS / "kokoro-linux-x86_64.txt")])
    ready.write_text(lock_identity() + "\n")


class Worker:
    def __init__(self, model):
        from .artifacts import validate_model
        validate_model(model)
        self.model = model
        self.lock = threading.Lock()
        python = python_for(model["engine"])
        if not python.exists() or not (python.parent.parent / ".sayit-lock").exists() or (python.parent.parent / ".sayit-lock").read_text().strip() != lock_identity():
            raise ValueError(f"Run: sayit setup {model['engine']}")
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        env["PYTHONPATH"] = str(LOCKS.parent.parent)
        env["PYTHONNOUSERSITE"] = "1"
        env.update(HF_HOME=str(private_dir(data_dir() / "huggingface")), HF_HUB_DISABLE_TELEMETRY="1",
                   HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        log = open(data_dir() / "engine.log", "a")
        try:
            self.process = subprocess.Popen([str(python), "-u", "-m", "sayit.worker"],
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
    from .artifacts import download_model
    return download_model(model, model_path(model))
