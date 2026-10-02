"""Read explicit XLSX rectangles without converting stored numbers to float."""

from __future__ import annotations

import posixpath
import re
from contextlib import contextmanager
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from defusedxml import ElementTree
from openpyxl import load_workbook
from openpyxl.styles.numbers import BUILTIN_FORMATS
from openpyxl.utils.cell import column_index_from_string, get_column_letter

from tableproof.errors import InputError

MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_EXPANDED_BYTES = 50 * 1024 * 1024
MAX_CELLS = 10000
_MAX_ENTRIES = 2048
_MAX_SHEET_STRUCTURES = 20000
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_CELL_REF = re.compile(r"\$?([A-Za-z]{1,3})\$?([1-9][0-9]{0,6})\Z")
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


def _coordinate(reference: str) -> tuple[int, int]:
    match = _CELL_REF.fullmatch(reference)
    if not match:
        raise InputError("单元格坐标必须是有效的 A1 坐标。")
    col = column_index_from_string(match[1].upper())
    row = int(match[2])
    if col > 16384 or row > 1048576:
        raise InputError("单元格坐标超出 XLSX 行列上限。")
    return col, row


def _rectangle(reference: str) -> tuple[int, int, int, int]:
    if not isinstance(reference, str):
        raise InputError("范围必须是 A1 或 A1:C3 形式。")
    parts = reference.strip().split(":")
    if len(parts) not in (1, 2):
        raise InputError("仅支持一个连续矩形范围。")
    left, top = _coordinate(parts[0])
    right, bottom = _coordinate(parts[-1])
    if left > right or top > bottom:
        raise InputError("范围终点不能位于起点之前。")
    return left, top, right, bottom


def _ref(col: int, row: int) -> str:
    return f"{get_column_letter(col)}{row}"


def _xml(archive: ZipFile, path: str):
    try:
        return ElementTree.fromstring(archive.read(path), forbid_dtd=True)
    except Exception as exc:
        raise InputError("工作簿包含缺失、不安全或无效的 XML 内容。") from exc


@contextmanager
def _workbook(data: bytes):
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise InputError("请提供非空 XLSX 文件。")
    if len(data) > MAX_INPUT_BYTES:
        raise InputError("XLSX 文件超过 10 MiB 输入上限。")
    archive = None
    book = None
    try:
        archive = ZipFile(BytesIO(data))
        entries = archive.infolist()
        if len(entries) > _MAX_ENTRIES or sum(item.file_size for item in entries) > MAX_EXPANDED_BYTES:
            raise InputError("XLSX 压缩包展开后超过安全上限。")
        names = [item.filename for item in entries]
        if len(names) != len(set(names)):
            raise InputError("XLSX 压缩包含重复文件名，无法确定来源。")
        for item in entries:
            path = item.filename
            if item.flag_bits & 1 or "\\" in path or path.startswith("/") or ".." in path.split("/"):
                raise InputError("XLSX 压缩包包含不安全路径或加密内容。")
            # Preflight every XML part before openpyxl sees it, including unused parts.
            if path.lower().endswith((".xml", ".rels")):
                _xml(archive, path)
        book = load_workbook(BytesIO(data), read_only=True, data_only=False, keep_links=False)
        yield archive, book
    except InputError:
        raise
    except (BadZipFile, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        raise InputError("无法读取 XLSX 工作簿；文件可能损坏或包含不支持的结构。") from exc
    finally:
        if book is not None:
            book.close()
        if archive is not None:
            archive.close()


def _sheet_xml(archive, worksheet):
    path = getattr(worksheet, "_worksheet_path", None)
    if not path:
        raise InputError("只支持普通工作表，不支持图表工作表。")
    root = _xml(archive, path)
    if root.tag != f"{_NS}worksheet":
        raise InputError("此工作表使用不支持的 XML 命名空间或结构。")
    return root


def _scan_sheet(root):
    """Resolve explicit and implicit coordinates independently of dimension hints."""
    column_elements = root.findall(f"{_NS}cols/{_NS}col")
    merge_elements = root.findall(f"{_NS}mergeCells/{_NS}mergeCell")
    if len(column_elements) + len(merge_elements) > _MAX_SHEET_STRUCTURES:
        raise InputError("工作表合并范围与列定义数量超过 20000 个安全上限。")
    cells = {}
    hidden_rows = set()
    seen_rows = set()
    previous_row = 0
    for row_element in root.findall(f"{_NS}sheetData/{_NS}row"):
        try:
            row = int(row_element.get("r", previous_row + 1))
        except ValueError as exc:
            raise InputError("工作表行坐标无效。") from exc
        if row in seen_rows or not 1 <= row <= 1048576:
            raise InputError("工作表包含重复或无效的行坐标。")
        seen_rows.add(row)
        previous_row = row
        if row_element.get("hidden") in ("1", "true"):
            hidden_rows.add(row)
        previous_col = 0
        for element in row_element.findall(f"{_NS}c"):
            coordinate = element.get("r")
            if coordinate:
                col, cell_row = _coordinate(coordinate)
                if cell_row != row:
                    raise InputError("单元格坐标与其所在行不一致。")
            else:
                col, cell_row = previous_col + 1, row
                if col > 16384:
                    raise InputError("工作表列坐标超出 XLSX 上限。")
            key = (col, cell_row)
            if key in cells:
                raise InputError("工作表包含重复单元格坐标，无法确定来源。")
            cells[key] = element
            previous_col = col
    hidden_columns = []
    for column in column_elements:
        if column.get("hidden") in ("1", "true"):
            try:
                first, last = int(column.get("min")), int(column.get("max"))
            except (ValueError, TypeError) as exc:
                raise InputError("隐藏列范围无效。") from exc
            if not 1 <= first <= last <= 16384:
                raise InputError("隐藏列范围超出 XLSX 上限。")
            hidden_columns.append((first, last))
    merges = [_rectangle(merge.get("ref")) for merge in merge_elements]
    if len(merges) != len(set(merges)):
        raise InputError("工作表包含重复合并范围，无法确定单元格结构。")
    return cells, hidden_rows, hidden_columns, merges


def _selected_structure_cells(hidden_columns, merges, left, top, right, bottom):
    """Bound structure lookup work to metadata size plus selected cells.

    Difference events handle overlapping column definitions without repeatedly
    expanding the same columns. Valid merges are disjoint; reject an overlap
    as soon as it is encountered, before it can amplify selected-cell work.
    """
    changes = [0] * (right - left + 2)
    for first, last in hidden_columns:
        first, last = max(first, left), min(last, right)
        if first <= last:
            changes[first - left] += 1
            changes[last - left + 1] -= 1
    selected_hidden = set()
    active = 0
    for offset, column in enumerate(range(left, right + 1)):
        active += changes[offset]
        if active:
            selected_hidden.add(column)

    selected_merged = set()
    for first_col, first_row, last_col, last_row in merges:
        first_col, last_col = max(first_col, left), min(last_col, right)
        first_row, last_row = max(first_row, top), min(last_row, bottom)
        if first_col > last_col or first_row > last_row:
            continue
        for row in range(first_row, last_row + 1):
            for column in range(first_col, last_col + 1):
                coordinate = (column, row)
                if coordinate in selected_merged:
                    raise InputError("所选范围包含相互重叠的合并范围，无法确定单元格结构。")
                selected_merged.add(coordinate)
    return selected_hidden, selected_merged


def _string(element):
    # Phonetic annotations (rPh) are metadata, not displayed cell text.
    texts = []
    for child in element:
        if child.tag == f"{_NS}t":
            texts.append(child.text or "")
        elif child.tag == f"{_NS}r":
            texts.extend(text.text or "" for text in child.findall(f"{_NS}t"))
    return "".join(texts)


def _shared_strings(archive):
    path = "xl/sharedStrings.xml"
    relationships = "xl/_rels/workbook.xml.rels"
    if relationships in archive.namelist():
        for relationship in _xml(archive, relationships):
            if relationship.get("Type", "").endswith("/sharedStrings"):
                if relationship.get("TargetMode") == "External":
                    raise InputError("不支持外部共享字符串。")
                target = relationship.get("Target", "")
                path = (
                    target.lstrip("/")
                    if target.startswith("/")
                    else posixpath.normpath(posixpath.join("xl", target))
                )
                if path.startswith("../") or "\\" in path:
                    raise InputError("共享字符串路径无效。")
                break
    if path not in archive.namelist():
        return []
    root = _xml(archive, path)
    return [_string(item) for item in root.findall(f"{_NS}si")]


def _number_format(book, element):
    try:
        style_id = int(element.get("s", "0"))
        if style_id < 0:
            raise IndexError
        number_id = book._cell_styles[style_id].numFmtId
        if number_id < 164:
            return BUILTIN_FORMATS.get(number_id, f"unsupported-format-{number_id}")
        return book._number_formats[number_id - 164]
    except (ValueError, IndexError) as exc:
        raise InputError("单元格引用了不存在的格式，无法可靠解释其值。") from exc


def _cell(book, element, coordinate, hidden, shared):
    cell = {
        "coordinate": coordinate,
        "kind": "blank",
        "value": None,
        "formula": None,
        "number_format": "General",
        "hidden": hidden,
        "issues": [],
    }
    if element is None:
        return cell
    if any(len(element.findall(f"{_NS}{tag}")) > 1 for tag in ("v", "f", "is")):
        raise InputError("单元格包含重复值或公式字段，无法确定来源。")
    cell["number_format"] = _number_format(book, element)
    formula = element.find(f"{_NS}f")
    if formula is not None:
        cell["formula"] = "=" + (formula.text or "")
        if not formula.text:
            cell["issues"].append("公式表达式缺失或为共享公式引用；无法完整还原公式。")
    value_element = element.find(f"{_NS}v")
    raw = value_element.text if value_element is not None else None
    kind = element.get("t", "n")
    if kind not in ("n", "b", "e", "s", "str", "inlineStr", "d"):
        cell["kind"], cell["value"] = "unknown", raw
        cell["issues"].append("单元格包含不支持的存储类型。")
        return cell
    if kind == "inlineStr":
        inline = element.find(f"{_NS}is")
        if inline is None:
            cell["kind"], cell["value"] = "empty_string", ""
        else:
            cell["value"] = _string(inline)
            cell["kind"] = "text" if cell["value"] else "empty_string"
    elif kind == "s":
        try:
            index = int(raw)
            if index < 0:
                raise IndexError
            cell["value"] = shared[index]
        except (TypeError, ValueError, IndexError) as exc:
            raise InputError("单元格引用了不存在的共享字符串。") from exc
        cell["kind"] = "text" if cell["value"] else "empty_string"
    elif kind == "str" and (value_element is not None or formula is None):
        cell["value"] = raw or ""
        cell["kind"] = "text" if cell["value"] else "empty_string"
    elif raw is None:
        if formula is not None:
            cell["kind"] = "unknown"
            cell["issues"].append("公式没有保存的缓存结果；工具不会重新计算公式。")
        elif kind != "n":
            cell["kind"] = "unknown"
            cell["issues"].append("显式存储类型缺少值，无法确认其为空白单元格。")
    elif kind == "n" and _NUMBER.fullmatch(raw):
        cell["kind"], cell["value"] = "number", raw
    elif kind == "b" and raw in ("0", "1"):
        cell["kind"], cell["value"] = "boolean", raw
    elif kind == "e":
        cell["kind"], cell["value"] = "error", raw
    else:
        cell["kind"], cell["value"] = "unknown", raw
        cell["issues"].append("单元格类型或存储值不受支持，无法可靠比较。")
    if cell["kind"] == "text" and re.search(r"_x[0-9a-fA-F]{4}_", cell["value"]):
        cell["issues"].append("字符串包含 OOXML 特殊字符转义；首版无法可靠解码。")
    return cell


def read_range(data: bytes, sheet: str, range_ref: str, max_cells: int = MAX_CELLS) -> dict:
    """Return every selected cell, including missing and hidden cells."""
    left, top, right, bottom = _rectangle(range_ref)
    if isinstance(max_cells, bool) or not isinstance(max_cells, int) or max_cells <= 0:
        raise InputError("单元格上限必须是正整数。")
    if (right - left + 1) * (bottom - top + 1) > min(max_cells, MAX_CELLS):
        raise InputError(f"所选范围超过 {min(max_cells, MAX_CELLS)} 个单元格上限。")
    with _workbook(data) as (archive, book):
        if sheet not in book.sheetnames:
            raise InputError("指定的工作表不存在。")
        worksheet = book[sheet]
        source, hidden_rows, hidden_columns, merges = _scan_sheet(_sheet_xml(archive, worksheet))
        hidden_columns, merged_cells = _selected_structure_cells(
            hidden_columns, merges, left, top, right, bottom
        )
        shared = _shared_strings(archive)
        rows = []
        for row in range(top, bottom + 1):
            result_row = []
            for col in range(left, right + 1):
                hidden = worksheet.sheet_state != "visible" or row in hidden_rows or col in hidden_columns
                cell = _cell(book, source.get((col, row)), _ref(col, row), hidden, shared)
                if (col, row) in merged_cells:
                    cell["issues"].append("所选单元格属于合并范围；首版无法确定逐格映射。")
                result_row.append(cell)
            rows.append(result_row)
    canonical = (
        _ref(left, top) if left == right and top == bottom else f"{_ref(left, top)}:{_ref(right, bottom)}"
    )
    return {"sheet": sheet, "range_ref": canonical, "rows": rows, "issues": []}


def inspect_workbook(data: bytes) -> dict:
    """Describe actual stored worksheet bounds without exposing cell content."""
    sheets = []
    with _workbook(data) as (archive, book):
        for worksheet in book.worksheets:
            cells, _, _, _ = _scan_sheet(_sheet_xml(archive, worksheet))
            if cells:
                left = min(col for col, _ in cells)
                right = max(col for col, _ in cells)
                top = min(row for _, row in cells)
                bottom = max(row for _, row in cells)
                reference = f"{_ref(left, top)}:{_ref(right, bottom)}"
            else:
                reference = "A1:A1"
            sheets.append(
                {
                    "name": worksheet.title,
                    "range_ref": reference,
                    "hidden": worksheet.sheet_state != "visible",
                }
            )
    return {"sheets": sheets, "max_cells": MAX_CELLS}
