"""Deterministic recipe gates for the overseer.

Each gate is a PURE function returning a typed :class:`GateResult`
``(ok, reason, fix_hint)`` over INJECTED seams or plain filesystem reads under
an injected ``state_dir``. No gate spawns a real process, model, network, or
un-injected subprocess -- the seams are always supplied by the caller. One gate
encodes one operator lesson.

Imports are stdlib-only, plus a guarded wrap of
``harness.planner.plan_validator.validate_plan`` (used only as the default
``validator`` for :func:`plan_preflight`; callers may inject their own).
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Mapping, Sequence
__all__ = ['GateResult', 'oracle_is_red', 'oracles_committed_at_head', 'brief_lint', 'plan_preflight', 'suite_green_zero_reg', 'posture_locked', 'wired']
try:
    from harness.planner.plan_validator import validate_plan as _validate_plan
except Exception:

    def _validate_plan(plan: Mapping[str, Any]) -> List[str]:
        """No-op fallback validator: reports no violations."""
        return []
validate_plan = _validate_plan

@dataclass
class GateResult:
    """Outcome of a single recipe gate.

    Attributes:
        ok: ``True`` when the gate passes.
        reason: Human-readable explanation of a failure (empty when ``ok``).
        fix_hint: Actionable remediation guidance (empty when ``ok``).
    """
    ok: bool
    reason: str
    fix_hint: str
_LINE_CITATION = re.compile('[\\w./\\\\-]+\\.\\w+:\\d+')
_TARGET_FILE = re.compile('[\\w./\\\\-]+\\.py\\b')

def oracle_is_red(test_path: str, *, run_seam: Callable[[str], int]) -> GateResult:
    """Assert the oracle test is RED (fails before implementation).

    ``run_seam`` executes the test and returns its exit code; a non-zero code
    means the test failed, i.e. it is RED -- which is what we require.
    """
    exit_code = run_seam(test_path)
    if exit_code != 0:
        return GateResult(ok=True, reason='', fix_hint='')
    return GateResult(ok=False, reason=f'oracle {test_path!r} is GREEN (exit 0); it must be RED first', fix_hint='A green oracle proves nothing -- write the test so it FAILS before the implementation exists.')

def oracles_committed_at_head(paths: Sequence[str], *, git_seam: Callable[[str], bool]) -> GateResult:
    """Assert every oracle path is committed at HEAD (not merely on disk).

    ``git_seam(path)`` answers whether ``path`` is tracked/committed at HEAD.
    """
    uncommitted = [p for p in paths if not git_seam(p)]
    if uncommitted:
        return GateResult(ok=False, reason='oracle(s) not committed at HEAD: ' + ', '.join(uncommitted), fix_hint='git add && git commit the oracle file(s) before promotion.')
    return GateResult(ok=True, reason='', fix_hint='')

def brief_lint(brief_text: str) -> GateResult:
    """Lint an operator brief.

    Checks (in order):
      * non-empty text with a markdown title heading,
      * no naked source line-number citations (e.g. ``file.py:123``),
      * a "Required plan shape" section is present,
      * exactly one target file is named.
    """
    text = brief_text or ''
    if not text.strip():
        return GateResult(ok=False, reason='brief is empty', fix_hint="Provide a title, a single target file, and a 'Required plan shape' section.")
    if not any((line.lstrip().startswith('#') for line in text.splitlines())):
        return GateResult(ok=False, reason='brief has no title heading', fix_hint="Start the brief with a markdown '# Title' heading.")
    if _LINE_CITATION.search(text):
        return GateResult(ok=False, reason='brief contains a naked source line-number citation', fix_hint='Cite code by structure/symbol, not by line number -- line numbers drift and leak the answer.')
    if 'required plan shape' not in text.lower():
        return GateResult(ok=False, reason="brief is missing the 'Required plan shape' section", fix_hint="Add a '# Required plan shape' section describing the expected task structurally.")
    targets = sorted(set(_TARGET_FILE.findall(text)))
    if len(targets) != 1:
        return GateResult(ok=False, reason=f'brief must name exactly one target file, found {len(targets)}', fix_hint='Scope the brief to a single target file.')
    return GateResult(ok=True, reason='', fix_hint='')

def plan_preflight(plan: Mapping[str, Any], *, state_dir: Any, validator: Callable[[Mapping[str, Any]], Sequence[str]]=validate_plan) -> GateResult:
    """Wrap the plan validator and add recipe-specific preflight checks.

    Order of checks:
      1. propagate any violations reported by ``validator``,
      2. reject generic/empty ``task_id`` (e.g. the placeholder ``'T1'``),
      3. reject collisions with an existing processed marker under ``state_dir``,
      4. require ``integration`` to be explicitly excluded in ``non_goals``,
      5. require at least two edge-case/regression tests.
    """
    violations = list(validator(plan) or [])
    if violations:
        return GateResult(ok=False, reason='plan_validator reported violations: ' + '; '.join((str(v) for v in violations)), fix_hint='Resolve every plan_validator violation, then retry.')
    task_id = str(plan.get('task_id', '') or '')
    if not task_id or task_id == 'T1':
        return GateResult(ok=False, reason=f'generic/empty task_id {task_id!r}; pick a descriptive task_id', fix_hint="Name the task after what it builds (e.g. 'build_foo'), not the placeholder 'T1'.")
    processed_marker = Path(state_dir) / 'tasks' / 'processed' / f'{task_id}.json'
    if processed_marker.exists():
        return GateResult(ok=False, reason=f'task_id {task_id!r} collides with an existing processed marker at {processed_marker}', fix_hint='Choose a fresh task_id; this one was already processed.')
    spec = plan.get('spec') or {}
    non_goals = spec.get('non_goals') or []
    if not any(('integration' in str(goal).lower() for goal in non_goals)):
        return GateResult(ok=False, reason='spec.non_goals must explicitly put integration out of scope', fix_hint="Add an explicit 'integration is out of scope' entry to spec.non_goals.")
    test_spec = spec.get('test_spec') or {}
    regression_tests = test_spec.get('regression_tests') or []
    if len(regression_tests) < 2:
        return GateResult(ok=False, reason=f'need at least two edge-case/regression tests, found {len(regression_tests)}', fix_hint='Specify two or more regression_tests covering edge cases.')
    return GateResult(ok=True, reason='', fix_hint='')

def suite_green_zero_reg(report: Mapping[str, Any]) -> GateResult:
    """Assert the oracle is GREEN and zero new regressions were introduced."""
    oracle_green = bool(report.get('oracle_green', False))
    new_regressions = int(report.get('new_regressions', 0) or 0)
    if not oracle_green:
        return GateResult(ok=False, reason='oracle is not GREEN; the implementation does not satisfy it', fix_hint='Make the oracle pass before promotion.')
    if new_regressions != 0:
        return GateResult(ok=False, reason=f'{new_regressions} new regression(s) introduced', fix_hint='Fix the regressions so the existing suite stays green.')
    return GateResult(ok=True, reason='', fix_hint='')

def wired(report: Mapping[str, Any]) -> GateResult:
    """Assert a wire report shows at least one live importer.

    Fails closed (``ok=False``) when ``report`` is not a mapping, when its
    ``'live_importers'`` value is empty, or when the key is absent entirely --
    an unmeasured or orphaned module must never pass. Passes when
    ``'live_importers'`` is a non-empty sequence.
    """
    if isinstance(report, Mapping):
        live_importers = report.get('live_importers')
        if isinstance(live_importers, Sequence) and (not isinstance(live_importers, (str, bytes))) and (len(live_importers) > 0):
            return GateResult(ok=True, reason='', fix_hint='')
    return GateResult(ok=False, reason='orphan: the module has no live importer', fix_hint='Add an import/call from a live module so the new module is reachable from a live entrypoint.')
def posture_locked(*, state_dir: Any) -> GateResult:
    """Assert the operational posture is fully locked down.

    Requires, under ``state_dir/control``:
      * the ``autowork/full_stop`` sentinel exists,
      * ``orchestrator.flag`` reads exactly ``pause``,
      * ``autowork/auto_promote.allowlist`` is deny-all (no non-comment,
        non-blank entries).

    Missing directories or files are handled gracefully (treated as failing /
    deny-all rather than raising).
    """
    control = Path(state_dir) / 'control'
    full_stop = control / 'autowork' / 'full_stop'
    flag_path = control / 'orchestrator.flag'
    allowlist_path = control / 'autowork' / 'auto_promote.allowlist'
    if not full_stop.exists():
        return GateResult(ok=False, reason='full_stop sentinel is missing', fix_hint=f'Create {full_stop} to halt autowork.')
    try:
        flag_value = flag_path.read_text().strip()
    except OSError:
        flag_value = ''
    if flag_value != 'pause':
        return GateResult(ok=False, reason=f"orchestrator.flag is {flag_value!r}, expected 'pause'", fix_hint=f"Write 'pause' to {flag_path}.")
    try:
        allowlist_lines = allowlist_path.read_text().splitlines()
    except OSError:
        allowlist_lines = []
    entries = [stripped for line in allowlist_lines if (stripped := line.strip()) and (not stripped.startswith('#'))]
    if entries:
        return GateResult(ok=False, reason='auto_promote.allowlist is not deny-all; entries: ' + ', '.join(entries), fix_hint='Remove every allowlist entry so auto-promote denies all.')
    return GateResult(ok=True, reason='', fix_hint='')
