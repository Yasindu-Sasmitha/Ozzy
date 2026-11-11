import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import windows_automation
import safe_file_actions


class SafeFileActionTests(unittest.TestCase):
    def setUp(self):
        windows_automation.resume_actions()
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        (self.home / "Desktop").mkdir()
        (self.home / "Documents").mkdir()
        (self.home / "Downloads").mkdir()
        self.home_patch = patch.object(safe_file_actions.Path, "home", return_value=self.home)
        self.home_patch.start()

    def tearDown(self):
        self.home_patch.stop()
        self.temp.cleanup()
        windows_automation.stop_actions()

    def test_known_folder_alias_resolves_inside_home(self):
        self.assertEqual(safe_file_actions._resolve_directory("Desktop"), self.home / "Desktop")
        self.assertEqual(safe_file_actions._resolve_directory("documents"), self.home / "Documents")

    def test_path_outside_home_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            with self.assertRaisesRegex(PermissionError, "limited to folders inside"):
                safe_file_actions._resolve_directory(outside)

    def test_relative_and_parent_traversal_paths_are_rejected(self):
        with self.assertRaises(ValueError):
            safe_file_actions._resolve_directory("OtherFolder")
        with self.assertRaises(ValueError):
            safe_file_actions._resolve_directory(str(self.home / "Documents" / ".." / "Desktop"))

    def test_sensitive_system_directories_are_rejected(self):
        private = self.home / "AppData" / "Roaming"
        private.mkdir(parents=True)
        with self.assertRaisesRegex(PermissionError, "system or private"):
            safe_file_actions._resolve_directory(str(private))
        hidden = self.home / ".private"
        hidden.mkdir()
        with self.assertRaisesRegex(PermissionError, "Hidden folders"):
            safe_file_actions._resolve_directory(str(hidden))

    def test_private_system_folder_names_cannot_be_created(self):
        for name in ("AppData", "Program Files", "Windows"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(PermissionError, "private or system folder"):
                    safe_file_actions._validate_leaf_name(name)

    def test_reparse_point_attribute_is_detected_without_path_is_junction(self):
        class FakePath:
            def is_symlink(self): return False
            def stat(self, *, follow_symlinks=False):
                return type("Stat", (), {"st_file_attributes": 0x400})()

        self.assertTrue(safe_file_actions._is_link_or_junction(FakePath()))

    def test_nonexistent_folder_is_rejected(self):
        with self.assertRaises(FileNotFoundError):
            safe_file_actions._resolve_directory(str(self.home / "missing"))

    def test_sensitive_named_subfolders_are_rejected(self):
        private = self.home / "Documents" / "passwords"
        private.mkdir()
        with self.assertRaisesRegex(PermissionError, "private configuration|credential, secret, or sensitive-data"):
            safe_file_actions._resolve_directory(str(private))

    def test_overlong_directory_path_is_rejected_before_resolution(self):
        with self.assertRaisesRegex(ValueError, "limited to 500 characters"):
            safe_file_actions._resolve_directory("C:\\" + "x" * 501)

    def test_list_directory_reports_metadata_without_contents(self):
        folder = self.home / "Downloads"
        (folder / "notes.txt").write_text("private file body", encoding="utf-8")
        (folder / ".hidden.txt").write_text("hidden", encoding="utf-8")
        (folder / "passwords.txt").write_text("not to list", encoding="utf-8")
        result = safe_file_actions._list_directory({"directory": "Downloads"})
        self.assertTrue(result["ok"])
        names = [item["name"] for item in result["items"]]
        self.assertIn("notes.txt", names)
        self.assertNotIn(".hidden.txt", names)
        self.assertNotIn("passwords.txt", names)
        self.assertNotIn("private file body", str(result))
        self.assertIn("size_bytes", result["items"][0])

    def test_list_directory_skips_symlinks_when_supported(self):
        folder = self.home / "Downloads"
        target = self.home / "Documents" / "target.txt"
        target.write_text("content", encoding="utf-8")
        link = folder / "linked.txt"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation is unavailable in this environment")
        result = safe_file_actions._list_directory({"directory": "Downloads"})
        self.assertNotIn("linked.txt", [item["name"] for item in result["items"]])

    def test_create_folder_creates_only_new_folder(self):
        result = safe_file_actions._create_folder({"directory": "Desktop", "folder_name": "Ozzy Test"})
        self.assertTrue((self.home / "Desktop" / "Ozzy Test").is_dir())
        self.assertIn("No existing items were changed", result["message"])

    def test_create_folder_never_merges_existing_folder(self):
        (self.home / "Desktop" / "Existing").mkdir()
        with self.assertRaisesRegex(FileExistsError, "will not overwrite or merge"):
            safe_file_actions._create_folder({"directory": "Desktop", "folder_name": "Existing"})

    def test_create_text_file_supports_only_plain_text_types(self):
        result = safe_file_actions._create_text_file({
            "directory": "Documents", "file_name": "test-note.md", "content": "Hello Ozzy"
        })
        self.assertEqual((self.home / "Documents" / "test-note.md").read_text(encoding="utf-8"), "Hello Ozzy")
        self.assertEqual(result["characters_written"], 10)

    def test_create_text_file_never_overwrites(self):
        target = self.home / "Documents" / "note.txt"
        target.write_text("original", encoding="utf-8")
        with self.assertRaisesRegex(FileExistsError, "will not overwrite"):
            safe_file_actions._create_text_file({"directory": "Documents", "file_name": "note.txt", "content": "new"})
        self.assertEqual(target.read_text(encoding="utf-8"), "original")

    def test_unsafe_file_extensions_are_rejected(self):
        for name in ("script.py", "app.exe", "macro.bat", "page.html", "data.json", "table.csv"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    safe_file_actions._validate_leaf_name(name, allowed_extensions=safe_file_actions.ALLOWED_TEXT_EXTENSIONS)

    def test_sensitive_names_and_secret_content_are_rejected(self):
        with self.assertRaises(PermissionError):
            safe_file_actions._validate_leaf_name("passwords.txt", allowed_extensions=safe_file_actions.ALLOWED_TEXT_EXTENSIONS)
        with self.assertRaises(PermissionError):
            safe_file_actions._create_text_file({
                "directory": "Documents", "file_name": "note.txt", "content": "api_key = abc123"
            })

    def test_invalid_windows_names_are_rejected(self):
        for name in ("bad:name", "trailing.", "CON.txt", "../escape", ".env"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    safe_file_actions._validate_leaf_name(name)

    def test_large_text_is_rejected(self):
        with self.assertRaises(ValueError):
            safe_file_actions._create_text_file({
                "directory": "Documents", "file_name": "large.txt", "content": "x" * 3001
            })

    def test_common_private_key_and_service_tokens_are_rejected(self):
        samples = (
            "-----BEGIN RSA PRIVATE KEY-----\nnot-a-real-key\n-----END RSA PRIVATE KEY-----",
            "AWS_ACCESS_KEY_ID=AKIA1234567890ABCDEF",
            "client_secret = not-a-real-secret",
            "xoxb-12345678901234567890",
        )
        for content in samples:
            with self.subTest(content=content[:30]):
                with self.assertRaises(PermissionError):
                    safe_file_actions._create_text_file({
                        "directory": "Documents", "file_name": "note.txt", "content": content
                    })

    def test_directory_listing_is_bounded_to_one_hundred_results(self):
        folder = self.home / "Downloads"
        for index in range(125):
            (folder / f"item-{index:03}.txt").touch()
        result = safe_file_actions._list_directory({"directory": "Downloads"})
        self.assertEqual(result["count"], 100)
        self.assertTrue(result["truncated"])

    def test_unknown_action_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported safe file action"):
            safe_file_actions.execute_action("delete_file", {})

    def test_file_actions_require_pc_control_permission(self):
        windows_automation.stop_actions()
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            safe_file_actions.execute_action("files_list_directory", {"directory": "Documents"})


if __name__ == "__main__":
    unittest.main()
