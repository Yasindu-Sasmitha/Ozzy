import unittest

import computer_control


class ComputerControlValidationTests(unittest.TestCase):
    def test_safe_shortcuts_are_normalized(self):
        self.assertEqual(computer_control.normalize_shortcut(" CTRL + R "), "ctrl+r")
        self.assertEqual(computer_control.normalize_shortcut("F12"), "f12")

    def test_unsafe_shortcuts_are_rejected(self):
        for shortcut in ("ctrl+alt+delete", "win+r", "alt+f4", "ctrl+shift+esc"):
            with self.subTest(shortcut=shortcut):
                with self.assertRaises(ValueError):
                    computer_control.normalize_shortcut(shortcut)

    def test_text_validation_accepts_ascii_and_newlines(self):
        text = "Hello Ozzy\nThis is a test."
        self.assertEqual(computer_control.validate_text(text), text)

    def test_text_validation_rejects_non_ascii(self):
        with self.assertRaises(ValueError):
            computer_control.validate_text("Hello 世界")

    def test_text_validation_rejects_long_input(self):
        with self.assertRaises(ValueError):
            computer_control.validate_text("a" * 4001)

    def test_text_validation_rejects_null_character(self):
        with self.assertRaises(ValueError):
            computer_control.validate_text("hello\x00world")

    def test_coordinate_bounds(self):
        self.assertEqual(computer_control._coordinate(10, "x", 100), 10)
        with self.assertRaises(ValueError):
            computer_control._coordinate(-1, "x", 100)
        with self.assertRaises(ValueError):
            computer_control._coordinate(100, "x", 100)
        with self.assertRaises(ValueError):
            computer_control._coordinate(True, "x", 100)

    def test_stop_latch_blocks_actions_until_resumed(self):
        computer_control.stop_current_action()
        with self.assertRaises(RuntimeError):
            computer_control.execute_action("unknown_action", {})
        computer_control.resume_actions()
        # Unknown actions are rejected by the allow-list without loading OS libraries.
        with self.assertRaises(ValueError):
            computer_control.execute_action("unknown_action", {})


if __name__ == "__main__":
    unittest.main()
