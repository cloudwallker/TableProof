"""Exported evidence must remain useful without exposing user content."""

import copy
import json
from html.parser import HTMLParser


def sample_report():
    return {
        "schema_version": 1,
        "tool_version": "0.1.0",
        "status": "FAIL",
        "scope": {"sheet": "secret-sheet", "range_ref": "A1:B2", "table_index": 0,
                  "header": True, "source_rows": 2, "source_columns": 2,
                  "markdown_rows": 2, "markdown_columns": 2},
        "summary": {"total": 4, "passed": 3, "failed": 1, "indeterminate": 0},
        "issues": ["secret-issue"],
        "path": "C:/secret-path.xlsx",
        "cells": [{"coordinate": "A2", "source_kind": "number", "source_value": "secret-value",
                   "markdown_value": "secret-output", "formula": "=secret-formula",
                   "number_format": '"secret-format"0', "status": "FAIL", "rule": "NUMERIC_CHANGED",
                   "reason": "secret-reason", "notes": ["secret-note"]}],
    }


def test_redaction_removes_all_content_including_embedded_messages_without_mutating_input():
    from tableproof.report import redact_report
    report = sample_report()
    before = copy.deepcopy(report)
    result = redact_report(report)
    assert "secret" not in json.dumps(result)
    assert result["cells"][0]["coordinate"] == "A2"
    assert result["cells"][0]["rule"] == "NUMERIC_CHANGED"
    assert result["summary"] == report["summary"]
    assert result["scope"]["range_ref"] == "A1:B2"
    assert report == before


def test_redaction_removes_sensitive_coordinate_prefix_and_unknown_fields():
    from tableproof.report import redact_report
    report = sample_report()
    report["cells"][0]["coordinate"] = "secret-sheet!A2"
    report["cells"][0]["extra"] = "secret-extra"
    result = redact_report(report)
    assert "secret" not in json.dumps(result)
    assert result["cells"][0]["coordinate"] == "A2"


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_html_escapes_injected_markup_and_has_no_network_dependencies():
    from tableproof.report import render_html
    report = sample_report()
    report["scope"]["sheet"] = '<img src=x onerror="alert(1)">'
    report["cells"][0]["source_value"] = "</script><script>alert(1)</script>"
    report["cells"][0]["reason"] = '<svg onload="alert(1)">'
    output = render_html(report)
    parsed = Tags()
    parsed.feed(output)
    assert not any(tag in {"img", "svg"} for tag, _ in parsed.tags)
    assert all("src" not in attrs for tag, attrs in parsed.tags if tag == "script")
    assert "&lt;/script&gt;&lt;script&gt;alert(1)&lt;/script&gt;" in output
    assert "A2" in output
    assert "NUMERIC_CHANGED" in output


def test_redacted_html_contains_counts_and_no_raw_contents():
    from tableproof.report import render_html
    output = render_html(sample_report(), redact=True)
    assert "secret" not in output
    assert "NUMERIC_CHANGED" in output
    assert "A2" in output

