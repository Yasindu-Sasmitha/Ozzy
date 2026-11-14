# Ozzy Stage 5 — Multi-Step Workflow Intelligence

This is an overlay patch for the current `main` branch checked on 2026-11-13. It adds a bounded workflow coordinator while continuing to use the existing browser, Windows UI Automation, Stage 4 wait/state, and safe file adapters.

## Install

1. Close Ozzy completely.
2. Extract the complete ZIP into the Ozzy project root (`C:\Users\DELL\Desktop\Ozzy`). Keep folder structure and allow the new test file to be added under `tests`.
3. Open PowerShell in the project root and run:

```powershell
.\.venv\Scripts\python.exe .\apply_stage5_patch.py
```

The installer makes timestamped backups of `server.py`, `index.html`, and `README.md` under `backups\stage5-*`. It checks all patch anchors before writing files and does not modify files if an anchor is missing.

## Validate

```powershell
.\.venv\Scripts\python.exe -m py_compile workflow_engine.py server.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_workflow_engine.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check desktop\main.js
node --check desktop\preload.js
```

Then start Ozzy:

```powershell
npm start
```

Connect, explicitly enable PC Control, and test with a harmless browser workflow first.

## Example workflow

Ask Ozzy: “Open the dashboard in your managed browser, then confirm the dashboard page loaded.”

The model should create a sequence using `workflow_run`. Each state-changing step in a multi-step workflow has an explicit read-only verifier; read-only observation steps can stand alone. For example, opening a site can be verified by `browser_inspect` and an expected URL/title field. Progress is shown in the PC Control activity panel.

## Stage 5 boundaries

- Up to 8 sequential steps and 120 seconds per workflow.
- 30-second per-action timeout.
- Every state-changing step in a multi-step workflow requires a read-only verification assertion; read-only observation steps can stand on their own.
- No automatic retries; a failed action or verification stops remaining steps.
- Disabling PC Control stops the workflow before the next step and before verification where possible; individual adapters retain their own stop checks. A Windows UIA provider call already running in a worker thread may finish after the workflow timeout; the runner will not start later steps.
- Raw visual mouse/keyboard actions, text-field filling and text-setting are not part of workflow orchestration v1 because their outcomes are not independently read back by the existing safety-limited inspection APIs. Use the existing individual tools separately when appropriate; the workflow runner will not pretend those field values were verified.
- Existing browser, Windows UIA and file safety checks remain in force. No delete, send, publish, purchase, credential, admin, shell, or arbitrary script tools are added.
- A single action may run without verification, but Ozzy reports it as `completed_unverified` rather than claiming the result was confirmed.
- No new Python packages are required.

## Rollback

Close Ozzy. Restore `server.py`, `index.html`, and `README.md` from the same timestamped backup folder created by the installer, then remove `workflow_engine.py` and `tests/test_workflow_engine.py`. The patch does not alter Stage 1–4 modules.
