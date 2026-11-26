"""Loopback-only, memory-only web workflow for TableProof."""

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .errors import InputError
from .report import redact_report, render_html

MAX_BODY_BYTES = 16 * 1024 * 1024
MAX_XLSX_BYTES = 10 * 1024 * 1024
MAX_MARKDOWN_BYTES = 2 * 1024 * 1024
STATIC = Path(__file__).parent / "static"


def _origin(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1"}:
            return None
        if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            return None
        return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None


class LocalOnlyMiddleware:
    """Check authority before reading data, and cap actual streamed bytes."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope["headers"]}
        local_origin = _origin(f'{scope.get("scheme", "http")}://{headers.get("host", "")}')
        error = None
        if local_origin is None:
            error = (403, "仅允许 localhost 或 127.0.0.1 访问本地服务。")
        elif "origin" in headers and _origin(headers["origin"]) != local_origin:
            error = (403, "请求来源与本地页面不一致，请在当前本地页面重试。")
        elif headers.get("sec-fetch-site") == "cross-site":
            error = (403, "不接受外部网页发起的请求。")
        try:
            declared_length = int(headers.get("content-length", "0"))
            if declared_length < 0:
                raise ValueError
            if declared_length > MAX_BODY_BYTES:
                error = (413, "请求过大：请缩小文件或选定范围。")
        except ValueError:
            error = (400, "请求长度无效。")

        async def safe_send(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend([
                    (b"x-content-type-options", b"nosniff"), (b"cache-control", b"no-store"),
                    (b"referrer-policy", b"no-referrer"), (b"x-frame-options", b"DENY"),
                    (b"content-security-policy", (b"default-src 'self'; script-src 'self'; style-src 'self'; "
                     b"img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
                     b"frame-ancestors 'none'; form-action 'self'")),
                ])
            await send(message)

        if error:
            return await JSONResponse({"detail": error[1]}, status_code=error[0])(scope, receive, safe_send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > MAX_BODY_BYTES:
                return await JSONResponse({"detail": "请求超过 16 MiB 限制。"}, status_code=413)(scope, receive, safe_send)
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, safe_send)


async def _json(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise InputError("请使用本地页面发送 JSON 请求。")
    try:
        result = await request.json()
    except (ValueError, UnicodeError, RecursionError):
        raise InputError("请求数据格式无效，请重新选择文件。") from None
    if not isinstance(result, dict):
        raise InputError("请求必须包含一个数据对象。")
    return result


def _input(data, require_mapping=True):
    encoded = data.get("xlsx_base64")
    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_XLSX_BYTES + 2) // 3):
        raise InputError("请选择不超过 10 MiB 的 XLSX 文件。")
    try:
        xlsx_data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise InputError("XLSX 文件编码无效，请重新选择文件。") from None
    if not xlsx_data or len(xlsx_data) > MAX_XLSX_BYTES:
        raise InputError("XLSX 文件为空或超过 10 MiB 限制。")
    markdown = data.get("markdown", "")
    if not isinstance(markdown, str):
        raise InputError("Markdown 必须是文本，且不能超过 2 MiB。")
    try:
        markdown_bytes = markdown.encode("utf-8")
    except UnicodeError:
        raise InputError("Markdown 含有无效的 Unicode 字符，请重新导入 UTF-8 文本。") from None
    if len(markdown_bytes) > MAX_MARKDOWN_BYTES:
        raise InputError("Markdown 必须是文本，且不能超过 2 MiB。")
    if not require_mapping:
        return xlsx_data, markdown
    sheet, range_ref = data.get("sheet"), data.get("range_ref")
    if not isinstance(sheet, str) or not sheet or not isinstance(range_ref, str) or not range_ref:
        raise InputError("请选择工作表并填写 A1 范围。")
    try:
        sheet.encode("utf-8")
        range_ref.encode("utf-8")
    except UnicodeError:
        raise InputError("工作表名或范围含有无效的 Unicode 字符。") from None
    index, header = data.get("table_index", 0), data.get("header", True)
    if type(index) is not int or index < 0 or type(header) is not bool:
        raise InputError("Markdown 表编号或表头选项无效。")
    return xlsx_data, markdown, sheet, range_ref, index, header


def _token(secret, args):
    digest = hashlib.sha256(args[0]).hexdigest()
    message = json.dumps([digest, *args[1:]], ensure_ascii=False, separators=(",", ":")).encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _inspect(data):
    from .markdown import parse_tables
    from .xlsx import inspect_workbook
    xlsx_data, markdown = _input(data, require_mapping=False)
    result = inspect_workbook(xlsx_data)
    result["tables"] = [{"index": table["index"], "rows": len(table["rows"]),
                         "columns": len(table["header"]), "header": table["header"],
                         "issues": table["issues"]}
                        for table in parse_tables(markdown)] if markdown.strip() else []
    return result


def _preview(data, secret):
    from .markdown import parse_tables
    from .xlsx import read_range
    args = _input(data)
    xlsx_data, markdown, sheet, range_ref, index, header = args
    source = read_range(xlsx_data, sheet, range_ref)
    tables = parse_tables(markdown, check_header_content=header)
    if index >= len(tables):
        raise InputError("未找到所选 Markdown 表，请检查内容和表编号。")
    table = tables[index]
    rows = ([table["header"]] if header else []) + table["rows"]
    source_rows = source["rows"]
    source_columns = len(source_rows[0]) if source_rows else 0
    matches = len(source_rows) == len(rows) and all(len(row) == source_columns for row in rows)
    issues = list(source["issues"]) + list(table["issues"])
    if not matches:
        issues.append("行列尺寸不一致；分析只报告结构问题，不逐格归因。")
    return {"mapping_token": _token(secret, args), "sheet": source["sheet"], "range_ref": source["range_ref"],
            "source_rows": len(source_rows), "source_columns": source_columns,
            "markdown_rows": len(rows), "markdown_columns": len(table["header"]),
            "source_preview": [row[:8] for row in source_rows[:6]], "markdown_preview": [row[:8] for row in rows[:6]],
            "preview_limited": len(source_rows) > 6 or len(rows) > 6 or source_columns > 8 or len(table["header"]) > 8,
            "dimensions_match": matches, "issues": issues, "header": header}


def _audit(data, secret):
    from .engine import audit
    args = _input(data)
    token = data.get("mapping_token", "")
    if (data.get("confirmed") is not True or not isinstance(token, str) or not token.isascii()
            or not hmac.compare_digest(token, _token(secret, args))):
        raise InputError("请先预览当前文件与范围，并明确确认行列对应关系。")
    return audit(*args)


def _demo():
    from openpyxl import Workbook
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "合成样例"
    sheet.append(["项目", "存储数值", "文本标记", "备注"])
    sheet.append(["精度示例", 123456789.123, "NA", None])
    sheet.append(["一致对照", 42, "001", "人工合成"])
    buffer = BytesIO()
    workbook.save(buffer)
    return {"xlsx_base64": base64.b64encode(buffer.getvalue()).decode("ascii"), "sheet": sheet.title,
            "range_ref": "A1:D3", "table_index": 0, "header": True, "filename": "tableproof-demo.xlsx",
            "markdown": "| 项目 | 存储数值 | 文本标记 | 备注 |\n| --- | --- | --- | --- |\n"
                        "| 精度示例 | 1.234568e+08 | NaN | NaN |\n| 一致对照 | 42 | 001 | 人工合成 |",
            "notice": "此示例为人工合成的精度、文本和空值变化；未使用外部转换器，不代表任何转换器当前行为。"}


def create_app() -> FastAPI:
    """Build an app without storing uploaded files, sessions, or audit data."""
    app = FastAPI(title="TableProof", docs_url=None, redoc_url=None, openapi_url=None)
    secret = secrets.token_bytes(32)
    app.add_middleware(LocalOnlyMiddleware)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.exception_handler(InputError)
    async def input_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))

    @app.get("/api/demo")
    async def demo():
        return await run_in_threadpool(_demo)

    @app.post("/api/inspect")
    async def inspect(request: Request):
        return await run_in_threadpool(_inspect, await _json(request))

    @app.post("/api/preview")
    async def preview(request: Request):
        return await run_in_threadpool(_preview, await _json(request), secret)

    @app.post("/api/audit")
    async def audit(request: Request):
        return await run_in_threadpool(_audit, await _json(request), secret)

    @app.post("/api/export")
    async def export(request: Request, format: str = "json", redact: bool = False):
        data = await _json(request)
        report = data.get("report")
        if (not isinstance(report, dict) or not isinstance(report.get("scope"), dict)
                or not isinstance(report.get("summary"), dict) or not isinstance(report.get("cells"), list)
                or not isinstance(report.get("issues", []), list)):
            raise InputError("报告数据无效，请重新运行分析。")
        if format not in {"json", "html"}:
            raise InputError("仅支持 JSON 或 HTML 导出。")
        try:
            if format == "json":
                result = redact_report(report) if redact else report
                content = json.dumps(result, ensure_ascii=False, indent=2)
                media_type = "application/json"
            else:
                content, media_type = render_html(report, redact=redact), "text/html"
            return Response(content, media_type=media_type,
                            headers={"Content-Disposition": f'attachment; filename="tableproof-report.{format}"'})
        except (TypeError, ValueError, AttributeError, KeyError, UnicodeError, RecursionError):
            raise InputError("报告结构无效，请重新运行分析。") from None

    return app
