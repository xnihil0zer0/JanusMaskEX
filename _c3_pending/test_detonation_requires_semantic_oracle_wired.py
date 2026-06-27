"""RED oracle for ngv2/detonation.py — C-3: the strong semantic detonation
gate is the DEFAULT; the weak marker-only path must REFUSE to ``'confirmed'``.

DEFECT under test (verified live 2026-06-11):
``DetonationChamber.detonate``'s default branch (``expected_fs_signature is
None``) returns ``verdict='confirmed'`` on ``exit_code == 0`` AND
``success_marker in stdout`` ALONE — with NO filesystem-effect evidence. A PoC
that merely PRINTS the marker (spoofing) without exploiting anything is thus
accepted. The strong ``semantic_verdict`` (which additionally requires
``expected_fs_signature in fs_snapshot_diff``) only runs when a caller passes
the signature; the live pipeline (``ngv2/pipeline.py`` -> ``detonate(...)``
without ``expected_fs_signature``) takes the weak path.

FIX the blind worker MUST build (pinned by this oracle):
In ``DetonationChamber.detonate``, when ``expected_fs_signature is None`` the
marker-only + exit0 path MUST NOT return ``'confirmed'`` — a ``'confirmed'``
verdict REQUIRES the semantic oracle (marker AND filesystem signature). The
marker-only clean run instead resolves to ``'inconclusive'`` (no FS evidence to
confirm against). Every OTHER weak-path outcome is preserved verbatim:
  * nonzero exit -> ``'refuted'``
  * exit0, no marker -> ``'inconclusive'``
  * runner raises -> ``'error'``
The fs-verification path (``expected_fs_signature`` is a string) is UNCHANGED:
it still delegates to ``semantic_verdict`` (confirmed / refuted / error).

This forces every ``'confirmed'`` through real-effect evidence.

Verdict vocabulary (exact strings, from the module): 'confirmed', 'refuted',
'inconclusive', 'error'.

WIRING: drives the live ``ngv2.detonation.DetonationChamber`` over the real
``ngv2.poc_runner`` injected-runner seam, proving the edited module is reachable.
The strong ``semantic_verdict`` is used as a differential reference and MUST be
left untouched by this leaf.
meta_task_type: data_model (EDIT to an existing module; integration excused via
the brief's Non-Goals).
"""
import pytest

from ngv2.contracts import PoC, LiveTestReport
from ngv2.poc_runner import make_mock_runner
from ngv2.detonation import DetonationChamber, semantic_verdict


MARKER = "VULNERABLE"
FS_SIG = "M poc_artifact.txt"


def _poc(finding_id="F1"):
    return PoC(
        finding_id=finding_id,
        language="python",
        code="print('VULNERABLE')",
        entrypoint="main",
    )


def _fs_runner(exit_code, stdout, stderr, duration_ms, fs_snapshot_diff):
    """A 5-tuple runner carrying an ``fs_snapshot_diff`` as the 5th element."""

    def runner(poc, target_spec):
        return (exit_code, stdout, stderr, duration_ms, fs_snapshot_diff)

    return runner


# --- THE CORE FIX: marker-only (no fs evidence) MUST NOT confirm -------------

def test_marker_only_no_fs_signature_is_not_confirmed():
    """exit0 + marker, expected_fs_signature=None -> NOT 'confirmed'.

    RED today: the weak default returns 'confirmed' on marker-spoof alone. After
    the fix a 'confirmed' verdict REQUIRES the semantic oracle (marker AND fs
    signature), so a marker-only clean run resolves to 'inconclusive'.
    """
    chamber = DetonationChamber(success_marker=MARKER)
    runner = make_mock_runner(exit_code=0, stdout="proof: VULNERABLE here", stderr="", duration_ms=5)
    report = chamber.detonate(_poc(), {"host": "x"}, runner)  # no expected_fs_signature
    assert isinstance(report, LiveTestReport)
    assert report.verdict != "confirmed"
    assert report.verdict == "inconclusive"
    assert report.poc_finding_id == "F1"
    assert report.exit_code == 0


def test_marker_in_stdout_alone_never_yields_confirmed_via_weak_path():
    """Differential: the weak default path may never return what only the strong
    oracle (with both marker AND fs signature) is entitled to return."""
    chamber = DetonationChamber(success_marker=MARKER)
    runner = make_mock_runner(exit_code=0, stdout="VULNERABLE", stderr="", duration_ms=11)
    weak_report = chamber.detonate(_poc(), {}, runner)  # no fs signature
    strong = semantic_verdict(
        0, "VULNERABLE", "", FS_SIG,
        success_marker=MARKER, expected_fs_signature=FS_SIG,
    )
    assert strong == "confirmed"
    # the weak path must NOT be able to reach 'confirmed' without fs evidence
    assert weak_report.verdict != strong


# --- the strong path still confirms when fs evidence is present -------------

def test_marker_and_matching_fs_signature_is_confirmed():
    chamber = DetonationChamber(success_marker=MARKER)
    runner = _fs_runner(0, "ran: VULNERABLE", "", 9, "M poc_artifact.txt\nA loot")
    report = chamber.detonate(_poc(), {"host": "x"}, runner, expected_fs_signature=FS_SIG)
    assert report.verdict == "confirmed"
    assert report.exit_code == 0
    assert report.duration_ms == 9


def test_marker_and_nonmatching_fs_signature_is_refuted():
    chamber = DetonationChamber(success_marker=MARKER)
    runner = _fs_runner(0, "ran: VULNERABLE", "", 4, "M unrelated_file.txt")
    report = chamber.detonate(_poc(), {"host": "x"}, runner, expected_fs_signature=FS_SIG)
    assert report.verdict == "refuted"


# --- non-confirming weak-path outcomes are preserved ------------------------

def test_nonzero_exit_weak_path_is_refuted():
    chamber = DetonationChamber(success_marker=MARKER)
    runner = make_mock_runner(exit_code=2, stdout="", stderr="crash", duration_ms=1)
    report = chamber.detonate(_poc(), {}, runner)
    assert report.verdict == "refuted"
    assert report.exit_code == 2


def test_exit0_no_marker_weak_path_is_inconclusive():
    chamber = DetonationChamber(success_marker=MARKER)
    runner = make_mock_runner(exit_code=0, stdout="nothing interesting", stderr="", duration_ms=3)
    report = chamber.detonate(_poc(), {}, runner)
    assert report.verdict == "inconclusive"


def test_runner_raises_weak_path_is_error():
    chamber = DetonationChamber(success_marker=MARKER)

    def runner(poc, target_spec):
        raise RuntimeError("runner boom")

    report = chamber.detonate(_poc(), {}, runner)
    assert report.verdict == "error"
    assert report.exit_code is None


# --- nonzero exit under fs-verification: exit dominates -> error ------------

def test_nonzero_exit_under_fs_verification_is_error():
    chamber = DetonationChamber(success_marker=MARKER)
    runner = _fs_runner(1, "VULNERABLE", "boom", 3, "M poc_artifact.txt")
    report = chamber.detonate(_poc(), {}, runner, expected_fs_signature=FS_SIG)
    assert report.verdict == "error"
    assert report.verdict == semantic_verdict(
        1, "VULNERABLE", "boom", "M poc_artifact.txt",
        success_marker=MARKER, expected_fs_signature=FS_SIG,
    )


# --- the strong helper is preserved (not regressed by this leaf) ------------

def test_semantic_verdict_helper_untouched_and_pure():
    assert callable(semantic_verdict)
    assert semantic_verdict(
        0, "VULNERABLE", "", FS_SIG,
        success_marker=MARKER, expected_fs_signature=FS_SIG,
    ) == "confirmed"
    assert semantic_verdict(
        0, "VULNERABLE", "", "",
        success_marker=MARKER, expected_fs_signature=FS_SIG,
    ) == "refuted"
