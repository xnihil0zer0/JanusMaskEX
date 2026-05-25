"""Pure metrics over word lists (this module ships NO tests of its own)."""


def char_total(words: list[str]) -> int:
    """Return the total number of characters across all words."""
    return sum(len(word) for word in words)


def longest(words: list[str]) -> str:
    """Return the longest word; '' if the list is empty. Earliest wins ties."""
    if not words:
        return ""
    best = words[0]
    for word in words[1:]:
        if len(word) > len(best):
            best = word
    return best
