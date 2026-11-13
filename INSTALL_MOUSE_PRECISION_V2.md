# Ozzy Mouse Precision v2

This update addresses the remaining case where Windows moves the pointer correctly to the coordinates Ozzy requested, but Ozzy's visual estimate is slightly off the intended control.

## What changes

- Each fresh desktop screenshot gets a small red crosshair with a white halo at the actual cursor position, when cursor annotation is available.
- `capture_screen` reports the pointer position and whether the marker was drawn.
- Ozzy is instructed to use a visual two-step targeting flow: move, capture again, inspect the crosshair, adjust if necessary, then click.
- The `move_mouse` result explicitly says that reaching a coordinate does not prove the intended button/icon was targeted.
- Adds pure coordinate-conversion tests. No new packages are required; the existing PyAutoGUI installation already depends on Pillow.

## Install

The fixed installer locates tool descriptions by their function names, so it works across slightly different `server.py` wording. It also treats description updates as optional; the main visual workflow instructions are still applied.

1. Close Ozzy completely.
2. Extract this ZIP into the Ozzy project root (the folder containing `computer_control.py`, `server.py`, and `tests`). When Windows asks, replace the older `apply_mouse_precision_v2.py` with the one from this ZIP.
3. Open PowerShell in that project root and run:

```powershell
.\.venv\Scripts\python.exe .\apply_mouse_precision_v2.py
```

The earlier installer may have stopped with “Could not find the capture_screen tool description”; that validation happened before any project files were changed. This fixed installer resolves that mismatch.

The installer creates backups under `backups\mouse-precision-v2-<timestamp>` before changing files. It does not edit Stage 2 browser, Stage 3 Windows UI Automation, or Stage 4 workflow/file-action modules.

## Test and restart

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_computer_control.py" -v
.\.venv\Scripts\python.exe -m py_compile computer_control.py server.py
npm start
```

## Test pointer accuracy

Ask Ozzy to move the cursor to the center of a reasonably large visible icon **without clicking**. Ask it to capture the screen and check the red crosshair. The crosshair should be directly over the intended point. Then test with a normal button in Notepad or File Explorer.

The marker is only an aid for visual correction; it is not computer vision or automatic object detection. Tiny or ambiguous targets should use browser/Windows semantic automation where available.
