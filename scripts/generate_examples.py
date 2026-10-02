"""Generate public, hand-authored controls; these are not converter measurements."""

import json
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook


def main():
    output = Path(__file__).resolve().parents[1] / "examples"
    output.mkdir(exist_ok=True)
    workbook = Workbook()
    workbook.properties.creator = "TableProof contributors"
    workbook.properties.lastModifiedBy = "TableProof contributors"
    workbook.properties.title = "TableProof synthetic controls"
    workbook.properties.description = "Hand-authored synthetic data, not a converter benchmark."
    utc_stamp = datetime(2026, 10, 2, tzinfo=timezone.utc).replace(tzinfo=None)
    workbook.properties.created = utc_stamp
    workbook.properties.modified = utc_stamp
    sheet = workbook.active
    sheet.title = "Demo"
    for row in [
        ["编号", "金额", "地区", "备注"],
        ["00123", 123456789.123, "NA", None],
        ["00007", 42, "NULL", "A|B"],
        ["00999", 0.125, "nan", "合成样例"],
    ]:
        sheet.append(row)
    for column in "ABCD":
        sheet.column_dimensions[column].width = 22
    workbook.save(output / "synthetic.xlsx")
    prefix = "# 合成对照（人工定义，非转换器实测）\n\n| 编号 | 金额 | 地区 | 备注 |\n| --- | --- | --- | --- |\n"
    (output / "correct.md").write_text(
        prefix + "| 00123 | 123456789.123 | NA | |\n| 00007 | 42 | NULL | A\\|B |\n| 00999 | 0.125 | nan | 合成样例 |\n",
        encoding="utf-8",
    )
    (output / "lossy.md").write_text(
        prefix + "| 123 | 1.234568e+08 | NaN | NaN |\n| 7 | 42 | NaN | A\\|B |\n| 00999 | 0.125 | nan | 合成样例 |\n",
        encoding="utf-8",
    )
    (output / "expected.json").write_text(json.dumps({
        "synthetic": True,
        "converter_measurement": False,
        "source": "synthetic.xlsx",
        "mapping": {"sheet": "Demo", "range_ref": "A1:D4", "table_index": 0, "header": True},
        "scenarios": {
            "correct.md": {"status": "PASS", "failed_coordinates": []},
            "lossy.md": {"status": "FAIL", "failed_coordinates": ["A2", "B2", "C2", "D2", "A3", "C3"]},
        },
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
