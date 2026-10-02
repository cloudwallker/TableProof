"""Deterministic comparison of an explicitly selected XLSX/Markdown mapping."""
import re
from decimal import Decimal, InvalidOperation

from . import __version__
from .errors import InputError

_NUMBER = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$")
_PLAIN_FORMAT = re.compile(r"^0(?:\.0+)?(?:[Ee][+-]0+)?$")


def _supported_number_format(fmt: str) -> bool:
    return fmt.casefold() == "general" or bool(_PLAIN_FORMAT.fullmatch(fmt))


def _looks_formatted(value: str) -> bool:
    """Formatting requires explicit semantics; never guess locale or units."""
    # Called only after the exact ASCII decimal grammar failed. Any remaining
    # numeric notation may represent locale, units, Unicode digits or symbols.
    return any(char.isnumeric() for char in value) or value.strip() in {"-", "−", "–", "—"}


def _finding(source: dict, value: str | None, status: str, rule: str, reason: str,
             notes: list[str] | None = None) -> dict:
    return {
        "coordinate": source["coordinate"],
        "source_kind": source["kind"],
        "source_value": source["value"],
        "markdown_value": value,
        "formula": source.get("formula"),
        "number_format": source.get("number_format", "General"),
        "status": status,
        "rule": rule,
        "reason": reason,
        "notes": list(notes or []),
    }


def compare_cell(source: dict, markdown_value: str) -> dict:
    """Compare one mapped cell without converting numeric strings to floats."""
    notes = []
    formula = source.get("formula")
    if formula is not None:
        notes.append("仅检查工作簿保存的公式缓存；缓存新鲜度未知，未重算公式。")
    if source.get("hidden"):
        notes.append("源单元格位于隐藏行或列中，仍包含在检查范围内。")

    def result(status, rule, reason):
        return _finding(source, markdown_value, status, rule, reason, notes)

    if source.get("issues"):
        notes.extend(source["issues"])
        return result("INDETERMINATE", "SOURCE_UNSUPPORTED", "源单元格含首版不支持的结构或数据。")
    original = source["value"]
    kind = source["kind"]
    if formula is not None and original is None:
        return result("INDETERMINATE", "FORMULA_NO_CACHE", "公式没有可用的已保存缓存。")
    if kind == "number":
        if not _supported_number_format(source.get("number_format", "General")):
            return result("INDETERMINATE", "NUMBER_FORMAT_UNSUPPORTED", "显示格式需要首版未支持的解释。")
        if not isinstance(original, str) or not _NUMBER.fullmatch(original):
            return result("INDETERMINATE", "SOURCE_NUMBER_INVALID", "源存储数值不是可验证的有限十进制数。")
        try:
            before = Decimal(original)
        except (InvalidOperation, ValueError):
            return result("INDETERMINATE", "SOURCE_NUMBER_INVALID", "无法精确读取源存储数值。")
        if not _NUMBER.fullmatch(markdown_value):
            if _looks_formatted(markdown_value):
                return result("INDETERMINATE", "OUTPUT_FORMAT_UNSUPPORTED", "输出可能含区域格式、单位或显示转换，未自动猜测。")
            return result("FAIL", "NUMBER_CHANGED", "源数值在输出中被替换为非数值或空值。")
        try:
            after = Decimal(markdown_value)
        except (InvalidOperation, ValueError):
            return result("INDETERMINATE", "OUTPUT_NUMBER_INVALID", "输出数值超出可解析范围。")
        if before == after:
            if original != markdown_value:
                notes.append("数值相等；小数位、符号或科学计数法的表达发生变化。")
            return result("PASS", "NUMBER_EQUAL", "存储数值精确相等，未使用容差。")
        return result("FAIL", "NUMBER_CHANGED", "输出数值与源存储数值不相等。")
    if kind == "text":
        if original == markdown_value:
            return result("PASS", "TEXT_EQUAL", "文本逐字一致。")
        return result("FAIL", "TEXT_CHANGED", "文本发生变化；未把 NA、NULL 或文本编号转换为数字或空值。")
    if kind == "blank":
        if markdown_value == "":
            return result("PASS", "BLANK_PRESERVED", "源空单元格对应空的 Markdown 单元格。")
        return result("FAIL", "BLANK_CHANGED", "源空单元格变成了非空内容。")
    if kind == "empty_string":
        if markdown_value == "":
            return result("INDETERMINATE", "EMPTY_STRING_AMBIGUOUS", "Markdown 空单元格不能证明空字符串与缺失单元格的区别。")
        return result("FAIL", "EMPTY_STRING_CHANGED", "源空字符串变成了非空内容。")
    return result("INDETERMINATE", "SOURCE_TYPE_UNSUPPORTED", "源类型不在首版可验证范围内。")


def audit(xlsx_data: bytes, markdown_text: str, sheet: str, range_ref: str,
          table_index: int = 0, header: bool = True) -> dict:
    """Audit a positional mapping. header=False compares only Markdown body rows."""
    from .markdown import parse_tables
    from .xlsx import read_range

    if type(table_index) is not int or table_index < 0:
        raise InputError("Markdown 表编号必须为非负整数（内部从 0 开始）。")
    if type(header) is not bool:
        raise InputError("header 必须是布尔值。")
    tables = parse_tables(markdown_text)
    if table_index >= len(tables):
        raise InputError("没有找到所选 Markdown 表格，请检查内容和表编号。")
    source = read_range(xlsx_data, sheet, range_ref)
    table = tables[table_index]
    source_rows = source["rows"]
    target_rows = ([table["header"]] if header else []) + table["rows"]
    row_count = len(source_rows)
    column_count = len(source_rows[0]) if source_rows else 0
    target_columns = len(table["header"])
    issues = list(source.get("issues", [])) + list(table.get("issues", []))
    mismatched = (len(target_rows) != row_count or target_columns != column_count or
                  any(len(row) != column_count for row in target_rows))
    if mismatched:
        issues.append("行列尺寸不一致，无法确认位置映射；未进行逐格差异归因。")
    findings = []
    if issues:
        for row in source_rows:
            for source_cell in row:
                findings.append(_finding(source_cell, None, "INDETERMINATE", "MAPPING_UNCERTAIN",
                                         "范围结构或映射存在歧义，无法进行可靠逐格比较。"))
    else:
        for row_index, row in enumerate(source_rows):
            for column_index, source_cell in enumerate(row):
                findings.append(compare_cell(source_cell, target_rows[row_index][column_index]))
    summary = {"total": len(findings), "passed": 0, "failed": 0, "indeterminate": 0}
    counters = {"PASS": "passed", "FAIL": "failed", "INDETERMINATE": "indeterminate"}
    for finding in findings:
        summary[counters[finding["status"]]] += 1
    status = "FAIL" if summary["failed"] else "INDETERMINATE" if summary["indeterminate"] else "PASS"
    return {
        "schema_version": 1, "tool_version": __version__, "status": status,
        "scope": {"sheet": source["sheet"], "range_ref": source["range_ref"],
                  "table_index": table_index, "header": header, "source_rows": row_count,
                  "source_columns": column_count, "markdown_rows": len(target_rows),
                  "markdown_columns": target_columns},
        "summary": summary, "issues": issues, "cells": findings,
    }
