"""Regression-lock oracle for ngv2.workers.poc.run_stage.

Locks the CURRENT real behavior of the committed poc worker under stubbed seams
so any future clobber goes RED. The poc worker never raises for the documented
edge cases -- it surfaces failure inside the returned artifacts. No
model/network/subprocess.

Frozen contract: run_stage(context: dict, seams: dict) -> list[dict].
"""
import inspect

from ngv2.workers import poc
from ngv2.workers.poc import run_stage

_FINDING = {"id": "F1", "title": "SQLi", "target": "acme/app",
            "severity": "high", "description": "param concatenated into query"}


def _writer(**_k):
    return "print('exploit')  # poc"


def test_signature_two_param_seam():
    params = list(inspect.signature(run_stage).parameters)
    assert params[:2] == ["context", "seams"]


def test_no_finding_returns_failure_artifact():
    out = run_stage({"target": "t"}, {})
    assert len(out) == 1
    assert out[0]["success"] is False
    assert out[0]["phase"] == "poc"


def test_missing_writer_seam_is_failure_not_raise():
    out = run_stage({"prior_findings": [_FINDING], "target": "acme/app"}, {})
    assert len(out) == 1
    assert out[0]["success"] is False
    assert "error" in out[0]


def test_writer_output_becomes_success_artifact():
    out = run_stage({"prior_findings": [_FINDING], "target": "acme/app"},
                    {"poc_writer": _writer})
    assert len(out) == 1
    art = out[0]
    assert art["success"] is True
    assert set(art.keys()) >= {"code", "content", "finding_id", "phase",
                               "success", "target", "filename"}
    assert art["phase"] == "poc"
    assert art["repaired"] is False  # no repair seam provided


def test_empty_writer_output_is_failure():
    out = run_stage({"prior_findings": [_FINDING], "target": "acme/app"},
                    {"poc_writer": lambda **_k: "   "})
    assert len(out) == 1
    assert out[0]["success"] is False
