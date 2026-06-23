"""RED behavioral oracle for the runtime-reachability symbol gate
(leaf: wire-up-runtime-gate, mutation_target: harness.orchestrator).

THE BLIND SPOT this oracle defends: the existing accept-time wire-up gate only
fires for a *newly-created* module (one not tracked in the parent HEAD). A commit
that ADDS a brand-new top-level callable to an ALREADY-TRACKED module slips through
untouched -- the symbol is orphaned (no live caller, no declared contract) yet the
module itself is wired, so ``_run_wire_up_gate`` waves it past.

TASK 2 closes that hole by teaching ``_run_wire_up_gate`` to, when armed via a NEW
``harness.orchestrator._wire_up_runtime_gate_enabled`` flag-reader, diff each
already-tracked touched module against its parent HEAD (via the real
``harness.wire_up.new_top_level_callables``) and, for every newly-added top-level
callable that is NOT covered by a valid per-symbol ``integration_contract`` and NOT
listed in ``wire_exempt``, write a REPORT-ONLY ``orphan_symbol_unwired`` ledger row
(``phase=='report'``). Report-only: it NEVER rolls back, NEVER blocks/rejects, and
ALWAYS returns False (proceed).

This file drives the REAL ``_run_wire_up_gate`` over a hermetic synthetic git tree
(git init + a committed PARENT ``pkg/mod.py`` defining ``def already(): ...`` and a
sibling staging worktree whose committed child ADDS ``def brand_new(): return 1``),
reads back the REAL ``state_dir/impl_progress.jsonl`` ledger, and pins:

  * DEFAULT-OFF strict no-op (byte-identical to today: no row, returns False),
  * armed + missing-contract report emission without rollback,
  * ``wire_exempt`` and valid per-symbol ``integration_contract`` suppression,
  * the self-cert rejections (a)-(d),
  * the pre-existing-symbol false-positive guard,
  * the dead-code static-reference hole.

It is RED on HEAD: ``_wire_up_runtime_gate_enabled`` and the report branch do not
exist yet, so the armed expectations fail until TASK 2 lands.

NON-GOALS: this is a unit-level oracle over ``_run_wire_up_gate`` ONLY -- it is NOT
an integration test (it never drives the full pipeline, spawns an agent, or hits a
real LIVE_ROOT inline). It does not re-implement or assert against
``harness/wire_up.py`` internals (``new_top_level_callables`` is exercised
transitively + used only to DERIVE expectations from on-disk source) or against
``harness/state_reconciler.py``. No production file is edited.
"""
import json
import subprocess
from pathlib import Path
import harness.orchestrator as orchestrator
from harness.orchestrator import _run_wire_up_gate
from harness.wire_up import LIVE_ROOTS, new_top_level_callables
_REL = 'pkg/mod.py'
_MARKER = 'orphan_symbol_unwired'
_PARENT_SRC = 'def already():\n    return 0\n'
_CHILD_SRC = 'def already():\n    return 0\n\n\ndef brand_new():\n    return 1\n'
_CHILD_DEADCODE = 'def already():\n    return 0\n\n\ndef brand_new():\n    return 1\n\n\ndef dead_sibling():\n    return brand_new()\n'
_CHILD_DATACLASS = 'from dataclasses import dataclass\n\n\ndef already():\n    return 0\n\n\n@dataclass\nclass NewThing:\n    x: int = 0\n\n\nNEW_CONST = 7\n'
_PARENT_OLD = 'def already():\n    return 0\n\n\ndef old_uncalled():\n    return 7\n'
_CHILD_OLD_WIRED = 'def already():\n    return 0\n\n\ndef old_uncalled():\n    return 7\n\n\ndef wired_one():\n    return 2\n'
_CHILD_OLD_BRANDNEW = 'def already():\n    return 0\n\n\ndef old_uncalled():\n    return 7\n\n\ndef brand_new():\n    return 1\n'

def _git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True, check=True)

def _sub(tmp_path, name):
    d = Path(tmp_path) / name
    d.mkdir(parents=True, exist_ok=True)
    return d

def _build_tree(root, parent_src, child_src, rel=_REL):
    """Build a parent repo (committed ``rel``) + a sibling staging worktree whose
    committed child rewrites ``rel`` to ``child_src``. Returns
    ``(state_dir, repo, staging, sha)`` -- the exact ``worktree_root`` / ``staging_path``
    pair ``_run_wire_up_gate`` expects, plus the staged commit sha and a fresh
    ``state_dir`` whose ``impl_progress.jsonl`` is read back after the gate runs."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    repo = root / 'repo'
    repo.mkdir()
    _git(repo, 'init', '-q', '-b', 'main')
    _git(repo, 'config', 'user.name', 'JanusMask Test')
    _git(repo, 'config', 'user.email', 'test@janusmask.local')
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    init = repo / Path(rel).parent / '__init__.py'
    if not init.exists():
        init.write_text('', encoding='utf-8')
    target.write_text(parent_src, encoding='utf-8')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-q', '-m', 'parent: already-tracked module')
    staging = root / 'repo_staging'
    _git(repo, 'worktree', 'add', '-b', 'staging', str(staging), 'HEAD')
    (staging / rel).write_text(child_src, encoding='utf-8')
    _git(staging, 'add', '-A')
    _git(staging, 'commit', '-q', '-m', 'child: add new top-level callable')
    sha = _git(staging, 'rev-parse', 'HEAD').stdout.strip()
    state_dir = root / 'state'
    (state_dir / 'output').mkdir(parents=True)
    (state_dir / 'tasks' / 'processed').mkdir(parents=True)
    return (state_dir, repo, staging, sha)

def _read_rows(state_dir):
    p = Path(state_dir) / 'impl_progress.jsonl'
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out

def _arm(monkeypatch, on):
    """Toggle the soon-to-exist runtime flag by monkeypatching the module-level
    reader (raising=False so it is created on HEAD where it does not yet exist),
    NEVER by detecting a fixture name."""
    monkeypatch.setattr(orchestrator, '_wire_up_runtime_gate_enabled', lambda *a, **k: on, raising=False)

def _task(task_id, *, integration_contract=None, wire_exempt=None, top_wire_exempt=None):
    constraints = {}
    if integration_contract is not None:
        constraints['integration_contract'] = integration_contract
    if wire_exempt is not None:
        constraints['wire_exempt'] = wire_exempt
    task = {'task_id': task_id, 'meta_task_type': 'harness_plumbing', 'files_touched': [_REL], 'constraints': constraints}
    if top_wire_exempt is not None:
        task['wire_exempt'] = top_wire_exempt
    return task

def _drive(task, state_dir, repo, staging, sha, task_id):
    returned = _run_wire_up_gate(task, [_REL], state_dir, task_id, staging, repo, {'sha': sha}, None)
    rows = _read_rows(state_dir)
    head = _git(staging, 'rev-parse', 'HEAD').stdout.strip()
    return (returned, rows, head)

def _is_symbol_report(r):
    """A report-only orphan_symbol_unwired ledger row: phase=='report' and the
    distinctive marker present as a field value (robust to the exact key name)."""
    if not isinstance(r, dict):
        return False
    if r.get('phase') != 'report':
        return False
    return any((v == _MARKER for v in r.values()))

def _reports(rows, symbol=None, file=_REL):
    out = []
    for r in rows:
        if not _is_symbol_report(r):
            continue
        if file is not None and r.get('file') != file:
            continue
        if symbol is not None and symbol not in (r.get('symbols') or []):
            continue
        out.append(r)
    return out

def _terminals(rows, task_id):
    """rejected/blocked terminal rows for a task (what report-only must NEVER write)."""
    out = []
    for r in rows:
        if not isinstance(r, dict) or r.get('task_id') != task_id:
            continue
        if r.get('event') == 'task_blocked' or r.get('phase') in ('rejected', 'blocked'):
            out.append(r)
    return out

def _valid_contract(symbols=('brand_new',), entrypoint=None, oracle='tests/harness/test_brand_new_runtime.py'):
    return {'entrypoints': [entrypoint if entrypoint is not None else LIVE_ROOTS[0]], 'symbols': list(symbols), 'observable_effect': 'brand_new is invoked during orchestration', 'runtime_oracle': oracle}

def test_hermetic_synthetic_tree_drives_real_run_wire_up_gate(tmp_path, monkeypatch):
    assert _run_wire_up_gate is orchestrator._run_wire_up_gate
    assert callable(_run_wire_up_gate)
    _arm(monkeypatch, True)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    probe = subprocess.run(['git', '-C', str(repo), 'cat-file', '-e', f'HEAD:{_REL}'], capture_output=True, text=True)
    assert probe.returncode == 0, 'parent HEAD must already track pkg/mod.py'
    parent_on_disk = _git(repo, 'show', f'HEAD:{_REL}').stdout
    child_on_disk = (staging / _REL).read_text(encoding='utf-8')
    expected_new = new_top_level_callables(parent_on_disk, child_on_disk)
    assert 'brand_new' in expected_new and 'already' not in expected_new
    returned, rows, head = _drive(_task('WURG_SMOKE'), state_dir, repo, staging, sha, 'WURG_SMOKE')
    assert returned is False
    assert _reports(rows, 'brand_new'), 'the real _run_wire_up_gate must emit an orphan_symbol_unwired report over the synthetic tree'
    assert head == sha

def test_default_off_strict_no_op_no_row_returns_false(tmp_path, monkeypatch):
    _arm(monkeypatch, False)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    returned, rows, head = _drive(_task('WURG_OFF'), state_dir, repo, staging, sha, 'WURG_OFF')
    assert returned is False, 'flag OFF must proceed (return False)'
    assert _reports(rows) == [], 'flag OFF must write NO orphan_symbol_unwired row'
    assert rows == [], 'flag OFF must be a strict no-op (no ledger writes at all)'
    assert head == sha

def test_armed_missing_contract_writes_report_row_no_rollback_returns_false(tmp_path, monkeypatch):
    _arm(monkeypatch, True)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    tid = 'WURG_ARMED'
    returned, rows, head = _drive(_task(tid), state_dir, repo, staging, sha, tid)
    reps = _reports(rows, 'brand_new')
    assert reps, 'armed + missing contract must write an orphan_symbol_unwired report row for brand_new'
    row = reps[0]
    assert row.get('phase') == 'report'
    assert row.get('file') == _REL
    assert 'brand_new' in (row.get('symbols') or [])
    assert returned is False, 'a report-only gate must still proceed (return False)'
    assert _terminals(rows, tid) == [], 'the armed report must NOT block/reject the task'
    assert head == sha, 'the staged commit must survive (no rollback)'

def test_wire_exempt_suppresses_report_for_symbol_and_dataclass_constant(tmp_path, monkeypatch):
    _arm(monkeypatch, True)
    sd, repo, stg, sha = _build_tree(_sub(tmp_path, 'control'), _PARENT_SRC, _CHILD_SRC)
    ret, rows, head = _drive(_task('WURG_EX_CTRL'), sd, repo, stg, sha, 'WURG_EX_CTRL')
    assert ret is False
    assert _reports(rows, 'brand_new'), 'control: brand_new must report when nothing exempts it'
    sd, repo, stg, sha = _build_tree(_sub(tmp_path, 'constraints'), _PARENT_SRC, _CHILD_SRC)
    ret, rows, head = _drive(_task('WURG_EX_C', wire_exempt=['brand_new']), sd, repo, stg, sha, 'WURG_EX_C')
    assert ret is False
    assert not _reports(rows, 'brand_new'), 'constraints.wire_exempt must suppress the report for brand_new'
    sd, repo, stg, sha = _build_tree(_sub(tmp_path, 'toplevel'), _PARENT_SRC, _CHILD_SRC)
    ret, rows, head = _drive(_task('WURG_EX_T', top_wire_exempt=['brand_new']), sd, repo, stg, sha, 'WURG_EX_T')
    assert ret is False
    assert not _reports(rows, 'brand_new'), 'top-level wire_exempt must suppress the report for brand_new'
    sd, repo, stg, sha = _build_tree(_sub(tmp_path, 'dataclass'), _PARENT_SRC, _CHILD_DATACLASS)
    ret, rows, head = _drive(_task('WURG_EX_D', wire_exempt=['NewThing', 'NEW_CONST']), sd, repo, stg, sha, 'WURG_EX_D')
    assert ret is False
    assert _reports(rows) == [], 'a wire_exempt-listed dataclass/constant addition must yield no report row'

def test_valid_per_symbol_contract_suppresses_report(tmp_path, monkeypatch):
    _arm(monkeypatch, True)
    live_root = LIVE_ROOTS[0]
    assert live_root in LIVE_ROOTS
    sd, repo, stg, sha = _build_tree(_sub(tmp_path, 'control'), _PARENT_SRC, _CHILD_SRC)
    ret, rows, head = _drive(_task('WURG_VC_CTRL'), sd, repo, stg, sha, 'WURG_VC_CTRL')
    assert ret is False
    assert _reports(rows, 'brand_new'), 'control: brand_new must report with no contract'
    contract = _valid_contract(symbols=['brand_new'], entrypoint=live_root)
    sd, repo, stg, sha = _build_tree(_sub(tmp_path, 'valid'), _PARENT_SRC, _CHILD_SRC)
    ret, rows, head = _drive(_task('WURG_VC', integration_contract=contract), sd, repo, stg, sha, 'WURG_VC')
    assert ret is False
    assert not _reports(rows, 'brand_new'), 'a valid per-symbol integration_contract must suppress the report'

def test_self_cert_bogus_and_non_live_root_and_blanket_and_unnamed_still_reported(tmp_path, monkeypatch):
    _arm(monkeypatch, True)
    live_root = LIVE_ROOTS[0]
    assert 'xyzzy' not in LIVE_ROOTS
    assert 'totally/made/up.py' not in LIVE_ROOTS
    cases = {'bogus': {'entrypoints': ['xyzzy'], 'symbols': ['brand_new'], 'observable_effect': 'x', 'runtime_oracle': 'tests/harness/test_x_runtime.py'}, 'nonliveroot': {'entrypoints': ['totally/made/up.py'], 'symbols': ['brand_new'], 'observable_effect': 'x', 'runtime_oracle': 'tests/harness/test_x_runtime.py'}, 'blanket': {'entrypoints': [live_root], 'observable_effect': 'x'}, 'unnamed': {'entrypoints': [live_root], 'symbols': ['some_other_symbol'], 'observable_effect': 'x', 'runtime_oracle': 'tests/harness/test_x_runtime.py'}}
    for name, contract in cases.items():
        sd, repo, stg, sha = _build_tree(_sub(tmp_path, name), _PARENT_SRC, _CHILD_SRC)
        tid = f'WURG_SELF_{name}'
        ret, rows, head = _drive(_task(tid, integration_contract=contract), sd, repo, stg, sha, tid)
        assert ret is False, f'{name}: report-only gate must still proceed'
        assert _reports(rows, 'brand_new'), f'{name}: a self-cert contract must NOT suppress -- brand_new must still be reported'
        assert _terminals(rows, tid) == [], f'{name}: report-only must not block/reject'
        assert head == sha, f'{name}: report-only must not roll back the staged commit'

def test_preexisting_zero_caller_symbol_never_flagged(tmp_path, monkeypatch):
    _arm(monkeypatch, True)
    contract = _valid_contract(symbols=['wired_one'], entrypoint=LIVE_ROOTS[0], oracle='tests/harness/test_wired_one_runtime.py')
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_OLD, _CHILD_OLD_WIRED)
    parent_on_disk = _git(repo, 'show', f'HEAD:{_REL}').stdout
    child_on_disk = (staging / _REL).read_text(encoding='utf-8')
    new_syms = new_top_level_callables(parent_on_disk, child_on_disk)
    assert 'old_uncalled' not in new_syms and 'wired_one' in new_syms
    returned, rows, head = _drive(_task('WURG_PREEXIST', integration_contract=contract), state_dir, repo, staging, sha, 'WURG_PREEXIST')
    assert returned is False
    assert _reports(rows, 'old_uncalled') == [], 'a pre-existing zero-caller symbol must NEVER be flagged (the diff is against the parent)'
    assert _reports(rows, 'wired_one') == [], 'the contract-covered new symbol must be suppressed'

def test_static_reference_in_dead_code_still_reported(tmp_path, monkeypatch):
    _arm(monkeypatch, True)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_DEADCODE)
    returned, rows, head = _drive(_task('WURG_DEAD'), state_dir, repo, staging, sha, 'WURG_DEAD')
    assert returned is False
    assert _reports(rows, 'brand_new'), 'a static call inside never-run dead code is NOT wiring -- brand_new must still be reported'
    assert head == sha

def test_report_only_branch_never_changes_return_value_or_rolls_back(tmp_path, monkeypatch):
    _arm(monkeypatch, True)
    firing = [('missing', _task('WURG_RO_missing')), ('selfcert', _task('WURG_RO_selfcert', integration_contract={'entrypoints': ['xyzzy'], 'symbols': ['brand_new'], 'observable_effect': 'x', 'runtime_oracle': 'tests/harness/test_x_runtime.py'}))]
    for name, task in firing:
        sd, repo, stg, sha = _build_tree(_sub(tmp_path, name), _PARENT_SRC, _CHILD_SRC)
        tid = task['task_id']
        ret, rows, head = _drive(task, sd, repo, stg, sha, tid)
        assert _reports(rows, 'brand_new'), f'{name}: the report branch must actually fire'
        assert ret is False, f'{name}: a report must never flip the gate to reject'
        assert head == sha, f'{name}: a report must never roll back the staged commit'
        assert _terminals(rows, tid) == [], f'{name}: a report must not write a rejected/blocked row'

def test_only_new_callables_relative_to_parent_are_ever_reported(tmp_path, monkeypatch):
    _arm(monkeypatch, True)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_OLD, _CHILD_OLD_BRANDNEW)
    parent_on_disk = _git(repo, 'show', f'HEAD:{_REL}').stdout
    child_on_disk = (staging / _REL).read_text(encoding='utf-8')
    expected_new = new_top_level_callables(parent_on_disk, child_on_disk)
    assert 'brand_new' in expected_new
    assert 'old_uncalled' not in expected_new
    assert 'already' not in expected_new
    returned, rows, head = _drive(_task('WURG_DIFF'), state_dir, repo, staging, sha, 'WURG_DIFF')
    assert returned is False
    assert _reports(rows, 'brand_new'), 'the newly-added callable must be reported'
    assert _reports(rows, 'old_uncalled') == [], 'a pre-existing callable must never be reported'
    assert _reports(rows, 'already') == [], 'an unchanged callable must never be reported'

def test_default_off_behavior_byte_identical_to_today_no_ledger_writes(tmp_path, monkeypatch):
    _arm(monkeypatch, False)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    returned, rows, head = _drive(_task('WURG_OFF_REG'), state_dir, repo, staging, sha, 'WURG_OFF_REG')
    assert returned is False
    assert rows == [], 'default-OFF must be byte-identical to today: NO ledger writes'
    assert _read_rows(state_dir) == []
    assert head == sha

def test_armed_run_writes_only_report_phase_rows_never_rejected_or_blocked(tmp_path, monkeypatch):
    _arm(monkeypatch, True)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    tid = 'WURG_ARMED_REG'
    returned, rows, head = _drive(_task(tid), state_dir, repo, staging, sha, tid)
    assert returned is False
    mine = [r for r in rows if isinstance(r, dict) and r.get('task_id') == tid]
    assert mine, 'an armed missing-contract run must write at least one ledger row'
    assert all((r.get('phase') == 'report' for r in mine)), "an armed report run must write ONLY phase=='report' rows for this task_id"
    assert _terminals(rows, tid) == [], 'an armed report run must NEVER write a rejected/blocked row'
    assert _reports(rows, 'brand_new'), 'the report row must name brand_new'
    assert head == sha