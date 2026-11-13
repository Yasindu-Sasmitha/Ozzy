# Ozzy Mouse Precision Hotfix

This patch calibrates screenshot pixel coordinates against the coordinate dimensions exposed by PyAutoGUI. It also verifies the pointer position before clicking and cancels the click if the pointer misses the target by more than two automation pixels.

## Install

1. Close Ozzy completely.
2. Extract this ZIP into the Ozzy project root (the folder containing `computer_control.py`).
3. Open PowerShell in that folder.
4. Run:

```powershell
.\.venv\Scripts\python.exe .\apply_mouse_precision_hotfix.py
```

The script backs up `computer_control.py` and `tests\test_computer_control.py` under `backups\mouse-precision-<timestamp>` before editing them. It does not change dependencies, Stage 2 browser automation, Stage 3 UI Automation, or Stage 4 file operations.

## Test

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_computer_control.py" -v
.\.venv\Scripts\python.exe -m py_compile computer_control.py
```

Then restart Ozzy with `npm start`.

## Important coordinate behaviour

Take a fresh screenshot before a visual click. Gemini should identify the target in the screenshot, convert the resized-image position using the returned `scale_x` and `scale_y` exactly once, and pass the resulting native screenshot pixel coordinates to `move_mouse` or `click_mouse`. The backend then maps those pixels into PyAutoGUI's coordinate space, which can differ under Windows display scaling.

If Windows display resolution or scaling changes, capture a new screenshot before the next coordinate action. A click is cancelled if the pointer position cannot be verified within two PyAutoGUI pixels of the calibrated target.
