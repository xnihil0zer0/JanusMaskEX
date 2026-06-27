"""Harvester-alignment oracle for ``ngv2.workers.report.run_stage``.

This oracle is RED against the committed (clobbered) ``ngv2/workers/report.py``
at HEAD, which emits a ``submission.report.json`` filename (note the DOT before
``report``). ``artifact_harvester.parse_stage_artifact`` only accepts filenames
that end in ``_report.json`` (or the literal ``detonation_report.json``), so the
committed report artifact is silently NON-harvestable -- the exact "silent
clobber" class this work closes.

This oracle PASSES once ``report.run_stage`` emits a harvester-aligned filename
ending in ``_report.json`` (e.g. ``submission_report.json``). That code change
is made by the SEPARATE refactor brief ``brief_hooks_report-harvester-align.md``
(slug ``report-harvester-align-impl``). Oracle and refactor are deliberately in
DIFFERENT briefs/plans so the plan_normalizer dedup guard never pair-drops them.

Contract under test (frozen):
    run_stage(context: dict, seams: dict) -> list[dict]

What the report worker does (verified against the source):
* Returns ``[]`` when there are no findings AND no parked_package.
* Otherwise composes the injected ``llm_client`` + ``submission_package`` seams
  to assemble a submission payload and emits exactly one report-stage artifact
  ``{filename, content, stage, phase, target}`` with JSON ``content``.

The behavioral surface (one artifact, JSON content, payload passthrough) is
regression-locked; the ASSERTION THAT DRIVES THIS RED is that the emitted
filename is harvester-parseable.
"""
import json
from ngv2 import artifact_harvester
from ngv2.workers.report import run_stage


def _ctx():
    return {
        "target": "acme/widget",
        "phase": "report",
        "prior_findings": [{"id": "F1", "title": "rce", "severity": "high"}],
        "parked_package": {"poc": "print('x')", "id": "PK1"},
    }


def _stub_seams():
    """Inject a stub submission_package builder so the oracle does not depend on
    the real builder's signature/quirks -- the behavior under test is the report
    worker's artifact-emission + filename, not the package renderer."""
    def _builder(**_kwargs):
        return {"submission": "stub", "sections": ["title", "poc"]}

    return {"llm_client": None, "submission_package": _builder}


def _artifact():
    out = run_stage(_ctx(), _stub_seams())
    assert isinstance(out, list) and len(out) == 1
    return out[0]


def test_no_material_returns_empty_list():
    assert run_stage({"prior_findings": [], "parked_package": None}, {}) == []
    assert run_stage({}, {}) == []


def test_emits_single_report_artifact_with_json_content():
    art = _artifact()
    assert isinstance(art, dict)
    assert art["stage"] == "report"
    assert isinstance(art["content"], str)
    payload = json.loads(art["content"])
    assert isinstance(payload, (dict, list))


def test_report_filename_is_harvester_parseable():
    """RED against HEAD (submission.report.json) -- GREEN once filename ends _report.json."""
    art = _artifact()
    filename = art["filename"]
    assert filename.endswith("_report.json") or filename == "detonation_report.json", (
        "report artifact filename %r is NOT accepted by "
        "artifact_harvester.parse_stage_artifact (must end in '_report.json')" % filename
    )


def test_real_harvester_parses_the_report_artifact():
    """The REAL parser must classify the emitted artifact as a report (RED at HEAD)."""
    art = _artifact()
    harvested = artifact_harvester.parse_stage_artifact(
        art["filename"], art["content"], "report"
    )
    assert harvested is not None, (
        "artifact_harvester.parse_stage_artifact returned None for the report "
        "artifact -- the filename suffix is not harvester-aligned"
    )
    assert harvested["kind"] == "report"


def test_parked_package_travels_through_payload():
    art = _artifact()
    payload = json.loads(art["content"])
    if isinstance(payload, dict):
        assert payload.get("parked_package") is not None
