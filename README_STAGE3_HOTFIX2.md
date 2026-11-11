# Ozzy Stage 3 hotfix 2 — active-window resolution and UIA click fallback

This update builds on the Stage 3 dispatcher hotfix and addresses the next two
problems in the supplied log:

1. **Active-window inspection:** the UIA backend returned a `WindowSpecification`
   for `desktop.get_active()` rather than a usable active window wrapper. The
   patch now obtains the foreground HWND through the Windows API and matches it
   against `Desktop.windows()`.
2. **Controls without Invoke/Selection patterns:** some UI Automation providers
   expose a visible, enabled control but do not implement the requested
   `InvokePattern` or `SelectionItemPattern`. The patch now falls back to
   `click_input()` only for explicit missing-pattern errors, after the exact
   control has been uniquely identified and checked visible/enabled. Other
   provider errors still fail instead of being hidden.

The earlier dispatcher argument-order correction is retained.

## Apply

1. Close Ozzy completely.
2. Extract this ZIP directly into the project root (the folder containing
   `server.py`). Allow it to overwrite `windows_automation.py` and
   `tests/test_windows_automation.py`.
3. Run these commands from the project root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_windows_automation.py" -v
.\.venv\Scripts\python.exe -m py_compile windows_automation.py
```

4. Start Ozzy, enable PC Control, and test:
   - “Inspect the active application window.”
   - “Inspect File Explorer and list its visible controls.”
   - “Click the [exact visible control name] control.”

## About the `capture_screen` error after Stop

The log shows PC Control was stopped at 20:07:49.722, then a screen capture
already in flight reached its stop check and was cancelled. That is expected
safety behavior. Do not remove or bypass that stop check. The next action after
Stop should be rejected; this patch does not alter that behavior.

No new dependencies are required. Stage 1 and Stage 2 are untouched.
