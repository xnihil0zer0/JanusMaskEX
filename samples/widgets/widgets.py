"""Sample target exercising the C9.6 robustness features of the rebuild engine.

Unlike ``samples/mathlib`` (pure, self-contained functions), this module has:

  * an intra-module call dependency (``quadruple`` calls ``double``) -- the
    reconstruction of ``quadruple`` needs ``double``'s real BODY at fuzz time,
    not just its signature (sibling-body injection);
  * an impure function (``file_size`` does filesystem IO) -- the
    merged==original oracle is unreliable for it, so the engine must take the
    tests-only verification path;
  * a class with methods (``Accumulator``) -- harvest/strip must handle
    ClassDef method units, not only module-level functions.
"""

from __future__ import annotations

import os


def double(x: int) -> int:
    """Return x doubled."""
    return x * 2


def quadruple(x: int) -> int:
    """Return x quadrupled by composing double (intra-module call dependency)."""
    return double(double(x))


def file_size(path: str) -> int:
    """Return the byte size of path, or -1 if it does not exist (impure: filesystem IO)."""
    if not os.path.exists(path):
        return -1
    return os.path.getsize(path)


class Accumulator:
    """A tiny stateful accumulator (a class with reconstructible methods)."""

    def __init__(self, start: int = 0) -> None:
        """Initialize the running total to start."""
        self.total = start

    def add(self, x: int) -> int:
        """Add x to the running total and return the new total."""
        self.total += x
        return self.total

    def reset(self) -> None:
        """Reset the running total to zero."""
        self.total = 0
