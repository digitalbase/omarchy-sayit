import collections
import copy
import fcntl
import json
import math
import os
import re
import signal
import socket
import socketserver
import threading
import time
import uuid
import wave
from pathlib import Path
from .catalog import installed, model_by_id, models
from .engines import Worker
from .paths import atomic_json, config_dir, data_dir, private_dir, read_json, runtime_dir
from .player import Player
from .voices import voices

MAX_REQUEST = 1_000_000
DEFAULTS = {"model": "kokoro-bf16", "rate": 1., "pace": 1., "idle_seconds": 600, "device": "auto", "selection_shortcut": "F10", "clipboard_shortcut": ""}


def chunks(text, limit=350):
    """Bound every chunk, including punctuation-free and CJK input."""
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        while paragraph.strip():
            paragraph = paragraph.strip()
            if len(paragraph) <= limit:
                yield paragraph
                break
            part = paragraph[:limit]
            sentences = list(re.finditer(r"[.!?。！？](?:\s+|$)", part))
            boundaries = sentences if sentences and sentences[-1].end() >= limit // 2 else list(re.finditer(r"\s+", part))
            end = boundaries[-1].end() if boundaries else limit
            yield paragraph[:end].strip()
            paragraph = paragraph[end:]


def bounded_number(value, low, high, name):
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def dictation_recording():
    """Read Voxtype's activity flag, never its audio or transcribed text."""
    import tomllib
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    try:
        settings = tomllib.loads((root / "voxtype/config.toml").read_text())
        state_file = settings.get("state_file", "auto")
        if state_file == "disabled":
            return False
        path = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "voxtype/state" if state_file == "auto" else Path(state_file).expanduser()
        return path.read_text().strip() == "recording"
    except (OSError, ValueError):
        return False


class Service:
    def __init__(self, player=None, worker_factory=Worker):
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.closing = False
        self.player = player or Player()
        self.worker_factory = worker_factory
        self.worker = None
        self.loaded = None
        self.last_used = time.monotonic()
        self.settings = DEFAULTS | read_json(config_dir() / "settings.json", {})
        self.jobs = read_json(data_dir() / "history.json", [])
        for job in self.jobs:
            if job["state"] in ("queued", "generating", "playing"):
                job["state"] = "cancelled"
        self.pending = collections.deque()
        self.current = None
        self.paused = False
        self.generation = 0
        self.thread = threading.Thread(target=self.run, daemon=True)

    def save(self):
        atomic_json(data_dir() / "history.json", self.jobs)

    def cancel_current(self):
        self.generation += 1
        if self.current and self.current["state"] not in ("complete", "failed"):
            self.current["state"] = "cancelled"
        self.player.command("stop")
        if self.worker:
            self.worker.close()
            self.worker, self.loaded = None, None
        self.paused = False

    def submit(self, req):
        with self.lock:
            text = req.get("text", "")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Provide text to speak")
            if len(text) > 100_000:
                raise ValueError("Text exceeds the 100,000 character limit")
            model = model_by_id(req.get("model") or self.settings["model"])
            if not model.get("engine"):
                raise ValueError("This catalog entry has not been ported; see docs/parity.md")
            if not installed(model):
                raise ValueError(f"Download the model first: sayit download {model['id']}")
            options = {k: v for k, v in req.items() if k in (
                "voice", "language", "description", "reference", "transcript", "seed") and v is not None}
            profile = req.get("voice_profile")
            if profile:
                matches = [v for v in voices() if profile in (v["id"], v["name"])]
                if len(matches) != 1:
                    raise ValueError("Voice profile not found or name is ambiguous")
                options.update({k: matches[0][k] for k in ("reference", "transcript")})
            if options.get("reference"):
                if not model["capabilities"].get("voiceCloning"):
                    raise ValueError("This model does not support voice cloning")
                from .voices import inspect_sample
                quality = inspect_sample(options["reference"])
                requirements = model["capabilities"].get("voiceCloneRequirements", {})
                if not requirements.get("minimumDuration", 3) <= quality["duration"] <= requirements.get("maximumDuration", 30):
                    raise ValueError("Reference duration is outside this model's supported range")
                if requirements.get("transcriptRequired") and not options.get("transcript"):
                    raise ValueError("This model needs the reference sample's transcript")
            if model["mode"] == "clone" and not (options.get("reference") and options.get("transcript")):
                raise ValueError("Qwen Base needs a saved voice sample with a transcript")
            if options.get("voice") and options["voice"] not in model["voices"]:
                raise ValueError("Choose a voice listed for this model")
            if options.get("description") and not model["capabilities"].get("voiceDescription"):
                raise ValueError("This model does not support voice descriptions")
            if options.get("language") and options["language"] not in model["languages"] and model["engine"] != "omnivoice":
                raise ValueError("Unsupported language for this model")
            options["pace"] = bounded_number(req["pace"] if req.get("pace") is not None else self.settings["pace"], .5, 2, "pace")
            rate = bounded_number(req["rate"] if req.get("rate") is not None else self.settings["rate"], .5, 2, "rate")
            if options["pace"] != 1 and model["engine"] not in ("kokoro", "omnivoice"):
                raise ValueError("Native pace is supported by Kokoro and OmniVoice; use playback rate for this model")
            policy = req.get("policy", "interrupt")
            if policy not in ("enqueue", "interrupt", "replace-all"):
                raise ValueError("Unknown queue policy")
            if policy != "enqueue":
                self.cancel_current()
            if policy == "replace-all":
                for pending in self.pending:
                    pending["state"] = "cancelled"
                self.pending.clear()
            job = {"id": uuid.uuid4().hex, "text": text.strip(), "model": model["id"], "options": options,
                   "rate": rate, "state": "queued", "created": time.time(), "segments": [], "error": None}
            self.jobs.insert(0, job)
            if policy == "interrupt":
                self.pending.appendleft(job)
            else:
                self.pending.append(job)
            self.save()
            self.wake.set()
            return copy.deepcopy(job)

    def snapshot(self):
        with self.lock:
            job = copy.deepcopy(self.current)
            state = job["state"] if job else "idle"
            local_position = self.player.get("time-pos", 0) or 0
            offset = 0
            if job and not job.get("replay"):
                index = self.player.get("playlist-pos", 0) or 0
                if 0 <= index < len(job["segments"]):
                    offset = job["segments"][index]["start"]
                if state == "generating" and not self.player.get("idle-active", True):
                    state = "playing"
            if self.paused and state in ("playing", "generating"):
                state = "paused"
            return {"state": state, "current": job, "queued": len(self.pending), "loadedModel": self.loaded,
                    "position": local_position + offset,
                    "duration": sum(s["duration"] for s in job["segments"]) if job else 0,
                    "rate": self.player.get("speed", self.settings["rate"]),
                    "shortcuts": {"selection": self.settings["selection_shortcut"], "clipboard": self.settings["clipboard_shortcut"]}}

    def dispatch(self, req):
        command = req.get("command")
        if command == "speak":
            return self.submit(req)
        if command == "status":
            return self.snapshot()
        with self.lock:
            if command in ("history", "jobs"):
                return copy.deepcopy(self.jobs)
            if command == "models":
                return [m | {"installed": installed(m)} for m in models()]
            if command == "voices":
                return voices()
            if command == "settings":
                values = req.get("values", {})
                if set(values) - set(DEFAULTS):
                    raise ValueError("Unknown setting")
                updated = self.settings | values
                model_by_id(updated["model"])
                for key, low, high in (("idle_seconds", 0, 86400), ("rate", .5, 2), ("pace", .5, 2)):
                    updated[key] = bounded_number(updated[key], low, high, key)
                if updated["device"] not in ("auto", "cpu", "cuda"):
                    raise ValueError("device must be auto, cpu or cuda")
                from contextlib import nullcontext
                from .shortcuts import FIELDS, normalize, apply
                for key in FIELDS:
                    updated[key] = normalize(updated[key])
                changing_shortcuts = any(key in values for key in FIELDS)
                with apply(updated) if changing_shortcuts else nullcontext():
                    atomic_json(config_dir() / "settings.json", updated)
                self.settings = updated
                return updated
            if command in ("pause", "resume", "toggle"):
                self.paused = (not self.paused) if command == "toggle" else command == "pause"
                self.player.command("set_property", "pause", self.paused)
            elif command in ("stop", "clear"):
                self.cancel_current()
                for job in self.pending:
                    job["state"] = "cancelled"
                self.pending.clear()
                self.save()
            elif command in ("seek", "skip"):
                seconds = bounded_number(req["seconds"], -86400 if command == "skip" else 0, 86400, "seconds")
                target = seconds if command == "seek" else self.snapshot()["position"] + seconds
                if self.current and not self.current.get("replay") and self.current["segments"]:
                    segments = self.current["segments"]
                    target = max(0, min(target, sum(s["duration"] for s in segments) - .01))
                    index = next((i for i, s in enumerate(segments) if s["start"] <= target < s["start"] + s["duration"]), len(segments)-1)
                    if index != self.player.get("playlist-pos", 0):
                        self.player.command("set_property", "playlist-pos", index)
                        for _ in range(50):
                            if self.player.get("path") == segments[index]["path"]:
                                break
                            time.sleep(.01)
                    self.player.command("seek", max(0, target - segments[index]["start"]), "absolute")
                else:
                    self.player.command("seek", max(0, target), "absolute")
            elif command == "rate":
                rate = bounded_number(req["rate"], .5, 2, "rate")
                self.player.command("set_property", "speed", rate)
                if self.current:
                    self.current["rate"] = rate
            elif command == "replay":
                job = next((j for j in self.jobs if j["id"] == req["id"]), None)
                if job is None or not job.get("audio") or not Path(job["audio"]).is_file():
                    raise ValueError("History audio is unavailable")
                self.cancel_current()
                replay = copy.deepcopy(job)
                replay.update(id=uuid.uuid4().hex, created=time.time(), state="queued", replay=True)
                self.jobs.insert(0, replay)
                self.pending.appendleft(replay)
                self.wake.set()
                self.save()
                return copy.deepcopy(replay)
            else:
                raise ValueError(f"Unknown command: {command}")
            return {"ok": True}

    def run(self):
        while not self.closing:
            self.wake.wait(.5)
            self.wake.clear()
            with self.lock:
                if not self.pending:
                    if self.worker and time.monotonic() - self.last_used >= self.settings["idle_seconds"]:
                        self.worker.close()
                        self.worker, self.loaded = None, None
                    continue
                job = self.pending.popleft()
                self.current = job
                generation = self.generation
            try:
                if not job.get("replay"):
                    self.synthesize(job, generation)
                with self.lock:
                    if generation != self.generation or self.closing:
                        continue
                    job["state"] = "playing"
                    if job.get("replay"):
                        self.player.play(job["audio"], job["rate"])
                        self.player.command("set_property", "pause", self.paused)
                # Let mpv process loadfile before checking idle-active.
                time.sleep(.1)
                while not self.closing and generation == self.generation and not self.player.get("idle-active", True):
                    time.sleep(.1)
                with self.lock:
                    if generation == self.generation:
                        job["state"] = "complete"
            except Exception as exc:
                with self.lock:
                    if generation == self.generation:
                        job.update(state="failed", error=str(exc))
            finally:
                with self.lock:
                    self.last_used = time.monotonic()
                    self.save()
                    if self.pending:
                        self.wake.set()

    def synthesize(self, job, generation):
        model = model_by_id(job["model"])
        with self.lock:
            if generation != self.generation:
                return
            job["state"] = "generating"
            if self.loaded != model["id"]:
                if self.worker:
                    self.worker.close()
                self.worker = self.worker_factory(model)
                self.loaded = None
                worker = self.worker
                needs_load = True
            else:
                worker, needs_load = self.worker, False
        if needs_load:
            worker.load(self.settings["device"])
            with self.lock:
                if generation != self.generation:
                    return
                self.loaded = model["id"]
        folder = private_dir(data_dir() / "audio" / job["id"])
        duration = 0
        for index, text in enumerate(chunks(job["text"])):
            with self.lock:
                if generation != self.generation or self.closing:
                    return
            path = folder / f"{index:05}.wav"
            info = worker.call("generate", **(job["options"] | {"text": text, "output": str(path)}))
            # Voxtype only pauses already-playing MPRIS players. If generation
            # finishes after F9 was pressed, wait before starting new audio.
            while dictation_recording() and generation == self.generation and not self.closing:
                time.sleep(.1)
            with self.lock:
                if generation != self.generation or self.closing:
                    return
                job["segments"].append({"text": text, "start": duration, "duration": info["duration"], "path": str(path)})
                if index == 0:
                    self.player.play(path, job["rate"])
                else:
                    self.player.command("loadfile", str(path), "append-play")
                self.player.command("set_property", "pause", self.paused)
            duration += info["duration"]
        output = folder / "speech.wav"
        with wave.open(str(output), "wb") as target:
            for index, segment in enumerate(job["segments"]):
                with wave.open(segment["path"], "rb") as source:
                    if index == 0:
                        target.setparams(source.getparams())
                    elif source.getframerate() != target.getframerate():
                        raise ValueError("Model changed sample rate between chunks")
                    target.writeframes(source.readframes(source.getnframes()))
        with self.lock:
            job.update(audio=str(output), duration=duration)

    def close(self):
        self.closing = True
        with self.lock:
            self.cancel_current()
            self.save()
        self.wake.set()
        self.thread.join(timeout=5)
        self.player.close()


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(5)
        try:
            line = self.rfile.readline(MAX_REQUEST + 1)
            if len(line) > MAX_REQUEST or not line.endswith(b"\n"):
                raise ValueError("Invalid or oversized request")
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("Expected a JSON object")
            response = {"ok": True, "result": self.server.service.dispatch(request)}
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
        self.wfile.write(json.dumps(response, ensure_ascii=False).encode() + b"\n")


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def call(command, **kwargs):
    with socket.socket(socket.AF_UNIX) as conn:
        conn.settimeout(15)
        for attempt in range(10):
            try:
                conn.connect(str(runtime_dir() / "service.sock"))
                break
            except (FileNotFoundError, ConnectionRefusedError) as exc:
                if attempt == 9:
                    raise RuntimeError("SayIt is not running. Run 'sayit daemon' or start sayit.service.") from exc
                time.sleep(.1)
        conn.sendall(json.dumps({"command": command, **kwargs}).encode() + b"\n")
        with conn.makefile("rb") as stream:
            response = json.loads(stream.readline())
        if not response["ok"]:
            raise ValueError(response["error"])
        return response["result"]


def main(http_port=None):
    os.umask(0o077)
    lock = open(runtime_dir() / "service.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError("SayIt is already running")
    path = runtime_dir() / "service.sock"
    path.unlink(missing_ok=True)
    service = Service()
    service.player.start()
    service.thread.start()
    server = Server(str(path), Handler)
    server.service = service
    threading.Thread(target=server.serve_forever, daemon=True).start()
    from .mpris import run
    http = None
    try:
        if http_port is not None:
            from .http_api import start
            http = start(service, http_port)
        run(service)
    finally:
        if http:
            http.shutdown()
            http.server_close()
        server.shutdown()
        server.server_close()
        service.close()
        path.unlink(missing_ok=True)
        lock.close()
