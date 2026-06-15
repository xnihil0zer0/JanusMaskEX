---
interfaces: "ngv2/poc_repair_loop.py exposes `run_repair_loop(finding, target, *, runner=None, client=None, resolver=None, max_attempts=3, timeout_s=30.0, success_marker='VULNERABLE', expected_fs_signature='pwned_marker') -> RepairResult`, plus dataclasses `RepairResult` and `AttemptRecord`, and the `RunnerFn` alias."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/poc_repair_loop.py — generate->detonate->repair closed loop (P4.3)

# Scope

Build `ngv2/poc_repair_loop.py` as a NEW single-file, whole-file Python module
(IMPL-only; the oracle `tests/test_poc_repair_loop_wired.py` is ALREADY COMMITTED).
The closed loop wraps the live `ngv2.poc_writer.draft_poc` synthesis core with a
bounded `generate -> detonate -> observe -> repair` loop over an INJECTED runner
(default `ngv2.poc_runner_live.detonate_live`, the real bwrap jail). Each attempt
detonates the synthesized Python PoC; the loop STOPS on a strong-oracle `confirmed`
verdict; on a non-confirmed attempt the runner's stderr + fs-snapshot diff are
threaded back into the drafter as repair feedback and the loop retries up to
`max_attempts`. Harmless payloads only. working_dir: /home/xnihil0zer0/NobleGreedv2.

★ VERBATIM TRANSCRIPTION REQUIRED ★ — Emit the module as a BYTE-FOR-BYTE copy of the
embedded artifact below. Do NOT paraphrase, rename, reorder, re-indent, "improve", or
regenerate any line. Copy it exactly — every helper (`_default_runner`,
`_build_feedback`), the keyword-only signature, and `__all__`. A paraphrase risks the
committed oracle. The embedded text is the ONLY acceptable output:

```python
"""ngv2.poc_repair_loop -- the generate->detonate->repair closed loop (P4.3).

Wraps :func:`ngv2.poc_writer.draft_poc` with a bounded detonate->observe->repair
loop over an INJECTED runner (default :func:`ngv2.poc_runner_live.detonate_live`,
the real bwrap jail). On each attempt the Python PoC is detonated; the loop stops
on a strong-oracle ``confirmed`` verdict (marker on stdout AND the
``expected_fs_signature`` present in the fs-snapshot diff). On a non-confirmed
attempt the runner's stderr + fs-diff are threaded back into the drafter as repair
feedback and the loop retries up to ``max_attempts``. Harmless payloads only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from ngv2.contracts import Finding, Target
from ngv2.poc_writer import draft_poc, PoCArtifact

RunnerFn = Callable[..., dict]
DEFAULT_MARKER = "VULNERABLE"
DEFAULT_FS_SIGNATURE = "pwned_marker"


@dataclass
class AttemptRecord:
    """One generate->detonate observation."""
    attempt: int
    verdict: str
    exit_code: Optional[int]
    stdout: str
    stderr: str
    fs_diff: Any
    feedback: Optional[str] = None


@dataclass
class RepairResult:
    """The terminal outcome of the repair loop."""
    confirmed: bool
    attempts: int
    artifact: Optional["PoCArtifact"]
    report: Optional[dict]
    history: List[AttemptRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "confirmed": self.confirmed,
            "attempts": self.attempts,
            "verdict": (self.report or {}).get("verdict"),
            "history": [
                {"attempt": h.attempt, "verdict": h.verdict,
                 "exit_code": h.exit_code} for h in self.history
            ],
        }


def _default_runner(poc, target_spec, *, timeout_s, success_marker,
                    expected_fs_signature):
    from ngv2.poc_runner_live import detonate_live
    return detonate_live(
        poc, target_spec, timeout_s=timeout_s, success_marker=success_marker,
        expected_fs_signature=expected_fs_signature)


def _build_feedback(report: dict) -> str:
    stderr = (report.get("stderr") or "").strip()
    fs_diff = report.get("fs_snapshot_diff")
    exit_code = report.get("exit_code")
    return ("stderr: %s\nexit_code: %s\nfs-diff: %s"
            % (stderr or "<none>", exit_code, fs_diff if fs_diff else "<none>"))


def run_repair_loop(
    finding: Finding,
    target: Target,
    *,
    runner: Optional[RunnerFn] = None,
    client: Any = None,
    resolver=None,
    max_attempts: int = 3,
    timeout_s: float = 30.0,
    success_marker: str = DEFAULT_MARKER,
    expected_fs_signature: str = DEFAULT_FS_SIGNATURE,
) -> RepairResult:
    """Generate a PoC and detonate->repair until ``confirmed`` or budget spent.

    The injected ``runner`` (default the real bwrap ``detonate_live``) receives the
    synthesized Python PoC and the target spec, and must return the
    ``detonate_live`` dict shape ``{exit_code, stdout, stderr, fs_snapshot_diff,
    verdict?}``. Returns a :class:`RepairResult`.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    runner = runner or _default_runner
    target_spec = {"repo_root": target.repo_root}
    history: List[AttemptRecord] = []
    feedback: Optional[str] = None
    artifact: Optional[PoCArtifact] = None
    report: Optional[dict] = None

    for attempt in range(1, max_attempts + 1):
        artifact = draft_poc(finding, target, client=client, resolver=resolver,
                             feedback=feedback)
        report = runner(
            artifact.python, target_spec, timeout_s=timeout_s,
            success_marker=success_marker,
            expected_fs_signature=expected_fs_signature)
        verdict = report.get("verdict")
        history.append(AttemptRecord(
            attempt=attempt, verdict=str(verdict),
            exit_code=report.get("exit_code"), stdout=report.get("stdout", ""),
            stderr=report.get("stderr", ""),
            fs_diff=report.get("fs_snapshot_diff"), feedback=feedback))
        if verdict == "confirmed":
            return RepairResult(confirmed=True, attempts=attempt,
                                artifact=artifact, report=report, history=history)
        feedback = _build_feedback(report)

    return RepairResult(confirmed=False, attempts=max_attempts,
                        artifact=artifact, report=report, history=history)


__all__ = ["run_repair_loop", "RepairResult", "AttemptRecord", "RunnerFn"]
```

Verify with `.venv/bin/python -m pytest tests/test_poc_repair_loop_wired.py -q` (NO `cd`
prefix — verification runs in the staging worktree, where `_e2e_run/targets/`,
`ngv2/contracts.py`, `ngv2/poc_writer.py`, and `ngv2/poc_runner_live.py` are present).

# Non-Goals

No NEW integration tests are authored or required: the committed oracle
`tests/test_poc_repair_loop_wired.py` IS the integration test (it drives the full
`run_repair_loop` over an injected runner across all five live patterns and asserts
the repair-feedback threading + wiring to the live `ngv2.poc_writer` and
`ngv2.poc_runner_live.detonate_live` seams). Integration testing is therefore EXCUSED
here — the plan needs no additional `integration_tests` entry. No live detonation in
this module's own tests (the oracle injects the runner). No new
third-party imports (stdlib + ngv2 only). No tests authored (oracle already committed).
Must bind to the LIVE `ngv2.poc_writer.draft_poc` (do not re-implement synthesis) and
keep `ngv2.poc_runner_live.detonate_live` as the default runner (imported lazily inside
`_default_runner`). Harmless payloads only.

# Inputs

The NobleGreedv2 repo at working_dir, with: the committed `Finding`/`Target`/`PoC`
shapes in `ngv2/contracts.py`; the live `ngv2/poc_writer.py` exposing
`draft_poc(finding, target, *, client=None, resolver=None, feedback=None) -> PoCArtifact`
(a `PoCArtifact` has `.python` (a `PoC`), `.node`, `.marker`, `.fs_signature`, `.cwe`,
`.grounding`); the live `ngv2/poc_runner_live.py` exposing
`detonate_live(poc, target_spec, *, timeout_s, success_marker, expected_fs_signature)
-> dict` returning `{exit_code, stdout, stderr, duration_ms, fs_snapshot_diff, verdict?}`;
the 5 synthetic targets at `_e2e_run/targets/<pattern>/svc.py`; and the committed oracle
`tests/test_poc_repair_loop_wired.py`.

# Deliverables

One NEW single-file whole-file module `ngv2/poc_repair_loop.py` exactly as the embedded
artifact above, passing `tests/test_poc_repair_loop_wired.py`.
