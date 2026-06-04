"""Auto-tag every test under tests/adversarial/ with the `slow` marker.

These are the heavy integration tests (subprocess / daemon / git-worktree
spawns) that dominate full-sweep wall time. Tagging them `slow` lets the fast
inner-loop tier exclude them via `-m "not slow"` while the serial gate still
runs everything. The `slow` marker is registered in pytest.ini.
"""
import pytest
_ADVERSARIAL_DIR = 'tests/adversarial/'

def pytest_collection_modifyitems(config, items):
    """Mark adversarial items `slow`; pin shared-disk-state modules to one xdist group."""
    for item in items:
        path = str(getattr(item, 'fspath', '')).replace('\\', '/')
        if _ADVERSARIAL_DIR in path:
            item.add_marker(pytest.mark.slow)
        if path.rsplit('/', 1)[-1] in _SHARED_DISK_STATE_MODULES:
            item.add_marker(pytest.mark.xdist_group('shared_disk_state'))
_SHARED_DISK_STATE_MODULES = ('test_P2_mutation_kill.py', 'test_B3_F5_crash_recovery_adversarial.py', 'test_p10_config_flag.py', 'test_p5b_single_agent_promotion.py')
'Auto-tag every test under tests/adversarial/ with the `slow` marker, and pin\nmodules that mutate shared on-disk state to a single xdist group.\n\nThe `slow` tag (registered in pytest.ini) lets the fast inner-loop tier exclude\nthe heavy adversarial integration suite via `-m "not slow"`. The xdist_group pin\nforces the listed modules -- which read/write shared on-disk state (config.yaml,\nstate/ dirs, sidecars) and otherwise race across `-n auto` workers -- onto a\nsingle worker so parallel runs stay deterministic.\n'