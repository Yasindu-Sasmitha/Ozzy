"""Restricted Windows desktop-control primitives for Ozzy.

This module deliberately exposes a small allow-list of actions. It does not run
shell commands, launch arbitrary executables, delete files, or access credentials.
PyAutoGUI is imported lazily so Ozzy can still start when optional control
packages have not yet been installed.
"""
from __future__ import annotations

from io import BytesIO
import os
import threading
from typing import Any

_STOP_REQUESTED = threading.Event()
# Native pixel dimensions of the most recent screenshot shown to Gemini.
_LAST_SCREENSHOT_SIZE: tuple[int, int] | None = None

# Exact shortcuts only. Arbitrary key chords are intentionally not accepted.
ALLOWED_SHORTCUTS = {
    "ctrl+r",          # refresh
    "f5",              # refresh
    "f12",             # browser developer tools
    "ctrl+shift+i",    # browser developer tools
    "ctrl+l",          # browser address bar
    "ctrl+t",          # new browser tab
    "ctrl+n",          # new window/document
    "ctrl+o",          # open dialog
    "ctrl+f",          # find
    "ctrl+s",          # save current document
    "ctrl+a",          # select all
    "ctrl+c",          # copy selection
    "ctrl+z",          # undo
    "ctrl+y",          # redo
    "ctrl+b",          # bold in editors
    "ctrl+i",          # italic in editors
    "ctrl+u",          # underline in editors
    "alt+tab",         # switch window
    "win",             # open Start menu/search
    "enter",
    "esc",
    "tab",
    "space",
    "backspace",
    "up",
    "down",
    "left",
    "right",
    "home",
    "end",
    "pageup",
    "pagedown",
}


def resume_actions() -> None:
    """Clear the emergency-stop latch after the user explicitly enables control."""
    _STOP_REQUESTED.clear()


def stop_current_action() -> None:
    """Request cancellation of a currently streaming type operation and block new work."""
    _STOP_REQUESTED.set()


def _check_running() -> None:
    if _STOP_REQUESTED.is_set():
        raise RuntimeError("PC control was stopped by the user.")


def _require_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("PC control v1 currently supports Windows 10/11 only.")


def _pyautogui():
    _require_windows()
    try:
        import pyautogui
    except ImportError as exc:
        raise RuntimeError(
            "PC-control dependencies are missing. Run: python -m pip install -r requirements.txt"
        ) from exc
    # PyAutoGUI's corner fail-safe remains enabled as a physical emergency stop.
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.04
    return pyautogui


def _screen_size() -> tuple[int, int]:
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


def _coordinate(value: Any, name: str, limit: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number.")
    number = int(value)
    if number < 0 or number >= limit:
        raise ValueError(f"{name} must be between 0 and {limit - 1}.")
    return number


def get_active_window() -> dict[str, Any]:
    _check_running()
    _require_windows()
    try:
        import pygetwindow
    except ImportError as exc:
        raise RuntimeError("pygetwindow is missing. Run: python -m pip install -r requirements.txt") from exc

    window = pygetwindow.getActiveWindow()
    if window is None:
        return {"ok": False, "message": "Windows did not report an active application window."}
    return {
        "ok": True,
        "title": str(window.title or "(untitled window)")[:240],
        "left": int(window.left),
        "top": int(window.top),
        "width": int(window.width),
        "height": int(window.height),
        "message": "Active window information retrieved.",
    }


def capture_screen() -> dict[str, Any]:
    """Capture a downsized JPEG in memory; never writes a screenshot to disk."""
    _check_running()
    pyautogui = _pyautogui()
    image = pyautogui.screenshot()
    original_width, original_height = image.size
    global _LAST_SCREENSHOT_SIZE
    _LAST_SCREENSHOT_SIZE = (int(original_width), int(original_height))

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
    output = BytesIO()
    image.convert("RGB").save(output, format="JPEG", quality=72, optimize=True)
    _check_running()
    return {
        "ok": True,
        "message": "Screen captured and sent to Gemini for visual inspection. The image was not saved to disk.",
        "width": int(original_width),
        "height": int(original_height),
        "image_width": int(image.width),
        "image_height": int(image.height),
        "scale_x": float(original_width / image.width),
        "scale_y": float(original_height / image.height),
        "pointer_marker_drawn": bool(pointer_marker_drawn),
        "pointer_x": pointer_screenshot_x,
        "pointer_y": pointer_screenshot_y,
        "automation_pointer_x": int(automation_pointer_x) if automation_pointer_x is not None else None,
        "automation_pointer_y": int(automation_pointer_y) if automation_pointer_y is not None else None,
        "image_bytes": output.getvalue(),
    }


def move_mouse(x: Any, y: Any) -> dict[str, Any]:
    _check_running()
    pyautogui = _pyautogui()
    screenshot_size = _coordinate_space_size()
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
        "message": f"Pointer reached screenshot pixel ({actual_screen_x}, {actual_screen_y}); coordinate verified, but the intended visual target is not yet verified. Capture a fresh screenshot and inspect the cursor crosshair.",
        "x": target_x, "y": target_y,
        "actual_x": actual_screen_x, "actual_y": actual_screen_y,
        "automation_x": int(actual_x), "automation_y": int(actual_y),
    }


def click_mouse(x: Any, y: Any, button: str = "left", clicks: int = 1) -> dict[str, Any]:
    _check_running()
    pyautogui = _pyautogui()
    screenshot_size = _coordinate_space_size()
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


def normalize_shortcut(shortcut: str) -> str:
    normalized = str(shortcut).strip().lower().replace(" ", "")
    if normalized not in ALLOWED_SHORTCUTS:
        raise ValueError(
            "That shortcut is not allowed. Use one of the documented safe shortcuts, such as ctrl+r or f12."
        )
    return normalized


def press_shortcut(shortcut: str) -> dict[str, Any]:
    _check_running()
    normalized = normalize_shortcut(shortcut)
    pyautogui = _pyautogui()
    if "+" in normalized:
        pyautogui.hotkey(*normalized.split("+"))
    else:
        pyautogui.press(normalized)
    _check_running()
    return {"ok": True, "message": f"Pressed {normalized}.", "shortcut": normalized}


def validate_text(text: Any) -> str:
    """Validate input before any OS automation module is loaded."""
    if not isinstance(text, str):
        raise ValueError("text must be a string.")
    if not text:
        return text
    if len(text) > 4000:
        raise ValueError("For safety, type_text is limited to 4,000 characters per call.")
    if not text.isascii():
        raise ValueError(
            "This first version supports ASCII text only. Non-ASCII typing needs a separate Unicode-safe input path."
        )
    if "\x00" in text:
        raise ValueError("Text contains an unsupported null character.")
    return text


def type_text(text: Any) -> dict[str, Any]:
    """Type bounded plain text, checking the emergency stop between small chunks."""
    _check_running()
    text = validate_text(text)
    if not text:
        return {"ok": True, "message": "There was no text to type.", "characters": 0}
    pyautogui = _pyautogui()
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    typed = 0
    for line_index, line in enumerate(lines):
        for offset in range(0, len(line), 48):
            _check_running()
            chunk = line[offset:offset + 48]
            pyautogui.write(chunk, interval=0.001)
            typed += len(chunk)
        if line_index < len(lines) - 1:
            _check_running()
            pyautogui.press("enter")
            typed += 1
    _check_running()
    return {"ok": True, "message": f"Typed {typed} characters.", "characters": typed}


def scroll_screen(x: Any, y: Any, amount: Any) -> dict[str, Any]:
    _check_running()
    pyautogui = _pyautogui()
    screenshot_size = _coordinate_space_size()
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
    _check_running()
    direction = "up" if amount > 0 else "down"
    return {"ok": True, "message": f"Scrolled {direction} by {abs(amount)} step(s)."}


def execute_action(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Dispatch only the explicitly supported PC-control tools."""
    _check_running()
    args = args or {}
    if name == "get_active_window":
        return get_active_window()
    if name == "capture_screen":
        return capture_screen()
    if name == "move_mouse":
        return move_mouse(args.get("x"), args.get("y"))
    if name == "click_mouse":
        return click_mouse(args.get("x"), args.get("y"), args.get("button", "left"), args.get("clicks", 1))
    if name == "press_shortcut":
        return press_shortcut(args.get("shortcut", ""))
    if name == "type_text":
        return type_text(args.get("text", ""))
    if name == "scroll_screen":
        return scroll_screen(args.get("x"), args.get("y"), args.get("amount"))
    raise ValueError(f"Unsupported PC-control action: {name}")
