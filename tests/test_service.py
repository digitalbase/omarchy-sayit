import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave
import urllib.request
import urllib.error

from sayit.service import Service, chunks, bounded_number
from sayit.selection import read_selection
from sayit.voices import inspect_sample, transcribe


class FakePlayer:
    def __init__(self):
        self.properties = {"idle-active": True, "pause": False}
        self.played = []

    def command(self, *args):
        if args[0] == "stop":
            self.properties["idle-active"] = True
        if args[0] == "set_property":
            self.properties[args[1]] = args[2]

    def get(self, name, default=None):
        return self.properties.get(name, default)

    def play(self, path, rate):
        self.played.append(path)
        self.properties["idle-active"] = True

    def close(self):
        pass


class FakeWorker:
    def __init__(self, model):
        self.closed = False

    def load(self, device):
        pass

    def call(self, command, **req):
        with wave.open(req["output"], "wb") as wav:
            wav.setparams((1, 2, 24000, 2400, "NONE", "not compressed"))
            wav.writeframes(b"\0\0" * 2400)
        return {"duration": .1, "sampleRate": 24000}

    def close(self):
        self.closed = True


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"XDG_DATA_HOME": self.tmp.name, "XDG_CONFIG_HOME": self.tmp.name,
                                          "XDG_RUNTIME_DIR": self.tmp.name})
        self.env.start()
        self.ready = patch("sayit.service.installed", return_value=True)
        self.ready.start()
        self.player = FakePlayer()
        self.service = Service(self.player, FakeWorker)

    def tearDown(self):
        if self.service.thread.is_alive():
            self.service.close()
        self.ready.stop()
        self.env.stop()
        self.tmp.cleanup()

    def submit(self, **kw):
        return self.service.submit({"text": "Hello world.", **kw})

    def wait_job(self, identifier):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = next(j for j in self.service.jobs if j["id"] == identifier)
            if job["state"] in ("complete", "failed", "cancelled"):
                return job
            time.sleep(.02)
        self.fail("Job timed out")

    def test_queue_policies(self):
        first = self.submit(policy="enqueue")
        second = self.submit(policy="enqueue")
        third = self.submit(policy="interrupt")
        self.assertEqual([j["id"] for j in self.service.pending], [third["id"], first["id"], second["id"]])
        fourth = self.submit(policy="replace-all")
        self.assertEqual([j["id"] for j in self.service.pending], [fourth["id"]])
        self.assertEqual(sum(j["state"] == "cancelled" for j in self.service.jobs), 3)

    def test_invalid_request_does_not_interrupt(self):
        first = self.submit()
        self.service.current = self.service.pending.popleft()
        self.service.current["state"] = "playing"
        with self.assertRaises(ValueError):
            self.submit(rate=math.nan)
        self.assertEqual(self.service.current["state"], "playing")

    def test_synthesis_history_replay(self):
        self.service.thread.start()
        job = self.wait_job(self.submit(text="A paragraph. " * 50)["id"])
        self.assertEqual(job["state"], "complete", job["error"])
        self.assertGreater(len(job["segments"]), 1)
        with wave.open(job["audio"]) as wav:
            self.assertEqual(wav.getnframes(), 2400 * len(job["segments"]))
        replay = self.service.dispatch({"command": "replay", "id": job["id"]})
        self.assertEqual(self.wait_job(replay["id"])["state"], "complete")
        self.assertEqual(len(self.player.played), 2)
        saved = json.loads((Path(self.tmp.name) / "sayit/history.json").read_text())
        self.assertEqual(saved[0]["id"], replay["id"])

    def test_cancel_generation_cannot_play_stale_audio(self):
        started, release = threading.Event(), threading.Event()
        class SlowWorker(FakeWorker):
            def call(self, command, **req):
                started.set()
                release.wait(3)
                return super().call(command, **req)
            def close(self):
                release.set()
        self.service.worker_factory = SlowWorker
        self.service.thread.start()
        job = self.submit()
        self.assertTrue(started.wait(3))
        self.service.dispatch({"command": "stop"})
        self.assertEqual(self.wait_job(job["id"])["state"], "cancelled")
        time.sleep(.15)
        self.assertEqual(self.player.played, [])

    def test_idle_unloads(self):
        self.service.settings["idle_seconds"] = 0
        self.service.thread.start()
        self.wait_job(self.submit()["id"])
        time.sleep(.7)
        self.assertIsNone(self.service.loaded)
        self.assertIsNone(self.service.worker)

    def test_pause_is_preserved_at_playback_start(self):
        self.submit()
        self.service.dispatch({"command": "pause"})
        self.service.thread.start()
        self.wait_job(self.service.jobs[0]["id"])
        self.assertTrue(self.player.properties["pause"])

    def test_generation_waits_for_dictation_to_finish(self):
        with patch("sayit.service.dictation_recording", return_value=True) as recording:
            self.service.thread.start()
            job = self.submit()
            time.sleep(.2)
            self.assertEqual(self.player.played, [])
            recording.return_value = False
            self.assertEqual(self.wait_job(job["id"])["state"], "complete")
            self.assertEqual(len(self.player.played), 1)

    def test_unsupported_model_rejected(self):
        with self.assertRaisesRegex(ValueError, "not been ported"):
            self.submit(model="echo-base")

    def test_clone_requirements(self):
        with self.assertRaisesRegex(ValueError, "sample"):
            self.submit(model="qwen3-06b-base-8bit")

    def test_chunking_bounds_and_content(self):
        for text in ("a" * 1000, "你好。" * 500, "A sentence. " * 500):
            pieces = list(chunks(text))
            self.assertTrue(all(0 < len(p) <= 350 for p in pieces))
            self.assertEqual("".join("".join(pieces).split()), "".join(text.split()))

    def test_numbers(self):
        for value in (float("inf"), float("nan"), -1, 0, 3):
            with self.assertRaises(ValueError):
                bounded_number(value, .5, 2, "rate")

    def test_zero_rate_is_rejected(self):
        with self.assertRaises(ValueError):
            self.submit(rate=0)

    def test_loopback_api_auth_and_validation(self):
        from sayit.http_api import start, token
        server = start(self.service, 0)
        url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(url + "/v1/status")
            self.assertEqual(error.exception.code, 401)
            error.exception.close()
            headers = {"Authorization": "Bearer " + token(), "Content-Type": "application/json"}
            request = urllib.request.Request(url + "/v1/status", headers=headers)
            with urllib.request.urlopen(request) as reply:
                self.assertEqual(json.load(reply)["state"], "idle")
            request = urllib.request.Request(url + "/v1/speech", data=b'{"text":"API speech"}', headers=headers)
            with urllib.request.urlopen(request) as reply:
                self.assertEqual(reply.status, 202)
                self.assertEqual(json.load(reply)["state"], "queued")
            request = urllib.request.Request(url + "/v1/speech", data=b'[]', headers=headers)
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, 400)
            error.exception.close()
        finally:
            server.shutdown()
            server.server_close()

    @patch("sayit.selection.subprocess.run")
    def test_selection_is_explicit(self, run):
        run.return_value.stdout = b"Selected text"
        self.assertEqual(read_selection(), "Selected text")
        self.assertIn("--primary", run.call_args.args[0])
        read_selection(True)
        self.assertNotIn("--primary", run.call_args.args[0])

    @patch("sayit.voices.subprocess.run")
    def test_voxtype_transcript_removes_progress(self, run):
        run.return_value.stdout = "Loading audio file: sample.wav\nProcessing 16000 samples (1.00s)...\n\nHello there.\n"
        self.assertEqual(transcribe("sample.wav"), "Hello there.")
        argv = run.call_args.args[0]
        self.assertIn("local", argv)
        self.assertIn("whisper", argv)

    def test_sample_rejects_silence(self):
        path = Path(self.tmp.name) / "silence.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setparams((1, 2, 24000, 96000, "NONE", "none"))
            wav.writeframes(b"\0\0" * 96000)
        with self.assertRaisesRegex(ValueError, "quiet"):
            inspect_sample(path)


if __name__ == "__main__":
    unittest.main()
