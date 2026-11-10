"""Consent-gated Windows UI Automation for Ozzy.

This module uses pywinauto's Microsoft UI Automation (UIA) backend to inspect
and operate ordinary controls in the currently running Windows applications.
It does not launch processes, execute commands, close applications, or read
editable control values during inspection.
"""
from __future__ import annotations

import re
import sys
import threading
from typing import Any

_DISABLED = threading.Event()
_DISABLED.set()

MAX_WINDOWS = 40
MAX_CONTROLS = 120
MAX_TEXT_LENGTH = 3000

SENSITIVE_INPUT = re.compile(
    r"(\b(api[_ -]?key|password|passwd|passcode|secret[_ -]?key|access[_ -]?token|refresh[_ -]?token)\b\s*(is|=|:)\s*\S+|"
    r"\bAIza[0-9A-Za-z_\-]{25,}\b|\bsk-[A-Za-z0-9_-]{20,}\b)",
    re.IGNORECASE,
)

SENSITIVE_CONTROL = re.compile(
    r"(password|passwd|passcode|pin code|one.?time.?code|otp|verification.?code|"
    r"security.?(code|token)|api.?key|access.?key|access.?token|refresh.?token|private.?key|ssh.?key|oauth.?token|secret|credential|"
    r"credit.?card|debit.?card|card.?number|\bcvv\b|\bcvc\b|\biban\b|"
    r"routing.?number|account.?number|bank.?account|swift.?code|sort.?code|social.?security|\bssn\b|"
    r"cc-number|cc-csc|cc-exp)",
    re.IGNORECASE,
)

HIGH_IMPACT_CONTROL = re.compile(
    r"(delete|remove|send|publish|\bpost\b|purchase|\bbuy\b|checkout|payment|"
    r"transfer|approve|unsubscribe|shut.?down|restart|install|uninstall|factory.?reset|format.?drive|"
    r"overwrite|replace.?file|empty.?recycle|empty.?trash|clear.?all|"
    r"change.?password|manage.?credentials|admin(istrator)?|security.?settings)",
    re.IGNORECASE,
)

CLICKABLE_TYPES = {
    "Button", "MenuItem", "TabItem", "ListItem", "TreeItem", "Hyperlink",
    "SplitButton", "Document", "Pane",
}


def resume_actions() -> None:
    """Enable UIA calls after the user enables PC Control for this session."""
    _DISABLED.clear()


def stop_actions() -> None:
    """Block subsequent UIA calls. An in-flight Windows provider call may finish."""
    _DISABLED.set()


def _check_enabled() -> None:
    if _DISABLED.is_set():
        raise RuntimeError("Windows UI Automation is disabled. Enable PC Control in Ozzy's Advanced Options first.")


def _require_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError("Windows UI Automation is available only on Windows 10/11.")


def validate_window_handle(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("window_handle must be a positive window handle returned by windows_list_windows.")
    try:
        handle = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError("window_handle must be a positive window handle returned by windows_list_windows.") from None
    if handle <= 0 or handle > 2**64 - 1:
        raise ValueError("window_handle must be a positive window handle returned by windows_list_windows.")
    return handle


def validate_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Text must be a string.")
    if len(value) > MAX_TEXT_LENGTH:
        raise ValueError(f"Windows text input is limited to {MAX_TEXT_LENGTH} characters per action.")
    if "\x00" in value:
        raise ValueError("Text contains an invalid null character.")
    if SENSITIVE_INPUT.search(value):
        raise PermissionError("Text that appears to contain a password, API key, access token or private secret cannot be entered by Ozzy.")
    digits = re.sub(r"\D", "", value)
    if 13 <= len(digits) <= 19 and re.search(r"\b(card|credit|debit|cvv|cvc)\b", value, re.IGNORECASE):
        raise PermissionError("Payment-card details cannot be entered by Ozzy.")
    return value


def is_sensitive_control(metadata: dict[str, Any]) -> bool:
    values = " ".join(
        str(metadata.get(key) or "")
        for key in ("name", "automation_id", "control_type", "label", "help_text")
    )
    return bool(SENSITIVE_CONTROL.search(values))


def is_high_impact_control(metadata: dict[str, Any]) -> bool:
    values = " ".join(str(metadata.get(key) or "") for key in ("name", "automation_id"))
    return bool(HIGH_IMPACT_CONTROL.search(values))


def _safe_value(obj: Any, attribute: str, default: Any = None) -> Any:
    try:
        value = getattr(obj, attribute)
        return value() if callable(value) else value
    except Exception:
        return default


def _control_metadata(control: Any) -> dict[str, Any]:
    info = getattr(control, "element_info", None)
    name = str(_safe_value(info, "name", "") or "")[:180]
    automation_id = str(_safe_value(info, "auto_id", "") or "")[:120]
    control_type = str(_safe_value(info, "control_type", "Unknown") or "Unknown")[:50]
    metadata = {
        "name": name,
        "automation_id": automation_id,
        "control_type": control_type,
        "enabled": bool(_safe_value(info, "enabled", False)),
        "visible": bool(_safe_value(info, "visible", False)),
    }
    if is_sensitive_control(metadata):
        metadata["name"] = "[sensitive control hidden]"
        metadata["automation_id"] = "[hidden]"
        metadata["sensitive"] = True
    return metadata


def _desktop():
    """Create a fresh UIA Desktop object; wrappers never persist across calls."""
    try:
        from pywinauto import Desktop
    except ImportError as exc:
        raise RuntimeError(
            "pywinauto is missing. Run: .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt"
        ) from exc
    return Desktop(backend="uia")


def _run_with_desktop(action):
    _check_enabled()
    _require_windows()
    pythoncom = None
    initialized = False
    desktop = None
    try:
        try:
            import pythoncom as _pythoncom
            pythoncom = _pythoncom
            pythoncom.CoInitialize()
            initialized = True
        except ImportError as exc:
            raise RuntimeError(
                "Windows COM support is missing. Reinstall the Ozzy dependencies with "
                ".\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt"
            ) from exc
        desktop = _desktop()
        result = action(desktop)
        _check_enabled()
        return result
    finally:
        # Drop UIA/COM wrappers before uninitializing this worker thread's COM apartment.
        desktop = None
        if initialized and pythoncom is not None:
            pythoncom.CoUninitialize()


def _window_title(window: Any) -> str:
    title = _safe_value(window, "window_text", "")
    if not title:
        info = getattr(window, "element_info", None)
        title = _safe_value(info, "name", "")
    return str(title or "(untitled window)")[:220]


def _resolve_window(desktop: Any, window_handle: Any = None):
    if window_handle is None or str(window_handle).strip() == "":
        active = desktop.get_active()
        if active is None:
            raise RuntimeError("Windows did not report an active application window.")
        try:
            window = active.top_level_parent()
        except Exception:
            window = active
        if str(_safe_value(window, "control_type", "Window")) != "Window":
            try:
                window = window.top_level_parent()
            except Exception:
                pass
        if window is None:
            raise RuntimeError("Could not identify the active application window.")
        return window

    wanted = validate_window_handle(window_handle)
    for window in desktop.windows():
        try:
            if int(window.handle) == wanted:
                if not window.is_visible():
                    raise RuntimeError("That application window is not visible.")
                return window
        except RuntimeError:
            raise
        except Exception:
            continue
    raise RuntimeError("That window handle is no longer available. Run windows_list_windows again.")


def _iter_controls(window: Any):
    try:
        iterator = window.iter_descendants()
    except Exception:
        iterator = iter(window.descendants())
    for index, control in enumerate(iterator):
        if index >= MAX_CONTROLS:
            break
        yield index, control


def _bounds(control: Any) -> dict[str, int] | None:
    try:
        rect = control.rectangle()
        return {
            "left": int(rect.left), "top": int(rect.top),
            "right": int(rect.right), "bottom": int(rect.bottom),
        }
    except Exception:
        return None


def _describe_control(index: int, control: Any) -> dict[str, Any] | None:
    meta = _control_metadata(control)
    if not meta["visible"]:
        return None
    if not meta["name"] and not meta["automation_id"]:
        return None
    result = {"index": index, **meta}
    if not meta.get("sensitive"):
        bounds = _bounds(control)
        if bounds:
            result["bounds"] = bounds
    return result


def _list_windows(desktop: Any) -> dict[str, Any]:
    rows = []
    for window in desktop.windows():
        if len(rows) >= MAX_WINDOWS:
            break
        try:
            if not window.is_visible():
                continue
            title = _window_title(window)
            if not title or title == "(untitled window)":
                continue
            info = getattr(window, "element_info", None)
            handle = int(window.handle)
            rows.append({
                "window_handle": str(handle),
                "title": title,
                "process_id": int(_safe_value(info, "process_id", 0) or 0),
                "control_type": str(_safe_value(info, "control_type", "Window") or "Window"),
            })
        except Exception:
            continue
    return {"ok": True, "count": len(rows), "windows": rows, "message": "Visible application windows listed. No window contents or field values were read."}


def _inspect(args: dict[str, Any], desktop: Any) -> dict[str, Any]:
    window = _resolve_window(desktop, args.get("window_handle"))
    controls = []
    visited = 0
    for index, control in _iter_controls(window):
        visited += 1
        description = _describe_control(index, control)
        if description:
            controls.append(description)
    return {
        "ok": True,
        "window_handle": str(int(window.handle)),
        "window_title": _window_title(window),
        "control_count_returned": len(controls),
        "scan_limit": MAX_CONTROLS,
        "controls": controls,
        "message": "UI Automation tree inspected. Editable values were not read.",
    }


def _find_control(window: Any, args: dict[str, Any], allowed_types: set[str]):
    name = str(args.get("name") or "").strip()
    automation_id = str(args.get("automation_id") or "").strip()
    requested_type = str(args.get("control_type") or "").strip()
    if not name and not automation_id:
        raise ValueError("Provide a control name or automation_id from windows_inspect.")
    if len(name) > 180 or len(automation_id) > 120 or len(requested_type) > 50:
        raise ValueError("The requested control identifier is too long.")

    if is_high_impact_control({"name": name, "automation_id": automation_id}):
        raise PermissionError("That control appears to perform a high-impact action. Ozzy will not activate it.")
    if is_sensitive_control({"name": name, "automation_id": automation_id, "control_type": requested_type}):
        raise PermissionError("Sensitive credential, payment, or security controls cannot be operated by Ozzy.")

    matches = []
    for _index, control in _iter_controls(window):
        meta = _control_metadata(control)
        raw_info = getattr(control, "element_info", None)
        raw_name = str(_safe_value(raw_info, "name", "") or "")
        raw_auto_id = str(_safe_value(raw_info, "auto_id", "") or "")
        raw_type = str(_safe_value(raw_info, "control_type", "") or "")
        if name and raw_name.casefold() != name.casefold():
            continue
        if automation_id and raw_auto_id.casefold() != automation_id.casefold():
            continue
        if requested_type and raw_type.casefold() != requested_type.casefold():
            continue
        if raw_type not in allowed_types:
            continue
        if is_sensitive_control({"name": raw_name, "automation_id": raw_auto_id, "control_type": raw_type}):
            raise PermissionError("Sensitive credential, payment, or security controls cannot be operated by Ozzy.")
        if is_high_impact_control({"name": raw_name, "automation_id": raw_auto_id}):
            raise PermissionError("That control appears to perform a high-impact action. Ozzy will not activate it.")
        matches.append((control, meta))

    if not matches:
        raise RuntimeError("No matching visible control was found. Inspect the window again and use its exact name or automation_id.")
    if len(matches) > 1:
        choices = [
            {"name": meta.get("name"), "control_type": meta.get("control_type"), "automation_id": meta.get("automation_id")}
            for _control, meta in matches[:8]
        ]
        raise RuntimeError(f"The control match is ambiguous ({len(matches)} matches). Add control_type or automation_id to identify exactly one: {choices}")
    control, meta = matches[0]
    if not meta["visible"] or not meta["enabled"]:
        raise RuntimeError("The matching control is not both visible and enabled.")
    return control, meta


def _activate(args: dict[str, Any], desktop: Any) -> dict[str, Any]:
    window = _resolve_window(desktop, args.get("window_handle"))
    try:
        window.set_focus()
    except Exception as exc:
        raise RuntimeError(f"Could not activate that window: {str(exc)[:180]}") from exc
    return {"ok": True, "window_handle": str(int(window.handle)), "window_title": _window_title(window), "message": "Application window activated."}


def _activate_control(control: Any, control_type: str) -> None:
    """Use the UIA interaction pattern appropriate for the selected control."""
    if control_type in {"TabItem", "ListItem", "TreeItem", "MenuItem"}:
        # These UIA controls expose SelectionItem patterns rather than Button.click().
        control.select()
    elif control_type == "Button":
        control.click()  # InvokePattern; preferable to coordinate-based clicking.
    elif control_type == "Hyperlink":
        control.invoke()
    else:
        # Document, Pane and SplitButton may not expose InvokePattern.
        control.click_input()


def _click(args: dict[str, Any], desktop: Any) -> dict[str, Any]:
    window = _resolve_window(desktop, args.get("window_handle"))
    control, meta = _find_control(window, args, CLICKABLE_TYPES)
    control_type = meta["control_type"]
    try:
        _activate_control(control, control_type)
    except Exception as exc:
        raise RuntimeError(f"Could not activate the UIA control: {str(exc)[:180]}") from exc
    return {"ok": True, "control_name": meta["name"], "control_type": control_type, "message": f"Activated the {control_type} control '{meta['name']}'."}


def _set_text(args: dict[str, Any], desktop: Any) -> dict[str, Any]:
    window = _resolve_window(desktop, args.get("window_handle"))
    text = validate_text(args.get("text"))
    control, meta = _find_control(window, args, {"Edit"})
    try:
        control.set_edit_text(text)
    except Exception as exc:
        raise RuntimeError(f"Could not set text in that Edit control: {str(exc)[:180]}") from exc
    return {"ok": True, "control_name": meta["name"], "characters": len(text), "message": f"Set {len(text)} characters in Edit control '{meta['name']}'. The entered value was not read back."}


def _select(args: dict[str, Any], desktop: Any) -> dict[str, Any]:
    window = _resolve_window(desktop, args.get("window_handle"))
    option = str(args.get("option") or "").strip()
    if not option or len(option) > 180:
        raise ValueError("Provide a dropdown or tab option with 1 to 180 characters.")
    if is_high_impact_control({"name": option}):
        raise PermissionError("That option appears to perform a high-impact action and is blocked.")
    if is_sensitive_control({"name": option}):
        raise PermissionError("Sensitive credential, payment, or security options cannot be selected by Ozzy.")
    control, meta = _find_control(window, args, {"ComboBox", "Tab"})
    try:
        control.select(option)
    except Exception as exc:
        raise RuntimeError(f"Could not select that option: {str(exc)[:180]}") from exc
    return {"ok": True, "control_name": meta["name"], "message": f"Selected the requested option in '{meta['name']}'."}


def _toggle(args: dict[str, Any], desktop: Any) -> dict[str, Any]:
    window = _resolve_window(desktop, args.get("window_handle"))
    checked = args.get("checked", True)
    if not isinstance(checked, bool):
        raise ValueError("checked must be true or false.")
    control, meta = _find_control(window, args, {"CheckBox", "RadioButton"})
    try:
        if meta["control_type"] == "RadioButton":
            if not checked:
                raise ValueError("Radio buttons cannot be unchecked directly; choose another option instead.")
            control.select()
        else:
            current = int(control.get_toggle_state()) == 1
            if current != checked:
                control.toggle()
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not change that control: {str(exc)[:180]}") from exc
    return {"ok": True, "control_name": meta["name"], "checked": checked, "message": f"Set '{meta['name']}' to {'checked' if checked else 'unchecked'}."}


def execute_action(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Dispatch the small allow-list of Windows UI Automation tools."""
    _check_enabled()
    # Every handler uses the same signature: (payload, desktop). Keep this
    # order consistent here; passing (desktop, payload) makes pywinauto's
    # WindowSpecification arrive as `args`, which then fails on args.get(...).
    actions = {
        "windows_list_windows": lambda payload, desktop: _list_windows(desktop),
        "windows_inspect": _inspect,
        "windows_activate": _activate,
        "windows_click": _click,
        "windows_set_text": _set_text,
        "windows_select": _select,
        "windows_toggle": _toggle,
    }
    action = actions.get(name)
    if action is None:
        raise ValueError(f"Unsupported Windows UI Automation action: {name}")
    payload = args if isinstance(args, dict) else {}
    return _run_with_desktop(lambda desktop: action(payload, desktop))
