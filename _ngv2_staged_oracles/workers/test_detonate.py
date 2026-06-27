"""Regression-lock oracle for ``ngv2.workers.detonate.run_stage``.

Behavioral regression lock for the already-committed ``ngv2/workers/detonate.py``
(shipped with ZERO oracles). Asserts the CURRENT real behavior under a stub
detonation seam so any future clobber goes RED.

Contract under test (frozen):
    run_stage(context: dict, seams: dict) -> list[dict]

What the committed detonate worker actually does (verified against the source):
* Extracts the PoC to detonate from ``parked_package`` / ``prior_findings``;
  with NO PoC it still emits exactly one artifact whose ``outcome == 'no_poc'``.
* With a PoC but no callable ``seams['detonation']`` it emits an ``error``
  outcome artifact (it never raises).
* With a callable detonation seam it invokes it (adapting to its signature),
  normalizes the result, and classifies the outcome (success/failure/error).
* The single emitted artifact carries ``phase == 'detonate'`` and a
  ``filename == 'detonate_live_test_report.json'`` which — critically — ends in
  ``_report.json`` so that
  ``artifact_harvester.parse_stage_artifact(filename, content, 'detonate')``
  PARSES it into a report artifact. This regression-locks that harvester
  alignment.
* A detonation seam that raises is caught and surfaced as an ``error`` outcome.

All seams are stubs; no real subprocess/network is used.
"""
import json
from ngv2 import artifact_harvester
from ngv2.workers import detonate
from ngv2.workers.detonate import run_stage


def _poc_context(poc="print('boom')"):
    return {"target": "acme/widget", "parked_package": {"poc": poc, "id": "PK1"}}


def test_no_poc_emits_single_no_poc_artifact():
    out = run_stage({"target": "acme/widget"}, {})
    assert isinstance(out, list) and len(out) == 1
    art = out[0]
    assert art["phase"] == "detonate"
    assert art["outcome"] == "no_poc"
    assert art["report"]["outcome"] == "no_poc"


def test_missing_detonation_seam_emits_error_artifact():
    out = run_stage(_poc_context(), {})
    assert len(out) == 1
    assert out[0]["outcome"] == "error"
    assert "detonation seam" in out[0]["report"]["error"]


def test_successful_detonation_classifies_success_and_parses():
    def _seam(*_a, **_k):
        return {"success": True, "exit_code": 0, "stdout": "pwned", "stderr": ""}

    out = run_stage(_poc_context(), {"detonation": _seam})
    assert len(out) == 1
    art = out[0]
    assert art["phase"] == "detonate"
    assert art["outcome"] == "success"
    assert art["success"] is True
    assert art["reproduced"] is True
    # frozen harvester-aligned filename
    assert art["filename"] == "detonate_live_test_report.json"
    assert art["filename"].endswith("_report.json")
    # content is valid JSON ...
    parsed = json.loads(art["content"])
    assert parsed["outcome"] == "success"
    # ... and the REAL harvester parser accepts the (filename, content) pair
    harvested = artifact_harvester.parse_stage_artifact(
        art["filename"], art["content"], "detonate"
    )
    assert harvested is not None
    assert harvested["kind"] == "report"
    assert harvested["data"]["outcome"] == "success"


def test_failed_detonation_classifies_failure():
    def _seam(*_a, **_k):
        return {"success": False, "exit_code": 0}

    out = run_stage(_poc_context(), {"detonation": _seam})
    assert out[0]["outcome"] == "failure"
    assert out[0]["success"] is False


def test_seam_raising_is_caught_as_error():
    def _seam(*_a, **_k):
        raise RuntimeError("detonation blew up")

    out = run_stage(_poc_context(), {"detonation": _seam})
    assert len(out) == 1
    assert out[0]["outcome"] == "error"
    assert "raised" in out[0]["report"]["error"]


def test_empty_dict_result_classifies_failure():
    """An empty dict has no success/crash/exit signal -> failure (not a crash)."""
    out = run_stage(_poc_context(), {"detonation": lambda *_a, **_k: {}})
    assert out[0]["outcome"] == "failure"


def test_none_seam_result_is_error():
    """A seam returning an unparseable/None result -> error outcome, never raises."""
    out = run_stage(_poc_context(), {"detonation": lambda *_a, **_k: None})
    assert out[0]["outcome"] == "error"


def test_context_not_mutated():
    ctx = _poc_context()
    before = json.dumps(ctx, sort_keys=True)
    run_stage(ctx, {"detonation": lambda *_a, **_k: {"success": True}})
    assert json.dumps(ctx, sort_keys=True) == before


def test_phase_constant_is_detonate():
    assert detonate.PHASE == "detonate"
