import pytest

from tableproof.errors import InputError
from tableproof.markdown import parse_tables


def test_plain_table_and_multiple_indices():
    result = parse_tables("| A | B |\n| --- | --- |\n| 1 | 2 |\n\nText\n\n| C |\n| --- |\n| 3 |")
    assert len(result) == 2
    assert result[0] == {"index": 0, "header": ["A", "B"], "rows": [["1", "2"]], "issues": []}
    assert result[1]["index"] == 1


def test_escaped_pipes_entities_and_backslashes_are_decoded():
    table = parse_tables(r"| A\|B | C |" + "\n| --- | --- |\n" + r"| one\|two | &amp; &lt;x&gt; \\ |")[0]
    assert table["header"] == ["A|B", "C"]
    assert table["rows"] == [["one|two", "& <x> \\"]]
    assert table["issues"] == []


def test_empty_rows_and_columns_are_preserved():
    table = parse_tables("| A | | C |\n| --- | --- | --- |\n| | | |\n| 1 | | 3 |")[0]
    assert table["header"] == ["A", "", "C"]
    assert table["rows"] == [["", "", ""], ["1", "", "3"]]
    assert table["issues"] == []


@pytest.mark.parametrize("row", ["| 1 |", "| 1 | 2 | 3 |", "1", "|"])
def test_malformed_row_width_cannot_be_silently_padded_or_truncated(row):
    table = parse_tables("| A | B |\n| --- | --- |\n" + row)[0]
    assert table["issues"]


@pytest.mark.parametrize(
    "cell",
    ["**bold**", "`code`", "[label](https://example.com)", "<b>HTML</b>", "![alt](image.png)", "~~strike~~"],
)
def test_unsupported_inline_expressions_are_flagged(cell):
    table = parse_tables("| A |\n| --- |\n| " + cell + " |")[0]
    assert table["issues"]


def test_html_only_and_no_table_are_explicitly_unknown():
    assert parse_tables("<table><tr><td>1</td></tr></table>")[0]["issues"]
    assert parse_tables("plain text") == []


def test_bad_separator_does_not_disappear_as_an_empty_input():
    tables = parse_tables("| A | B |\n| --- |\n| 1 | 2 |")
    assert tables and tables[0]["issues"]


def test_nested_table_is_flagged():
    table = parse_tables("> | A |\n> | --- |\n> | 1 |")[0]
    assert table["issues"]


def test_tables_in_code_fences_are_not_parsed():
    assert parse_tables("```\n| A |\n| --- |\n| 1 |\n```") == []


def test_markdown_input_limit():
    with pytest.raises(InputError):
        parse_tables("x" * (2 * 1024 * 1024 + 1))


def test_unicode_line_separator_is_cell_text_not_a_markdown_row_break():
    table = parse_tables("| a\u2028b | C |\n| --- | --- |\n| a\u2028b | D |")[0]
    assert table["header"] == ["a\u2028b", "C"]
    assert table["rows"] == [["a\u2028b", "D"]]
    assert table["issues"] == []
