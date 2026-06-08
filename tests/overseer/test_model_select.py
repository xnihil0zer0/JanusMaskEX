"""RED oracle for overseer/model_select.py — model dropdown resolution.

claude takes ``--model opus|sonnet|haiku``; agy (compiled Antigravity/Gemini
binary) has NO --model flag and self-selects, so it resolves to an empty argv.
Unknown agent/model are rejected (no silent fallthrough).
"""
import pytest

from overseer.model_select import AVAILABLE_MODELS, resolve_model_argv


def test_available_models_lists_claude_tiers_and_agy_has_no_pick():
    assert AVAILABLE_MODELS["claude"] == ["opus", "sonnet", "haiku"]
    # agy self-selects internally — no operator model choice.
    assert list(AVAILABLE_MODELS["agy"]) == []


@pytest.mark.parametrize("model", ["opus", "sonnet", "haiku"])
def test_claude_resolves_to_model_flag(model):
    assert resolve_model_argv("claude", model) == ["--model", model]


def test_agy_resolves_to_empty_argv_regardless_of_request():
    assert resolve_model_argv("agy", None) == []
    assert resolve_model_argv("agy", "opus") == []  # request ignored for agy


def test_unknown_claude_model_is_rejected():
    with pytest.raises(ValueError):
        resolve_model_argv("claude", "gpt-4")


def test_unknown_agent_is_rejected():
    with pytest.raises(ValueError):
        resolve_model_argv("not-an-agent", "opus")


def test_claude_requires_a_model_choice():
    # claude has real model tiers, so None/empty is not a valid pick.
    with pytest.raises(ValueError):
        resolve_model_argv("claude", None)
