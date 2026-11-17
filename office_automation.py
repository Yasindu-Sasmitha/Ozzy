"""Stage 7: consent-gated Microsoft Office automation through the active COM session.

This module never launches Office applications. It attaches only to an already-running
Word, Excel, or PowerPoint instance, uses a small action allow-list, and keeps all COM
objects inside the worker thread that initialized COM.
"""
from __future__ import annotations

import datetime as _datetime
import json
import math
import os
import re
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

_DISABLED = threading.Event()
_DISABLED.set()

APP_PROGIDS = {
    "word": "Word.Application",
    "excel": "Excel.Application",
    "powerpoint": "PowerPoint.Application",
}
APP_EXTENSIONS = {
    "word": {".docx"},
    "excel": {".xlsx"},
    "powerpoint": {".pptx"},
}
MAX_TEXT = 10_000
MAX_RANGE_CELLS = 200
MAX_RANGE_ADDRESS = re.compile(r"^[A-Za-z]{1,3}[1-9][0-9]{0,6}(?::[A-Za-z]{1,3}[1-9][0-9]{0,6})?$")
SENSITIVE_TEXT = re.compile(
    r"(\b(api[_ -]?key|password|passwd|passcode|secret[_ -]?key|access[_ -]?token|refresh[_ -]?token)\b\s*(is|=|:)\s*\S+|"
    r"\bAIza[0-9A-Za-z_\-]{25,}\b|\bsk-[A-Za-z0-9_-]{20,}\b)", re.IGNORECASE,
)
SENSITIVE_FILENAME = re.compile(r"(password|credential|secret|token|private.?key|recovery.?code|bank.?statement|tax.?return)", re.IGNORECASE)


class OfficeAutomationError(RuntimeError):
    """Raised when an Office target or operation is unavailable or unsafe."""


def resume_actions() -> None:
    """Allow Office calls after explicit PC Control opt-in for the session."""
    _DISABLED.clear()


def stop_actions() -> None:
    """Reject subsequent Office calls after PC Control is disabled."""
    _DISABLED.set()


def _check_enabled() -> None:
    if _DISABLED.is_set():
        raise PermissionError("Office automation is disabled. Enable PC Control in Ozzy's Advanced Options first.")


def _require_windows() -> None:
    if sys.platform != "win32":
        raise OfficeAutomationError("Microsoft Office COM automation is available only on Windows 10/11.")


def _connect(progid: str):
    """Attach to an existing Office application; Dispatch/CreateObject is intentionally not used."""
    try:
        from win32com.client import GetActiveObject
    except ImportError as exc:
        raise OfficeAutomationError(
            "pywin32 is not installed. Run: .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt"
        ) from exc
    try:
        return GetActiveObject(progid)
    except Exception as exc:
        app_name = next((name.title() for name, value in APP_PROGIDS.items() if value == progid), progid)
        raise OfficeAutomationError(
            f"{app_name} is not running or has no active COM session. Open the application and the document first."
        ) from exc


def _with_app(app_key: str, callback: Callable[[Any], dict[str, Any]]) -> dict[str, Any]:
    _check_enabled()
    _require_windows()
    key = str(app_key or "").strip().lower()
    if key not in APP_PROGIDS:
        raise ValueError("application must be 'word', 'excel', or 'powerpoint'.")
    try:
        import pythoncom
    except ImportError as exc:
        raise OfficeAutomationError("Windows COM support is missing. Install the project requirements.") from exc
    pythoncom.CoInitialize()
    app = None
    try:
        _check_enabled()
        app = _connect(APP_PROGIDS[key])
        result = callback(app)
        _check_enabled()
        if not isinstance(result, dict):
            raise OfficeAutomationError("The Office adapter returned an invalid result.")
        return result
    finally:
        app = None
        pythoncom.CoUninitialize()


def _active_word(app):
    try:
        document = app.ActiveDocument
    except Exception as exc:
        raise OfficeAutomationError("No active Word document was found. Open a document first.") from exc
    if document is None:
        raise OfficeAutomationError("No active Word document was found. Open a document first.")
    return document


def _active_workbook(app):
    try:
        workbook = app.ActiveWorkbook
    except Exception as exc:
        raise OfficeAutomationError("No active Excel workbook was found. Open a workbook first.") from exc
    if workbook is None:
        raise OfficeAutomationError("No active Excel workbook was found. Open a workbook first.")
    return workbook


def _active_presentation(app):
    try:
        presentation = app.ActivePresentation
    except Exception as exc:
        raise OfficeAutomationError("No active PowerPoint presentation was found. Open a presentation first.") from exc
    if presentation is None:
        raise OfficeAutomationError("No active PowerPoint presentation was found. Open a presentation first.")
    return presentation


def _writable(obj, app_label: str) -> None:
    try:
        if bool(obj.ReadOnly):
            raise PermissionError(f"The active {app_label} file is read-only. Ozzy will not change it.")
    except AttributeError:
        pass
    except PermissionError:
        raise
    except Exception as exc:
        raise OfficeAutomationError(f"Could not verify whether the active {app_label} is writable. No change was made.") from exc


def _inspect_only_error(app_key: str) -> OfficeAutomationError:
    label = {"word": "Word .docx", "excel": "Excel .xlsx", "powerpoint": "PowerPoint .pptx"}.get(app_key, "Office")
    extension = {"word": "docx", "excel": "xlsx", "powerpoint": "pptx"}.get(app_key, "")
    return OfficeAutomationError(
        f"Editing is limited to macro-free {label} files in this release. "
        f"This active file format is inspect-only; save a separate .{extension} copy manually first."
    )


def _require_macro_free_powerpoint(presentation: Any) -> None:
    """PowerPoint's Presentation object has no FileFormat property, so verify via its file name.

    A saved ``.pptx`` cannot contain VBA, so the extension is sufficient. An unsaved new
    presentation has no extension; it is accepted only when PowerPoint confirms it has no VBA project.
    """
    try:
        full_name = str(presentation.FullName or presentation.Name or "")
    except Exception as exc:
        raise OfficeAutomationError("Could not verify the active PowerPoint .pptx file format. No change was made.") from exc
    suffix = os.path.splitext(full_name.replace("\\", "/").rsplit("/", 1)[-1])[1].lower()
    if suffix == ".pptx":
        return
    if suffix:
        raise _inspect_only_error("powerpoint")  # .ppt, .pptm, .potx, .ppsx, ...
    try:
        has_vba = bool(presentation.HasVBProject)
    except Exception as exc:
        raise OfficeAutomationError("Could not verify the active PowerPoint .pptx file format. No change was made.") from exc
    if has_vba:
        raise _inspect_only_error("powerpoint")


def _require_macro_free_format(app_key: str, office_item: Any) -> None:
    """Restrict edits to the macro-free Office Open XML formats supported here."""
    if app_key == "powerpoint":
        _require_macro_free_powerpoint(office_item)
        return
    # Word reports a normal .docx as wdFormatXMLDocument (12); 16 is wdFormatDocumentDefault.
    # 13 (.docm), 0 (.doc) and other formats stay inspect-only. Excel: 51 = xlOpenXMLWorkbook (.xlsx).
    allowed_formats = {"word": {12, 16}, "excel": {51}}
    label = {"word": "Word .docx", "excel": "Excel .xlsx"}.get(app_key, "Office")
    try:
        file_format = int(office_item.SaveFormat if app_key == "word" else office_item.FileFormat)
    except Exception as exc:
        raise OfficeAutomationError(f"Could not verify the active {label} file format. No change was made.") from exc
    if file_format not in allowed_formats.get(app_key, set()):
        raise _inspect_only_error(app_key)


@contextmanager
def _excel_events_suppressed(app):
    """Temporarily suspend Excel VBA/application events during a COM write, then restore."""
    try:
        original = bool(app.EnableEvents)
        app.EnableEvents = False
    except Exception as exc:
        raise OfficeAutomationError("Could not safely suspend Excel workbook events. No change was made.") from exc
    try:
        yield
    finally:
        try:
            app.EnableEvents = original
        except Exception as exc:
            raise OfficeAutomationError("Excel events could not be restored to their previous state. Check Excel before continuing.") from exc


def _clean_text(value: Any, label: str = "text", limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    if not value.strip():
        raise ValueError(f"{label} cannot be empty.")
    if len(value) > limit:
        raise ValueError(f"{label} is limited to {limit} characters.")
    if "\x00" in value:
        raise ValueError(f"{label} contains an invalid null character.")
    if SENSITIVE_TEXT.search(value):
        raise PermissionError(f"{label} appears to contain a password, API key, token, or private secret and cannot be entered.")
    return value


def _normalise_com_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        return value
    if isinstance(value, (_datetime.datetime, _datetime.date, _datetime.time)):
        return value.isoformat()
    return str(value)[:1000]


def _redact_sensitive_text(value: str) -> str:
    """Keep obvious credential-like text out of tool responses sent to Gemini."""
    value = re.sub(
        r"(?i)(\b(?:api[_ -]?key|password|passwd|passcode|secret[_ -]?key|access[_ -]?token|refresh[_ -]?token)\b\s*(?:is|=|:)\s*)[^\s,;]+",
        r"\1[REDACTED]", value,
    )
    value = re.sub(r"\bAIza[0-9A-Za-z_\-]{25,}\b", "[REDACTED_KEY]", value)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{20,}\b", "[REDACTED_TOKEN]", value)
    return value


def _validate_range_address(address: Any) -> str:
    if not isinstance(address, str):
        raise ValueError("range must be a simple Excel A1 address such as A1 or A1:C8.")
    clean = address.strip().upper()
    if len(clean) > 24 or not MAX_RANGE_ADDRESS.fullmatch(clean):
        raise ValueError("range must be a simple Excel A1 address such as A1 or A1:C8; named ranges and external references are not supported.")
    return clean


def _worksheet(workbook, sheet_name: Any = None):
    try:
        if sheet_name is None or str(sheet_name).strip() == "":
            sheet = workbook.ActiveSheet
        else:
            name = str(sheet_name).strip()
            if len(name) > 31 or any(char in name for char in ":\\/?*[]"):
                raise ValueError("sheet_name must be a valid Excel worksheet name (1 to 31 characters).")
            sheet = workbook.Worksheets(name)
    except ValueError:
        raise
    except Exception as exc:
        raise OfficeAutomationError("The requested worksheet was not found in the active workbook.") from exc
    try:
        _ = sheet.Cells
    except Exception as exc:
        raise OfficeAutomationError("The active Excel tab is not a worksheet. Select a worksheet and try again.") from exc
    return sheet


def _excel_values(raw: Any, rows: int, columns: int) -> list[list[Any]]:
    if rows == 1 and columns == 1:
        value = _normalise_com_value(raw)
        return [[_redact_sensitive_text(value) if isinstance(value, str) else value]]
    if not isinstance(raw, (tuple, list)):
        value = _normalise_com_value(raw)
        return [[_redact_sensitive_text(value) if isinstance(value, str) else value]]
    result: list[list[Any]] = []
    for row in raw:
        values = list(row) if isinstance(row, (tuple, list)) else [row]
        row_values = []
        for value in values:
            normalised = _normalise_com_value(value)
            row_values.append(_redact_sensitive_text(normalised) if isinstance(normalised, str) else normalised)
        result.append(row_values)
    # Bound total response size so a 200-cell range cannot produce an enormous tool payload.
    remaining = 12_000
    for row in result:
        for index, value in enumerate(row):
            if isinstance(value, str):
                row[index] = value[:max(0, min(500, remaining))]
                remaining -= len(row[index])
    return result


def _validate_values_json(raw: Any) -> list[list[Any]]:
    if not isinstance(raw, str) or len(raw) > 40_000:
        raise ValueError("values_json must be a JSON string containing a rectangular array of up to 200 cells.")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("values_json is not valid JSON.") from exc
    if not isinstance(parsed, list) or not parsed or any(not isinstance(row, list) or not row for row in parsed):
        raise ValueError("values_json must be a non-empty two-dimensional array, for example [[\"Name\",\"Score\"],[\"A\",92]].")
    width = len(parsed[0])
    if width < 1 or any(len(row) != width for row in parsed):
        raise ValueError("Every row in values_json must have the same number of columns.")
    if len(parsed) * width > MAX_RANGE_CELLS:
        raise ValueError(f"Excel writes are limited to {MAX_RANGE_CELLS} cells per action.")
    cleaned: list[list[Any]] = []
    for row in parsed:
        output_row = []
        for value in row:
            if value is None or isinstance(value, bool) or isinstance(value, int):
                output_row.append(value)
            elif isinstance(value, float):
                if not math.isfinite(value):
                    raise ValueError("Excel values must be finite numbers.")
                output_row.append(value)
            elif isinstance(value, str):
                if len(value) > 1000 or "\x00" in value:
                    raise ValueError("Each Excel text value is limited to 1,000 characters and cannot contain null characters.")
                if value.lstrip().startswith(("=", "+", "-", "@")):
                    raise PermissionError("Excel formula-like text is blocked. Ozzy writes literal values only; formulas must be entered manually by the user.")
                if SENSITIVE_TEXT.search(value):
                    raise PermissionError("Excel text that appears to contain a password, key, token, or private secret is blocked.")
                output_row.append(value)
            else:
                raise ValueError("Excel cells may contain only strings, numbers, booleans, or null values. Formulas and nested objects are not supported.")
        cleaned.append(output_row)
    return cleaned


def _resolve_new_file_path(app_key: str, raw_path: Any) -> Path:
    if app_key not in APP_EXTENSIONS:
        raise ValueError("application must be 'word', 'excel', or 'powerpoint'.")
    if not isinstance(raw_path, str) or not raw_path.strip() or len(raw_path) > 500:
        raise ValueError("file_path must be an absolute path for the new Office file.")
    candidate = Path(os.path.expandvars(raw_path.strip())).expanduser()
    if not candidate.is_absolute() or candidate.name in {"", ".", ".."}:
        raise ValueError("file_path must be an absolute path to a new file inside your Desktop, Documents, or OneDrive folder.")
    extension = candidate.suffix.lower()
    if extension not in APP_EXTENSIONS[app_key]:
        expected = ", ".join(sorted(APP_EXTENSIONS[app_key]))
        raise ValueError(f"The {app_key.title()} save path must use {expected}.")
    if SENSITIVE_FILENAME.search(candidate.name):
        raise PermissionError("That filename looks sensitive and cannot be created by Ozzy.")
    try:
        profile = Path.home().resolve(strict=True)
        parent = candidate.parent.resolve(strict=True)
        resolved = parent / candidate.name
        relative = parent.relative_to(profile)
    except (OSError, ValueError) as exc:
        raise PermissionError("The save folder must be an existing folder inside your Windows user profile.") from exc
    first_folder = relative.parts[0].casefold() if relative.parts else ""
    allowed_folder = first_folder in {"desktop", "documents"} or first_folder.startswith("onedrive")
    if not parent.is_dir() or not allowed_folder:
        raise PermissionError("Office files may only be saved in Desktop, Documents, or OneDrive folders inside your user profile.")
    if candidate.name.startswith(".") or any(part.startswith(".") for part in relative.parts):
        raise PermissionError("Hidden folders and hidden filenames are not supported.")
    if resolved.exists():
        raise FileExistsError("That file already exists. Choose a new filename; Ozzy never overwrites an existing file.")
    return resolved


def prepare_save_request(args: dict[str, Any]) -> dict[str, str]:
    """Validate and describe a Save-as-new request without creating or changing a file."""
    if not isinstance(args, dict):
        raise ValueError("Save request arguments must be an object.")
    app_key = str(args.get("application") or "").strip().lower()
    path = _resolve_new_file_path(app_key, args.get("file_path"))
    return {
        "application": app_key,
        "application_label": {"word": "Microsoft Word", "excel": "Microsoft Excel", "powerpoint": "Microsoft PowerPoint"}[app_key],
        "file_path": str(path),
        "file_name": path.name,
    }


def get_active_target_info(app_key: str) -> dict[str, str]:
    """Identify the active Office item before approval and detect target switches."""
    key = str(app_key or "").strip().lower()
    def describe(app):
        if key == "word":
            target = _active_word(app)
        elif key == "excel":
            target = _active_workbook(app)
        elif key == "powerpoint":
            target = _active_presentation(app)
        else:
            raise ValueError("application must be 'word', 'excel', or 'powerpoint'.")
        name = str(target.Name)[:180]
        try:
            identity = str(target.FullName or name)[:500]
        except Exception:
            identity = name
        return {"ok": True, "name": name, "identity": identity}
    return _with_app(key, describe)


def get_active_target_name(app_key: str) -> str:
    """Compatibility wrapper returning the display name of the current Office item."""
    return get_active_target_info(app_key)["name"]


def _office_list_running_apps(_args: dict[str, Any]) -> dict[str, Any]:
    running = []
    for app_key, progid in APP_PROGIDS.items():
        try:
            app = _connect(progid)
            target = ""
            try:
                if app_key == "word":
                    target = str(app.ActiveDocument.Name)
                elif app_key == "excel":
                    target = str(app.ActiveWorkbook.Name)
                else:
                    target = str(app.ActivePresentation.Name)
            except Exception:
                target = "No active document"
            running.append({"application": app_key, "active_item": target[:180]})
            app = None
        except Exception:
            continue
    return {"ok": True, "applications": running, "count": len(running), "message": "Already-running Microsoft Office applications checked. Ozzy did not launch any application."}


def _word_inspect(_args: dict[str, Any], app) -> dict[str, Any]:
    doc = _active_word(app)
    # Read only the bounded tail rather than materializing an entire large document.
    content_end = int(doc.Content.End)
    text_range = doc.Range(max(0, content_end - 6000), content_end)
    text = _redact_sensitive_text(str(text_range.Text or ""))
    pages = None
    try:
        pages = int(doc.ComputeStatistics(2))  # wdStatisticPages
    except Exception:
        pass
    return {
        "ok": True, "application": "word", "document_name": str(doc.Name)[:180],
        "paragraph_count": int(doc.Paragraphs.Count), "page_count": pages,
        "character_count": max(0, content_end - 1), "text_excerpt": text[-6000:],
        "message": "Active Word document inspected. Text is an excerpt of the document's end; no content was changed.",
    }


def _word_insert_text(args: dict[str, Any], app) -> dict[str, Any]:
    doc = _active_word(app)
    _require_macro_free_format("word", doc)
    _writable(doc, "Word document")
    text = _clean_text(args.get("text"), "text")
    start = max(0, int(doc.Content.End) - 1)
    insertion = doc.Range(start, start)
    insertion.InsertAfter(text + "\r")
    return {
        "ok": True, "application": "word", "document_name": str(doc.Name)[:180],
        "inserted_characters": len(text), "message": f"Appended {len(text)} characters to the active Word document. The change is not saved to disk yet.",
    }


def _word_add_heading(args: dict[str, Any], app) -> dict[str, Any]:
    doc = _active_word(app)
    _require_macro_free_format("word", doc)
    _writable(doc, "Word document")
    heading = _clean_text(args.get("heading"), "heading", 240)
    level = args.get("level", 1)
    if isinstance(level, bool) or not isinstance(level, int) or level not in {1, 2, 3}:
        raise ValueError("level must be 1, 2, or 3.")
    start = max(0, int(doc.Content.End) - 1)
    insertion = doc.Range(start, start)
    insertion.InsertAfter(heading + "\r")
    doc.Range(start, start + len(heading)).Style = f"Heading {level}"
    return {
        "ok": True, "application": "word", "document_name": str(doc.Name)[:180],
        "heading": heading, "level": level, "message": f"Added Heading {level} to the active Word document. The change is not saved to disk yet.",
    }


def _excel_inspect_range(args: dict[str, Any], app) -> dict[str, Any]:
    workbook = _active_workbook(app)
    address = _validate_range_address(args.get("range"))
    sheet = _worksheet(workbook, args.get("sheet_name"))
    selected = sheet.Range(address)
    rows, columns = int(selected.Rows.Count), int(selected.Columns.Count)
    count = rows * columns
    if count > MAX_RANGE_CELLS:
        raise ValueError(f"Inspection is limited to {MAX_RANGE_CELLS} cells per action; the requested range has {count} cells.")
    values = _excel_values(selected.Value2, rows, columns)
    sheet_names = [str(workbook.Worksheets.Item(i).Name)[:31] for i in range(1, int(workbook.Worksheets.Count) + 1)]
    return {
        "ok": True, "application": "excel", "workbook_name": str(workbook.Name)[:180],
        "sheet_name": str(sheet.Name)[:31], "worksheet_names": sheet_names,
        "range": address, "rows": rows, "columns": columns, "values": values,
        "message": f"Read {count} cell value(s) from {sheet.Name}!{address}. Formulas were not returned.",
    }


def _excel_write_range(args: dict[str, Any], app) -> dict[str, Any]:
    workbook = _active_workbook(app)
    _require_macro_free_format("excel", workbook)
    _writable(workbook, "Excel workbook")
    address = _validate_range_address(args.get("range"))
    values = _validate_values_json(args.get("values_json"))
    sheet = _worksheet(workbook, args.get("sheet_name"))
    target = sheet.Range(address)
    rows, columns = int(target.Rows.Count), int(target.Columns.Count)
    if rows != len(values) or columns != len(values[0]):
        raise ValueError(f"The supplied values are {len(values)}x{len(values[0])}, but {address} is {rows}x{columns}. Make the range and data dimensions match exactly.")
    with _excel_events_suppressed(app):
        if rows == 1 and columns == 1:
            target.Value = values[0][0]
        else:
            target.Value = tuple(tuple(row) for row in values)
    return {
        "ok": True, "application": "excel", "workbook_name": str(workbook.Name)[:180],
        "sheet_name": str(sheet.Name)[:31], "range": address,
        "written_cells": rows * columns,
        "message": f"Wrote {rows * columns} literal value(s) to {sheet.Name}!{address}. The workbook is not saved to disk yet.",
    }


def _excel_add_worksheet(args: dict[str, Any], app) -> dict[str, Any]:
    workbook = _active_workbook(app)
    _require_macro_free_format("excel", workbook)
    _writable(workbook, "Excel workbook")
    name = _clean_text(args.get("sheet_name"), "sheet_name", 31).strip()
    if any(char in name for char in ":\\/?*[]") or name.startswith("'") or name.endswith("'"):
        raise ValueError("sheet_name contains a character Excel does not allow.")
    existing = [str(workbook.Worksheets.Item(i).Name).casefold() for i in range(1, int(workbook.Worksheets.Count) + 1)]
    if name.casefold() in existing:
        raise FileExistsError(f"A worksheet named '{name}' already exists. Existing sheets are never replaced.")
    with _excel_events_suppressed(app):
        sheet = workbook.Worksheets.Add(After=workbook.Worksheets.Item(workbook.Worksheets.Count))
        sheet.Name = name
    return {
        "ok": True, "application": "excel", "workbook_name": str(workbook.Name)[:180],
        "sheet_name": name, "worksheet_count": int(workbook.Worksheets.Count),
        "message": f"Created worksheet '{name}'. The workbook is not saved to disk yet.",
    }


def _powerpoint_inspect(_args: dict[str, Any], app) -> dict[str, Any]:
    presentation = _active_presentation(app)
    total = int(presentation.Slides.Count)
    slides = []
    total_chars = 0
    first_slide = max(1, total - 29)  # Include the newest slide so workflow verification can see additions.
    for index in range(first_slide, total + 1):
        slide = presentation.Slides.Item(index)
        texts = []
        shape_count = min(int(slide.Shapes.Count), 80)
        for shape_index in range(1, shape_count + 1):
            shape = slide.Shapes.Item(shape_index)
            try:
                if bool(shape.HasTextFrame) and bool(shape.TextFrame.HasText):
                    value = str(shape.TextFrame.TextRange.Text or "").strip()
                    if value:
                        value = _redact_sensitive_text(value)
                        excerpt = value[:700]
                        texts.append(excerpt)
                        total_chars += len(excerpt)
            except Exception:
                continue
            if total_chars >= 9000:
                break
        slides.append({"slide_number": index, "text": "\n".join(texts)[:1200]})
        if total_chars >= 9000:
            break
    return {
        "ok": True, "application": "powerpoint", "presentation_name": str(presentation.Name)[:180],
        "slide_count": total, "slides_inspected": len(slides), "slides": slides,
        "message": "Active PowerPoint presentation inspected. Text excerpts only; no slides were changed.",
    }


def _powerpoint_add_slide(args: dict[str, Any], app) -> dict[str, Any]:
    presentation = _active_presentation(app)
    _require_macro_free_format("powerpoint", presentation)
    _writable(presentation, "PowerPoint presentation")
    title = _clean_text(args.get("title"), "title", 240)
    body = args.get("body", "")
    if body is None:
        body = ""
    if not isinstance(body, str) or len(body) > 5000 or "\x00" in body:
        raise ValueError("body must be text of up to 5,000 characters.")
    if SENSITIVE_TEXT.search(body):
        raise PermissionError("PowerPoint body text that appears to contain a secret or credential is blocked.")
    slide_number = int(presentation.Slides.Count) + 1
    slide = presentation.Slides.Add(slide_number, 2)  # ppLayoutText
    try:
        slide.Shapes.Placeholders.Item(1).TextFrame.TextRange.Text = title
        if body:
            slide.Shapes.Placeholders.Item(2).TextFrame.TextRange.Text = body
    except Exception as exc:
        raise OfficeAutomationError(f"A new slide was inserted, but its title/body placeholders could not be filled: {str(exc)[:160]}") from exc
    return {
        "ok": True, "application": "powerpoint", "presentation_name": str(presentation.Name)[:180],
        "slide_number": slide_number, "slide_count": int(presentation.Slides.Count),
        "title": title, "message": f"Added slide {slide_number} titled '{title}'. The presentation is not saved to disk yet.",
    }


def _check_expected_active_identity(target: Any, expected_identity: Any) -> None:
    """Bind an approved save to the same active Office item shown in the dialog."""
    if expected_identity is None or expected_identity == "":
        return
    if not isinstance(expected_identity, str) or len(expected_identity) > 500:
        raise ValueError("The approved Office document identity is invalid.")
    try:
        actual = str(target.FullName or target.Name)[:500]
    except Exception:
        actual = str(target.Name)[:500]
    if actual != expected_identity:
        raise PermissionError("The active Office document changed after approval. No file was saved; review the active document and approve again.")


def _office_save_new(args: dict[str, Any]) -> dict[str, Any]:
    preview = prepare_save_request(args)
    app_key = preview["application"]
    path = Path(preview["file_path"])

    def save(app):
        if path.exists():
            raise FileExistsError("The destination file appeared after approval. Nothing was overwritten; choose another filename.")
        if app_key == "word":
            document = _active_word(app)
            _check_expected_active_identity(document, args.get("_expected_active_identity"))
            _writable(document, "Word document")
            _require_macro_free_format("word", document)
            # SaveAs2 changes the active document's path; the previous file, if any, is left untouched.
            document.SaveAs2(str(path), 16, False, "", False)  # wdFormatXMLDocument; LockComments=False; no password; not added to recent files
        elif app_key == "excel":
            workbook = _active_workbook(app)
            _check_expected_active_identity(workbook, args.get("_expected_active_identity"))
            _writable(workbook, "Excel workbook")
            if int(workbook.FileFormat) != 51:
                raise OfficeAutomationError("Only a standard .xlsx workbook can be copied by this first release. Save macro-enabled or legacy workbooks manually in Excel.")
            with _excel_events_suppressed(app):
                workbook.SaveCopyAs(str(path))
        else:
            presentation = _active_presentation(app)
            _check_expected_active_identity(presentation, args.get("_expected_active_identity"))
            _writable(presentation, "PowerPoint presentation")
            _require_macro_free_format("powerpoint", presentation)
            presentation.SaveCopyAs(str(path), 24, False)  # ppSaveAsOpenXMLPresentation
        if not path.is_file() or path.stat().st_size <= 0:
            raise OfficeAutomationError("Office returned from Save As, but the new file could not be verified on disk.")
        return {
            "ok": True, "application": app_key, "file_path": str(path),
            "file_size_bytes": path.stat().st_size,
            "message": f"Created and verified a new {app_key.title()} file: {path.name}",
        }

    return _with_app(app_key, save)


def execute_action(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Dispatch the Stage 7 Office action allow-list under the existing PC Control consent."""
    _check_enabled()
    payload = args if isinstance(args, dict) else {}
    if name == "office_list_running_apps":
        _require_windows()
        import pythoncom
        pythoncom.CoInitialize()
        try:
            return _office_list_running_apps(payload)
        finally:
            pythoncom.CoUninitialize()
    if name == "office_save_new":
        return _office_save_new(payload)
    if name == "word_inspect":
        return _with_app("word", lambda app: _word_inspect(payload, app))
    if name == "word_insert_text":
        return _with_app("word", lambda app: _word_insert_text(payload, app))
    if name == "word_add_heading":
        return _with_app("word", lambda app: _word_add_heading(payload, app))
    if name == "excel_inspect_range":
        return _with_app("excel", lambda app: _excel_inspect_range(payload, app))
    if name == "excel_write_range":
        return _with_app("excel", lambda app: _excel_write_range(payload, app))
    if name == "excel_add_worksheet":
        return _with_app("excel", lambda app: _excel_add_worksheet(payload, app))
    if name == "powerpoint_inspect":
        return _with_app("powerpoint", lambda app: _powerpoint_inspect(payload, app))
    if name == "powerpoint_add_slide":
        return _with_app("powerpoint", lambda app: _powerpoint_add_slide(payload, app))
    raise ValueError(f"Unsupported Office automation action: {name}")
