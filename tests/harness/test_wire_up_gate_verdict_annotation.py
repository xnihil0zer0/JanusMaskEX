"""RED oracle for the ADDITIVE, report-only per-symbol ``wireup_symbol_verdict``
annotation that ``harness.orchestrator._run_wire_up_gate`` is to emit for every
new top-level callable (harness/orchestrator.py:2241).

THE BEHAVIOUR PINNED: when the runtime symbol gate is armed
(``_wire_up_runtime_gate_enabled`` True) and enforcement is OFF
(``_wire_up_runtime_gate_enforce_enabled`` False), the gate must, for each
newly-added top-level callable ``S``, write an additive REPORT-ONLY ledger row
``event == 'wireup_symbol_verdict'`` carrying the four per-symbol grades:

  * ``floor_reachable``   -- ``wire_up.symbol_reachable_from_live_root`` verdict
                             (S is statically reachable from a LIVE_ROOT);
  * ``would_be_orphan``   -- not floor-reachable AND no valid contract AND not
                             exempt;
  * ``contract_detonated``-- the FAIL-CLOSED ``wire_up.detonate_oracle`` grade
                             (never depends on a live detonation succeeding);
  * ``exempt_honored``    -- ``wire_up.validate_exemption`` verdict for a
                             ``wire_exempt`` symbol (honoured only when it passes
                             the static floor).

CRITICALLY ADDITIVE: emitting the verdict must NOT change the existing
``orphan_symbol_unwired`` suppression, the rollback path, or the gate return
value -- the gate still NEVER returns True and NEVER rolls back under
ON + enforce-OFF, and a verbatim ``wire_exempt`` still suppresses the existing
orphan row byte-for-byte.

This drives the REAL ``_run_wire_up_gate`` over the hermetic synthetic git tree
built by the sibling oracle ``test_wire_up_runtime_gate_accept`` (reusing its
``_build_tree`` / ``_arm`` / ``_task`` / ``_drive`` / ``_read_rows`` idiom) and
reads back ``state_dir/impl_progress.jsonl``. It is RED on HEAD: no
``wireup_symbol_verdict`` event exists yet, so every armed verdict expectation
fails until the annotation lands.

NON-GOALS: unit-level oracle over ``_run_wire_up_gate`` ONLY -- it never drives
the full pipeline, spawns an agent, or hits a real LIVE_ROOT inline; it runs NO
live detonation (it relies on ``detonate_oracle`` fail-closing to False); it does
NOT import or run the broad adversarial suite, does NOT re-author any existing
uncovered/suppress or ``orphan_symbol_unwired`` test, and edits no production
file. Offline/hermetic throughout.
"""
from pathlib import Path
import harness.orchestrator as orchestrator
from harness.orchestrator import _run_wire_up_gate
from harness.wire_up import LIVE_ROOTS, new_top_level_callables
from tests.harness.test_wire_up_runtime_gate_accept import _build_tree, _arm, _task, _drive, _read_rows, _sub, _git, _reports, _terminals, _valid_contract, _REL, _PARENT_SRC, _CHILD_SRC
_S = 'brand_new'
_LIVE_ROOT_REF = 'from pkg.mod import {sym}\n\n\ndef _live_use():\n    return {sym}()\n'

def _arm_report_only(monkeypatch):
    """Arm ``wire_up_runtime_gate`` ON and pin enforcement OFF.

    ``_arm`` monkeypatches ``orchestrator._wire_up_runtime_gate_enabled`` to True
    (raising=False so it is created on HEAD), and the explicit setattr forces the
    fail-closed enforce knob OFF so the gate stays strictly report-only.
    """
    _arm(monkeypatch, True)
    monkeypatch.setattr(orchestrator, '_wire_up_runtime_gate_enforce_enabled', lambda *a, **k: False, raising=False)

def _wire_live_root(staging, symbol, *, live_root=LIVE_ROOTS[0]):
    """Add a committed LIVE_ROOT module to ``staging`` that statically references
    ``symbol``, making it floor-reachable. Returns the new staging tip sha."""
    p = Path(staging) / live_root
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_LIVE_ROOT_REF.format(sym=symbol), encoding='utf-8')
    _git(staging, 'add', '-A')
    _git(staging, 'commit', '-q', '-m', 'wire: live root statically references new symbol')
    return _git(staging, 'rev-parse', 'HEAD').stdout.strip()

def _verdicts(rows, symbol):
    """Select the additive verdict rows for ``symbol``: ``event ==
    'wireup_symbol_verdict'`` and ``symbol == S``."""
    return [r for r in rows if isinstance(r, dict) and r.get('event') == 'wireup_symbol_verdict' and (r.get('symbol') == symbol)]

def test_floor_reachable_symbol_emits_verdict(tmp_path, monkeypatch):
    """A new top-level callable statically reachable from a LIVE_ROOT emits a
    verdict with ``floor_reachable: true`` (forcing ``symbol_reachable_from_live_root``
    to be wired)."""
    assert _run_wire_up_gate is orchestrator._run_wire_up_gate
    _arm_report_only(monkeypatch)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    expected_new = new_top_level_callables(_PARENT_SRC, _CHILD_SRC)
    assert _S in expected_new and 'already' not in expected_new
    new_sha = _wire_live_root(staging, _S)
    returned, rows, head = _drive(_task('WUV_FLOOR'), state_dir, repo, staging, new_sha, 'WUV_FLOOR')
    vs = _verdicts(rows, _S)
    assert vs, 'a floor-reachable new callable must emit a wireup_symbol_verdict'
    v = vs[0]
    assert v.get('floor_reachable') is True
    assert v.get('would_be_orphan') is False
    assert returned is False, 'report-only gate must proceed (return False)'
    assert head == new_sha, 'report-only gate must not roll back the staged commit'

def test_orphan_symbol_would_be_orphan_true(tmp_path, monkeypatch):
    """A non-reachable orphan with no contract and not exempt yields a verdict
    with ``would_be_orphan: true`` (floor_reachable / contract_detonated /
    exempt_honored all False)."""
    _arm_report_only(monkeypatch)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    returned, rows, head = _drive(_task('WUV_ORPHAN'), state_dir, repo, staging, sha, 'WUV_ORPHAN')
    vs = _verdicts(rows, _S)
    assert vs, 'a new orphan callable must still emit a wireup_symbol_verdict'
    v = vs[0]
    assert v.get('would_be_orphan') is True
    assert v.get('floor_reachable') is False
    assert v.get('contract_detonated') is False
    assert v.get('exempt_honored') is False
    assert returned is False
    assert head == sha

def test_wire_exempt_fail_floor_exempt_honored_false(tmp_path, monkeypatch):
    """A ``wire_exempt`` symbol that FAILS the static floor yields a verdict with
    ``exempt_honored: false`` (forcing ``validate_exemption`` to be wired)."""
    _arm_report_only(monkeypatch)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    returned, rows, head = _drive(_task('WUV_EX_FAIL', wire_exempt=[_S]), state_dir, repo, staging, sha, 'WUV_EX_FAIL')
    vs = _verdicts(rows, _S)
    assert vs, 'a wire_exempt symbol must still emit a wireup_symbol_verdict'
    v = vs[0]
    assert v.get('exempt_honored') is False
    assert v.get('floor_reachable') is False
    assert returned is False
    assert head == sha

def test_wire_exempt_fail_floor_orphan_row_still_suppressed(tmp_path, monkeypatch):
    """The ADDITIVE proof: for a verbatim ``wire_exempt`` symbol that fails the
    floor, the NEW verdict reports ``exempt_honored: false`` WHILE the EXISTING
    ``orphan_symbol_unwired`` suppression is unchanged (no orphan row)."""
    _arm_report_only(monkeypatch)
    sd, repo, stg, sha = _build_tree(_sub(tmp_path, 'control'), _PARENT_SRC, _CHILD_SRC)
    _ret, rows, _head = _drive(_task('WUV_SUP_CTRL'), sd, repo, stg, sha, 'WUV_SUP_CTRL')
    assert _reports(rows, _S), 'control: orphan_symbol_unwired must fire when nothing exempts brand_new'
    sd, repo, stg, sha = _build_tree(_sub(tmp_path, 'exempt'), _PARENT_SRC, _CHILD_SRC)
    ret, rows, head = _drive(_task('WUV_SUP_EX', wire_exempt=[_S]), sd, repo, stg, sha, 'WUV_SUP_EX')
    assert _reports(rows, _S) == [], 'wire_exempt must keep suppressing the existing orphan_symbol_unwired row (unchanged)'
    vs = _verdicts(rows, _S)
    assert vs, 'the additive verdict must still be emitted alongside the unchanged suppression'
    assert vs[0].get('exempt_honored') is False
    assert ret is False
    assert head == sha

def test_wire_exempt_pass_floor_exempt_honored_true(tmp_path, monkeypatch):
    """A ``wire_exempt`` symbol that PASSES the static floor yields a verdict with
    ``exempt_honored: true``."""
    _arm_report_only(monkeypatch)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    new_sha = _wire_live_root(staging, _S)
    returned, rows, head = _drive(_task('WUV_EX_PASS', wire_exempt=[_S]), state_dir, repo, staging, new_sha, 'WUV_EX_PASS')
    vs = _verdicts(rows, _S)
    assert vs
    v = vs[0]
    assert v.get('exempt_honored') is True
    assert v.get('floor_reachable') is True
    assert returned is False
    assert head == new_sha

def test_contract_detonated_false_without_valid_contract(tmp_path, monkeypatch):
    """With no valid contract naming S, ``contract_detonated`` is a fail-closed
    bool (False)."""
    _arm_report_only(monkeypatch)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    returned, rows, head = _drive(_task('WUV_NOCONTRACT'), state_dir, repo, staging, sha, 'WUV_NOCONTRACT')
    vs = _verdicts(rows, _S)
    assert vs
    v = vs[0]
    assert isinstance(v.get('contract_detonated'), bool)
    assert v.get('contract_detonated') is False
    assert returned is False
    assert head == sha

def test_valid_contract_consults_detonation_fail_closed_bool(tmp_path, monkeypatch):
    """A VALID ``integration_contract`` naming S (entrypoints subset of
    LIVE_ROOTS, runtime_oracle present) still emits the verdict; the hermetic
    jail cannot detonate, so ``contract_detonated`` is consulted-but-fail-closed
    (a bool, False). Never depends on a live detonation succeeding."""
    _arm_report_only(monkeypatch)
    contract = _valid_contract(symbols=[_S], entrypoint=LIVE_ROOTS[0])
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    returned, rows, head = _drive(_task('WUV_CONTRACT', integration_contract=contract), state_dir, repo, staging, sha, 'WUV_CONTRACT')
    vs = _verdicts(rows, _S)
    assert vs, 'a valid-contract symbol must STILL emit a verdict (annotation is independent of coverage)'
    v = vs[0]
    assert isinstance(v.get('contract_detonated'), bool)
    assert v.get('contract_detonated') is False
    assert returned is False
    assert head == sha

def test_report_only_gate_never_returns_true_or_rolls_back(tmp_path, monkeypatch):
    """PROPERTY: under runtime-gate ON + enforce OFF, across every verdict
    fixture the gate NEVER returns True, NEVER rolls back (staging tip
    unchanged, no rejected/blocked row), and ``contract_detonated`` stays a
    fail-closed bool."""
    _arm_report_only(monkeypatch)
    fixtures = [('orphan', _task('WUV_PROP_orphan'), False), ('exempt_fail', _task('WUV_PROP_exfail', wire_exempt=[_S]), False), ('contract', _task('WUV_PROP_contract', integration_contract=_valid_contract(symbols=[_S], entrypoint=LIVE_ROOTS[0])), False), ('floor', _task('WUV_PROP_floor'), True)]
    for name, task, needs_root in fixtures:
        sd, repo, stg, sha = _build_tree(_sub(tmp_path, name), _PARENT_SRC, _CHILD_SRC)
        if needs_root:
            sha = _wire_live_root(stg, _S)
        tid = task['task_id']
        ret, rows, head = _drive(task, sd, repo, stg, sha, tid)
        assert _verdicts(rows, _S), f'{name}: a wireup_symbol_verdict row must be emitted'
        assert ret is False, f'{name}: report-only gate must never return True'
        assert head == sha, f'{name}: report-only gate must never roll back the staged commit'
        assert _terminals(rows, tid) == [], f'{name}: report-only must write no rejected/blocked row'
        for v in _verdicts(rows, _S):
            assert isinstance(v.get('contract_detonated'), bool), f'{name}: contract_detonated must be a fail-closed bool'

def test_both_knobs_off_strict_no_op(tmp_path, monkeypatch):
    """Both knobs OFF is a strict no-op: no wireup_symbol_verdict events, no
    orphan_symbol_unwired rows, returns False, staging tip unchanged."""
    _arm(monkeypatch, False)
    monkeypatch.setattr(orchestrator, '_wire_up_runtime_gate_enforce_enabled', lambda *a, **k: False, raising=False)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    returned, rows, head = _drive(_task('WUV_OFF'), state_dir, repo, staging, sha, 'WUV_OFF')
    assert returned is False, 'both knobs OFF must proceed (return False)'
    assert _verdicts(rows, _S) == [], 'both knobs OFF must emit NO wireup_symbol_verdict event'
    assert _reports(rows, _S) == [], 'both knobs OFF must emit NO orphan_symbol_unwired row'
    assert rows == [], 'both knobs OFF must be a strict no-op (no ledger writes at all)'
    assert head == sha

def test_red_on_head_no_wireup_symbol_verdict_event(tmp_path, monkeypatch):
    """RED-on-HEAD guard: an armed run must emit at least one
    ``wireup_symbol_verdict`` event naming S. The event does not exist on HEAD,
    so this FAILS until the additive annotation lands."""
    _arm_report_only(monkeypatch)
    state_dir, repo, staging, sha = _build_tree(tmp_path, _PARENT_SRC, _CHILD_SRC)
    returned, rows, head = _drive(_task('WUV_RED'), state_dir, repo, staging, sha, 'WUV_RED')
    verdict_events = [r for r in rows if isinstance(r, dict) and r.get('event') == 'wireup_symbol_verdict']
    assert verdict_events, 'the wireup_symbol_verdict annotation must be emitted (RED on HEAD until it lands)'
    assert any((r.get('symbol') == _S for r in verdict_events))
    assert returned is False
    assert head == sha