from app.services.review_service import add_review_items, count_open, find_duplicate_suspects


def test_duplicate_translation_with_different_sources_is_suspect():
    sources = ["Das ist ein erster Satz.", "Etwas ganz anderes hier."]
    targets = ["این یک جمله تکراری است", "این یک جمله تکراری است"]
    assert find_duplicate_suspects(sources, targets) == [(0, 1)]


def test_legitimate_repetition_in_source_is_ignored():
    sources = ["Ganz toll, wirklich.", "Ganz toll, wirklich."]
    targets = ["واقعا عالیه این کار", "واقعا عالیه این کار"]
    assert find_duplicate_suspects(sources, targets) == []


def test_short_lines_are_ignored():
    assert find_duplicate_suspects(["Ja.", "Nein."], ["آره", "آره"]) == []


def test_review_items_are_stored_with_absolute_numbers(tmp_path):
    path = str(tmp_path / "review.json")
    assert add_review_items(path, [(0, 2)], 25) == 1
    assert add_review_items(path, [(0, 2)], 25) == 0
    assert count_open(path) == 1


from app.services.review_service import restore_colors


def test_restore_colors_per_line():
    src = '<font color="#00FF00">Hallo, Andi.</font>\n<font color="#FFFF00">Theo, du musst aufstehen.</font>'
    tr = '<font color="#00FF00">سلام</font>\nباید پاشی'
    fixed, changed = restore_colors(src, tr)
    assert changed
    assert fixed == '<font color="#00FF00">سلام</font>\n<font color="#FFFF00">باید پاشی</font>'


def test_restore_colors_unchanged_when_equal_or_ambiguous():
    src = '<font color="#FFFFFF">A</font>\n<font color="#FF0000">B</font>'
    assert restore_colors(src, src) == (src, False)
    assert restore_colors(src, "یک خط") == ("یک خط", False)
