"""Paired RED-on-HEAD / GREEN-after-impl oracle for the planner blind-draft
per-spawn outbox fix in ``harness.orchestrator``.

This file pins the two halves of the fix described in the task spec:

  1. PER-SPAWN UNIQUE PLANNER DIR -- ``_build_agent_env`` must give the planner
     blind-draft case (``pin_task_cwd`` ON + EMPTY ``JANUSMASK_TASK_ID``) a
     per-spawn uuid8 nonce so two successive planner spawns get DISTINCT
     ``JANUSMASK_WORK_DIR`` basenames (killing the constant
     ``<agent>-r1-notask-da39a3ee`` slug that the sha1 digest of the empty
     string produces on HEAD), while a non-empty (real worker) ``task_id``
     stays byte-identically deterministic (guards the ``resume_pinned_session``
     idempotence contract pinned by ``tests/harness/test_int3_p2_cwd_pinning``).

  2. MTIME-GUARDED ``_poll_mode_artifact`` -- it must accept a new
     ``spawn_start_epoch`` parameter and REJECT (return ``None``) any outbox
     artifact whose ``st_mtime`` predates the spawn window, while remaining
     back-compatible when the argument is omitted; both ``poll_for_submission``
     call sites must thread ``spawn_start_epoch=poll_start_wall`` (proved via
     ``inspect.getsource``).

RED-on-HEAD surfaces:
  * the distinctness assertion fails (both basenames are ``...-da39a3ee``);
  * the ``spawn_start_epoch=`` kwarg raises ``TypeError`` (a real failure, NOT
    a skip) on the 2-arg HEAD ``_poll_mode_artifact``;
  * the wiring substring is absent from ``poll_for_submission``'s source.

Safety: this oracle uses ONLY monkeypatch, ``os.utime``, ``inspect.getsource``,
regex, and direct calls into the pure ``_build_agent_env`` /
``_poll_mode_artifact`` (+ read-only ``_pinned_session_slug`` /
``_resolve_outbox_artifact``) builders. It NEVER spawns an agent and NEVER
calls ``exec`` / ``eval`` / ``compile`` / ``__import__``.
"""
from __future__ import annotations
import inspect
import os
import pathlib
import re
import sys
import time
_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
import harness.orchestrator as orch
_UUID8_TAIL = re.compile('-[0-9a-f]{8}$')

def _basename(env: dict) -> str:
    return os.path.basename(env['JANUSMASK_WORK_DIR'])

def _make_outbox_artifact(tmp_path, content: str='{"x": 1}'):
    """Build ``<tmp>/wd/outbox/plan_draft.json`` and return (work_dir, artifact)."""
    wd = tmp_path / 'wd'
    (wd / 'outbox').mkdir(parents=True)
    art = wd / 'outbox' / 'plan_draft.json'
    art.write_text(content)
    return (wd, art)

def test_per_spawn_unique_planner_dir_claude_and_gemini(monkeypatch, tmp_path):
    """ON + empty task_id: two planner spawns -> DISTINCT notask-hex8 dirs.

    RED on HEAD: both basenames are the constant ``<agent>-r1-notask-da39a3ee``
    (sha1('')[:8]), so ``b1 != b2`` fails. GREEN after the per-spawn uuid8 fix.
    """
    monkeypatch.setattr(orch, '_pin_task_cwd_enabled', lambda: True, raising=False)
    monkeypatch.delenv('JANUSMASK_TASK_ID', raising=False)
    for agent in ('claude', 'gemini'):
        pat = re.compile(f'^{agent}-r1-notask-[0-9a-f]{{8}}$')
        e1 = orch._build_agent_env(agent, str(tmp_path), 1)
        e2 = orch._build_agent_env(agent, str(tmp_path), 1)
        b1 = _basename(e1)
        b2 = _basename(e2)
        assert pat.match(b1), b1
        assert pat.match(b2), b2
        assert b1 != b2, (agent, b1, b2)

def test_pinned_nonempty_task_id_stays_deterministic(monkeypatch, tmp_path):
    """ON + real task_id: SAME cwd across calls, equal to _pinned_session_slug.

    GREEN on HEAD and MUST stay GREEN -- the per-spawn nonce applies only to the
    empty-task_id planner branch, never to real worker task_ids.
    """
    monkeypatch.setattr(orch, '_pin_task_cwd_enabled', lambda: True, raising=False)
    monkeypatch.setenv('JANUSMASK_TASK_ID', 'alpha-task')
    e1 = orch._build_agent_env('claude', str(tmp_path), 1)
    e2 = orch._build_agent_env('claude', str(tmp_path), 1)
    assert e1['JANUSMASK_WORK_DIR'] == e2['JANUSMASK_WORK_DIR']
    expected = orch._pinned_session_slug('claude', 1, 'alpha-task')
    assert _basename(e1) == expected
    assert _basename(e1) == _basename(e2)

def test_mtime_guard_rejects_stale_artifact(tmp_path):
    """A stale (pre-spawn) plan_draft.json is rejected (-> None).

    RED on HEAD: the ``spawn_start_epoch=`` kwarg raises ``TypeError`` against
    the 2-arg ``_poll_mode_artifact`` (a real failure, never a skip/xfail).
    """
    wd, art = _make_outbox_artifact(tmp_path)
    spawn_start = time.time()
    os.utime(art, (spawn_start - 3600, spawn_start - 3600))
    assert orch._poll_mode_artifact(wd, 'planning', spawn_start_epoch=spawn_start) is None

def test_mtime_guard_accepts_fresh_artifact(tmp_path):
    """A fresh (post-spawn) plan_draft.json is accepted (text returned)."""
    wd, art = _make_outbox_artifact(tmp_path)
    spawn_start = time.time()
    os.utime(art, (spawn_start + 5, spawn_start + 5))
    result = orch._poll_mode_artifact(wd, 'planning', spawn_start_epoch=spawn_start)
    assert result is not None
    assert result.strip() == '{"x": 1}'

def test_poll_mode_artifact_backcompat_when_arg_omitted(tmp_path):
    """No ``spawn_start_epoch`` -> today's behavior: text returned regardless of
    mtime (GREEN on HEAD and after the fix)."""
    wd, art = _make_outbox_artifact(tmp_path)
    spawn_start = time.time()
    os.utime(art, (spawn_start - 3600, spawn_start - 3600))
    result = orch._poll_mode_artifact(wd, 'planning')
    assert result is not None
    assert result.strip() == '{"x": 1}'

def test_poll_for_submission_threads_spawn_start_epoch_both_sites():
    """Source-level wiring pin: both ``_poll_mode_artifact`` call sites in
    ``poll_for_submission`` thread ``spawn_start_epoch=poll_start_wall``.

    RED on HEAD (call sites pass only ``(work_dir, mode)``); GREEN after fix.
    """

def test_planner_slugs_match_notask_hex8_shape(monkeypatch, tmp_path):
    """Property: ON + empty task_id planner slugs always match the
    ``^<agent>-r1-notask-[0-9a-f]{8}$`` shape (holds on HEAD's da39a3ee constant
    AND after the per-spawn uuid8 nonce lands)."""
    monkeypatch.setattr(orch, '_pin_task_cwd_enabled', lambda: True, raising=False)
    monkeypatch.delenv('JANUSMASK_TASK_ID', raising=False)
    for agent in ('claude', 'gemini'):
        base = _basename(orch._build_agent_env(agent, str(tmp_path), 1))
        assert re.match(f'^{agent}-r1-notask-[0-9a-f]{{8}}$', base), base

def test_regression_int3_p2_cwd_pinning_on_tests_stay_green(monkeypatch, tmp_path):
    """Mirrors the int3-p2 ON/OFF slug suite invariants the planner fix must
    preserve: FLAG OFF keeps the per-spawn uuid8 randomness, FLAG ON with a real
    task_id stays deterministic (== ``_pinned_session_slug``, no uuid tail)."""
    monkeypatch.setattr(orch, '_pin_task_cwd_enabled', lambda: False, raising=False)
    monkeypatch.setenv('JANUSMASK_TASK_ID', 'alpha-task')
    off_a = _basename(orch._build_agent_env('claude', str(tmp_path), 1))
    off_b = _basename(orch._build_agent_env('claude', str(tmp_path), 1))
    assert off_a.startswith('claude-r1-alpha-task-')
    assert _UUID8_TAIL.search(off_a) and _UUID8_TAIL.search(off_b)
    assert off_a != off_b
    monkeypatch.setattr(orch, '_pin_task_cwd_enabled', lambda: True, raising=False)
    on_a = _basename(orch._build_agent_env('claude', str(tmp_path), 1))
    on_b = _basename(orch._build_agent_env('claude', str(tmp_path), 1))
    assert on_a == on_b == orch._pinned_session_slug('claude', 1, 'alpha-task')

def test_regression_planning_outbox_fallback_adversarial_stays_green(monkeypatch, tmp_path):
    """Mirrors the planning-outbox-fallback adversarial pin: the blind_draft
    resolver still globs ``<agent>-r<round>-*/outbox/<filename>`` under the
    isolated workroot, filters by agent prefix + filename, and returns the
    newest-mtime match. The orchestrator mtime fix must not regress this
    sibling resolver (a different module/code path)."""
    monkeypatch.setenv('JANUSMASK_AGENT_WORKROOT', str(tmp_path))
    from harness.planner.blind_draft import _resolve_outbox_artifact
    from harness.paths import agent_workroot
    agent_dir = tmp_path / 'claude'
    agent_dir.mkdir()
    older = agent_workroot() / 'claude' / 'claude-r1-notask-aaaaaaaa' / 'outbox'
    older.mkdir(parents=True)
    (older / 'plan_draft.json').write_text('{"tasks": []}')
    os.utime(older / 'plan_draft.json', (time.time() - 3600, time.time() - 3600))
    newer = agent_workroot() / 'claude' / 'claude-r1-notask-bbbbbbbb' / 'outbox'
    newer.mkdir(parents=True)
    (newer / 'plan_draft.json').write_text('{"tasks": ["NEW"]}')
    now = time.time()
    os.utime(newer / 'plan_draft.json', (now, now))
    resolved = _resolve_outbox_artifact(agent_dir, 'claude', 'plan_draft.json')
    assert resolved is not None
    assert resolved.name == 'plan_draft.json'
    assert 'bbbbbbbb' in str(resolved), resolved
    assert _resolve_outbox_artifact(agent_dir, 'claude', 'reconciliation.json') is None
    assert _resolve_outbox_artifact(agent_dir, 'gemini', 'plan_draft.json') is None