# Ozzy Stage 7 — Office Productivity

## What this adds

Stage 7 connects Ozzy to already-running Microsoft Word, Excel and PowerPoint applications through Windows COM automation. It extends the existing PC Control consent and Stage 5/6 workflow engine; it does not create a second permission system.

- Word: inspect a bounded document excerpt, append text, and add Heading 1–3. Editing is restricted to macro-free `.docx` documents; other formats are inspect-only.
- Excel: inspect up to 200 cells (with a bounded response), write literal rectangular values to an exact range, and add a new worksheet. Editing is restricted to macro-free `.xlsx` workbooks. Formula-like text is blocked. Excel events are temporarily suspended for edits and restored to their previous state; this temporarily affects all open workbooks in that Excel instance.
- PowerPoint: inspect text excerpts from up to 30 recent slides and add a new title-and-content slide. Editing is restricted to macro-free `.pptx` presentations; other formats are inspect-only.
- Office save: create a new `.docx`, `.xlsx` or `.pptx` file in Desktop, Documents or OneDrive under the Windows user profile, after a separate native confirmation dialog. Existing destinations are rejected.
- Non-save Office actions are available to the existing bounded workflow engine and can be saved as Stage 6 workflow recipes. `office_save_new` is intentionally excluded from reusable workflows in this release because it requires an interactive approval at execution time.

## Install

1. Close Ozzy.
2. Extract this ZIP into the root of `C:\Users\DELL\Desktop\Ozzy` (or your actual Ozzy repository folder), keeping the folder structure.
3. Open PowerShell in that folder and run:

```powershell
.\.venv\Scripts\python.exe .\apply_stage7_patch.py
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

4. Restart Ozzy with `npm start`.

The patch installer creates timestamped backups of every modified existing file before applying changes. It also installs `office_automation.py` and the unit test file. The Stage 7 patch does not modify the SQLite database or existing Office documents.

## First-time checks

Install the Microsoft Office desktop applications (Microsoft 365 web apps are not sufficient), then open Word, Excel and PowerPoint yourself and create blank test documents/workbooks/presentations. For the most predictable first test, keep each app running in the same Windows user session as Ozzy. Connect Ozzy, enable PC Control, and try:

- “Which Office apps are already open?”
- “Inspect the active Word document.”
- “Append this sentence to the end of the active Word document: Stage 7 test.”
- “Inspect cells A1:C5 in the active Excel worksheet.”
- “Write this data to cells A1:B2 in the active Excel workbook: [[\"Name\",\"Score\"],[\"Ada\",98]].”
- “Add a worksheet named Ozzy Test to the active Excel workbook.”
- “Add a slide titled Stage 7 Test with body text Office automation is connected.”

For the save test, explicitly ask Ozzy to save the active file as a new file, for example `C:\Users\DELL\Documents\Ozzy-Word-Test.docx`. Review the full path in the native dialog and approve or cancel it. Try an existing destination afterward; Ozzy must reject it without overwriting.

## Tests and syntax checks

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_office_automation -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m py_compile server.py workflow_engine.py office_automation.py
node --check desktop\main.js
node --check desktop\preload.js
```

Unit tests exercise validation and consent behavior without requiring Office or Windows. Actual COM behavior must be tested on a Windows PC with licensed Office desktop applications running. This patch has not been live-tested against your installed Office applications.

## Important limits

- Office desktop applications must already be running. Ozzy does not launch them or open arbitrary files.
- Only the active document/workbook/worksheet/presentation is targeted; Excel range inspection/writes can optionally name a worksheet.
- Word text is appended at the end. Excel writes literal values only; formulas, macro-enabled documents, macros, and external links are not edited or created. PowerPoint only adds slides.
- Office content remains unsaved in the active app until you explicitly request `office_save_new` and approve the native dialog.
- Word's Save As changes the active document's path to the new file. Excel and PowerPoint create copies and keep the original active file path.
- Office save paths must be new files under Desktop, Documents or OneDrive. The first release supports `.docx`, standard `.xlsx` workbooks and `.pptx` presentations only. Legacy and macro-enabled files are inspect-only and cannot be edited or copied by the save action.
- Do not use Ozzy on sensitive documents unless you are comfortable sending requested document excerpts/cell values to Gemini for analysis.

## Rollback

Close Ozzy. Restore the timestamped backups created by `apply_stage7_patch.py` for the files you want to revert. Remove the new `office_automation.py` only after restoring `server.py` and `workflow_engine.py`. Remove `tests/test_office_automation.py` if desired. The patch does not alter `ozzy_memory.sqlite3`.
