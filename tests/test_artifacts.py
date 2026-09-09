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
        return self.response(self.files[url.split("/resolve/" + "a" * 40 + "/")[1]])

    def response(self, data, length=None):
        source = io.BytesIO(data)
        source.headers = {} if length is None else {"Content-Length": length}
        return source

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
        with patch("urllib.request.urlopen", return_value=self.response(b"bad")):
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                download_model(self.spec, self.folder)
        self.assertFalse((self.folder / "config.json").exists())
        self.assertFalse((self.folder / ".sayit-ready").exists())
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_oversized_header_rejected_before_reading(self):
        source = self.response(b"{}", "5")
        with patch("sayit.artifacts.CONFIG_MAX_BYTES", 4), \
                patch("urllib.request.urlopen", return_value=source), \
                patch.object(source, "read", wraps=source.read) as read:
            with self.assertRaisesRegex(ValueError, "oversized Content-Length"):
                download_model(self.spec, self.folder)
            read.assert_not_called()
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_oversized_stream_rejected_regardless_of_header(self):
        for length in (None, "0", "2", "4"):
            with self.subTest(length=length):
                source = self.response(b"x" * 100, length)
                (self.folder / ".sayit-ready").write_text("stale")
                with patch("sayit.artifacts.CONFIG_MAX_BYTES", 4), \
                        patch("urllib.request.urlopen", return_value=source), \
                        patch.object(source, "read", wraps=source.read) as read:
                    with self.assertRaisesRegex(ValueError, "byte limit"):
                        download_model(self.spec, self.folder)
                    read.assert_called_once_with(5)
                self.assertEqual(list(self.folder.iterdir()), [])

    def test_exact_limit_is_accepted(self):
        for length in (None, "2"):
            with self.subTest(length=length):
                with tempfile.TemporaryDirectory() as folder, \
                        patch("sayit.artifacts.CONFIG_MAX_BYTES", 2), \
                        patch("urllib.request.urlopen", side_effect=lambda url, timeout:
                              self.response(self.files[url.split("/resolve/" + "a" * 40 + "/")[1]], length)):
                    download_model(self.spec, folder)
                    self.assertEqual(verify_model(self.spec, folder), fingerprint(self.spec))

    def test_limit_counts_all_chunks_before_writing_overflow(self):
        source = self.response(b"")
        with patch("sayit.artifacts.CONFIG_MAX_BYTES", 4), \
                patch("urllib.request.urlopen", return_value=source), \
                patch.object(source, "read", side_effect=[b"xx", b"xx", b"x"]) as read:
            with self.assertRaisesRegex(ValueError, "byte limit"):
                download_model(self.spec, self.folder)
            self.assertEqual([call.args[0] for call in read.call_args_list], [5, 3, 1])
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_weights_and_voices_have_enforced_limits(self):
        for constant, name in (("WEIGHTS_MAX_BYTES", "kokoro-v1_0.pth"),
                               ("VOICE_MAX_BYTES", "voices/af_test.pt")):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder, \
                    patch("sayit.artifacts." + constant, 4), \
                    patch("urllib.request.urlopen", side_effect=self.fetch):
                with self.assertRaisesRegex(ValueError, "byte limit.*" + name):
                    download_model(self.spec, folder)
                self.assertFalse((Path(folder) / name).exists())
                self.assertFalse((Path(folder) / ".sayit-ready").exists())
                self.assertTrue(all(str(path.relative_to(folder)) in self.files
                                    for path in Path(folder).rglob("*") if path.is_file()))

    def test_stream_failure_removes_partial_and_preserves_existing_target(self):
        target = self.folder / "config.json"
        target.write_bytes(b"old")
        source = self.response(b"")
        with patch("urllib.request.urlopen", return_value=source), \
                patch.object(source, "read", side_effect=[b"{", OSError("connection lost")]):
            with self.assertRaisesRegex(OSError, "connection lost"):
                download_model(self.spec, self.folder)
        self.assertEqual(target.read_bytes(), b"old")
        self.assertEqual(list(self.folder.iterdir()), [target])

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
