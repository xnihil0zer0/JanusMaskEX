"""Auto-tag every test under tests/adversarial/ with the `slow` marker.

These are the heavy integration tests (subprocess / daemon / git-worktree
spawns) that dominate full-sweep wall time. Tagging them `slow` lets the fast
inner-loop tier exclude them via `-m "not slow"` while the serial gate still
runs everything. The `slow` marker is registered in pytest.ini.
"""
import pytest
_ADVERSARIAL_DIR = 'tests/adversarial/'

def pytest_collection_modifyitems(config, items):
    """Add the `slow` marker to every collected item under tests/adversarial/."""
    for item in items:
        path = str(getattr(item, 'fspath', '')).replace('\\', '/')
        if _ADVERSARIAL_DIR in path:
            item.add_marker(pytest.mark.slow)