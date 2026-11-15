import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import office_automation as office
import workflow_engine as engine


class OfficeValidationTests(unittest.TestCase):
    def test_validates_simple_excel_ranges(self):
        self.assertEqual(office._validate_range_address("a1:c4"), "A1:C4")
        self.assertEqual(office._validate_range_address("B7"), "B7")

    def test_rejects_external_and_named_ranges(self):
        for address in ("Sheet1!A1", "[book.xlsx]Sheet1!A1", "MyNamedRange", "A1:C5, E1"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                office._validate_range_address(address)

    def test_validates_rectangular_values_json(self):
        values = office._validate_values_json('[["Name", "Score"], ["Ada", 98]]')
        self.assertEqual(values, [["Name", "Score"], ["Ada", 98]])

    def test_validates_single_cell_value_matrix(self):
        self.assertEqual(office._validate_values_json('[["only"]]'), [["only"]])

    def test_rejects_ragged_or_oversized_values(self):
        with self.assertRaises(ValueError):
            office._validate_values_json('[["A", "B"], ["C"]]')
        large = json.dumps([[1] * 21 for _ in range(10)])
        with self.assertRaises(ValueError):
            office._validate_values_json(large)

    def test_rejects_formula_like_text_and_secret_patterns(self):
        for value in ('=SUM(A1:A2)', '+cmd|...!', '@HYPERLINK("x")', 'AIza' + 'A' * 30):
            with self.subTest(value=value), self.assertRaises(PermissionError):
                office._validate_values_json(json.dumps([[value]]))

    def test_rejects_non_primitive_excel_values(self):
        with self.assertRaises(ValueError):
            office._validate_values_json('[[{"formula": "=1+1"}]]')

    def test_save_target_is_limited_to_new_supported_profile_file(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            docs = home / "Documents"
            docs.mkdir()
            with mock.patch.object(Path, "home", return_value=home):
                result = office._resolve_new_file_path("word", str(docs / "Report.docx"))
                self.assertEqual(result.name, "Report.docx")
                with self.assertRaises(PermissionError):
                    office._resolve_new_file_path("word", str(home / "AppData" / "Report.docx"))
                with self.assertRaises(ValueError):
                    office._resolve_new_file_path("word", str(docs / "Report.xlsx"))
                (docs / "Existing.docx").write_text("existing")
                with self.assertRaises(FileExistsError):
                    office._resolve_new_file_path("word", str(docs / "Existing.docx"))

    def test_excel_read_values_redact_secrets_and_bound_payload(self):
        values = office._excel_values(
            (("API_KEY=AIza" + "A" * 30, "ordinary"), ("x" * 20_000, 4)),
            2, 2,
        )
        self.assertIn("[REDACTED]", values[0][0])
        self.assertLessEqual(sum(len(v) for row in values for v in row if isinstance(v, str)), 12_000)

    def test_word_inspection_reads_only_bounded_excerpt_and_redacts_secrets(self):
        class FakeRange:
            Text = "safe text\rAPI_KEY=AIza" + "B" * 30

        class FakeParagraphs:
            Count = 3

        class FakeContent:
            End = 20_001

        class FakeDocument:
            Name = "Draft.docx"
            Content = FakeContent()
            Paragraphs = FakeParagraphs()
            def Range(self, start, end):
                self.requested_range = (start, end)
                return FakeRange()
            def ComputeStatistics(self, _kind):
                return 4

        class FakeApp:
            ActiveDocument = FakeDocument()

        result = office._word_inspect({}, FakeApp())
        self.assertEqual(FakeApp.ActiveDocument.requested_range, (14_001, 20_001))
        self.assertIn("[REDACTED]", result["text_excerpt"])
        self.assertEqual(result["character_count"], 20_000)

    def test_save_approval_preview_has_no_side_effect(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            docs = home / "Documents"
            docs.mkdir()
            with mock.patch.object(Path, "home", return_value=home):
                preview = office.prepare_save_request({"application": "excel", "file_path": str(docs / "Data.xlsx")})
            self.assertEqual(preview["application"], "excel")
            self.assertFalse((docs / "Data.xlsx").exists())

    def test_office_inspection_and_edit_actions_are_workflow_allowlisted(self):
        self.assertIn("word_inspect", engine.WORKFLOW_ACTIONS)
        self.assertIn("word_insert_text", engine.WORKFLOW_ACTIONS)
        self.assertIn("excel_inspect_range", engine.VERIFY_ACTIONS)
        self.assertNotIn("office_save_new", engine.WORKFLOW_ACTIONS)

    def test_macro_enabled_or_legacy_documents_are_inspect_only(self):
        class WordDoc:
            SaveFormat = 13
        with self.assertRaises(office.OfficeAutomationError):
            office._require_macro_free_format("word", WordDoc())
        class ExcelBook:
            FileFormat = 52
        with self.assertRaises(office.OfficeAutomationError):
            office._require_macro_free_format("excel", ExcelBook())
        class PowerPointDeck:
            FileFormat = 25
        with self.assertRaises(office.OfficeAutomationError):
            office._require_macro_free_format("powerpoint", PowerPointDeck())

    def test_excel_events_restore_previous_state_even_after_failure(self):
        class ExcelApp:
            EnableEvents = True
        app = ExcelApp()
        with self.assertRaises(RuntimeError):
            with office._excel_events_suppressed(app):
                self.assertFalse(app.EnableEvents)
                raise RuntimeError("simulated Office edit failure")
        self.assertTrue(app.EnableEvents)

    def test_approved_save_is_bound_to_the_same_active_office_item(self):
        class Target:
            Name = "Report.docx"
            FullName = r"C:\Users\Demo\Documents\Report.docx"
        office._check_expected_active_identity(Target(), Target.FullName)
        with self.assertRaises(PermissionError):
            office._check_expected_active_identity(Target(), r"C:\Users\Demo\Documents\Other.docx")

    def test_writable_check_fails_closed_when_read_only_state_cannot_be_checked(self):
        class Uninspectable:
            @property
            def ReadOnly(self):
                raise RuntimeError("COM provider unavailable")
        with self.assertRaises(office.OfficeAutomationError):
            office._writable(Uninspectable(), "Word document")

    def test_office_tool_calls_are_blocked_without_consent(self):
        office.stop_actions()
        try:
            with self.assertRaises(PermissionError):
                office.execute_action("word_inspect", {})
        finally:
            office.stop_actions()


if __name__ == "__main__":
    unittest.main()
