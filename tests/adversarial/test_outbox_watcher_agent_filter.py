"""Adversarial characterization — impl_outbox_watcher agent-name filter (Plan 04, CASE-D/E/F).

GAP-1 (HIGH): ``scripts/impl_outbox_watcher.py`` filters scanned agent dirs to
``("claude", "gemini")`` (line 209) and parses the session slug with
``_SESSION_RE = ^(claude|gemini)-r...`` (line 40). Both ``claude_fallback`` and
``antigravity`` are REAL spawn agents (config.yaml ``agents`` block;
``orchestrator.py:517/541`` synthesis fallback; ``autowork_daemon.py:546``
default autobrief agent) that produce workdirs named ``claude_fallback`` /
``antigravity`` under ``agent_workroot()``. The async sidecar therefore SILENTLY
DROPS their outbox submissions — no canonical JSON, no ledger row.

These tests pin the CURRENT (buggy) behavior as characterization tests so they
flip to fix-detectors once the filter/regex are widened. CASE-E/F are positive
controls proving the claude/gemini path still writes JSON + ledger rows, making
the silent-drop asymmetry explicit. NO source is modified here.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import scripts.impl_outbox_watcher as watcher  # noqa: E402

_VALID_CODE = "def f(x):\n    return x + 1\n"
# Trips rpc_submit_code.ensure_valid (nondeterminism rule) — see probe.
_BAD_CODE = "import random\n\ndef f():\n    return random.random()\n"


@pytest.fixture(autouse=True)
def _isolate_agent_workroot(tmp_path, monkeypatch):
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(tmp_path / "agentwork"))


def _stage_submission(agent: str, code: str, *, round_no: int = 1, task: str = "T1",
                      suffix: str = "deadbeef") -> pathlib.Path:
    from harness.paths import agent_workroot
    slug = f"{agent}-r{round_no}-{task}-{suffix}"
    outbox = agent_workroot() / agent / slug / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    sub = outbox / "submission.py"
    sub.write_text(code, encoding="utf-8")
    return sub


def _sessions_jsons(state_dir: pathlib.Path) -> list[pathlib.Path]:
    sd = state_dir / "sessions"
    if not sd.is_dir():
        return []
    return [p for p in sd.iterdir() if p.suffix == ".json"]


def _ledger_rows(state_dir: pathlib.Path) -> list[dict]:
    sd = state_dir / "sessions"
    rows: list[dict] = []
    if not sd.is_dir():
        return rows
    for p in sd.glob("*.ledger.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


# --------------------------------------------------- CASE-D (H6: fallback persisted)


class TestSilentDropFallbackIdentities:
    """H6 fix-detectors (was characterization of the silent-drop GAP-1). The
    watcher now accepts the full spawn-agent set: _SESSION_RE (:40, hand-edit)
    parses the fallback slug and _scan_once's dir filter (:209, pipeline) accepts
    the fallback agent dir, so a claude_fallback / antigravity submission is
    persisted end-to-end (canonical JSON + allow ledger row)."""

    def test_claude_fallback_submission_persisted(self, tmp_path):
        """H6: a valid claude_fallback outbox submission is picked up end-to-end."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        _stage_submission("claude_fallback", _VALID_CODE)
        rc = watcher.main(["--state-dir", str(state_dir), "--once"])
        assert rc == 0
        assert len(_sessions_jsons(state_dir)) == 1, (
            "claude_fallback submission must be persisted (filter + regex widened)"
        )
        allow = [r for r in _ledger_rows(state_dir) if r.get("outcome") == "allow"]
        assert len(allow) == 1
        assert allow[0]["detail"]["source"] == "outbox_watcher"
        assert allow[0]["agent"] == "claude_fallback"

    def test_antigravity_submission_persisted(self, tmp_path):
        """H6 companion: antigravity (default autobrief agent) also persisted."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        _stage_submission("antigravity", _VALID_CODE)
        rc = watcher.main(["--state-dir", str(state_dir), "--once"])
        assert rc == 0
        assert len(_sessions_jsons(state_dir)) == 1, (
            "antigravity submission must be persisted (filter + regex widened)"
        )
        allow = [r for r in _ledger_rows(state_dir) if r.get("outcome") == "allow"]
        assert len(allow) == 1 and allow[0]["agent"] == "antigravity"

    def test_session_regex_accepts_fallback_slug(self):
        """H6 (:40): _SESSION_RE now parses the claude_fallback / antigravity
        prefixes (the regex half of the fix)."""
        assert watcher._parse_session("claude_fallback-r1-T1-deadbeef") is not None
        assert watcher._parse_session("antigravity-r1-T1-deadbeef") is not None
        # claude_fallback parses as its own agent, not as a "claude" prefix match.
        parsed = watcher._parse_session("claude_fallback-r1-T1-deadbeef")
        assert parsed[0] == "claude_fallback"
        # control: claude/gemini still parse fine
        assert watcher._parse_session("claude-r1-T1-deadbeef") is not None
        assert watcher._parse_session("gemini-r2-T9-abcd1234") is not None


# --------------------------------------------------------- CASE-E (control: accept)


class TestAcceptCanonicalAgents:
    def test_claude_valid_submission_accepted(self, tmp_path):
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        _stage_submission("claude", _VALID_CODE)
        rc = watcher.main(["--state-dir", str(state_dir), "--once"])
        assert rc == 0
        jsons = _sessions_jsons(state_dir)
        assert len(jsons) == 1, "expected exactly one canonical submission JSON"
        rows = _ledger_rows(state_dir)
        allow = [r for r in rows if r.get("outcome") == "allow"]
        assert len(allow) == 1
        assert allow[0]["detail"]["source"] == "outbox_watcher"
        assert allow[0]["agent"] == "claude"

    def test_gemini_valid_submission_accepted(self, tmp_path):
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        _stage_submission("gemini", _VALID_CODE)
        rc = watcher.main(["--state-dir", str(state_dir), "--once"])
        assert rc == 0
        assert len(_sessions_jsons(state_dir)) == 1
        allow = [r for r in _ledger_rows(state_dir) if r.get("outcome") == "allow"]
        assert len(allow) == 1 and allow[0]["agent"] == "gemini"

    def test_process_submission_returns_accept_directly(self, tmp_path):
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        sub = _stage_submission("claude", _VALID_CODE)
        assert watcher._process_submission(state_dir, sub) == "accept"


# --------------------------------------------------------- CASE-F (deny path)


class TestDenyPathLedger:
    def test_ast_violation_lands_deny_ledger_no_json(self, tmp_path):
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        sub = _stage_submission("claude", _BAD_CODE)
        outcome = watcher._process_submission(state_dir, sub)
        assert outcome == "deny"
        # No canonical JSON written on deny.
        assert _sessions_jsons(state_dir) == []
        deny = [r for r in _ledger_rows(state_dir) if r.get("outcome") == "deny"]
        assert len(deny) == 1
        d = deny[0]["detail"]
        assert d["reason"] == "persist_time_ast_gate"
        assert d["source"] == "outbox_watcher"
        assert d["error_count"] >= 1
        assert d["violations"], "deny row must carry non-empty violations list"
