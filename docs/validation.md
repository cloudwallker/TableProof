# Validation and interfaces / 验证与接口

TableProof compares an explicitly selected XLSX rectangle with one Markdown table. The source reader and Markdown reader operate independently; conversion output is never used as its own verification baseline.

TableProof 比较明确选定的 XLSX 矩形范围与一张 Markdown 表。两种格式独立读取，转换结果不能作为自己的验证基准。

## Reproduce the checks / 复现检查

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check src tests scripts
python -m build
```

The test suite covers independent expected values, raw numeric precision, text identifiers, blank distinctions, formula caches, explicit mapping, structural uncertainty, report escaping and redaction, input/output path protection, and the local interface. It uses synthetic data. Test success does not establish accuracy on real-world workbooks.

测试使用合成数据，覆盖独立预期值、原始数值精度、文本标识、空值区别、公式缓存、显式映射、结构不确定性、报告转义和脱敏、输入输出路径保护与本地界面。测试通过不能证明真实工作簿的准确率。

## Expected examples / 合成示例预期

```bash
tableproof check examples/synthetic.xlsx --markdown examples/correct.md --sheet Demo --range A1:D4
tableproof check examples/synthetic.xlsx --markdown examples/lossy.md --sheet Demo --range A1:D4
```

The first command returns `PASS` with exit code `0`. The second returns `FAIL` with exit code `1`, identifying six deliberately introduced differences. These are hand-authored controls, not outputs measured from a particular converter. See [the fixture definitions](../examples/README.md).

第一条命令应返回 `PASS`，退出码为 `0`；第二条应返回 `FAIL`，退出码为 `1`，定位六处人工加入的差异。样例不能用于断言某个转换器存在缺陷，详见 [样例定义](../examples/README.md)。

## Comparison contract / 比较规则

| Result | Meaning / 含义 |
| --- | --- |
| `PASS` | Every selected cell matches under supported rules. / 选定范围在支持规则下相符。 |
| `FAIL` | A confirmed difference exists. / 至少存在一处确定差异。 |
| `INDETERMINATE` | No confirmed difference exists, but some selected content cannot be verified. / 没有确定差异，但存在无法验证的内容。 |

Confirmed differences take precedence over unknown results. Structural mismatches produce a structural issue without guessing cell alignments. CLI table numbers start at `1`; JSON `table_index` starts at `0`. The selected source row maps to the Markdown header unless `--no-header` is supplied. Users must confirm mappings; equal-size reordering is not detected automatically.

确定差异优先于不确定结果。结构尺寸不符时只报告结构问题，不猜测单元格对齐。CLI 表编号从 `1` 开始，JSON `table_index` 从 `0` 开始。默认将源选区第一行映射到 Markdown 表头；`--no-header` 改为只映射数据行。使用者必须确认映射，工具不会自动识别同尺寸的行列重排。

Raw numeric XML values use decimal arithmetic: `1`, `1.0` and `1e0` are equal, with no default tolerance. Text `00123` is distinct from numeric `123`. Literal `NA`, `NULL` and `NaN` remain text; blanks are not silently normalized into them. Missing formula caches, unsupported display interpretations and distinctions Markdown cannot preserve are indeterminate.

原始 XML 数值使用十进制运算；`1`、`1.0`、`1e0` 等价，没有默认容差。文本 `00123` 与数值 `123` 不同。字面量 `NA`、`NULL`、`NaN` 保持文本含义，空白不会被静默归并。缺失公式缓存、不支持的显示格式解释，以及 Markdown 无法表达的区别，均返回不确定结果。

## Reports and privacy / 报告与隐私

Use `--json -` for machine-readable output and `--redact` when preparing a report for sharing. Redaction removes cell values and sensitive descriptions while retaining coordinates, rule identifiers and counts. Review every exported report before publishing it. Inputs stay on the local machine; macros, formulas and external links are not executed.

`--json -` 将机器可读结果写入标准输出。准备共享报告时可用 `--redact`，移除单元格值及敏感描述，保留坐标、规则标识和数量。发布前仍须人工检查报告。输入在本机处理，宏、公式和外部链接不会执行。

CI runs tests and builds the package on Linux and Windows with Python 3.10 and 3.12. It does not publish packages or releases.

CI 在 Linux、Windows 及 Python 3.10、3.12 组合上执行测试和构建，不自动发布包或 Release。
