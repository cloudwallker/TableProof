from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from openpyxl import Workbook

from tableproof.errors import InputError
from tableproof.xlsx import inspect_workbook, read_range


def workbook_bytes(cells=None, sheet_xml=None, extra=None):
    book = Workbook()
    book.active.title = "Data"
    for coordinate, value in (cells or {}).items():
        book.active[coordinate] = value
    stream = BytesIO()
    book.save(stream)
    if sheet_xml is None and not extra:
        return stream.getvalue()
    output = BytesIO()
    with ZipFile(stream) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for info in source.infolist():
            content = source.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml" and sheet_xml is not None:
                content = (
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    + sheet_xml
                    + "</worksheet>"
                ).encode()
            if extra and info.filename in extra:
                content = extra[info.filename]
            target.writestr(info.filename, content)
        for path, content in (extra or {}).items():
            if path not in source.namelist():
                target.writestr(path, content)
    return output.getvalue()


def test_decimal_text_is_not_rounded_through_float():
    data = workbook_bytes(
        sheet_xml='<sheetData><row r="1"><c r="A1"><v>12345678901234567890.123456789</v></c></row></sheetData>'
    )
    cell = read_range(data, "Data", "A1")["rows"][0][0]
    assert cell["kind"] == "number"
    assert cell["value"] == "12345678901234567890.123456789"


def test_explicit_rectangle_preserves_missing_rows_and_columns_even_if_dimension_lies():
    data = workbook_bytes(
        sheet_xml='<dimension ref="A1"/><sheetData><row r="3"><c r="C3"><v>7</v></c></row></sheetData>'
    )
    table = read_range(data, "Data", "$A$1:$D$4")
    assert table["range_ref"] == "A1:D4"
    assert len(table["rows"]) == 4
    assert all(len(row) == 4 for row in table["rows"])
    assert table["rows"][2][2]["value"] == "7"
    assert table["rows"][3][3]["kind"] == "blank"
    assert table["rows"][3][3]["coordinate"] == "D4"


def test_literal_nulls_leading_zero_and_empty_string_remain_distinct():
    data = workbook_bytes(
        sheet_xml='<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>NA</t></is></c><c r="B1" t="inlineStr"><is><t>001</t></is></c><c r="C1" t="inlineStr"><is><t></t></is></c></row></sheetData>'
    )
    row = read_range(data, "Data", "A1:D1")["rows"][0]
    assert [(c["kind"], c["value"]) for c in row] == [
        ("text", "NA"),
        ("text", "001"),
        ("empty_string", ""),
        ("blank", None),
    ]


def test_shared_and_inline_rich_strings_preserve_runs_without_phonetic_text():
    data = workbook_bytes(
        sheet_xml='<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><r><t>one</t></r><r><t xml:space="preserve"> two</t></r><rPh sb="0" eb="3"><t>phonetic</t></rPh></is></c></row></sheetData>',
        extra={
            "xl/sharedStrings.xml": b'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><r><t>left</t></r><r><t>right</t></r></si></sst>'
        },
    )
    assert [cell["value"] for cell in read_range(data, "Data", "A1:B1")["rows"][0]] == [
        "leftright",
        "one two",
    ]


def test_formula_cache_is_raw_and_missing_cache_is_unknown():
    data = workbook_bytes(
        sheet_xml='<sheetData><row r="1"><c r="A1"><f>1+1</f><v>2.00000000000000001</v></c><c r="B1"><f>2+2</f><v/></c><c r="C1" t="str"><f>""</f><v/></c></row></sheetData>'
    )
    row = read_range(data, "Data", "A1:C1")["rows"][0]
    assert (row[0]["formula"], row[0]["value"]) == ("=1+1", "2.00000000000000001")
    assert row[1]["kind"] == "unknown"
    assert row[1]["issues"]
    assert row[2]["kind"] == "empty_string"


def test_hidden_cells_and_merges_are_not_silently_skipped():
    data = workbook_bytes(
        sheet_xml='<cols><col min="2" max="2" hidden="1" width="10"/></cols><sheetData><row r="1" hidden="1"><c r="A1"><v>1</v></c></row><row r="2"><c r="A2"><v>2</v></c></row></sheetData><mergeCells count="1"><mergeCell ref="C1:D2"/></mergeCells>'
    )
    rows = read_range(data, "Data", "A1:D2")["rows"]
    assert rows[0][0]["hidden"] and rows[1][1]["hidden"]
    assert not rows[1][0]["hidden"]
    assert rows[0][2]["issues"] and rows[1][3]["issues"]


def test_boolean_error_date_and_format_metadata():
    book = Workbook()
    book.active.title = "Data"
    book.active["A1"] = True
    book.active["B1"] = "#DIV/0!"
    book.active["C1"] = 0.125
    book.active["C1"].number_format = "0.0%"
    stream = BytesIO()
    book.save(stream)
    row = read_range(stream.getvalue(), "Data", "A1:C1")["rows"][0]
    assert (row[0]["kind"], row[0]["value"]) == ("boolean", "1")
    assert (row[1]["kind"], row[1]["value"]) == ("error", "#DIV/0!")
    assert row[2]["number_format"] == "0.0%"


def test_inspection_lists_hidden_sheets_without_returning_values():
    book = Workbook()
    book.active.title = "Data"
    book.active["C3"] = "private cell content"
    book.create_sheet("Hidden").sheet_state = "hidden"
    stream = BytesIO()
    book.save(stream)
    result = inspect_workbook(stream.getvalue())
    assert result["sheets"] == [
        {"name": "Data", "range_ref": "C3:C3", "hidden": False},
        {"name": "Hidden", "range_ref": "A1:A1", "hidden": True},
    ]
    assert "private cell content" not in str(result)


@pytest.mark.parametrize(
    "selection", ["A0", "A2:A1", "A:A", "1:3", "A1:XFE1", "A1:A1048577", "Data!A1", "A1:B2,C3"]
)
def test_invalid_ranges_rejected(selection):
    with pytest.raises(InputError):
        read_range(workbook_bytes(), "Data", selection)


def test_limits_and_missing_sheet_are_clear_input_errors():
    data = workbook_bytes()
    with pytest.raises(InputError):
        read_range(data, "Data", "A1:B2", max_cells=3)
    with pytest.raises(InputError):
        read_range(data, "Absent", "A1")
    with pytest.raises(InputError):
        inspect_workbook(b"not a zip")
    with pytest.raises(InputError):
        inspect_workbook(b"x" * (10 * 1024 * 1024 + 1))


def test_zip_expansion_and_xml_entities_are_rejected():
    data = workbook_bytes(extra={"large.txt": b"x" * (50 * 1024 * 1024 + 1)})
    with pytest.raises(InputError):
        inspect_workbook(data)
    data = workbook_bytes(
        extra={
            "xl/worksheets/sheet1.xml": b'<!DOCTYPE worksheet [<!ENTITY x "bad">]><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>&x;</t></is></c></row></sheetData></worksheet>'
        }
    )
    with pytest.raises(InputError):
        read_range(data, "Data", "A1")


def test_ambiguous_duplicate_source_coordinates_are_rejected():
    data = workbook_bytes(
        sheet_xml='<sheetData><row r="1"><c r="A1"><v>1</v></c><c r="A1"><v>2</v></c></row></sheetData>'
    )
    with pytest.raises(InputError):
        read_range(data, "Data", "A1")


def test_missing_style_or_shared_string_cannot_be_treated_as_verified():
    data = workbook_bytes(
        sheet_xml='<sheetData><row r="1"><c r="A1" s="999"><v>1</v></c><c r="B1" t="s"><v>999</v></c></row></sheetData>'
    )
    with pytest.raises(InputError):
        read_range(data, "Data", "A1:B1")


def test_invalid_numeric_and_boolean_values_are_not_accepted():
    data = workbook_bytes(
        sheet_xml='<sheetData><row r="1"><c r="A1"><v>NaN</v></c><c r="B1" t="b"><v>2</v></c></row></sheetData>'
    )
    rows = read_range(data, "Data", "A1:B1")["rows"]
    assert rows[0][0]["kind"] == "unknown" and rows[0][0]["issues"]
    assert rows[0][1]["kind"] == "unknown" and rows[0][1]["issues"]


@pytest.mark.parametrize(
    "xml", ['<c r="A1" t="unsupported"/>', '<c r="A1" t="inlineStr"><is><t>_x000D_</t></is></c>']
)
def test_uninterpreted_types_or_ooxml_string_escapes_do_not_become_verified(xml):
    data = workbook_bytes(sheet_xml='<sheetData><row r="1">' + xml + "</row></sheetData>")
    cell = read_range(data, "Data", "A1")["rows"][0][0]
    assert cell["issues"]


def test_duplicate_value_elements_are_rejected():
    data = workbook_bytes(sheet_xml='<sheetData><row r="1"><c r="A1"><v>1</v><v>2</v></c></row></sheetData>')
    with pytest.raises(InputError):
        read_range(data, "Data", "A1")


def test_string_type_without_value_is_not_a_missing_cell():
    from tableproof.engine import audit

    data = workbook_bytes(sheet_xml='<sheetData><row r="1"><c r="A1" t="str"/></row></sheetData>')
    cell = read_range(data, "Data", "A1")["rows"][0][0]
    assert (cell["kind"], cell["value"]) == ("empty_string", "")
    assert audit(data, "| |\n| --- |", "Data", "A1")["status"] == "INDETERMINATE"


@pytest.mark.parametrize("kind", ["b", "e", "d"])
def test_missing_typed_value_is_not_verified_as_blank(kind):
    from tableproof.engine import audit

    data = workbook_bytes(sheet_xml=f'<sheetData><row r="1"><c r="A1" t="{kind}"/></row></sheetData>')
    cell = read_range(data, "Data", "A1")["rows"][0][0]
    assert cell["kind"] == "unknown"
    assert audit(data, "| |\n| --- |", "Data", "A1")["status"] == "INDETERMINATE"


@pytest.mark.parametrize("structure", ["merges", "hidden_columns"])
def test_ten_thousand_unrelated_structures_do_not_multiply_selected_cell_work(structure):
    from time import perf_counter

    if structure == "merges":
        metadata = (
            "<mergeCells>"
            + "".join(f'<mergeCell ref="A{row}:B{row}"/>' for row in range(1, 10001))
            + "</mergeCells>"
        )
    else:
        metadata = (
            "<cols>"
            + "".join(
                f'<col min="{column}" max="{column}" hidden="1" width="10"/>' for column in range(4, 10004)
            )
            + "</cols>"
        )
    data = workbook_bytes(sheet_xml="<sheetData/>" + metadata)
    started = perf_counter()
    result = read_range(data, "Data", "C1:C10000")
    elapsed = perf_counter() - started
    assert len(result["rows"]) == 10000
    assert all(not row[0]["hidden"] and not row[0]["issues"] for row in result["rows"])
    # The previous cross-product performed 100 million range checks (> 5 s).
    # The bound is deliberately generous for XML parsing plus 10,000 cells.
    assert elapsed < 3.0, f"Unrelated metadata amplified selection work: {elapsed:.2f}s"


@pytest.mark.parametrize("references", [["A1:B2", "A1:B2"], ["A1:B2", "B2:C3"]])
def test_duplicate_or_overlapping_selected_merges_are_rejected(references):
    metadata = "<mergeCells>" + "".join(f'<mergeCell ref="{ref}"/>' for ref in references) + "</mergeCells>"
    data = workbook_bytes(sheet_xml="<sheetData/>" + metadata)
    with pytest.raises(InputError):
        read_range(data, "Data", "A1:C3")


def test_extreme_structure_count_is_rejected_before_mapping():
    metadata = (
        "<mergeCells>"
        + "".join(f'<mergeCell ref="A{row}:B{row}"/>' for row in range(1, 20002))
        + "</mergeCells>"
    )
    data = workbook_bytes(sheet_xml="<sheetData/>" + metadata)
    with pytest.raises(InputError):
        read_range(data, "Data", "C1")


def test_huge_merge_and_overlapping_hidden_column_ranges_are_clipped_to_selection():
    metadata = '<cols><col min="1" max="16384" hidden="1"/><col min="2" max="16384" hidden="1"/></cols>'
    metadata += '<mergeCells><mergeCell ref="A1:XFD1048576"/></mergeCells>'
    data = workbook_bytes(sheet_xml="<sheetData/>" + metadata)
    rows = read_range(data, "Data", "C2:D3")["rows"]
    assert [[cell["coordinate"] for cell in row] for row in rows] == [["C2", "D2"], ["C3", "D3"]]
    assert all(cell["hidden"] and cell["issues"] for row in rows for cell in row)
