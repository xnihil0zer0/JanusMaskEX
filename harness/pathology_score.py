"""Task pathology metric calculator for decomposition characteristics."""
import math

def pathology_score(banner_count: int, descendant_count: int, max_depth: int) -> float:
    """Calculate a pathology score for a task decomposition.

    Factors: 0.1 * banner_count + 0.05 * descendant_count + 0.15 * max_depth
    Upper bound is enforced via min(1.0, ...); no lower bound is applied.
    Negative inputs propagate to negative outputs — caller must pre-validate.
    Pure arithmetic; never raises.

    Args:
        banner_count: Number of banners in task decomposition.
        descendant_count: Number of descendant tasks.
        max_depth: Maximum decomposition depth.

    Returns:
        A float pathology score, bounded above at 1.0.
    """
    raise NotImplementedError

def test_zero_inputs():
    """Zero inputs should return 0.0."""
    assert pathology_score(0, 0, 0) == 0.0

def test_banner_contribution():
    """Banner count contributes 0.1 per unit."""
    assert math.isclose(pathology_score(1, 0, 0), 0.1)
    assert math.isclose(pathology_score(2, 0, 0), 0.2)
    assert math.isclose(pathology_score(3, 0, 0), 0.3)

def test_descendant_contribution():
    """Descendant count contributes 0.05 per unit."""
    assert math.isclose(pathology_score(0, 1, 0), 0.05)
    assert math.isclose(pathology_score(0, 2, 0), 0.1)
    assert math.isclose(pathology_score(0, 10, 0), 0.5)

def test_depth_contribution():
    """Max depth contributes 0.15 per unit."""
    assert math.isclose(pathology_score(0, 0, 1), 0.15)
    assert math.isclose(pathology_score(0, 0, 2), 0.3)
    assert math.isclose(pathology_score(0, 0, 6), 0.9)

def test_combined_inputs():
    """Multiple factors contribute additively."""
    assert math.isclose(pathology_score(3, 0, 0), 0.3)
    assert math.isclose(pathology_score(0, 0, 6), 0.9)
    assert math.isclose(pathology_score(2, 4, 1), 0.55)

def test_clamped_at_one():
    """Results above 1.0 are clamped to 1.0."""
    assert math.isclose(pathology_score(5, 10, 2), 1.0)
    assert math.isclose(pathology_score(100, 100, 100), 1.0)

def test_realistic_task_pathology():
    """Realistic task decomposition pathology scores."""
    simple = pathology_score(2, 3, 1)
    assert 0.0 < simple < 1.0
    assert math.isclose(simple, 0.5)
    complex_task = pathology_score(4, 8, 3)
    assert math.isclose(complex_task, 1.0)

def test_monotonic_increasing_banner():
    """Score increases monotonically with banner_count."""
    base = pathology_score(0, 5, 2)
    for i in range(1, 5):
        score = pathology_score(i, 5, 2)
        assert score > base, f'Score should increase with banner_count'
        base = score

def test_monotonic_increasing_depth():
    """Score increases monotonically with max_depth."""
    base = pathology_score(2, 5, 0)
    for i in range(1, 5):
        score = pathology_score(2, 5, i)
        assert score > base, f'Score should increase with max_depth'
        base = score

def test_bounded_zero_to_one():
    """Score is bounded at 1.0 for all reasonable inputs."""
    test_cases = [(0, 0, 0), (1, 1, 1), (10, 10, 10), (5, 5, 5), (100, 200, 50)]
    for banner, descendant, depth in test_cases:
        score = pathology_score(banner, descendant, depth)
        assert score <= 1.0, f'Score should be clamped at 1.0, got {score}'

def test_negative_input_not_clamped_to_zero():
    """Negative inputs produce negative scores without lower-bound clamping."""
    assert math.isclose(pathology_score(-1, 0, 0), -0.1)
    assert math.isclose(pathology_score(0, -5, 0), -0.25)
    assert math.isclose(pathology_score(0, 0, -2), -0.3)
    assert math.isclose(pathology_score(1, -10, 2), -0.1)
BANNER_WEIGHT = 0.1
DESCENDANT_WEIGHT = 0.05
DEPTH_WEIGHT = 0.15
if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])