"""Name-casing helpers built on the inflection library (cross-module + cycle)."""

import inflection

import text


def to_snake(name):
    """Return the snake_case form of a CamelCase or spaced name."""
    return inflection.underscore(name.replace(" ", "_"))


def to_title(name):
    """Return the Title Case form of a name, splitting words via text.split_words."""
    return " ".join(word.capitalize() for word in text.split_words(name))


class Caser:
    """Stateless name caser exposing the module helpers as methods."""

    def snake(self, name):
        """Return the snake_case form of ``name``."""
        return to_snake(name)

    def title(self, name):
        """Return the Title Case form of ``name``."""
        return to_title(name)
