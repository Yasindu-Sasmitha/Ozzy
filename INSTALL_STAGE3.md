# Install Ozzy Stage 3 — Windows Application Automation

This patch targets Ozzy `main` after the Firefox launcher fix (`385f5b9`) and the Stage 2.1 Firefox support commit. It also expects your existing Stage 1 and Stage 2 files.

## 1. Extract the patch

Extract the ZIP directly into the root of your existing Ozzy repository — the folder that contains `server.py`, `index.html`, `requirements.txt`, and `desktop/`.

Do not extract it into a new nested folder.

## 2. Apply the integration patch

Open PowerShell in the Ozzy repository root and run:

```powershell
.\.venv\Scripts\python.exe .\apply_windows_automation_stage3.py
```

The script checks that its expected source sections are present before writing. It adds `/backups/` to `.gitignore` so the local safety copies are not accidentally included in your next feature commit. It backs up every modified repository file in:

```text
backups\windows-automation-stage3\
```

It adds `windows_automation.py` and `tests\test_windows_automation.py` to the repository.

## 3. Install the Windows automation dependency

Use the same virtual environment that launches Ozzy:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The patch pins the stable pywinauto 0.6.x line. No browser binaries or separate automation service are needed for Stage 3.

## 4. Run tests and checks

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m py_compile server.py windows_automation.py browser_control.py computer_control.py
node --check desktop\main.js
node --check desktop\preload.js
```

## 5. Launch and test

```powershell
npm start
```

Connect Ozzy, enable **PC Control** in Advanced Options, and keep the target application open. Start by asking Ozzy to list windows, then inspect the target application before asking it to operate a specific control.

Suggested tests:

- “List the open application windows.”
- “Inspect the active Word window and list the available controls.”
- “Activate the Word window.”
- “Inspect File Explorer and tell me the names of the visible navigation controls.”
- “Find the address field in File Explorer and enter `C:\Users\DELL\Downloads`.”
- “Inspect the active Notepad window and find the text editor control.”

For Word's document body, UI Automation may expose a `Document` surface rather than an `Edit` control. Ask Ozzy to focus the document surface, then use the existing visual keyboard `type_text` action for document text.

## Scope and limitations

- Stage 3 is Windows-only and uses pywinauto's Microsoft UI Automation (`uia`) backend.
- It is additive: PyAutoGUI (Stage 1) and Playwright (Stage 2) remain available.
- It does not launch or terminate apps, execute shell commands, read/write arbitrary files directly, or close windows.
- It only operates visible, enabled controls that can be identified uniquely by their exact accessible name and optionally Automation ID/control type.
- Password, verification, credential, payment and security controls are blocked. Obvious high-impact controls such as delete, send, publish, purchase, transfer, shutdown and install are blocked.
- Some custom app controls are not exposed through UI Automation. Elevated apps may also require Ozzy to run at the same privilege level. Use existing visual PC Control actions as a fallback when UIA cannot identify a control.
- UIA inspection does not intentionally read editable field values. Visible labels/control names and requested screenshots are still sent to Gemini for reasoning, as with the other Ozzy control features.

After you have tested Word and File Explorer on your PC, commit the working Stage 3 changes.
