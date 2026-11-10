# Ozzy Stage 3 hotfix — Windows UI Automation dispatcher

This hotfix fixes a parameter-order bug in `windows_automation.execute_action()`.
The Stage 3 handlers expect `(args, desktop)`, but the dispatcher passed
`(desktop, args)`. As a result, actions such as `windows_inspect`,
`windows_activate`, `windows_click`, `windows_set_text`, `windows_select`, and
`windows_toggle` could fail with errors such as:

`AttributeError: Neither GUI element (wrapper) nor wrapper method 'get' were found`

## Apply

1. Fully close Ozzy.
2. Extract this ZIP directly into the Ozzy project root (the folder containing
   `server.py`). Allow it to overwrite `windows_automation.py` and
   `tests/test_windows_automation.py`.
3. Run these commands from the Ozzy project root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_windows_automation.py" -v
.\.venv\Scripts\python.exe -m py_compile windows_automation.py
```

4. Start Ozzy again and enable PC Control. Try:
   - “List all open application windows.”
   - “Inspect the active application window.”
   - “Activate the [application] window.”

No dependency changes are required. Stage 1 mouse/keyboard control and Stage 2
browser automation are unchanged. This hotfix does not modify `server.py`.
