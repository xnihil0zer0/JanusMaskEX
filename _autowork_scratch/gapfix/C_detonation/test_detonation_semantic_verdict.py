"""RED oracle (gap area C — detonation/verification seam): the detonate WORKER
must score ``reproduced`` SEMANTICALLY off the FS signature/marker, not off a
bare exit code, and the conductor's detonation_evidence gate must consume that.

DEFECT under test (traced live on HEAD 2026-06-14):

``ngv2.workers.detonate._classify`` derives the outcome WITHOUT ever inspecting
the success marker (``poc_writer.MARKER == 'VULNERABLE'``) or the filesystem
signature (``poc_writer.FS_SIGNATURE == 'pwned_marker'``). Concretely:

  * CASE A (FALSE NEGATIVE): a genuinely reproducing run whose seam returns
    ``exit_code == 0`` + marker on stdout + the fs signature in
    ``fs_snapshot_diff`` -- but NO explicit ``success``/``reproduced`` flag --
    is classified ``'failure'`` (``reproduced=False``).  The conductor then maps
    that to ``observed_runtime_effect=False`` and the ``detonation_evidence``
    gate fails closed (``static_assertion`` / ``unproven``).  A CORRECT PoC is
    scored as a failure.

  * CASE B (FALSE POSITIVE -- the dangerous one): a crash (``exit_code != 0``,
    no marker, no fs effect) hits ``_classify``'s "exit_code != 0 => triggered
    => success" branch and is scored ``'success'`` (``reproduced=True``).  A bare
    crash becomes a "confirmed exploit" -- an untrustworthy confirm that would
    feed a real bounty submission.

REQUIRED FIX (pinned by this oracle): when the seam result carries semantic
evidence (a ``fs_snapshot_diff`` / fs-signature field, or a marker token in
stdout/stderr), ``_classify`` MUST delegate the verdict to the SAME semantic
oracle the rest of the chain uses (``ngv2.detonation.semantic_verdict`` with
``success_marker = poc_writer.MARKER`` and
``expected_fs_signature = poc_writer.FS_SIGNATURE`` by default, overridable via
the result/context). ``reproduced`` is True IFF that verdict is ``'confirmed'``.
A crash (nonzero exit) is NEVER ``reproduced``. An EXPLICIT ``success`` /
``reproduced`` flag from the seam still wins verbatim (the live
``_make_detonation_seam`` already pre-computes the semantic verdict and sets
these flags, so that path is preserved).

This oracle uses injected/fake seam results only -- no bwrap, no network, no
subprocess; writes nothing. It FAILS on current HEAD and PASSES after the edit.
"""
import pytest

from ngv2.workers.detonate import run_stage
from ngv2.conductor_seams import _gate_detonation
from ngv2.gate_executor import run_gates
from ngv2.poc_writer import MARKER, FS_SIGNATURE


# The canonical FS-effect a reproducing PoC must produce (contract to agents A/B):
# the PoC writes a file/marker named so that FS_SIGNATURE appears in the jail's
# fs_snapshot_diff, and prints MARKER. diff_snapshots renders an added path as
# "A pwned_marker".
_REPRODUCING_DIFF = "A {sig}".format(sig=FS_SIGNATURE)


def _poc_context():
    return {"target": "acme/widget", "parked_package": {"poc": "open('pwned_marker','w')", "id": "PK1"}}


def _run(seam_result):
    return run_stage(_poc_context(), {"detonation": lambda *a, **k: seam_result})[0]


def _gate_decision(raw_report):
    """Push a worker report through the conductor gate-mapping + executor exactly
    as build_evidence -> run_gates does, with the OTHER detonate-transition gates
    satisfied so detonation_evidence is the deciding gate."""
    ev = {
        "detonation_report": _gate_detonation(raw_report),
        "target_source": "os.system(payload)",
        "expected_signature": "os.system",
        "sink_name": "os.system",
        "call_sites": ["app/handler.py:42"],
    }
    return run_gates("detonate", "novelty", ev)


# --- CASE A: genuine reproduction (marker + fs signature) -> reproduced -------

def test_marker_and_fs_signature_present_is_reproduced():
    """exit0 + MARKER on stdout + FS_SIGNATURE in fs_snapshot_diff, no explicit
    success flag -> the worker must score it reproduced/success (semantic)."""
    art = _run({
        "exit_code": 0,
        "stdout": "exploit ran: {m}".format(m=MARKER),
        "stderr": "",
        "fs_snapshot_diff": _REPRODUCING_DIFF,
    })
    assert art["outcome"] == "success"
    assert art["reproduced"] is True
    assert art["success"] is True


def test_reproducing_report_passes_detonation_evidence_gate():
    """The genuine reproduction must traverse the conductor gate: detonation_evidence
    returns may_confirm=True (live_execution) and the transition advances."""
    art = _run({
        "exit_code": 0,
        "stdout": MARKER,
        "stderr": "",
        "fs_snapshot_diff": _REPRODUCING_DIFF,
    })
    decision = _gate_decision(art["report"])
    det = decision["results"].get("detonation_evidence")
    assert det is not None
    assert det["evidence_kind"] == "live_execution"
    assert det["may_confirm"] is True
    # The detonation_evidence gate itself must NOT block (other transition gates
    # such as sink_reachability are out of scope for this seam).
    assert "detonation_evidence" not in decision["blocked_by"]


# --- CASE A negative: marker but NO fs signature -> NOT reproduced ------------

def test_marker_without_fs_signature_is_not_reproduced():
    """Marker-spoof (printed marker, no filesystem effect) must NOT be scored a
    reproduction -- the strong gate refutes, and detonation_evidence fails closed."""
    art = _run({
        "exit_code": 0,
        "stdout": MARKER,
        "stderr": "",
        "fs_snapshot_diff": "",  # no fs effect at all
    })
    assert art["outcome"] == "failure"
    assert art["reproduced"] is False
    det = _gate_decision(art["report"])["results"].get("detonation_evidence")
    assert det["may_confirm"] is False


def test_fs_signature_without_marker_is_not_reproduced():
    """An fs change that is NOT the expected signature (or no marker) must refute."""
    art = _run({
        "exit_code": 0,
        "stdout": "ran, nothing proven",
        "stderr": "",
        "fs_snapshot_diff": "M unrelated_scratch.txt",
    })
    assert art["outcome"] == "failure"
    assert art["reproduced"] is False


# --- CASE B: crash (nonzero exit, no evidence) -> NOT reproduced --------------

def test_crash_is_not_a_reproduction_false_positive_closed():
    """A bare crash (nonzero exit, no marker, no fs effect) must NEVER be scored a
    reproduction. On HEAD _classify maps nonzero-exit -> success (false positive)."""
    art = _run({
        "exit_code": 1,
        "stdout": "",
        "stderr": "Traceback (most recent call last): ...",
    })
    assert art["outcome"] != "success"
    assert art["reproduced"] is False
    det = _gate_decision(art["report"])["results"].get("detonation_evidence")
    assert det["may_confirm"] is False


def test_crash_with_marker_and_signature_still_not_reproduced():
    """Nonzero exit dominates even if marker + fs signature are present (the run
    did not complete cleanly): semantic_verdict -> 'error', so not reproduced."""
    art = _run({
        "exit_code": 137,
        "stdout": MARKER,
        "stderr": "OOM",
        "fs_snapshot_diff": _REPRODUCING_DIFF,
    })
    assert art["outcome"] != "success"
    assert art["reproduced"] is False


# --- preserved behavior: explicit seam flags still win verbatim --------------

def test_explicit_success_flag_still_wins():
    """The live _make_detonation_seam pre-computes the semantic verdict and sets
    success/reproduced/verdict explicitly; that path must be preserved."""
    art = _run({
        "success": True,
        "reproduced": True,
        "verdict": "confirmed",
        "exit_code": 0,
        "stdout": MARKER,
        "stderr": "",
        "fs_snapshot_diff": _REPRODUCING_DIFF,
    })
    assert art["outcome"] == "success"
    assert art["reproduced"] is True


def test_explicit_failure_flag_still_wins():
    art = _run({"success": False, "exit_code": 0})
    assert art["outcome"] == "failure"
    assert art["reproduced"] is False
