"""Regression-lock oracle for ngv2.workers.hunt.run_stage.

The worker modules shipped with zero oracles, which is how a sibling worker
(report.py) was silently clobbered. This locks the CURRENT real behavior of the
committed hunt worker under stubbed seams so any future clobber (empty-list,
wrong-shape, signature regression) goes RED. No model/network/subprocess.

Frozen contract: run_stage(context: dict, seams: dict) -> list[dict].
"""
import inspect

from ngv2.workers import hunt
from ngv2.workers.hunt import run_stage


def _llm_with_candidates(*_a, **_k):
    return {"candidates": [{"title": "SQLi in login", "category": "injection",
                            "severity": "high", "description": "param concatenated"}]}


def _allow(*_a, **_k):
    return True


def _reject(*_a, **_k):
    return False


def test_signature_two_param_seam():
    params = list(inspect.signature(run_stage).parameters)
    assert params[:2] == ["context", "seams"]


def test_no_seams_returns_empty():
    assert run_stage({"target": "acme/app"}, {}) == []


def test_empty_candidates_returns_empty():
    seams = {"llm_client": lambda *_a, **_k: {"candidates": []}, "may_confirm": _allow}
    assert run_stage({"target": "acme/app"}, seams) == []


def test_confirmed_candidate_becomes_hunt_artifact():
    seams = {"llm_client": _llm_with_candidates, "may_confirm": _allow}
    out = run_stage({"target": "acme/app"}, seams)
    assert isinstance(out, list) and len(out) >= 1
    art = out[0]
    assert set(art.keys()) >= {"content", "filename", "phase"}
    assert art["phase"] == "hunt"
    assert isinstance(art["filename"], str) and art["filename"]
    assert isinstance(art["content"], str)


def test_gate_reject_withholds_artifact():
    seams = {"llm_client": _llm_with_candidates, "may_confirm": _reject}
    assert run_stage({"target": "acme/app"}, seams) == []


def test_never_raises_on_bad_llm():
    seams = {"llm_client": lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
             "may_confirm": _allow}
    assert run_stage({"target": "acme/app"}, seams) == []
