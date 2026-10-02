# 合成对照 / Synthetic controls

`synthetic.xlsx` 是人工构造的数据，所有内容均可公开。`correct.md` 与 `lossy.md` 也由人工定义，**不是任何版本 MarkItDown 的实际输出**。它们只验证 TableProof 的规则和演示流程，不构成对转换器的性能或准确率测量。

The workbook and both Markdown files are hand-authored synthetic fixtures, **not observed converter output**. They exercise TableProof's comparison rules without making claims about any converter.

映射：工作表 `Demo`、范围 `A1:D4`、Markdown 第一张表、包含一行表头。

| 文件 | 预期 |
| --- | --- |
| `correct.md` | `PASS`，数值/文字/空值均对应 |
| `lossy.md` | `FAIL`；A2、A3 丢前导零，B2 数值改变，C2、C3 字面文本改变，D2 空值变为文本 |

`A\|B` 用于验证 Markdown 转义竖线，`0.125` 没有百分比格式。工作簿不含公式、宏、外部链接或真实个人信息。文件属性署名为 TableProof contributors。

```bash
python scripts/generate_examples.py
tableproof check examples/synthetic.xlsx --markdown examples/correct.md --sheet Demo --range A1:D4
tableproof check examples/synthetic.xlsx --markdown examples/lossy.md --sheet Demo --range A1:D4 --html example-report.html
```

生成器会替换这些合成示例文件。对转换器做真实实验时，请保留其版本与参数，并把测量结果与这些人工对照分开。
