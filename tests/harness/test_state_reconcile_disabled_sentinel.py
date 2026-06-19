"""RED oracle: the ``state_reconcile.disabled`` sentinel forces ARM 2 OFF.

Pins the exact observable contract for a runtime operator-control override of
the state reconciler: a ``state/control/autowork/state_reconcile.disabled``
sentinel that forces ``_reclaim_zombie_briefs``'s ``_state_reconcile_on`` gate
OFF regardless of the ``autowork.state_reconcile`` config flag.

  * Helper ``_state_reconcile_disabled(state_dir)`` returns True iff the
    sentinel exists, False otherwise (Case a).
  * Sentinel present AND config flag true: ARM 2 is a no-op identical to the
    flag-OFF behaviour -- the stale brief is KEPT at root and the
    ``sha_staleness_sweep.marker`` is NOT written (Case b).
  * Sentinel absent AND config flag true: behaviour UNCHANGED -- the stale
    brief is archived and the marker is written (Case c, regression guard).

RED on HEAD: the ``_state_reconcile_disabled`` symbol does not yet exist, so
the module-level import raises ImportError and Cases (a)/(b) fail; all cases
turn GREEN once task state-reconcile-disable-impl lands.

The gate reads ``state_dir.parent / 'harness' / 'config.yaml'``; with
``state_dir = tmp_path / 'state'`` that resolves to
``tmp_path / 'harness' / 'config.yaml'``.

Scope: unit-level oracle mirroring tests/harness/test_state_reconcile_flag_gate.py.
We deliberately do NOT run an end-to-end factory or daemon loop and we do NOT
edit any source.
"""
import json
import pytest
from harness.autowork_daemon import _reclaim_zombie_briefs, _state_reconcile_disabled
WRONG_SHA = '0' * 64
BRIEF_BODY = '# zztest brief\n\nThis is a PLANNED_STALE brief whose plan stamps a deliberately wrong\nsource_brief_sha256, so the sha-only staleness check (ARM 2) sees a mismatch.\n'

def _build_planned_stale(tmp_path, flag=True):
    """Build a hermetic PLANNED_STALE state tree and return (repo_root, state_dir).

    Mirrors tests/harness/test_state_reconcile_flag_gate.py: repo_root =
    tmp_path, state_dir = tmp_path/'state' with control/autowork and
    tasks/processed. Writes brief_hooks_zztest.md + plan_hooks_zztest.json with
    a wrong source_brief_sha256 (64 zeros) and a single un-landed task id. No
    impl_progress.jsonl is written, so the task id is NOT accepted (the
    landed-aware guard does not spare the brief). When ``flag`` is True a
    config.yaml is written at tmp_path/'harness'/'config.yaml' with
    ``autowork:\\n  state_reconcile: true\\n``.
    """
    repo_root = tmp_path
    state_dir = tmp_path / 'state'
    (state_dir / 'control' / 'autowork').mkdir(parents=True, exist_ok=True)
    (state_dir / 'tasks' / 'processed').mkdir(parents=True, exist_ok=True)
    brief = repo_root / 'brief_hooks_zztest.md'
    brief.write_text(BRIEF_BODY, encoding='utf-8')
    plan = repo_root / 'plan_hooks_zztest.json'
    plan.write_text(json.dumps({'source_brief_sha256': WRONG_SHA, 'tasks': [{'task_id': 'zztest-unlanded'}]}), encoding='utf-8')
    if flag:
        harness_dir = tmp_path / 'harness'
        harness_dir.mkdir(parents=True, exist_ok=True)
        (harness_dir / 'config.yaml').write_text('autowork:\n  state_reconcile: true\n', encoding='utf-8')
    return (repo_root, state_dir)

def _marker_path(state_dir):
    return state_dir / 'control' / 'autowork' / 'sha_staleness_sweep.marker'

def _sentinel_path(state_dir):
    return state_dir / 'control' / 'autowork' / 'state_reconcile.disabled'

def test_helper_true_when_sentinel_present(tmp_path):
    """(a) Helper returns True with the sentinel present, False without it."""
    repo_root, state_dir = _build_planned_stale(tmp_path, flag=True)
    assert _sentinel_path(state_dir).exists() is False
    assert _state_reconcile_disabled(state_dir) is False
    _sentinel_path(state_dir).write_text('1', encoding='utf-8')
    assert _state_reconcile_disabled(state_dir) is True

def test_sentinel_forces_arm2_noop_despite_flag_true(tmp_path):
    """(b) Sentinel present + flag true => ARM 2 no-op (RED on HEAD).

    The brief must be KEPT at root and the throttle marker must NOT be written,
    identical to flag-OFF behaviour, even though the config flag is true.
    """
    repo_root, state_dir = _build_planned_stale(tmp_path, flag=True)
    _sentinel_path(state_dir).write_text('1', encoding='utf-8')
    _reclaim_zombie_briefs(repo_root, state_dir, running=None)
    assert (repo_root / 'brief_hooks_zztest.md').exists() is True
    assert _marker_path(state_dir).exists() is False

def test_flag_true_no_sentinel_arm2_still_runs(tmp_path):
    """(c) Flag true + no sentinel => normal reconciliation (regression guard).

    The override must not break the happy path: the stale brief is archived and
    the marker is written.
    """
    repo_root, state_dir = _build_planned_stale(tmp_path, flag=True)
    assert _sentinel_path(state_dir).exists() is False
    _reclaim_zombie_briefs(repo_root, state_dir, running=None)
    assert _marker_path(state_dir).exists() is True
    assert (repo_root / 'brief_hooks_zztest.md').exists() is False

def test_helper_callable_and_returns_bool(tmp_path):
    """Witness: the helper is importable, callable, and bool-typed."""
    assert callable(_state_reconcile_disabled)
    _repo_root, state_dir = _build_planned_stale(tmp_path, flag=True)
    assert isinstance(_state_reconcile_disabled(state_dir), bool)

def test_builder_writes_flag_true_config_and_stale_pair(tmp_path):
    """The mirrored builder stamps a wrong sha, one un-landed task id, flag=true."""
    repo_root, state_dir = _build_planned_stale(tmp_path, flag=True)
    assert (repo_root / 'brief_hooks_zztest.md').exists() is True
    plan_data = json.loads((repo_root / 'plan_hooks_zztest.json').read_text(encoding='utf-8'))
    assert plan_data['source_brief_sha256'] == WRONG_SHA
    assert plan_data['tasks'] == [{'task_id': 'zztest-unlanded'}]
    assert (state_dir / 'impl_progress.jsonl').exists() is False
    assert (tmp_path / 'harness' / 'config.yaml').read_text(encoding='utf-8') == 'autowork:\n  state_reconcile: true\n'