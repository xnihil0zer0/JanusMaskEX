"""Regression-lock oracle for ``ngv2.workers.verify.run_stage``.

Behavioral regression lock for the already-committed ``ngv2/workers/verify.py``
(shipped with ZERO oracles). Asserts the CURRENT real behavior under mocked
seams so any future clobber goes RED.

Contract under test (frozen):
    run_stage(context: dict, seams: dict) -> list[dict]

What the committed verify worker actually does (verified against the source):
* Gathers findings from ``context['prior_findings']`` and ``parked_package``;
  returns ``[]`` when there are none.
* For each finding it drives the injected llm-client seam to attempt
  reproduction, normalizes the result into a reproduced/not-reproduced boolean,
  then builds a LiveTestReport-shaped report dict (``phase``, ``target``,
  ``finding_id``, ``reproduced``, ``confirmed``, ``status``, ``summary``,
  ``evidence``).
* Each surviving report is wrapped into an artifact dict
  ``{phase, filename, content, report}`` with a JSON ``content`` and a
  ``live_test_report_{ordinal}.json`` filename.
* The verify ``may_confirm`` gate may withhold an artifact (a falsey verdict
  drops it); with no gate injected the report passes through.

All seams are stubs; no real model/network/subprocess is used.
"""
import json
from ngv2.workers import verify
from ngv2.workers.verify import run_stage


def _reproduced_llm(*_a, **_k):
    return {"reproduced": True, "evidence": "stack trace captured"}


def _not_reproduced_llm(*_a, **_k):
    return {"reproduced": False}


def _finding(fid="F1"):
    return {"id": fid, "title": "path traversal", "target": "acme/widget"}


def test_no_findings_returns_empty_list():
    assert run_stage({"prior_findings": []}, {}) == []
    assert run_stage({}, {}) == []


def test_non_dict_context_returns_empty_list():
    assert run_stage(None, {}) == []


def test_reproduced_finding_yields_verified_report_artifact():
    ctx = {"target": "acme/widget", "prior_findings": [_finding()]}
    seams = {"llm_client": _reproduced_llm}
    out = run_stage(ctx, seams)
    assert isinstance(out, list) and len(out) == 1
    art = out[0]
    assert art["phase"] == "verify"
    assert isinstance(art["filename"], str) and art["filename"].endswith(".json")
    assert isinstance(art["content"], str)
    report = json.loads(art["content"])
    assert report["reproduced"] is True
    assert report["confirmed"] is True
    assert report["status"] == "verified"
    assert report["finding_id"] == "F1"
    assert report["phase"] == "verify"
    # nested report mirror
    assert art["report"]["status"] == "verified"


def test_not_reproduced_finding_yields_not_reproduced_status():
    ctx = {"target": "acme/widget", "prior_findings": [_finding()]}
    seams = {"llm_client": _not_reproduced_llm}
    out = run_stage(ctx, seams)
    assert len(out) == 1
    report = out[0]["report"]
    assert report["reproduced"] is False
    assert report["confirmed"] is False
    assert report["status"] == "not_reproduced"


def test_gate_rejection_withholds_artifact():
    ctx = {"prior_findings": [_finding()]}
    seams = {"llm_client": _reproduced_llm, "verify_may_confirm": lambda *_a, **_k: False}
    assert run_stage(ctx, seams) == []


def test_gate_acceptance_passes_artifact_through():
    ctx = {"prior_findings": [_finding()]}
    seams = {"llm_client": _reproduced_llm, "verify_may_confirm": lambda *_a, **_k: True}
    assert len(run_stage(ctx, seams)) == 1


def test_findings_also_collected_from_parked_package():
    """A finding supplied only via parked_package is still verified."""
    ctx = {"target": "acme/widget", "parked_package": {"findings": [_finding("PK1")]}}
    seams = {"llm_client": _reproduced_llm}
    out = run_stage(ctx, seams)
    assert len(out) == 1
    assert out[0]["report"]["finding_id"] == "PK1"


def test_phase_constant_is_verify():
    assert verify.PHASE == "verify"
