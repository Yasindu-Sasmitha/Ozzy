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
    pyautogui = _pyautogui()
    width, height = pyautogui.size()
    return int(width), int(height)


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
        "image_bytes": output.getvalue(),
    }


def move_mouse(x: Any, y: Any) -> dict[str, Any]:
    _check_running()
    pyautogui = _pyautogui()
    width, height = _screen_size()
    target_x = _coordinate(x, "x", width)
    target_y = _coordinate(y, "y", height)
    pyautogui.moveTo(target_x, target_y, duration=0.18)
    _check_running()
    return {"ok": True, "message": f"Moved the pointer to ({target_x}, {target_y}).", "x": target_x, "y": target_y}


def click_mouse(x: Any, y: Any, button: str = "left", clicks: int = 1) -> dict[str, Any]:
    _check_running()
    pyautogui = _pyautogui()
    width, height = _screen_size()
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
    width, height = _screen_size()
    target_x = _coordinate(x, "x", width)
    target_y = _coordinate(y, "y", height)
    if isinstance(amount, bool) or not isinstance(amount, int) or amount == 0 or abs(amount) > 20:
        raise ValueError("amount must be a non-zero integer between -20 and 20.")
    pyautogui.moveTo(target_x, target_y, duration=0.08)
    pyautogui.scroll(amount, x=target_x, y=target_y)
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
