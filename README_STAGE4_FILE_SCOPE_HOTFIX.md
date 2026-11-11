# Ozzy Stage 4 — File Scope Hotfix

This hotfix fixes the Stage 4 `safe_file_actions._resolve_directory()` check that rejected ordinary test folders on Windows.

## Cause

On Windows, `tempfile.TemporaryDirectory()` commonly creates test folders beneath `%LOCALAPPDATA%\Temp`, whose absolute path contains `AppData`. The previous check scanned every component of the resolved absolute path for forbidden names, so it rejected safe `Desktop`, `Documents`, and `Downloads` folders even when they were inside the test's designated user-profile root.

## Fix

The forbidden-folder check now examines only the path components *relative to the profile root*. This allows a profile/test root to be hosted under an ancestor named `AppData`, while continuing to reject a folder such as `<profile>\AppData\Roaming`, as well as other forbidden child folders. The outside-profile check and symlink/junction rejection remain unchanged.

## Apply

1. Close Ozzy.
2. Extract this ZIP directly into the Ozzy project root (the folder containing `server.py`).
3. Allow it to overwrite:
   - `safe_file_actions.py`
   - `tests\test_safe_file_actions.py`
4. Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_safe_file_actions.py" -v
```

5. Then run the Stage 4 workflow tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_windows_workflows.py" -v
```

No dependency changes are required. The hotfix does not change `server.py`, Stage 1, Stage 2, Stage 3, the tool declarations, or the PC Control consent model.
