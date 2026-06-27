"""Hermetic oracle for the agy-empty-hunt deterministic fallback.

RED on HEAD (no fallback), GREEN after the hunt_lead_client.py edit that wires
ngv2.pattern_scanner as a deterministic lead source when agy returns [].

No network, no agy, no state/. A fake `complete` seam is injected so the agy
path is fully controlled; the fallback scans a tmp fixture dir.
"""
from __future__ import annotations
import json
import os

import pytest

from ngv2 import hunt_lead_client


# --- agy candidate shape contract (keys downstream triage/poc consume) ---
_AGY_KEYS = {
    'id', 'target', 'category', 'sink_name', 'call_sites', 'severity',
    'evidence', 'title', 'description', 'expected_fs_signature',
    'success_marker',
}


def _fake_complete_returning(payload):
    def complete(messages, **kwargs):
        return payload
    return complete


def _write_fixture(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "cmd.py").write_text(
        "import subprocess\n"
        "def run(user):\n"
        "    subprocess.Popen(user, shell=True)\n"
    )
    (repo / "code.py").write_text(
        "def danger(user):\n"
        "    eval(user)\n"
    )
    (repo / "files.py").write_text(
        "def read(filename, request):\n"
        "    return open(os.path.join('/data', request.args['filename']))\n"
    )
    return str(repo)


# (1) agy returns leads -> fallback NOT invoked, candidates unchanged.
def test_agy_leads_present_no_fallback(tmp_path):
    repo = _write_fixture(tmp_path)
    leads = json.dumps([
        {"title": "real agy lead", "category": "CWE-89", "severity": "high",
         "evidence": ["x.py:1"], "sink_name": "execute",
         "call_sites": ["cur.execute('...'+x)"], "expected_signature": "execute"}
    ])
    client = hunt_lead_client.make_hunt_lead_client(
        complete=_fake_complete_returning(leads))
    out = client(target="t", context={"repo": repo})
    cands = out["candidates"]
    assert len(cands) == 1
    assert cands[0]["title"] == "real agy lead"
    # fallback never ran: sink_name is the agy one, not a scanner-derived one
    assert cands[0]["sink_name"] == "execute"


# (2) agy returns [] -> fallback scans the fixture; accurate sink_name/category.
def test_agy_empty_triggers_scanner_fallback(tmp_path):
    repo = _write_fixture(tmp_path)
    client = hunt_lead_client.make_hunt_lead_client(
        complete=_fake_complete_returning("[]"))
    out = client(target="t", context={"repo": repo})
    cands = out["candidates"]
    assert cands, "fallback must surface candidates when agy returns []"
    for c in cands:
        # shape matches the agy candidate contract exactly
        missing = _AGY_KEYS - set(c.keys())
        assert not missing, "fallback candidate missing keys: {}".format(missing)
        assert isinstance(c["call_sites"], list) and c["call_sites"]
        assert isinstance(c["evidence"], list) and c["evidence"]
        assert ":" in c["evidence"][0], "evidence must be path:line"
        assert c["target"] == "t"
    sinks = {c["sink_name"] for c in cands}
    cats = {c["category"] for c in cands}
    # accurate sink extraction via sink_extract
    assert "subprocess.Popen" in sinks
    assert "eval" in sinks
    assert "CWE-78" in cats   # subprocess.Popen
    assert "CWE-95" in cats   # eval
    # path/open sink present (CWE-22)
    assert "CWE-22" in cats


# (3) determinism: two runs over the same fixture -> identical ordering.
def test_fallback_deterministic(tmp_path):
    repo = _write_fixture(tmp_path)
    client = hunt_lead_client.make_hunt_lead_client(
        complete=_fake_complete_returning("[]"))
    a = client(target="t", context={"repo": repo})["candidates"]
    b = client(target="t", context={"repo": repo})["candidates"]
    assert [c["sink_name"] for c in a] == [c["sink_name"] for c in b]
    assert [c["evidence"] for c in a] == [c["evidence"] for c in b]
    assert [c["id"] for c in a] == [c["id"] for c in b]


# (4) fail-soft: scanner raising -> original empty result, no exception.
def test_fallback_failsoft_on_scanner_error(tmp_path, monkeypatch):
    repo = _write_fixture(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("scanner exploded")

    monkeypatch.setattr(hunt_lead_client.pattern_scanner, "scan_directory", boom)
    client = hunt_lead_client.make_hunt_lead_client(
        complete=_fake_complete_returning("[]"))
    out = client(target="t", context={"repo": repo})
    assert out == {"candidates": []}
