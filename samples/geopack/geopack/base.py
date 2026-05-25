"""Base geometry helpers -- one half of the base<->shapes import CYCLE."""
from . import shapes


def unit_length() -> int:
    """Return the canonical unit length (always 1)."""
    return 1


def double_area(n: int) -> int:
    """Return twice the area of an ``n``-sided unit square."""
    return 2 * shapes.square_area(n)
