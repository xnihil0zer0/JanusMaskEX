"""A STATEFUL class with shared __init__ state and one multi-method test."""


class Accumulator:
    """Accumulate values, tracking the running total and the count of adds."""

    def __init__(self, start: int = 0) -> None:
        """Seed the running total with ``start`` and zero the add count."""
        self.total = start
        self.count = 0

    def add(self, x: int) -> None:
        """Add ``x`` to the running total and increment the add count."""
        self.total += x
        self.count += 1

    def mean(self) -> float:
        """Return total/count of the adds, or 0.0 when nothing was added."""
        return self.total / self.count if self.count else 0.0
