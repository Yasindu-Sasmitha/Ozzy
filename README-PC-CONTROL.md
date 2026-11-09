# Ozzy PC Control v1

This patch adds a permission-gated desktop-control layer to the existing Windows Electron + Python + Gemini Live app.

## What it adds

- `get_active_window`: reads the active window title and bounds.
- `capture_screen`: captures a downsized JPEG in memory and sends it to Gemini; it is not written to disk. The tool returns scale factors so visual coordinates can be mapped back to screen pixels.
- `move_mouse`: moves the pointer to an on-screen coordinate.
- `click_mouse`: supports left/right click and double-click.
- `press_shortcut`: supports a fixed allow-list of shortcuts (including `ctrl+r` and `f12`).
- `type_text`: types up to 4,000 ASCII characters per call, including line breaks.
- `scroll_screen`: scrolls at a screen coordinate.

PC control is off by default. In Advanced Options, connect Ozzy and explicitly enable **PC Control**. Enabling it permits Ozzy to inspect the screen and use the mouse/keyboard for the active session. Use **Stop now** to turn it off immediately. Moving the pointer to the top-left screen corner also triggers PyAutoGUI's physical fail-safe.

## Apply

Extract this patch into the root of the existing Ozzy repository (the folder containing `server.py` and `index.html`), then run:

```powershell
python .\apply_pc_control.py
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m py_compile server.py computer_control.py
node --check desktop\main.js
node --check desktop\preload.js
npm start
```

The patch script backs up each changed file (`server.py`, `index.html`, `requirements.txt`, and `scripts/build-backend.ps1`) under `backups/pc-control-v1/` and writes only after all source anchors have been found exactly once. If the repository files have drifted from the version this patch targets, it stops and leaves them unchanged.

## Safety limits in v1

- Windows 10/11 only.
- No shell/PowerShell execution, script execution, installers, or administrative tools. Common end-user applications may be opened only when the user names them explicitly, using the visible Start-menu flow.
- No file deletion, file moving, downloads, purchases, form submission APIs, or administrative actions.
- Keyboard shortcuts are allow-listed (including `win` for the Start menu); arbitrary key combinations are rejected.
- Typing is limited to 4,000 ASCII characters per call.
- PC control requires the explicit in-app opt-in each session and resets on disconnect.
- WebSocket connections are restricted to the local Ozzy UI origin (`http://127.0.0.1:8000`).
- A stop request cancels ongoing chunked typing and blocks subsequent actions.

The tool layer provides visual mouse/keyboard interaction. It does not yet include semantic browser automation (Playwright), Windows UI Automation, or Word document APIs. Those are the next integration stages after the basic control loop is tested on the target PC.

## Notes

This patch is based on Ozzy `main` commit `34368e8da411e76e95431d0f26c78c1f2b5865f0`. It does not alter or push to GitHub. Review the backup copies if you need to revert.
