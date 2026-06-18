"""RED oracle for the autowork.state_reconcile flag gate on ARM 2.

Drives ``harness.autowork_daemon._reclaim_zombie_briefs`` directly against a
hermetic ``tmp_path`` state tree and asserts the DESIRED post-fix contract:

  * With ``autowork.state_reconcile`` OFF or absent, the sha-staleness
    enforcement arm (ARM 2) must be a NO-OP: no brief is archived and no
    ``sha_staleness_sweep.marker`` is written (Case A / Case B).
  * With the flag explicitly ``true`` the arm runs: the stale brief is archived
    and the marker is written (Case C).

RED on HEAD because ARM 2 currently runs UNCONDITIONALLY (the function does not
consult the flag), so Case A / Case B fail on HEAD and turn GREEN only once the
gate is added.

The gate reads ``state_dir.parent / 'harness' / 'config.yaml'``; with
``state_dir = tmp_path / 'state'`` that resolves to
``tmp_path / 'harness' / 'config.yaml'``.

Scope: unit-level oracle. We deliberately do NOT run an end-to-end factory or
daemon loop (integration-excused) and we do NOT edit any source.
"""
import json
import pytest
from harness.autowork_daemon import _reclaim_zombie_briefs
WRONG_SHA = '0' * 64
BRIEF_BODY = '# zztest brief\n\nThis is a PLANNED_STALE brief whose plan stamps a deliberately wrong\nsource_brief_sha256, so the sha-only staleness check (ARM 2) sees a mismatch.\n'

def _config_text(value: bool) -> str:
    """Literal two-space-indented autowork.state_reconcile flag block."""
    if value:
        return 'autowork:\n  state_reconcile: true\n'
    return 'autowork:\n  state_reconcile: false\n'

def _build_planned_stale(tmp_path, flag=None):
    """Build a hermetic PLANNED_STALE state tree and return (repo_root, state_dir).

    repo_root = tmp_path, state_dir = tmp_path/'state' with control/autowork and
    tasks/processed. Writes brief_hooks_zztest.md + plan_hooks_zztest.json with a
    wrong source_brief_sha256 and a single unlanded task id. No impl_progress.jsonl
    is written, so the task id is NOT accepted (the landed-aware guard does not
    spare the brief). When ``flag`` is not None a config.yaml is written at
    tmp_path/'harness'/'config.yaml' with the state_reconcile flag.
    """
    repo_root = tmp_path
    state_dir = tmp_path / 'state'
    (state_dir / 'control' / 'autowork').mkdir(parents=True, exist_ok=True)
    (state_dir / 'tasks' / 'processed').mkdir(parents=True, exist_ok=True)
    brief = repo_root / 'brief_hooks_zztest.md'
    brief.write_text(BRIEF_BODY, encoding='utf-8')
    plan = repo_root / 'plan_hooks_zztest.json'
    plan.write_text(json.dumps({'source_brief_sha256': WRONG_SHA, 'tasks': [{'task_id': 'zztest-unlanded'}]}), encoding='utf-8')
    if flag is not None:
        harness_dir = tmp_path / 'harness'
        harness_dir.mkdir(parents=True, exist_ok=True)
        (harness_dir / 'config.yaml').write_text(_config_text(flag), encoding='utf-8')
    return (repo_root, state_dir)

def _marker_path(state_dir):
    return state_dir / 'control' / 'autowork' / 'sha_staleness_sweep.marker'

def test_case_a_flag_absent_arm2_noop_red_on_head(tmp_path):
    repo_root, state_dir = _build_planned_stale(tmp_path, flag=None)
    _reclaim_zombie_briefs(repo_root, state_dir, running=None)
    assert (repo_root / 'brief_hooks_zztest.md').exists() is True
    assert _marker_path(state_dir).exists() is False

def test_case_b_flag_false_arm2_noop(tmp_path):
    repo_root, state_dir = _build_planned_stale(tmp_path, flag=False)
    _reclaim_zombie_briefs(repo_root, state_dir, running=None)
    assert (repo_root / 'brief_hooks_zztest.md').exists() is True
    assert _marker_path(state_dir).exists() is False

def test_case_c_flag_true_arm2_runs_marker_written(tmp_path):
    repo_root, state_dir = _build_planned_stale(tmp_path, flag=True)
    _reclaim_zombie_briefs(repo_root, state_dir, running=None)
    assert _marker_path(state_dir).exists() is True
    assert (repo_root / 'brief_hooks_zztest.md').exists() is False

def test_import_and_direct_call_non_vacuity_witness(tmp_path):
    assert callable(_reclaim_zombie_briefs)
    repo_root, state_dir = _build_planned_stale(tmp_path, flag=True)
    result = _reclaim_zombie_briefs(repo_root, state_dir, running=None)
    assert isinstance(result, dict)
    assert set(result.keys()) >= {'reclaimed', 'slugs'}
    assert _marker_path(state_dir).exists() is True

def test_empty_state_tree_returns_wellformed_dict(tmp_path):
    repo_root = tmp_path
    state_dir = tmp_path / 'state'
    (state_dir / 'control' / 'autowork').mkdir(parents=True, exist_ok=True)
    (state_dir / 'tasks' / 'processed').mkdir(parents=True, exist_ok=True)
    result = _reclaim_zombie_briefs(repo_root, state_dir, running=None)
    assert isinstance(result, dict)
    assert isinstance(result.get('reclaimed'), int)
    assert isinstance(result.get('slugs'), list)
    assert result == {'reclaimed': 0, 'slugs': []}

def test_helper_builds_planned_stale_pair(tmp_path):
    repo_root, state_dir = _build_planned_stale(tmp_path, flag=None)
    brief = repo_root / 'brief_hooks_zztest.md'
    plan = repo_root / 'plan_hooks_zztest.json'
    assert brief.exists() is True
    assert plan.exists() is True
    plan_data = json.loads(plan.read_text(encoding='utf-8'))
    assert plan_data['source_brief_sha256'] == WRONG_SHA
    assert plan_data['tasks'] == [{'task_id': 'zztest-unlanded'}]
    assert (state_dir / 'impl_progress.jsonl').exists() is False

def test_arm1_still_effective_flag_off_return_contract_intact(tmp_path):
    repo_root, state_dir = _build_planned_stale(tmp_path, flag=False)
    result = _reclaim_zombie_briefs(repo_root, state_dir, running=None)
    assert result == {'reclaimed': 0, 'slugs': []}

def test_return_shape_and_fail_closed_unchanged_flag_off(tmp_path):
    repo_root = tmp_path
    state_dir = tmp_path / 'state'
    (state_dir / 'control' / 'autowork').mkdir(parents=True, exist_ok=True)
    (state_dir / 'tasks' / 'processed').mkdir(parents=True, exist_ok=True)
    harness_dir = tmp_path / 'harness'
    harness_dir.mkdir(parents=True, exist_ok=True)
    (harness_dir / 'config.yaml').write_text(_config_text(False), encoding='utf-8')
    result = _reclaim_zombie_briefs(repo_root, state_dir, running=None)
    assert isinstance(result, dict)
    assert isinstance(result['reclaimed'], int)
    assert isinstance(result['slugs'], list)