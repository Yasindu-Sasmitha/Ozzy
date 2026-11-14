# Ozzy Stage 6 — Workflow Library & Execution History

Stage 6 adds named, reusable workflow recipes and local run history on top of Stage 5. It does not add a new automation engine or new operating-system actions.

## What is included

- Local SQLite storage in the existing `%APPDATA%\Ozzy\ozzy_memory.sqlite3` database (development) or the existing Ozzy user-data database path.
- Explicit in-app confirmation before a workflow recipe is saved or deleted.
- Read-only listing, searching and recent run-history tools.
- Running a named saved recipe through the existing Stage 5 workflow engine. Stored steps are revalidated every time.
- Separate counters and timestamps for template use, plus bounded recent execution summaries.
- No new Python dependencies.

## Install

1. Close Ozzy completely.
2. Extract the complete ZIP into the Ozzy project root, for example `C:\Users\DELL\Desktop\Ozzy`. Merge the included `tests` folder when prompted.
3. Open PowerShell in the project root and run:

```powershell
.\.venv\Scripts\python.exe .\apply_stage6_patch.py
```

The installer verifies each integration point before changing files. It backs up `server.py`, `index.html`, and `README.md` under `backups\stage6-<timestamp>`. It refuses to install twice.

## Test

Run the Stage 6 unit tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_workflow_library.py" -v
```

Run all tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Check Python syntax:

```powershell
.\.venv\Scripts\python.exe -m py_compile workflow_library.py server.py
```

Start Ozzy:

```powershell
npm start
```

## First test sequence

Connect Ozzy, enable PC Control, and run a small, harmless Stage 5 workflow such as opening `https://example.com` and verifying the page title. Then explicitly ask Ozzy to save that routine under a name such as `Open Example Site`. Approve the confirmation. Ask Ozzy to list saved workflows, run `Open Example Site`, and show its run history.

For deletion testing, explicitly ask Ozzy to delete that saved workflow. Approve the separate confirmation only after checking the displayed name. Then list saved workflows again to confirm it is gone.

## Safety and behavior

- Saving requires an explicit user request plus a separate app confirmation. Merely running a workflow never saves it automatically.
- Running a saved recipe requires a direct user request and the existing per-session PC Control permission. A saved recipe is not a permission grant.
- Every run reuses Stage 5 validation, verification, timeouts, allowed actions and Stop Now checks.
- Credentials, common secret patterns and sensitive URL query parameters are rejected from stored recipes.
- Deleting a recipe removes only that local recipe and its local history. It does not delete any file or data in another application or website.
- Run history is local metadata (status, step counts, duration and timestamp only; no observed page text or window titles). It does not prove the current state of an external website or app.

## Rollback

Close Ozzy. Restore `server.py`, `index.html`, and `README.md` from the matching `backups\stage6-<timestamp>` folder. Delete `workflow_library.py` and `tests\test_workflow_library.py` if you want to remove the Stage 6 code. The two Stage 6 SQLite tables can remain harmlessly unused; no saved memories are changed. If you wish to remove the Stage 6 tables as well, back up the database first and ask for a separate database migration script rather than editing the database manually.
