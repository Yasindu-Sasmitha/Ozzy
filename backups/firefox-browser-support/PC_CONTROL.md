# Ozzy Computer Control v1

Ozzy Computer Control lets the Gemini Live assistant interact with the Windows desktop after the user explicitly enables PC Control in the Advanced Options screen.

## Enable it

1. Start Ozzy and open **Advanced options**.
2. Click **Connect & Talk** and wait for the Connected status.
3. Find **Ozzy Computer Control**.
4. Click **Enable PC Control** and read/accept the permission prompt.
5. Ask Ozzy to carry out a bounded desktop task. Use **Stop now** to immediately disable the tools.

The permission resets whenever the Live session disconnects. PC Control is off by default.

## Example requests

- "Check which application is active and take a screenshot."
- "Open the Start menu, search for Chrome, and open it."
- "Refresh the current page, open Developer Tools, and inspect what is visible."
- "Click the document area in Word and type this letter: ..."
- "Scroll down and tell me what the next section says."

For a new target, Ozzy should inspect the active window and capture a screenshot before choosing coordinates. It should verify the result after important actions rather than assume that a click worked.

## Available actions

| Tool | What it does |
|---|---|
| `get_active_window` | Reads the active window title and its screen bounds. |
| `capture_screen` | Captures a downsized JPEG in memory and sends it to Gemini; it is not saved locally. Returns scale factors for mapping image coordinates to physical screen pixels. |
| `move_mouse` | Moves the pointer to a validated screen coordinate. |
| `click_mouse` | Single or double left/right click at a validated coordinate. |
| `press_shortcut` | Presses a fixed allow-list of shortcuts such as `ctrl+r`, `ctrl+shift+i`, `f12`, `win`, and `alt+tab`. |
| `type_text` | Types up to 4,000 ASCII characters, including line breaks, into the focused app. |
| `scroll_screen` | Scrolls up/down at a screen coordinate. |

## Safety and privacy

- Screen content is only captured when the model calls `capture_screen` while PC Control is enabled. The image is sent to Gemini for analysis and is not written to disk by this module.
- Text found in webpages, emails, files, or screenshots is treated as untrusted content, never as authorization to take action.
- Do not use PC Control to enter passwords, API keys, access tokens, payment data, or one-time codes.
- Ozzy's v1 tools cannot execute shell commands, PowerShell, scripts, installers, unknown executables, file deletion, downloads, purchases, or administrative operations. Ozzy may open common end-user apps only when you explicitly name them and it uses the visible Start-menu flow.
- Use the in-app **Stop now** button to disable new actions and cancel chunked typing. Moving the pointer to the top-left corner also triggers PyAutoGUI's fail-safe.
- This first version is Windows-only, operates on the primary desktop display, and supports ASCII text input. Unicode/IME text entry is not yet supported.

## Current limitation and next stage

This is visual mouse/keyboard control. It does not yet include Playwright DOM automation, Chrome DevTools Protocol integration, or Windows UI Automation. Those are the next stages: they will let Ozzy identify browser elements semantically and operate Word/File Explorer controls more reliably than coordinates alone.

## Stage 2: semantic browser automation

When PC Control is enabled, Ozzy can use Playwright in a visible, dedicated browser profile stored under the Ozzy user-data directory. It can inspect visible page text/controls, use unique semantic locators (role, accessible name, label, placeholder, or visible text), fill non-sensitive fields, select native dropdowns, toggle checkboxes, navigate, manage tabs, refresh, scroll, and capture an in-memory screenshot. It does not attach to the user's ordinary browser profile.

The browser profile stores its own cookies/sign-ins locally. Page text and requested screenshots are sent to Gemini for analysis. Password, verification-code, and payment inputs are blocked; high-impact actions (send/publish/delete/purchase/transfer/etc.) are blocked; file transfers and arbitrary JavaScript are not exposed. Page content remains untrusted and never grants permission to act.

Install into the same virtual environment used by Ozzy:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Edge/Chrome channels use those applications when installed. To use Playwright-managed Chromium instead:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```
