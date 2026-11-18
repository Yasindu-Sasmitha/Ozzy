import ntpath
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import office_automation as office
import office_documents as docs

ZIP = b"PK\x03\x04" + b"\x00" * 64
OLE = bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 64  # password-protected / legacy Office container


class Node:
    def __init__(self, **values):
        self.__dict__.update(values)


class OpenFileTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name).resolve()
        for folder in ("Desktop", "Documents", "Downloads", "Pictures"):
            (self.home / folder).mkdir()
        patcher = mock.patch.object(Path, "home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make(self, relative, data=ZIP):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path


class ResolveExistingFileTests(OpenFileTestCase):
    def test_accepts_absolute_and_alias_paths(self):
        report = self.make("Documents/Report.docx")
        for raw in (str(report), "Documents/Report.docx", "documents\\Report.docx"):
            with self.subTest(raw=raw):
                app_key, resolved = docs.resolve_existing_file(raw)
                self.assertEqual((app_key, resolved), ("word", report))
        self.assertEqual(docs.resolve_existing_file(str(self.make("Desktop/Budget.xlsx")))[0], "excel")
        self.assertEqual(docs.resolve_existing_file(str(self.make("Downloads/Deck.PPTX")))[0], "powerpoint")

    def test_onedrive_folders_are_allowed(self):
        path = self.make("OneDrive - Personal/Notes/Plan.docx")
        self.assertEqual(docs.resolve_existing_file(str(path))[1], path)
        self.assertEqual(docs.resolve_existing_file("OneDrive - Personal/Notes/Plan.docx")[1], path)

    def test_rejects_unsupported_extensions(self):
        for name in ("Macro.docm", "Old.doc", "Sheet.xls", "Data.csv", "Deck.ppt", "Template.dotx", "x.exe", "noext"):
            path = self.make(f"Documents/{name}")
            with self.subTest(name=name), self.assertRaises(ValueError):
                docs.resolve_existing_file(str(path))

    def test_rejects_missing_files_and_bad_input(self):
        with self.assertRaises(FileNotFoundError):
            docs.resolve_existing_file("Documents/Nope.docx")
        for raw in ("", "   ", None, 7, "Report.docx", "x" * 600):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                docs.resolve_existing_file(raw)

    def test_rejects_locations_outside_the_allowed_folders(self):
        outside = self.make("Pictures/Photo.docx")
        with self.assertRaises(PermissionError):
            docs.resolve_existing_file(str(outside))
        with self.assertRaises(PermissionError):
            docs.resolve_existing_file(str(self.make("Documents.docx")))  # directly in the profile root
        with tempfile.TemporaryDirectory() as other:
            stray = Path(other) / "Documents" / "Stray.docx"
            stray.parent.mkdir()
            stray.write_bytes(ZIP)
            with self.assertRaises(PermissionError):
                docs.resolve_existing_file(str(stray))

    def test_rejects_traversal_hidden_temp_forbidden_and_sensitive_names(self):
        self.make("Documents/Real.docx")
        with self.assertRaises(ValueError):
            docs.resolve_existing_file("Documents/../Documents/Real.docx")
        for relative in ("Documents/.hidden.docx", "Documents/~$Lock.docx", "Documents/password list.docx",
                         "Documents/bank statement 2026.xlsx", "Documents/.git/Notes.docx",
                         "Documents/AppData/Notes.docx"):
            path = self.make(relative)
            with self.subTest(relative=relative), self.assertRaises(PermissionError):
                docs.resolve_existing_file(str(path))

    def test_rejects_symlinks(self):
        target = self.make("Pictures/Real.docx")
        link = self.home / "Documents" / "Link.docx"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaises(PermissionError):
            docs.resolve_existing_file(str(link))
        linked_dir = self.home / "Documents" / "LinkedDir"
        os.symlink(self.home / "Pictures", linked_dir)
        with self.assertRaises(PermissionError):
            docs.resolve_existing_file(str(linked_dir / "Real.docx"))

    def test_rejects_empty_oversized_and_non_zip_files(self):
        with self.assertRaises(ValueError):
            docs.resolve_existing_file(str(self.make("Documents/Empty.docx", b"")))
        with self.assertRaises(ValueError) as caught:
            docs.resolve_existing_file(str(self.make("Documents/Locked.docx", OLE)))
        self.assertIn("password", str(caught.exception))
        with self.assertRaises(ValueError):
            docs.resolve_existing_file(str(self.make("Documents/Fake.xlsx", b"not a zip at all")))
        big = self.make("Documents/Big.docx")
        with mock.patch.object(docs, "MAX_OPEN_BYTES", 10), self.assertRaises(ValueError):
            docs.resolve_existing_file(str(big))


class PrepareOpenRequestTests(OpenFileTestCase):
    def test_describes_the_file_for_approval(self):
        path = self.make("Documents/Report.docx")
        preview = docs.prepare_open_request({"file_path": "Documents/Report.docx"})
        self.assertEqual((preview["application"], preview["file_name"], preview["file_path"]), ("word", "Report.docx", str(path)))
        self.assertEqual(preview["size_bytes"], path.stat().st_size)
        self.assertEqual(preview["modified_ns"], str(path.stat().st_mtime_ns))
        self.assertFalse(preview["read_only"])
        self.assertFalse(preview["internet_download"])

    def test_read_only_flag_and_application_hint(self):
        self.make("Documents/Report.docx")
        self.assertTrue(docs.prepare_open_request({"file_path": "Documents/Report.docx", "read_only": True})["read_only"])
        self.assertEqual(docs.prepare_open_request({"file_path": "Documents/Report.docx", "application": "Word"})["application"], "word")
        with self.assertRaises(ValueError):
            docs.prepare_open_request({"file_path": "Documents/Report.docx", "application": "excel"})
        with self.assertRaises(ValueError):
            docs.prepare_open_request({"file_path": "Documents/Report.docx", "read_only": "yes"})

    def test_internet_downloads_are_forced_read_only(self):
        self.make("Downloads/Report.docx")
        with mock.patch.object(docs, "is_internet_file", return_value=True):
            preview = docs.prepare_open_request({"file_path": "Downloads/Report.docx", "read_only": False})
        self.assertTrue(preview["internet_download"])
        self.assertTrue(preview["read_only"])

    def test_is_internet_file_is_false_without_a_zone_marker(self):
        self.assertFalse(docs.is_internet_file(self.make("Documents/Plain.docx")))


# --------------------------------------------------------------------------- fake Office applications

class RecordingApp:
    """Records property writes to AutomationSecurity / DisplayAlerts and holds document collections."""

    def __init__(self, kind, *, fail_security=False):
        object.__setattr__(self, "log", [])
        object.__setattr__(self, "fail_security", fail_security)
        object.__setattr__(self, "AutomationSecurity", 2)  # msoAutomationSecurityByUI
        object.__setattr__(self, "DisplayAlerts", {"word": -1, "excel": True, "powerpoint": 2}[kind])
        object.__setattr__(self, "Visible", False)
        self.kind = kind
        self.items = []
        self.open_calls = []
        collection = Collection(self)
        setattr(self, {"word": "Documents", "excel": "Workbooks", "powerpoint": "Presentations"}[kind], collection)

    def __setattr__(self, name, value):
        if name == "AutomationSecurity" and self.fail_security:
            raise Exception("denied")
        if name in ("AutomationSecurity", "DisplayAlerts"):
            self.log.append((name, value))
        object.__setattr__(self, name, value)


class FakeItem:
    def __init__(self, full_name, read_only=False, with_window=False):
        self.FullName = full_name
        self.Name = ntpath.basename(full_name)  # Office reports Windows-style names
        self.ReadOnly = read_only
        self.activated = False
        self.Windows = Node(Item=lambda index: Node(Activate=self._activate))

    def _activate(self):
        self.activated = True

    def Activate(self):
        self.activated = True


class Collection:
    def __init__(self, app):
        self.app = app

    @property
    def Count(self):
        return len(self.app.items)

    def Item(self, index):
        return self.app.items[index - 1]

    def Open(self, *args):
        self.app.open_calls.append(args)
        read_only = {"word": args[2], "excel": args[2], "powerpoint": args[1] == -1}[self.app.kind]
        item = FakeItem(args[0], read_only=bool(read_only))
        self.app.items.append(item)
        return item


class OpenDocumentTests(OpenFileTestCase):
    def run_open(self, app, args, **extra):
        def fake_with_app(app_key, callback, allow_launch=False):
            self.assertEqual(app_key, app.kind)
            self.assertTrue(allow_launch)  # only the approved open action may start Office
            return callback(app)
        with mock.patch.object(office, "_with_app", side_effect=fake_with_app):
            return docs.execute("office_open_document", {**args, **extra})

    def test_word_opens_with_macros_disabled_and_settings_restored(self):
        path = self.make("Documents/Report.docx")
        app = RecordingApp("word")
        result = self.run_open(app, {"file_path": "Documents/Report.docx"})
        self.assertEqual(app.open_calls, [(str(path), False, False, False)])
        self.assertEqual(app.log, [("AutomationSecurity", 3), ("DisplayAlerts", 0),
                                   ("DisplayAlerts", -1), ("AutomationSecurity", 2)])
        self.assertTrue(app.Visible)
        self.assertEqual((result["ok"], result["document_name"], result["already_open"], result["read_only"]),
                         (True, "Report.docx", False, False))
        self.assertIn("macros disabled", result["message"])

    def test_excel_and_powerpoint_open_arguments(self):
        path = self.make("Documents/Budget.xlsx")
        app = RecordingApp("excel")
        self.run_open(app, {"file_path": "Documents/Budget.xlsx", "read_only": True})
        self.assertEqual(app.open_calls, [(str(path), 0, True)])  # UpdateLinks=0 (never), ReadOnly
        self.assertEqual(app.log[1], ("DisplayAlerts", False))
        deck = self.make("Documents/Deck.pptx")
        app = RecordingApp("powerpoint")
        result = self.run_open(app, {"file_path": "Documents/Deck.pptx", "read_only": True})
        self.assertEqual(app.open_calls, [(str(deck), -1, 0, -1)])
        self.assertTrue(result["read_only"])
        app = RecordingApp("powerpoint")
        self.run_open(app, {"file_path": "Documents/Deck.pptx"})
        self.assertEqual(app.open_calls, [(str(deck), 0, 0, -1)])
        self.assertEqual(app.log[1], ("DisplayAlerts", 1))  # ppAlertsNone

    def test_already_open_documents_are_activated_not_reopened(self):
        path = self.make("Documents/Report.docx")
        app = RecordingApp("word")
        existing = FakeItem(str(path))
        app.items.append(existing)
        result = self.run_open(app, {"file_path": "Documents/Report.docx"})
        self.assertTrue(result["already_open"])
        self.assertTrue(existing.activated)
        self.assertEqual(app.open_calls, [])
        self.assertEqual(app.log, [])

    def test_refuses_to_open_when_macros_cannot_be_disabled(self):
        self.make("Documents/Report.docx")
        app = RecordingApp("word", fail_security=True)
        with self.assertRaises(office.OfficeAutomationError):
            self.run_open(app, {"file_path": "Documents/Report.docx"})
        self.assertEqual(app.open_calls, [])

    def test_office_errors_are_wrapped_and_settings_restored(self):
        self.make("Documents/Report.docx")
        app = RecordingApp("word")
        app.Documents.Open = mock.Mock(side_effect=Exception("file is corrupt"))
        with self.assertRaises(office.OfficeAutomationError) as caught:
            self.run_open(app, {"file_path": "Documents/Report.docx"})
        self.assertIn("could not open", str(caught.exception))
        self.assertEqual(app.AutomationSecurity, 2)
        self.assertEqual(app.DisplayAlerts, -1)

    def test_file_changed_after_approval_is_not_opened(self):
        path = self.make("Documents/Report.docx")
        preview = docs.prepare_open_request({"file_path": "Documents/Report.docx"})
        app = RecordingApp("word")
        path.write_bytes(ZIP + b"tampered after approval")
        with self.assertRaises(PermissionError):
            self.run_open(app, {"file_path": "Documents/Report.docx"},
                          _expected_size=preview["size_bytes"], _expected_modified_ns=preview["modified_ns"])
        self.assertEqual(app.open_calls, [])
        same_size = path.stat().st_size
        os.utime(path, ns=(1_000_000_000, 1_000_000_000))
        with self.assertRaises(PermissionError):
            self.run_open(app, {"file_path": "Documents/Report.docx"}, _expected_size=same_size,
                          _expected_modified_ns=preview["modified_ns"])

    def test_approved_fingerprint_allows_open(self):
        self.make("Documents/Report.docx")
        preview = docs.prepare_open_request({"file_path": "Documents/Report.docx"})
        app = RecordingApp("word")
        result = self.run_open(app, {"file_path": "Documents/Report.docx"},
                               _expected_size=preview["size_bytes"], _expected_modified_ns=preview["modified_ns"])
        self.assertTrue(result["ok"])


class ListAndActivateTests(unittest.TestCase):
    def make_apps(self):
        word = RecordingApp("word")
        first, second = FakeItem(r"C:\Users\Demo\Documents\A.docx"), FakeItem(r"C:\Users\Demo\Desktop\A.docx", read_only=True)
        word.items.extend([first, second])
        word.ActiveDocument = second
        excel = RecordingApp("excel")
        book = FakeItem(r"C:\Users\Demo\Documents\Budget.xlsx")
        excel.items.append(book)
        excel.ActiveWorkbook = book
        return word, excel, first, second, book

    def run_list(self, args, **connected):
        def fake_connect(progid, allow_launch=False):
            for key, app in connected.items():
                if office.APP_PROGIDS[key] == progid:
                    return app
            raise office.OfficeAutomationError("not running")
        stub = Node(CoInitialize=lambda: None, CoUninitialize=lambda: None)
        with mock.patch.dict(sys.modules, {"pythoncom": stub}), \
                mock.patch.object(office, "_require_windows"), \
                mock.patch.object(office, "_connect", side_effect=fake_connect):
            return docs.execute("office_list_open_documents", args)

    def test_lists_names_only_and_marks_the_active_document(self):
        word, excel, *_ = self.make_apps()
        result = self.run_list({}, word=word, excel=excel)
        self.assertEqual(result["count"], 3)
        summary = [(d["application"], d["index"], d["name"], d["active"], d["read_only"]) for d in result["documents"]]
        self.assertEqual(summary, [("word", 1, "A.docx", False, False), ("word", 2, "A.docx", True, True),
                                   ("excel", 1, "Budget.xlsx", True, False)])
        self.assertNotIn("Users", str(result))  # no paths leave the machine

    def test_list_can_be_limited_to_one_application_and_skips_closed_apps(self):
        word, excel, *_ = self.make_apps()
        self.assertEqual(self.run_list({"application": "excel"}, word=word, excel=excel)["count"], 1)
        self.assertEqual(self.run_list({}, word=word)["count"], 2)
        with self.assertRaises(ValueError):
            self.run_list({"application": "outlook"}, word=word)

    def run_activate(self, args, app):
        with mock.patch.object(office, "_with_app", side_effect=lambda key, callback, allow_launch=False: callback(app)):
            return docs.execute("office_activate_document", args)

    def test_activate_by_index_and_unique_name(self):
        word, excel, first, second, book = self.make_apps()
        self.assertTrue(self.run_activate({"application": "word", "index": 1}, word)["ok"])
        self.assertTrue(first.activated)
        self.run_activate({"application": "excel", "name": "budget.XLSX"}, excel)
        self.assertTrue(book.activated)

    def test_activate_validation(self):
        word, *_ = self.make_apps()
        for bad in ({"application": "word"}, {"application": "word", "name": "A.docx", "index": 1},
                    {"application": "outlook", "index": 1}, {"application": "word", "index": 9},
                    {"application": "word", "index": True}):
            with self.subTest(args=bad), self.assertRaises(ValueError):
                self.run_activate(bad, word)
        with self.assertRaises(office.OfficeAutomationError):
            self.run_activate({"application": "word", "name": "Missing.docx"}, word)
        with self.assertRaises(office.OfficeAutomationError) as caught:
            self.run_activate({"application": "word", "name": "A.docx"}, word)  # two documents share the name
        self.assertIn("index", str(caught.exception))


class DispatchTests(unittest.TestCase):
    def test_execute_action_routes_document_actions(self):
        office.resume_actions()
        with mock.patch.object(docs, "execute", side_effect=lambda name, args: {"ok": True, "name": name}):
            for name in sorted(docs.ACTIONS):
                self.assertEqual(office.execute_action(name, {})["name"], name)

    def test_unknown_extension_map_is_macro_free_only(self):
        self.assertEqual(set(docs.OPEN_EXTENSIONS), {".docx", ".xlsx", ".pptx"})


if __name__ == "__main__":
    unittest.main()
