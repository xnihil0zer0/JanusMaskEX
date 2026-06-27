from ngv2.contracts import PoC
from ngv2.contracts import LiveTestReport

def semantic_verdict(exit_code, stdout: str, stderr: str, fs_snapshot_diff: str, *, success_marker: str, expected_fs_signature: str, nonce: str='') -> str:
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
    if not expected_fs_signature or not expected_fs_signature.strip():
        return 'refuted'
    if nonce:
        if nonce not in stdout and nonce not in stderr or nonce not in fs_snapshot_diff:
            return 'refuted'
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

    def detonate(self, poc: PoC, target_spec, runner, *, expected_fs_signature=None) -> LiveTestReport:
        """Detonate ``poc`` over the injected ``runner`` and map its result to a
        deterministic :class:`LiveTestReport`.

        Confirmation is reserved for the strong semantic oracle: a ``'confirmed'``
        verdict requires BOTH the success marker AND an expected filesystem-effect
        signature, and is reachable only through the fs-verification path
        (``expected_fs_signature`` is a string).

        When ``expected_fs_signature is None`` (the STRICT default) the gate is
        marker-spoof-proof: a nonzero exit is ``'refuted'``; every other clean or
        inconclusive outcome (exit 0 with or without the marker, or ``exit_code``
        ``None``) is ``'inconclusive'`` and never ``'confirmed'``.
        """
        try:
            result = runner(poc, target_spec)
        except Exception as exc:
            return LiveTestReport(poc_finding_id=poc.finding_id, verdict='error', exit_code=None, stdout='', stderr=str(exc), duration_ms=0)
        exit_code = result[0]
        stdout = result[1]
        stderr = result[2]
        duration_ms = result[3]
        if expected_fs_signature is None:
            if exit_code is not None and exit_code != 0:
                verdict = 'refuted'
            else:
                verdict = 'inconclusive'
        else:
            fs_snapshot_diff = result[4] if len(result) > 4 else ''
            verdict = semantic_verdict(exit_code, stdout, stderr, fs_snapshot_diff, success_marker=self.success_marker, expected_fs_signature=expected_fs_signature)
        return LiveTestReport(poc_finding_id=poc.finding_id, verdict=verdict, exit_code=exit_code, stdout=stdout, stderr=stderr, duration_ms=duration_ms)