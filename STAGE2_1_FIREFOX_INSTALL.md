# Ozzy Firefox Browser Support (Stage 2.1)

This incremental patch adds Firefox to the existing Stage 2 Playwright browser automation. It preserves the working Edge/Chrome/Chromium flow and the visual mouse/keyboard controls.

## Important distinction

Playwright cannot automate the branded Firefox application directly because it relies on patches in its own Firefox build. This patch launches **Playwright's managed Firefox build**, downloaded by the Playwright CLI. It uses a separate persistent profile at `%APPDATA%\Ozzy\browser-profile-firefox` and does not attach to your everyday Firefox window, tabs, cookies, or profile. Your normal Firefox profile is left untouched.

## Apply

1. Extract this ZIP into the root of the Ozzy project (the folder containing `server.py` and `browser_control.py`).
2. Run:

```powershell
.\.venv\Scripts\python.exe .\apply_firefox_support.py
```

3. Download Playwright's Firefox build:

```powershell
.\.venv\Scripts\python.exe -m playwright install firefox
```

4. Run all tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

5. Syntax checks and launch:

```powershell
.\.venv\Scripts\python.exe -m py_compile server.py browser_control.py computer_control.py
node --check desktop\main.js
npm start
```

Connect Ozzy and enable PC Control. Ask: **"Open example.com in Firefox."** Ozzy should select `browser="firefox"` and launch the managed Playwright Firefox window.

## Profiles

- Existing Edge/Chrome/Chromium profile remains at the current `browser-profile` path.
- Firefox gets a sibling profile directory named `browser-profile-firefox`.
- The profiles are isolated from your normal browser profiles.
- Closing Ozzy's connected session closes the managed browser context, but the Firefox profile persists for later sessions.

## Rollback

The patch backs up the five changed files under `backups\firefox-browser-support\`. Restore those backups after closing Ozzy if you need to revert this incremental patch.
