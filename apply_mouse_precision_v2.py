from pathlib import Path
import shutil
from datetime import datetime
import re

PROJECT = Path.cwd()
module = PROJECT / "computer_control.py"
server = PROJECT / "server.py"
tests = PROJECT / "tests" / "test_computer_control.py"
if not all(path.is_file() for path in (module, server, tests)):
    raise SystemExit("Run this script from the Ozzy project root (computer_control.py, server.py, and tests/ must exist).")

source = module.read_text(encoding="utf-8")
server_source = server.read_text(encoding="utf-8")
test_source = tests.read_text(encoding="utf-8")
if "MOUSE_PRECISION_V2_POINTER_MARKER" in source and "MOUSE_PRECISION_V2_VISUAL_FLOW" in server_source:
    print("Mouse precision v2 already appears to be installed; no files changed.")
    raise SystemExit(0)
if "def _coordinate_space_size()" not in source or "_LAST_SCREENSHOT_SIZE = (int(original_width), int(original_height))" not in source:
    raise SystemExit("The v1 mouse precision hotfix was not found. Install the previous mouse precision hotfix first.")

# Use exact anchors and validate every edit before writing anything.
required_server_text = (
    "- For visual tasks, call get_active_window and capture_screen first when needed. Screenshot pixels may be scaled: use the capture_screen result scale_x and scale_y to convert screenshot positions into physical screen pixels before move_mouse/click_mouse. The primary display origin is top-left.\n"
    "- Prefer small, verifiable steps. After a click or shortcut, inspect the screen again before assuming the action succeeded.\n"
)
if required_server_text not in server_source:
    raise SystemExit("Could not find the expected PC CONTROL instruction block in server.py; no files changed.")

# Add a pure conversion helper after the v1 coordinate-space helper.
helper_anchor = '''def _coordinate_space_size() -> tuple[int, int]:
    """Use the exact screenshot dimensions Gemini was shown, when available."""
    if _LAST_SCREENSHOT_SIZE is not None:
        return _LAST_SCREENSHOT_SIZE
    return _screen_size()
'''
helper_replacement = helper_anchor + '''

# MOUSE_PRECISION_V2_POINTER_MARKER
def _pointer_to_screenshot(
    x: Any,
    y: Any,
    screenshot_size: tuple[int, int],
    automation_size: tuple[int, int],
) -> tuple[int, int]:
    """Convert the live PyAutoGUI pointer position into native screenshot pixels."""
    screenshot_width, screenshot_height = screenshot_size
    automation_width, automation_height = automation_size
    if min(screenshot_width, screenshot_height, automation_width, automation_height) <= 0:
        raise RuntimeError("Invalid screen dimensions; capture a fresh screenshot and try again.")
    point_x = round(int(x) * screenshot_width / automation_width)
    point_y = round(int(y) * screenshot_height / automation_height)
    return (
        min(max(point_x, 0), screenshot_width - 1),
        min(max(point_y, 0), screenshot_height - 1),
    )
'''
if helper_anchor not in source:
    raise SystemExit("Could not find the v1 coordinate-space helper; no files changed.")
source = source.replace(helper_anchor, helper_replacement, 1)

capture_anchor = '''    _LAST_SCREENSHOT_SIZE = (int(original_width), int(original_height))
    image.thumbnail((1440, 900))
'''
capture_replacement = '''    _LAST_SCREENSHOT_SIZE = (int(original_width), int(original_height))

    # Mark the real pointer position in the temporary screenshot sent to Gemini.
    # PyAutoGUI screenshots do not consistently include the Windows cursor, so
    # draw a small crosshair ourselves. This image remains in memory only.
    pointer_screenshot_x = None
    pointer_screenshot_y = None
    automation_pointer_x = None
    automation_pointer_y = None
    pointer_marker_drawn = False
    try:
        automation_width, automation_height = _screen_size()
        automation_pointer_x, automation_pointer_y = pyautogui.position()
        pointer_screenshot_x, pointer_screenshot_y = _pointer_to_screenshot(
            automation_pointer_x,
            automation_pointer_y,
            (int(original_width), int(original_height)),
            (automation_width, automation_height),
        )
        from PIL import ImageDraw

        draw = ImageDraw.Draw(image)
        radius = max(8, round(min(original_width, original_height) / 150))
        center_x, center_y = pointer_screenshot_x, pointer_screenshot_y
        # White halo keeps the red marker visible on both light and dark areas.
        draw.ellipse(
            (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
            outline=(255, 255, 255),
            width=max(4, radius // 3),
        )
        draw.ellipse(
            (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
            outline=(255, 35, 35),
            width=max(2, radius // 5),
        )
        arm = radius + max(5, radius // 2)
        draw.line((center_x - arm, center_y, center_x + arm, center_y), fill=(255, 35, 35), width=max(2, radius // 5))
        draw.line((center_x, center_y - arm, center_x, center_y + arm), fill=(255, 35, 35), width=max(2, radius // 5))
        draw.ellipse((center_x - 2, center_y - 2, center_x + 2, center_y + 2), fill=(255, 35, 35))
        pointer_marker_drawn = True
    except Exception:
        # Screenshot capture must remain available even if cursor annotation fails.
        pointer_marker_drawn = False

    image.thumbnail((1440, 900))
'''
if capture_anchor not in source:
    raise SystemExit("Could not find the v1 screenshot-size capture block; no files changed.")
source = source.replace(capture_anchor, capture_replacement, 1)

return_anchor = '''        "scale_x": float(original_width / image.width),
        "scale_y": float(original_height / image.height),
        "image_bytes": output.getvalue(),
'''
return_replacement = '''        "scale_x": float(original_width / image.width),
        "scale_y": float(original_height / image.height),
        "pointer_marker_drawn": bool(pointer_marker_drawn),
        "pointer_x": pointer_screenshot_x,
        "pointer_y": pointer_screenshot_y,
        "automation_pointer_x": int(automation_pointer_x) if automation_pointer_x is not None else None,
        "automation_pointer_y": int(automation_pointer_y) if automation_pointer_y is not None else None,
        "image_bytes": output.getvalue(),
'''
if return_anchor not in source:
    raise SystemExit("Could not find the screenshot response fields; no files changed.")
source = source.replace(return_anchor, return_replacement, 1)

# Make the action result honest: it verifies coordinates, not the semantic target.
old_move_message = '"message": f"Moved pointer to screenshot pixel ({target_x}, {target_y}); verified at ({actual_screen_x}, {actual_screen_y}).",'
new_move_message = '"message": f"Pointer reached screenshot pixel ({actual_screen_x}, {actual_screen_y}); coordinate verified, but the intended visual target is not yet verified. Capture a fresh screenshot and inspect the cursor crosshair.",'
if old_move_message not in source:
    raise SystemExit("Could not find the v1 move_mouse success message; no files changed.")
source = source.replace(old_move_message, new_move_message, 1)

# Update the tool guidance and system-level behavior in server.py.
server_source = server_source.replace(
    required_server_text,
    '''- For visual tasks, call get_active_window and capture_screen first when needed. Screenshot pixels may be scaled: use the capture_screen result scale_x and scale_y to convert positions in the displayed screenshot into native screenshot pixels exactly once. The primary display origin is top-left.\n'''
    '''- The capture_screen image includes a red crosshair with a white halo showing the actual pointer center when pointer_marker_drawn is true. Use that marker to compare the cursor with the intended target; do not assume the cursor is visible without this marker.\n'''
    '''- MOUSE_PRECISION_V2_VISUAL_FLOW: For a visual target, NEVER click immediately from the first screenshot. First call move_mouse to the estimated center, then call capture_screen again. Inspect the new crosshair relative to the target. If it is off-center, calculate the visual offset in the displayed screenshot, convert that offset with scale_x/scale_y exactly once, and call move_mouse with the corrected native screenshot coordinates. Repeat at most twice. Only then call click_mouse using the refined coordinates. If the marker is missing, the target is tiny/ambiguous, or the cursor cannot be positioned confidently, use semantic browser/Windows automation or ask the user.\n'''
    '''- A successful move_mouse result confirms only that the pointer reached the requested coordinate; it does NOT confirm that the coordinate is on the intended button or icon. Never say "I moved to the target" until a fresh screenshot shows the crosshair centered on it. After clicking, capture the screen again and verify the visible result before reporting success.\n''',
    1,
)

# Tool descriptions differ slightly between project revisions. Replace descriptions
# by the FunctionDeclaration name rather than requiring a byte-for-byte sentence match.
def update_tool_description(text: str, tool_name: str, description: str) -> tuple[str, bool]:
    pattern = rf'(name="{re.escape(tool_name)}",\s*description=")(.*?)("(?=\s*,\s*parameters=))'
    updated, count = re.subn(
        pattern,
        lambda match: match.group(1) + description + match.group(3),
        text,
        count=1,
        flags=re.DOTALL,
    )
    return updated, count == 1

new_capture_desc = 'Capture the primary desktop as a temporary image and provide it to Gemini for visual inspection. The image is not saved to disk. When available, a red crosshair with a white halo marks the actual cursor center; pointer_marker_drawn and pointer_x/pointer_y report whether and where it was drawn. The result includes scale_x and scale_y for converting displayed-image coordinates to native screenshot pixels. Requires the user\'s PC Control opt-in.'
new_move_desc = 'Move the desktop pointer to a coordinate from the most recent screenshot. Use native screenshot pixels after applying scale_x/scale_y exactly once. This verifies pointer position only, not that the intended visual target was identified correctly. For visual targets, move first and capture_screen again to inspect the cursor crosshair before clicking. Requires PC Control opt-in.'
new_click_desc = 'Click at a refined coordinate from the most recent screenshot. For visual targets, first move the pointer, capture_screen again, and inspect the crosshair; adjust the coordinate if needed before calling this tool. Only left/right click and single/double click are supported. Do not use for purchases, sending/publishing, deletion, login/security, or irreversible confirmation actions. Requires PC Control opt-in.'

server_source, capture_desc_updated = update_tool_description(server_source, "capture_screen", new_capture_desc)
server_source, move_desc_updated = update_tool_description(server_source, "move_mouse", new_move_desc)
server_source, click_desc_updated = update_tool_description(server_source, "click_mouse", new_click_desc)
if not capture_desc_updated:
    print("Note: capture_screen tool description was not found in its expected declaration format; system instruction update will still apply.")
if not move_desc_updated:
    print("Note: move_mouse tool description was not found in its expected declaration format; system instruction update will still apply.")
if not click_desc_updated:
    print("Note: click_mouse tool description was not found in its expected declaration format; system instruction update will still apply.")

# Add regression tests for pointer coordinate conversion.
if "test_pointer_position_maps_to_native_screenshot_pixels" not in test_source:
    test_insert = '''\n    def test_pointer_position_maps_to_native_screenshot_pixels(self):
        self.assertEqual(
            computer_control._pointer_to_screenshot(500, 250, (2000, 1000), (1000, 500)),
            (1000, 500),
        )

    def test_pointer_position_mapping_preserves_equal_dimensions(self):
        self.assertEqual(
            computer_control._pointer_to_screenshot(640, 360, (1280, 720), (1280, 720)),
            (640, 360),
        )

'''
    test_marker = 'if __name__ == "__main__":'
    if test_marker not in test_source:
        raise SystemExit("Could not find the test insertion point; no files changed.")
    test_source = test_source.replace(test_marker, test_insert + test_marker, 1)

# Validate all edited content before touching the project.
markers = [
    "MOUSE_PRECISION_V2_POINTER_MARKER",
    '"pointer_marker_drawn": bool(pointer_marker_drawn)',
    "intended visual target is not yet verified",
]
if not all(marker in source for marker in markers):
    raise SystemExit("Internal validation failed for computer_control.py; no files changed.")
if "MOUSE_PRECISION_V2_VISUAL_FLOW" not in server_source or "red crosshair" not in server_source:
    raise SystemExit("Internal validation failed for server.py; no files changed.")

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backup_dir = PROJECT / "backups" / f"mouse-precision-v2-{stamp}"
backup_dir.mkdir(parents=True, exist_ok=True)
shutil.copy2(module, backup_dir / "computer_control.py")
shutil.copy2(server, backup_dir / "server.py")
shutil.copy2(tests, backup_dir / "test_computer_control.py")

module.write_text(source, encoding="utf-8")
server.write_text(server_source, encoding="utf-8")
tests.write_text(test_source, encoding="utf-8")
print("Mouse precision v2 applied.")
print(f"Backups: {backup_dir}")
print("Fresh screenshots now show a red cursor crosshair when annotation is available.")
print("The system instructions require move -> screenshot -> inspect -> adjust -> click for visual targets.")
print("The move result no longer claims that the intended target was reached.")
