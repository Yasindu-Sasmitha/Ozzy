import unittest

import workflow_engine as engine


class WorkflowValidationTests(unittest.TestCase):
    def test_rejects_empty_or_too_many_steps(self):
        with self.assertRaises(engine.WorkflowValidationError):
            engine.validate_steps([])
        with self.assertRaises(engine.WorkflowValidationError):
            engine.validate_steps([{"action": "browser_inspect"}] * 9)

    def test_rejects_unsupported_action(self):
        with self.assertRaises(engine.WorkflowValidationError):
            engine.validate_steps([{"action": "delete_file", "args": {}}])

    def test_multistep_requires_verification_for_each_step(self):
        steps = [
            {"action": "browser_open", "args": {"url": "https://example.com"}},
            {"action": "browser_click", "args": {"by": "role", "role": "button", "value": "Next"}},
        ]
        with self.assertRaisesRegex(engine.WorkflowValidationError, "needs a read-only verification"):
            engine.validate_steps(steps)

    def test_verifier_must_be_read_only(self):
        step = [{"action": "browser_click", "args": {"by": "text", "value": "Continue"},
                 "verify": {"action": "browser_click", "args": {}, "contains": "Done"}}]
        with self.assertRaisesRegex(engine.WorkflowValidationError, "read-only"):
            engine.validate_steps(step)

    def test_verification_requires_exactly_one_matcher(self):
        step = [{"action": "browser_click", "args": {},
                 "verify": {"action": "browser_inspect", "contains": "Done", "equals": "Done"}}]
        with self.assertRaises(engine.WorkflowValidationError):
            engine.validate_steps(step)

    def test_rejects_non_json_workflow_args(self):
        step = [{"action": "browser_inspect", "args": {"bad": object()}}]
        with self.assertRaises(engine.WorkflowValidationError):
            engine.validate_steps(step)


class WorkflowExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_runs_steps_sequentially_and_verifies_each(self):
        calls = []
        progress = []
        async def execute(action, args):
            calls.append((action, args))
            if action == "browser_open":
                return {"ok": True, "url": "https://example.com/dashboard"}
            if action == "browser_inspect":
                return {"ok": True, "title": "Dashboard", "url": "https://example.com/dashboard", "text": "Welcome back"}
            raise AssertionError(action)
        async def report(event):
            progress.append(event)
        steps = [
            {"label": "Open dashboard", "action": "browser_open", "args": {"url": "https://example.com/dashboard"},
             "verify": {"action": "browser_inspect", "args": {}, "field": "url", "contains": "example.com/dashboard"}},
            {"label": "Check page content", "action": "browser_inspect", "args": {},
             "verify": {"action": "browser_inspect", "args": {}, "field": "text", "contains": "Welcome back"}},
        ]
        result = await engine.execute_workflow(steps, execute, is_enabled=lambda: True, on_progress=report, workflow_id="test")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["completed_steps"], 2)
        self.assertEqual(len(calls), 4)
        self.assertEqual(result["steps"][0]["status"], "verified")
        self.assertTrue(any(event["status"] == "verified" for event in progress))

    async def test_stops_when_verification_does_not_match(self):
        calls = []
        async def execute(action, args):
            calls.append(action)
            if action == "browser_click":
                return {"ok": True, "message": "Clicked"}
            if action == "browser_inspect":
                return {"ok": True, "text": "Still on old page"}
            return {"ok": True}
        steps = [
            {"action": "browser_click", "args": {"by": "text", "value": "Next"},
             "verify": {"action": "browser_inspect", "args": {}, "field": "text", "contains": "New page"}},
            {"action": "browser_inspect", "args": {},
             "verify": {"action": "browser_inspect", "args": {}, "field": "text", "contains": "Still on old page"}},
        ]
        result = await engine.execute_workflow(steps, execute, is_enabled=lambda: True)
        self.assertEqual(result["status"], "verification_failed")
        self.assertEqual(calls, ["browser_click", "browser_inspect"])
        self.assertEqual(result["processed_steps"], 1)

    async def test_stops_after_action_failure(self):
        calls = []
        async def execute(action, args):
            calls.append(action)
            return {"ok": False, "message": "Denied"}
        result = await engine.execute_workflow([{"action": "browser_click", "args": {}}], execute, is_enabled=lambda: True)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(calls, ["browser_click"])

    async def test_single_unverified_action_is_reported_honestly(self):
        async def execute(action, args):
            return {"ok": True, "message": "Filled field"}
        result = await engine.execute_workflow([{"action": "windows_click", "args": {"name": "Open"}}], execute, is_enabled=lambda: True)
        self.assertEqual(result["status"], "completed_unverified")
        self.assertFalse(result["ok"])

    async def test_cancels_before_next_step_when_permission_is_revoked(self):
        enabled = True
        calls = []
        async def execute(action, args):
            nonlocal enabled
            calls.append(action)
            enabled = False
            return {"ok": True, "title": "Page"}
        steps = [{"action": "browser_open", "args": {},
                  "verify": {"action": "browser_inspect", "args": {}, "field": "title", "equals": "Page"}},
                 {"action": "browser_inspect", "args": {},
                  "verify": {"action": "browser_inspect", "args": {}, "field": "title", "equals": "Page"}}]
        result = await engine.execute_workflow(steps, execute, is_enabled=lambda: enabled)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(calls, ["browser_open"])


    async def test_verification_timeout_is_reported_as_timeout(self):
        async def execute(action, args):
            if action == "browser_click":
                return {"ok": True, "message": "Clicked"}
            await __import__("asyncio").sleep(0.05)
            return {"ok": True, "text": "done"}
        original_timeout = engine.MAX_ACTION_TIMEOUT_SECONDS
        try:
            engine.MAX_ACTION_TIMEOUT_SECONDS = 0.01
            steps = [{"action": "browser_click", "args": {},
                      "verify": {"action": "browser_inspect", "args": {}, "field": "text", "contains": "done"}}]
            result = await engine.execute_workflow(steps, execute, is_enabled=lambda: True)
            self.assertEqual(result["status"], "timed_out")
        finally:
            engine.MAX_ACTION_TIMEOUT_SECONDS = original_timeout

    async def test_field_equals_matcher(self):
        async def execute(action, args):
            return {"ok": True, "control_state": {"toggle_state": "checked"}}
        steps = [{"action": "windows_get_control_state", "args": {},
                  "verify": {"action": "windows_get_control_state", "args": {}, "field": "control_state.toggle_state", "equals": "checked"}}]
        result = await engine.execute_workflow(steps, execute, is_enabled=lambda: True)
        self.assertEqual(result["status"], "completed")


if __name__ == "__main__":
    unittest.main()
