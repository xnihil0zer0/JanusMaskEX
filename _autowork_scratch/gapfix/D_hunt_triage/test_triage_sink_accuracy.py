"""RED oracle for deterministic, accurate sink extraction in triage (Gap D).

This oracle proves the fix for the hunt/triage accuracy gap:

* A new deterministic, stdlib-only module ``ngv2.sink_extract`` that, given a
  code line / snippet, returns the canonical dotted ``sink_name`` and the CWE
  ``category`` implied by that sink -- via AST (regex fallback). It is
  reproducible: the same input always yields the same output.

* ``ngv2.workers.triage.run_stage`` GUARANTEES that every emitted triaged
  artifact carries an accurate ``sink_name`` (str) and ``call_sites``
  (non-empty list) derived deterministically from the finding's own evidence
  /code, and RECONCILES a wrong ``category`` with the sink that is actually
  present (the dbgpt class of bug: declared CWE-22 but the real sink is
  ``asyncio.create_subprocess_exec`` -> CWE-78).

These tests FAIL on HEAD (no ``ngv2.sink_extract`` module; triage copies the
LLM-asserted sink_name/category verbatim and never derives or reconciles them)
and PASS after the edits in FINDINGS.md are applied.

Pure stubs only -- no network / model / subprocess.
"""
import importlib
import json

import pytest


# --------------------------------------------------------------------------
# Part 1: deterministic sink-extraction module (ngv2.sink_extract)
# --------------------------------------------------------------------------

def _load_sink_extract():
    try:
        return importlib.import_module("ngv2.sink_extract")
    except Exception as exc:  # pragma: no cover - explicit RED on HEAD
        pytest.fail("ngv2.sink_extract is not importable yet: {0!r}".format(exc))


def test_extract_subprocess_sink():
    se = _load_sink_extract()
    res = se.extract_sink("subprocess.Popen(cmd, shell=True)")
    assert res is not None
    assert res["sink_name"] == "subprocess.Popen"
    assert res["category"] == "CWE-78"


def test_extract_eval_sink():
    se = _load_sink_extract()
    res = se.extract_sink("    return eval(user_payload)")
    assert res is not None
    assert res["sink_name"] == "eval"
    assert res["category"] == "CWE-95"


def test_extract_open_path_sink():
    se = _load_sink_extract()
    # The OUTER dangerous sink is open(); os.path.join is a benign helper.
    res = se.extract_sink("return open(os.path.join(base_dir, name))")
    assert res is not None
    assert res["sink_name"] == "open"
    assert res["category"] == "CWE-22"


def test_extract_async_subprocess_is_command_injection():
    """The dbgpt miscategorization class: async subprocess == CWE-78."""
    se = _load_sink_extract()
    res = se.extract_sink("await asyncio.create_subprocess_exec(prog, *args)")
    assert res is not None
    assert res["sink_name"] == "asyncio.create_subprocess_exec"
    assert res["category"] == "CWE-78"


def test_extract_unknown_returns_none():
    se = _load_sink_extract()
    assert se.extract_sink("x = a + b") is None
    assert se.extract_sink("") is None


def test_extract_is_reproducible_across_runs():
    se = _load_sink_extract()
    snippet = "subprocess.run(['sh', '-c', tainted], shell=True)"
    first = se.extract_sink(snippet)
    for _ in range(5):
        assert se.extract_sink(snippet) == first


def test_enrich_finding_populates_sink_and_reconciles_category():
    """A finding declared CWE-22 whose real evidence line is a subprocess call
    must be enriched to sink_name=subprocess.* and reconciled to CWE-78."""
    se = _load_sink_extract()
    finding = {
        "id": "F-DBGPT",
        "title": "path traversal in runner",
        "category": "CWE-22",            # WRONG (LLM/agy mislabel)
        "call_sites": ["asyncio.create_subprocess_exec(prog, *cmd)"],
        "evidence": ["dbgpt/util/run.py:42"],
    }
    out = se.enrich_finding(finding)
    assert out["sink_name"] == "asyncio.create_subprocess_exec"
    assert isinstance(out["call_sites"], list) and out["call_sites"]
    # category reconciled to the sink's true class
    assert out["category"] == "CWE-78"
    # original input is not mutated
    assert finding["category"] == "CWE-22"


def test_enrich_finding_uses_code_field_when_no_call_sites():
    se = _load_sink_extract()
    finding = {"id": "F2", "title": "eval", "code": "return eval(p)"}
    out = se.enrich_finding(finding)
    assert out["sink_name"] == "eval"
    assert out["category"] == "CWE-95"
    assert out["call_sites"] == ["return eval(p)"]


# --------------------------------------------------------------------------
# Part 2: triage worker GUARANTEES accurate sink_name / call_sites
# --------------------------------------------------------------------------

def _llm_stub(*_a, **_k):
    return {"confidence": 0.9, "priority": "high"}


def _gate_allow(*_a, **_k):
    return True


def _run_triage(finding):
    from ngv2.workers.triage import run_stage
    seams = {"llm_client": _llm_stub, "triage_may_confirm": _gate_allow}
    return run_stage({"prior_findings": [finding], "target": "acme/widget"}, seams)


def _finding_body(artifact):
    """Pull the finding-shaped body out of a triage artifact dict."""
    body = artifact.get("finding")
    if isinstance(body, dict):
        return body
    content = artifact.get("content")
    if isinstance(content, str):
        try:
            return json.loads(content)
        except Exception:
            return artifact
    return artifact


def test_triage_emits_accurate_sink_name_for_subprocess():
    finding = {
        "id": "F1",
        "title": "command injection",
        "category": "CWE-22",  # wrong on purpose
        "call_sites": ["subprocess.Popen(cmd, shell=True)"],
    }
    arts = _run_triage(finding)
    assert len(arts) == 1
    body = _finding_body(arts[0])
    assert body.get("sink_name") == "subprocess.Popen"
    assert isinstance(body.get("call_sites"), list) and body["call_sites"]
    # triage reconciles the wrong category to the sink's class
    assert body.get("category") == "CWE-78"


def test_triage_emits_accurate_sink_name_for_eval():
    finding = {
        "id": "F2",
        "title": "code exec",
        "category": "CWE-94",
        "evidence": ["m.py:5"],
        "code": "return eval(payload)",
    }
    arts = _run_triage(finding)
    body = _finding_body(arts[0])
    assert body.get("sink_name") == "eval"
    assert body.get("category") == "CWE-95"


def test_triage_emits_accurate_sink_name_for_open_path():
    finding = {
        "id": "F3",
        "title": "path traversal",
        "category": "CWE-22",
        "call_sites": ["open(os.path.join(base, user_name))"],
    }
    arts = _run_triage(finding)
    body = _finding_body(arts[0])
    assert body.get("sink_name") == "open"
    assert body.get("category") == "CWE-22"  # already correct, kept


def test_triage_sink_name_always_present_when_derivable():
    """Even if the finding has NO sink_name field, triage derives one."""
    finding = {
        "id": "F4",
        "title": "ssrf",
        "category": "CWE-918",
        "call_sites": ["requests.get(user_url)"],
    }
    arts = _run_triage(finding)
    body = _finding_body(arts[0])
    assert body.get("sink_name") == "requests.get"
    assert body.get("category") == "CWE-918"


def test_triage_is_reproducible():
    finding = {
        "id": "F5",
        "title": "x",
        "category": "CWE-22",
        "call_sites": ["subprocess.run(['sh','-c',t], shell=True)"],
    }
    first = _run_triage(finding)
    first_body = _finding_body(first[0])
    for _ in range(3):
        again = _finding_body(_run_triage(finding)[0])
        assert again.get("sink_name") == first_body.get("sink_name")
        assert again.get("category") == first_body.get("category")


def test_triage_unknown_sink_leaves_category_untouched():
    """When no sink can be derived, triage must NOT corrupt the category."""
    finding = {"id": "F6", "title": "logic bug", "category": "CWE-863"}
    arts = _run_triage(finding)
    body = _finding_body(arts[0])
    assert body.get("category") == "CWE-863"
