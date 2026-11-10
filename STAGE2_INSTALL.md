# Ozzy Browser Automation — Stage 2

This patch adds Playwright semantic browser automation to the existing PC Control v1 implementation.

## What it adds

- Open a visible managed Microsoft Edge, Google Chrome, or Playwright Chromium browser.
- Keep the browser in a dedicated persistent profile under the Ozzy user-data folder. It does **not** attach to the user's ordinary Chrome/Edge profile.
- Inspect visible page text and visible interactive controls.
- Find and click a unique element by accessible role/name, text, label, placeholder, alt text, title, or test ID.
- Fill normal text fields, choose native dropdown options, check/uncheck checkboxes and radio controls.
- Navigate, refresh, go back/forward, open/switch tabs, scroll, and capture an in-memory screenshot.
- Reuse the existing PC Control opt-in and stop state. Browser actions are off until the user enables PC Control.

## Apply to the current Ozzy repository

1. Extract the ZIP into the root of the Ozzy repository (the folder containing `server.py` and `index.html`).
2. Open PowerShell in that folder and run:

```powershell
python .\apply_browser_automation.py
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m py_compile server.py browser_control.py computer_control.py
node --check desktop\main.js
node --check desktop\preload.js
```

3. Launch Ozzy with `npm start`.
4. Connect to Ozzy, open Advanced Options, enable PC Control, and approve the updated permission prompt.
5. Ask Ozzy to open a user-requested website. The first managed browser launch uses Microsoft Edge by default; the browser tool can also select `chrome` or `chromium`.

The apply script validates all expected source anchors before it modifies project files. It backs up the originals under `backups/browser-automation-stage2/`.

## Browser prerequisites

- `msedge` uses Microsoft Edge installed on the computer.
- `chrome` uses Google Chrome installed on the computer.
- `chromium` uses Playwright's downloaded Chromium. Install it only when needed:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

The Windows PyInstaller build now collects the Playwright Python driver. The browser application itself must still be installed on the target computer (Edge/Chrome) or installed as Playwright Chromium.

## Safety and privacy

- The browser profile is separate from the user's ordinary browser profile. Existing Chrome/Edge cookies and tabs are not reused.
- Cookies and sign-ins made in the Ozzy-managed browser are stored locally in its dedicated profile.
- Page text and screenshots requested for analysis are sent to Gemini. Page inspection does not read form field values.
- Password, API-key, access-token, verification-code, and payment fields are blocked. High-impact controls (send, publish, delete, purchase, checkout, transfer, etc.) are blocked by target text and must be handled manually.
- URLs are limited to HTTP and HTTPS. Embedded URL credentials are rejected. Query strings are redacted in returned URL summaries.
- No file upload/download tool, arbitrary script execution, shell execution, or generic form-submit tool is exposed.
- Webpage content is untrusted data and cannot grant Ozzy permission to act.
