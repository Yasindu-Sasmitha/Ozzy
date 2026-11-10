# Ozzy Stage 3 — Windows Application Automation

Stage 3 adds a Windows UI Automation (UIA) layer using the stable `pywinauto` 0.6.x package. It complements rather than replaces Stage 1 visual desktop control and Stage 2 Playwright browser automation.

## What it adds

- `windows_list_windows`: list visible top-level application windows and return their window handles.
- `windows_inspect`: inspect the active window or a window selected by a handle from `windows_list_windows`; return visible control names, control types, automation IDs, enabled/visible state and bounds. It does not read Edit control values.
- `windows_activate`: focus a selected visible application window.
- `windows_click`: activate one uniquely identified safe Button, MenuItem, TabItem, ListItem, TreeItem, Hyperlink, SplitButton, Document or Pane control. Buttons use the UIA Invoke pattern; selection controls use their SelectionItem pattern; other supported controls use a visible click.
- `windows_set_text`: set text in one uniquely identified, non-sensitive Edit control. The entered value is not read back.
- `windows_select`: select a named option in a ComboBox or Tab control.
- `windows_toggle`: set a CheckBox or RadioButton to a requested state.

## Safety and scope

- All Stage 3 actions use the existing per-session **Enable PC Control** consent. They are disabled at startup, blocked by **Stop now**, and disabled when the Live session disconnects.
- UIA controls must be found in the inspected window by exact accessible name and/or Automation ID. Ambiguous matches are rejected; the assistant should inspect again and add `control_type` or `automation_id`.
- Password, PIN, OTP, verification, credential, payment and banking controls are blocked. Sensitive control names and Automation IDs are redacted from inspection results.
- Buttons or controls whose names imply delete, send, publish, purchase, payment, transfer, shutdown, restart, install, uninstall, reset, drive formatting, administration or security changes are blocked.
- The tool layer does not start/kill processes, run shell commands, read/write arbitrary files, close windows, or expose arbitrary keyboard shortcuts. Use Stage 1 for visual fallback when UIA does not expose a control.
- Some applications expose incomplete or custom accessibility trees. UIA may not be able to control elevated applications from a non-elevated Ozzy process; run both at the same privilege level.

## Installation

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe .\apply_windows_automation_stage3.py
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m py_compile server.py windows_automation.py browser_control.py computer_control.py
node --check desktop\main.js
node --check desktop\preload.js
npm start
```

## Example requests

Enable PC Control in Advanced Options, then try:

- "List the open application windows."
- "Inspect the active Word window and tell me which controls are available."
- "Activate the window whose title is Document1."
- "Click the Save button in Word."
- "Inspect File Explorer and open the Downloads folder using its visible navigation control."
- "Find the file name field in the Save As dialog and enter `notes.txt`."

Stage 3 operates through Windows UI Automation patterns. It does not guarantee support for every application or every custom-drawn control. Microsoft Word's document canvas may expose a Document control rather than a normal Edit control; in that case use UIA to focus the document surface and Stage 1 keyboard typing for the actual text.
