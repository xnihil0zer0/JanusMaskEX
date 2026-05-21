import os
import tempfile
from pathlib import Path

import pytest

from harness.safe_subpath import is_safe_subpath


class TestSafeSubpath:
    """Unit tests for is_safe_subpath function."""

    def test_safe_absolute_descendant(self):
        assert is_safe_subpath('/tmp/worktree/safe.py', '/tmp/worktree') is True

    def test_safe_relative_descendant(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                Path('src').mkdir(exist_ok=True)
                Path('src/file.py').touch()
                assert is_safe_subpath('./src/file.py', '.') is True
            finally:
                os.chdir(old_cwd)

    def test_unsafe_traversal_escape(self):
        assert is_safe_subpath('../../etc/passwd', '/tmp/worktree') is False

    def test_sibling_not_descendant(self):
        assert is_safe_subpath('/tmp/other', '/tmp/worktree') is False

    def test_none_inputs(self):
        assert is_safe_subpath(None, '/tmp/worktree') is False
        assert is_safe_subpath('/tmp/worktree', None) is False
        assert is_safe_subpath(None, None) is False

    def test_empty_string_inputs(self):
        assert is_safe_subpath('', '') is True
        assert is_safe_subpath('', '/tmp') is False

    def test_double_dot_escapes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = Path(tmpdir) / 'subdir'
            subdir.mkdir()
            escape_path = str(subdir / '..' / '..' / 'etc' / 'passwd')
            assert is_safe_subpath(escape_path, tmpdir) is False

    def test_reflexive_path_is_safe_to_itself(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert is_safe_subpath(tmpdir, tmpdir) is True

    def test_with_real_tempdir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_dir = Path(tmpdir) / 'a' / 'b' / 'c'
            nested_dir.mkdir(parents=True)
            nested_file = nested_dir / 'file.txt'
            nested_file.write_text('test')
            assert is_safe_subpath(str(nested_file), tmpdir) is True
            assert is_safe_subpath(tmpdir, str(nested_dir)) is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
