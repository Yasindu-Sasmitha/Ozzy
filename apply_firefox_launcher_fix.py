from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BROWSER_CONTROL = ROOT / "browser_control.py"
TESTS = ROOT / "tests" / "test_browser_control.py"
BACKUP_DIR = ROOT / "backups" / "firefox-launcher-fix"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: expected exactly one source anchor, found {count}. "
            "No project files were changed. Make sure Stage 2.1 Firefox support is installed."
        )
    return source.replace(old, new, 1)


def patch_browser_control(source: str) -> str:
    helper_anchor = "\n\ndef validate_url(url: Any, *, allow_blank: bool = False) -> str:\n"
    launch_helper = '''

async def _launch_persistent_context(playwright, browser: str, profile_dir: Path | str):
    """Launch the selected Playwright engine with a browser-specific persistent profile."""
    selected_profile = _profile_dir_for_browser(profile_dir, browser)
    selected_profile.mkdir(parents=True, exist_ok=True)
    browser_type = _browser_type(playwright, browser)
    launch_options = _browser_launch_options(browser)
    return await browser_type.launch_persistent_context(
        user_data_dir=str(selected_profile), **launch_options
    )
'''
    source = replace_once(source, helper_anchor, launch_helper + helper_anchor, "engine-specific launch helper")

    old_launch = '''        self.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._playwright = await async_playwright().start()
            launch_options: dict[str, Any] = {
                "headless": False,
                "viewport": None,
                "args": ["--no-first-run", "--no-default-browser-check"],
            }
            if browser != "chromium":
                launch_options["channel"] = browser
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir), **launch_options
            )
'''
    new_launch = '''        try:
            self._playwright = await async_playwright().start()
            self._context = await _launch_persistent_context(
                self._playwright, browser, self.profile_dir
            )
'''
    source = replace_once(source, old_launch, new_launch, "Playwright persistent-context engine selection")
    return source


def patch_tests(source: str) -> str:
    test_class = '''

class BrowserEngineLaunchTests(unittest.IsolatedAsyncioTestCase):
    async def test_firefox_launches_through_firefox_engine_and_uses_firefox_profile(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace

        class FakeEngine:
            def __init__(self):
                self.options = None

            async def launch_persistent_context(self, **kwargs):
                self.options = kwargs
                return "firefox-context"

        firefox_engine = FakeEngine()
        chromium_engine = FakeEngine()
        playwright = SimpleNamespace(firefox=firefox_engine, chromium=chromium_engine)

        with TemporaryDirectory() as temp_dir:
            base_profile = Path(temp_dir) / "browser-profile"
            result = await browser_control._launch_persistent_context(
                playwright, "firefox", base_profile
            )
            self.assertEqual(result, "firefox-context")
            firefox_profile = base_profile.with_name("browser-profile-firefox")
            self.assertEqual(firefox_engine.options["user_data_dir"], str(firefox_profile))
            self.assertTrue(firefox_profile.is_dir())
            self.assertNotIn("channel", firefox_engine.options)
            self.assertNotIn("args", firefox_engine.options)
            self.assertFalse(firefox_engine.options["headless"])
            self.assertIsNone(firefox_engine.options["viewport"])
            self.assertIsNone(chromium_engine.options)

    async def test_edge_still_launches_through_chromium_with_channel(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace

        class FakeEngine:
            def __init__(self):
                self.options = None

            async def launch_persistent_context(self, **kwargs):
                self.options = kwargs
                return "edge-context"

        firefox_engine = FakeEngine()
        chromium_engine = FakeEngine()
        playwright = SimpleNamespace(firefox=firefox_engine, chromium=chromium_engine)

        with TemporaryDirectory() as temp_dir:
            base_profile = Path(temp_dir) / "browser-profile"
            result = await browser_control._launch_persistent_context(
                playwright, "msedge", base_profile
            )
            self.assertEqual(result, "edge-context")
            self.assertEqual(chromium_engine.options["user_data_dir"], str(base_profile))
            self.assertEqual(chromium_engine.options["channel"], "msedge")
            self.assertIn("--no-first-run", chromium_engine.options["args"])
            self.assertIsNone(firefox_engine.options)
'''
    anchor = "\n\nclass BrowserControlConsentTests(unittest.IsolatedAsyncioTestCase):\n"
    return replace_once(source, anchor, test_class + anchor, "engine launch regression tests")


def main() -> None:
    for path in (BROWSER_CONTROL, TESTS):
        if not path.is_file():
            raise RuntimeError(f"Required file is missing: {path}. Extract this patch into the Ozzy repository root.")

    original_browser = BROWSER_CONTROL.read_text(encoding="utf-8")
    original_tests = TESTS.read_text(encoding="utf-8")
    updated_browser = patch_browser_control(original_browser)
    updated_tests = patch_tests(original_tests)

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for path in (BROWSER_CONTROL, TESTS):
        backup = BACKUP_DIR / path.relative_to(ROOT)
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(path, backup)

    BROWSER_CONTROL.write_text(updated_browser, encoding="utf-8", newline="\n")
    TESTS.write_text(updated_tests, encoding="utf-8", newline="\n")
    print("Applied Firefox Playwright launcher fix.")
    print("Firefox now launches via playwright.firefox, not playwright.chromium with channel='firefox'.")
    print(f"Backups: {BACKUP_DIR.relative_to(ROOT)}")
    print("Next: .\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v")


if __name__ == "__main__":
    main()
