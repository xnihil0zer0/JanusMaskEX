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
