"""Adversarial regression bar for R-PROMOTE-7.

Bug: ``harness/mcp_server.py`` still has bare ``state/tasks/current_task.json``
fallback sites at :296 (cmd_get_task) and :369 (cmd_submit_code), missed by
the AW10c six-site patch landed on ``harness/orchestrator.py`` in session
#19 (commit b3a3dca).

Fix shape (this brief): route the fallback through
``harness.task_paths.current_task_spec_path(state_dir, task_id or 'default')``
so the on-disk path becomes ``state/tasks/current_task_<task_id>.json`` and
the bare ``current_task.json`` literal disappears from the module source.

The three xfail markers in this file are dropped in a follow-up META commit
once the fix lands.
"""
from __future__ import annotations

import json
import pathlib

import pytest


@pytest.fixture
def state_dir_with_default_spec(tmp_path: pathlib.Path) -> pathlib.Path:
    """A state dir with a per-task spec at ``current_task_default.json`` and
    no bare ``current_task.json`` — mirrors what test fixtures will write
    once the per-task contract is the only path through the fallback.
    """
    state_dir = tmp_path / "state"
    tasks_dir = state_dir / "tasks"
    tasks_dir.mkdir(parents=True)
    spec = {
        "task_id": "default",
        "specification": "RP7 sentinel spec body.",
        "files_touched": ["harness/foo.py"],
        "constraints": {"deterministic": False},
        "synthesis_target_type": "harness_module",
    }
    (tasks_dir / "current_task_default.json").write_text(
        json.dumps(spec), encoding="utf-8"
    )
    return state_dir


def test_cmd_get_task_uses_per_task_path_when_env_unset(
    state_dir_with_default_spec: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When JANUSMASK_TASK_ID is unset and the per-task glob misses, the
    fallback must resolve to ``current_task_<default>.json`` and return the
    spec rather than the (non-existent) bare ``current_task.json`` file.

    Pre-fix: fallback reads ``state/tasks/current_task.json`` (no such file)
    and returns ``{'error': 'No current task found.', 'code': 'no_task'}``.
    Post-fix: fallback routes through ``task_paths.current_task_spec_path``
    with the ``'default'`` sentinel and returns the spec dict.
    """
    from harness import mcp_server

    monkeypatch.delenv("JANUSMASK_TASK_ID", raising=False)

    server = mcp_server.JanusMaskServer(agent_id="claude", state_dir=state_dir_with_default_spec)
    result = server.cmd_get_task({})

    assert isinstance(result, dict), f"expected dict result, got {type(result).__name__}"
    assert result.get("code") != "no_task", (
        f"cmd_get_task fell back to no_task instead of resolving the per-task "
        f"spec at current_task_default.json; result={result!r}"
    )
    assert result.get("task_id") == "default", (
        f"expected task_id='default' from per-task spec; got {result!r}"
    )
    assert "RP7 sentinel spec body" in (result.get("specification") or ""), (
        f"per-task spec body not returned; got {result!r}"
    )


def test_cmd_submit_code_reads_constraints_from_per_task_default(
    state_dir_with_default_spec: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cmd_submit_code's constraint lookup must hit the per-task spec
    (allow_nondet=True from constraints.deterministic=False) when the env
    var is unset and the per-task glob misses.

    Pre-fix: reads bare ``current_task.json`` (missing), constraint lookup
    catches FileNotFoundError silently → allow_nondet stays False → code
    with time.time() is rejected as nondeterministic.
    Post-fix: reads current_task_default.json → allow_nondet=True → code
    accepted (or at least: not rejected for nondeterminism).
    """
    from harness import mcp_server

    monkeypatch.delenv("JANUSMASK_TASK_ID", raising=False)

    server = mcp_server.JanusMaskServer(agent_id="claude", state_dir=state_dir_with_default_spec)
    server.task_read = True  # bypass inbox gate for this isolated submission test

    # Nondeterministic code: time.time() should be tolerated when
    # allow_nondet is True (constraints.deterministic=False in fixture).
    nondet_code = "import time\n\ndef stamp():\n    return time.time()\n"
    result = server.cmd_submit_code({"code": nondet_code})

    assert isinstance(result, dict), f"expected dict result, got {type(result).__name__}"
    # Pre-fix: constraint lookup misses → allow_nondet=False → AST rejects
    # time.time(). Post-fix: constraint lookup hits → allow_nondet=True →
    # submission proceeds.
    violations = result.get("violations") or []
    nondet_violations = [
        v for v in violations
        if isinstance(v, dict) and "nondeterminism" in str(v.get("rule", "")).lower()
    ]
    assert not nondet_violations, (
        f"cmd_submit_code rejected nondet code despite constraints.deterministic=False "
        f"in per-task spec — fallback is reading the wrong file. Violations: {violations!r}"
    )


def test_mcp_server_source_no_bare_current_task_json() -> None:
    """Source-grep regression bar: ``harness/mcp_server.py`` MUST NOT
    contain the bare string literal ``'current_task.json'`` (single- or
    double-quoted) after R-PROMOTE-7 lands. All task-spec resolution must
    route through the per-task glob (``*{task_id}.json.processing``) or the
    ``task_paths.current_task_spec_path`` helper.
    """
    src = (
        pathlib.Path(__file__).resolve().parents[2]
        / "harness"
        / "mcp_server.py"
    ).read_text(encoding="utf-8")
    assert '"current_task.json"' not in src, (
        "bare double-quoted \"current_task.json\" string found in harness/mcp_server.py — "
        "R-PROMOTE-7 fix must route the fallback through task_paths.current_task_spec_path"
    )
    assert "'current_task.json'" not in src, (
        "bare single-quoted 'current_task.json' string found in harness/mcp_server.py — "
        "R-PROMOTE-7 fix must route the fallback through task_paths.current_task_spec_path"
    )
    # Sanity: ensure the per-task contract IS referenced.
    assert (
        "task_paths" in src
        or "current_task_spec_path" in src
        or "current_task_" in src
    ), (
        "harness/mcp_server.py lost its per-task-spec routing entirely — "
        "expected task_paths.current_task_spec_path or current_task_<id> pattern"
    )
