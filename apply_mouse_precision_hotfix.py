from pathlib import Path
import shutil
from datetime import datetime

ROOT = Path(__file__).resolve().parent
PROJECT = Path.cwd()
module = PROJECT / 'computer_control.py'
tests = PROJECT / 'tests' / 'test_computer_control.py'
if not module.is_file() or not tests.is_file():
    raise SystemExit('Run this script from the Ozzy project root (the folder containing computer_control.py and tests/).')

source = module.read_text(encoding='utf-8')
if 'def _map_screenshot_to_automation(' in source:
    print('Mouse precision hotfix already appears to be installed; no files changed.')
    raise SystemExit(0)

stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
backup_dir = PROJECT / 'backups' / f'mouse-precision-{stamp}'
backup_dir.mkdir(parents=True, exist_ok=True)
shutil.copy2(module, backup_dir / 'computer_control.py')
shutil.copy2(tests, backup_dir / 'test_computer_control.py')

source = source.replace(
    '_STOP_REQUESTED = threading.Event()\n',
    '_STOP_REQUESTED = threading.Event()\n# Native pixel dimensions of the most recent screenshot shown to Gemini.\n_LAST_SCREENSHOT_SIZE: tuple[int, int] | None = None\n'
)
source = source.replace(
    'def _screen_size() -> tuple[int, int]:\n    pyautogui = _pyautogui()\n    width, height = pyautogui.size()\n    return int(width), int(height)\n',
    '''def _screen_size() -> tuple[int, int]:
    """Return the coordinate dimensions exposed by PyAutoGUI on this Windows session."""
    pyautogui = _pyautogui()
    width, height = pyautogui.size()
    return int(width), int(height)


def _map_screenshot_to_automation(
    x: Any,
    y: Any,
    screenshot_size: tuple[int, int],
    automation_size: tuple[int, int],
) -> tuple[int, int]:
    """Map native screenshot pixels to PyAutoGUI coordinates (DPI-safe)."""
    screenshot_width, screenshot_height = screenshot_size
    automation_width, automation_height = automation_size
    if min(screenshot_width, screenshot_height, automation_width, automation_height) <= 0:
        raise RuntimeError("Invalid screen dimensions; capture a fresh screenshot and try again.")
    source_x = _coordinate(x, "x", screenshot_width)
    source_y = _coordinate(y, "y", screenshot_height)
    mapped_x = round(source_x * automation_width / screenshot_width)
    mapped_y = round(source_y * automation_height / screenshot_height)
    return (
        min(max(mapped_x, 0), automation_width - 1),
        min(max(mapped_y, 0), automation_height - 1),
    )


def _coordinate_space_size() -> tuple[int, int]:
    """Use the exact screenshot dimensions Gemini was shown, when available."""
    if _LAST_SCREENSHOT_SIZE is not None:
        return _LAST_SCREENSHOT_SIZE
    return _screen_size()
'''
)
source = source.replace(
    '    original_width, original_height = image.size\n    image.thumbnail((1440, 900))\n',
    '    original_width, original_height = image.size\n    global _LAST_SCREENSHOT_SIZE\n    _LAST_SCREENSHOT_SIZE = (int(original_width), int(original_height))\n    image.thumbnail((1440, 900))\n'
)
source = source.replace(
    '''    width, height = _screen_size()
    target_x = _coordinate(x, "x", width)
    target_y = _coordinate(y, "y", height)
    pyautogui.moveTo(target_x, target_y, duration=0.18)
    _check_running()
    return {"ok": True, "message": f"Moved the pointer to ({target_x}, {target_y}).", "x": target_x, "y": target_y}
''',
    '''    screenshot_size = _coordinate_space_size()
    automation_size = _screen_size()
    target_x = _coordinate(x, "x", screenshot_size[0])
    target_y = _coordinate(y, "y", screenshot_size[1])
    automation_x, automation_y = _map_screenshot_to_automation(
        target_x, target_y, screenshot_size, automation_size
    )
    pyautogui.moveTo(automation_x, automation_y, duration=0.18)
    _check_running()
    actual_x, actual_y = pyautogui.position()
    actual_screen_x = round(actual_x * screenshot_size[0] / automation_size[0])
    actual_screen_y = round(actual_y * screenshot_size[1] / automation_size[1])
    return {
        "ok": True,
        "message": f"Moved pointer to screenshot pixel ({target_x}, {target_y}); verified at ({actual_screen_x}, {actual_screen_y}).",
        "x": target_x, "y": target_y,
        "actual_x": actual_screen_x, "actual_y": actual_screen_y,
        "automation_x": int(actual_x), "automation_y": int(actual_y),
    }
'''
)
source = source.replace(
    '''    width, height = _screen_size()
    target_x = _coordinate(x, "x", width)
    target_y = _coordinate(y, "y", height)
    if button not in {"left", "right"}:
        raise ValueError("Only left and right mouse clicks are supported.")
    if isinstance(clicks, bool) or clicks not in {1, 2}:
        raise ValueError("clicks must be 1 or 2.")
    pyautogui.click(x=target_x, y=target_y, clicks=clicks, interval=0.12, button=button)
    _check_running()
    description = "double-clicked" if clicks == 2 else "clicked"
    return {"ok": True, "message": f"{description} at ({target_x}, {target_y}) with the {button} button."}
''',
    '''    screenshot_size = _coordinate_space_size()
    automation_size = _screen_size()
    target_x = _coordinate(x, "x", screenshot_size[0])
    target_y = _coordinate(y, "y", screenshot_size[1])
    if button not in {"left", "right"}:
        raise ValueError("Only left and right mouse clicks are supported.")
    if isinstance(clicks, bool) or clicks not in {1, 2}:
        raise ValueError("clicks must be 1 or 2.")
    automation_x, automation_y = _map_screenshot_to_automation(
        target_x, target_y, screenshot_size, automation_size
    )
    # Move first, then verify the actual pointer location before issuing a click.
    pyautogui.moveTo(automation_x, automation_y, duration=0.12)
    _check_running()
    actual_x, actual_y = pyautogui.position()
    if abs(int(actual_x) - automation_x) > 2 or abs(int(actual_y) - automation_y) > 2:
        raise RuntimeError(
            "Pointer did not reach the calibrated target; click cancelled for safety. "
            "Capture a fresh screenshot and retry."
        )
    _check_running()
    pyautogui.click(clicks=clicks, interval=0.12, button=button)
    _check_running()
    actual_screen_x = round(actual_x * screenshot_size[0] / automation_size[0])
    actual_screen_y = round(actual_y * screenshot_size[1] / automation_size[1])
    description = "double-clicked" if clicks == 2 else "clicked"
    return {
        "ok": True,
        "message": f"{description} at calibrated screenshot pixel ({actual_screen_x}, {actual_screen_y}) with the {button} button.",
        "x": target_x, "y": target_y,
        "actual_x": actual_screen_x, "actual_y": actual_screen_y,
        "automation_x": int(actual_x), "automation_y": int(actual_y),
    }
'''
)
source = source.replace(
    '''    width, height = _screen_size()
    target_x = _coordinate(x, "x", width)
    target_y = _coordinate(y, "y", height)
    if isinstance(amount, bool) or not isinstance(amount, int) or amount == 0 or abs(amount) > 20:
        raise ValueError("amount must be a non-zero integer between -20 and 20.")
    pyautogui.moveTo(target_x, target_y, duration=0.08)
    pyautogui.scroll(amount, x=target_x, y=target_y)
''',
    '''    screenshot_size = _coordinate_space_size()
    automation_size = _screen_size()
    target_x = _coordinate(x, "x", screenshot_size[0])
    target_y = _coordinate(y, "y", screenshot_size[1])
    if isinstance(amount, bool) or not isinstance(amount, int) or amount == 0 or abs(amount) > 20:
        raise ValueError("amount must be a non-zero integer between -20 and 20.")
    automation_x, automation_y = _map_screenshot_to_automation(
        target_x, target_y, screenshot_size, automation_size
    )
    pyautogui.moveTo(automation_x, automation_y, duration=0.08)
    pyautogui.scroll(amount, x=automation_x, y=automation_y)
'''
)

required_markers = [
    'def _map_screenshot_to_automation(',
    'pyautogui.click(clicks=clicks, interval=0.12, button=button)',
    '_LAST_SCREENSHOT_SIZE = (int(original_width), int(original_height))',
]
if not all(marker in source for marker in required_markers):
    raise SystemExit('Could not safely apply all coordinate-calibration edits. Backups were created; no source files were written.')

# Add pure coordinate-mapping regression tests without depending on a real desktop.
test_source = tests.read_text(encoding='utf-8')
if 'test_screenshot_coordinates_map_to_dpi_scaled_automation_coordinates' not in test_source:
    insertion = '''\n    def test_screenshot_coordinates_map_to_dpi_scaled_automation_coordinates(self):
        # Example: a 150% DPI-aware screenshot is larger than PyAutoGUI's logical space.
        self.assertEqual(
            computer_control._map_screenshot_to_automation(1500, 900, (3000, 1800), (2000, 1200)),
            (1000, 600),
        )

    def test_screenshot_coordinate_mapping_preserves_equal_dimensions(self):
        self.assertEqual(
            computer_control._map_screenshot_to_automation(640, 360, (1280, 720), (1280, 720)),
            (640, 360),
        )

    def test_screenshot_coordinate_mapping_rejects_out_of_bounds(self):
        with self.assertRaises(ValueError):
            computer_control._map_screenshot_to_automation(1280, 0, (1280, 720), (1280, 720))

'''
    marker = 'if __name__ == "__main__":'
    if marker not in test_source:
        raise SystemExit('Could not find test insertion point; module backup is available.')
    test_source = test_source.replace(marker, insertion + '\n' + marker, 1)

module.write_text(source, encoding='utf-8')
tests.write_text(test_source, encoding='utf-8')
print('Mouse precision hotfix applied.')
print(f'Backups: {backup_dir}')
print('Coordinate inputs now use the most recent screenshot pixel dimensions and are mapped to PyAutoGUI coordinates.')
print('Clicks now move first, verify the pointer position, and cancel if the pointer misses the calibrated target.')
