"""Adversarial smoke coverage for harness.pathology_score.

Pins the public contract of pathology_score:
  * bounded above at 1.0 (min clamp)
  * NOT bounded below (negative inputs propagate — documented contract)
  * monotonic in each non-negative factor
  * pure arithmetic; never raises

These tests are the test-partner for the module under harness/ so Gate 3
(test-partner for new public symbols) finds harness.pathology_score imported.
The module itself also carries embedded test_* functions that are NOT collected
by the main battery (harness/ is not on the pytest rootdir). This file is the
canonical external coverage.
"""

import math

import pytest

from harness.pathology_score import pathology_score


class TestHappyPath:
    def test_zero_inputs_return_zero(self) -> None:
        assert pathology_score(0, 0, 0) == 0.0

    def test_banner_weighted_0_1(self) -> None:
        assert math.isclose(pathology_score(1, 0, 0), 0.1)

    def test_descendant_weighted_0_05(self) -> None:
        assert math.isclose(pathology_score(0, 1, 0), 0.05)

    def test_depth_weighted_0_15(self) -> None:
        assert math.isclose(pathology_score(0, 0, 1), 0.15)

    def test_additive_combination(self) -> None:
        # 0.1*2 + 0.05*4 + 0.15*1 = 0.55
        assert math.isclose(pathology_score(2, 4, 1), 0.55)


class TestUpperBound:
    def test_clamped_at_one_for_sum_over_one(self) -> None:
        assert pathology_score(5, 10, 2) == 1.0  # 1.3 clamped

    def test_large_inputs_stay_at_one(self) -> None:
        assert pathology_score(1_000, 1_000, 1_000) == 1.0

    def test_exactly_at_boundary(self) -> None:
        # 0.1*10 + 0 + 0 = 1.0 exactly — clamp is no-op
        assert pathology_score(10, 0, 0) == 1.0


class TestLowerBoundSemantics:
    """Negative inputs propagate — NO lower-bound clamp. Pinned contract."""

    def test_negative_banner_propagates(self) -> None:
        assert math.isclose(pathology_score(-1, 0, 0), -0.1)

    def test_negative_descendant_propagates(self) -> None:
        assert math.isclose(pathology_score(0, -5, 0), -0.25)

    def test_negative_depth_propagates(self) -> None:
        assert math.isclose(pathology_score(0, 0, -2), -0.3)

    def test_mixed_sign_inputs_not_clamped_at_zero(self) -> None:
        # 0.1 + (-0.5) + 0.30 = -0.1  (crosses zero; must stay negative)
        assert math.isclose(pathology_score(1, -10, 2), -0.1)


class TestMonotonicity:
    def test_increases_with_banner_count(self) -> None:
        prev = pathology_score(0, 5, 2)
        for i in range(1, 5):
            cur = pathology_score(i, 5, 2)
            assert cur >= prev
            prev = cur

    def test_increases_with_depth(self) -> None:
        prev = pathology_score(2, 5, 0)
        for i in range(1, 5):
            cur = pathology_score(2, 5, i)
            assert cur >= prev
            prev = cur


class TestPurity:
    def test_same_inputs_same_output(self) -> None:
        a = pathology_score(3, 7, 2)
        b = pathology_score(3, 7, 2)
        assert a == b

    def test_no_exception_on_extreme_inputs(self) -> None:
        # Must not raise on any int triple including negatives and huge values.
        for triple in [(0, 0, 0), (-10_000, -10_000, -10_000), (10**9, 10**9, 10**9)]:
            pathology_score(*triple)  # should not raise

    def test_returns_float(self) -> None:
        assert isinstance(pathology_score(1, 2, 3), float)


class TestTypeCoercion:
    def test_bool_inputs_coerce_to_int(self) -> None:
        # Python bool is-a int; pathology_score(True, False, True) == 0.1 + 0 + 0.15 = 0.25
        assert math.isclose(pathology_score(True, False, True), 0.25)

    def test_float_inputs_accepted(self) -> None:
        # Contract is "int" but arithmetic tolerates floats; pin current behaviour.
        assert math.isclose(pathology_score(1.0, 2.0, 1.0), 0.35)
