"""mpv controls, with a private IPC socket and no user mpv configuration."""
import json
import socket
import subprocess
import threading
import time
from .paths import runtime_dir


class Player:
    def __init__(self):
        self.path = runtime_dir() / "mpv.sock"
        self.process = None
        self.lock = threading.RLock()

    def start(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                return
            self.path.unlink(missing_ok=True)
            self.process = subprocess.Popen([
                "mpv", "--no-config", "--idle=yes", "--no-video", "--no-terminal",
                "--audio-display=no", "--keep-open=no", f"--input-ipc-server={self.path}",
            ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(100):
                if self.path.exists():
                    return
                if self.process.poll() is not None:
                    break
                time.sleep(.02)
            raise RuntimeError("mpv did not start")

    def command(self, *args):
        with self.lock:
            self.start()
            with socket.socket(socket.AF_UNIX) as conn:
                conn.settimeout(2)
                conn.connect(str(self.path))
                conn.sendall(json.dumps({"command": args, "request_id": 1}).encode() + b"\n")
                stream = conn.makefile("rb")
                while line := stream.readline():
                    reply = json.loads(line)
                    if reply.get("request_id") == 1:
                        if reply.get("error") != "success":
                            raise RuntimeError(reply.get("error", "mpv error"))
                        return reply.get("data")
            raise RuntimeError("mpv disconnected")

    def get(self, name, default=None):
        try:
            return self.command("get_property", name)
        except (OSError, RuntimeError):
            return default

    def play(self, path, rate=1):
        self.command("loadfile", str(path), "replace")
        self.command("set_property", "speed", rate)
        self.command("set_property", "pause", False)

    def close(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.path.unlink(missing_ok=True)

