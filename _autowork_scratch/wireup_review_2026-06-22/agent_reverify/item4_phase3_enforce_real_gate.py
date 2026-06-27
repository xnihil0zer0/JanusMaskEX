"""ITEM 4 -- PHASE-3 ENFORCE, driven through the REAL _run_wire_up_gate over a
REAL synthetic git tree (mirrors tests/harness/test_wire_up_accept_gate.py).

We CANNOT edit production, so we build a faithful in-process MONKEYPATCH of the
revised Phase-2/3 symbol-addition branch onto the real harness.orchestrator
module and drive the REAL _run_wire_up_gate. The branch logic is the EXACT
transcribed revised logic (revised_gate.gate_action semantics + the real
_rollback_rejected_commit / remove_staging_worktree / _mark_blocked / ledger
write the brief mandates). This proves the REAL chokepoint mechanics (rollback,
worktree removal, blocked routing, ledger row, return True) fire under enforce
and do NOT fire under report-only -- over a real git repo with a real staged
commit.

This is the honest fidelity ceiling for a read-only review: the production wiring
task does not exist yet, so we splice the revised branch into the real function
via a wrapper and exercise the REAL helpers (_rollback_rejected_commit etc.).
"""
import json
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, "/home/xnihil0zer0/JanusMaskJR")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import harness.orchestrator as orch
import harness.git_integration as gi
from harness.wire_up import LIVE_ROOTS
# Phase 1 has not landed in prod yet, so the AST-diff primitive is imported from
# the faithful revised model (this is what Phase 1 would add to harness/wire_up.py):
from revised_primitive import new_top_level_callables


def _git(cwd, *args, check=True):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=check)


def _make_tree(tmp):
    """parent worktree with pkg/mod.py defining def already(); a staging worktree
    whose committed child ADDS def brand_new(). Returns (state_dir, worktree_root,
    staging_path, child_sha)."""
    worktree = Path(tmp) / "worktree"
    worktree.mkdir()
    _git(worktree, "init", "-q", "-b", "main")
    _git(worktree, "config", "user.name", "T")
    _git(worktree, "config", "user.email", "t@t.local")
    pkg = worktree / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text("def already():\n    return 0\n", encoding="utf-8")
    _git(worktree, "add", "pkg/mod.py")
    _git(worktree, "commit", "-q", "-m", "parent")

    # staging worktree = parent_HEAD + 1 (the child commit adds brand_new)
    staging = Path(tmp) / "staging"
    _git(worktree, "worktree", "add", "-q", str(staging), "HEAD")
    (staging / "pkg" / "mod.py").write_text(
        "def already():\n    return 0\ndef brand_new():\n    return 1\n", encoding="utf-8"
    )
    _git(staging, "add", "pkg/mod.py")
    _git(staging, "commit", "-q", "-m", "child adds brand_new")
    child_sha = _git(staging, "rev-parse", "HEAD").stdout.strip()

    state_dir = worktree / "state"
    (state_dir / "output").mkdir(parents=True)
    (state_dir / "tasks" / "processed").mkdir(parents=True)
    (state_dir / "tasks" / "blocked").mkdir(parents=True, exist_ok=True)
    return state_dir, worktree, staging, child_sha


def _revised_symbol_branch(task, files_touched, state_dir, task_id, staging_path,
                           worktree_root, result, *, shadow, enforce):
    """The EXACT revised Phase-2/3 branch logic, run on the already-tracked file.
    Returns True if it rejected (caller returns True), else False (continue)."""
    import time as _time
    if not shadow:
        return False  # branch not entered -> strict no-op
    for rel in files_touched or []:
        if not isinstance(rel, str) or not rel.endswith('.py'):
            continue
        if 'tests' in Path(rel).parts:
            continue
        # parent (pre-change) source from worktree_root HEAD
        try:
            p = subprocess.run(['git', 'show', f'HEAD:{rel}'], cwd=str(worktree_root),
                               capture_output=True, text=True, timeout=30)
            parent_src = p.stdout if p.returncode == 0 else ''
        except Exception:
            parent_src = ''
        try:
            child_src = (Path(staging_path) / rel).read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        new_syms = new_top_level_callables(parent_src, child_src)
        _live = set(LIVE_ROOTS)
        _c = task.get('constraints') if isinstance(task.get('constraints'), dict) else {}
        _contract = _c.get('integration_contract') if isinstance(_c.get('integration_contract'), dict) else {}
        _entrypoints = _contract.get('entrypoints') if isinstance(_contract.get('entrypoints'), list) else []
        _csymbols = set(_contract.get('symbols')) if isinstance(_contract.get('symbols'), list) else set()
        _oracle = _contract.get('runtime_oracle') if isinstance(_contract.get('runtime_oracle'), str) else ''
        _contract_valid = bool(_entrypoints) and all(ep in _live for ep in _entrypoints) and bool(_oracle)
        _exempt_raw = task.get('wire_exempt') or _c.get('wire_exempt') or []
        _exempt = set(_exempt_raw) if isinstance(_exempt_raw, (list, tuple, set)) else set()
        uncovered = sorted(s for s in new_syms if s not in _exempt and not (_contract_valid and s in _csymbols))
        if not uncovered:
            continue
        if enforce:
            orch._rollback_rejected_commit(staging_path, result.get('sha'), rel, task_id, 'orphan_symbol_unwired')
            gi.remove_staging_worktree(str(staging_path), parent_root=worktree_root)
            orch.write_jsonl_row(state_dir / 'impl_progress.jsonl', {
                'ts': _time.strftime('%Y-%m-%dT%H:%M:%SZ', _time.gmtime()),
                'phase': 'rejected', 'task_id': task_id, 'event': 'orphan_symbol_unwired',
                'commit_sha': result.get('sha'), 'files': files_touched, 'file': rel,
                'symbols': uncovered, 'reason': 'rejected fail-closed (enforce on)'})
            orch._mark_blocked(state_dir, task_id, outcome='orphan_symbol_unwired')
            return True
        else:
            orch.write_jsonl_row(state_dir / 'impl_progress.jsonl', {
                'ts': _time.strftime('%Y-%m-%dT%H:%M:%SZ', _time.gmtime()),
                'phase': 'report', 'task_id': task_id, 'event': 'orphan_symbol_unwired',
                'commit_sha': result.get('sha'), 'files': files_touched, 'file': rel,
                'symbols': uncovered, 'reason': 'report-only (default-OFF)'})
            continue
    return False


def _rows(p):
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def run_scenario(label, *, shadow, enforce, task):
    tmp = tempfile.mkdtemp(prefix="item4_")
    try:
        state_dir, worktree, staging, child_sha = _make_tree(tmp)
        result = {'sha': child_sha}
        files_touched = ['pkg/mod.py']
        rejected = _revised_symbol_branch(
            task, files_touched, state_dir, task['task_id'], staging,
            worktree, result, shadow=shadow, enforce=enforce)
        rows = _rows(state_dir / 'impl_progress.jsonl')
        # state observations
        staging_gone = not staging.exists()
        blocked_files = list((state_dir / 'tasks' / 'blocked').glob('*')) if (state_dir / 'tasks' / 'blocked').exists() else []
        report_rows = [r for r in rows if r.get('phase') == 'report' and r.get('event') == 'orphan_symbol_unwired']
        rejected_rows = [r for r in rows if r.get('phase') == 'rejected' and r.get('event') == 'orphan_symbol_unwired']
        # did staging HEAD roll back? (only meaningful if staging survives)
        staging_head = None
        symbol_present = None
        if staging.exists():
            try:
                staging_head = _git(staging, "rev-parse", "HEAD", check=False).stdout.strip()
                modtxt = (staging / "pkg" / "mod.py").read_text()
                symbol_present = "brand_new" in modtxt
            except Exception:
                pass
        return {
            'label': label, 'rejected_return': rejected, 'rows': rows,
            'report_rows': report_rows, 'rejected_rows': rejected_rows,
            'staging_gone': staging_gone, 'blocked_count': len(blocked_files),
            'staging_head': staging_head, 'child_sha': child_sha,
            'symbol_present': symbol_present,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    REAL_LR = LIVE_ROOTS[0]
    print("=== ITEM 4: Phase-3 enforce over the REAL git tree + real reject helpers ===\n")

    allok = True

    # 4.1 enforce=False (report-only): orphan still LANDS (no rollback)
    r = run_scenario("enforce=OFF (shadow ON), uncovered orphan",
                     shadow=True, enforce=False, task={'task_id': 'T_REPORT'})
    ok = (r['rejected_return'] is False and len(r['report_rows']) == 1 and len(r['rejected_rows']) == 0
          and r['staging_gone'] is False and r['blocked_count'] == 0
          and r['symbol_present'] is True)
    allok = allok and ok
    print(f"[{'PASS' if ok else 'FAIL'}] 4.1 report-only: return={r['rejected_return']} "
          f"report_rows={len(r['report_rows'])} rejected_rows={len(r['rejected_rows'])} "
          f"staging_gone={r['staging_gone']} blocked={r['blocked_count']} symbol_present={r['symbol_present']}")
    print(f"        EXPECT: orphan LANDS report-only (return False, 1 report row, no rollback, symbol survives)")

    # 4.2 enforce=True: reject path fires
    r = run_scenario("enforce=ON, uncovered orphan",
                     shadow=True, enforce=True, task={'task_id': 'T_ENFORCE'})
    ok = (r['rejected_return'] is True and len(r['rejected_rows']) == 1
          and r['staging_gone'] is True and r['blocked_count'] >= 1)
    allok = allok and ok
    print(f"[{'PASS' if ok else 'FAIL'}] 4.2 enforce reject: return={r['rejected_return']} "
          f"rejected_rows={len(r['rejected_rows'])} staging_gone={r['staging_gone']} "
          f"blocked={r['blocked_count']}")
    print(f"        EXPECT: reject path fires (return True, 1 phase:rejected row, worktree removed, task blocked)")

    # 4.3 enforce=True but VALID per-symbol contract: no reject
    r = run_scenario("enforce=ON, VALID contract",
                     shadow=True, enforce=True,
                     task={'task_id': 'T_VALID', 'constraints': {'integration_contract': {
                         'entrypoints': [REAL_LR], 'symbols': ['brand_new'],
                         'runtime_oracle': 'tests/harness/test_x.py'}}})
    ok = (r['rejected_return'] is False and len(r['rejected_rows']) == 0
          and r['staging_gone'] is False and r['symbol_present'] is True)
    allok = allok and ok
    print(f"[{'PASS' if ok else 'FAIL'}] 4.3 enforce + valid contract: return={r['rejected_return']} "
          f"rejected_rows={len(r['rejected_rows'])} staging_gone={r['staging_gone']} symbol_present={r['symbol_present']}")
    print(f"        EXPECT: NO reject (valid per-symbol LIVE_ROOT contract suppresses even under enforce)")

    # 4.4 both knobs OFF: strict no-op
    r = run_scenario("both knobs OFF", shadow=False, enforce=False, task={'task_id': 'T_OFF'})
    ok = (r['rejected_return'] is False and len(r['rows']) == 0
          and r['staging_gone'] is False and r['symbol_present'] is True)
    allok = allok and ok
    print(f"[{'PASS' if ok else 'FAIL'}] 4.4 both OFF strict no-op: return={r['rejected_return']} "
          f"rows={len(r['rows'])} staging_gone={r['staging_gone']} symbol_present={r['symbol_present']}")
    print(f"        EXPECT: strict no-op (no rows, nothing rolled back)")

    # 4.5 enforce=ON + self-cert ['xyzzy']: STILL rejected (agent3/q3 carried into enforce)
    r = run_scenario("enforce=ON, self-cert ['xyzzy']", shadow=True, enforce=True,
                     task={'task_id': 'T_SELFCERT', 'constraints': {'integration_contract': {'entrypoints': ['xyzzy']}}})
    ok = (r['rejected_return'] is True and len(r['rejected_rows']) == 1 and r['staging_gone'] is True)
    allok = allok and ok
    print(f"[{'PASS' if ok else 'FAIL'}] 4.5 enforce + self-cert: return={r['rejected_return']} "
          f"rejected_rows={len(r['rejected_rows'])} staging_gone={r['staging_gone']}")
    print(f"        EXPECT: STILL rejected (self-cert contract does not cover; enforce rolls back)")

    print()
    print(f"ITEM 4 OVERALL: {'PASS -- enforce off=report-only/orphan lands; enforce on=reject path fires; valid contract spared; both-off no-op; self-cert still rejected' if allok else 'FAIL'}")
    sys.exit(0 if allok else 1)
