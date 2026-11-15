# Ozzy Stage 6 — Approval Dialog Hotfix

This hotfix fixes the Stage 6 save/delete confirmation path. Instead of relying on `window.confirm()` inside the renderer, it displays an Electron-native dialog from the main process through a narrowly scoped IPC handler.

## Install

1. Close Ozzy completely.
2. Extract `apply_stage6_approval_fix.py` into `C:\Users\DELL\Desktop\Ozzy` (project root).
3. Open PowerShell in the project root and run:

```powershell
.\.venv\Scripts\python.exe .\apply_stage6_approval_fix.py
```

4. Restart Ozzy:

```powershell
npm start
```

The patch backs up `index.html`, `desktop\preload.js`, and `desktop\main.js` under `backups\stage6-approval-fix-<timestamp>`. It does not modify SQLite data, saved memories, workflow recipes, Stage 5, or the workflow execution engine.

## Test

With Ozzy connected and PC Control enabled, run a harmless Stage 5 workflow and explicitly ask Ozzy to save it. The Electron confirmation dialog should display the recipe name, description, and step preview. Select **Save workflow** to approve or **Cancel** to reject. Deletion uses a separate confirmation.

Then check the workflow library list. A rejected or unavailable dialog must not save or delete anything.

## Syntax checks

```powershell
.\.venv\Scripts\python.exe -m py_compile .\apply_stage6_approval_fix.py
node --check .\desktop\preload.js
node --check .\desktop\main.js
```

## Rollback

Close Ozzy and restore the three backed-up files from the matching `backups\stage6-approval-fix-*` folder. No database rollback is required.
