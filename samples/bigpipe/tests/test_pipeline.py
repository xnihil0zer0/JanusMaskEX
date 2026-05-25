from bigpipe.pipeline import normalize


def test_basic_collapse_and_capitalize():
    assert normalize("  hello   world  ") == "Hello World."


def test_strips_punctuation_spacing():
    assert normalize("foo , bar .") == "Foo Bar."


def test_underscores_and_dashes_become_spaces():
    assert normalize("foo_bar-baz") == "Foo Bar Baz."


def test_short_words_not_titlecased():
    assert normalize("a an the cat") == "A an The Cat."


def test_alnum_only_kept():
    assert normalize("he!!o w@rld") == "Heo Wrld."


def test_empty_returns_empty():
    assert normalize("   ") == ""


def test_already_terminated():
    assert normalize("done.") == "Done."
