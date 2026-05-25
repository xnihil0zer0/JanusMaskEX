"""Word-splitting helpers; normalizes names via casing (cycle partner)."""

import casing


def split_words(name):
    """Split a name into lowercase words via casing.to_snake."""
    return [w for w in casing.to_snake(name).split("_") if w]


def word_count(name):
    """Return the number of words in a name."""
    return len(split_words(name))
