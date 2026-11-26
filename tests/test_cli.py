"""End-to-end command contracts: exit statuses, mapping and safe exports."""

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "tableproof", *map(str, args)],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=20, check=False,
    )


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "中文 源表.xlsx"
    book = Workbook()
    book.active.title = "数据"
    book.active.append(["编号", "金额", "地区"])
    book.active.append(["00123", 123456789.123, "NA"])
    book.save(path)
    return path


def test_help_works_without_optional_converter():
    result = run_cli("--help")
    assert result.returncode == 0, result.stderr
    assert "check" in result.stdout and "convert" in result.stdout


def test_inspect_handles_unicode_paths_without_cell_contents(source):
    result = run_cli("inspect", source)
    assert result.returncode == 0, result.stderr
    info = json.loads(result.stdout)
    assert info["sheets"][0]["name"] == "数据"
    assert "00123" not in result.stdout


@pytest.mark.parametrize(
    ("body", "exit_code", "status"),
    [
        ("| 00123 | 123456789.123 | NA |", 0, "PASS"),
        ("| `00123` | 123456789.123 | NA |", 0, "PASS"),
        ("| `123` | 123456789.123 | NA |", 1, "FAIL"),
        ("| 123 | 1.234568e+08 | NaN |", 1, "FAIL"),
        ("| 00123 | 123456789.123 | NA |\n| x | 1 | y |", 2, "INDETERMINATE"),
    ],
)
def test_check_exit_codes_and_json(source, tmp_path, body, exit_code, status):
    md = tmp_path / "转换结果.md"
    md.write_text("| 编号 | 金额 | 地区 |\n| --- | --- | --- |\n" + body, encoding="utf-8")
    result = run_cli("check", source, "--markdown", md, "--sheet", "数据", "--range", "A1:C2", "--json", "-")
    assert result.returncode == exit_code, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == status
    assert report["scope"]["table_index"] == 0


def test_second_table_and_no_header_map_to_first_selected_source_row(source, tmp_path):
    md = tmp_path / "two.md"
    md.write_text(
        "| other |\n| --- |\n| nope |\n\n"
        "| **A** | B | C |\n| --- | --- | --- |\n| 00123 | 123456789.123 | NA |\n",
        encoding="utf-8",
    )
    result = run_cli("check", source, "--markdown", md, "--sheet", "数据", "--range", "A2:C2", "--no-header", "--table", "2", "--json", "-")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["scope"]["table_index"] == 1
    assert report["scope"]["header"] is False
    assert report["cells"][0]["coordinate"] == "A2"


def test_redacted_json_and_html_remove_source_content(source, tmp_path):
    md = tmp_path / "in.md"
    md.write_text("| 编号 | 金额 | 地区 |\n| --- | --- | --- |\n| 00123 | 123456789.123 | NA |", encoding="utf-8")
    json_path, html_path = tmp_path / "报告.json", tmp_path / "报告.html"
    result = run_cli("check", source, "--markdown", md, "--sheet", "数据", "--range", "A1:C2", "--json", json_path, "--html", html_path, "--redact")
    assert result.returncode == 0, result.stderr
    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "PASS"
    for path in (json_path, html_path):
        exported = path.read_text(encoding="utf-8")
        assert "123456789.123" not in exported
        assert "00123" not in exported
        assert "A2" in exported


@pytest.mark.parametrize("args", [[], ["check"], ["serve", "--port", "0"], ["serve", "--host", "0.0.0.0"]])
def test_invalid_command_returns_input_error(args):
    result = run_cli(*args)
    assert result.returncode == 3
    assert "Traceback" not in result.stderr


def test_missing_file_and_zero_table_return_input_error(source, tmp_path):
    missing = run_cli("inspect", tmp_path / "missing.xlsx")
    assert missing.returncode == 3
    zero = run_cli("check", source, "--markdown", "absent.md", "--sheet", "数据", "--range", "A1:C2", "--table", "0")
    assert zero.returncode == 3
    assert "Traceback" not in missing.stderr + zero.stderr


def test_check_refuses_to_overwrite_source(source, tmp_path):
    original = source.read_bytes()
    md = tmp_path / "in.md"
    md.write_text("| A |\n| --- |\n| B |", encoding="utf-8")
    result = run_cli("check", source, "--markdown", md, "--sheet", "数据", "--range", "A1:C2", "--json", source)
    assert result.returncode == 3
    assert source.read_bytes() == original


def test_occupied_port_is_runtime_error_not_check_failure():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        result = run_cli("serve", "--port", str(listener.getsockname()[1]))
    assert result.returncode == 3, result.stderr


def test_same_json_and_html_destination_does_not_overwrite(source, tmp_path):
    output = tmp_path / "existing.txt"
    output.write_text("keep this report", encoding="utf-8")
    result = run_cli("check", source, "--markdown", "absent.md", "--sheet", "数据", "--range", "A1:C2", "--json", output, "--html", output)
    assert result.returncode == 3
    assert output.read_text(encoding="utf-8") == "keep this report"
