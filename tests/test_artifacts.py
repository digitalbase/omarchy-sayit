import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from sayit.artifacts import download_model, validate_model, verify_model, fingerprint
from sayit.catalog import installed, models
from sayit.worker import Engine, deny_network


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.files = {"config.json": b"{}", "kokoro-v1_0.pth": b"weights", "voices/af_test.pt": b"voice"}
        self.spec = {"engine": "kokoro", "id": "test", "repository": "owner/model",
                     "revision": "a" * 40, "voices": ["af_test"], "defaultVoice": "af_test",
                     "artifacts": {k: hashlib.sha256(v).hexdigest() for k, v in self.files.items()}}

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, url, timeout):
        self.assertIn("/resolve/" + "a" * 40 + "/", url)
        return io.BytesIO(self.files[url.split("/resolve/" + "a" * 40 + "/")[1]])

    def test_download_only_pinned_files_and_verify_existing_cache(self):
        with patch("urllib.request.urlopen", side_effect=self.fetch) as fetch:
            download_model(self.spec, self.folder)
            self.assertEqual(fetch.call_count, 3)
            download_model(self.spec, self.folder)
            self.assertEqual(fetch.call_count, 3)
        self.assertEqual(verify_model(self.spec, self.folder), fingerprint(self.spec))
        (self.folder / "kokoro-v1_0.pth").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "modified"):
            Engine(self.spec, self.folder, "cpu")

    def test_wrong_hash_never_publishes_artifact_or_ready_marker(self):
        with patch("urllib.request.urlopen", return_value=io.BytesIO(b"bad")):
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                download_model(self.spec, self.folder)
        self.assertFalse((self.folder / "config.json").exists())
        self.assertFalse((self.folder / ".sayit-ready").exists())

    def test_mutable_or_missing_pins_and_path_escape_rejected(self):
        for field, value in (("revision", "main"), ("revision", "a" * 7),
                             ("artifacts", {}), ("engine", "qwen")):
            with self.subTest(field=field, value=value):
                spec = self.spec | {field: value}
                with self.assertRaises(ValueError):
                    validate_model(spec)
        for name in ("../outside", "/tmp/file", "voices/../../file", "config.json/../x", "extra.py"):
            spec = copy.deepcopy(self.spec)
            spec["artifacts"][name] = "a" * 64
            with self.assertRaises(ValueError):
                validate_model(spec)

    def test_symlink_rejected(self):
        (self.folder / "config.json").symlink_to("/etc/hosts")
        with self.assertRaises(ValueError):
            verify_model(self.spec, self.folder)

    def test_legacy_ready_marker_not_trusted(self):
        (self.folder / ".sayit-ready").write_text("1\n")
        with patch("sayit.catalog.model_path", return_value=self.folder):
            self.assertFalse(installed(self.spec))

    def test_custom_catalog_cannot_bypass_validation(self):
        custom = self.spec | {"revision": "main"}
        with patch("sayit.catalog.read_json", return_value=[custom]):
            with self.assertRaises(ValueError):
                models()

    def test_no_implicit_download_or_subprocess_in_worker(self):
        for event in ("socket.connect", "socket.getaddrinfo", "subprocess.Popen", "os.system"):
            with self.assertRaises(RuntimeError):
                deny_network(event, ())
        deny_network("open", ())

    def test_all_active_builtin_models_are_pinned(self):
        with patch("sayit.catalog.read_json", return_value=[]):
            for spec in models():
                if spec["engine"]:
                    validate_model(spec)
