"""Wiring oracle for the worker-sidecar-purge leaf (plan-validator *_wired requirement).

The edited module is harness/orchestrator_worker.py — itself a LIVE_ROOT — so
this asserts the edit target stays a wired live entrypoint and that the new
bridge is reachable from it (module-level symbol on the live module).
"""
from pathlib import Path

from harness.wire_up import check_wired


def test_orchestrator_worker_is_wired_live_root():
    repo_root = Path(__file__).resolve().parents[1]
    res = check_wired(repo_root, 'harness/orchestrator_worker.py')
    assert res.wired, res.reason


def test_purge_bridge_reachable_on_live_module():
    import harness.orchestrator_worker as ow
    assert callable(getattr(ow, '_purge_stale_sidecars_safe', None)), (
        'the purge bridge must be a module-level symbol on the live worker module')
