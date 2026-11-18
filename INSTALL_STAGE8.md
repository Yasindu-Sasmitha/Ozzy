# Stage 8: Office formatting, formulas and opening existing documents

Applies on top of Stage 7 (and the Office format-check hotfix). No new Python packages are required.

## New files
- `office_styling.py` – validated formatting and formula actions for Word, Excel and PowerPoint
- `office_documents.py` – open existing documents, list open documents, switch active document
- `tests/test_office_styling.py`, `tests/test_office_documents.py`

## Changed files
`office_automation.py`, `server.py`, `workflow_engine.py`, `index.html`, `desktop/main.js`, `desktop/preload.js`, `README.md`

## Manual test checklist (Windows, with Office installed)
Turn PC Control on first.

1. **Open:** "Open Documents\Report.docx". A native dialog shows the full path. Approve it. Word opens the file (and starts if it was closed). Cancel must open nothing.
2. **Word formatting:** "Make the last paragraph bold, Arial 14, dark blue." Then select a sentence in Word and say "highlight my selection yellow". Then "make every 'Total' red".
3. **Word styles:** "Turn paragraph 3 into Heading 2 and center it."
4. **Excel formatting:** "Make A1:D1 bold with a light blue fill and borders." "Format C2:C20 as currency." "Autofit the columns."
5. **Excel formulas:** "Put =SUM(B2:C2) in D2:D10." Then "=IF(D2>=50,\"Pass\",\"Fail\")" in E2:E10. Check the results in the sheet.
6. **Blocked formulas:** ask for `=INDIRECT("A1")`, `=HYPERLINK(...)`, `=SUM(MyName)` or `=SUM([Book2]Sheet1!A1)`. Each must be refused with an explanation.
7. **PowerPoint:** "Make all slide titles Georgia 40 and navy." "Set slide 2 background to light yellow."
8. **Switching:** open two documents, say "list my open documents", then "switch to Budget.xlsx".
9. **Safety:** try opening a `.docm`, a password-protected `.docx`, a file outside Desktop/Documents/Downloads/OneDrive, and a file downloaded from the internet (it must open read-only).

Formatting and formula actions return a read-back of what Office actually applied. If a read-back disagrees with what you asked for, tell Ozzy.

## Limitations
- Workflow verification still compares document *content*; formatting is verified through each action's own read-back.
- Formulas use US English syntax (comma separators). Dynamic-array functions (FILTER, SORT, UNIQUE), named ranges, 3D references and structured table references are not supported.
- Word style names are tried in English first, then by built-in style ID for other languages.
- `text_match` formats characters only. Paragraph-level formatting needs a paragraph, selection or document target.
- Opened files are never saved in place by Ozzy. Use Office's own Save, or `office_save_new` for a new copy.

## Rollback
`git revert` the Stage 8 commit, or delete the two new modules and restore the changed files. Stage 7 behaviour is unchanged otherwise.
