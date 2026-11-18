"""Stage 8: bounded formatting and formula actions for Word, Excel and PowerPoint.

Every action here works on the *active* document, workbook or presentation through the
existing Stage 7 COM adapter (``office_automation``) and inherits its rules: PC Control
consent, macro-free ``.docx``/``.xlsx``/``.pptx`` only, read-only files are never changed,
and nothing is saved to disk (saving still goes through ``office_save_new``).

Formatting inputs are validated into plain Python values first (colors, fonts, sizes,
number formats) and only then touch COM, so the validators can be unit-tested without Office.

Excel formulas are accepted only after a conservative static check: an allow-list of
functions, no external-workbook references, no DDE/array/structured-reference syntax and no
named ranges. Formula text is never executed by Ozzy itself; Excel evaluates it.
"""
from __future__ import annotations

import math
import re
from typing import Any, Callable

import office_automation as base

OfficeAutomationError = base.OfficeAutomationError

MAX_FORMAT_CELLS = 100_000
MAX_FORMULA_CELLS = 2_000
MAX_FORMULA_CHARS = 1_000
MAX_TEXT_MATCHES = 200
MAX_SLIDES_PER_ACTION = 100
MAX_SHAPES_PER_SLIDE = 80

ACTIONS = {
    "word_format_text", "excel_format_range", "excel_set_formula",
    "powerpoint_format_text", "powerpoint_set_slide_background",
}

# --------------------------------------------------------------------------- colors

NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0), "green": (0, 128, 0),
    "lime": (0, 255, 0), "blue": (0, 0, 255), "navy": (0, 0, 128), "yellow": (255, 255, 0),
    "orange": (255, 165, 0), "purple": (128, 0, 128), "pink": (255, 192, 203),
    "magenta": (255, 0, 255), "cyan": (0, 255, 255), "teal": (0, 128, 128),
    "brown": (165, 42, 42), "maroon": (128, 0, 0), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "light gray": (211, 211, 211), "light grey": (211, 211, 211),
    "dark gray": (64, 64, 64), "dark grey": (64, 64, 64), "silver": (192, 192, 192),
    "gold": (255, 215, 0), "olive": (128, 128, 0), "light blue": (173, 216, 230),
    "dark blue": (0, 0, 139), "sky blue": (135, 206, 235), "light green": (144, 238, 144),
    "dark green": (0, 100, 0), "dark red": (139, 0, 0), "coral": (255, 127, 80),
    "indigo": (75, 0, 130), "violet": (238, 130, 238), "beige": (245, 245, 220),
    "turquoise": (64, 224, 208), "salmon": (250, 128, 114), "crimson": (220, 20, 60),
}
_HEX_COLOR = re.compile(r"#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})")
_NO_COLOR_WORDS = {"none", "transparent", "no fill", "nofill", "no color", "nocolor"}


def parse_color(value: Any, label: str = "color", *, allow_none: bool = False) -> int | None:
    """Return an Office BGR integer for a color name or hex value (``None`` means 'no color')."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a color name such as red, or a hex value such as #1F4E79.")
    text = value.strip().lower()
    if len(text) > 40:
        raise ValueError(f"{label} is too long.")
    if allow_none and text in _NO_COLOR_WORDS:
        return None
    match = _HEX_COLOR.fullmatch(text)
    if match:
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        red, green, blue = int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)
        return red | (green << 8) | (blue << 16)
    name = re.sub(r"[\s_-]+", " ", text)
    if name in NAMED_COLORS:
        red, green, blue = NAMED_COLORS[name]
        return red | (green << 8) | (blue << 16)
    raise ValueError(f"{label} must be a color name such as red, or a hex value such as #1F4E79.")


def color_hex(bgr: Any) -> str | None:
    """Format an Office BGR integer as #RRGGBB for read-back reports."""
    try:
        number = int(bgr)
    except (TypeError, ValueError):
        return None
    if number < 0 or number > 0xFFFFFF:
        return None
    return "#{:02X}{:02X}{:02X}".format(number & 255, (number >> 8) & 255, (number >> 16) & 255)


# --------------------------------------------------------------------------- scalar validators

_FONT_NAME = re.compile(r"^\w[\w ._\-]{0,63}$")


def validate_font_name(value: Any) -> str:
    if not isinstance(value, str) or not _FONT_NAME.fullmatch(value.strip()):
        raise ValueError("font_name must be a plain font name such as Calibri or Times New Roman (up to 64 characters).")
    return value.strip()


def validate_number(value: Any, label: str, minimum: float, maximum: float) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number.")
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} must be between {minimum:g} and {maximum:g}.")
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def validate_font_size(value: Any) -> float | int:
    return validate_number(value, "font_size", 4, 400)


def _flag(args: dict[str, Any], key: str) -> bool | None:
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false.")
    return value


def _choice(args: dict[str, Any], key: str, options: dict[str, Any]) -> Any:
    value = args.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str) or value.strip().casefold() not in options:
        raise ValueError(f"{key} must be one of: {', '.join(options)}.")
    return value.strip().casefold()


ALIGNMENT_NAMES = ("left", "center", "right", "justify")
WORD_ALIGNMENT = {"left": 0, "center": 1, "right": 2, "justify": 3}
PPT_ALIGNMENT = {"left": 1, "center": 2, "right": 3, "justify": 4}
EXCEL_HALIGN = {"left": -4131, "center": -4108, "right": -4152, "justify": -4130}
EXCEL_VALIGN = {"top": -4160, "middle": -4108, "center": -4108, "bottom": -4107}
WORD_HIGHLIGHT = {
    "none": 0, "black": 1, "blue": 2, "turquoise": 3, "cyan": 3, "bright green": 4, "lime": 4,
    "pink": 5, "magenta": 5, "red": 6, "yellow": 7, "white": 8, "dark blue": 9, "teal": 10,
    "green": 11, "violet": 12, "purple": 12, "dark red": 13, "dark yellow": 14, "olive": 14,
    "gray": 15, "grey": 15, "light gray": 16, "light grey": 16,
}
# Word built-in style names accepted by word_format_text, with WdBuiltinStyle fallbacks for
# non-English Word installations where the English style name is not recognised.
WORD_STYLES: dict[str, int] = {
    "normal": -1, "heading 1": -2, "heading 2": -3, "heading 3": -4, "heading 4": -5,
    "title": -63, "subtitle": -75, "list bullet": -49, "list number": -50,
    "quote": -181, "no spacing": -158,
}
WORD_STYLE_DISPLAY = {
    "normal": "Normal", "heading 1": "Heading 1", "heading 2": "Heading 2", "heading 3": "Heading 3",
    "heading 4": "Heading 4", "title": "Title", "subtitle": "Subtitle", "list bullet": "List Bullet",
    "list number": "List Number", "quote": "Quote", "no spacing": "No Spacing",
}
NUMBER_FORMAT_PRESETS = {
    "general": "General", "number": "#,##0.00", "integer": "0", "currency": "$#,##0.00",
    "percent": "0.00%", "percent0": "0%", "date": "yyyy-mm-dd", "short date": "m/d/yyyy",
    "time": "h:mm AM/PM", "text": "@", "scientific": "0.00E+00",
}
BORDER_MODES = ("all", "outline", "none")


def validate_number_format(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("number_format must be a preset name (general, number, integer, currency, percent, date, text) or an Excel format code.")
    text = value.strip()
    preset = NUMBER_FORMAT_PRESETS.get(text.casefold())
    if preset:
        return preset
    if len(text) > 100 or not text.isprintable():
        raise ValueError("number_format must be a printable Excel format code of up to 100 characters.")
    return text


def _common_text_spec(args: dict[str, Any]) -> dict[str, Any]:
    """Validate the character formatting properties shared by Word, Excel and PowerPoint."""
    spec: dict[str, Any] = {}
    for key in ("bold", "italic", "underline", "strikethrough"):
        flag = _flag(args, key)
        if flag is not None:
            spec[key] = flag
    if args.get("font_name") not in (None, ""):
        spec["font_name"] = validate_font_name(args["font_name"])
    if args.get("font_size") is not None:
        spec["font_size"] = validate_font_size(args["font_size"])
    if args.get("font_color") not in (None, ""):
        spec["font_color"] = parse_color(args["font_color"], "font_color")
    return spec


def _com_value(getter: Callable[[], Any]) -> Any:
    try:
        return getter()
    except Exception:
        return None


def _tri(value: Any) -> Any:
    """Normalise Office tri-state values (-1/1 true, 0 false, 9999999 mixed) for read-back."""
    if isinstance(value, bool):
        return value
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number in (-1, 1):
        return True
    if number == 0:
        return False
    return "mixed" if number == 9999999 else None


def _number_or_mixed(value: Any) -> Any:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number >= 9999999:
        return "mixed"
    return int(number) if number.is_integer() else round(number, 2)


def _color_report(value: Any) -> Any:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number == -16777216:
        return "automatic"
    if number == 9999999:
        return "mixed"
    return color_hex(number)


def _readback_font(font: Any, color: Callable[[], Any] | None = None) -> dict[str, Any]:
    """Read formatting back from COM so the model can confirm what Office actually applied."""
    if font is None:
        return {}
    report = {
        "bold": _tri(_com_value(lambda: font.Bold)),
        "italic": _tri(_com_value(lambda: font.Italic)),
        "font_name": _com_value(lambda: str(font.Name) or "mixed"),
        "font_size": _number_or_mixed(_com_value(lambda: font.Size)),
        "font_color": _color_report(_com_value(color or (lambda: font.Color))),
    }
    return {key: value for key, value in report.items() if value is not None}


# --------------------------------------------------------------------------- Word

def _parse_word_spec(args: dict[str, Any], target: str) -> dict[str, Any]:
    spec = _common_text_spec(args)
    highlight = _choice(args, "highlight_color", WORD_HIGHLIGHT)
    if highlight is not None:
        spec["highlight"] = WORD_HIGHLIGHT[highlight]
    paragraph_level: dict[str, Any] = {}
    alignment = _choice(args, "alignment", {name: name for name in ALIGNMENT_NAMES})
    if alignment is not None:
        paragraph_level["alignment"] = WORD_ALIGNMENT[alignment]
    if args.get("line_spacing") is not None:
        paragraph_level["line_spacing"] = validate_number(args["line_spacing"], "line_spacing", 0.5, 3)
    for key in ("space_before", "space_after"):
        if args.get(key) is not None:
            paragraph_level[key] = validate_number(args[key], key, 0, 200)
    style = _choice(args, "style", WORD_STYLES)
    if style is not None:
        paragraph_level["style"] = style
    if paragraph_level and target == "text_match":
        raise ValueError(
            "alignment, line_spacing, space_before, space_after and style apply to whole paragraphs; "
            "use target last_paragraph, paragraph, selection or document for them."
        )
    spec.update(paragraph_level)
    if not spec:
        raise ValueError("Provide at least one formatting property, such as bold, font_name, font_size, font_color, highlight_color, alignment or style.")
    return spec


def _last_text_paragraph(doc) -> tuple[int, Any]:
    count = int(doc.Paragraphs.Count)
    for index in range(count, max(0, count - 60), -1):
        paragraph = doc.Paragraphs.Item(index)
        if str(paragraph.Range.Text or "").strip():
            return index, paragraph.Range
    raise OfficeAutomationError("The active Word document has no text to format yet.")


def _find_word_matches(doc, match_text: str, match_case: bool) -> list[Any]:
    content_end = int(doc.Content.End)
    search = doc.Content
    find = search.Find
    find.ClearFormatting()
    find.Text = match_text
    find.Forward = True
    find.Wrap = 0  # wdFindStop
    find.MatchCase = match_case
    find.MatchWildcards = False
    find.Format = False
    found: list[Any] = []
    while len(found) < MAX_TEXT_MATCHES and find.Execute():
        start, end = int(search.Start), int(search.End)
        found.append(doc.Range(start, end))
        if end >= content_end or end <= start:
            break
        search.SetRange(end, content_end)
    return found


def _word_target_ranges(doc, app, args: dict[str, Any], target: str) -> tuple[list[Any], str]:
    if target == "last_paragraph":
        index, rng = _last_text_paragraph(doc)
        return [rng], f"paragraph {index}"
    if target == "paragraph":
        index = args.get("paragraph_index")
        count = int(doc.Paragraphs.Count)
        if isinstance(index, bool) or not isinstance(index, int) or not 1 <= index <= count:
            raise ValueError(f"paragraph_index must be a whole number from 1 to {count}. Use word_inspect to see paragraph numbers.")
        return [doc.Paragraphs.Item(index).Range], f"paragraph {index}"
    if target == "document":
        return [doc.Content], "the whole document"
    if target == "selection":
        try:
            selection = app.Selection
            start, end = int(selection.Start), int(selection.End)
        except Exception as exc:
            raise OfficeAutomationError("Could not read the current Word selection.") from exc
        if start == end:
            raise OfficeAutomationError("Nothing is selected in Word. Select the text to format first, or choose another target.")
        return [selection.Range], "the current selection"
    if target == "text_match":
        match_text = args.get("match_text")
        if not isinstance(match_text, str) or not match_text.strip() or len(match_text) > 200 or "\r" in match_text or "\x00" in match_text:
            raise ValueError("match_text must be 1 to 200 characters of text to find.")
        match_case = _flag(args, "match_case") or False
        ranges = _find_word_matches(doc, match_text, match_case)
        if not ranges:
            raise OfficeAutomationError(f"The text '{match_text[:60]}' was not found in the active Word document. Nothing was changed.")
        return ranges, f"{len(ranges)} occurrence(s) of the matched text"
    raise ValueError("target must be one of: last_paragraph, paragraph, selection, text_match, document.")


def _apply_word_style(rng, style_key: str) -> None:
    name = WORD_STYLE_DISPLAY[style_key]
    try:
        rng.Style = name
    except Exception:
        try:
            rng.Style = WORD_STYLES[style_key]  # WdBuiltinStyle constant for localized Word
        except Exception as exc:
            raise OfficeAutomationError(f"Word could not apply the '{name}' style to that text.") from exc


def _apply_word_spec(rng, spec: dict[str, Any]) -> None:
    if "style" in spec:
        _apply_word_style(rng, spec["style"])  # Apply first so explicit character formatting wins.
    font = rng.Font
    if "bold" in spec:
        font.Bold = spec["bold"]
    if "italic" in spec:
        font.Italic = spec["italic"]
    if "underline" in spec:
        font.Underline = 1 if spec["underline"] else 0  # wdUnderlineSingle / wdUnderlineNone
    if "strikethrough" in spec:
        font.StrikeThrough = spec["strikethrough"]
    if "font_name" in spec:
        font.Name = spec["font_name"]
    if "font_size" in spec:
        font.Size = spec["font_size"]
    if "font_color" in spec:
        font.Color = spec["font_color"]
    if "highlight" in spec:
        rng.HighlightColorIndex = spec["highlight"]
    if any(key in spec for key in ("alignment", "line_spacing", "space_before", "space_after")):
        paragraph = rng.ParagraphFormat
        if "alignment" in spec:
            paragraph.Alignment = spec["alignment"]
        if "line_spacing" in spec:
            paragraph.LineSpacingRule = 5  # wdLineSpaceMultiple
            paragraph.LineSpacing = spec["line_spacing"] * 12  # LinesToPoints(n)
        if "space_before" in spec:
            paragraph.SpaceBefore = spec["space_before"]
        if "space_after" in spec:
            paragraph.SpaceAfter = spec["space_after"]


def _word_format_text(args: dict[str, Any], app) -> dict[str, Any]:
    doc = base._active_word(app)
    base._require_macro_free_format("word", doc)
    base._writable(doc, "Word document")
    target = str(args.get("target") or "last_paragraph").strip().lower()
    spec = _parse_word_spec(args, target)
    ranges, description = _word_target_ranges(doc, app, args, target)
    for rng in ranges:
        _apply_word_spec(rng, spec)
    report = _readback_font(ranges[0].Font)
    return {
        "ok": True, "application": "word", "document_name": str(doc.Name)[:180],
        "target": target, "ranges_formatted": len(ranges), "applied": sorted(spec),
        "readback_first_range": report,
        "message": f"Formatted {description} in the active Word document. The change is not saved to disk yet.",
    }


# --------------------------------------------------------------------------- Excel

def _parse_excel_format(args: dict[str, Any]) -> dict[str, Any]:
    spec = _common_text_spec(args)
    if "fill_color" in args and args["fill_color"] not in (None, ""):
        spec["fill_color"] = parse_color(args["fill_color"], "fill_color", allow_none=True)
    if args.get("number_format") not in (None, ""):
        spec["number_format"] = validate_number_format(args["number_format"])
    alignment = _choice(args, "alignment", {name: name for name in ALIGNMENT_NAMES})
    if alignment is not None:
        spec["alignment"] = EXCEL_HALIGN[alignment]
    vertical = _choice(args, "vertical_alignment", EXCEL_VALIGN)
    if vertical is not None:
        spec["vertical_alignment"] = EXCEL_VALIGN[vertical]
    wrap = _flag(args, "wrap_text")
    if wrap is not None:
        spec["wrap_text"] = wrap
    borders = _choice(args, "borders", {mode: mode for mode in BORDER_MODES})
    if borders is not None:
        spec["borders"] = borders
    if args.get("column_width") is not None:
        spec["column_width"] = validate_number(args["column_width"], "column_width", 1, 255)
    if args.get("row_height") is not None:
        spec["row_height"] = validate_number(args["row_height"], "row_height", 1, 409)
    autofit = _flag(args, "autofit_columns")
    if autofit:
        spec["autofit_columns"] = True
    if not spec:
        raise ValueError(
            "Provide at least one formatting property, such as bold, font_color, fill_color, number_format, "
            "alignment, borders, column_width or autofit_columns."
        )
    return spec


def _apply_excel_spec(target, spec: dict[str, Any]) -> None:
    font = target.Font
    if "bold" in spec:
        font.Bold = spec["bold"]
    if "italic" in spec:
        font.Italic = spec["italic"]
    if "underline" in spec:
        font.Underline = 2 if spec["underline"] else -4142  # xlUnderlineStyleSingle / xlUnderlineStyleNone
    if "strikethrough" in spec:
        font.Strikethrough = spec["strikethrough"]
    if "font_name" in spec:
        font.Name = spec["font_name"]
    if "font_size" in spec:
        font.Size = spec["font_size"]
    if "font_color" in spec:
        font.Color = spec["font_color"]
    if "fill_color" in spec:
        interior = target.Interior
        if spec["fill_color"] is None:
            interior.Pattern = -4142  # xlNone
        else:
            interior.Pattern = 1  # xlSolid
            interior.Color = spec["fill_color"]
    if "number_format" in spec:
        target.NumberFormat = spec["number_format"]
    if "alignment" in spec:
        target.HorizontalAlignment = spec["alignment"]
    if "vertical_alignment" in spec:
        target.VerticalAlignment = spec["vertical_alignment"]
    if "wrap_text" in spec:
        target.WrapText = spec["wrap_text"]
    if "borders" in spec:
        mode = spec["borders"]
        if mode == "all":
            target.Borders.LineStyle = 1  # xlContinuous
            target.Borders.Weight = 2  # xlThin
        elif mode == "outline":
            target.BorderAround(1, 2)
        else:
            target.Borders.LineStyle = -4142  # xlNone
    if "column_width" in spec:
        target.ColumnWidth = spec["column_width"]
    if "row_height" in spec:
        target.RowHeight = spec["row_height"]
    if spec.get("autofit_columns"):
        target.Columns.AutoFit()


def _bounded_excel_range(args: dict[str, Any], app, *, limit: int):
    workbook = base._active_workbook(app)
    base._require_macro_free_format("excel", workbook)
    base._writable(workbook, "Excel workbook")
    address = base._validate_range_address(args.get("range"))
    sheet = base._worksheet(workbook, args.get("sheet_name"))
    target = sheet.Range(address)
    rows, columns = int(target.Rows.Count), int(target.Columns.Count)
    if rows * columns > limit:
        raise ValueError(f"This action is limited to {limit:,} cells; the requested range has {rows * columns:,}.")
    return workbook, sheet, target, address, rows, columns


def _excel_format_range(args: dict[str, Any], app) -> dict[str, Any]:
    workbook, sheet, target, address, rows, columns = _bounded_excel_range(args, app, limit=MAX_FORMAT_CELLS)
    spec = _parse_excel_format(args)
    with base._excel_events_suppressed(app):
        _apply_excel_spec(target, spec)
    first = _com_value(lambda: target.Cells(1, 1))
    readback: dict[str, Any] = {}
    if first is not None:
        readback = _readback_font(first.Font)
        fill = _com_value(lambda: first.Interior.Color)
        if "fill_color" in spec and fill is not None:
            readback["fill_color"] = color_hex(fill)
        if "number_format" in spec:
            readback["number_format"] = _com_value(lambda: str(first.NumberFormat)[:100])
        readback = {key: value for key, value in readback.items() if value is not None}
    return {
        "ok": True, "application": "excel", "workbook_name": str(workbook.Name)[:180],
        "sheet_name": str(sheet.Name)[:31], "range": address, "cells": rows * columns,
        "applied": sorted(spec), "readback_first_cell": readback,
        "message": f"Formatted {sheet.Name}!{address}. The workbook is not saved to disk yet.",
    }


# --- Excel formulas -------------------------------------------------------------------

ALLOWED_FUNCTIONS = frozenset("""
ABS CEILING CEILING.MATH FLOOR FLOOR.MATH EXP INT LN LOG LOG10 MOD MROUND PI POWER PRODUCT QUOTIENT
RAND RANDBETWEEN ROUND ROUNDDOWN ROUNDUP SIGN SQRT SUM SUMIF SUMIFS SUMPRODUCT TRUNC SIN COS TAN
RADIANS DEGREES
AVERAGE AVERAGEA AVERAGEIF AVERAGEIFS COUNT COUNTA COUNTBLANK COUNTIF COUNTIFS MAX MAXIFS MIN MINIFS
MEDIAN MODE MODE.SNGL LARGE SMALL RANK RANK.EQ RANK.AVG STDEV STDEV.S STDEV.P VAR VAR.S VAR.P
PERCENTILE PERCENTILE.INC QUARTILE QUARTILE.INC CORREL SLOPE INTERCEPT FORECAST FORECAST.LINEAR
IF IFS IFERROR IFNA AND OR NOT XOR TRUE FALSE SWITCH
CONCAT CONCATENATE EXACT FIND LEFT LEN LOWER MID PROPER REPLACE REPT RIGHT SEARCH SUBSTITUTE TEXT
TEXTJOIN TRIM UPPER VALUE
DATE DATEDIF DAY DAYS EDATE EOMONTH HOUR MINUTE MONTH NETWORKDAYS NOW SECOND TIME TODAY WEEKDAY
WEEKNUM WORKDAY YEAR YEARFRAC
CHOOSE COLUMN COLUMNS HLOOKUP INDEX MATCH ROW ROWS VLOOKUP XLOOKUP XMATCH LOOKUP
ISBLANK ISERROR ISERR ISNA ISNUMBER ISTEXT ISLOGICAL ISEVEN ISODD N NA
PMT FV PV NPV IRR RATE NPER
""".split())

_STRING_LITERAL = re.compile(r'"(?:[^"]|"")*"')
_QUOTED_SHEET = re.compile(r"'((?:[^']|'')+)'!")
_PLAIN_SHEET = re.compile(r"(?<![A-Za-z0-9_.'])([A-Za-z_][A-Za-z0-9_.]*)!")
_FUNCTION_CALL = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\(")
_COLUMN_RANGE = re.compile(r"\$?[A-Za-z]{1,3}:\$?[A-Za-z]{1,3}(?![A-Za-z0-9_(])")
_ROW_RANGE = re.compile(r"(?<![A-Za-z0-9_.])\$?[0-9]{1,7}:\$?[0-9]{1,7}(?![A-Za-z0-9_.(])")
_CELL_REF = re.compile(r"(?<![A-Za-z0-9_.$])\$?[A-Za-z]{1,3}\$?[0-9]{1,7}(?![A-Za-z0-9_.(])")
_NUMBER = re.compile(r"(?<![A-Za-z0-9_.$])(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_FORBIDDEN_FORMULA_CHARS = re.compile(r"[\x00-\x1f\x7f\[\]\\{}|@#;]")
_LEFTOVER_CHARS = re.compile(r"[^0-9A-Za-z_.$+\-*/^&=<>%,:()\s\"]")
_SHEET_NAME_BAD = re.compile(r"[:\\/?*\[\]]")


def validate_formula(value: Any) -> tuple[str, list[str]]:
    """Statically vet an Excel formula. Returns (formula, referenced same-workbook sheet names)."""
    if not isinstance(value, str):
        raise ValueError("formula must be text beginning with =, for example =SUM(B2:B10).")
    formula = value.strip()
    if not formula.startswith("=") or len(formula) < 2:
        raise ValueError("formula must begin with = and contain an expression, for example =SUM(B2:B10).")
    if len(formula) > MAX_FORMULA_CHARS:
        raise ValueError(f"formula is limited to {MAX_FORMULA_CHARS} characters.")
    if base.SENSITIVE_TEXT.search(formula):
        raise PermissionError("The formula appears to contain a password, key, token, or private secret and cannot be entered.")
    if _FORBIDDEN_FORMULA_CHARS.search(formula):
        raise ValueError(
            "The formula contains a character that is not supported (control characters, [ ] \\ { } | @ # ;). "
            "External workbook links, array constants, structured references and DDE are not allowed."
        )
    body = formula[1:]
    body = _STRING_LITERAL.sub('""', body)
    if body.count('"') % 2:
        raise ValueError("The formula has an unbalanced quotation mark.")

    sheets: list[str] = []

    def take_quoted(match: re.Match) -> str:
        name = match.group(1).replace("''", "'")
        if not 1 <= len(name) <= 31 or _SHEET_NAME_BAD.search(name):
            raise ValueError("The formula references an invalid worksheet name.")
        sheets.append(name)
        return " "

    body = _QUOTED_SHEET.sub(take_quoted, body)
    if "'" in body:
        raise ValueError("The formula contains an unmatched apostrophe in a sheet reference.")

    def take_plain(match: re.Match) -> str:
        sheets.append(match.group(1))
        return " "

    body = _PLAIN_SHEET.sub(take_plain, body)
    if "!" in body:
        raise ValueError("The formula contains an unsupported sheet reference (3D and external references are not allowed).")

    def take_function(match: re.Match) -> str:
        name = match.group(1).upper()
        if name.startswith("_XLFN."):
            name = name[6:]
        if name not in ALLOWED_FUNCTIONS:
            raise PermissionError(
                f"The function {match.group(1).upper()} is not on Ozzy's allowed list. Ozzy permits common math, statistics, "
                "logic, text, date, lookup and financial functions, and blocks external-data, volatile-reference and system functions."
            )
        return "("

    body = _FUNCTION_CALL.sub(take_function, body)
    depth = 0
    for char in body:
        depth += (char == "(") - (char == ")")
        if depth < 0:
            break
    if depth != 0:
        raise ValueError("The formula has unbalanced parentheses.")

    body = _COLUMN_RANGE.sub(" ", body)
    body = _ROW_RANGE.sub(" ", body)
    body = _CELL_REF.sub(" ", body)
    body = _NUMBER.sub(" ", body)
    for identifier in _IDENTIFIER.findall(body):
        if identifier.upper() in {"TRUE", "FALSE"}:
            continue
        raise PermissionError(
            f"'{identifier[:40]}' looks like a named range or defined name. Ozzy supports cell and range references "
            "(for example B2:B10 or Sheet2!A1) but not named ranges."
        )
    bad = _LEFTOVER_CHARS.search(body)
    if bad:
        raise ValueError(f"The formula contains an unsupported character: {bad.group(0)!r}.")
    return formula, sheets


_EXCEL_ERROR_TEXTS = {"#DIV/0!", "#N/A", "#NAME?", "#NULL!", "#NUM!", "#REF!", "#VALUE!", "#SPILL!", "#CALC!"}


def _excel_set_formula(args: dict[str, Any], app) -> dict[str, Any]:
    workbook, sheet, target, address, rows, columns = _bounded_excel_range(args, app, limit=MAX_FORMULA_CELLS)
    formula, referenced = validate_formula(args.get("formula"))
    existing = {str(workbook.Worksheets.Item(i).Name).casefold(): str(workbook.Worksheets.Item(i).Name)
                for i in range(1, int(workbook.Worksheets.Count) + 1)}
    for name in referenced:
        if name.casefold() not in existing:
            raise OfficeAutomationError(
                f"The formula refers to a worksheet named '{name}', which is not in the active workbook. "
                "No change was made (Excel would otherwise ask for an external file)."
            )
    with base._excel_events_suppressed(app):
        try:
            target.Formula = formula
        except Exception as exc:
            raise OfficeAutomationError(f"Excel rejected the formula: {str(exc)[:160]}. No change was made.") from exc
        try:
            target.Calculate()
        except Exception:
            pass
    first = _com_value(lambda: target.Cells(1, 1))
    shown = _com_value(lambda: str(first.Text)[:60]) if first is not None else None
    value = _com_value(lambda: first.Value2) if first is not None else None
    if isinstance(value, str):
        value = base._redact_sensitive_text(value)
    elif value is not None:
        value = base._normalise_com_value(value)
    payload = {
        "ok": True, "application": "excel", "workbook_name": str(workbook.Name)[:180],
        "sheet_name": str(sheet.Name)[:31], "range": address, "cells": rows * columns,
        "formula": formula, "first_cell_display": shown, "first_cell_value": value,
        "message": f"Entered the formula in {sheet.Name}!{address} ({rows * columns} cell(s)). The workbook is not saved to disk yet.",
    }
    if shown in _EXCEL_ERROR_TEXTS:
        payload["evaluation_error"] = shown
        payload["message"] = (
            f"The formula was entered in {sheet.Name}!{address} but Excel evaluated the first cell to {shown}. "
            "Check function names, references and argument counts. The workbook is not saved to disk yet."
        )
    return payload


# --------------------------------------------------------------------------- PowerPoint

PPT_TARGETS = ("title", "body", "all_text", "shape_index")
_PPT_TITLE_TYPES = {1, 3}
_PPT_BODY_TYPES = {2, 4, 7}


def _parse_ppt_spec(args: dict[str, Any]) -> dict[str, Any]:
    spec = _common_text_spec(args)
    alignment = _choice(args, "alignment", {name: name for name in ALIGNMENT_NAMES})
    if alignment is not None:
        spec["alignment"] = PPT_ALIGNMENT[alignment]
    if "shape_fill_color" in args and args["shape_fill_color"] not in (None, ""):
        spec["shape_fill_color"] = parse_color(args["shape_fill_color"], "shape_fill_color", allow_none=True)
    if not spec:
        raise ValueError("Provide at least one formatting property, such as bold, font_name, font_size, font_color, alignment or shape_fill_color.")
    return spec


def _tri_value(flag: bool) -> int:
    return -1 if flag else 0


def _slide_numbers(presentation, slide_number: Any) -> list[int]:
    total = int(presentation.Slides.Count)
    if total < 1:
        raise OfficeAutomationError("The active presentation has no slides.")
    if slide_number is None:
        return list(range(1, min(total, MAX_SLIDES_PER_ACTION) + 1))
    if isinstance(slide_number, bool) or not isinstance(slide_number, int) or not 1 <= slide_number <= total:
        raise ValueError(f"slide_number must be a whole number from 1 to {total}, or omitted to apply to every slide.")
    return [slide_number]


def _placeholder_type(shape) -> int | None:
    try:
        return int(shape.PlaceholderFormat.Type)
    except Exception:
        return None


def _ppt_text_shapes(slide, target: str, shape_index: Any) -> list[Any]:
    shapes = slide.Shapes
    count = min(int(shapes.Count), MAX_SHAPES_PER_SLIDE)
    if target == "shape_index":
        if isinstance(shape_index, bool) or not isinstance(shape_index, int) or not 1 <= shape_index <= int(shapes.Count):
            raise ValueError(f"shape_index must be a whole number from 1 to {int(shapes.Count)}. Use powerpoint_inspect to see shape numbers.")
        return [shapes.Item(shape_index)]
    found = []
    for index in range(1, count + 1):
        shape = shapes.Item(index)
        if target == "all_text":
            try:
                if bool(shape.HasTextFrame):
                    found.append(shape)
            except Exception:
                continue
            continue
        kind = _placeholder_type(shape)
        if target == "title" and kind in _PPT_TITLE_TYPES:
            found.append(shape)
        elif target == "body" and kind in _PPT_BODY_TYPES:
            found.append(shape)
    return found


def _apply_ppt_spec(shape, spec: dict[str, Any]) -> None:
    text_keys = {"bold", "italic", "underline", "strikethrough", "font_name", "font_size", "font_color", "alignment"}
    if text_keys & set(spec):
        text_range = shape.TextFrame.TextRange
        font = text_range.Font
        if "bold" in spec:
            font.Bold = _tri_value(spec["bold"])
        if "italic" in spec:
            font.Italic = _tri_value(spec["italic"])
        if "underline" in spec:
            font.Underline = _tri_value(spec["underline"])
        if "font_name" in spec:
            font.Name = spec["font_name"]
        if "font_size" in spec:
            font.Size = spec["font_size"]
        if "font_color" in spec:
            font.Color.RGB = spec["font_color"]
        if "alignment" in spec:
            text_range.ParagraphFormat.Alignment = spec["alignment"]
    if "shape_fill_color" in spec:
        fill = shape.Fill
        if spec["shape_fill_color"] is None:
            fill.Visible = 0
        else:
            fill.Visible = -1
            fill.Solid()
            fill.ForeColor.RGB = spec["shape_fill_color"]


def _powerpoint_format_text(args: dict[str, Any], app) -> dict[str, Any]:
    presentation = base._active_presentation(app)
    base._require_macro_free_format("powerpoint", presentation)
    base._writable(presentation, "PowerPoint presentation")
    target = str(args.get("target") or "").strip().lower()
    if target not in PPT_TARGETS:
        raise ValueError("target must be one of: title, body, all_text, shape_index.")
    spec = _parse_ppt_spec(args)
    shape_index = args.get("shape_index")
    slide_number = args.get("slide_number")
    if target == "shape_index" and slide_number is None:
        raise ValueError("slide_number is required when target is shape_index.")
    slides = _slide_numbers(presentation, slide_number)
    formatted = 0
    touched_slides: list[int] = []
    first_shape = None
    for number in slides:
        slide = presentation.Slides.Item(number)
        shapes = _ppt_text_shapes(slide, target, shape_index)
        for shape in shapes:
            _apply_ppt_spec(shape, spec)
            formatted += 1
            first_shape = first_shape or shape
        if shapes:
            touched_slides.append(number)
    if formatted == 0:
        raise OfficeAutomationError("No matching text shapes were found on the selected slide(s). Nothing was changed.")
    report: dict[str, Any] = {}
    if first_shape is not None:
        ppt_font = _com_value(lambda: first_shape.TextFrame.TextRange.Font)
        report = _readback_font(ppt_font, color=lambda: ppt_font.Color.RGB)
    return {
        "ok": True, "application": "powerpoint", "presentation_name": str(presentation.Name)[:180],
        "target": target, "shapes_formatted": formatted, "slides": touched_slides[:30],
        "applied": sorted(spec), "readback_first_shape": report,
        "message": f"Formatted {formatted} shape(s) on {len(touched_slides)} slide(s). The presentation is not saved to disk yet.",
    }


def _powerpoint_set_slide_background(args: dict[str, Any], app) -> dict[str, Any]:
    presentation = base._active_presentation(app)
    base._require_macro_free_format("powerpoint", presentation)
    base._writable(presentation, "PowerPoint presentation")
    color = parse_color(args.get("color"), "color")
    slides = _slide_numbers(presentation, args.get("slide_number"))
    for number in slides:
        slide = presentation.Slides.Item(number)
        slide.FollowMasterBackground = 0
        fill = slide.Background.Fill
        fill.Visible = -1
        fill.Solid()
        fill.ForeColor.RGB = color
    return {
        "ok": True, "application": "powerpoint", "presentation_name": str(presentation.Name)[:180],
        "slides_changed": len(slides), "color": color_hex(color),
        "message": f"Set the background color of {len(slides)} slide(s) to {color_hex(color)}. The presentation is not saved to disk yet.",
    }


# --------------------------------------------------------------------------- dispatch

def execute(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "word_format_text":
        return base._with_app("word", lambda app: _word_format_text(args, app))
    if name == "excel_format_range":
        return base._with_app("excel", lambda app: _excel_format_range(args, app))
    if name == "excel_set_formula":
        return base._with_app("excel", lambda app: _excel_set_formula(args, app))
    if name == "powerpoint_format_text":
        return base._with_app("powerpoint", lambda app: _powerpoint_format_text(args, app))
    if name == "powerpoint_set_slide_background":
        return base._with_app("powerpoint", lambda app: _powerpoint_set_slide_background(args, app))
    raise ValueError(f"Unsupported Office styling action: {name}")
