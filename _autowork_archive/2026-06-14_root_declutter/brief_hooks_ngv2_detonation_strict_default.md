---
dependencies: []
interfaces: "edits ngv2/detonation.py DetonationChamber.detonate weak-default branch so a marker-only clean run with no expected_fs_signature resolves to 'inconclusive' (never 'confirmed') — confirmation now requires the semantic oracle (marker AND fs effect)"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
verification_command: ".venv/bin/python -m pytest tests/test_detonation.py tests/test_pipeline.py tests/test_poc_runner.py tests/test_handlers_wired.py tests/ngv2/test_detonation_requires_semantic_oracle_wired.py tests/ngv2/test_detonation_semantic_gate_wired.py tests/ngv2/test_detonation_chamber_semantic_gate_wired.py tests/ngv2/test_poc_runner_live_smoke.py -q"
---

# Title

ngv2/detonation.py — STRICT default: marker-only clean run with no expected_fs_signature is 'inconclusive', never 'confirmed' (close the marker-spoof hole)

# Scope

EDIT the EXISTING module `ngv2/detonation.py` in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). The ONLY behavioral change vs the current file is in the `expected_fs_signature is None` weak-default branch of `DetonationChamber.detonate`: today it returns `verdict='confirmed'` when `exit_code == 0 AND self.success_marker in stdout` (marker-spoofing ALONE, NO filesystem-effect evidence). Under the owner's STRICT DEFAULT, a `'confirmed'` verdict MUST require the strong semantic oracle (marker AND fs effect, via the `expected_fs_signature` path), so a marker-only clean run with no fs evidence MUST resolve to `'inconclusive'`. The new weak-default mapping is: nonzero exit -> `'refuted'`; otherwise (exit0 with or without the marker; exit_code None) -> `'inconclusive'`; runner raises -> `'error'` LiveTestReport (preserved). The top-level `semantic_verdict` helper and the entire fs-verification path (string `expected_fs_signature` -> delegate to `semantic_verdict`) are PRESERVED UNCHANGED.

This is a whole-file replacement of a SHORT module. The complete VALIDATED file content is embedded below (oracle-proven green against the full anti-seesaw union) — ship `ngv2/detonation.py` EXACTLY as the whole file below, byte-for-byte. Do NOT restructure, do NOT change `semantic_verdict`, do NOT change `detonate`'s signature, and do NOT touch the fs-verification (string-signature) path.

meta_task_type=`refactor`. # Required plan shape: EXACTLY ONE impl task (no decomposition — this is a tiny whole-file edit), meta_task_type=refactor, files_touched=[`ngv2/detonation.py`]; integration tests EXCUSED via Non-Goals; author NO new tests — the committed oracles are authoritative. The plan's `spec.edge_cases` MUST mirror into `test_spec.regression_tests` by NAME referencing already-committed oracle tests (do NOT author them): set `regression_tests` to at least these two existing tests — `test_marker_only_is_inconclusive_when_no_fs_signature_requested` (marker-only, no fs sig → 'inconclusive') and `test_marker_and_fs_signature_present_is_confirmed` (fs evidence → 'confirmed'). verification_command exactly as in the front-matter (the full anti-seesaw union of all eight oracle files).

# Non-Goals

This is an EDIT and integration is out of scope — the literal word integration: do NOT add integration/e2e tests, do NOT author or modify any test (the committed oracles below are authoritative). Do NOT change `semantic_verdict`'s signature or behavior. Do NOT change `detonate`'s signature `(self, poc, target_spec, runner, *, expected_fs_signature=None) -> LiveTestReport`. Do NOT change the fs-verification path (the `expected_fs_signature` is-a-string branch) at all. Do NOT change the runner-exception -> error LiveTestReport path. Do NOT modify `ngv2/pipeline.py`, `ngv2/poc_runner.py`, `ngv2/poc_runner_live.py`, `ngv2/handlers.py`, `ngv2/contracts.py`, or any module other than `ngv2/detonation.py`. Do NOT import `poc_runner_live` or perform any real fork/execve/subprocess/network/clock/random work — the runner stays an injected seam. stdlib + ngv2 only.

# Inputs

The current `ngv2/detonation.py` (a short module: a `from ngv2.contracts import PoC, LiveTestReport` line, the pure top-level `semantic_verdict(...)` function, and the `DetonationChamber` class with `__init__` and `detonate`). The relevant existing weak-default block inside `detonate` (only reached when `expected_fs_signature is None`, after the runner-exception try/except) currently maps `exit0+marker -> 'confirmed'`, `nonzero -> 'refuted'`, `else -> 'inconclusive'`. The committed authoritative oracles (ALL must pass together — anti-seesaw union, also named in the verification_command): `tests/test_detonation.py`, `tests/test_pipeline.py`, `tests/test_poc_runner.py`, `tests/test_handlers_wired.py`, `tests/ngv2/test_detonation_requires_semantic_oracle_wired.py`, `tests/ngv2/test_detonation_semantic_gate_wired.py`, `tests/ngv2/test_detonation_chamber_semantic_gate_wired.py`, `tests/ngv2/test_poc_runner_live_smoke.py`. They assert: marker-only + no expected_fs_signature -> 'inconclusive' (NOT 'confirmed'); exit0+no-marker -> 'inconclusive'; nonzero exit -> 'refuted'; runner raises -> 'error'; and the fs-verification path (string signature) still 'confirmed'/'refuted'/'error' via semantic_verdict. (NOTE: this leaf is dispatched AFTER the pipeline-threading leaf is merged, so `ngv2/pipeline.py` already threads expected_fs_signature and the pipeline confirmed-flow test is green via the fs path.) stdlib + ngv2 only.

# Deliverables

Replace the WHOLE file `ngv2/detonation.py` with EXACTLY this VALIDATED content (oracle-proven green against the full union):

```python
from ngv2.contracts import PoC, LiveTestReport

def semantic_verdict(exit_code, stdout: str, stderr: str, fs_snapshot_diff: str, *, success_marker: str, expected_fs_signature: str) -> str:
    """Pure Semantic-Oracle verdict over an injected runner result.

    Upgrades the weak exit-code+grep gate: a detonation is only ``'confirmed'``
    when the process exited cleanly (``exit_code == 0``), emitted the
    ``success_marker`` on stdout or stderr, AND mutated the filesystem in a way
    whose ``expected_fs_signature`` shows up in ``fs_snapshot_diff``.

    A nonzero ``exit_code`` always dominates and yields ``'error'`` -- even if
    the marker and FS signature are both present. An ``exit_code`` of ``0`` or
    ``None`` that does not clear the confirmed bar yields ``'refuted'``.

    This function is pure: no I/O, no clock, no randomness; the same inputs
    always produce the same verdict.
    """
    if exit_code is not None and exit_code != 0:
        return 'error'
    if exit_code == 0 and (success_marker in stdout or success_marker in stderr) and (expected_fs_signature in fs_snapshot_diff):
        return 'confirmed'
    return 'refuted'
class DetonationChamber:
    """Deterministic orchestrator that detonates a PoC over an injected runner.

    The exploit is treated purely as data: the ``runner`` callable is injected
    by the caller and is responsible for whatever (mocked) execution happens.
    This class never spawns a real subprocess or touches the network; it simply
    maps the runner's outcome onto a :class:`LiveTestReport` verdict.
    """

    def __init__(self, success_marker: str='VULNERABLE') -> None:
        self.success_marker = success_marker

    def detonate(self, poc, target_spec, runner, *, expected_fs_signature=None) -> LiveTestReport:
        if expected_fs_signature is None:
            # Weak-gate (default) path -- STRICT: confirmation requires the
            # semantic oracle (marker AND fs effect), so a marker-only clean run
            # can never be 'confirmed' here.
            try:
                exit_code, stdout, stderr, duration_ms = runner(poc, target_spec)
            except Exception as exc:
                return LiveTestReport(
                    poc_finding_id=poc.finding_id,
                    verdict="error",
                    exit_code=None,
                    stdout="",
                    stderr=str(exc),
                    duration_ms=0,
                )
            if exit_code is not None and exit_code != 0:
                verdict = "refuted"
            else:
                # STRICT default: with no expected_fs_signature there is no
                # filesystem-effect evidence, so a marker-only clean run can
                # never be 'confirmed' -- it resolves to 'inconclusive'.
                verdict = "inconclusive"
            return LiveTestReport(
                poc_finding_id=poc.finding_id,
                verdict=verdict,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
            )

        # fs-verification path: route the verdict through the strong
        # Semantic-Oracle gate over an fs_snapshot_diff drawn from the runner
        # result. Accept either a 4-tuple (no fs evidence -> empty diff) or a
        # 5-tuple (5th element is the fs diff).
        result = runner(poc, target_spec)
        exit_code = result[0]
        stdout = result[1]
        stderr = result[2]
        duration_ms = result[3]
        fs_snapshot_diff = result[4] if len(result) >= 5 else ""
        verdict = semantic_verdict(
            exit_code,
            stdout,
            stderr,
            fs_snapshot_diff,
            success_marker=self.success_marker,
            expected_fs_signature=expected_fs_signature,
        )
        return LiveTestReport(
            poc_finding_id=poc.finding_id,
            verdict=verdict,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
        )
```

Verified GREEN by the verification_command (the full anti-seesaw union of all eight affected oracle files passing together).
