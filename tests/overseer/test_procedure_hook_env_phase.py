"""RED oracle: the PreToolUse hook reads the active phase from the spawn env.

Real Claude Code PreToolUse events carry ``tool_name``/``tool_input``/``cwd`` --
*never* the procedure phase. So for the registered hook to be anything but inert,
``decide`` must fall back to the ``JANUSMASK_PROCEDURE_PHASE`` env var (exported
into the spawn by ``turn_runner.make_seams``) when the event itself carries no
phase. An explicit event ``phase`` still wins; an unset env with no event phase
fails *open* (inert) so non-procedure spawns behave exactly as before.

Pure, stdlib-only: no spawn, no I/O, no test execution.
"""
import json

from overseer.procedure_hook import decide


def test_env_phase_blocks_out_of_phase_brief_write(monkeypatch):
    """A pre-BRIEF env phase blocks a brief_hooks_* Write with no event phase."""
    monkeypatch.setenv("JANUSMASK_PROCEDURE_PHASE", "SCOPE")
    decision = decide({"tool_name": "Write",
                       "tool_input": {"file_path": "brief_hooks_x.md"}})
    assert decision["decision"] == "block"
    blob = json.dumps(decision).lower()
    assert "deny" in blob or "block" in blob


def test_event_phase_wins_over_env(monkeypatch):
    """An explicit event ``phase`` overrides the env var."""
    monkeypatch.setenv("JANUSMASK_PROCEDURE_PHASE", "SCOPE")
    decision = decide({"tool_name": "Write",
                       "tool_input": {"file_path": "brief_hooks_x.md"},
                       "phase": "COMPLETE"})
    assert decision["decision"] == "allow"
    blob = json.dumps(decision).lower()
    assert "deny" not in blob and "block" not in blob


def test_unset_env_no_event_phase_is_inert(monkeypatch):
    """With no env phase and no event phase, the hook never blocks (fail-open)."""
    monkeypatch.delenv("JANUSMASK_PROCEDURE_PHASE", raising=False)
    decision = decide({"tool_name": "Write",
                       "tool_input": {"file_path": "brief_hooks_x.md"}})
    assert decision["decision"] == "allow"


def test_read_only_tool_allowed_regardless_of_env(monkeypatch):
    """A read-only tool is consistent with any active phase, env or not."""
    monkeypatch.setenv("JANUSMASK_PROCEDURE_PHASE", "SCOPE")
    decision = decide({"tool_name": "Read",
                       "tool_input": {"file_path": "overseer/driver.py"}})
    assert decision["decision"] == "allow"
