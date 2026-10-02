"""Optional converter tests isolate the external library, not file behavior."""

import hashlib
import importlib
import json
from types import SimpleNamespace

import pytest
from openpyxl import Workbook


def write_source(path):
    book = Workbook()
    book.active.append(["地区"])
    book.active.append(["NA"])
    book.save(path)


def test_convert_dependency_error_has_install_instruction(tmp_path, monkeypatch):
    from tableproof.adapter import convert_file
    from tableproof.errors import InputError

    source = tmp_path / "source.xlsx"
    write_source(source)
    original_import = importlib.import_module

    def missing(name, *args, **kwargs):
        if name == "markitdown":
            raise ModuleNotFoundError("No module named 'markitdown'", name="markitdown")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", missing)
    with pytest.raises(InputError, match=r"\[convert\]"):
        convert_file(source, tmp_path / "out.md")
    assert not (tmp_path / "out.md").exists()


def test_convert_writes_unicode_markdown_and_versioned_metadata(tmp_path, monkeypatch):
    from tableproof import adapter

    source = tmp_path / "源表.xlsx"
    write_source(source)
    output = tmp_path / "结果.md"

    class Converter:
        def __init__(self, *, enable_plugins):
            assert enable_plugins is False

        def convert(self, path):
            assert path == str(source)
            return SimpleNamespace(text_content="| 地区 |\n| --- |\n| NA |\n")

    original_import = importlib.import_module
    monkeypatch.setattr(importlib, "import_module", lambda name: SimpleNamespace(MarkItDown=Converter) if name == "markitdown" else original_import(name))
    monkeypatch.setattr(adapter.metadata, "version", lambda name: "0.1.test")
    result = adapter.convert_file(source, output)
    saved = json.loads((tmp_path / "结果.md.metadata.json").read_text(encoding="utf-8"))
    assert saved == result
    assert saved["converter"] == {"name": "markitdown", "version": "0.1.test", "parameters": {"enable_plugins": False}}
    assert saved["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert saved["output_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert "NA" in output.read_text(encoding="utf-8")
    assert str(tmp_path) not in json.dumps(saved)


def test_convert_cannot_overwrite_input_even_with_markdown_suffix(tmp_path):
    from tableproof.adapter import convert_file
    from tableproof.errors import InputError

    source = tmp_path / "source.xlsx"
    source.write_bytes(b"original")
    with pytest.raises(InputError):
        convert_file(source, source)
    assert source.read_bytes() == b"original"


def test_invalid_workbook_is_rejected_before_optional_conversion(tmp_path):
    from tableproof.adapter import convert_file
    from tableproof.errors import InputError

    source, output = tmp_path / "invalid.xlsx", tmp_path / "out.md"
    source.write_bytes(b"not an XLSX file")
    with pytest.raises(InputError, match="工作簿|XLSX 压缩"):
        convert_file(source, output)
    assert not output.exists()


def test_metadata_hardlink_cannot_overwrite_converted_markdown(tmp_path, monkeypatch):
    from tableproof.adapter import convert_file
    from tableproof.errors import InputError

    source, output = tmp_path / "source.xlsx", tmp_path / "out.md"
    write_source(source)
    output.write_text("original", encoding="utf-8")
    sidecar = tmp_path / "out.md.metadata.json"
    sidecar.hardlink_to(output)
    original_import = importlib.import_module
    converter = SimpleNamespace(convert=lambda path: SimpleNamespace(text_content="| a |\n| --- |"))
    monkeypatch.setattr(importlib, "import_module", lambda name: SimpleNamespace(MarkItDown=lambda **kwargs: converter)
                        if name == "markitdown" else original_import(name))
    with pytest.raises(InputError, match="不同"):
        convert_file(source, output)
    assert output.read_text(encoding="utf-8") == "original"
    assert sidecar.read_text(encoding="utf-8") == "original"
