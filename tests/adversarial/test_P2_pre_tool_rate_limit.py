"""M9 — loop-until-6th-deny end-to-end rate-limit invariant.

Sub-plan 02 §4.2 row 4 pins the monotonic-counter invariant for
``submit_code``: five accepted submissions permitted per session,
the sixth must deny with ``outcome=rate_limited``.  The existing
``tests/hooks/unit/test_claude_pre_tool.py::TestWriteSubmissionSynthesis``
cases seed the ledger via ``_ledger.append_hook_event`` with synthesised
rows and then fire one hook invocation — so the counter *logic* is
proved, but the monotonic-counter *invariant over a real sequence of
PreToolUse calls* is not.

This adversarial test closes that gap: it drives the
``harness.hooks.claude.pre_tool.main`` entrypoint six times
sequentially, each iteration appending the *real* ledger row the
hook's post-write peer (``harness.hooks.claude.post_tool``) would
append on an accepted write, and asserts:

    iter 1..5: decision=="allow"   + new submit_code/allow row on disk
    iter 6   : decision=="deny"    + reason mentions rate limit
                                   + ``rate_limited`` row on disk
                                   + no extra submit_code/allow row
                                     ever appears past iter 5

The loop stages each accept's ledger row between iterations rather
than relying on any in-process counter, so the hook is forced to
re-open + re-read the JSONL ledger file each call.  That is the
exact data path production uses (hooks are short-lived subprocesses
with no shared state except the ledger).

This file lives under ``tests/adversarial/test_P2_*.py`` — which is
covered by the META-phase scope exception registered in the
``impl_progress.jsonl`` ledger for this audit round.
"""

from __future__ import annotations

import io
import json
import pathlib

import pytest

import harness.hooks.claude.pre_tool as pre_tool
from harness.hooks import _ledger


_CLEAN_CODE = "def add(a, b):\n    return a + b\n"


def _stage(tmp_path, monkeypatch, *, mode="synthesis"):
    """Mirror the fixture from test_P2_pre_tool.py but with a
    dedicated session id so we never collide with the other suite."""
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "claude" / "sess-rl"
    (workdir / "inbox").mkdir(parents=True)
    (workdir / "outbox").mkdir(parents=True)
    (workdir / "inbox" / "task.json").write_text(
        json.dumps(
            {
                "task_id": "T-RL",
                "synthesis_target_type": "pure_function",
                "constraints": {"deterministic": True},
            }
        )
    )
    (state / "STATE.json").write_text(
        json.dumps({"round": 1, "phase": mode, "task_id": "T-RL"})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "claude")
    monkeypatch.setenv("JANUSMASK_MODE", mode)
    return {"state": state, "workdir": workdir, "session_id": "sess-rl"}


def _run(tool_name, tool_input, session_id):
    stdin = io.StringIO(
        json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "session_id": session_id,
                "tool_name": tool_name,
                "tool_input": tool_input,
            }
        )
    )
    stdout = io.StringIO()
    pre_tool.main(stdin, stdout)
    return json.loads(stdout.getvalue())


def _submit_code_allow_rows(rows):
    return [
        r
        for r in rows
        if r.get("verb") == "submit_code" and r.get("outcome") == "allow"
    ]


def _submit_code_rate_limited_rows(rows):
    return [
        r
        for r in rows
        if r.get("verb") == "submit_code"
        and r.get("outcome") == "rate_limited"
    ]


class TestMonotonicRateLimit:
    def test_loop_until_sixth_call_denies(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        target = str(env["workdir"] / "outbox" / "submission.py")
        session_id = env["session_id"]

        decisions: list[str] = []
        for i in range(1, 7):
            out = _run(
                "Write",
                {"file_path": target, "content": _CLEAN_CODE},
                session_id=session_id,
            )
            decisions.append(out["decision"])

            if i <= 5:
                assert out["decision"] == "allow", (
                    f"iter {i}: expected allow but got "
                    f"{out}"
                )
                # Mirror what post_tool would append on an accepted
                # submission — this is the only write that advances
                # the counter the hook reads on the next iteration.
                _ledger.append_hook_event(
                    session_id,
                    "claude",
                    "submit_code",
                    "allow",
                )
            else:
                assert out["decision"] == "deny", (
                    f"iter {i}: expected deny (6th call) but got {out}"
                )
                reason = (out.get("reason") or "").lower()
                assert (
                    "rate limit" in reason or "5/5" in reason
                ), (
                    "6th deny reason must mention the rate limit / "
                    f"5-of-5 counter; got {out.get('reason')!r}"
                )

        # Sanity on the accumulated sequence.
        assert decisions[:5] == ["allow"] * 5
        assert decisions[5] == "deny"

    def test_ledger_has_exactly_five_accepted_submit_code_rows(
        self, tmp_path, monkeypatch
    ):
        env = _stage(tmp_path, monkeypatch)
        target = str(env["workdir"] / "outbox" / "submission.py")
        session_id = env["session_id"]

        for i in range(1, 7):
            out = _run(
                "Write",
                {"file_path": target, "content": _CLEAN_CODE},
                session_id=session_id,
            )
            if i <= 5 and out["decision"] == "allow":
                _ledger.append_hook_event(
                    session_id,
                    "claude",
                    "submit_code",
                    "allow",
                )

        rows = _ledger.read_events(session_id, "claude")
        allows = _submit_code_allow_rows(rows)
        rate_limited = _submit_code_rate_limited_rows(rows)

        assert (
            len(allows) == 5
        ), f"expected exactly 5 submit_code/allow rows, got {len(allows)}"
        assert (
            len(rate_limited) >= 1
        ), (
            "expected at least one submit_code/rate_limited row after "
            f"the 6th call; got {len(rate_limited)}"
        )

    def test_seventh_call_still_denies_and_does_not_add_allow(
        self, tmp_path, monkeypatch
    ):
        """Monotonicity: once the counter tips over, it never slides
        back. Fire a 7th call and confirm the allow-count does not
        grow."""
        env = _stage(tmp_path, monkeypatch)
        target = str(env["workdir"] / "outbox" / "submission.py")
        session_id = env["session_id"]

        for _ in range(5):
            out = _run(
                "Write",
                {"file_path": target, "content": _CLEAN_CODE},
                session_id=session_id,
            )
            assert out["decision"] == "allow"
            _ledger.append_hook_event(session_id, "claude", "submit_code", "allow")

        sixth = _run(
            "Write",
            {"file_path": target, "content": _CLEAN_CODE},
            session_id=session_id,
        )
        assert sixth["decision"] == "deny"

        seventh = _run(
            "Write",
            {"file_path": target, "content": _CLEAN_CODE},
            session_id=session_id,
        )
        assert seventh["decision"] == "deny"

        rows = _ledger.read_events(session_id, "claude")
        assert len(_submit_code_allow_rows(rows)) == 5, (
            "a deny must never be silently reclassified as an allow; "
            "the accepted-submission counter must stay at 5."
        )

    def test_rate_limit_is_per_session(self, tmp_path, monkeypatch):
        """A different session id must start from zero — the 5-cap is
        a per-session bound, not a per-agent one. Guards against a
        ledger-path bug that accidentally shares state across
        sessions."""
        env = _stage(tmp_path, monkeypatch)
        target = str(env["workdir"] / "outbox" / "submission.py")

        for _ in range(5):
            _run(
                "Write",
                {"file_path": target, "content": _CLEAN_CODE},
                session_id="sess-rl",
            )
            _ledger.append_hook_event("sess-rl", "claude", "submit_code", "allow")

        # Pre-staged session hits the cap on the next call:
        capped = _run(
            "Write",
            {"file_path": target, "content": _CLEAN_CODE},
            session_id="sess-rl",
        )
        assert capped["decision"] == "deny"

        # Fresh session id starts clean.
        fresh = _run(
            "Write",
            {"file_path": target, "content": _CLEAN_CODE},
            session_id="sess-rl-fresh",
        )
        assert fresh["decision"] == "allow"
