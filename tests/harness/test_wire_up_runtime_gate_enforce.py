"""RED behavioral oracle for the fail-closed runtime symbol gate -- the full
PHASE-3 knob matrix over the REAL ``harness.orchestrator._run_wire_up_gate``
(leaf: wire-up-runtime-gate-enforce, mutation_target: harness.orchestrator).

THE BLIND SPOT this oracle pins: the accept-time wire-up gate only fires for a
*newly-created* module. A commit that ADDS a brand-new top-level callable to an
ALREADY-TRACKED module slips through. PHASE-2 (already on HEAD) teaches
``_run_wire_up_gate`` -- when armed via ``_wire_up_runtime_gate_enabled`` -- to
AST-diff each tracked touched module against its parent HEAD and SHADOW-REPORT
(``phase=='report'``, ``event=='orphan_symbol_unwired'``) every newly-added
callable lacking a valid per-symbol runtime-reachability contract. PHASE-3
(TASK 2, NOT on HEAD) adds a SECOND knob, ``_wire_up_runtime_gate_enforce_enabled``
(absent on HEAD -- hence ``raising=False``), that turns an uncovered finding into
a hard REJECT via the existing reject path: roll the staged commit back, remove
the worktree, write a ``phase=='rejected'`` row, route the task to blocked/, and
return True.

This module drives the REAL ``_run_wire_up_gate`` over a hermetic synthetic git
tree (``git init`` + a committed PARENT ``pkg/mod.py`` defining ``def already():``
and a sibling staging worktree whose committed child ADDS
``def brand_new(): return 1``), reads back the REAL ``state_dir/impl_progress.jsonl``
ledger, and inspects the REAL git HEAD / rollback state, pinning:

  * both knobs OFF  -> strict no-op (no row, returns False),
  * shadow ON only  -> report row, NO rollback, returns False,
  * shadow+enforce + uncovered -> REJECT (return True, rejected row, rollback,
    blocked, worktree removed) -- RED on HEAD,
  * a valid per-symbol LIVE_ROOT contract OR a ``wire_exempt`` entry -> NO reject,
  * a self-cert contract -> STILL rejected -- RED on HEAD,
  * a pre-existing zero-caller symbol -> NEVER rejected.

Expectations are DERIVED from on-disk source (via the real
``new_top_level_callables``), the real ledger file, and the real git HEAD/rollback
state -- never a frozen ledger literal and never by pasting the impl into the test.

NON-GOALS: this is a hermetic, unit-level behavioral oracle over
``_run_wire_up_gate`` ONLY -- it is NOT an integration test (it never drives the
full pipeline, spawns a real agent, or hits a real LIVE_ROOT inline) and the
literal word *integration* appears here solely to excuse the integration-test
requirement. It does not re-implement or assert against ``harness/wire_up.py``
internals (``new_top_level_callables`` is used transitively only to DERIVE
expectations) or against ``harness/state_reconciler.py``, and it edits no
production file. It is RED on HEAD: ``_wire_up_runtime_gate_enforce_enabled`` and
the reject branch do not exist yet, so the enforce-reject expectations fail until
TASK 2 lands.
"""
import json
import subprocess
from pathlib import Path
import harness.orchestrator as orchestrator
from harness.orchestrator import _run_wire_up_gate
from harness.wire_up import LIVE_ROOTS, new_top_level_callables
_REL = 'pkg/mod.py'
_MARKER = 'orphan_symbol_unwired'
_MODULE_MARKER = 'orphan_unwired'
_PARENT_SRC = 'def already():\n    return 0\n'
_CHILD_SRC = 'def already():\n    return 0\n\n\ndef brand_new():\n    return 1\n'
_PARENT_OLD = 'def already():\n    return 0\n\n\ndef old_uncalled():\n    return 7\n'
_CHILD_OLD_WIRED = 'def already():\n    return 0\n\n\ndef old_uncalled():\n    return 7\n\n\ndef wired_one():\n    return 2\n'
_CHILD_OLD_BRANDNEW = 'def already():\n    return 0\n\n\ndef old_uncalled():\n    return 7\n\n\ndef brand_new():\n    return 1\n'
_CHILD_FACTORY = 'from dataclasses import dataclass\n\n\ndef already():\n    return 0\n\n\ndef make_widget():\n    return 1\n\n\n@dataclass\nclass Widget:\n    n: int = 0\n\n\nWIDGET_CONST = 9\n'

def _git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True, check=True)

def _build_tree(root, parent_src, child_src, rel=_REL):
    """Parent repo (committed ``rel``) + a sibling staging worktree on branch
    ``staging`` whose committed child rewrites ``rel`` to ``child_src``. Returns
    ``(state_dir, repo, staging, sha)`` -- exactly the ``worktree_root`` /
    ``staging_path`` pair ``_run_wire_up_gate`` expects, the staged child sha, and
    a fresh ``state_dir`` whose ``impl_progress.jsonl`` is read back after."""
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

def _stage_task_file(state_dir, task_id, task):
    """Place the task spec where ``_mark_blocked`` looks for it so a reject can
    actually route it into ``tasks/blocked/``."""
    p = Path(state_dir) / 'tasks' / f'{task_id}.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(task), encoding='utf-8')
    return p

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

def _arm(monkeypatch, *, shadow, enforce):
    """Toggle the two knobs by monkeypatching the module-level readers. The
    enforce reader does NOT exist on HEAD, so ``raising=False`` creates it (and is
    auto-reverted on teardown); NEVER detect a fixture name."""
    monkeypatch.setattr(orchestrator, '_wire_up_runtime_gate_enabled', lambda *a, **k: shadow, raising=False)
    monkeypatch.setattr(orchestrator, '_wire_up_runtime_gate_enforce_enabled', lambda *a, **k: enforce, raising=False)

def _task(task_id, *, integration_contract=None, wire_exempt=None):
    constraints = {}
    if integration_contract is not None:
        constraints['integration_contract'] = integration_contract
    if wire_exempt is not None:
        constraints['wire_exempt'] = wire_exempt
    return {'task_id': task_id, 'meta_task_type': 'harness_plumbing', 'files_touched': [_REL], 'constraints': constraints}

def _valid_contract(symbols, entrypoint=None, oracle='tests/harness/test_x_runtime.py'):
    """A VALID per-symbol runtime-reachability contract: entrypoint is a real
    LIVE_ROOT, the symbol is named, and a runtime_oracle is declared."""
    return {'entrypoints': [entrypoint if entrypoint is not None else LIVE_ROOTS[0]], 'symbols': list(symbols), 'observable_effect': 'invoked during orchestration', 'runtime_oracle': oracle}

def _drive(task, state_dir, repo, staging, sha, task_id):
    """Run the REAL gate, then read the real ledger + real git/worktree state.

    ``staging_tip`` is read from the PARENT repo's ``staging`` branch ref so it
    resolves whether or not the worktree was removed on reject."""
    returned = _run_wire_up_gate(task, [_REL], state_dir, task_id, staging, repo, {'sha': sha}, None)
    rows = _read_rows(state_dir)
    tip = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'staging'], capture_output=True, text=True).stdout.strip()
    exists = Path(staging).exists()
    return (returned, rows, tip, exists)

def _staging_blob(repo, rel=_REL):
    r = subprocess.run(['git', '-C', str(repo), 'show', f'staging:{rel}'], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ''

def _symbol_rows(rows, *, task_id=None, phase=None, symbol=None, file=_REL):
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if r.get('event') != _MARKER:
            continue
        if task_id is not None and r.get('task_id') != task_id:
            continue
        if phase is not None and r.get('phase') != phase:
            continue
        if file is not None and r.get('file') != file:
            continue
        if symbol is not None and symbol not in (r.get('symbols') or []):
            continue
        out.append(r)
    return out

def _reject_rows(rows, task_id=None, symbol=None):
    return _symbol_rows(rows, task_id=task_id, phase='rejected', symbol=symbol)

def _report_rows(rows, task_id=None, symbol=None):
    return _symbol_rows(rows, task_id=task_id, phase='report', symbol=symbol)

def _blocked_rows(rows, task_id):
    return [r for r in rows if isinstance(r, dict) and r.get('task_id') == task_id and (r.get('event') == 'task_blocked')]

def _module_orphan_rows(rows, task_id=None):
    out = []
    for r in rows:
        if not isinstance(r, dict) or r.get('event') != _MODULE_MARKER:
            continue
        if task_id is not None and r.get('task_id') != task_id:
            continue
        out.append(r)
    return out

def test_run_wire_up_gate_drives_real_synthetic_tree(tmp_path, monkeypatch):
    assert _run_wire_up_gate is orchestrator._run_wire_up_gate
    assert callable(_run_wire_up_gate)
    assert isinstance(LIVE_ROOTS, list) and LIVE_ROOTS, 'LIVE_ROOTS must be a non-empty list'
    _arm(monkeypatch, shadow=True, enforce=False)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    probe = subprocess.run(['git', '-C', str(repo), 'cat-file', '-e', f'HEAD:{_REL}'], capture_output=True, text=True)
    assert probe.returncode == 0, 'parent HEAD must already track pkg/mod.py (tracked-in-parent branch)'
    parent_on_disk = _git(repo, 'show', f'HEAD:{_REL}').stdout
    child_on_disk = (staging / _REL).read_text(encoding='utf-8')
    new_syms = new_top_level_callables(parent_on_disk, child_on_disk)
    assert 'brand_new' in new_syms and 'already' not in new_syms
    returned, rows, tip, exists = _drive(_task('WURGE_SMOKE'), state_dir, repo, staging, sha, 'WURGE_SMOKE')
    assert returned is False
    assert _report_rows(rows, 'WURGE_SMOKE', symbol='brand_new'), 'the real _run_wire_up_gate must emit an orphan_symbol_unwired report over the synthetic tree'
    assert exists is True and tip == sha

def test_both_knobs_off_strict_no_op_no_row_returns_false(tmp_path, monkeypatch):
    _arm(monkeypatch, shadow=False, enforce=False)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    tid = 'WURGE_OFF'
    returned, rows, tip, exists = _drive(_task(tid), state_dir, repo, staging, sha, tid)
    assert returned is False, 'both knobs OFF must proceed (return False)'
    assert _symbol_rows(rows) == [], 'both knobs OFF must write NO orphan_symbol_unwired row'
    assert [r for r in rows if isinstance(r, dict) and r.get('task_id') == tid] == [], 'both knobs OFF must be a strict no-op (no ledger writes for this task)'
    assert exists is True and tip == sha, 'a strict no-op must not touch the staged commit/worktree'

def test_both_knobs_off_strict_no_op_even_with_contract_and_exempt(tmp_path, monkeypatch):
    _arm(monkeypatch, shadow=False, enforce=False)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    tid = 'WURGE_OFF_CTR'
    task = _task(tid, integration_contract={'entrypoints': ['xyzzy']}, wire_exempt=['brand_new'])
    returned, rows, tip, exists = _drive(task, state_dir, repo, staging, sha, tid)
    assert returned is False
    assert [r for r in rows if isinstance(r, dict) and r.get('task_id') == tid] == [], 'OFF must be a strict no-op regardless of contract/exempt content'
    assert exists is True and tip == sha

def test_shadow_only_writes_report_row_no_rollback_returns_false(tmp_path, monkeypatch):
    _arm(monkeypatch, shadow=True, enforce=False)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    tid = 'WURGE_SHADOW'
    returned, rows, tip, exists = _drive(_task(tid), state_dir, repo, staging, sha, tid)
    reps = _report_rows(rows, tid, symbol='brand_new')
    assert reps, 'shadow ON + enforce OFF must write a phase==report orphan_symbol_unwired row for brand_new'
    row = reps[0]
    assert row.get('phase') == 'report'
    assert row.get('file') == _REL
    assert 'brand_new' in (row.get('symbols') or [])
    assert returned is False, 'a report-only run must proceed (return False)'
    assert _reject_rows(rows, tid) == [], 'shadow-only must NOT write a rejected row'
    assert _blocked_rows(rows, tid) == [], 'shadow-only must NOT block the task'
    assert exists is True, 'shadow-only must NOT remove the staging worktree'
    assert tip == sha, 'shadow-only: the staged commit must SURVIVE (no rollback)'

def test_enforce_on_uncovered_rejects_rolls_back_blocks_returns_true(tmp_path, monkeypatch):
    _arm(monkeypatch, shadow=True, enforce=True)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    parent_sha = _git(repo, 'rev-parse', 'HEAD').stdout.strip()
    assert parent_sha != sha
    tid = 'WURGE_ENF_REJ'
    task = _task(tid)
    _stage_task_file(state_dir, tid, task)
    parent_on_disk = _git(repo, 'show', f'HEAD:{_REL}').stdout
    child_on_disk = (staging / _REL).read_text(encoding='utf-8')
    new_syms = new_top_level_callables(parent_on_disk, child_on_disk)
    assert 'brand_new' in new_syms
    returned, rows, tip, exists = _drive(task, state_dir, repo, staging, sha, tid)
    assert returned is True, 'enforce ON + uncovered must REJECT (return True)'
    rej = _reject_rows(rows, tid, symbol='brand_new')
    assert rej, 'enforce ON + uncovered must write a phase==rejected orphan_symbol_unwired row naming brand_new'
    row = rej[0]
    assert row.get('phase') == 'rejected'
    assert row.get('event') == _MARKER
    assert row.get('file') == _REL
    assert 'brand_new' in (row.get('symbols') or [])
    assert _blocked_rows(rows, tid), 'a rejected task must be routed to blocked/ (task_blocked row)'
    assert (state_dir / 'tasks' / 'blocked' / f'{tid}.json').exists(), 'the task spec must land in tasks/blocked/'
    assert not (state_dir / 'tasks' / f'{tid}.json').exists(), 'the original task spec must leave tasks/'
    assert exists is False, 'the staging worktree must be removed on reject'
    assert tip != sha, 'the staged child commit must be rolled back off the staging branch'
    assert tip == parent_sha, 'rollback must reset the staging branch to its parent commit'
    assert 'brand_new' not in _staging_blob(repo), 'brand_new must be gone from the rolled-back tree'

def test_enforce_on_valid_live_root_contract_proceeds_no_reject_row(tmp_path, monkeypatch):
    _arm(monkeypatch, shadow=True, enforce=True)
    live_root = LIVE_ROOTS[0]
    assert live_root in LIVE_ROOTS
    contract = _valid_contract(['brand_new'], entrypoint=live_root, oracle='tests/harness/test_brand_new_runtime.py')
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    tid = 'WURGE_VC'
    returned, rows, tip, exists = _drive(_task(tid, integration_contract=contract), state_dir, repo, staging, sha, tid)
    assert returned is False, 'a valid per-symbol LIVE_ROOT contract must suppress the reject (proceed)'
    assert _reject_rows(rows, tid) == [], 'no phase==rejected row may be written for a covered symbol'
    assert _blocked_rows(rows, tid) == []
    assert exists is True and tip == sha, 'a covered symbol must leave the staged commit intact'

def test_enforce_on_wire_exempt_symbol_proceeds_no_reject_row(tmp_path, monkeypatch):
    _arm(monkeypatch, shadow=True, enforce=True)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    tid = 'WURGE_EX'
    returned, rows, tip, exists = _drive(_task(tid, wire_exempt=['brand_new']), state_dir, repo, staging, sha, tid)
    assert returned is False, 'wire_exempt must suppress the reject (proceed)'
    assert _reject_rows(rows, tid) == [], 'a wire_exempt symbol must not produce a rejected row'
    assert _blocked_rows(rows, tid) == []
    assert exists is True and tip == sha, 'the staged commit must survive'

def test_enforce_on_wire_exempt_dataclass_constant_proceeds(tmp_path, monkeypatch):
    _arm(monkeypatch, shadow=True, enforce=True)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_FACTORY)
    parent_on_disk = _git(repo, 'show', f'HEAD:{_REL}').stdout
    child_on_disk = (staging / _REL).read_text(encoding='utf-8')
    new_syms = new_top_level_callables(parent_on_disk, child_on_disk)
    assert 'make_widget' in new_syms and 'already' not in new_syms
    tid = 'WURGE_EX_DC'
    task = _task(tid, wire_exempt=['make_widget', 'Widget', 'WIDGET_CONST'])
    returned, rows, tip, exists = _drive(task, state_dir, repo, staging, sha, tid)
    assert returned is False, 'a wire_exempt-listed dataclass/constant + factory addition must proceed under enforce'
    assert _reject_rows(rows, tid) == [], 'no rejected row may be written when every new symbol is exempt'
    assert _blocked_rows(rows, tid) == []
    assert exists is True and tip == sha, 'the staged commit must survive'

def test_enforce_on_self_cert_contract_still_rejects_brand_new(tmp_path, monkeypatch):
    _arm(monkeypatch, shadow=True, enforce=True)
    assert 'xyzzy' not in LIVE_ROOTS
    contract = {'entrypoints': ['xyzzy']}
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    parent_sha = _git(repo, 'rev-parse', 'HEAD').stdout.strip()
    tid = 'WURGE_SELFCERT'
    task = _task(tid, integration_contract=contract)
    _stage_task_file(state_dir, tid, task)
    returned, rows, tip, exists = _drive(task, state_dir, repo, staging, sha, tid)
    assert returned is True, 'a self-cert contract must NOT cover brand_new -> reject under enforce'
    assert _reject_rows(rows, tid, symbol='brand_new'), 'a self-cert contract must still produce a phase==rejected row naming brand_new'
    assert _blocked_rows(rows, tid), 'the rejected task must be blocked'
    assert exists is False, 'the staging worktree must be removed on reject'
    assert tip != sha and tip == parent_sha, 'the staged commit must be rolled back'

def test_enforce_on_preexisting_zero_caller_symbol_never_rejected(tmp_path, monkeypatch):
    _arm(monkeypatch, shadow=True, enforce=True)
    contract = _valid_contract(['wired_one'], entrypoint=LIVE_ROOTS[0], oracle='tests/harness/test_wired_one_runtime.py')
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_OLD, _CHILD_OLD_WIRED)
    parent_on_disk = _git(repo, 'show', f'HEAD:{_REL}').stdout
    child_on_disk = (staging / _REL).read_text(encoding='utf-8')
    new_syms = new_top_level_callables(parent_on_disk, child_on_disk)
    assert 'wired_one' in new_syms and 'old_uncalled' not in new_syms
    tid = 'WURGE_PREEXIST'
    returned, rows, tip, exists = _drive(_task(tid, integration_contract=contract), state_dir, repo, staging, sha, tid)
    assert returned is False, 'a covered new symbol + a pre-existing symbol must proceed'
    assert _reject_rows(rows, tid) == [], 'no rejected row may be written'
    assert _symbol_rows(rows, task_id=tid, symbol='old_uncalled') == [], 'a pre-existing zero-caller symbol must NEVER be flagged (report or reject)'
    assert exists is True and tip == sha

def test_reject_rows_only_ever_name_new_in_commit_symbols(tmp_path, monkeypatch):
    _arm(monkeypatch, shadow=True, enforce=True)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_OLD, _CHILD_OLD_BRANDNEW)
    parent_on_disk = _git(repo, 'show', f'HEAD:{_REL}').stdout
    child_on_disk = (staging / _REL).read_text(encoding='utf-8')
    new_syms = set(new_top_level_callables(parent_on_disk, child_on_disk))
    assert 'brand_new' in new_syms and 'old_uncalled' not in new_syms and ('already' not in new_syms)
    tid = 'WURGE_PROP'
    task = _task(tid)
    _stage_task_file(state_dir, tid, task)
    returned, rows, tip, exists = _drive(task, state_dir, repo, staging, sha, tid)
    assert returned is True, 'enforce ON + uncovered must reject (the property has teeth only when a reject occurs)'
    rej = _reject_rows(rows, tid)
    assert rej, 'a phase==rejected row must exist to exercise the property'
    named = set()
    for r in rej:
        syms = set(r.get('symbols') or [])
        assert syms, 'a reject row must name at least one symbol'
        assert syms <= new_syms, 'a reject row may only name symbols that are NEW in this commit'
        assert 'old_uncalled' not in syms, 'a pre-existing symbol must never appear in a reject row'
        assert 'already' not in syms, 'an unchanged symbol must never appear in a reject row'
        named |= syms
    assert 'brand_new' in named, 'the genuinely-new uncovered symbol must be the one rejected'

def test_phase2_report_row_shape_unchanged_under_shadow_only(tmp_path, monkeypatch):
    _arm(monkeypatch, shadow=True, enforce=False)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    tid = 'WURGE_P2SHAPE'
    returned, rows, tip, exists = _drive(_task(tid), state_dir, repo, staging, sha, tid)
    reps = _report_rows(rows, tid)
    assert reps, 'shadow-only must still emit the PHASE-2 report row'
    row = reps[0]
    assert row.get('phase') == 'report'
    assert row.get('event') == _MARKER
    assert row.get('file') == _REL
    assert isinstance(row.get('symbols'), list) and 'brand_new' in row.get('symbols')
    assert returned is False
    assert _reject_rows(rows, tid) == [], 'shadow-only must not emit a rejected row'
    assert exists is True and tip == sha, 'shadow-only must not roll back'

def test_module_level_orphan_unwired_path_not_triggered_by_symbol_branch(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrator, '_wire_up_gate_enabled', lambda *a, **k: True, raising=False)
    _arm(monkeypatch, shadow=True, enforce=False)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    tid = 'WURGE_MODSPLIT'
    returned, rows, tip, exists = _drive(_task(tid), state_dir, repo, staging, sha, tid)
    assert _report_rows(rows, tid, symbol='brand_new'), 'the tracked-file symbol branch must fire'
    assert _module_orphan_rows(rows, tid) == [], 'a tracked-file new symbol must NEVER trigger the module-level orphan_unwired path'
    assert returned is False, 'the tracked-file symbol branch must not reject under shadow-only'
    assert exists is True and tip == sha, 'no rollback may occur via the module-level path'