"""Optional local converter; the checker does not depend on this module."""

import hashlib
import importlib
import json
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from .errors import InputError
from .xlsx import MAX_INPUT_BYTES, inspect_workbook


def convert_file(source: str | Path, output: str | Path) -> dict:
    """Convert XLSX with optional MarkItDown and write a provenance sidecar."""
    source, output = Path(source), Path(output)
    if source.suffix.lower() != ".xlsx":
        raise InputError("可选转换仅支持 .xlsx 文件。")
    if source.resolve() == output.resolve() or (output.exists() and source.samefile(output)):
        raise InputError("输出路径不能覆盖源工作簿。")
    if not source.is_file():
        raise InputError("找不到源工作簿。")
    with source.open("rb") as stream:
        source_data = stream.read(MAX_INPUT_BYTES + 1)
    # Apply the same input/ZIP expansion checks as the independent reader.
    inspect_workbook(source_data)
    try:
        module = importlib.import_module("markitdown")
    except ImportError as exc:
        raise InputError("缺少可选转换依赖，请在项目目录运行：python -m pip install '.[convert]'") from exc

    parameters = {"enable_plugins": False}
    try:
        version = metadata.version("markitdown")
    except metadata.PackageNotFoundError:
        version = str(getattr(module, "__version__", "unknown"))
    try:
        converted = module.MarkItDown(**parameters).convert(str(source))
        text = converted.text_content
    except ImportError as exc:
        raise InputError("缺少 XLSX 转换依赖，请在项目目录运行：python -m pip install '.[convert]'") from exc
    except Exception as exc:
        raise InputError(f"MarkItDown 转换失败（{type(exc).__name__}）。") from exc
    if not isinstance(text, str):
        raise InputError("MarkItDown 没有返回 Markdown 文本。")

    output_bytes = text.encode("utf-8")
    result = {
        "schema_version": 1,
        "converter": {"name": "markitdown", "version": version, "parameters": parameters},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": hashlib.sha256(source_data).hexdigest(),
        "output_sha256": hashlib.sha256(output_bytes).hexdigest(),
    }
    sidecar = Path(str(output) + ".metadata.json")
    # Preflight both destinations before modifying either one.
    if output.resolve() == sidecar.resolve() or (output.exists() and sidecar.exists() and output.samefile(sidecar)):
        raise InputError("Markdown 与元数据必须写入不同文件。")
    for path in (output, sidecar):
        if not path.parent.is_dir() or path.is_dir():
            raise InputError("输出目录不存在，或输出路径是目录。")
        if path.exists() and source.samefile(path):
            raise InputError("输出路径不能覆盖源工作簿。")
    output.write_bytes(output_bytes)
    sidecar.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
