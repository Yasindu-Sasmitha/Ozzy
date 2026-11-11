# Install Ozzy Stage 4 — Context-aware Desktop Workflows

This patch targets the current Ozzy `main` branch after Stage 3 UIA Hotfix 2 (commit `bfe2c6d`). It assumes the Stage 1–3 code and `pywinauto` dependency are already installed and working.

## 1. Apply the patch

1. Close Ozzy completely.
2. Extract this ZIP directly into the existing repository root — the folder containing `server.py`, `windows_automation.py`, `requirements.txt`, and `scripts/`.
3. Open PowerShell in that repository root.
4. Run:

```powershell
.\.venv\Scripts\python.exe .\apply_stage4_patch.py
```

The integration script checks for the expected current source sections before changing files. It backs up the original versions of `server.py`, `scripts\build-backend.ps1`, `README.md`, and `PC_CONTROL.md` under `backups\stage4-desktop-workflows\`. It adds `windows_workflows.py`, `safe_file_actions.py`, and both new test files under `tests\`.

Do not run this script from the ZIP extraction folder unless that folder is your Ozzy repository root. It must be run from the project root.

## 2. Run tests and syntax checks

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_windows_workflows.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_safe_file_actions.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m py_compile server.py windows_automation.py windows_workflows.py safe_file_actions.py browser_control.py computer_control.py
node --check desktop\main.js
node --check desktop\preload.js
```

No new requirements need to be installed. Stage 4 reuses `pywinauto` and the existing PC Control permission state.

## 3. Launch

```powershell
npm start
```

Connect to Ozzy and enable PC Control in Advanced Options.

## 4. New Stage 4 tools

**Native UI workflow tools**

- `windows_wait_for_window`: waits up to 15 seconds for one visible top-level window/dialog by title.
- `windows_wait_for_control`: waits up to 15 seconds for one exact UIA control to become visible and enabled.
- `windows_get_control_state`: verifies control visibility/enabled state, checkbox state, radio/tab/list selection and keyboard focus when exposed by the provider. It never reads Edit values or document text.

**Restricted file tools**

- `files_list_directory`: lists visible, non-sensitive metadata for up to 100 items inside Desktop, Documents, Downloads, or another folder under the current user's profile. It never reads file contents.
- `files_create_folder`: creates one new folder inside an existing user-profile directory. It never merges with an existing folder.
- `files_create_text_file`: creates a new `.txt` or `.md` file, maximum 3,000 characters. It never overwrites an existing file.

File tools require a direct user request and PC Control opt-in. They skip hidden/system items and symlinks, reject paths outside the user profile and block sensitive names. Delete, overwrite, move, rename, copy, download, and file execution are not available.

Waits poll every 250 ms, have a hard 15-second maximum and check PC Control permission on every poll. Stop Now cancels the wait. Ambiguous matches fail immediately rather than guessing.

## 5. Suggested first tests

1. In Notepad, use `Ctrl+Shift+S` only if the document is unsaved, or use a harmless app dialog that you opened yourself.
2. Ask Ozzy: “Wait for the Save As window to appear.”
3. Ask Ozzy to inspect that dialog and identify its file-name control.
4. Ask: “Wait for the File name control to become available.”
5. Ask Ozzy to inspect again and verify a checkbox state using `windows_get_control_state`.
6. Press Stop Now while Ozzy is waiting for a window that will not appear; it should cancel quickly.
7. Ask: “List the files and folders in Downloads.” This should return metadata only.
8. Ask: “Create a folder named `Ozzy-Stage4-Test` on my Desktop.”
9. Ask: “Inside `Desktop\Ozzy-Stage4-Test`, create a text file named `stage4-note.md` containing `Ozzy Stage 4 file test.`”
10. Ask Ozzy to list that test folder and confirm the new filename appears.
11. Try creating the same filename again. Ozzy should refuse rather than overwrite it.

Do not save over an existing file during the UI dialog test. Use a new test name and cancel the dialog after checking the controls. The file-tool test creates a new folder and a new Markdown file; remove that test folder manually in File Explorer after testing if you no longer need it.

## Rollback

Close Ozzy and restore the backed-up files from the newest `backups\stage4-desktop-workflows\<timestamp>\` directory. Remove the added `windows_workflows.py`, `safe_file_actions.py`, `tests\test_windows_workflows.py`, and `tests\test_safe_file_actions.py` files. Stage 1–3 files are not otherwise changed by this patch.
