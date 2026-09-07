import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from sayit.engines import LOCKS, python_for, setup


class EngineLockTests(unittest.TestCase):
    def test_no_unlocked_or_cuda_setup(self):
        with patch('subprocess.run') as run:
            for family in ('qwen', 'chatterbox', 'omnivoice'):
                with self.assertRaises(ValueError):
                    setup(family)
            with self.assertRaises(ValueError):
                setup('kokoro', cuda=True)
            run.assert_not_called()

    def test_setup_consumes_hash_locks_and_fixed_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            python = Path(tmp) / 'engine/bin/python'
            python.parent.mkdir(parents=True)
            with patch('sayit.engines.python_for', return_value=python), \
                 patch('pathlib.Path.is_file', return_value=True), \
                 patch('subprocess.check_output', return_value='uv 0.12.10'), \
                 patch('subprocess.run') as run:
                setup('kokoro')
            calls = [c.args[0] for c in run.call_args_list]
            self.assertEqual(len(calls), 3)
            self.assertIn('--python-downloads-json-url', calls[0])
            self.assertIn((LOCKS / 'python-downloads.json').as_uri(), calls[0])
            self.assertIn('cpython-3.11.16-linux-x86_64-gnu', calls[0])
            for flag in ('--require-hashes', '--only-binary', '--reinstall', '--no-python-downloads'):
                self.assertIn(flag, calls[2])
            self.assertIn(str(LOCKS / 'kokoro-linux-x86_64.txt'), calls[2])
            self.assertTrue((python.parent.parent / '.sayit-lock').exists())

    def test_failed_setup_does_not_mark_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            python = Path(tmp) / 'engine/bin/python'
            python.parent.mkdir(parents=True)
            with patch('sayit.engines.python_for', return_value=python), \
                 patch('pathlib.Path.is_file', return_value=True), \
                 patch('subprocess.check_output', return_value='uv 0.12.10'), \
                 patch('subprocess.run', side_effect=[None, None, RuntimeError('hash mismatch')]):
                with self.assertRaises(RuntimeError):
                    setup('kokoro')
            self.assertFalse((python.parent.parent / '.sayit-lock').exists())

    def test_every_requirement_has_exact_version_or_url_and_hash(self):
        for filename in ('kokoro-linux-x86_64.txt', 'bootstrap.txt', 'build.txt'):
            text = (LOCKS / filename).read_text().replace('\\\n', '')
            for line in text.splitlines():
                if not line.strip() or line.lstrip().startswith('#'):
                    continue
                self.assertRegex(line, r'^[a-zA-Z0-9_-]+(?:==[^ ]+| @ https://[^ ]+)\s+--hash=sha256:[0-9a-f]{64}')
                self.assertNotIn('git+', line)
        metadata = json.loads((LOCKS / 'python-downloads.json').read_text())
        self.assertEqual(len(metadata), 1)
        entry = next(iter(metadata.values()))
        self.assertRegex(entry['sha256'], r'^[0-9a-f]{64}$')
        self.assertIn('/20260901/', entry['url'])
