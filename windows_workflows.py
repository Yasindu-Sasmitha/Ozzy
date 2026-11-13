"""Bounded, consent-gated helpers for reliable multi-step Windows UI workflows.

Stage 4 builds on windows_automation.py. It does not launch programs, read
editable values, execute commands, or mutate files directly. All polling is
short, bounded, and cancelled when the user disables PC Control.
"""
from __future__ import annotations

import time
from typing import Any

import windows_automation as ui

MAX_WAIT_SECONDS = 15
POLL_INTERVAL_SECONDS = 0.25
MAX_TITLE_LENGTH = 180

STATE_CONTROL_TYPES = {
    "Button", "MenuItem", "TabItem", "ListItem", "TreeItem", "Hyperlink",
    "SplitButton", "Document", "Pane", "Edit", "ComboBox", "Tab", "CheckBox", "RadioButton",
}


def _validate_timeout(value: Any) -> int:
    if value is None:
        return 5
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("timeout_seconds must be a whole number from 1 to 15.")
    if value < 1 or value > MAX_WAIT_SECONDS:
        raise ValueError("timeout_seconds must be from 1 to 15 seconds.")
    return value


def _validate_title(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("title must be a string.")
    title = value.strip()
    if not title or len(title) > MAX_TITLE_LENGTH:
        raise ValueError("Provide a window title from 1 to 180 characters.")
    return title


def _window_matches(actual: str, wanted: str, match: str) -> bool:
    actual_folded = actual.casefold()
    wanted_folded = wanted.casefold()
    if match == "exact":
        return actual_folded == wanted_folded
    if match == "contains":
        return wanted_folded in actual_folded
    raise ValueError("match must be 'exact' or 'contains'.")


def _find_window(desktop: Any, title: str, match: str) -> Any | None:
    matches = []
    for window in desktop.windows():
        try:
            if not window.is_visible():
                continue
            window_title = ui._window_title(window)
            if _window_matches(window_title, title, match):
                matches.append(window)
        except Exception:
            continue
    if len(matches) > 1:
        titles = [ui._window_title(item) for item in matches[:8]]
        raise RuntimeError(
            f"More than one visible window matched that title: {titles}. "
            "Use an exact title or windows_list_windows to identify the target."
        )
    return matches[0] if matches else None


def _wait_for_window(args: dict[str, Any], desktop: Any) -> dict[str, Any]:
    title = _validate_title(args.get("title"))
    match = str(args.get("match", "exact")).strip().lower()
    if match not in {"exact", "contains"}:
        raise ValueError("match must be 'exact' or 'contains'.")
    timeout = _validate_timeout(args.get("timeout_seconds"))
    deadline = time.monotonic() + timeout

    while True:
        ui._check_enabled()
        window = _find_window(desktop, title, match)
        if window is not None:
            return {
                "ok": True,
                "window_handle": str(int(window.handle)),
                "window_title": ui._window_title(window),
                "waited_seconds": round(max(0.0, timeout - max(0.0, deadline - time.monotonic())), 2),
                "message": "The requested visible application window is available.",
            }
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"No visible window matched '{title}' within {timeout} seconds.")
        time.sleep(min(POLL_INTERVAL_SECONDS, remaining))


def _is_retryable_control_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "no matching visible control was found" in message
        or "not both visible and enabled" in message
    )


def _wait_for_control(args: dict[str, Any], desktop: Any) -> dict[str, Any]:
    # Resolve the target window once. A modal dialog should be passed by its
    # handle from windows_wait_for_window instead of relying on focus changes.
    window = ui._resolve_window(desktop, args.get("window_handle"))
    timeout = _validate_timeout(args.get("timeout_seconds"))
    name = str(args.get("name") or "").strip()
    automation_id = str(args.get("automation_id") or "").strip()
    if not name and not automation_id:
        raise ValueError("Provide a control name or automation_id from windows_inspect.")
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None

    while True:
        ui._check_enabled()
        try:
            control, metadata = ui._find_control(
                window,
                {
                    "name": name,
                    "automation_id": automation_id,
                    "control_type": args.get("control_type", ""),
                },
                STATE_CONTROL_TYPES,
            )
            return {
                "ok": True,
                "window_handle": str(int(window.handle)),
                "window_title": ui._window_title(window),
                "control": {
                    "name": metadata.get("name"),
                    "automation_id": metadata.get("automation_id"),
                    "control_type": metadata.get("control_type"),
                    "enabled": metadata.get("enabled"),
                    "visible": metadata.get("visible"),
                },
                "message": "The requested visible, enabled control is available.",
            }
        except RuntimeError as exc:
            if not _is_retryable_control_error(exc):
                raise
            last_error = exc
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            detail = f" Last status: {last_error}" if last_error else ""
            raise TimeoutError(
                f"Control '{name or automation_id}' did not become visible and enabled "
                f"within {timeout} seconds.{detail}"
            ) from last_error
        time.sleep(min(POLL_INTERVAL_SECONDS, remaining))


def _get_control_state(args: dict[str, Any], desktop: Any) -> dict[str, Any]:
    window = ui._resolve_window(desktop, args.get("window_handle"))
    control, metadata = ui._find_control(window, args, STATE_CONTROL_TYPES)
    control_type = metadata["control_type"]
    state: dict[str, Any] = {
        "name": metadata.get("name"),
        "automation_id": metadata.get("automation_id"),
        "control_type": control_type,
        "enabled": bool(metadata.get("enabled")),
        "visible": bool(metadata.get("visible")),
    }

    # Only read interaction state. Never read Edit/Document text or field values.
    if control_type == "CheckBox":
        try:
            toggle_state = int(control.get_toggle_state())
            state["toggle_state"] = {
                0: "unchecked", 1: "checked", 2: "indeterminate",
            }.get(toggle_state, "unknown")
        except Exception:
            state["toggle_state"] = "unavailable"
    elif control_type in {"RadioButton", "TabItem", "ListItem", "TreeItem"}:
        try:
            state["selected"] = bool(control.is_selected())
        except Exception:
            state["selected"] = None

    try:
        focused = ui._safe_value(control, "has_keyboard_focus", None)
        if focused is not None:
            state["has_keyboard_focus"] = bool(focused)
    except Exception:
        pass

    return {
        "ok": True,
        "window_handle": str(int(window.handle)),
        "window_title": ui._window_title(window),
        "control_state": state,
        "message": "Control interaction state checked. Text field values and document contents were not read.",
    }


def execute_action(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Dispatch bounded Stage 4 wait/state tools using the existing PC consent."""
    ui._check_enabled()
    payload = args if isinstance(args, dict) else {}
    actions = {
        "windows_wait_for_window": _wait_for_window,
        "windows_wait_for_control": _wait_for_control,
        "windows_get_control_state": _get_control_state,
    }
    action = actions.get(name)
    if action is None:
        raise ValueError(f"Unsupported Windows workflow action: {name}")
    return ui._run_with_desktop(lambda desktop: action(payload, desktop))
