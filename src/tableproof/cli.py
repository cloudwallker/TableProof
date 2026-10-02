"""Command-line entry points for independent local table verification."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .errors import InputError


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise InputError(message)


def _positive(value):
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是正整数") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("必须是正整数（表编号从 1 开始）")
    return number


def _port(value):
    number = _positive(value)
    if number > 65535:
        raise argparse.ArgumentTypeError("端口必须在 1 到 65535 之间")
    return number


def _parser():
    parser = _Parser(prog="tableproof", description="独立检查 XLSX 与 Markdown 的单元格转换差异。")
    parser.add_argument("--version", action="version", version=f"TableProof {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="列出工作表和使用范围")
    inspect.add_argument("file", type=Path)
    check = commands.add_parser("check", help="检查明确映射的源范围和 Markdown 表")
    check.add_argument("file", type=Path)
    check.add_argument("--markdown", type=Path, required=True)
    check.add_argument("--sheet", required=True)
    check.add_argument("--range", dest="range_ref", required=True)
    check.add_argument("--table", type=_positive, default=1, help="Markdown 表编号，从 1 开始")
    check.add_argument("--no-header", dest="header", action="store_false", help="源范围全部行对齐 Markdown 数据行")
    check.add_argument("--json", dest="json_path", help="JSON 输出路径，或 - 写到 stdout")
    check.add_argument("--html", dest="html_path", type=Path, help="独立 HTML 报告路径")
    check.add_argument("--redact", action="store_true", help="导出时隐藏单元格内容等敏感字段")
    serve = commands.add_parser("serve", help="启动只监听 127.0.0.1 的本地界面")
    serve.add_argument("--port", type=_port, default=8765)
    serve.add_argument("--open", action="store_true", help="服务就绪后打开浏览器")
    convert = commands.add_parser("convert", help="可选使用 MarkItDown 转换 XLSX")
    convert.add_argument("file", type=Path)
    convert.add_argument("--output", type=Path, required=True)
    return parser


def _read_limited(path, limit):
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise InputError(f"输入文件超过 {limit // (1024 * 1024)} MiB 限制。")
    return data


def _same_path(first, second):
    return first.resolve() == second.resolve() or (
        first.exists() and second.exists() and first.samefile(second)
    )


def _check(args):
    from .engine import audit
    from .markdown import MAX_INPUT_BYTES as MAX_MARKDOWN_BYTES
    from .report import redact_report, render_html
    from .xlsx import MAX_INPUT_BYTES as MAX_XLSX_BYTES

    outputs = []
    if args.json_path and args.json_path != "-":
        outputs.append(Path(args.json_path))
    if args.html_path:
        outputs.append(args.html_path)
    for index, path in enumerate(outputs):
        if any(_same_path(path, input_path) for input_path in (args.file, args.markdown)):
            raise InputError("报告输出路径不能覆盖输入文件。")
        if any(_same_path(path, other) for other in outputs[:index]):
            raise InputError("JSON 与 HTML 报告必须使用不同输出路径。")
        if not path.parent.is_dir() or path.is_dir():
            raise InputError("报告输出目录不存在，或输出路径是目录。")
    workbook = _read_limited(args.file, MAX_XLSX_BYTES)
    markdown = _read_limited(args.markdown, MAX_MARKDOWN_BYTES).decode("utf-8-sig")
    report = audit(workbook, markdown, args.sheet, args.range_ref, args.table - 1, args.header)
    exported = redact_report(report) if args.redact else report
    if args.json_path:
        content = json.dumps(exported, ensure_ascii=False, indent=2) + "\n"
        if args.json_path == "-":
            print(content, end="")
        else:
            Path(args.json_path).write_text(content, encoding="utf-8")
    if args.html_path:
        args.html_path.write_text(render_html(report, redact=args.redact), encoding="utf-8")
    summary = report["summary"]
    stream = sys.stderr if args.json_path == "-" else sys.stdout
    print(
        f"{report['status']} · 总计 {summary['total']} · "
        f"通过 {summary['passed']} · 差异 {summary['failed']} · 无法判断 {summary['indeterminate']}",
        file=stream,
    )
    for cell in report["cells"]:
        if cell["status"] != "PASS":
            print(f"  {cell['coordinate']}: {cell['status']} [{cell['rule']}]", file=stream)
    if report["issues"]:
        print(f"  范围或结构提示：{len(report['issues'])} 项；使用 --json 或 --html 查看详情。", file=stream)
    return {"PASS": 0, "FAIL": 1, "INDETERMINATE": 2}[report["status"]]


def _serve(args):
    import threading
    import webbrowser

    import uvicorn

    from .web import create_app

    url = f"http://127.0.0.1:{args.port}"

    class LocalServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            if self.started and args.open:
                threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()

    print(f"TableProof 本地界面：{url}")
    server = LocalServer(uvicorn.Config(
        create_app(), host="127.0.0.1", port=args.port, access_log=False, proxy_headers=False,
    ))
    server.run()
    return 0 if server.started else 3


def main(argv=None):
    """Return the documented process exit code; never upload user input."""
    # UTF-8 keeps redirected Chinese reports portable on Windows as well.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        args = _parser().parse_args(argv)
        if args.command == "inspect":
            from .xlsx import MAX_INPUT_BYTES, inspect_workbook

            data = inspect_workbook(_read_limited(args.file, MAX_INPUT_BYTES))
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
        if args.command == "check":
            return _check(args)
        if args.command == "serve":
            return _serve(args)
        if args.command == "convert":
            from .adapter import convert_file

            result = convert_file(args.file, args.output)
            print(f"已转换 · MarkItDown {result['converter']['version']} · 版本和参数已写入 .metadata.json")
            return 0
    except (InputError, OSError, UnicodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("已停止。", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 -- CLI privacy boundary hides source-bearing exceptions.
        # Some parsers include source contents in exception strings.
        print(f"运行错误（{type(exc).__name__}），请检查输入或使用合成样例报告问题。", file=sys.stderr)
        return 3
    return 3
