# Ozzy Firefox Launcher Fix

## Why Firefox did not open

The earlier Stage 2.1 patch added Firefox to the browser allow-list and created engine-selection helpers, but the actual launch path still called `playwright.chromium.launch_persistent_context(...)`. It also passed `channel="firefox"`. Playwright reports `Unsupported chromium channel "firefox"` because Firefox must be launched through `playwright.firefox`.

## Apply

1. Extract this ZIP into the root of your Ozzy repository (the folder containing `server.py` and `browser_control.py`).
2. In PowerShell, run:

```powershell
.\.venv\Scripts\python.exe .\apply_firefox_launcher_fix.py
```

3. Run the tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

4. Restart Ozzy:

```powershell
npm start
```

You do not need to reinstall Playwright or Firefox if `playwright install firefox` already completed successfully in Ozzy's `.venv`.

## What changes

- Selects `playwright.firefox` when `browser="firefox"`.
- Retains `playwright.chromium` for Edge, Chrome and Chromium.
- Uses a separate `browser-profile-firefox` directory for Firefox.
- Uses Firefox-appropriate launch options (no Chromium channel or Chromium-only flags).
- Adds regression tests that verify Firefox goes through the Firefox engine and that Edge remains on Chromium.

The patch backs up the two modified files under `backups/firefox-launcher-fix/` and verifies all source anchors before changing either file.
