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
    raise NotImplementedError

def test_banner_contribution():
    """Banner count contributes 0.1 per unit."""
    raise NotImplementedError

def test_descendant_contribution():
    """Descendant count contributes 0.05 per unit."""
    raise NotImplementedError

def test_depth_contribution():
    """Max depth contributes 0.15 per unit."""
    raise NotImplementedError

def test_combined_inputs():
    """Multiple factors contribute additively."""
    raise NotImplementedError

def test_clamped_at_one():
    """Results above 1.0 are clamped to 1.0."""
    raise NotImplementedError

def test_realistic_task_pathology():
    """Realistic task decomposition pathology scores."""
    raise NotImplementedError

def test_monotonic_increasing_banner():
    """Score increases monotonically with banner_count."""
    raise NotImplementedError

def test_monotonic_increasing_depth():
    """Score increases monotonically with max_depth."""
    raise NotImplementedError

def test_bounded_zero_to_one():
    """Score is bounded at 1.0 for all reasonable inputs."""
    raise NotImplementedError

def test_negative_input_not_clamped_to_zero():
    """Negative inputs produce negative scores without lower-bound clamping."""
    raise NotImplementedError
BANNER_WEIGHT = 0.1
DESCENDANT_WEIGHT = 0.05
DEPTH_WEIGHT = 0.15
if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])