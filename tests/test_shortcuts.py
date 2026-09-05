import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from sayit.shortcuts import apply, check_conflicts, normalize, render


class ShortcutTests(unittest.TestCase):
    def test_normalize_and_reject_injection(self):
        self.assertEqual(normalize(' shift+ctrl+f10 '), 'CTRL + SHIFT + F10')
        self.assertEqual(normalize(''), '')
        for value in ('F10"', 'F10\nquit()', 'CTRL + CTRL + R', 'MYSTERY + X', 'CTRL + ', 'F1000', 'NOT_A_KEY'):
            with self.assertRaises(ValueError): normalize(value)

    def test_migration_preserves_other_bindings(self):
        original = ('-- user note\no.bind("F9", "Dictate", "voxtype record start")\n'
                    'o.bind("F10", "Read selected text", "sayit selection --detach")\n'
                    'o.bind("SHIFT + F10", "Read clipboard", "sayit clipboard --detach")\n')
        result = render(original, 'F10', '')
        self.assertIn('voxtype record start', result)
        self.assertIn('-- user note', result)
        self.assertNotIn('SHIFT + F10', result)
        self.assertEqual(result.count('sayit selection --detach'), 1)
        self.assertEqual(render(result, 'F10', ''), result)
        changed = render(result, 'CTRL + F11', 'F12')
        self.assertNotIn('F10', changed)
        self.assertIn('sayit clipboard --detach', changed)

    def test_conflicts_do_not_replace_other_actions(self):
        with self.assertRaisesRegex(ValueError, 'Dictation'):
            check_conflicts([{'key': 'F9', 'modmask': 0, 'description': 'Dictation'}], '', 'F9', '')
        with self.assertRaisesRegex(ValueError, 'different'):
            check_conflicts([], '', 'F10', 'F10')
        original = 'o.bind("F10", "Read selected text", "sayit selection --detach")\n'
        check_conflicts([{'key': 'F10', 'modmask': 0, 'description': 'Read selected text'}], original, 'F10', '')

    def run_apply(self, fail_validation=False, fail_save=False):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, XDG_CONFIG_HOME=folder):
            path = Path(folder) / 'hypr/bindings.lua'
            path.parent.mkdir()
            path.write_text('-- unrelated binding\n')
            calls = []
            def run(argv, **kwargs):
                calls.append(argv)
                if argv[-1] == 'binds': return SimpleNamespace(stdout='[]')
                if fail_validation and len(calls) == 4: return SimpleNamespace(stdout='Invalid key')
                return SimpleNamespace(stdout='')
            with patch('sayit.shortcuts.subprocess.run', side_effect=run):
                if fail_save or fail_validation:
                    with self.assertRaises((ValueError, OSError)):
                        with apply({'selection_shortcut': 'F10', 'clipboard_shortcut': ''}):
                            if fail_save: raise OSError('settings disk failure')
                    self.assertEqual(path.read_text(), '-- unrelated binding\n')
                    self.assertEqual(calls[-2:], [['hyprctl', 'reload'], ['hyprctl', 'configerrors']])
                else:
                    with apply({'selection_shortcut': 'F10', 'clipboard_shortcut': ''}): pass
                    self.assertIn('sayit selection --detach', path.read_text())
                self.assertEqual(len(list(path.parent.glob('*.bak-sayit-*'))), 1)

    def test_apply_backs_up_and_validates(self): self.run_apply()
    def test_validation_failure_rolls_back(self): self.run_apply(fail_validation=True)
    def test_settings_failure_rolls_back(self): self.run_apply(fail_save=True)
