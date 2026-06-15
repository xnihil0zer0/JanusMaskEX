---
interfaces: "NEW orchestration module ngv2/spawn_preflight.py exposing run_preflight(*, worker_type, task_target=None, recent_completions=None, available_memory_mb=None, active_workers=0, max_workers=8, running_targets=None, recent_target_completions=None, now=0.0, dedup_window_s=300, consecutive_failures=0, last_failure_at=None, force=False) -> dict (the 5-gate spawn preflight: cascade/memory/capacity/dedup/cooldown), plus the module constants MAX_CONCURRENT_WORKERS, CASCADE_FAILURE_THRESHOLD, CASCADE_MIN_SAMPLE, MEMORY_MIN_AVAILABLE_MB, DEDUP_COMPLETED_WINDOW_S, COOLDOWN_BASE_S, COOLDOWN_MAX_S and the helper _cooldown_seconds(consecutive_failures) -> int"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
meta_task_type: io_adapter
---

# Title

ngv2/spawn_preflight.py — NEW Phase-8.2 5-gate spawn preflight (cascade/memory/capacity/dedup/cooldown) concept-ported pure from legacy with injected facts

# Scope

Build a NEW orchestration module ngv2/spawn_preflight.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). This concept-ports legacy services/spawn_preflight.py's 5-gate spawn preflight (the gate that killed legacy's rate-limit cascade self-DoS) but DISCARDS legacy's host probing (no sqlite, no psutil, no os.path scans, no real clock): EVERY fact — recent completion outcomes, available memory, the active-worker census, running/recently-completed targets, the consecutive-failure streak, and the current time — is INJECTED, so run_preflight is pure, total, deterministic, and stdlib-only. The five gates run IN ORDER and short-circuit on the first BLOCK: (1) cascade — if >50% of >=4 recent completions failed, BLOCK; (2) memory — if injected available_memory_mb is below the 2048 MB floor, BLOCK; (3) capacity — if active_workers >= max_workers, BLOCK; (4) dedup — if task_target is running OR completed within dedup_window_s, BLOCK; (5) cooldown — if a per-type exponential backoff window (15s base, doubling, 180s cap) is still active since last_failure_at, BLOCK. A GO verdict returns the full gate list passed; a BLOCK names blocked_by and the partial gates passed before it. force=True bypasses all five (emergency only). Emit the whole file VERBATIM from Deliverables. Name the committed oracle tests/test_spawn_preflight_wired.py in the verification_command. Required plan shape: EXACTLY ONE impl task building this one new single file.

# Non-Goals

This is a NEW single-file module, not an edit; integration is out of scope — do NOT author or modify any test (the oracle tests/test_spawn_preflight_wired.py is committed and authoritative) and do NOT add integration/e2e tests. Do NOT touch, import, or alter ngv2/worker_registry.py, ngv2/dynamic_scheduler.py, ngv2/concurrency_scheduler.py, or any other module. Do NOT call sqlite, psutil, the filesystem, the network, a real clock, randomness, or subprocess in any path — every external fact is an injected argument. No LLM, no third-party imports (stdlib only). Touch exactly the one new file ngv2/spawn_preflight.py.

# Inputs

run_preflight receives all facts as keyword arguments: ``recent_completions`` is a sequence of mappings each with a ``success`` bool (default True); cascade BLOCKS only when there are >= CASCADE_MIN_SAMPLE (4) of them and the failed fraction exceeds CASCADE_FAILURE_THRESHOLD (0.50). ``available_memory_mb`` (int or None — None skips the memory gate) is compared to MEMORY_MIN_AVAILABLE_MB (2048). ``active_workers`` vs ``max_workers`` (default MAX_CONCURRENT_WORKERS=8) is the capacity gate (BLOCK on >=). ``task_target`` (str or None — None skips dedup) BLOCKS if in ``running_targets`` OR if ``recent_target_completions`` (a mapping target->epoch-seconds) has it within ``dedup_window_s`` (default DEDUP_COMPLETED_WINDOW_S=300) of the injected ``now``. The cooldown gate uses ``consecutive_failures`` (the per-type failure streak) -> _cooldown_seconds = min(COOLDOWN_BASE_S * 2**(n-1), COOLDOWN_MAX_S) and BLOCKS while (now - last_failure_at) < that window. ``force=True`` short-circuits to GO with reason 'forced'.

# Deliverables

ngv2/spawn_preflight.py with EXACTLY this content:

```python
"""ngv2.spawn_preflight — Phase-8.2 5-gate spawn preflight (concept-ported).

Concept-ports legacy services/spawn_preflight.py's pre-spawn gate that prevented
the three biggest worker-waste sources (rate-limit cascades, duplicate dispatch,
OOM) — the guard that killed legacy's spawn-storm self-DoS. DISCARDS legacy's
host probing: no sqlite, no psutil, no filesystem, no real clock. EVERY fact is
INJECTED, so run_preflight is pure, total, deterministic, and stdlib-only.

The five gates run IN ORDER and short-circuit on the first BLOCK:
    1. cascade  — >50% of >=4 recent completions failed.
    2. memory   — injected available memory below the 2 GB floor.
    3. capacity — active worker count at/above the cap.
    4. dedup    — same target running, or completed within the window.
    5. cooldown — per-type exponential backoff still active.
"""
from __future__ import annotations
from typing import Any, Dict, List, Mapping, Optional, Sequence

CASCADE_FAILURE_THRESHOLD = 0.50
CASCADE_MIN_SAMPLE = 4
MEMORY_MIN_AVAILABLE_MB = 2048
MAX_CONCURRENT_WORKERS = 8
DEDUP_COMPLETED_WINDOW_S = 300
COOLDOWN_BASE_S = 15
COOLDOWN_MAX_S = 180

_GATE_ORDER = ('cascade', 'memory', 'capacity', 'dedup', 'cooldown')


def _go() -> Dict[str, Any]:
    return {'verdict': 'GO', 'blocked_by': '', 'reason': '', 'gates': list(_GATE_ORDER)}


def _block(gate: str, reason: str, passed: List[str]) -> Dict[str, Any]:
    return {'verdict': 'BLOCKED', 'blocked_by': gate, 'reason': reason, 'gates': passed}


def _cooldown_seconds(consecutive_failures: int) -> int:
    """Per-type exponential backoff: 15s base, doubling, capped at 180s."""
    if consecutive_failures <= 0:
        return 0
    return min(COOLDOWN_BASE_S * (2 ** (consecutive_failures - 1)), COOLDOWN_MAX_S)


def run_preflight(
    *,
    worker_type: str,
    task_target: Optional[str] = None,
    recent_completions: Optional[Sequence[Mapping[str, Any]]] = None,
    available_memory_mb: Optional[int] = None,
    active_workers: int = 0,
    max_workers: int = MAX_CONCURRENT_WORKERS,
    running_targets: Optional[Sequence[str]] = None,
    recent_target_completions: Optional[Mapping[str, float]] = None,
    now: float = 0.0,
    dedup_window_s: int = DEDUP_COMPLETED_WINDOW_S,
    consecutive_failures: int = 0,
    last_failure_at: Optional[float] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Run the 5-gate spawn preflight over INJECTED facts. Pure & deterministic.

    Returns ``{'verdict': 'GO'|'BLOCKED', 'blocked_by': str, 'reason': str,
    'gates': [...]}`` where ``gates`` is the ordered list of gates passed (the
    full five on GO, the partial prefix on BLOCK). ``force=True`` bypasses all.
    """
    if force:
        return {'verdict': 'GO', 'blocked_by': '', 'reason': 'forced', 'gates': list(_GATE_ORDER)}
    passed: List[str] = []
    # 1. cascade — abort the spawn-storm before it starts.
    comps = list(recent_completions or [])
    if len(comps) >= CASCADE_MIN_SAMPLE:
        failed = sum(1 for c in comps if not c.get('success', True))
        rate = failed / len(comps)
        if rate > CASCADE_FAILURE_THRESHOLD:
            return _block('cascade', 'cascade failure rate %.2f exceeds %.2f'
                          % (rate, CASCADE_FAILURE_THRESHOLD), passed)
    passed.append('cascade')
    # 2. memory floor.
    if available_memory_mb is not None and available_memory_mb < MEMORY_MIN_AVAILABLE_MB:
        return _block('memory', 'available memory %d MB below floor %d MB'
                      % (available_memory_mb, MEMORY_MIN_AVAILABLE_MB), passed)
    passed.append('memory')
    # 3. capacity cap.
    if active_workers >= max_workers:
        return _block('capacity', 'active workers %d at/above cap %d'
                      % (active_workers, max_workers), passed)
    passed.append('capacity')
    # 4. dedup — same target running or recently completed.
    if task_target is not None:
        if task_target in set(running_targets or ()):
            return _block('dedup', 'target %r already running' % (task_target,), passed)
        completed_at = (recent_target_completions or {}).get(task_target)
        if completed_at is not None and (now - completed_at) < dedup_window_s:
            return _block('dedup', 'target %r completed %.0fs ago (<%ds)'
                          % (task_target, now - completed_at, dedup_window_s), passed)
    passed.append('dedup')
    # 5. cooldown — per-type exponential backoff.
    cd = _cooldown_seconds(consecutive_failures)
    if cd > 0 and last_failure_at is not None and (now - last_failure_at) < cd:
        return _block('cooldown', 'type %r cooling down %ds (%.0fs elapsed)'
                      % (worker_type, cd, now - last_failure_at), passed)
    passed.append('cooldown')
    return _go()
```

DISPATCH DIRECTIVE — this is a NEW single-file module. Emit it as a single whole-file deliverable for ngv2/spawn_preflight.py reproducing the Deliverables content BYTE-FOR-BYTE (it already imports everything it needs from the stdlib; no ngv2 sibling imports). Do NOT emit a `__JANUSMASK_PATCHES__` list — this is a new file, not a symbol patch. meta_task_type=io_adapter (external NGv2 target; the diff-fuzzer cannot resolve external imports, so use the fuzzer-bypassed, smoke-gated io_adapter meta-type). Use this task_id VERBATIM: `ngv2-spawn-preflight`. priority: high. dependencies: []. files_touched: `["ngv2/spawn_preflight.py"]` ONLY. verification_command (CWD-relative, NO `cd`): `.venv/bin/python -m pytest tests/test_spawn_preflight_wired.py -q`. The committed oracle tests/test_spawn_preflight_wired.py is the authoritative acceptance contract; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from this brief's committed oracle (plan descriptors referencing the committed oracle — this does NOT authorize authoring tests), e.g. `test_clean_go` and `test_cascade_blocks_on_high_failure` (also good: `test_capacity_cap_blocks`, `test_cooldown_seconds_caps`).
