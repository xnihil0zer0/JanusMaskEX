"""Spec for the mathlib rebuild target. Copied VERBATIM into the output repo.

These tests are the only behavioral contract the dual agents see when they
reconstruct each body blind. They are RED against the stripped skeleton and
must go GREEN once every body is reconstructed and merged.
"""

import mathlib


class TestGcd:
    def test_basic(self):
        assert mathlib.gcd(12, 8) == 4
        assert mathlib.gcd(54, 24) == 6

    def test_coprime(self):
        assert mathlib.gcd(13, 7) == 1

    def test_zero(self):
        assert mathlib.gcd(0, 0) == 0
        assert mathlib.gcd(5, 0) == 5
        assert mathlib.gcd(0, 5) == 5

    def test_negative(self):
        assert mathlib.gcd(-12, 8) == 4
        assert mathlib.gcd(12, -8) == 4


class TestIsPrime:
    def test_small(self):
        assert mathlib.is_prime(2) is True
        assert mathlib.is_prime(3) is True
        assert mathlib.is_prime(4) is False

    def test_not_prime(self):
        assert mathlib.is_prime(0) is False
        assert mathlib.is_prime(1) is False
        assert mathlib.is_prime(9) is False
        assert mathlib.is_prime(15) is False

    def test_prime(self):
        assert mathlib.is_prime(13) is True
        assert mathlib.is_prime(97) is True

    def test_negative(self):
        assert mathlib.is_prime(-7) is False


class TestFib:
    def test_base(self):
        assert mathlib.fib(0) == 0
        assert mathlib.fib(1) == 1

    def test_sequence(self):
        assert mathlib.fib(2) == 1
        assert mathlib.fib(7) == 13
        assert mathlib.fib(10) == 55

    def test_negative(self):
        assert mathlib.fib(-3) == 0
