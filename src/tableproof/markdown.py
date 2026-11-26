"""Conservative GFM table parsing with checks on the original row widths."""

from __future__ import annotations

import re

from markdown_it import MarkdownIt

from tableproof.errors import InputError

MAX_INPUT_BYTES = 2 * 1024 * 1024
_MAX_TABLE_CELLS = 100000


def _split_row(line: str) -> list[str]:
    """Split only unescaped pipes; retain escape text for the real parser."""
    line = line.strip()
    cells = []
    start = 0
    backslashes = 0
    for offset, char in enumerate(line):
        if char == "|" and backslashes % 2 == 0:
            cells.append(line[start:offset])
            start = offset + 1
        backslashes = backslashes + 1 if char == "\\" else 0
    cells.append(line[start:])
    if line.startswith("|"):
        cells.pop(0)
    if len(cells) > 0 and start == len(line) and line.endswith("|"):
        cells.pop()
    return [cell.strip() for cell in cells]


def _plain(inline, issues):
    children = inline.children or []
    if issues is not None and any(child.type not in ("text", "code_inline") for child in children):
        message = "表格含不支持的 Markdown 内联样式、链接、图片或 HTML；无法可靠逐格比较。"
        if message not in issues:
            issues.append(message)
    # For unsupported expressions this is a preview only; issues block verification.
    return "".join(child.content for child in children if child.nesting == 0)


def _unknown(issue):
    return {"index": 0, "header": [], "rows": [], "issues": [issue]}


def parse_tables(text: str, *, check_header_content: bool = True) -> list[dict]:
    """Parse GFM tables; always verify row widths, even when header values are out of scope."""
    if not isinstance(text, str):
        raise InputError("Markdown 输入必须是文本。")
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise InputError("Markdown 文件超过 2 MiB 输入上限。")
    parser = MarkdownIt("commonmark", {"html": True}).enable(["table", "strikethrough"])
    tokens = parser.parse(text)
    # CommonMark recognizes CR/LF only; Unicode line separators are cell data.
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    found = []
    covered = set()
    count = 0
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type == "table_open":
            table = {"index": 0, "header": [], "rows": [], "issues": []}
            if token.level:
                table["issues"].append("嵌套在列表或引用内的表格不受支持。")
            start, end = token.map
            covered.update(range(start, end))
            width = None
            for line_number in range(start, end):
                raw_width = len(_split_row(lines[line_number]))
                if width is None:
                    width = raw_width
                elif raw_width != width:
                    table["issues"].append(
                        f"Markdown 第 {line_number + 1} 行列数与表头不同；禁止自动补齐或截断。"
                    )
            current_row = None
            header = False
            index += 1
            while index < len(tokens) and tokens[index].type != "table_close":
                item = tokens[index]
                if item.type == "thead_open":
                    header = True
                elif item.type == "thead_close":
                    header = False
                elif item.type == "tr_open":
                    current_row = []
                elif item.type == "inline" and current_row is not None:
                    issues = None if header and not check_header_content else table["issues"]
                    current_row.append(_plain(item, issues))
                    count += 1
                    if count > _MAX_TABLE_CELLS:
                        raise InputError("Markdown 表格单元格数量超过安全上限。")
                elif item.type == "tr_close":
                    if header:
                        table["header"] = current_row
                    else:
                        table["rows"].append(current_row)
                    current_row = None
                index += 1
            found.append((start, table))
        elif token.type in ("fence", "code_block") and token.map:
            covered.update(range(*token.map))
        elif token.type == "html_block" and re.search(r"<\s*table\b", token.content, re.IGNORECASE):
            start, end = token.map
            covered.update(range(start, end))
            found.append((start, _unknown("HTML 表格不受支持；请提供 GitHub 风格 Markdown 表格。")))
        index += 1
    # markdown-it intentionally treats malformed table headers as paragraphs.
    # Keep these candidates visible so the caller cannot silently skip them.
    for line_number in range(len(lines) - 1):
        if line_number in covered or line_number + 1 in covered:
            continue
        first, second = lines[line_number : line_number + 2]
        parts = _split_row(second)
        if "|" in first and parts and all(re.fullmatch(r":?-+:?", part) for part in parts):
            found.append((line_number, _unknown("表格表头与分隔行不完整或列数不一致。")))
            covered.update((line_number, line_number + 1))
    found.sort(key=lambda item: item[0])
    result = [table for _, table in found]
    for index, table in enumerate(result):
        table["index"] = index
    return result
