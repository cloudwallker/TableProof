# TableProof

### Cell-level fidelity checks for Excel-to-Markdown conversions

**Compare an original XLSX workbook with converted Markdown, identify confirmed differences, and inspect their source-cell evidence—all locally.**

English | [中文](README_ZH.md)

[Install](#install) · [Try it](#try-it) · [Commands](#commands) · [Validation](docs/validation.md) · [Contributing](CONTRIBUTING.md)

![TableProof local UI showing three synthetic differences and source-cell evidence](docs/images/tableproof.jpg)

Give TableProof an original XLSX workbook and an existing Markdown conversion. It independently reads the source cells and compares an explicitly selected range by position. Findings explain changes such as text `00123` becoming `123`, `123456789.123` becoming `1.234568e+08`, or literal `NA` becoming `NaN`, with the source cell coordinates.

Use the CLI or local web interface to preview the selected cell-to-table mapping and export findings as JSON or HTML.

## Install

Python 3.10 or later is required. Run these commands from the project directory:

```bash
git clone https://github.com/cloudwallker/TableProof.git
cd TableProof
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Run only the activation command for your platform, or call `.venv/bin/python` / `.venv\Scripts\python.exe` directly. This project has not been published to PyPI; install from the local directory to avoid an unrelated package with the same name.

## Try it

```bash
tableproof inspect examples/synthetic.xlsx
tableproof check examples/synthetic.xlsx --markdown examples/correct.md --sheet Demo --range A1:D4
tableproof check examples/synthetic.xlsx --markdown examples/lossy.md --sheet Demo --range A1:D4 --html report.html --json report.json
tableproof serve --open
```

The first Markdown fixture should `PASS`; the second should `FAIL`. They are **hand-authored synthetic controls, not measured MarkItDown output**. They make no claim about a current or historical converter version. See [examples/README.md](examples/README.md).

The local interface binds exclusively to `127.0.0.1` (default port `8765`). `--port 9000` changes the port; only `--open` launches a browser. Upload the files, choose a range and table, review the mapping preview, then confirm the comparison. Files are processed locally with no telemetry or model calls. Workbook macros, formulas and external links are not executed.

After installing the environment, Windows users can also double-click `Start-TableProof.cmd` in the project root.

## Commands

| Command | Purpose |
| --- | --- |
| `inspect FILE` | Print sheet metadata as JSON, without cell contents |
| `check FILE --markdown FILE --sheet NAME --range A1:C3` | Check an explicit mapping |
| `serve [--port 8765] [--open]` | Start the loopback-only interface |
| `convert FILE --output converted.md` | Optionally run local MarkItDown and record conversion metadata |

By default, the first selected XLSX row maps to the Markdown header. With `--no-header`, every selected source row maps to Markdown data rows; the Markdown header is ignored. `--table 2` selects the second table. CLI table numbers start at 1; JSON `table_index` starts at 0. Same-size row or column reordering is not detected automatically; the user must confirm the mapping.

```bash
tableproof check source.xlsx --markdown converted.md --sheet Sheet1 --range B2:D20 --table 2 --no-header --json -
tableproof check source.xlsx --markdown converted.md --sheet Sheet1 --range A1:C3 --html shared.html --json shared.json --redact
```

`--json -` emits JSON to stdout and the summary to stderr. Output paths are overwritten if they already exist, but cannot refer to an input file. `--redact` removes values and potentially sensitive descriptions from exported reports while preserving coordinates, rule identifiers and counts. Full reports may contain private data; review them before sharing.

| Exit code | Status | Meaning |
| --- | --- | --- |
| `0` | `PASS` | All selected cells match under supported rules |
| `1` | `FAIL` | At least one confirmed difference |
| `2` | `INDETERMINATE` | No confirmed difference, but some cells or structures cannot be verified |
| `3` | Error | Invalid input/arguments, file access, missing dependency or runtime error |

Confirmed differences take precedence over unknown results in the overall status. Shape mismatches produce a structural issue and `INDETERMINATE`, without assigning misleading cell-level differences.

## Optional conversion

```bash
python -m pip install -e ".[convert]"
tableproof convert examples/synthetic.xlsx --output converted.md
```

`converted.md.metadata.json` records the MarkItDown version, parameters, source/output SHA-256 hashes and timestamp, without absolute paths. Third-party MarkItDown plugins are disabled. Missing optional dependencies return code `3`; all other commands remain available. Conversion output is never used as its own verification baseline.

## Limits

A PASS result covers the selected mapped cells under supported comparison rules. Workbook-wide completeness, formula correctness, and an AI system's interpretation require separate checks.

- XLSX only for this release, one sheet and contiguous rectangle, mapped to one GFM table. CSV input is not implemented.
- Raw numeric XML values are compared using decimal arithmetic. `1`, `1.0` and `1e0` are numerically equal. No default tolerance or guessed locale/thousands separators.
- Text identifiers retain leading zeros. Literal `NA`, `NULL`, `NaN` and blanks remain distinct. A source distinction that Markdown cannot express, such as an empty string versus an absent cell, is not certified.
- Formulas use saved cached results only, with unknown freshness. Missing caches yield an indeterminate result; no recalculation.
- Stored values and display formats are separate. Unsupported date/percentage interpretation is indeterminate; `0.125` versus `12.5%` is not automatically labelled corruption.
- Recognizable unsupported structures, including merged cells, HTML/nested tables and incomplete rows, are reported. Only a single header row is supported; the user must confirm this. Semantic multi-row headings made from ordinary text cannot be identified automatically. Relationships, units, totals and reordered mappings are not verified.
- XLSX input is limited to 10 MiB, expanded ZIP content to 50 MiB, Markdown to 2 MiB, and a selection to 10,000 cells. Oversized input is rejected rather than silently truncated.
- Data already lost before the workbook was saved cannot be recovered. Redaction is not automatic authorization to publish a report.

## Develop

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check src tests scripts
python -m build
python scripts/generate_examples.py
```

Contributions should include small synthetic regression fixtures and independently specified expectations. Include converter version and parameters for real conversion reports, and never publish private spreadsheets or credentials. See [CONTRIBUTING.md](CONTRIBUTING.md).

MIT License · Copyright (c) 2026 TableProof contributors.

## Interface

Local Excel-to-Markdown fidelity checks with readable cell evidence, keyboard-accessible filters, and responsive workspace and offline HTML reports.
