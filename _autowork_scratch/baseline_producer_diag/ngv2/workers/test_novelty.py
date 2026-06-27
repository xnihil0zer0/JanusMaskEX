"""Regression-lock oracle for ``ngv2.workers.novelty.run_stage``.

Behavioral regression lock for the already-committed ``ngv2/workers/novelty.py``
(shipped with ZERO oracles). Asserts the CURRENT real, fail-closed behavior
under a stub novelty gate so any future clobber goes RED.

Contract under test (frozen):
    run_stage(context: dict, seams: dict) -> list[dict]

What the committed novelty worker actually does (verified against the source):
* ALWAYS returns exactly one artifact dict ``{filename, content, phase}`` (it is
  a single-verdict judge), with ``filename == 'novelty.json'``.
* Composes ``seams['novelty_gate']`` and NEVER relaxes it: only an explicit
  novel signal yields ``novel == True``. Duplicates, failures, malformed output,
  missing verdicts, a missing/non-callable gate, and empty finding material all
  fail-closed to ``novel == False``.
* ``content`` is a JSON string carrying at least ``novel``/``verdict`` keys.

All seams are stubs; no real model/network/subprocess is used.
"""
import json
from ngv2.workers.novelty import run_stage


def _material_ctx():
    return {
        "phase": "novelty",
        "target": "acme/widget",
        "prior_findings": [{"id": "F1", "title": "ssrf"}],
    }


def _content(out):
    assert isinstance(out, list) and len(out) == 1
    art = out[0]
    assert art["filename"] == "novelty.json"
    assert art["phase"] == "novelty"
    return json.loads(art["content"])


def test_always_emits_single_novelty_artifact():
    out = run_stage(_material_ctx(), {"novelty_gate": lambda *_a, **_k: True})
    body = _content(out)
    assert "novel" in body or "is_novel" in body
    assert "verdict" in body


def test_explicit_novel_gate_yields_novel_true():
    out = run_stage(_material_ctx(), {"novelty_gate": lambda *_a, **_k: True})
    body = _content(out)
    assert body.get("novel") is True
    assert body.get("verdict") == "novel"


def test_duplicate_gate_fails_closed_to_non_novel():
    gate = lambda *_a, **_k: {"novel": False, "duplicate_of": "R-42"}
    body = _content(run_stage(_material_ctx(), {"novelty_gate": gate}))
    assert body.get("novel") is False
    assert body.get("verdict") in ("duplicate", "non_novel")


def test_gate_raising_fails_closed_with_error_flag():
    def _boom(*_a, **_k):
        raise RuntimeError("gate down")

    body = _content(run_stage(_material_ctx(), {"novelty_gate": _boom}))
    assert body.get("novel") is False
    assert body.get("verdict") == "failure"
    assert body.get("error") is True


def test_missing_gate_seam_fails_closed():
    body = _content(run_stage(_material_ctx(), {}))
    assert body.get("novel") is False
    assert body.get("error") is True


def test_no_finding_material_fails_closed():
    body = _content(run_stage({"phase": "novelty", "target": "x"}, {"novelty_gate": lambda *_a, **_k: True}))
    assert body.get("novel") is False
    assert body.get("verdict") == "non_novel"


def test_malformed_gate_output_fails_closed():
    body = _content(run_stage(_material_ctx(), {"novelty_gate": lambda *_a, **_k: 12345}))
    assert body.get("novel") is False


def test_non_dict_context_is_tolerated():
    out = run_stage(None, {"novelty_gate": lambda *_a, **_k: True})
    assert isinstance(out, list) and len(out) == 1
