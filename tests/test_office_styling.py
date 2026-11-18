import re
import unittest
from unittest import mock

import office_automation as office
import office_styling as styling
import workflow_engine as engine


class Node:
    """Fake COM object: records writes; unknown reads return a child Node; calls are recorded."""

    def __init__(self, **values):
        self.__dict__.update(values)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        child = Node()
        self.__dict__[name] = child
        return child

    def __call__(self, *args, **kwargs):
        self.__dict__.setdefault("_calls", []).append((args, kwargs))
        return Node()


def bgr(red, green, blue):
    return red | (green << 8) | (blue << 16)


# --------------------------------------------------------------------------- validators

class ColorTests(unittest.TestCase):
    def test_hex_and_names_use_office_bgr_order(self):
        self.assertEqual(styling.parse_color("#FF0000"), 255)
        self.assertEqual(styling.parse_color("0000ff"), 0xFF0000)
        self.assertEqual(styling.parse_color("#1F4E79"), bgr(0x1F, 0x4E, 0x79))
        self.assertEqual(styling.parse_color("red"), 255)
        self.assertEqual(styling.parse_color("Dark-Green"), bgr(0, 100, 0))
        self.assertEqual(styling.parse_color("#fa0"), bgr(0xFF, 0xAA, 0x00))

    def test_none_only_when_allowed(self):
        self.assertIsNone(styling.parse_color("none", allow_none=True))
        with self.assertRaises(ValueError):
            styling.parse_color("none")

    def test_rejects_invalid_colors(self):
        for value in ("", "  ", "notacolor", "#12345", "#GGGGGG", None, 5, "x" * 50):
            with self.subTest(value=value), self.assertRaises(ValueError):
                styling.parse_color(value)

    def test_color_hex_round_trip(self):
        self.assertEqual(styling.color_hex(styling.parse_color("#1F4E79")), "#1F4E79")
        self.assertIsNone(styling.color_hex("junk"))
        self.assertIsNone(styling.color_hex(-5))


class ScalarValidatorTests(unittest.TestCase):
    def test_font_name(self):
        self.assertEqual(styling.validate_font_name(" Times New Roman "), "Times New Roman")
        self.assertEqual(styling.validate_font_name("Segoe UI Semibold"), "Segoe UI Semibold")
        self.assertEqual(styling.validate_font_name("Arial\r\n"), "Arial")  # surrounding whitespace is trimmed
        for value in ("", "Arial; DROP", "a" * 80, None, "Ar\nial", "Ar\x00ial"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                styling.validate_font_name(value)

    def test_font_size(self):
        self.assertEqual(styling.validate_font_size(14), 14)
        self.assertEqual(styling.validate_font_size(11.5), 11.5)
        self.assertEqual(styling.validate_font_size(12.0), 12)
        for value in (0, 3, 401, True, "12", float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                styling.validate_font_size(value)

    def test_number_format_presets_and_codes(self):
        self.assertEqual(styling.validate_number_format("Currency"), "$#,##0.00")
        self.assertEqual(styling.validate_number_format("0.0%"), "0.0%")
        for value in ("", None, "x" * 101, "bad\x00code", "line\nbreak"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                styling.validate_number_format(value)


class FormulaValidationTests(unittest.TestCase):
    def test_accepts_common_formulas(self):
        good = [
            "=SUM(B2:C2)", "=SUM(B2:B10)/COUNT(B2:B10)", '=IF(B2>=50,"Pass","Fail")', "=A1*50%",
            "=$A$1*1E5", "=SUM(A:A)", "=SUM(1:3)", "=A1<>B1", '=A1&" items"', "=-A1^2", "=TRUE",
            "=ROUND(AVERAGE(B2:B9),2)", '=TEXT(A1,"0.00")', "=PMT(0.05/12,36,-A1)", "=1+2",
            "=VLOOKUP(A2,B:D,3,FALSE)", "=XLOOKUP(A2,B:B,C:C)", "=_xlfn.XLOOKUP(A2,B:B,C:C)",
            '=IF(A1="","",A1)', "=STDEV.S(B2:B20)", "=IFERROR(A1/B1,0)",
        ]
        for formula in good:
            with self.subTest(formula=formula):
                self.assertEqual(styling.validate_formula(formula)[0], formula)

    def test_records_same_workbook_sheet_references(self):
        self.assertEqual(styling.validate_formula("=Sheet2!A1+1")[1], ["Sheet2"])
        self.assertEqual(styling.validate_formula("='My Sheet'!A1*2")[1], ["My Sheet"])
        self.assertEqual(styling.validate_formula("=SUM(Data!A:A)+Data!B1")[1], ["Data", "Data"])
        self.assertEqual(styling.validate_formula("='It''s'!A1")[1], ["It's"])

    def test_rejects_unsafe_or_unsupported_formulas(self):
        bad = [
            "SUM(A1)", "=", "  ", '=INDIRECT("A1")', '=HYPERLINK("http://x","y")', '=WEBSERVICE("http://x")',
            "=OFFSET(A1,1,1)", '=CELL("filename")', "=INFO(\"directory\")",
            "=cmd|' /C calc'!A0", "=SUM([Book2.xlsx]Sheet1!A1)", "=SUM('C:\\x\\[Book.xlsx]Sheet1'!A1)",
            "=SUM(MyName)", "=Sales2024*2", "=AB1CD2+1", "=SUM(A1:A3", "=SUM(A1:A3))", '=A1&"unterminated',
            "=A1+@B1", "={1,2,3}", "=A1#", "=SUM(Sheet1:Sheet3!A1)", "=A1;B1", "=SUM(A1)\n+1",
            "=A1\u00d72", '="password=abc123"', "=" + "A1+" * 400 + "1",
        ]
        for formula in bad:
            with self.subTest(formula=formula), self.assertRaises((ValueError, PermissionError)):
                styling.validate_formula(formula)

    def test_rejects_non_strings(self):
        for value in (None, 5, ["=A1"]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                styling.validate_formula(value)


# --------------------------------------------------------------------------- Word fakes

class WordFind:
    def __init__(self, rng):
        self.rng = rng
        self.Text = ""
        self.MatchCase = False

    def ClearFormatting(self):
        pass

    def Execute(self):
        text = self.rng.doc.text[self.rng.Start:self.rng.End]
        needle = self.Text
        hay, needle = (text, needle) if self.MatchCase else (text.lower(), needle.lower())
        index = hay.find(needle)
        if index < 0:
            return False
        origin = self.rng.Start
        self.rng.Start, self.rng.End = origin + index, origin + index + len(needle)
        return True


class WordRange:
    def __init__(self, doc, start, end):
        self.doc, self.Start, self.End = doc, start, end
        self.Font = Node()
        self.ParagraphFormat = Node()
        self.HighlightColorIndex = None
        self.Find = WordFind(self)
        self.Style = None

    @property
    def Text(self):
        return self.doc.text[self.Start:self.End]

    def SetRange(self, start, end):
        self.Start, self.End = start, end


class StrictStyleRange(WordRange):
    """Rejects style *names* like a non-English Word; accepts WdBuiltinStyle integers."""

    def __setattr__(self, name, value):
        if name == "Style" and isinstance(value, str):
            raise Exception("style name not found")
        super().__setattr__(name, value)


class WordParagraphs:
    def __init__(self, doc, range_class):
        self.items = []
        position = 0
        for chunk in doc.text.split("\r")[:-1]:
            end = position + len(chunk) + 1
            paragraph = Node(Range=range_class(doc, position, end))
            self.items.append(paragraph)
            position = end
        self.Count = len(self.items)

    def Item(self, index):
        return self.items[index - 1]


class WordDoc:
    def __init__(self, text, *, read_only=False, save_format=12, range_class=WordRange):
        self.text = text
        self.Name = "Report.docx"
        self.ReadOnly = read_only
        self.SaveFormat = save_format
        self.Content = range_class(self, 0, len(text))
        self.created = []
        self._range_class = range_class
        self.Paragraphs = WordParagraphs(self, range_class)

    def Range(self, start, end):
        created = self._range_class(self, start, end)
        self.created.append(created)
        return created


def word_app(doc, selection=None):
    return Node(ActiveDocument=doc, Selection=selection if selection is not None else Node(Start=0, End=0))


class WordFormatTests(unittest.TestCase):
    def setUp(self):
        self.doc = WordDoc("Title\rBody text with Total and total\r\r")
        self.app = word_app(self.doc)

    def run_format(self, **args):
        return styling._word_format_text(args, self.app)

    def test_last_paragraph_means_last_paragraph_with_text(self):
        result = self.run_format(font_name="Arial", font_size=14, font_color="#FF0000", bold=True, underline=True)
        font = self.doc.Paragraphs.Item(2).Range.Font
        self.assertEqual((font.Name, font.Size, font.Color, font.Bold, font.Underline), ("Arial", 14, 255, True, 1))
        self.assertEqual(self.doc.Paragraphs.Item(1).Range.Font.__dict__, {})  # untouched
        self.assertEqual(self.doc.Paragraphs.Item(3).Range.Font.__dict__, {})  # empty trailing paragraph untouched
        self.assertTrue(result["ok"])
        self.assertEqual(result["ranges_formatted"], 1)
        self.assertIn("not saved", result["message"])
        self.assertEqual(result["readback_first_range"]["font_name"], "Arial")

    def test_paragraph_target_and_paragraph_level_properties(self):
        self.run_format(target="paragraph", paragraph_index=1, alignment="center", line_spacing=1.5,
                        space_before=6, space_after=12, style="Heading 2")
        rng = self.doc.Paragraphs.Item(1).Range
        self.assertEqual(rng.Style, "Heading 2")
        self.assertEqual(rng.ParagraphFormat.Alignment, 1)
        self.assertEqual(rng.ParagraphFormat.LineSpacingRule, 5)
        self.assertEqual(rng.ParagraphFormat.LineSpacing, 18)
        self.assertEqual((rng.ParagraphFormat.SpaceBefore, rng.ParagraphFormat.SpaceAfter), (6, 12))

    def test_paragraph_index_validation(self):
        for index in (0, 99, "2", True, None):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.run_format(target="paragraph", paragraph_index=index, bold=True)

    def test_text_match_formats_every_occurrence_case_insensitively(self):
        result = self.run_format(target="text_match", match_text="total", bold=True, highlight_color="yellow")
        self.assertEqual(result["ranges_formatted"], 2)
        self.assertEqual([r.Text for r in self.doc.created], ["Total", "total"])
        for rng in self.doc.created:
            self.assertTrue(rng.Font.Bold)
            self.assertEqual(rng.HighlightColorIndex, 7)

    def test_text_match_respects_match_case(self):
        result = self.run_format(target="text_match", match_text="total", match_case=True, italic=True)
        self.assertEqual(result["ranges_formatted"], 1)

    def test_text_match_rejects_paragraph_level_properties_and_missing_text(self):
        with self.assertRaises(ValueError):
            self.run_format(target="text_match", match_text="Total", alignment="right")
        with self.assertRaises(office.OfficeAutomationError):
            self.run_format(target="text_match", match_text="absent", bold=True)
        with self.assertRaises(ValueError):
            self.run_format(target="text_match", match_text="", bold=True)

    def test_selection_target(self):
        selected = WordRange(self.doc, 6, 10)
        app = word_app(self.doc, selection=Node(Start=6, End=10, Range=selected))
        styling._word_format_text({"target": "selection", "font_color": "blue"}, app)
        self.assertEqual(selected.Font.Color, 0xFF0000)

    def test_collapsed_selection_is_refused(self):
        with self.assertRaises(office.OfficeAutomationError):
            self.run_format(target="selection", bold=True)

    def test_document_target(self):
        self.run_format(target="document", font_name="Calibri")
        self.assertEqual(self.doc.Content.Font.Name, "Calibri")

    def test_style_falls_back_to_builtin_id_for_localised_word(self):
        doc = WordDoc("Hello\r", range_class=StrictStyleRange)
        styling._word_format_text({"style": "Heading 1"}, word_app(doc))
        self.assertEqual(doc.Paragraphs.Item(1).Range.Style, -2)

    def test_requires_a_property_and_valid_values(self):
        with self.assertRaises(ValueError):
            self.run_format()
        for bad in ({"bold": "yes"}, {"font_size": 1000}, {"font_color": "nope"}, {"alignment": "diagonal"},
                    {"highlight_color": "ultraviolet"}, {"style": "Heading 9"}, {"line_spacing": 9}, {"target": "everything"}):
            with self.subTest(args=bad), self.assertRaises(ValueError):
                self.run_format(**bad)

    def test_read_only_and_legacy_documents_are_not_changed(self):
        read_only = WordDoc("Hi\r", read_only=True)
        with self.assertRaises(PermissionError):
            styling._word_format_text({"bold": True}, word_app(read_only))
        legacy = WordDoc("Hi\r", save_format=0)
        with self.assertRaises(office.OfficeAutomationError):
            styling._word_format_text({"bold": True}, word_app(legacy))
        self.assertEqual(legacy.Paragraphs.Item(1).Range.Font.__dict__, {})

    def test_empty_document_has_nothing_to_format(self):
        doc = WordDoc("\r")
        with self.assertRaises(office.OfficeAutomationError):
            styling._word_format_text({"bold": True}, word_app(doc))


class WordOutlineTests(unittest.TestCase):
    def test_outline_lists_numbered_non_empty_paragraphs(self):
        doc = WordDoc("Title\r\rBody one\rBody two\r")
        outline, start = office._word_outline(doc, None)
        self.assertEqual(start, 1)
        self.assertEqual([(item["index"], item["text"]) for item in outline], [(1, "Title"), (3, "Body one"), (4, "Body two")])

    def test_outline_from_paragraph_and_validation(self):
        doc = WordDoc("A\rB\rC\r")
        outline, start = office._word_outline(doc, 2)
        self.assertEqual((start, [item["index"] for item in outline]), (2, [2, 3]))
        for bad in (0, 9, "1", True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                office._word_outline(doc, bad)


# --------------------------------------------------------------------------- Excel fakes

def _column_number(letters):
    number = 0
    for char in letters:
        number = number * 26 + (ord(char) - 64)
    return number


class ExcelColumns:
    def __init__(self, count):
        self.Count = count
        self.autofit = False

    def AutoFit(self):
        self.autofit = True


class ExcelRange:
    def __init__(self, address, *, reject_formula=False, shown="42"):
        match = re.fullmatch(r"([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?", address)
        first_col, first_row = _column_number(match.group(1)), int(match.group(2))
        last_col = _column_number(match.group(3)) if match.group(3) else first_col
        last_row = int(match.group(4)) if match.group(4) else first_row
        self.Rows = Node(Count=last_row - first_row + 1)
        self.Columns = ExcelColumns(last_col - first_col + 1)
        self.Font = Node()
        self.Interior = Node()
        self.Borders = Node()
        self.cell = Node(Font=self.Font, Interior=self.Interior, Text=shown, Value2=shown, NumberFormat="General")
        self.reject_formula = reject_formula
        self.calculated = False

    def __setattr__(self, name, value):
        if name == "Formula" and self.__dict__.get("reject_formula"):
            raise Exception("We found a problem with this formula")
        super().__setattr__(name, value)

    def Cells(self, row, column):
        return self.cell

    def Calculate(self):
        self.calculated = True

    def BorderAround(self, line_style, weight):
        self.border_around = (line_style, weight)


class ExcelSheets:
    def __init__(self, names):
        self.sheets = [Node(Name=name, Cells=Node()) for name in names]

    @property
    def Count(self):
        return len(self.sheets)

    def Item(self, index):
        return self.sheets[index - 1]

    def __call__(self, name):
        for sheet in self.sheets:
            if sheet.Name.casefold() == str(name).casefold():
                return sheet
        raise Exception("not found")


class ExcelSheet:
    def __init__(self, name, **range_options):
        self.Name = name
        self.Cells = Node()
        self.ranges = {}
        self.range_options = range_options

    def Range(self, address):
        self.ranges[address] = ExcelRange(address, **self.range_options)
        return self.ranges[address]


def excel_app(*, sheet_names=("Sheet1", "Data"), read_only=False, file_format=51, **range_options):
    active = ExcelSheet("Sheet1", **range_options)
    workbook = Node(Name="Budget.xlsx", ReadOnly=read_only, FileFormat=file_format, ActiveSheet=active,
                    Worksheets=ExcelSheets(sheet_names))
    return Node(ActiveWorkbook=workbook, EnableEvents=True), active


class ExcelFormatTests(unittest.TestCase):
    def test_formats_font_fill_numbers_alignment_and_borders(self):
        app, sheet = excel_app()
        result = styling._excel_format_range({
            "range": "a1:d1", "bold": True, "italic": False, "underline": True, "font_name": "Arial",
            "font_size": 12, "font_color": "#FFFFFF", "fill_color": "#1F4E79", "number_format": "currency",
            "alignment": "center", "vertical_alignment": "middle", "wrap_text": True, "borders": "all",
            "column_width": 18, "row_height": 24, "autofit_columns": True,
        }, app)
        target = sheet.ranges["A1:D1"]
        self.assertEqual((target.Font.Bold, target.Font.Italic, target.Font.Underline), (True, False, 2))
        self.assertEqual((target.Font.Name, target.Font.Size, target.Font.Color), ("Arial", 12, 0xFFFFFF))
        self.assertEqual((target.Interior.Pattern, target.Interior.Color), (1, bgr(0x1F, 0x4E, 0x79)))
        self.assertEqual(target.NumberFormat, "$#,##0.00")
        self.assertEqual((target.HorizontalAlignment, target.VerticalAlignment, target.WrapText), (-4108, -4108, True))
        self.assertEqual((target.Borders.LineStyle, target.Borders.Weight), (1, 2))
        self.assertEqual((target.ColumnWidth, target.RowHeight), (18, 24))
        self.assertTrue(target.Columns.autofit)
        self.assertEqual(result["cells"], 4)
        self.assertEqual(result["range"], "A1:D1")
        self.assertTrue(app.EnableEvents)  # events restored

    def test_clear_fill_and_border_modes(self):
        app, sheet = excel_app()
        styling._excel_format_range({"range": "B2:C3", "fill_color": "none", "borders": "outline"}, app)
        target = sheet.ranges["B2:C3"]
        self.assertEqual(target.Interior.Pattern, -4142)
        self.assertEqual(target.border_around, (1, 2))
        styling._excel_format_range({"range": "B2:C3", "borders": "none"}, app)
        self.assertEqual(sheet.ranges["B2:C3"].Borders.LineStyle, -4142)

    def test_requires_property_and_bounds_range_size(self):
        app, _ = excel_app()
        with self.assertRaises(ValueError):
            styling._excel_format_range({"range": "A1"}, app)
        with self.assertRaises(ValueError):
            styling._excel_format_range({"range": "A1:Z5000", "bold": True}, app)
        for bad in ({"range": "MyName", "bold": True}, {"range": "A1", "borders": "dotted"},
                    {"range": "A1", "column_width": 999}, {"range": "A1", "fill_color": "nope"},
                    {"range": "A1", "bold": "true"}):
            with self.subTest(args=bad), self.assertRaises(ValueError):
                styling._excel_format_range(bad, app)

    def test_read_only_and_legacy_workbooks_are_not_changed(self):
        app, sheet = excel_app(read_only=True)
        with self.assertRaises(PermissionError):
            styling._excel_format_range({"range": "A1", "bold": True}, app)
        app, sheet = excel_app(file_format=56)  # .xls
        with self.assertRaises(office.OfficeAutomationError):
            styling._excel_format_range({"range": "A1", "bold": True}, app)
        self.assertEqual(sheet.ranges, {})


class ExcelFormulaTests(unittest.TestCase):
    def test_enters_formula_over_range_and_reports_result(self):
        app, sheet = excel_app(shown="7")
        result = styling._excel_set_formula({"range": "d2:d10", "formula": "=SUM(B2:C2)"}, app)
        target = sheet.ranges["D2:D10"]
        self.assertEqual(target.Formula, "=SUM(B2:C2)")
        self.assertTrue(target.calculated)
        self.assertEqual((result["cells"], result["first_cell_display"]), (9, "7"))
        self.assertNotIn("evaluation_error", result)
        self.assertTrue(app.EnableEvents)

    def test_references_to_other_sheets_must_exist(self):
        app, sheet = excel_app()
        result = styling._excel_set_formula({"range": "A1", "formula": "=Data!A1+1"}, app)
        self.assertEqual(sheet.ranges["A1"].Formula, "=Data!A1+1")
        self.assertTrue(result["ok"])
        app, sheet = excel_app()
        with self.assertRaises(office.OfficeAutomationError):
            styling._excel_set_formula({"range": "A1", "formula": "=Missing!A1+1"}, app)
        self.assertNotIn("Formula", sheet.ranges["A1"].__dict__)  # nothing was written

    def test_unsafe_formulas_never_reach_excel(self):
        app, sheet = excel_app()
        for formula in ('=INDIRECT("A1")', "=SUM(MyName)", "=SUM([x.xlsx]Sheet1!A1)", "A1"):
            with self.subTest(formula=formula), self.assertRaises((ValueError, PermissionError)):
                styling._excel_set_formula({"range": "A1", "formula": formula}, app)
        self.assertNotIn("Formula", sheet.ranges.get("A1", Node()).__dict__)

    def test_excel_rejection_becomes_clear_error_and_restores_events(self):
        app, _ = excel_app(reject_formula=True)
        with self.assertRaises(office.OfficeAutomationError) as caught:
            styling._excel_set_formula({"range": "A1", "formula": "=SUM(B2:B3)"}, app)
        self.assertIn("rejected", str(caught.exception))
        self.assertTrue(app.EnableEvents)

    def test_evaluation_errors_are_reported(self):
        app, _ = excel_app(shown="#NAME?")
        result = styling._excel_set_formula({"range": "A1", "formula": "=SUM(B2:B3)"}, app)
        self.assertEqual(result["evaluation_error"], "#NAME?")
        self.assertIn("#NAME?", result["message"])
        app, _ = excel_app(shown="########")  # a too-narrow column is not a formula error
        self.assertNotIn("evaluation_error", styling._excel_set_formula({"range": "A1", "formula": "=A2*1000000"}, app))

    def test_formula_range_is_bounded(self):
        app, _ = excel_app()
        with self.assertRaises(ValueError):
            styling._excel_set_formula({"range": "A1:A5000", "formula": "=B1"}, app)

    def test_read_only_workbook_is_not_changed(self):
        app, _ = excel_app(read_only=True)
        with self.assertRaises(PermissionError):
            styling._excel_set_formula({"range": "A1", "formula": "=1+1"}, app)


# --------------------------------------------------------------------------- PowerPoint fakes

class PptShape:
    def __init__(self, name, placeholder_type=None, has_text=True):
        self.Name = name
        self.HasTextFrame = has_text
        self.TextFrame = Node(HasText=has_text, TextRange=Node(Font=Node(Color=Node()), ParagraphFormat=Node()))
        self.Fill = Node()
        if placeholder_type is not None:
            self.PlaceholderFormat = Node(Type=placeholder_type)
        else:
            self.PlaceholderFormat = None  # property access on a non-placeholder raises in real COM


class PptShapes:
    def __init__(self, shapes):
        self.shapes = shapes

    @property
    def Count(self):
        return len(self.shapes)

    def Item(self, index):
        return self.shapes[index - 1]


class PptSlide:
    def __init__(self, shapes):
        self.Shapes = PptShapes(shapes)
        self.Background = Node(Fill=Node())
        self.FollowMasterBackground = -1


class PptSlides:
    def __init__(self, slides):
        self.slides = slides
        self.Count = len(slides)

    def Item(self, index):
        return self.slides[index - 1]


def ppt_app(*, read_only=False, full_name=r"C:\Users\Demo\Documents\Deck.pptx"):
    slides = [
        PptSlide([PptShape("Title 1", 1), PptShape("Content 2", 2), PptShape("Footer", None)]),
        PptSlide([PptShape("Title 1", 1), PptShape("Picture", None, has_text=False)]),
    ]
    presentation = Node(Name="Deck.pptx", FullName=full_name, ReadOnly=read_only, Slides=PptSlides(slides))
    return Node(ActivePresentation=presentation), slides


class PowerPointFormatTests(unittest.TestCase):
    def test_formats_titles_on_every_slide(self):
        app, slides = ppt_app()
        result = styling._powerpoint_format_text({
            "target": "title", "font_name": "Georgia", "font_size": 40, "font_color": "navy",
            "bold": True, "italic": False, "underline": True, "alignment": "center",
        }, app)
        for slide in slides:
            text_range = slide.Shapes.Item(1).TextFrame.TextRange
            self.assertEqual((text_range.Font.Name, text_range.Font.Size), ("Georgia", 40))
            self.assertEqual(text_range.Font.Color.RGB, bgr(0, 0, 128))
            self.assertEqual((text_range.Font.Bold, text_range.Font.Italic, text_range.Font.Underline), (-1, 0, -1))
            self.assertEqual(text_range.ParagraphFormat.Alignment, 2)
        self.assertEqual(slides[0].Shapes.Item(2).TextFrame.TextRange.Font.__dict__.get("Name"), None)
        self.assertEqual((result["shapes_formatted"], result["slides"]), (2, [1, 2]))
        self.assertEqual(result["readback_first_shape"]["font_name"], "Georgia")

    def test_body_and_all_text_targets(self):
        app, slides = ppt_app()
        result = styling._powerpoint_format_text({"target": "body", "slide_number": 1, "font_size": 20}, app)
        self.assertEqual(result["shapes_formatted"], 1)
        self.assertEqual(slides[0].Shapes.Item(2).TextFrame.TextRange.Font.Size, 20)
        result = styling._powerpoint_format_text({"target": "all_text", "font_color": "red"}, app)
        self.assertEqual(result["shapes_formatted"], 4)  # picture without a text frame is skipped

    def test_shape_index_and_fill(self):
        app, slides = ppt_app()
        styling._powerpoint_format_text({"target": "shape_index", "slide_number": 1, "shape_index": 3,
                                         "shape_fill_color": "#FFF2CC", "bold": True}, app)
        shape = slides[0].Shapes.Item(3)
        self.assertEqual(shape.Fill.Visible, -1)
        self.assertEqual(shape.Fill.ForeColor.RGB, bgr(0xFF, 0xF2, 0xCC))
        styling._powerpoint_format_text({"target": "shape_index", "slide_number": 1, "shape_index": 3,
                                         "shape_fill_color": "none"}, app)
        self.assertEqual(shape.Fill.Visible, 0)

    def test_validation(self):
        app, _ = ppt_app()
        for bad in ({"target": "title"}, {"target": "bogus", "bold": True},
                    {"target": "shape_index", "shape_index": 1, "bold": True},
                    {"target": "shape_index", "slide_number": 1, "shape_index": 99, "bold": True},
                    {"target": "title", "slide_number": 9, "bold": True},
                    {"target": "title", "slide_number": True, "bold": True}):
            with self.subTest(args=bad), self.assertRaises(ValueError):
                styling._powerpoint_format_text(bad, app)

    def test_no_matching_shapes_changes_nothing(self):
        app, slides = ppt_app()
        with self.assertRaises(office.OfficeAutomationError):
            styling._powerpoint_format_text({"target": "body", "slide_number": 2, "bold": True}, app)

    def test_read_only_and_macro_decks_are_not_changed(self):
        app, _ = ppt_app(read_only=True)
        with self.assertRaises(PermissionError):
            styling._powerpoint_format_text({"target": "title", "bold": True}, app)
        app, _ = ppt_app(full_name=r"C:\Users\Demo\Documents\Deck.pptm")
        with self.assertRaises(office.OfficeAutomationError):
            styling._powerpoint_format_text({"target": "title", "bold": True}, app)

    def test_slide_background(self):
        app, slides = ppt_app()
        result = styling._powerpoint_set_slide_background({"color": "#FFF2CC", "slide_number": 2}, app)
        self.assertEqual(result["slides_changed"], 1)
        self.assertEqual(slides[1].FollowMasterBackground, 0)
        self.assertEqual(slides[1].Background.Fill.ForeColor.RGB, bgr(0xFF, 0xF2, 0xCC))
        self.assertEqual(slides[0].FollowMasterBackground, -1)
        result = styling._powerpoint_set_slide_background({"color": "black"}, app)
        self.assertEqual(result["slides_changed"], 2)
        with self.assertRaises(ValueError):
            styling._powerpoint_set_slide_background({"color": "nope"}, app)


# --------------------------------------------------------------------------- inspect extensions

class InspectExtensionTests(unittest.TestCase):
    def excel_with(self, value2, formula):
        selected = Node(Rows=Node(Count=1), Columns=Node(Count=2), Value2=value2, Formula=formula)
        sheet = Node(Name="Sheet1", Cells=Node(), Range=lambda address: selected)
        workbook = Node(Name="Budget.xlsx", ActiveSheet=sheet, Worksheets=ExcelSheets(["Sheet1"]))
        return Node(ActiveWorkbook=workbook)

    def test_excel_inspect_returns_formulas_only_when_asked(self):
        app = self.excel_with(((3, "Total"),), (("=1+2", "Total"),))
        plain = office._excel_inspect_range({"range": "A1:B1"}, app)
        self.assertNotIn("formulas", plain)
        self.assertEqual(plain["values"], [[3, "Total"]])
        with_formulas = office._excel_inspect_range({"range": "A1:B1", "include_formulas": True}, app)
        self.assertEqual(with_formulas["formulas"], [["=1+2", "Total"]])
        self.assertEqual(with_formulas["values"], [[3, "Total"]])
        self.assertNotIn("Formulas were not returned", with_formulas["message"])

    def test_excel_inspect_redacts_secrets_in_formula_text(self):
        app = self.excel_with((("x", "y"),), (('="password: hunter2"', "y"),))
        result = office._excel_inspect_range({"range": "A1:B1", "include_formulas": True}, app)
        self.assertNotIn("hunter2", str(result["formulas"]))

    def ppt_with(self, slide_count):
        def shape(name, text):
            return Node(Name=name, HasTextFrame=True, TextFrame=Node(HasText=True, TextRange=Node(Text=text)))
        slides = [Node(Shapes=PptShapes([shape("Title 1", f"Slide {n} title"), shape("Content 2", f"Slide {n} body")]))
                  for n in range(1, slide_count + 1)]
        return Node(ActivePresentation=Node(Name="Deck.pptx", Slides=PptSlides(slides)))

    def test_powerpoint_inspect_lists_numbered_shapes(self):
        result = office._powerpoint_inspect({}, self.ppt_with(2))
        first = result["slides"][0]
        self.assertEqual(first["shapes"], [{"index": 1, "name": "Title 1", "has_text": True},
                                           {"index": 2, "name": "Content 2", "has_text": True}])
        self.assertIn("Slide 1 title", first["text"])

    def test_powerpoint_inspect_defaults_to_newest_30_and_honours_from_slide(self):
        app = self.ppt_with(40)
        newest = office._powerpoint_inspect({}, app)
        self.assertEqual((newest["slides"][0]["slide_number"], newest["slides"][-1]["slide_number"]), (11, 40))
        early = office._powerpoint_inspect({"from_slide": 1}, app)
        self.assertEqual((early["slides"][0]["slide_number"], early["slides_inspected"]), (1, 30))
        for bad in (0, 41, "3", True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                office._powerpoint_inspect({"from_slide": bad}, app)


# --------------------------------------------------------------------------- wiring

class StylingWiringTests(unittest.TestCase):
    def test_actions_are_dispatched_by_execute_action(self):
        office.resume_actions()
        calls = []
        with mock.patch.object(styling, "execute", side_effect=lambda name, args: calls.append(name) or {"ok": True}):
            for name in sorted(styling.ACTIONS):
                self.assertEqual(office.execute_action(name, {"x": 1}), {"ok": True})
        self.assertEqual(sorted(calls), sorted(styling.ACTIONS))
        with self.assertRaises(ValueError):
            office.execute_action("word_delete_everything", {})

    def test_workflow_engine_allows_stage8_actions_but_not_interactive_ones(self):
        for name in ("word_format_text", "excel_format_range", "excel_set_formula", "powerpoint_format_text",
                     "powerpoint_set_slide_background", "office_list_open_documents", "office_activate_document"):
            self.assertIn(name, engine.WORKFLOW_ACTIONS)
        self.assertIn("office_list_open_documents", engine.VERIFY_ACTIONS)
        for name in ("office_open_document", "office_save_new"):
            self.assertNotIn(name, engine.WORKFLOW_ACTIONS)


if __name__ == "__main__":
    unittest.main()
