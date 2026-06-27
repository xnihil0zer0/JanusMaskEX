"""Oracle: ngv2.codeql_lead_source -- CodeQL-backed PRIMARY hunt lead source.

CodeQL gives true interprocedural source->sink taint, so its findings are
reachability-VERIFIED. This module turns a security-suite SARIF into the agy
candidate shape the FSM consumes, and is wired as the FIRST lead source in
hunt_lead_client (CodeQL -> agy -> regex fallback).

These tests are HERMETIC: no real codeql binary. A scripted runner feeds the
saved reference SARIF (real `py/command-line-injection` result) so the parse +
enrich + candidate-mapping path runs end to end. Proves: SARIF cmd-injection
result -> candidate with normalized CWE-78, sink snippet, sink_name, reachable,
evidence; the candidate passes the sink_reachability gate; determinism;
fail-soft; and the hunt_lead_client wiring preference order.
"""
import importlib
import json
import os

import pytest

mod = importlib.import_module("ngv2.codeql_lead_source")
runner_mod = importlib.import_module("ngv2.codeql_runner")
gate_mod = importlib.import_module("ngv2.sink_reachability_gate")
hlc = importlib.import_module("ngv2.hunt_lead_client")

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixture_cmdinj.sarif")


def _load_fixture():
    with open(_FIXTURE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _scripted_runner():
    """A runner that succeeds for `database create` and returns the fixture SARIF
    for `database analyze`."""
    sarif = _load_fixture()
    script = {"database": (0, "", "", sarif)}
    return runner_mod.make_scripted_runner(script, default=(0, "", "", sarif))


def _make_repo(tmp_path):
    """Materialize the SARIF's vulnerable file so snippet reading succeeds."""
    app = tmp_path / "app"
    app.mkdir()
    # line 2 = source (import/user input), line 9 = the subprocess sink.
    vuln = (
        "import flask\n"
        "from flask import request\n"
        "app = flask.Flask(__name__)\n"
        "\n"
        "import subprocess\n"
        "\n"
        "@app.route('/run')\n"
        "def run():\n"
        "    return subprocess.Popen(request.args['cmd'], shell=True)\n"
    )
    (app / "vuln.py").write_text(vuln)
    return str(tmp_path)


# ---------------------------------------------------------------------------
# (a) SARIF cmd-injection result -> reachability-verified candidate
# ---------------------------------------------------------------------------

def test_cmdinj_sarif_becomes_candidate(tmp_path):
    repo = _make_repo(tmp_path)
    findings = mod.codeql_scan(repo, runner=_scripted_runner(), languages=["python"])
    assert findings, "expected at least one enriched finding"
    f = findings[0]
    assert f["category"] == "CWE-78"  # normalized from CWE-078
    assert f["reachable"] is True
    assert f["source"] == "codeql"
    assert f["sink_name"], "sink_name should be inferred"
    assert isinstance(f["call_sites"], list) and f["call_sites"][0]
    # source location pulled from codeFlows
    assert isinstance(f.get("source_location"), dict)
    assert f["source_location"]["file"] == "app/vuln.py"

    cands = mod.findings_to_candidates(findings, "acme")
    assert cands, "expected at least one candidate"
    c = cands[0]
    assert c["category"] == "CWE-78"
    assert c["sink_name"]
    assert c["call_sites"] and "subprocess.Popen" in c["call_sites"][0]
    assert c["reachable"] is True
    assert c["codeql_reachable"] is True
    assert c["source"] == "codeql"
    assert c["evidence"] == ["app/vuln.py:9"]
    assert c["target"] == "acme"
    # agy candidate-shape contract: detonation oracle hints defaulted in
    assert c["expected_fs_signature"] == "pwned_marker"
    assert c["success_marker"] == "VULNERABLE"
    assert c["id"].startswith("HUNT-")


# ---------------------------------------------------------------------------
# (b) candidate passes the triage sink-reachability gate
# ---------------------------------------------------------------------------

def test_candidate_passes_reachability_gate(tmp_path):
    repo = _make_repo(tmp_path)
    findings = mod.codeql_scan(repo, runner=_scripted_runner(), languages=["python"])
    c = mod.findings_to_candidates(findings, "acme")[0]
    verdict = gate_mod.assess_sink_reachability(c["sink_name"], c["call_sites"])
    assert verdict["reachable"] is True
    assert verdict["may_confirm"] is True


def test_call_site_is_standalone_parseable_when_sink_is_nested(tmp_path):
    """Regression: real sink lines are INDENTED inside nested blocks. The
    reachability gate ast-parses each call_site, and ast.parse rejects indented
    source, so an indented multi-statement snippet silently reads as
    unreachable. The enriched call_site must be the dedented sink line that
    parses on its own. (A live CodeQL scan exposed this; the prior fixture
    masked it because its context window happened to form a valid def+body.)
    """
    import ast
    app = tmp_path / "app"
    app.mkdir()
    # Sink on line 9, nested two levels deep, with sibling statements around it
    # so a naive context block is NOT standalone-parseable.
    vuln = (
        "import subprocess\n"
        "from flask import request\n"
        "app = object()\n"
        "\n"
        "def handler():\n"
        "    if True:\n"
        "        host = request.args['h']\n"
        "        cmd = 'ping ' + host\n"
        "        subprocess.Popen(cmd, shell=True)\n"
        "        return 'ok'\n"
    )
    (app / "vuln.py").write_text(vuln)
    findings = mod.codeql_scan(str(tmp_path), runner=_scripted_runner(), languages=["python"])
    c = mod.findings_to_candidates(findings, "acme")[0]
    assert c["call_sites"], "expected a call_site snippet"
    snippet = c["call_sites"][0]
    # The call_site MUST parse standalone (no IndentationError).
    ast.parse(snippet)
    assert "subprocess.Popen" in snippet
    verdict = gate_mod.assess_sink_reachability(c["sink_name"], c["call_sites"])
    assert verdict["reachable"] is True
    assert verdict["may_confirm"] is True


# ---------------------------------------------------------------------------
# (c) determinism
# ---------------------------------------------------------------------------

def test_determinism(tmp_path):
    repo = _make_repo(tmp_path)
    a = mod.codeql_scan(repo, runner=_scripted_runner(), languages=["python"])
    b = mod.codeql_scan(repo, runner=_scripted_runner(), languages=["python"])
    assert a == b
    ca = mod.findings_to_candidates(a, "acme")
    cb = mod.findings_to_candidates(b, "acme")
    assert ca == cb


# ---------------------------------------------------------------------------
# (d) fail-soft
# ---------------------------------------------------------------------------

def test_failsoft_raising_runner(tmp_path):
    repo = _make_repo(tmp_path)

    def boom(argv):
        raise RuntimeError("codeql exploded")

    assert mod.codeql_scan(repo, runner=boom, languages=["python"]) == []


def test_failsoft_non_dict_sarif(tmp_path):
    repo = _make_repo(tmp_path)
    runner = runner_mod.make_scripted_runner(
        {"database": (0, "", "", "not-a-dict")}, default=(0, "", "", "not-a-dict")
    )
    assert mod.codeql_scan(repo, runner=runner, languages=["python"]) == []


def test_failsoft_no_repo():
    assert mod.codeql_scan("/nonexistent/path/xyz", runner=_scripted_runner()) == []


def test_findings_to_candidates_non_list():
    assert mod.findings_to_candidates(None, "t") == []
    assert mod.findings_to_candidates("nope", "t") == []


# ---------------------------------------------------------------------------
# (e) wiring: hunt_lead_client prefers codeql, else falls back to agy/regex
# ---------------------------------------------------------------------------

def _stub_agy_complete(messages, *, max_tokens=4096, system=None):
    return json.dumps([{
        "title": "SQLi in login", "category": "CWE-89", "severity": "high",
        "description": "param concatenated", "evidence": ["app/db.py:42"],
        "sink_name": "cursor.execute", "call_sites": ["cursor.execute(q)"],
        "expected_signature": "cursor.execute(q)",
    }])


def test_wiring_prefers_codeql(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    # Force codeql enabled + inject a codeql_scan that yields findings.
    monkeypatch.setenv("NGV2_CODEQL_LEADS", "1")
    monkeypatch.setattr(hlc, "_codeql_enabled", lambda: True)
    real_findings = mod.codeql_scan(repo, runner=_scripted_runner(), languages=["python"])

    import ngv2.codeql_lead_source as cls
    monkeypatch.setattr(cls, "codeql_scan", lambda r, **k: real_findings)

    client = hlc.make_hunt_lead_client(complete=_stub_agy_complete)
    out = client(target="acme", context={"repo": repo})
    cands = out["candidates"]
    assert cands, "codeql should have produced candidates"
    # CodeQL preferred over agy: source is codeql, category is CWE-78 (not 89)
    assert cands[0]["source"] == "codeql"
    assert cands[0]["category"] == "CWE-78"


def test_wiring_disabled_falls_back_to_agy(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    monkeypatch.setenv("NGV2_CODEQL_LEADS", "0")  # explicitly disabled
    client = hlc.make_hunt_lead_client(complete=_stub_agy_complete)
    out = client(target="acme", context={"repo": repo})
    cands = out["candidates"]
    assert cands, "agy path should produce candidates"
    # agy candidate, NOT codeql
    assert cands[0]["category"] == "CWE-89"
    assert cands[0].get("source") != "codeql"


def test_wiring_codeql_empty_falls_back(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(hlc, "_codeql_enabled", lambda: True)
    import ngv2.codeql_lead_source as cls
    monkeypatch.setattr(cls, "codeql_scan", lambda r, **k: [])  # no codeql leads
    client = hlc.make_hunt_lead_client(complete=_stub_agy_complete)
    out = client(target="acme", context={"repo": repo})
    assert out["candidates"][0]["category"] == "CWE-89"  # fell back to agy
