"""Shape-area helpers -- the other half of the base<->shapes import CYCLE."""
from . import base


def square_area(n: int) -> int:
    """Return the area of an ``n``-sided square in unit-length units."""
    return n * n * base.unit_length()
