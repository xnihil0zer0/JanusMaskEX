"""RED oracle for overseer/mode_prompts.py — per-mode procedure guidance.

MODE_PROMPTS holds the system-prompt/procedure text per mode; render_mode_context
is the SessionStart additionalContext analog ("you are in mode=X, tier=Y, you may
do A/B/C, you may NOT do D"). Every mode must be covered.
"""
import pytest

from overseer.modes import MODE_REGISTRY
from overseer.mode_prompts import MODE_PROMPTS, render_mode_context

TIER_S = {"flag-steward", "harness-self-fix", "security-review", "rebuild-factory", "push"}


def test_every_mode_has_prompt_text():
    assert set(MODE_PROMPTS) == set(MODE_REGISTRY)
    for name, text in MODE_PROMPTS.items():
        assert isinstance(text, str)
        assert text.strip()  # non-empty


@pytest.mark.parametrize("name", sorted(MODE_REGISTRY))
def test_render_mode_context_states_the_mode_and_tier(name):
    state = {"current_mode": name, "unlocked_modes": []}
    ctx = render_mode_context(name, state)
    assert isinstance(ctx, str)
    assert ctx.strip()
    assert name in ctx  # names the active mode
    assert MODE_REGISTRY[name].tier in ctx  # surfaces the tier


def test_render_rejects_unknown_mode():
    with pytest.raises(KeyError):
        render_mode_context("no-such-mode", {"current_mode": "no-such-mode"})


def test_tier_s_context_mentions_unlock_requirement():
    for name in TIER_S:
        ctx = render_mode_context(name, {"current_mode": name, "unlocked_modes": [name]})
        assert "unlock" in ctx.lower()


def test_read_only_context_signals_no_writes():
    ctx = render_mode_context("observe", {"current_mode": "observe", "unlocked_modes": []})
    low = ctx.lower()
    # The read-only constraint must be explicit in the procedure text.
    assert "read" in low


# --- state-derived procedure guidance (enforcement-integration leaf) ----------
# When the conversation state carries procedure phase info, render_mode_context
# surfaces the CURRENT phase, the single next action, and (when the last gate
# failed) its reason + fix hint — all read from durable state, never inferred.
# With no procedure_* keys present the base behaviour above is unchanged.

def test_render_includes_active_phase_and_next_action():
    state = {"current_mode": "brief-author", "unlocked_modes": [],
             "procedure_phase": "ORACLE",
             "procedure_next_action": "Draft the oracle tests for the task."}
    ctx = render_mode_context("brief-author", state)
    assert "ORACLE" in ctx
    assert "Draft the oracle tests for the task." in ctx


def test_render_surfaces_last_gate_failure_reason_and_fix():
    state = {"current_mode": "brief-author", "unlocked_modes": [],
             "procedure_phase": "COMMIT",
             "procedure_next_action": "Commit the oracle.",
             "procedure_last_gate": {"ok": False, "reason": "oracle not committed",
                                     "fix_hint": "git commit the test file"}}
    ctx = render_mode_context("brief-author", state)
    assert "oracle not committed" in ctx
    assert "git commit the test file" in ctx


def test_render_without_procedure_state_is_unchanged():
    ctx = render_mode_context("observe", {"current_mode": "observe", "unlocked_modes": []})
    assert "observe" in ctx and MODE_REGISTRY["observe"].tier in ctx
