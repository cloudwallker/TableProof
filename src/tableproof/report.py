"""Offline, escaped evidence reports with conservative content redaction."""

import re
from html import escape
from pathlib import Path

HIDDEN = "[已隐藏]"
STATUSES = {"PASS", "FAIL", "INDETERMINATE"}
KINDS = {"number", "text", "blank", "empty_string", "boolean", "error", "unknown"}


def _status(value):
    return value if value in STATUSES else "INDETERMINATE"


def _coordinate(value):
    coordinate = str(value).rsplit("!", 1)[-1]
    return coordinate if re.fullmatch(r"\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}", coordinate) else HIDDEN


def _count(value):
    return value if type(value) is int and 0 <= value <= 100_000_000 else 0


def redact_report(report: dict) -> dict:
    """Rebuild the public schema, removing all content-bearing free text.

    Unknown fields are intentionally dropped: future path/metadata fields must
    not accidentally defeat the promise made by the existing export control.
    """
    scope = report.get("scope", {})
    range_ref = str(scope.get("range_ref", ""))
    if not re.fullmatch(r"\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}(?::\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6})?", range_ref):
        range_ref = HIDDEN
    version = str(report.get("tool_version", ""))
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[a-z0-9.+-]*)?", version):
        version = HIDDEN
    result = {
        "schema_version": _count(report.get("schema_version", 1)),
        "tool_version": version,
        "redacted": True,
        "status": _status(report.get("status")),
        "scope": {"sheet": HIDDEN, "range_ref": range_ref,
                  "table_index": _count(scope.get("table_index", 0)), "header": scope.get("header") is True,
                  **{key: _count(scope.get(key)) for key in
                     ("source_rows", "source_columns", "markdown_rows", "markdown_columns")}},
        "summary": {key: _count(report.get("summary", {}).get(key)) for key in
                    ("total", "passed", "failed", "indeterminate")},
        "issues": [HIDDEN for _ in report.get("issues", [])],
        "cells": [],
    }
    for cell in report.get("cells", []):
        rule = str(cell.get("rule", ""))
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,79}", rule):
            rule = HIDDEN
        result["cells"].append({
            "coordinate": _coordinate(cell.get("coordinate", "")),
            "source_kind": cell.get("source_kind") if cell.get("source_kind") in KINDS else "unknown",
            "source_value": HIDDEN, "markdown_value": HIDDEN, "formula": HIDDEN,
            "number_format": HIDDEN, "status": _status(cell.get("status")), "rule": rule,
            "reason": HIDDEN, "notes": [HIDDEN for _ in cell.get("notes", [])],
        })
    return result


def _text(value):
    return escape("∅ 空值" if value is None else str(value), quote=True)


def render_html(report: dict, redact: bool = False) -> str:
    """Return a self-contained HTML document; no network or active user markup."""
    if redact:
        report = redact_report(report)
    scope = report.get("scope", {})
    summary = report.get("summary", {})
    status = _status(report.get("status"))
    labels = {"PASS": "通过", "FAIL": "存在差异", "INDETERMINATE": "无法判断"}
    tiles, rows = [], []
    for index, cell in enumerate(report.get("cells", [])):
        state = _status(cell.get("status"))
        coordinate = _text(cell.get("coordinate", ""))
        notes = " · ".join(_text(item) for item in cell.get("notes", []))
        formula = f'<div class="muted">公式 {_text(cell["formula"])}</div>' if cell.get("formula") else ""
        tiles.append(f'<a class="source-cell {state}" id="source-{index}" href="#finding-{index}" '
                     f'data-state="{state}"><b>{coordinate}</b><span>{_text(cell.get("source_value"))}</span></a>')
        rows.append(f'<tr id="finding-{index}" data-state="{state}"><td><a href="#source-{index}">'
                    f'{coordinate}</a></td><td><span class="badge {state}">{labels[state]}</span></td>'
                    f'<td>{_text(cell.get("source_value"))}{formula}<div class="muted">'
                    f'{_text(cell.get("source_kind", ""))} · {_text(cell.get("number_format", ""))}</div></td>'
                    f'<td>{_text(cell.get("markdown_value"))}</td><td><code>{_text(cell.get("rule", ""))}</code>'
                    f'<div>{_text(cell.get("reason", ""))}</div><div class="muted">{notes}</div></td></tr>')
    issues = "".join(f"<li>{_text(issue)}</li>" for issue in report.get("issues", []))
    css = (Path(__file__).parent / "static" / "report.css").read_text(encoding="utf-8")
    columns = max(1, min(_count(scope.get("source_columns")) or 1, 12))
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>TableProof · 表格验收报告</title><style>{css}</style></head><body><a class="skip-link" href="#report-main">跳到验收报告</a><main id="report-main" tabindex="-1">
<header><div class="brand">▦ TableProof <span>独立验收报告</span></div><span class="local">离线文件 · 本地证据</span></header>
<section class="intro"><div><div class="eyebrow">TABLE FIDELITY / CELL EVIDENCE</div><h1>每个单元格，都有依据。</h1>
<p>{_text(scope.get("sheet", ""))} · {_text(scope.get("range_ref", ""))} · Markdown 表 {_count(scope.get("table_index")) + 1}</p>
<p class="muted">{'包含源表头' if scope.get('header') else '源范围仅对齐 Markdown 数据行'} · TableProof {_text(report.get('tool_version', ''))}
{' · 内容已隐藏' if report.get('redacted') else ''}</p></div><div class="verdict {status}"><strong>{status}</strong><span>{labels[status]}</span></div></section>
<section class="stats"><article><small>选定单元格</small><strong>{_count(summary.get('total'))}</strong></article>
<article><small>通过 PASS</small><strong>{_count(summary.get('passed'))}</strong></article>
<article><small>差异 FAIL</small><strong>{_count(summary.get('failed'))}</strong></article>
<article><small>未知 INDETERMINATE</small><strong>{_count(summary.get('indeterminate'))}</strong></article></section>
<p class="boundary">本报告只验证上述选定范围与已确认的位置映射。INDETERMINATE 表示证据不足；通过不代表整份工作簿、公式或 AI 回答正确。</p>
{'<aside class="issues"><b>范围与结构提示</b><ul>' + issues + '</ul></aside>' if issues else ''}
<section class="panel"><div class="panel-title"><h2>源单元格定位</h2><span>点击坐标，在来源与证据之间跳转</span></div>
<div class="source-grid" style="grid-template-columns:repeat({columns},minmax(90px,1fr))">{''.join(tiles) or '<p>映射无法确定，未生成逐格归因。</p>'}</div></section>
<section class="panel"><div class="panel-title"><h2 id="evidence-heading">逐格证据</h2><div class="filters"><button class="active" data-filter="ALL" aria-pressed="true">全部</button><button data-filter="FAIL" aria-pressed="false">差异 FAIL</button><button data-filter="INDETERMINATE" aria-pressed="false">未知</button><button data-filter="PASS" aria-pressed="false">通过 PASS</button></div></div>
<div class="table-wrap" tabindex="0" role="region" aria-labelledby="evidence-heading"><table><thead><tr><th>源坐标</th><th>状态</th><th>XLSX 存储值</th><th>Markdown 值</th><th>规则与依据</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div><p id="filter-empty" role="status" hidden>此筛选条件下没有单元格。</p></section>
<footer>TableProof · 可复查的转换证据 · 数值以 XLSX 存储值为准；公式不会重算。</footer>
</main><script>
document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {{
 document.querySelectorAll('[data-filter]').forEach(item => {{
  item.classList.toggle('active', item === button);
  item.setAttribute('aria-pressed', String(item === button));
 }});
 let visible = 0;
 document.querySelectorAll('tbody tr[data-state]').forEach(row => {{ row.hidden = button.dataset.filter !== 'ALL' && row.dataset.state !== button.dataset.filter; if (!row.hidden) visible++; }});
 document.getElementById('filter-empty').hidden = visible > 0;
}}));
document.querySelectorAll('.source-cell').forEach(link => link.addEventListener('click', () => {{
 const row = document.querySelector(link.getAttribute('href')); if (row) row.hidden = false;
}}));
</script></body></html>'''
