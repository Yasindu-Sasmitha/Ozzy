from __future__ import annotations
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES = {
    "browser_control.py": ROOT / "browser_control.py",
    "server.py": ROOT / "server.py",
    "tests/test_browser_control.py": ROOT / "tests" / "test_browser_control.py",
    "README.md": ROOT / "README.md",
    "PC_CONTROL.md": ROOT / "PC_CONTROL.md",
}
BACKUP_DIR = ROOT / "backups" / "firefox-browser-support"

def replace_once(src: str, old: str, new: str, label: str) -> str:
    count = src.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source anchor, found {count}. No project files were changed.")
    return src.replace(old, new, 1)

def patch_browser_control(src: str) -> str:
    src = replace_once(src, 'ALLOWED_BROWSERS = {"msedge", "chrome", "chromium"}', 'ALLOWED_BROWSERS = {"msedge", "chrome", "chromium", "firefox"}', "Firefox allow-list")
    src = replace_once(src, 'raise ValueError("Browser must be one of: msedge, chrome, chromium.")', 'raise ValueError("Browser must be one of: msedge, chrome, chromium, firefox.")', "Firefox validation message")
    anchor = '\n\ndef validate_url(url: Any, *, allow_blank: bool = False) -> str:\n'
    helpers = '''


def _browser_type(playwright, browser: str):
    """Choose the Playwright engine. Firefox requires Playwright's patched build."""
    return playwright.firefox if browser == "firefox" else playwright.chromium


def _profile_dir_for_browser(profile_dir: Path | str, browser: str) -> Path:
    """Keep Firefox storage separate while preserving the existing Chromium profile path."""
    base = Path(profile_dir).expanduser().resolve()
    return base.with_name(f"{base.name}-firefox") if browser == "firefox" else base


def _browser_launch_options(browser: str) -> dict[str, Any]:
    if browser == "firefox":
        return {"headless": False, "viewport": None}
    options: dict[str, Any] = {
        "headless": False,
        "viewport": None,
        "args": ["--no-first-run", "--no-default-browser-check"],
    }
    if browser != "chromium":
        options["channel"] = browser
    return options
'''
    src = replace_once(src, anchor, helpers + anchor, "Firefox launch helpers")
    old_start = '            if browser == "chromium":\n'
    old_end = '            raise RuntimeError(f"Could not launch the managed {browser} browser. {hint} Details: {detail}") from exc\n'
    start_index = src.index(old_start, src.index("async def _ensure_started"))
    end_index = src.index(old_end, start_index)
    new_hint = r'''            if browser == "firefox":
                hint = (
                    "Install Playwright's Firefox build with "
                    r".\.venv\Scripts\python.exe -m playwright install firefox. "
                    "Ozzy uses a separate managed Firefox profile; it does not attach to your normal Firefox profile."
                )
            elif browser == "chromium":
                hint = r"Install Playwright Chromium with .\.venv\Scripts\python.exe -m playwright install chromium."
            else:
                hint = f"Make sure {browser.title()} is installed, then try browser='chromium' after installing Playwright Chromium."
'''
    src = src[:start_index] + new_hint + src[end_index:]
    return src

def patch_server(src: str) -> str:
    src = replace_once(
        src,
        "- browser_open launches a visible, Ozzy-managed browser using a separate persistent profile under the Ozzy user-data directory. This profile is separate from the user's ordinary Chrome/Edge profile; do not claim to control their existing normal-profile tabs.\n",
        "- browser_open launches a visible, Ozzy-managed browser using a separate persistent profile under the Ozzy user-data directory. This profile is separate from the user's ordinary browser profile; do not claim to control their existing normal-profile tabs.\n- If the user specifically requests Firefox, call browser_open with browser='firefox'. This launches Playwright's patched Firefox build with its own persistent profile, not the branded Firefox app or the user's normal Firefox profile.\n",
        "Firefox system instructions")
    src = replace_once(
        src,
        'description="Open a user-requested website in Ozzy\'s visible managed browser. It uses a separate Ozzy profile, not the user\'s ordinary Chrome/Edge profile. Browser must be msedge, chrome, or chromium; default is msedge. Requires PC Control opt-in.",',
        'description="Open a user-requested website in Ozzy\'s visible managed browser. It uses a separate Ozzy profile, not the user\'s normal browser profile. Browser options: msedge, chrome, chromium, or firefox; default is msedge. When the user specifically requests Firefox, choose firefox. Firefox uses Playwright\'s own patched Firefox build, not the installed branded Firefox. Requires PC Control opt-in.",',
        "Firefox tool description")
    src = replace_once(
        src,
        '"browser": {"type": "STRING", "enum": ["msedge", "chrome", "chromium"], "description": "Installed browser channel. Defaults to msedge."},',
        '"browser": {"type": "STRING", "enum": ["msedge", "chrome", "chromium", "firefox"], "description": "Browser engine. Firefox uses Playwright\'s managed Firefox build. Defaults to msedge."},',
        "Firefox tool enum")
    return src

def patch_tests(src: str) -> str:
    src = replace_once(
        src,
        '        self.assertEqual(browser_control.validate_browser("CHROME"), "chrome")\n        for value in ("firefox", "edge", "powershell"):\n',
        '        self.assertEqual(browser_control.validate_browser("CHROME"), "chrome")\n        self.assertEqual(browser_control.validate_browser("FIREFOX"), "firefox")\n        for value in ("edge", "powershell", "webkit"):\n',
        "Firefox allow-list test")
    extra = '''    def test_firefox_uses_firefox_engine(self):
        from types import SimpleNamespace
        firefox_engine = object()
        chromium_engine = object()
        playwright = SimpleNamespace(firefox=firefox_engine, chromium=chromium_engine)
        self.assertIs(browser_control._browser_type(playwright, "firefox"), firefox_engine)
        self.assertIs(browser_control._browser_type(playwright, "msedge"), chromium_engine)

    def test_firefox_uses_separate_persistent_profile(self):
        from pathlib import Path
        import tempfile
        base = Path(tempfile.gettempdir()) / "ozzy-test" / "browser-profile"
        firefox = browser_control._profile_dir_for_browser(base, "firefox")
        chromium = browser_control._profile_dir_for_browser(base, "msedge")
        self.assertEqual(firefox, base.with_name("browser-profile-firefox"))
        self.assertEqual(chromium, base)
        self.assertNotEqual(firefox, chromium)

    def test_firefox_launch_options_do_not_include_chromium_flags(self):
        self.assertEqual(browser_control._browser_launch_options("firefox"), {"headless": False, "viewport": None})

'''
    return replace_once(src, '    def test_rejects_long_or_invalid_fill_text(self):\n', extra + '    def test_rejects_long_or_invalid_fill_text(self):\n', "Firefox launch tests")

def patch_readme(src: str) -> str:
    src = replace_once(src,
        "- Open a visible managed Microsoft Edge, Google Chrome, or Playwright Chromium browser.\n",
        "- Open a visible managed Microsoft Edge, Google Chrome, Playwright Chromium, or Playwright Firefox browser.\n",
        "README browser list")
    return replace_once(src,
        "The default `msedge` and `chrome` channels use browsers already installed on Windows. If neither is installed, install Playwright Chromium and request `browser='chromium'`:\n\n```powershell\n.\\.venv\\Scripts\\python.exe -m playwright install chromium\n```\n",
        "The default `msedge` and `chrome` channels use browsers already installed on Windows. Playwright Firefox is a separately downloaded, patched Firefox build; it does not automate the branded Firefox installation or reuse its normal profile. Request `browser='firefox'` to use it. Install it with:\n\n```powershell\n.\\.venv\\Scripts\\python.exe -m playwright install firefox\n```\n\nIf neither Edge nor Chrome is installed, install Playwright Chromium and request `browser='chromium'`:\n\n```powershell\n.\\.venv\\Scripts\\python.exe -m playwright install chromium\n```\n",
        "README Firefox install instructions")

def patch_pc_control_doc(src: str) -> str:
    return replace_once(src,
        "Edge/Chrome channels use those applications when installed. To use Playwright-managed Chromium instead:\n\n```powershell\n.\\.venv\\Scripts\\python.exe -m playwright install chromium\n```\n",
        "Edge/Chrome channels use those applications when installed. Firefox uses Playwright's patched Firefox build (not the branded Firefox install) and a separate `%APPDATA%\\Ozzy\\browser-profile-firefox` profile. Install it with:\n\n```powershell\n.\\.venv\\Scripts\\python.exe -m playwright install firefox\n```\n\nTo use Playwright-managed Chromium instead:\n\n```powershell\n.\\.venv\\Scripts\\python.exe -m playwright install chromium\n```\n",
        "PC Control Firefox install instructions")

def main() -> None:
    for name, path in FILES.items():
        if not path.is_file():
            raise RuntimeError(f"Required file is missing: {name}. Extract this patch into the Stage 2 repository root.")
    originals = {name: path.read_text(encoding="utf-8") for name, path in FILES.items()}
    updated = {
        "browser_control.py": patch_browser_control(originals["browser_control.py"]),
        "server.py": patch_server(originals["server.py"]),
        "tests/test_browser_control.py": patch_tests(originals["tests/test_browser_control.py"]),
        "README.md": patch_readme(originals["README.md"]),
        "PC_CONTROL.md": patch_pc_control_doc(originals["PC_CONTROL.md"]),
    }
    # No project file is written until every source anchor above validates.
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for name, path in FILES.items():
        backup = BACKUP_DIR / name
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(path, backup)
    for name, path in FILES.items():
        path.write_text(updated[name], encoding="utf-8", newline="\n")
    print("Applied Ozzy Firefox Browser Support.")
    print(f"Backups: {BACKUP_DIR.relative_to(ROOT)}")
    print("Next: .\\.venv\\Scripts\\python.exe -m playwright install firefox")
    print("Then: .\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v")

if __name__ == "__main__":
    main()
