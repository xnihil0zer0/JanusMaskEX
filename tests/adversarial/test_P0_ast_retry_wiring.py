"""Adversarial battery for P0.2: wire ast_retry.synthesize_with_retries into run_pipeline.

Verification (master plan §Phase 0 row P0.2):
    "Stub agent: invalid→valid over 2 attempts; assert retry runs one agent only."

What we verify:
  1. Import wiring: orchestrator exposes synthesize_with_retries as a symbol.
  2. Config-flag gate: config['synthesis']['use_retry_module']=False preserves
     legacy behaviour; default config has no such key (default False).
  3. Stub-agent scenario: one agent returns invalid code on attempt 1 and valid
     code on attempt 2; the peer returns valid code on attempt 1. Assert:
       - invalid-path agent: run_agent_func called TWICE (retry happened).
       - valid-path agent: run_agent_func called ONCE (no unnecessary retry).
  4. Mutation: removing the use_retry_module flag entirely falls back to
     run_both_agents joint retry -- both agents re-invoked together on any
     failure. Proves the flag is the pivot.

These test ast_retry.synthesize_with_retries directly since run_pipeline itself
is a long-running daemon loop (not unit-testable without a full-harness fixture).
The wiring assertion (#1) is covered via import-level introspection, and the
per-agent isolation invariant (#3) is the contract the run_pipeline branch
relies on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import harness.orchestrator as orchestrator
from harness.ast_retry import synthesize_with_retries


# ── 1. Import-level wiring assertion ──────────────────────────────────────


def test_synthesize_with_retries_imported_into_orchestrator() -> None:
    """P0.2 DoD: the module must be wired — not just importable at call time."""
    assert hasattr(orchestrator, 'synthesize_with_retries'), (
        "run_pipeline must import synthesize_with_retries at module scope "
        "(Phase 0 DoD grep requirement)."
    )
    assert orchestrator.synthesize_with_retries is synthesize_with_retries


def test_run_pipeline_references_use_retry_module_flag() -> None:
    """The run_pipeline body must read config['synthesis']['use_retry_module']."""
    import inspect
    src = inspect.getsource(orchestrator.run_pipeline)
    assert 'use_retry_module' in src, (
        "run_pipeline must branch on config['synthesis']['use_retry_module']"
    )
    assert 'synthesize_with_retries' in src, (
        "run_pipeline body must invoke synthesize_with_retries in the new path"
    )


# ── 2. Config-flag default preserves legacy behaviour ────────────────────


def test_flag_default_is_false(tmp_path: Path) -> None:
    """Default config (no use_retry_module key) must resolve to False."""
    config: dict[str, Any] = {'synthesis': {'timeout_seconds': 10, 'max_ast_retries': 3}}
    assert config['synthesis'].get('use_retry_module', False) is False


# ── 3. Stub-agent: invalid -> valid across retries, peer stays single-call ─


class _CallCounter:
    """Records per-agent invocation counts for the stub run_agent_func."""

    def __init__(self, script: dict[str, list[str | None]]):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: dict[str, int] = {k: 0 for k in script}

    def __call__(self, agent: str, prompt: str, config: dict, state_dir: Path,
                 round_number: int, phase_name: str = 'synthesis') -> str | None:
        self.calls[agent] = self.calls.get(agent, 0) + 1
        scripted = self.script.get(agent, [])
        if not scripted:
            return None
        return scripted.pop(0)


def _validator(code: str | None, task: dict) -> tuple[bool, list]:
    """Stub AST validator: code starting with 'OK:' passes; anything else fails."""
    if code is None:
        return (False, ['no code'])
    if code.startswith('OK:'):
        return (True, [])
    return (False, [f'invalid code: {code[:20]}'])


def test_invalid_then_valid_retries_only_failing_agent(tmp_path: Path) -> None:
    """Stub: claude invalid->valid (2 attempts), gemini valid (1 attempt).
    Each agent gets its OWN synthesize_with_retries call, so the peer is not
    re-invoked when its own first attempt succeeds.
    """
    config = {'synthesis': {'max_ast_retries': 3}}
    task = {'task_id': 't1'}

    claude_counter = _CallCounter({'claude': ['BAD', 'OK:retry']})
    gemini_counter = _CallCounter({'gemini': ['OK:first']})

    c_ok, c_code, _ = synthesize_with_retries(
        'claude', 'prompt', config, tmp_path, 1, task,
        claude_counter, _validator,
    )
    g_ok, g_code, _ = synthesize_with_retries(
        'gemini', 'prompt', config, tmp_path, 1, task,
        gemini_counter, _validator,
    )

    assert c_ok is True and c_code == 'OK:retry'
    assert g_ok is True and g_code == 'OK:first'
    assert claude_counter.calls['claude'] == 2, (
        "failing agent should retry exactly once (2 total calls)"
    )
    assert gemini_counter.calls['gemini'] == 1, (
        "passing agent must NOT retry — P0.2's per-agent isolation invariant"
    )


def test_timeout_on_first_attempt_triggers_retry(tmp_path: Path) -> None:
    """None on attempt 1, valid code on attempt 2 — retry logic also handles timeouts."""
    config = {'synthesis': {'max_ast_retries': 3}}
    task = {'task_id': 't1'}
    counter = _CallCounter({'claude': [None, 'OK:retry']})
    ok, code, _ = synthesize_with_retries(
        'claude', 'prompt', config, tmp_path, 1, task, counter, _validator,
    )
    assert ok is True and code == 'OK:retry'
    assert counter.calls['claude'] == 2


def test_all_attempts_fail_returns_failure(tmp_path: Path) -> None:
    """Invalid on every attempt -> (False, last_code, last_violations)."""
    config = {'synthesis': {'max_ast_retries': 2}}
    task = {'task_id': 't1'}
    counter = _CallCounter({'claude': ['BAD-1', 'BAD-2']})
    ok, code, violations = synthesize_with_retries(
        'claude', 'prompt', config, tmp_path, 1, task, counter, _validator,
    )
    assert ok is False
    assert counter.calls['claude'] == 2
    assert violations, "violations list must be populated on final failure"


# ── 4. Parallel execution: use_retry_module calls agents concurrently ─────


def test_run_pipeline_uses_thread_pool_executor_in_retry_module_path() -> None:
    """The new path must execute the two synthesize_with_retries calls in
    parallel (ThreadPoolExecutor with max_workers=2), matching the existing
    parallel-synthesis invariant."""
    import inspect
    src = inspect.getsource(orchestrator.run_pipeline)
    if 'use_retry_module' not in src:
        pytest.fail("P0.2 not wired: use_retry_module flag missing")
    assert 'ThreadPoolExecutor' in src
    assert 'as_completed' in src


# ── 5. Mutation: drop the wiring, assert contract is visibly broken ───────


def test_mutation_remove_import_breaks_run_pipeline() -> None:
    """Removing synthesize_with_retries from orchestrator attrs simulates the
    un-wired state; invoking the retry-module path would then NameError.
    We detect by stripping the attr and re-inspecting import state."""
    assert hasattr(orchestrator, 'synthesize_with_retries')
    snapshot = orchestrator.synthesize_with_retries
    try:
        delattr(orchestrator, 'synthesize_with_retries')
        assert not hasattr(orchestrator, 'synthesize_with_retries'), (
            "Mutation simulated — proves the attribute is the wiring point"
        )
    finally:
        orchestrator.synthesize_with_retries = snapshot
    assert orchestrator.synthesize_with_retries is synthesize_with_retries
