import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import memory_service
import workflow_engine
import workflow_library as library


class WorkflowLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "ozzy_test.sqlite3"
        self.db_patch = patch.object(memory_service, "database_path", return_value=self.db_path)
        self.db_patch.start()
        memory_service.initialize()
        library.initialize()
        self.steps = [
            {"label": "Inspect sample page", "action": "browser_inspect", "args": {}},
        ]

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_save_and_get_template(self):
        result = library.save_template("Check Sample", "Inspect the current page", self.steps)
        self.assertTrue(result["ok"])
        found = library.get_template("check sample")
        self.assertEqual(found["name"], "Check Sample")
        self.assertEqual(found["step_count"], 1)
        self.assertEqual(found["steps"][0]["action"], "browser_inspect")

    def test_duplicate_name_is_rejected_case_insensitively(self):
        library.save_template("Check Sample", "", self.steps)
        with self.assertRaisesRegex(library.WorkflowLibraryError, "already exists"):
            library.save_template("check sample", "", self.steps)

    def test_empty_or_long_names_are_rejected(self):
        for name in ("", "x" * 65):
            with self.subTest(name=name):
                with self.assertRaises(library.WorkflowLibraryError):
                    library.prepare_template(name, "", self.steps)

    def test_invalid_steps_rejected_by_stage5_validator(self):
        with self.assertRaises(workflow_engine.WorkflowValidationError):
            library.prepare_template("Bad", "", [{"action": "delete_file", "args": {}}])

    def test_multistep_mutation_requires_verification(self):
        steps = [
            {"action": "browser_open", "args": {"url": "https://example.com"}},
            {"action": "browser_inspect", "args": {}},
        ]
        with self.assertRaises(workflow_engine.WorkflowValidationError):
            library.prepare_template("Needs Checks", "", steps)

    def test_credentials_rejected_in_description_and_steps(self):
        with self.assertRaises(library.WorkflowLibraryError):
            library.prepare_template("Safe", "api_key=not-a-real-secret", self.steps)
        secret_steps = [{"action": "browser_open", "args": {"url": "https://example.com?token=abc"}}]
        with self.assertRaises(library.WorkflowLibraryError):
            library.prepare_template("Unsafe URL", "", secret_steps)
        camel_case_secret = [{"action": "browser_open", "args": {"url": "https://example.com?apiKey=abc"}}]
        with self.assertRaises(library.WorkflowLibraryError):
            library.prepare_template("Unsafe API URL", "", camel_case_secret)

    def test_list_and_search(self):
        library.save_template("Daily Dashboard", "Inspect a dashboard", self.steps)
        library.save_template("Check Example", "Inspect example content", self.steps)
        self.assertEqual(len(library.list_templates()), 2)
        matches = library.search_templates("dashboard")
        self.assertEqual([item["name"] for item in matches], ["Daily Dashboard"])

    def test_library_has_a_bounded_template_count(self):
        for index in range(library.MAX_TEMPLATES):
            library.save_template(f"Routine {index}", "", self.steps)
        with self.assertRaisesRegex(library.WorkflowLibraryError, "library is full"):
            library.save_template("One Too Many", "", self.steps)

    def test_missing_template_returns_none(self):
        self.assertIsNone(library.get_template("Not saved"))

    def test_mark_used_increments_counter(self):
        item = library.save_template("Counter", "", self.steps)["template"]
        library.mark_template_used(item["id"])
        library.mark_template_used(item["id"])
        found = library.get_template_by_id(item["id"])
        self.assertEqual(found["use_count"], 2)
        self.assertIsNotNone(found["last_used_at"])

    def test_run_history_is_recorded_and_listed(self):
        item = library.save_template("History", "", self.steps)["template"]
        run = library.record_run(item["id"], {
            "status": "completed", "completed_steps": 1, "total_steps": 1,
            "duration_seconds": 0.42, "message": "All steps verified.",
        })
        self.assertEqual(run["status"], "completed")
        history = library.list_runs("History")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["summary"], "completed: 1/1 step(s) verified.")

    def test_invalid_run_status_is_normalized(self):
        item = library.save_template("Status", "", self.steps)["template"]
        run = library.record_run(item["id"], {"status": "surprise", "completed_steps": 0, "total_steps": 1})
        self.assertEqual(run["status"], "failed")

    def test_delete_removes_template_and_run_history(self):
        item = library.save_template("Delete Me", "", self.steps)["template"]
        library.record_run(item["id"], {"status": "completed", "completed_steps": 1, "total_steps": 1})
        result = library.delete_template(item["id"])
        self.assertTrue(result["ok"])
        self.assertIsNone(library.get_template("Delete Me"))
        with self.assertRaises(library.WorkflowLibraryError):
            library.list_runs("Delete Me")

    def test_run_history_is_bounded(self):
        item = library.save_template("Bounded History", "", self.steps)["template"]
        for index in range(35):
            library.record_run(item["id"], {
                "status": "completed", "completed_steps": 1, "total_steps": 1,
                "duration_seconds": 0.1, "message": f"run {index}",
            })
        history = library.list_runs("Bounded History", 50)
        self.assertEqual(len(history), library.MAX_RUNS)
        self.assertGreater(history[0]["id"], history[-1]["id"])
        self.assertEqual(history[0]["summary"], "completed: 1/1 step(s) verified.")

    def test_template_data_survives_reinitialization(self):
        library.save_template("Persistent", "Local SQLite test", self.steps)
        library.initialize()
        self.assertIsNotNone(library.get_template("Persistent"))


if __name__ == "__main__":
    unittest.main()
