"""ngv2.poc_repair_loop -- bounded generate->detonate->observe->repair loop (P4.3).

This module wires the live PoC synthesizer (``ngv2.poc_writer.draft_poc``) to a
detonation runner and drives a closed feedback loop: synthesize a proof-of-concept,
detonate it, observe the verdict, and -- if the exploit is not confirmed -- thread
the observed stderr / exit code / filesystem diff back into the synthesizer as
``feedback`` for another attempt, up to ``max_attempts`` times.

The detonation seam is injectable so the loop can be exercised hermetically; when no
runner is supplied the default dispatches to the production bwrap jail seam
(``ngv2.poc_runner_live.detonate_live``), imported lazily to avoid pulling the jail
into the import graph at module load time.
"""
from __future__ import annotations
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from ngv2.poc_writer import draft_poc
DEFAULT_MARKER = 'VULNERABLE'
DEFAULT_FS_SIGNATURE = 'pwned_marker'
RunnerFn = Callable[..., dict]
__all__ = ['run_repair_loop', 'RepairResult', 'AttemptRecord', 'RunnerFn']

@dataclass
class AttemptRecord:
    """One synthesize->detonate cycle within the repair loop."""
    attempt: int
    verdict: Optional[str]
    exit_code: Optional[int]
    stdout: str
    stderr: str
    fs_diff: Any
    feedback: Optional[str] = None

@dataclass
class RepairResult:
    """Aggregate outcome of a bounded repair loop."""
    confirmed: bool
    attempts: int
    artifact: Any
    report: Dict[str, Any]
    history: List[AttemptRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {'confirmed': self.confirmed, 'attempts': self.attempts, 'verdict': self.report.get('verdict') if self.report else None, 'history': [{'attempt': h.attempt, 'verdict': h.verdict, 'exit_code': h.exit_code} for h in self.history]}

def _default_runner(poc: Any, target_spec: Dict[str, Any], *, timeout_s: float, success_marker: str, expected_fs_signature: str) -> dict:
    """Detonate ``poc`` against the production bwrap jail seam.

    The jail module is imported lazily so importing this loop does not eagerly
    pull ``ngv2.poc_runner_live`` (and its heavyweight detonation machinery).
    """
    from ngv2.poc_runner_live import detonate_live
    return detonate_live(poc, target_spec, timeout_s=timeout_s, success_marker=success_marker, expected_fs_signature=expected_fs_signature)

def _build_feedback(report: Dict[str, Any]) -> str:
    """Render a detonation ``report`` into repair feedback for the synthesizer."""
    stderr = report.get('stderr') or '<none>'
    exit_code = report.get('exit_code')
    exit_code = '<none>' if exit_code is None else exit_code
    stdout = report.get('stdout') or '<none>'
    fs_diff = report.get('fs_snapshot_diff') or '<none>'
    feedback_str = 'stderr: %s\nexit_code: %s\nstdout: %s\nfs-diff: %s' % (stderr, exit_code, stdout, fs_diff)
    coverage = report.get('coverage')
    if coverage:
        warmer_lines = []
        for item in coverage:
            if isinstance(item, dict):
                text = item.get('text', '')
                executed = item.get('executed')
            elif isinstance(item, (tuple, list)):
                text = item[1] if len(item) > 1 else ''
                executed = item[2] if len(item) > 2 else False
            else:
                text = ''
                executed = False
            status = 'EXECUTED' if executed else 'NOT EXECUTED'
            warmer_lines.append('%s  # %s' % (text, status))
        if warmer_lines:
            feedback_str += '\n' + '\n'.join(warmer_lines)
    return feedback_str

def run_repair_loop(finding: Any, target: Any, *, runner: Optional[RunnerFn]=None, client: Any=None, resolver: Any=None, max_attempts: int=3, timeout_s: float=30.0, success_marker: str=DEFAULT_MARKER, expected_fs_signature: str=DEFAULT_FS_SIGNATURE, refine_cap: int=2) -> RepairResult:
    """Drive a bounded generate->detonate->observe->repair loop.

    Each attempt synthesizes a PoC via the live ``draft_poc`` (threading any prior
    failure's feedback back in), detonates it through ``runner`` (defaulting to the
    production jail), and stops as soon as the verdict is ``"confirmed"``. If the
    budget is exhausted without confirmation, the last artifact/report and the full
    attempt history are returned with ``confirmed=False``.
    """
    if max_attempts < 1:
        raise ValueError('max_attempts must be >= 1')
    if runner is None:
        runner = _default_runner
    target_spec = {'repo_root': target.repo_root}
    feedback: Optional[str] = None
    history: List[AttemptRecord] = []
    artifact: Any = None
    report: Dict[str, Any] = {}
    malformed_count = 0
    consecutive_refines = 0
    for attempt in range(1, max_attempts + 1):
        if consecutive_refines >= refine_cap:
            feedback = None
            consecutive_refines = 0
        if feedback is not None:
            honesty = 'if the target is unexploitable, say so explicitly'
            if honesty not in feedback:
                feedback += f'\n{honesty}'
        artifact = draft_poc(finding, target, client=client, resolver=resolver, feedback=feedback)
        is_malformed = False
        if artifact is None:
            is_malformed = True
        elif not hasattr(artifact, 'python'):
            is_malformed = True
        else:
            python_val = artifact.python
            if not python_val:
                is_malformed = True
            else:
                if isinstance(python_val, str):
                    code_str = python_val
                elif hasattr(python_val, 'code'):
                    code_str = python_val.code
                elif isinstance(python_val, dict) and 'code' in python_val:
                    code_str = python_val['code']
                else:
                    code_str = str(python_val)
                if not code_str:
                    is_malformed = True
                else:
                    try:
                        ast.parse(code_str)
                    except Exception:
                        is_malformed = True
        if is_malformed:
            malformed_count += 1
            history.append(AttemptRecord(attempt=attempt, verdict='malformed', exit_code=None, stdout='', stderr='', fs_diff=[], feedback=feedback))
            if malformed_count >= 3:
                return RepairResult(confirmed=False, attempts=attempt, artifact=artifact, report=report, history=history)
            if feedback is not None:
                consecutive_refines += 1
            else:
                consecutive_refines = 0
            continue
        poc = artifact.python
        report = runner(poc, target_spec, timeout_s=timeout_s, success_marker=success_marker, expected_fs_signature=expected_fs_signature)
        verdict = report.get('verdict')
        history.append(AttemptRecord(attempt=attempt, verdict=verdict, exit_code=report.get('exit_code'), stdout=report.get('stdout'), stderr=report.get('stderr'), fs_diff=report.get('fs_snapshot_diff'), feedback=feedback))
        if verdict == 'confirmed':
            return RepairResult(confirmed=True, attempts=attempt, artifact=artifact, report=report, history=history)
        if feedback is not None:
            consecutive_refines += 1
        else:
            consecutive_refines = 0
        feedback = _build_feedback(report)
    return RepairResult(confirmed=False, attempts=max_attempts, artifact=artifact, report=report, history=history)
import ast