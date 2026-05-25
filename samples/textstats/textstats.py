"""A real branching/looping/multi-variable module for the oversized-unit driver.

Unlike samples/bigpipe (a single carry variable threaded through a linear
pipeline), ``summarize`` keeps SEVERAL independent live variables across
multiple phases, each with its own loop and branches. It exercises
decompose -> reconstruct -> recompose on genuinely non-linear logic: the blind
agent must reconstruct each contiguous segment (multiple statements, nested
branches, accumulators) from the signature + docstring + tests + prior
segments, not just re-thread one variable.
"""


def summarize(text):
    """Tokenize ``text`` into alphanumeric words and report statistics.

    Processing happens in four phases, each iterating over the data:

      1. Tokenize: scan the characters of ``text``, accumulating maximal runs
         of alphanumeric characters into ``words`` (any non-alphanumeric
         character is a separator that closes the current word).
      2. Classify each word by length: words of 3 or fewer characters are
         "short", longer words are "long".
      3. Vowel histogram: count occurrences of each vowel (a, e, i, o, u,
         case-insensitive) across every character of every word, as a dict
         keyed by the lowercase vowel.
      4. Longest + averages: the longest word (the FIRST one on a length tie),
         the total number of characters across all words, and the average word
         length = total / word-count rounded to 2 decimals (0.0 if no words).

    Returns a dict with keys: ``words`` (int count), ``short`` (int),
    ``long`` (int), ``vowels`` (dict), ``longest`` (str), ``total_len`` (int),
    and ``avg_len`` (float).
    """
    words = []
    current = ""
    for ch in text:
        if ch.isalnum():
            current += ch
        elif current:
            words.append(current)
            current = ""
    if current:
        words.append(current)
    short = 0
    long = 0
    for w in words:
        if len(w) <= 3:
            short += 1
        else:
            long += 1
    vowels = {}
    for w in words:
        for ch in w:
            c = ch.lower()
            if c in "aeiou":
                vowels[c] = vowels.get(c, 0) + 1
    longest = ""
    total_len = 0
    for w in words:
        total_len += len(w)
        if len(w) > len(longest):
            longest = w
    avg_len = round(total_len / len(words), 2) if words else 0.0
    return {
        "words": len(words),
        "short": short,
        "long": long,
        "vowels": vowels,
        "longest": longest,
        "total_len": total_len,
        "avg_len": avg_len,
    }
