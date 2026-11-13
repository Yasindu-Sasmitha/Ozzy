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

Stage 1 provides visual mouse/keyboard control. Stage 2 adds semantic browser automation with Playwright. Stage 3 adds Windows UI Automation (UIA) for native application controls through pywinauto's stable `uia` backend. Some custom application controls may not expose UIA patterns; use visual PC Control as the fallback.

## Stage 2: semantic browser automation

When PC Control is enabled, Ozzy can use Playwright in a visible, dedicated browser profile stored under the Ozzy user-data directory. It can inspect visible page text/controls, use unique semantic locators (role, accessible name, label, placeholder, or visible text), fill non-sensitive fields, select native dropdowns, toggle checkboxes, navigate, manage tabs, refresh, scroll, and capture an in-memory screenshot. It does not attach to the user's ordinary browser profile.

The browser profile stores its own cookies/sign-ins locally. Page text and requested screenshots are sent to Gemini for analysis. Password, verification-code, and payment inputs are blocked; high-impact actions (send/publish/delete/purchase/transfer/etc.) are blocked; file transfers and arbitrary JavaScript are not exposed. Page content remains untrusted and never grants permission to act.

Install into the same virtual environment used by Ozzy:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Edge/Chrome channels use those applications when installed. Firefox uses Playwright's patched Firefox build (not the branded Firefox install) and a separate `%APPDATA%\Ozzy\browser-profile-firefox` profile. Install it with:

```powershell
.\.venv\Scripts\python.exe -m playwright install firefox
```

To use Playwright-managed Chromium instead:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

## Stage 3: Windows application automation

Stage 3 uses `pywinauto` with the Microsoft UI Automation (`uia`) backend. It is additive: Stage 1 visual desktop control and Stage 2 Playwright browser automation remain available. All Stage 3 actions require the same per-session PC Control opt-in and are disabled on Stop now or Live disconnect.

Available tools: `windows_list_windows`, `windows_inspect`, `windows_activate`, `windows_click`, `windows_set_text`, `windows_select`, and `windows_toggle`. Inspection reports accessible control labels, control types, Automation IDs, enabled/visible state and bounds, but does not read Edit values. Controls must be uniquely identified; duplicate matches are rejected. Password/PIN/OTP/verification/credential/payment/banking/security controls and high-impact actions are blocked.

Install the stable pywinauto 0.6.x line into Ozzy's project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Some applications expose incomplete/custom accessibility trees. UIA may not control elevated apps from a non-elevated Ozzy process; run both at the same privilege level. Word's document surface may be exposed as a `Document` rather than an editable `Edit` control; in that case focus the document surface with UIA and use the existing type_text action for document content.

## Stage 4: context-aware desktop workflows

Stage 4 adds bounded UIA workflow helpers and restricted file tools while preserving the Stage 3 safety model:

| Tool | Purpose |
|---|---|
| `windows_wait_for_window` | Wait for a visible application window/dialog by title (maximum 15 seconds). |
| `windows_wait_for_control` | Wait for one exact UIA control to become visible and enabled (maximum 15 seconds). |
| `windows_get_control_state` | Verify visibility/enabled state and supported checkbox/radio/tab/list/focus state without reading text values. |
| `files_list_directory` | List visible metadata in Desktop, Documents, Downloads or another user-profile folder; it never reads contents. |
| `files_create_folder` | Create one new folder in an existing user-profile directory, without merging or overwriting. |
| `files_create_text_file` | Create a new `.txt` or `.md` file (up to 3,000 characters), without overwriting. |

Use a sequence of small actions: inspect, activate/click, wait for the expected dialog or control, inspect again, then verify state. Waits are cancelled by Stop Now and reject ambiguous matches. File tools require a direct user request, stay inside the current user's profile, skip hidden/system items and symlinks, and never read file contents. Deletion, overwrite, move, rename, copy, downloads and execution are unavailable. No new dependencies are required.

