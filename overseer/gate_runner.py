"""overseer/gate_runner.py -- production resolver: phase gate-label -> real check.

make_default_gate_runner returns gate_runner(mode, phase, rec, state_dir) that
turn_runner.run_chat_turn calls each turn to decide whether the procedure may
advance. Backed gates run the real overseer.gates functions on inputs gathered
from rec['procedure_artifacts'] + injected seams (pytest/git) or state_dir;
derived gates use status/pending/pushed seams; judgment gates pass only when
rec['procedure_attested'][phase] is true. A backed gate with no recorded
artifact fails with an actionable hint (never silent-pass).
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path
from typing import Callable, Optional
from overseer.gates import GateResult, oracle_is_red, oracles_committed_at_head, brief_lint, plan_preflight, suite_green_zero_reg, posture_locked
from overseer.procedure import PROCEDURE_REGISTRY
_ATTESTED_LABELS = {'scope_locked', 'oracle_present', 'oracle_drafted', 'staged', 'built', 'restored', 'daemon_observed', 'daemon_healthy', 'reconciled', 'reported'}

def gate_label_for(mode: str, phase: str) -> Optional[str]:
    """Resolve a (mode, phase) to the phase's gate NAME, or None."""
    proc = PROCEDURE_REGISTRY.get(mode)
    if proc is None:
        return None
    for p in proc.phases:
        if p.name == phase:
            return p.gate
    return None

def _missing(what: str, hint: str) -> GateResult:
    return GateResult(ok=False, reason='no %s recorded for this phase' % what, fix_hint=hint)

def _default_run_seam(repo_root) -> Callable[[str], int]:

    def run(test_path: str) -> int:
        try:
            return subprocess.run(['python', '-m', 'pytest', test_path, '-q'], cwd=str(repo_root), capture_output=True).returncode
        except OSError:
            return 1
    return run

def _default_git_seam(repo_root) -> Callable[[str], bool]:

    def committed(path: str) -> bool:
        try:
            return subprocess.run(['git', 'ls-files', '--error-unmatch', path], cwd=str(repo_root), capture_output=True).returncode == 0
        except OSError:
            return False
    return committed

def _default_status_seam(repo_root) -> Callable[[], bool]:

    def clean() -> bool:
        try:
            out = subprocess.run(['git', 'status', '--porcelain'], cwd=str(repo_root), capture_output=True, text=True)
            return out.returncode == 0 and out.stdout.strip() == ''
        except OSError:
            return False
    return clean

def _default_pending_seam(state_dir) -> Callable[[], int]:

    def count() -> int:
        try:
            return len(list((Path(state_dir) / 'tasks').glob('*.json')))
        except OSError:
            return 0
    return count

def _default_pushed_seam(repo_root) -> Callable[[], bool]:

    def pushed() -> bool:
        try:
            out = subprocess.run(['git', 'rev-list', '--count', 'origin/master..HEAD'], cwd=str(repo_root), capture_output=True, text=True)
            return out.returncode == 0 and out.stdout.strip() == '0'
        except OSError:
            return False
    return pushed

def make_default_gate_runner(repo_root, state_dir, *, run_seam=None, git_seam=None, status_seam=None, pending_seam=None, pushed_seam=None):
    """Build the production gate_runner(mode, phase, rec, state_dir) -> GateResult."""
    from overseer.gates import wired
    run_seam = run_seam or _default_run_seam(repo_root)
    git_seam = git_seam or _default_git_seam(repo_root)
    status_seam = status_seam or _default_status_seam(repo_root)
    pending_seam = pending_seam or _default_pending_seam(state_dir)
    pushed_seam = pushed_seam or _default_pushed_seam(repo_root)

    def _run_gate(label, arts, attested, sd) -> GateResult:
        if label is None:
            return GateResult(ok=False, reason='unknown phase/mode (no gate)', fix_hint='Check the procedure registry.')
        if label == 'oracle_is_red':
            path = arts.get('oracle_path')
            if not path:
                return _missing('oracle', 'Draft + record the oracle (procedure_artifacts.oracle_path).')
            return oracle_is_red(path, run_seam=run_seam)
        if label == 'oracle_committed':
            paths = arts.get('oracle_paths') or ([arts['oracle_path']] if arts.get('oracle_path') else [])
            if not paths:
                return _missing('oracle path', 'Record the committed oracle path(s).')
            return oracles_committed_at_head(paths, git_seam=git_seam)
        if label == 'brief_written':
            text = arts.get('brief_text')
            if text is None and arts.get('brief_path'):
                try:
                    text = Path(arts['brief_path']).read_text(encoding='utf-8')
                except OSError:
                    text = None
            if text is None:
                return _missing('brief', 'Write + record the brief (procedure_artifacts.brief_path).')
            return brief_lint(text)
        if label == 'plan_ready':
            plan = arts.get('plan')
            if plan is None and arts.get('plan_path'):
                try:
                    plan = json.loads(Path(arts['plan_path']).read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    plan = None
            if plan is None:
                return _missing('plan', 'Produce + record the plan (procedure_artifacts.plan_path).')
            return plan_preflight(plan, state_dir=sd)
        if label == 'verified':
            report = arts.get('report')
            if report is None:
                return _missing('verification report', 'Run the oracle + record the report.')
            return suite_green_zero_reg(report)
        if label == 'wired':
            report = arts.get('wire_report')
            if report is None:
                return _missing('wire report', 'Run check_wired + record the report (procedure_artifacts.wire_report).')
            return wired(report)
        if label == 'posture_ok':
            return posture_locked(state_dir=sd)
        if label in ('preflight_clean', 'swept'):
            if status_seam():
                return GateResult(ok=True, reason='', fix_hint='')
            return GateResult(ok=False, reason='working tree is not clean', fix_hint='Commit or stash stray changes.')
        if label == 'registry_zeroed':
            n = pending_seam()
            if n == 0:
                return GateResult(ok=True, reason='', fix_hint='')
            return GateResult(ok=False, reason='%d task(s) still queued' % n, fix_hint='Drain or clear the task registry.')
        if label == 'pushed':
            if pushed_seam():
                return GateResult(ok=True, reason='', fix_hint='')
            return GateResult(ok=False, reason='HEAD is not pushed to origin', fix_hint='git push, then re-check.')
        if label in _ATTESTED_LABELS:
            if attested:
                return GateResult(ok=True, reason='', fix_hint='')
            return GateResult(ok=False, reason='awaiting operator confirmation of gate %r' % label, fix_hint='Confirm this step is done to advance.')
        return GateResult(ok=False, reason='unrecognized gate %r' % label, fix_hint='Add a handler for this gate.')

    def gate_runner(mode, phase, rec, state_dir_arg=None):
        sd = state_dir_arg if state_dir_arg is not None else state_dir
        label = gate_label_for(mode, phase)
        arts = (rec or {}).get('procedure_artifacts') or {}
        attested = ((rec or {}).get('procedure_attested') or {}).get(phase, False)
        return _run_gate(label, arts, attested, sd)
    return gate_runner