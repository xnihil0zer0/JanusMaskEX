"""Tiny pure-math sample library used as the rebuild engine's smoke target.

Every function is pure, deterministic, integer-domain, and self-contained
(no inter-function calls), which makes it the minimal honest target for the
clean-room rebuild loop: each body can be reconstructed blind by the dual
agents and checked merged-equivalent against the original.
"""

from __future__ import annotations


def gcd(a: int, b: int) -> int:
    """Return the greatest common divisor of a and b (Euclid's algorithm).

    Operates on absolute values, so the result is always non-negative.
    gcd(0, 0) == 0.
    """
    a, b = abs(a), abs(b)
    while b:
        a, b = b, a % b
    return a


def is_prime(n: int) -> bool:
    """Return True iff n is a prime number.

    n < 2 is never prime. 2 and 3 are prime. Even numbers > 2 are not.
    Trial division by odd factors up to sqrt(n).
    """
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0:
        return False
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 2
    return True


def fib(n: int) -> int:
    """Return the nth Fibonacci number (fib(0) == 0, fib(1) == 1).

    Negative n returns 0. Iterative, so it is O(n) and never recurses.
    """
    if n < 0:
        return 0
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a
