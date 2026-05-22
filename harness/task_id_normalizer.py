import re
from typing import List
from typing import Tuple

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
    result = task_id
    changed = True
    while changed:
        changed = False
        for suffix in _DECOMPOSITION_SUFFIXES:
            if result.endswith(suffix):
                result = result[:-len(suffix)]
                changed = True
                break
    return result

class TestStripDecompositionSuffixes:
    """Test suite for strip_decomposition_suffixes function."""

    def test_no_suffix_unchanged(self):
        """Test that task IDs without suffixes remain unchanged."""
        raise NotImplementedError

    def test_single_suffix_removed(self):
        """Test that a single trailing suffix is removed."""
        raise NotImplementedError

    def test_multiple_suffixes_removed(self):
        """Test that multiple trailing suffixes are all removed."""
        raise NotImplementedError

    def test_repeated_suffix_removed(self):
        """Test that repeated suffixes are all removed."""
        raise NotImplementedError

    def test_empty_string(self):
        """Test that empty string returns empty string."""
        raise NotImplementedError

    def test_all_seven_suffix_types(self):
        """Test that all seven suffix types are recognized and removed."""
        raise NotImplementedError

    def test_complex_chain_real_task_id(self):
        """Integration test with complex chain of suffixes on real-like task ID."""
        raise NotImplementedError

    def test_idempotent_second_call_returns_same(self):
        """Property test: calling twice should return the same result."""
        raise NotImplementedError

    def test_interior_suffix_not_removed(self):
        """Regression test: suffixes in the middle should not be stripped."""
        raise NotImplementedError

    def test_suffix_like_substrings_not_removed(self):
        """Verify that suffix patterns that are not trailing are preserved."""
        raise NotImplementedError

    def test_only_suffix(self):
        """Test behavior when input is only a suffix."""
        raise NotImplementedError

    def test_mixed_suffix_order(self):
        """Test that suffix order doesn't matter; all are removed."""
        raise NotImplementedError
_DECOMPOSITION_SUFFIXES = ('-reviewed', '-compose', '-boundary', '-empty_input', '-type_error', '-general', '-single_element')
if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])