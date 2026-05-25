from textstats import summarize


def test_empty():
    assert summarize("") == {
        "words": 0,
        "short": 0,
        "long": 0,
        "vowels": {},
        "longest": "",
        "total_len": 0,
        "avg_len": 0.0,
    }


def test_simple_sentence():
    assert summarize("The quick brown fox") == {
        "words": 4,
        "short": 2,
        "long": 2,
        "vowels": {"e": 1, "u": 1, "i": 1, "o": 2},
        "longest": "quick",
        "total_len": 16,
        "avg_len": 4.0,
    }


def test_punctuation_and_digits():
    assert summarize("Hello, World! 123") == {
        "words": 3,
        "short": 1,
        "long": 2,
        "vowels": {"e": 1, "o": 2},
        "longest": "Hello",
        "total_len": 13,
        "avg_len": 4.33,
    }


def test_length_and_vowel_edges():
    assert summarize("a aa aaa aaaa") == {
        "words": 4,
        "short": 3,
        "long": 1,
        "vowels": {"a": 10},
        "longest": "aaaa",
        "total_len": 10,
        "avg_len": 2.5,
    }


def test_longest_first_on_tie():
    # quick and brown both length 5; the first (quick) wins
    assert summarize("quick brown")["longest"] == "quick"
