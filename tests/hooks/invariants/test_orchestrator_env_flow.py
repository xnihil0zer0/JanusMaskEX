"""P4 invariant: orchestrator -> worker env flow (HOOK-40).

Every `JANUSMASK_*` key a hook script reads off the environment must
be set by `_build_agent_env` on every worker spawn. Without this,
`harness/hooks/{claude,gemini}/*` fall back to ambiguous defaults
that let the worker start but silently skip enforcement (sub-plan
04 §3.11 + HOOK-30 authoritative-settings contract in
harness/hooks/gemini/session_start.py:80-92).
"""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from harness.orchestrator import PROJECT_DIR, _build_agent_env  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_janusmask_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("JANUSMASK_"):
            monkeypatch.delenv(key, raising=False)


def test_claude_env_has_required_keys():
    env = _build_agent_env("claude", "/tmp/state", round_number=3)
    assert env["JANUSMASK_AGENT"] == "claude"
    assert env["JANUSMASK_STATE_DIR"] == "/tmp/state"
    assert env["JANUSMASK_ROUND"] == "3"
    assert env["JANUSMASK_MODE"] == "synthesis"
    assert env["JANUSMASK_TASK_ID"] == ""


def test_gemini_env_has_required_keys():
    env = _build_agent_env("gemini", "/tmp/state", round_number=7)
    assert env["JANUSMASK_AGENT"] == "gemini"
    assert env["JANUSMASK_STATE_DIR"] == "/tmp/state"
    assert env["JANUSMASK_ROUND"] == "7"
    assert env["JANUSMASK_MODE"] == "synthesis"
    assert env["JANUSMASK_TASK_ID"] == ""


def test_gemini_env_includes_gemini_settings_pointer():
    env = _build_agent_env("gemini", "/tmp/state", round_number=1)
    expected = str(PROJECT_DIR / "config" / "gemini_settings.json")
    assert env["JANUSMASK_GEMINI_SETTINGS"] == expected


def test_claude_env_does_not_synthesise_gemini_settings():
    env = _build_agent_env("claude", "/tmp/state", round_number=1)
    assert "JANUSMASK_GEMINI_SETTINGS" not in env


def test_mode_pass_through(monkeypatch):
    monkeypatch.setenv("JANUSMASK_MODE", "planning")
    env = _build_agent_env("claude", "/tmp/state")
    assert env["JANUSMASK_MODE"] == "planning"


def test_mode_pass_through_reconciliation(monkeypatch):
    monkeypatch.setenv("JANUSMASK_MODE", "reconciliation")
    env = _build_agent_env("gemini", "/tmp/state")
    assert env["JANUSMASK_MODE"] == "reconciliation"


def test_task_id_pass_through(monkeypatch):
    monkeypatch.setenv("JANUSMASK_TASK_ID", "STAB-007")
    env = _build_agent_env("gemini", "/tmp/state")
    assert env["JANUSMASK_TASK_ID"] == "STAB-007"


def test_gemini_settings_caller_override(monkeypatch):
    monkeypatch.setenv("JANUSMASK_GEMINI_SETTINGS", "/custom/path.json")
    env = _build_agent_env("gemini", "/tmp/state")
    assert env["JANUSMASK_GEMINI_SETTINGS"] == "/custom/path.json"


def test_pythonhashseed_deterministic():
    env = _build_agent_env("claude", "/tmp/state", round_number=42)
    assert env["PYTHONHASHSEED"] == "0"


def test_round_num_stringified():
    env = _build_agent_env("claude", "/tmp/state", round_number=42)
    assert env["JANUSMASK_ROUND"] == "42"
    assert isinstance(env["JANUSMASK_ROUND"], str)


def test_state_dir_is_preserved_verbatim():
    # absolute path with non-ascii and spaces — the orchestrator must
    # not rewrite it, the hook does its own resolution.
    env = _build_agent_env("claude", "/opt/jm state/run 1", round_number=1)
    assert env["JANUSMASK_STATE_DIR"] == "/opt/jm state/run 1"


def test_returns_a_plain_dict_not_os_environ_mutation():
    # spreading os.environ must produce a new dict — mutating the
    # returned env must not leak to the parent process.
    before = os.environ.get("JANUSMASK_AGENT", "<missing>")
    env = _build_agent_env("claude", "/tmp/state")
    env["JANUSMASK_AGENT"] = "stomp"
    assert os.environ.get("JANUSMASK_AGENT", "<missing>") == before
