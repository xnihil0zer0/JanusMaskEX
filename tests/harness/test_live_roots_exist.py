"""Wire-up-sweep remediation (#2): the LIVE_ROOTS seed must not list files that
do not exist.

WIRE_UP_HANDOFF.md §3/§7 flagged the shipped ``LIVE_ROOTS`` constant as STALE:
it still named three modules that were removed (harness/webui_control.py,
harness/overseer.py, harness/services.py) plus the old hook entrypoints
(harness/hooks/{claude,gemini}_hook.py). ``discover_live_roots`` filters
non-existent entries at runtime, so this is cosmetic -- but the seed constant
should still reflect reality. This oracle pins that every seeded root exists and
that the four genuine entrypoints are retained.
"""
from __future__ import annotations

from pathlib import Path

from harness.wire_up import LIVE_ROOTS

REPO_ROOT = Path(__file__).resolve().parents[2]

# The four real entrypoints that must remain seeded.
REAL_ENTRYPOINTS = [
    "harness/orchestrator.py",
    "harness/orchestrator_worker.py",
    "harness/autowork_daemon.py",
    "harness/planner/cli.py",
]


def test_every_live_root_exists():
    """No LIVE_ROOTS entry may point at a non-existent file."""
    missing = [r for r in LIVE_ROOTS if not (REPO_ROOT / r).is_file()]
    assert not missing, f"LIVE_ROOTS lists non-existent files: {missing}"


def test_real_entrypoints_retained():
    """The genuine live entrypoints stay in the seed."""
    for r in REAL_ENTRYPOINTS:
        assert r in LIVE_ROOTS, f"{r} must remain a seeded live root"
