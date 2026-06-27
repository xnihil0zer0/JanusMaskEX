"""Regression-lock oracle for ``ngv2.workers.triage.run_stage``.

This oracle is a *behavioral regression lock* for the already-committed
``ngv2/workers/triage.py``. It exists because the worker modules shipped with
ZERO oracles, which is exactly how a sibling worker (report.py) got silently
clobbered. It asserts the CURRENT, real behavior of the committed module under
mocked seams so that any future clobber (e.g. an empty-list or wrong-shape
regression) goes RED.

Contract under test (frozen):
    run_stage(context: dict, seams: dict) -> list[dict]

What the committed triage worker actually does (verified against the source):
* Reads ``context['prior_findings']`` (and ``context['target']``); returns ``[]``
  when there are no prior findings.
* For each prior finding it invokes the injected llm-client seam to assess it,
  then asks the injected triage ``may_confirm`` gate whether it may advance.
* Confirmed findings are rendered to artifact dicts; each artifact carries a
  ``filename`` (str), a JSON ``content`` (str), ``phase == 'triage'``, a
  ``confidence`` float, a ``triage`` metadata dict, and a nested ``finding``
  dict. The artifact body merges the original record fields.
* A gate that rejects a finding withholds its artifact (fail-closed on the
  rejected item). A gate that raises is treated as a rejection.

All seams are stubs; no real model/network/subprocess is used.
"""
import json
import pytest
from ngv2.workers import triage
from ngv2.workers.triage import run_stage


def _llm_stub(*_args, **_kwargs):
    """A deterministic llm-client seam returning a fixed assessment."""
    return {"confidence": 0.9, "priority": "high", "rationale": "looks real"}


def _gate_allow(*_args, **_kwargs):
    return True


def _gate_reject(*_args, **_kwargs):
    return False


def _finding(fid="F1", title="SQLi in login"):
    return {
        "id": fid,
        "target": "acme/widget",
        "category": "injection",
        "severity": "high",
        "title": title,
        "description": "param is concatenated into a query",
    }


def test_empty_prior_findings_returns_empty_list():
    """No prior findings -> empty list, no seam calls required."""
    assert run_stage({"prior_findings": []}, {}) == []
    assert run_stage({}, {}) == []


def test_none_context_and_seams_return_empty_list():
    """Tolerant of non-dict context/seams; never raises."""
    assert run_stage(None, None) == []


def test_confirmed_finding_yields_one_parseable_shaped_artifact():
    """A single confirmed finding -> exactly one well-shaped artifact dict."""
    ctx = {"target": "acme/widget", "prior_findings": [_finding()]}
    seams = {"llm_client": _llm_stub, "triage_may_confirm": _gate_allow}
    out = run_stage(ctx, seams)
    assert isinstance(out, list) and len(out) == 1
    art = out[0]
    assert isinstance(art, dict)
    # frozen artifact envelope
    assert art["phase"] == "triage"
    assert isinstance(art["filename"], str) and art["filename"].endswith(".json")
    assert isinstance(art["content"], str)
    # content is valid JSON
    body = json.loads(art["content"])
    assert isinstance(body, dict)
    # nested finding + triage metadata survive
    assert isinstance(art["finding"], dict)
    assert art["finding"]["id"] == "F1"
    assert isinstance(art["confidence"], float)
    assert art["confidence"] == pytest.approx(0.9)
    assert isinstance(art["triage"], dict)
    assert art["triage"].get("priority") == "high"


def test_gate_rejection_withholds_artifact():
    """A rejecting gate withholds the artifact (fail-closed on that item)."""
    ctx = {"target": "acme/widget", "prior_findings": [_finding()]}
    seams = {"llm_client": _llm_stub, "triage_may_confirm": _gate_reject}
    out = run_stage(ctx, seams)
    assert out == []


def test_gate_raising_is_treated_as_rejection():
    """A gate that raises -> the finding is dropped, not crashed on."""
    def _boom(*_a, **_k):
        raise RuntimeError("gate exploded")

    ctx = {"prior_findings": [_finding()]}
    seams = {"llm_client": _llm_stub, "triage_may_confirm": _boom}
    out = run_stage(ctx, seams)
    assert out == []


def test_multiple_findings_partition_by_gate():
    """Two findings, gate confirms only the high-confidence one."""
    f_keep = _finding(fid="KEEP", title="keep me")
    f_drop = _finding(fid="DROP", title="drop me")

    def _selective_gate(finding, *_rest, **_kw):
        rec = finding if isinstance(finding, dict) else {}
        return rec.get("id") == "KEEP"

    ctx = {"prior_findings": [f_keep, f_drop]}
    seams = {"llm_client": _llm_stub, "triage_may_confirm": _selective_gate}
    out = run_stage(ctx, seams)
    ids = [a["finding"]["id"] for a in out]
    assert ids == ["KEEP"]


def test_no_gate_seam_defaults_to_advancing():
    """With no gate injected the committed worker advances the finding."""
    ctx = {"prior_findings": [_finding()]}
    seams = {"llm_client": _llm_stub}
    out = run_stage(ctx, seams)
    assert len(out) == 1


def test_phase_constant_is_triage():
    assert triage.PHASE == "triage"
