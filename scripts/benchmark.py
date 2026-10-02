"""Reproducible synthetic benchmark, with Python-allocation (not RSS) memory."""
import json
import platform
import time
import tracemalloc
from io import BytesIO

from openpyxl import Workbook

from tableproof.engine import audit


def main():
    size = 100
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Synthetic"
    headers = [f"c{index}" for index in range(size)]
    sheet.append(headers)
    rows = [list(range(row * size, (row + 1) * size)) for row in range(size - 1)]
    for row in rows:
        sheet.append(row)
    source = BytesIO()
    workbook.save(source)
    markdown = "\n".join("|" + "|".join(map(str, row)) + "|" for row in
                         [headers, ["---"] * size, *rows])
    tracemalloc.start()
    started = time.perf_counter()
    report = audit(source.getvalue(), markdown, "Synthetic", "A1:CV100")
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(json.dumps({"case": "100x100 synthetic numeric table", "platform": platform.platform(),
                      "python": platform.python_version(), "xlsx_bytes": len(source.getvalue()),
                      "markdown_bytes": len(markdown.encode()), "status": report["status"],
                      "summary": report["summary"], "elapsed_seconds_with_tracemalloc": round(elapsed, 3),
                      "python_allocation_peak_mib": round(peak / (1024 * 1024), 2)}, indent=2))


if __name__ == "__main__":
    main()
