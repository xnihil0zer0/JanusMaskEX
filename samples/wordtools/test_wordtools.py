from casing import Caser, to_snake, to_title
from text import split_words, word_count


def test_to_snake():
    assert to_snake("CamelCase") == "camel_case"
    assert to_snake("hello world") == "hello_world"


def test_split_words():
    assert split_words("CamelCase") == ["camel", "case"]
    assert split_words("hello world") == ["hello", "world"]


def test_word_count():
    assert word_count("one two three") == 3


def test_to_title():
    assert to_title("hello_world") == "Hello World"


def test_caser_snake():
    assert Caser().snake("FooBar") == "foo_bar"


def test_caser_title():
    assert Caser().title("hello_world") == "Hello World"
