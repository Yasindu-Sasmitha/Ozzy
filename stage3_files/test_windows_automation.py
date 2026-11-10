import unittest

import windows_automation


class FakeInfo:
    def __init__(self, name, control_type="Button", auto_id="", enabled=True, visible=True):
        self.name = name
        self.control_type = control_type
        self.auto_id = auto_id
        self.enabled = enabled
        self.visible = visible


class FakeControl:
    def __init__(self, name, control_type="Button", auto_id="", enabled=True, visible=True):
        self.element_info = FakeInfo(name, control_type, auto_id, enabled, visible)


class FakeWindow:
    def __init__(self, controls):
        self._controls = controls

    def iter_descendants(self):
        return iter(self._controls)


class WindowsAutomationValidationTests(unittest.TestCase):
    def tearDown(self):
        windows_automation.stop_actions()

    def test_actions_are_disabled_by_default(self):
        windows_automation.stop_actions()
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            windows_automation.execute_action("windows_list_windows", {})

    def test_stop_disables_actions_after_resume(self):
        windows_automation.resume_actions()
        windows_automation.stop_actions()
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            windows_automation.execute_action("windows_list_windows", {})

    def test_unknown_action_is_rejected_without_loading_windows_apis(self):
        windows_automation.resume_actions()
        with self.assertRaisesRegex(ValueError, "Unsupported Windows UI Automation action"):
            windows_automation.execute_action("run_powershell", {})

    def test_window_handle_validation(self):
        self.assertEqual(windows_automation.validate_window_handle("1234"), 1234)
        for value in (None, "", "not-a-handle", 0, -1, True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    windows_automation.validate_window_handle(value)

    def test_text_validation(self):
        self.assertEqual(windows_automation.validate_text("Hello Ozzy\nWorld"), "Hello Ozzy\nWorld")
        with self.assertRaises(ValueError):
            windows_automation.validate_text("x" * 3001)
        with self.assertRaises(ValueError):
            windows_automation.validate_text("hello\x00world")
        with self.assertRaises(ValueError):
            windows_automation.validate_text(123)
        with self.assertRaises(PermissionError):
            windows_automation.validate_text("password = hunter2")
        with self.assertRaises(PermissionError):
            windows_automation.validate_text("Credit card 4111 1111 1111 1111")

    def test_sensitive_controls_are_detected(self):
        for metadata in (
            {"name": "Password"},
            {"automation_id": "otpEntry"},
            {"name": "Credit card number"},
            {"control_type": "Edit", "name": "Verification code"},
        ):
            with self.subTest(metadata=metadata):
                self.assertTrue(windows_automation.is_sensitive_control(metadata))
        self.assertFalse(windows_automation.is_sensitive_control({"name": "Search"}))

    def test_high_impact_controls_are_detected(self):
        for name in ("Delete file", "Send message", "Publish", "Purchase", "Shut down", "Approve request"):
            with self.subTest(name=name):
                self.assertTrue(windows_automation.is_high_impact_control({"name": name}))
        self.assertFalse(windows_automation.is_high_impact_control({"name": "Open document"}))
        self.assertFalse(windows_automation.is_high_impact_control({"name": "Save"}))

    def test_sensitive_control_metadata_is_redacted(self):
        control = FakeControl("Password", "Edit", "passwordBox")
        metadata = windows_automation._control_metadata(control)
        self.assertTrue(metadata["sensitive"])
        self.assertEqual(metadata["name"], "[sensitive control hidden]")
        self.assertEqual(metadata["automation_id"], "[hidden]")

    def test_click_type_allowlist_is_bounded(self):
        self.assertIn("Button", windows_automation.CLICKABLE_TYPES)
        self.assertIn("Document", windows_automation.CLICKABLE_TYPES)
        self.assertNotIn("Window", windows_automation.CLICKABLE_TYPES)
        self.assertNotIn("Edit", windows_automation.CLICKABLE_TYPES)

    def test_unique_control_is_matched_by_exact_name_and_type(self):
        expected = FakeControl("Save", "Button", "saveButton")
        window = FakeWindow([FakeControl("Save As", "Button"), expected])
        actual, metadata = windows_automation._find_control(
            window, {"name": "Save", "control_type": "Button"}, {"Button"}
        )
        self.assertIs(actual, expected)
        self.assertEqual(metadata["automation_id"], "saveButton")

    def test_duplicate_controls_are_rejected(self):
        window = FakeWindow([FakeControl("Open"), FakeControl("Open")])
        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            windows_automation._find_control(window, {"name": "Open"}, {"Button"})

    def test_high_impact_and_sensitive_controls_cannot_be_found_for_actions(self):
        with self.assertRaises(PermissionError):
            windows_automation._find_control(
                FakeWindow([FakeControl("Delete file")]), {"name": "Delete file"}, {"Button"}
            )
        with self.assertRaises(PermissionError):
            windows_automation._find_control(
                FakeWindow([FakeControl("Password", "Edit")]), {"name": "Password"}, {"Edit"}
            )


    def test_control_activation_uses_the_matching_uia_pattern(self):
        class ActionControl:
            def __init__(self):
                self.called = []
            def click(self): self.called.append("click")
            def select(self): self.called.append("select")
            def invoke(self): self.called.append("invoke")
            def click_input(self): self.called.append("click_input")

        cases = {
            "Button": "click",
            "MenuItem": "select",
            "TabItem": "select",
            "ListItem": "select",
            "TreeItem": "select",
            "Hyperlink": "invoke",
            "Document": "click_input",
            "Pane": "click_input",
            "SplitButton": "click_input",
        }
        for control_type, expected in cases.items():
            with self.subTest(control_type=control_type):
                control = ActionControl()
                windows_automation._activate_control(control, control_type)
                self.assertEqual(control.called, [expected])

    def test_sensitive_dropdown_options_are_blocked(self):
        original_resolve = windows_automation._resolve_window
        original_find = windows_automation._find_control
        try:
            windows_automation._resolve_window = lambda desktop, handle=None: object()
            windows_automation._find_control = lambda *args, **kwargs: self.fail(
                "A sensitive option must be rejected before resolving the UIA control"
            )
            with self.assertRaises(PermissionError):
                windows_automation._select({"name": "Payment method", "option": "Credit card"}, object())
            with self.assertRaises(PermissionError):
                windows_automation._select({"name": "Account type", "option": "One-time code"}, object())
        finally:
            windows_automation._resolve_window = original_resolve
            windows_automation._find_control = original_find

    def test_disabled_or_hidden_controls_are_not_actionable(self):
        with self.assertRaisesRegex(RuntimeError, "not both visible and enabled"):
            windows_automation._find_control(
                FakeWindow([FakeControl("Save", enabled=False)]), {"name": "Save"}, {"Button"}
            )
        with self.assertRaisesRegex(RuntimeError, "not both visible and enabled"):
            windows_automation._find_control(
                FakeWindow([FakeControl("Save", visible=False)]), {"name": "Save"}, {"Button"}
            )


if __name__ == "__main__":
    unittest.main()
