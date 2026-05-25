import re
from typing import List, Tuple


def strip_decomposition_suffixes(task_id: str) -> str:
    """Remove all trailing decomposition-related suffixes from task_id.
    
    Suffixes to strip: -reviewed, -compose, -boundary, -empty_input, -type_error, -general, -single_element
    Strips repeatedly until no suffix matches. Pure string operation; no I/O.
    Never raises.
    
    Args:
        task_id: The task ID string to normalize
        
    Returns:
        The task_id with all trailing decomposition suffixes removed
    """
    suffixes = re.compile(r'(-reviewed|-compose|-boundary|-empty_input|-type_error|-general|-single_element)$')
    prev = None
    while prev != task_id:
        prev = task_id
        task_id = suffixes.sub('', task_id)
    return task_id


class TestStripDecompositionSuffixes:
    """Test suite for strip_decomposition_suffixes function."""

    def test_no_suffix_unchanged(self):
        """Test that task IDs without suffixes remain unchanged."""
        assert strip_decomposition_suffixes('GIT-COMMIT-001') == 'GIT-COMMIT-001'
        assert strip_decomposition_suffixes('TASK-123') == 'TASK-123'
        assert strip_decomposition_suffixes('PS-001') == 'PS-001'

    def test_single_suffix_removed(self):
        """Test that a single trailing suffix is removed."""
        assert strip_decomposition_suffixes('GIT-COMMIT-001-reviewed') == 'GIT-COMMIT-001'
        assert strip_decomposition_suffixes('TASK-123-compose') == 'TASK-123'
        assert strip_decomposition_suffixes('PS-001-boundary') == 'PS-001'

    def test_multiple_suffixes_removed(self):
        """Test that multiple trailing suffixes are all removed."""
        assert strip_decomposition_suffixes('GIT-COMMIT-001-reviewed-compose') == 'GIT-COMMIT-001'
        assert strip_decomposition_suffixes('PS-001-boundary-empty_input-type_error') == 'PS-001'
        assert strip_decomposition_suffixes('TASK-123-general-single_element') == 'TASK-123'

    def test_repeated_suffix_removed(self):
        """Test that repeated suffixes are all removed."""
        assert strip_decomposition_suffixes('GIT-COMMIT-001-reviewed-reviewed') == 'GIT-COMMIT-001'
        assert strip_decomposition_suffixes('PS-001-boundary-boundary-boundary') == 'PS-001'
        assert strip_decomposition_suffixes('TASK-123-compose-compose') == 'TASK-123'

    def test_empty_string(self):
        """Test that empty string returns empty string."""
        assert strip_decomposition_suffixes('') == ''

    def test_all_seven_suffix_types(self):
        """Test that all seven suffix types are recognized and removed."""
        base = 'ROOT'
        assert strip_decomposition_suffixes(f'{base}-reviewed') == base
        assert strip_decomposition_suffixes(f'{base}-compose') == base
        assert strip_decomposition_suffixes(f'{base}-boundary') == base
        assert strip_decomposition_suffixes(f'{base}-empty_input') == base
        assert strip_decomposition_suffixes(f'{base}-type_error') == base
        assert strip_decomposition_suffixes(f'{base}-general') == base
        assert strip_decomposition_suffixes(f'{base}-single_element') == base

    def test_complex_chain_real_task_id(self):
        """Integration test with complex chain of suffixes on real-like task ID."""
        task_id = 'GIT-REFACTOR-042-boundary-empty_input-type_error-reviewed-compose'
        expected = 'GIT-REFACTOR-042'
        assert strip_decomposition_suffixes(task_id) == expected

    def test_idempotent_second_call_returns_same(self):
        """Property test: calling twice should return the same result."""
        task_id = 'PS-001-boundary-empty_input-type_error'
        first_call = strip_decomposition_suffixes(task_id)
        second_call = strip_decomposition_suffixes(first_call)
        assert first_call == second_call

    def test_interior_suffix_not_removed(self):
        """Regression test: suffixes in the middle should not be stripped."""
        # Interior occurrence should NOT be stripped
        task_id = 'GIT-reviewed-reviewed-COMMIT-001'
        expected = 'GIT-reviewed-COMMIT-001'
        assert strip_decomposition_suffixes(task_id) == expected

    def test_suffix_like_substrings_not_removed(self):
        """Verify that suffix patterns that are not trailing are preserved."""
        # '-reviewed' is part of the task ID, not a trailing suffix
        task_id = 'REVIEW-001'
        assert strip_decomposition_suffixes(task_id) == 'REVIEW-001'
        
        # Compound word containing suffix
        task_id = 'COMPOSE-002'
        assert strip_decomposition_suffixes(task_id) == 'COMPOSE-002'

    def test_only_suffix(self):
        """Test behavior when input is only a suffix."""
        # Should strip the suffix and return empty string
        assert strip_decomposition_suffixes('-reviewed') == ''
        assert strip_decomposition_suffixes('-compose') == ''

    def test_mixed_suffix_order(self):
        """Test that suffix order doesn't matter; all are removed."""
        # Order shouldn't affect the result since we strip all matching suffixes
        task_id = 'TASK-999-general-type_error-boundary'
        expected = 'TASK-999'
        assert strip_decomposition_suffixes(task_id) == expected


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
