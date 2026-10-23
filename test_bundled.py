from bot.scraper import list_parts, list_units, parse_words

HTML = """
<html><body>
<h2>Unit 1</h2>
<h3>Part A</h3>
<table>
  <tr><td>cat</td><td>кот</td></tr>
  <tr><td>dog</td><td>собака; пёс</td></tr>
  <tr><td>Header</td></tr>
</table>
<h3>Part B</h3>
<table><tr><th>apple</th><th>яблоко</th></tr><tr><td>fine</td><td>hello</td></tr></table>
<h2>Unit 2</h2>
<table><tr><td>house</td><td>дом</td></tr></table>
<script>var x = "<tr><td>evil</td><td>зло</td></tr>";</script>
</body></html>
"""


def test_parse_units_parts_and_rows():
    rows = parse_words(HTML)
    assert [(r.unit, r.part, r.en, r.ru) for r in rows] == [
        ("1", "A", "cat", "кот"),
        ("1", "A", "dog", "собака; пёс"),
        ("1", "B", "apple", "яблоко"),
        ("2", "", "house", "дом"),
    ]


def test_rows_without_cyrillic_translation_skipped_and_scripts_ignored():
    rows = parse_words(HTML)
    assert all(r.en != "evil" for r in rows)
    assert all(r.en != "fine" for r in rows)


def test_units_and_parts_listing():
    rows = parse_words(HTML)
    assert list_units(rows) == ["1", "2"]
    assert list_parts(rows, "1") == ["A", "B"]


def test_empty_page_has_no_words():
    assert parse_words("<html><body><p>Nothing here</p></body></html>") == []
