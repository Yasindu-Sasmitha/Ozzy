import unittest
from unittest.mock import patch

import windows_automation
import windows_workflows


class FakeInfo:
    def __init__(self, name="Test", control_type="Button", auto_id="testControl", enabled=True, visible=True):
        self.name = name
        self.control_type = control_type
        self.auto_id = auto_id
        self.enabled = enabled
        self.visible = visible


class FakeWindow:
    def __init__(self, title="Save As", handle=4321, visible=True):
        self._title = title
        self.handle = handle
        self._visible = visible
        self.element_info = type("Info", (), {"name": title})()

    def is_visible(self):
        return self._visible

    def window_text(self):
        return self._title


class WindowsWorkflowTests(unittest.TestCase):
    def setUp(self):
        windows_automation.resume_actions()

    def tearDown(self):
        windows_automation.stop_actions()

    def test_timeout_validation(self):
        self.assertEqual(windows_workflows._validate_timeout(None), 5)
        self.assertEqual(windows_workflows._validate_timeout(15), 15)
        for value in (True, False, 0, -1, 16, 1.5, "5"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    windows_workflows._validate_timeout(value)

    def test_title_validation(self):
        self.assertEqual(windows_workflows._validate_title(" Save As "), "Save As")
        for value in (None, "", " " , "x" * 181):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    windows_workflows._validate_title(value)

    def test_exact_and_contains_title_matching_are_case_insensitive(self):
        self.assertTrue(windows_workflows._window_matches("Save As", "save as", "exact"))
        self.assertFalse(windows_workflows._window_matches("Save As - Notepad", "Save As", "exact"))
        self.assertTrue(windows_workflows._window_matches("Save As - Notepad", "save as", "contains"))
        with self.assertRaises(ValueError):
            windows_workflows._window_matches("Save As", "Save", "regex")

    def test_find_window_ignores_hidden_windows(self):
        desktop = type("Desktop", (), {"windows": lambda self: [
            FakeWindow("Save As", 1, visible=False), FakeWindow("Save As", 2, visible=True)
        ]})()
        result = windows_workflows._find_window(desktop, "Save As", "exact")
        self.assertEqual(result.handle, 2)

    def test_find_window_rejects_ambiguous_matches(self):
        desktop = type("Desktop", (), {"windows": lambda self: [FakeWindow("Save As", 1), FakeWindow("Save As - Copy", 2)]})()
        with self.assertRaisesRegex(RuntimeError, "More than one visible window"):
            windows_workflows._find_window(desktop, "Save As", "contains")

    def test_wait_for_window_returns_matching_handle(self):
        expected = FakeWindow("Save As", 7788)
        desktop = type("Desktop", (), {"windows": lambda self: [expected]})()
        result = windows_workflows._wait_for_window({"title": "Save As", "timeout_seconds": 2}, desktop)
        self.assertTrue(result["ok"])
        self.assertEqual(result["window_handle"], "7788")
        self.assertEqual(result["window_title"], "Save As")

    def test_wait_for_window_times_out(self):
        desktop = type("Desktop", (), {"windows": lambda self: []})()
        with patch.object(windows_workflows.time, "monotonic", side_effect=[0.0, 2.0]), patch.object(windows_workflows.time, "sleep"):
            with self.assertRaisesRegex(TimeoutError, "within 1 seconds"):
                windows_workflows._wait_for_window({"title": "Save As", "timeout_seconds": 1}, desktop)

    def test_wait_for_window_checks_cancel_state_during_polling(self):
        desktop = type("Desktop", (), {"windows": lambda self: []})()
        with patch.object(windows_automation, "_check_enabled", side_effect=[None, RuntimeError("disabled by Stop Now")]), patch.object(windows_workflows.time, "monotonic", return_value=0.0), patch.object(windows_workflows.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "disabled by Stop Now"):
                windows_workflows._wait_for_window({"title": "Save As", "timeout_seconds": 5}, desktop)

    def test_wait_for_control_retries_until_control_is_ready(self):
        fake_window = FakeWindow("Save As", 200)
        fake_control = object()
        meta = {"name": "File name", "automation_id": "FileNameControl", "control_type": "Edit", "enabled": True, "visible": True}
        with patch.object(windows_automation, "_resolve_window", return_value=fake_window), patch.object(
            windows_automation, "_find_control", side_effect=[RuntimeError("No matching visible control was found."), (fake_control, meta)]
        ) as find, patch.object(windows_workflows.time, "monotonic", side_effect=[0.0, 0.0, 0.1]), patch.object(windows_workflows.time, "sleep"):
            result = windows_workflows._wait_for_control({"name": "File name", "window_handle": "200", "timeout_seconds": 5}, object())
        self.assertTrue(result["ok"])
        self.assertEqual(result["control"]["automation_id"], "FileNameControl")
        self.assertEqual(find.call_count, 2)

    def test_wait_for_control_does_not_suppress_ambiguous_matches(self):
        with patch.object(windows_automation, "_resolve_window", return_value=FakeWindow()), patch.object(
            windows_automation, "_find_control", side_effect=RuntimeError("The control match is ambiguous")
        ), patch.object(windows_workflows.time, "monotonic", return_value=0.0):
            with self.assertRaisesRegex(RuntimeError, "ambiguous"):
                windows_workflows._wait_for_control({"name": "Open", "timeout_seconds": 5}, object())

    def test_wait_for_control_requires_identifier(self):
        with patch.object(windows_automation, "_resolve_window", return_value=FakeWindow()):
            with self.assertRaisesRegex(ValueError, "control name or automation_id"):
                windows_workflows._wait_for_control({"timeout_seconds": 1}, object())

    def test_get_checkbox_state_reads_toggle_state_only(self):
        class Checkbox:
            def get_toggle_state(self): return 1
            has_keyboard_focus = True
        checkbox = Checkbox()
        metadata = {"name": "Word Wrap", "automation_id": "wordWrap", "control_type": "CheckBox", "enabled": True, "visible": True}
        with patch.object(windows_automation, "_resolve_window", return_value=FakeWindow()), patch.object(
            windows_automation, "_find_control", return_value=(checkbox, metadata)
        ):
            result = windows_workflows._get_control_state({"name": "Word Wrap"}, object())
        self.assertEqual(result["control_state"]["toggle_state"], "checked")
        self.assertTrue(result["control_state"]["has_keyboard_focus"])
        self.assertNotIn("value", result["control_state"])

    def test_get_edit_state_does_not_read_or_return_field_text(self):
        class EditControl:
            has_keyboard_focus = False
            def window_text(self):
                raise AssertionError("Edit field text must never be read")
            def get_value(self):
                raise AssertionError("Edit field value must never be read")
        metadata = {"name": "File name", "automation_id": "FileNameControl", "control_type": "Edit", "enabled": True, "visible": True}
        with patch.object(windows_automation, "_resolve_window", return_value=FakeWindow()), patch.object(
            windows_automation, "_find_control", return_value=(EditControl(), metadata)
        ):
            result = windows_workflows._get_control_state({"name": "File name", "control_type": "Edit"}, object())
        self.assertEqual(result["control_state"]["control_type"], "Edit")
        self.assertNotIn("value", result["control_state"])
        self.assertNotIn("text", result["control_state"])

    def test_get_radio_state_reports_selected_status(self):
        class Radio:
            def is_selected(self): return True
        metadata = {"name": "Portrait", "automation_id": "portrait", "control_type": "RadioButton", "enabled": True, "visible": True}
        with patch.object(windows_automation, "_resolve_window", return_value=FakeWindow()), patch.object(
            windows_automation, "_find_control", return_value=(Radio(), metadata)
        ):
            result = windows_workflows._get_control_state({"name": "Portrait"}, object())
        self.assertTrue(result["control_state"]["selected"])

    def test_get_state_allows_edit_metadata_without_reading_values(self):
        self.assertIn("Edit", windows_workflows.STATE_CONTROL_TYPES)
        self.assertIn("CheckBox", windows_workflows.STATE_CONTROL_TYPES)

    def test_dispatch_rejects_unknown_actions(self):
        with self.assertRaisesRegex(ValueError, "Unsupported Windows workflow action"):
            windows_workflows.execute_action("run_command", {})

    def test_dispatch_uses_existing_consent_and_desktop_lifecycle(self):
        fake_desktop = object()
        with patch.object(windows_automation, "_run_with_desktop", side_effect=lambda callback: callback(fake_desktop)), patch.object(
            windows_workflows, "_wait_for_window", return_value={"ok": True}
        ) as action:
            result = windows_workflows.execute_action("windows_wait_for_window", {"title": "Save As"})
        self.assertTrue(result["ok"])
        action.assert_called_once_with({"title": "Save As"}, fake_desktop)

    def test_dispatch_requires_pc_control_consent(self):
        windows_automation.stop_actions()
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            windows_workflows.execute_action("windows_wait_for_window", {"title": "Save As"})


if __name__ == "__main__":
    unittest.main()
