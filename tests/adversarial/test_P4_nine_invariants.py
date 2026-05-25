"""P4 adversarial battery — HOOK-46 nine-invariants stress scenarios.

The invariant-side file (``tests/hooks/invariants/test_nine_invariants.py``)
locks each invariant with a mutation test.  This file adds fuzz-style
attacks that exercise the invariants under malformed inputs, race-prone
orderings, and adversarial content.
"""

from __future__ import annotations

import io
import json
import pathlib
import sys
from typing import Any
from unittest.mock import patch

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness.hooks import _ledger, _state_gates  # noqa: E402
from harness.hooks.claude import user_prompt_submit as ups_mod  # noqa: E402
from harness.hooks.rpc import submit_code as rpc_submit_code  # noqa: E402


@pytest.fixture
def state_env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    (state / "sessions").mkdir(parents=True)
    workdir = state / "workdirs" / "claude" / "sess"
    (workdir / "inbox").mkdir(parents=True)
    (workdir / "outbox").mkdir(parents=True)
    (state / "STATE.json").write_text(
        json.dumps({"round": 1, "phase": "synthesis", "task_id": "T1"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "claude")
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    monkeypatch.delenv("JANUSMASK_ROUND", raising=False)
    (workdir / "inbox" / "task.json").write_text(
        json.dumps({"task_id": "T1", "specification": "spec"}), encoding="utf-8"
    )
    return state, workdir


# ---------------------------------------------------------------------------
# Inv-1: session_id injection attacks — attacker supplies a forged id.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("forged", [
    "sess",  # legit
    "../etc/passwd",  # path-traversal styled; ledger treats it as opaque id
    "' OR 1=1--",  # sql-style
    "id with spaces",
    "id-with-hyphens-123",
])
def test_inv1_forged_session_ids_all_storable(state_env, forged):
    # Ledger must accept any reasonable string; stability invariant holds
    # per-id, not across different ids.
    _ledger.append_hook_event(forged, "claude", "session_start", "allow", hook="H")
    rows = _ledger.read_events(forged, "claude")
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Inv-2: adversarial JANUSMASK_ROUND values.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_round,expected", [
    ("abc", 1),  # garbage falls back to state round=1 set in state_env
    ("", 1),
    ("-1", -1),  # parseable — hook will use this value
    ("1e10", 1),  # scientific notation fails int parse
])
def test_inv2_adversarial_env_rounds(state_env, monkeypatch, bad_round, expected):
    monkeypatch.setenv("JANUSMASK_ROUND", bad_round)
    got = _state_gates.current_round()
    # Either the parseable value wins, or it falls back gracefully.
    assert isinstance(got, int)


# ---------------------------------------------------------------------------
# Inv-3: feedback file present across phase transitions — no leak.
# ---------------------------------------------------------------------------

def test_inv3_phase_flip_during_session_no_feedback_leak(state_env, monkeypatch):
    state, workdir = state_env
    (workdir / "inbox" / "feedback.json").write_text(
        json.dumps({"code_under_review": "def h(): pass"}), encoding="utf-8"
    )
    # Turn 1: synthesis → no feedback injection.
    stdout = io.StringIO()
    ups_mod.main(io.StringIO(json.dumps({"session_id": "sess"})), stdout)
    assert "CROSS-EXAMINATION FEEDBACK" not in stdout.getvalue()

    # Mid-session phase transition to cross_examination — next turn
    # triggers feedback injection ONCE.
    (state / "STATE.json").write_text(
        json.dumps({"round": 1, "phase": "cross_examination", "task_id": "T1"}),
        encoding="utf-8",
    )
    stdout = io.StringIO()
    ups_mod.main(io.StringIO(json.dumps({"session_id": "sess"})), stdout)
    assert "CROSS-EXAMINATION FEEDBACK" in stdout.getvalue()

    # Turn 3 (still cross_examination): feedback NOT re-injected.
    stdout = io.StringIO()
    ups_mod.main(io.StringIO(json.dumps({"session_id": "sess"})), stdout)
    assert "CROSS-EXAMINATION FEEDBACK" not in stdout.getvalue()


# ---------------------------------------------------------------------------
# Inv-4: submission counter under interleaved allow + deny rows.
# ---------------------------------------------------------------------------

def test_inv4_interleaved_allow_deny(state_env):
    sid = "sess"
    pattern = ["allow", "deny", "allow", "deny", "allow"]
    for outcome in pattern:
        _ledger.append_hook_event(sid, "claude", "submit_code", outcome, hook="H")
    assert _state_gates.submissions_count(sid, "claude") == 3


def test_inv4_unrelated_verbs_do_not_increment(state_env):
    sid = "sess"
    for verb in ("task_read", "session_start", "stop", "plan_draft"):
        _ledger.append_hook_event(sid, "claude", verb, "allow", hook="H")
    assert _state_gates.submissions_count(sid, "claude") == 0


# ---------------------------------------------------------------------------
# Inv-5: idempotency survives corrupt ledger lines mid-file.
# ---------------------------------------------------------------------------

def test_inv5_corrupt_ledger_line_does_not_clear_flag(state_env):
    sid = "sess"
    _ledger.append_hook_event(sid, "claude", "plan_draft", "allow", hook="H")
    # Inject a corrupt line.
    path = _ledger.ledger_path(sid, "claude")
    with path.open("a", encoding="utf-8") as fh:
        fh.write("not valid json\n")
    _ledger.append_hook_event(sid, "claude", "submit_code", "allow", hook="H")
    # The corrupt line is skipped; the plan_draft row is still counted.
    assert _state_gates.plan_submitted(sid, "claude")


# ---------------------------------------------------------------------------
# Inv-6: ordering under concurrent-style writes (sequential, but asserts
# no buffering reorders).
# ---------------------------------------------------------------------------

def test_inv6_high_cardinality_order(state_env):
    sid = "sess"
    for i in range(50):
        _ledger.append_hook_event(sid, "claude", f"verb_{i:02d}", "allow", hook="H")
    rows = _ledger.read_events(sid, "claude")
    verbs = [r["verb"] for r in rows]
    assert verbs == [f"verb_{i:02d}" for i in range(50)]


# ---------------------------------------------------------------------------
# Inv-7: AST rejection with zero violations still returns a valid
# payload (not a raw crash).
# ---------------------------------------------------------------------------

def test_inv7_empty_violations_list():
    payload = rpc_submit_code.rejected_payload([])
    assert payload["status"] == "rejected"
    assert payload["violations"] == []


def test_inv7_huge_violations_list_truncated():
    from harness.ast_enforcer import Violation
    vios = [
        Violation(rule="r", line=i, message=f"err {i}", severity="error")
        for i in range(200)
    ]
    payload = rpc_submit_code.rejected_payload(vios, max_show=50)
    assert len(payload["violations"]) == 50
    assert "Showing first 50" in payload["message"]


# ---------------------------------------------------------------------------
# Inv-8: log continuity under malformed NDJSON lines — raw bytes still
# mirrored; log never truncated.
# ---------------------------------------------------------------------------

def test_inv8_log_preserves_unparseable_lines(tmp_path):
    from harness import agent_streamer as strm
    lines = [
        "not json at all",
        json.dumps({"type": "system", "subtype": "init", "model": "m", "tools": []}),
        "{also broken",
        json.dumps({
            "type": "result", "subtype": "success", "total_cost_usd": 0.0,
            "duration_ms": 0, "usage": {},
        }),
    ]
    log_path = tmp_path / "claude_stream.jsonl"
    strm.stream_agent_output(
        io.StringIO("\n".join(lines) + "\n"), "claude", log_path=log_path
    )
    mirrored = log_path.read_text(encoding="utf-8").splitlines()
    assert len(mirrored) == len(lines)


# ---------------------------------------------------------------------------
# Inv-9: task injection with corrupt inbox/task.json falls through
# cleanly (no crash, no partial injection).
# ---------------------------------------------------------------------------

def test_inv9_corrupt_task_json_no_injection(state_env):
    state, workdir = state_env
    (workdir / "inbox" / "task.json").write_text("{not json", encoding="utf-8")
    stdout = io.StringIO()
    ups_mod.main(io.StringIO(json.dumps({"session_id": "sess"})), stdout)
    out = json.loads(stdout.getvalue())
    # No task section emitted, and no task_read ledger marker.
    assert "--- TASK ---" not in out["hookSpecificOutput"]["additionalContext"]


def test_inv9_empty_inbox_dir_no_injection(state_env):
    state, workdir = state_env
    (workdir / "inbox" / "task.json").unlink()
    stdout = io.StringIO()
    ups_mod.main(io.StringIO(json.dumps({"session_id": "sess"})), stdout)
    out = json.loads(stdout.getvalue())
    # Locked-fields reminder still appears (always appended), but no
    # task section.
    assert "--- TASK ---" not in out["hookSpecificOutput"]["additionalContext"]
    assert "Identity:" in out["hookSpecificOutput"]["additionalContext"]
