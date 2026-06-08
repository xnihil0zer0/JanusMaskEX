"""RED oracle for overseer/procedure_hook.py — the agent-boundary hard-block.

A PreToolUse hook that DENIES a raw tool call inconsistent with the active
procedure phase, closing the gap where the jailed agent could bypass the
structured action seam with a raw tool (e.g. Write a brief before the ORACLE +
COMMIT phases have passed). The deny logic is a PURE, stdlib-only decision over
(tool_name, tool_input, phase) — no spawn, no I/O, no test execution. ``decide``
maps a PreToolUse event dict to an allow/deny decision dict.
"""
import json

from overseer.procedure_hook import evaluate, decide


# --- the pure phase/tool deny rule -------------------------------------------

def test_write_to_brief_denied_before_brief_phase():
    allow, reason = evaluate("Write", {"file_path": "brief_hooks_foo.md"}, phase="ORACLE")
    assert allow is False
    assert "brief" in reason.lower()


def test_write_to_brief_allowed_at_brief_phase():
    allow, _ = evaluate("Write", {"file_path": "brief_hooks_foo.md"}, phase="BRIEF")
    assert allow is True


def test_unrelated_read_is_always_allowed():
    allow, _ = evaluate("Read", {"file_path": "overseer/driver.py"}, phase="SCOPE")
    assert allow is True


def test_no_active_phase_allows_everything():
    # no procedure active (phase None / COMPLETE) -> the hook never blocks.
    assert evaluate("Write", {"file_path": "brief_hooks_foo.md"}, phase=None)[0] is True
    assert evaluate("Write", {"file_path": "brief_hooks_foo.md"}, phase="COMPLETE")[0] is True


# --- the hook entrypoint maps an event to a decision -------------------------

def test_decide_blocks_an_out_of_phase_write():
    decision = decide({"tool_name": "Write",
                       "tool_input": {"file_path": "brief_hooks_x.md"},
                       "phase": "ORACLE"})
    assert isinstance(decision, dict)
    # the decision must be machine-readably a DENY (whatever the field shape,
    # it serializes to a deny/block signal with a reason).
    blob = json.dumps(decision).lower()
    assert "deny" in blob or "block" in blob


def test_decide_allows_an_in_phase_write():
    decision = decide({"tool_name": "Write",
                       "tool_input": {"file_path": "brief_hooks_x.md"},
                       "phase": "BRIEF"})
    blob = json.dumps(decision).lower()
    assert "deny" not in blob and "block" not in blob
