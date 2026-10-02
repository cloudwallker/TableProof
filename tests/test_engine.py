"""Manually specified fidelity cases; raw XLSX fixtures never pass through a converter."""
from io import BytesIO
from zipfile import ZipFile

import pytest
from openpyxl import Workbook

from tableproof.engine import audit, compare_cell
from tableproof.errors import InputError


def cell(kind, value, **changes):
    result = {"coordinate": "B2", "kind": kind, "value": value, "formula": None,
                  "number_format": "General", "hidden": False, "issues": []}
    result.update(changes)
    return result


@pytest.mark.parametrize("source,output,status", [
    (cell("number", "1"), "1", "PASS"),
    (cell("number", "1"), "1.0", "PASS"),
    (cell("number", "1000"), "1e3", "PASS"),
    (cell("number", "0.0001"), "1E-4", "PASS"),
    (cell("number", "-12.50"), "-12.5", "PASS"),
    (cell("number", "0"), "-0", "PASS"),
    (cell("number", "123456789.123"), "123456789.1230", "PASS"),
    (cell("number", "123456789012345678901234567890.123456"),
     "123456789012345678901234567890.123456", "PASS"),
    (cell("text", "NA"), "NA", "PASS"),
    (cell("text", "NULL"), "NULL", "PASS"),
    (cell("text", "NaN"), "NaN", "PASS"),
    (cell("text", "001"), "001", "PASS"),
    (cell("text", "中文|English"), "中文|English", "PASS"),
    (cell("blank", None), "", "PASS"),
    (cell("number", "1.25", number_format="0.00"), "1.25", "PASS"),
    (cell("number", "123456789.123"), "1.234568e+08", "FAIL"),
    (cell("number", "0.1234567890123456789012345678901"),
     "0.1234567890123456789012345678902", "FAIL"),
    (cell("number", "0"), "", "FAIL"),
    (cell("number", "5"), "NaN", "FAIL"),
    (cell("text", "001"), "1", "FAIL"),
    (cell("text", "NA"), "NaN", "FAIL"),
    (cell("text", "NULL"), "", "FAIL"),
    (cell("text", "a"), "A", "FAIL"),
    (cell("text", "  a"), "a", "FAIL"),
    (cell("blank", None), "NaN", "FAIL"),
    (cell("blank", None), "NULL", "FAIL"),
    (cell("empty_string", ""), "", "INDETERMINATE"),
    (cell("empty_string", ""), "NA", "FAIL"),
    (cell("number", "0.125", number_format="0.0%"), "12.5%", "INDETERMINATE"),
    (cell("number", "46000", number_format="yyyy-mm-dd"), "2025-12-09", "INDETERMINATE"),
    (cell("number", "1000"), "1,000", "INDETERMINATE"),
    (cell("number", "1.2"), "1,2", "INDETERMINATE"),
    (cell("number", "5"), "$5", "INDETERMINATE"),
    (cell("number", "0.125"), "12.5%", "INDETERMINATE"),
    (cell("number", "-1"), "−1", "INDETERMINATE"),
    (cell("number", "0.125"), "12.5％", "INDETERMINATE"),
    (cell("number", "1"), "١", "INDETERMINATE"),
    (cell("number", "5"), "5euro", "INDETERMINATE"),
    (cell("unknown", None, formula="=1+2"), "3", "INDETERMINATE"),
    (cell("number", "3", formula="=1+2"), "3", "PASS"),
    (cell("number", "3", formula="=1+2"), "4", "FAIL"),
    (cell("error", "#VALUE!"), "#VALUE!", "INDETERMINATE"),
    (cell("boolean", "1"), "TRUE", "INDETERMINATE"),
    (cell("number", "1", issues=["Merged cells are unsupported"]), "1", "INDETERMINATE"),
    (cell("number", "NaN"), "NaN", "INDETERMINATE"),
    (cell("number", "1"), "Infinity", "FAIL"),
])
def test_fixed_cases(source, output, status):
    finding = compare_cell(source, output)
    assert finding["status"] == status
    assert finding["coordinate"] == "B2"
    assert finding["source_kind"] == source["kind"]
    assert finding["source_value"] == source["value"]
    assert finding["markdown_value"] == output
    assert finding["rule"] and finding["reason"]


def workbook(rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "数据"
    for row in rows:
        ws.append(row)
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_audit_equal_with_empty_column_and_literal_null():
    source = workbook([["编号", "值", "空列"], ["001", "NULL", None]])
    report = audit(source, "|编号|值|空列|\n|---|---|---|\n|001|NULL||", "数据", "A1:C2")
    assert report["status"] == "PASS"
    assert report["summary"] == {"total": 6, "passed": 6, "failed": 0, "indeterminate": 0}


def test_audit_dimensions_do_not_make_shifted_cell_claims():
    source = workbook([["key", "value"], ["a", 1], ["b", 2]])
    report = audit(source, "|key|value|\n|---|---|\n|b|2|", "数据", "A1:B3")
    assert report["status"] == "INDETERMINATE"
    assert report["summary"] == {"total": 6, "passed": 0, "failed": 0, "indeterminate": 6}
    assert all(c["markdown_value"] is None for c in report["cells"])
    assert all(c["rule"] == "MAPPING_UNCERTAIN" for c in report["cells"])


def test_no_header_compares_source_to_body_only():
    report = audit(workbook([["a", 1]]), "|label|value|\n|---|---|\n|a|1|", "数据", "A1:B1", header=False)
    assert report["status"] == "PASS"
    assert report["summary"]["total"] == 2


def test_malformed_markdown_cannot_pass_via_implicit_padding():
    report = audit(workbook([["a", "b"], ["x", None]]), "|a|b|\n|---|---|\n|x|", "数据", "A1:B2")
    assert report["status"] == "INDETERMINATE"
    assert report["summary"]["passed"] == 0


def test_difference_takes_precedence_over_unknown():
    report = audit(workbook([["x", "y"], ["old", "=1+1"]]), "|x|y|\n|---|---|\n|new|2|", "数据", "A1:B2")
    assert report["status"] == "FAIL"
    assert report["summary"] == {"total": 4, "passed": 2, "failed": 1, "indeterminate": 1}
    assert report["cells"][2]["coordinate"] == "A2"


def test_selected_second_table():
    text = "|wrong|\n|---|\n|no|\n\n|right|\n|---|\n|yes|"
    assert audit(workbook([["right"], ["yes"]]), text, "数据", "A1:A2", table_index=1)["status"] == "PASS"


@pytest.mark.parametrize("kwargs,text", [
    ({"table_index": -1}, "|x|\n|---|"),
    ({"table_index": 2}, "|x|\n|---|"),
    ({}, "No table here"),
    ({"header": "false"}, "|x|\n|---|"),
])
def test_invalid_selection_raises_input_error(kwargs, text):
    with pytest.raises(InputError):
        audit(workbook([["x"]]), text, "数据", "A1:A1", **kwargs)


def test_cached_formula_note_and_hidden_note():
    finding = compare_cell(cell("number", "3", formula="=1+2", hidden=True), "3.0")
    assert finding["status"] == "PASS"
    assert len(finding["notes"]) >= 2


def test_raw_xml_precision_is_preserved_end_to_end():
    original = workbook([["number"], [1]])
    buffer = BytesIO()
    precise = "0.1234567890123456789012345678901"
    with ZipFile(BytesIO(original)) as incoming, ZipFile(buffer, "w") as outgoing:
        for name in incoming.namelist():
            data = incoming.read(name)
            if name == "xl/worksheets/sheet1.xml":
                data = data.replace(b"<v>1</v>", f"<v>{precise}</v>".encode())
            outgoing.writestr(name, data)
    report = audit(buffer.getvalue(), f"|number|\n|---|\n|{precise}|", "数据", "A1:A2")
    assert report["status"] == "PASS"
    assert report["cells"][1]["source_value"] == precise
