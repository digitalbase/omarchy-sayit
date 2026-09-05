"""Exercise GTK key capture without changing live shortcuts."""
import unittest
from types import SimpleNamespace

try:
    from sayit.ui import ShortcutInput, Gdk, Gtk
    HAS_GTK = Gtk.init_check()[0]
except ImportError:
    HAS_GTK = False


@unittest.skipUnless(HAS_GTK, "GTK and a display are required")
class ShortcutInputTests(unittest.TestCase):
    def setUp(self):
        self.field = ShortcutInput()
        self.field.set_text("F10")
        self.field.capture.set_active(True)

    def tearDown(self):
        self.field.destroy()

    def press(self, key, state=0, is_modifier=False):
        return self.field.key_pressed(self.field.capture, SimpleNamespace(
            keyval=key, state=state, is_modifier=is_modifier))

    def test_combination_and_ignored_lock(self):
        self.press(Gdk.KEY_R, Gdk.ModifierType.CONTROL_MASK |
                   Gdk.ModifierType.MOD1_MASK | Gdk.ModifierType.LOCK_MASK)
        self.assertEqual(self.field.get_text(), "CTRL + ALT + R")
        self.assertFalse(self.field.capture.get_active())

    def test_modifier_waits_and_escape_preserves(self):
        self.press(Gdk.KEY_Control_L, is_modifier=True)
        self.assertTrue(self.field.capture.get_active())
        self.press(Gdk.KEY_Escape)
        self.assertEqual(self.field.get_text(), "F10")

    def test_clear_and_modified_delete(self):
        self.press(Gdk.KEY_BackSpace)
        self.assertEqual(self.field.get_text(), "")
        self.field.capture.set_active(True)
        self.press(Gdk.KEY_Delete, Gdk.ModifierType.CONTROL_MASK)
        self.assertEqual(self.field.get_text(), "CTRL + DELETE")

    def test_super_shift_and_unsupported_key(self):
        self.press(Gdk.KEY_exclam)
        self.assertTrue(self.field.capture.get_active())
        self.assertEqual(self.field.get_text(), "F10")
        self.press(Gdk.KEY_F12, Gdk.ModifierType.MOD4_MASK | Gdk.ModifierType.SHIFT_MASK)
        self.assertEqual(self.field.get_text(), "SUPER + SHIFT + F12")

    def test_tab_and_focus_loss_cancel(self):
        self.assertFalse(self.press(Gdk.KEY_Tab))
        self.assertFalse(self.field.capture.get_active())
        self.field.capture.set_active(True)
        self.field.focus_out()
        self.assertFalse(self.field.capture.get_active())
        self.assertEqual(self.field.get_text(), "F10")
