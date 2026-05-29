"""P4 adversarial battery — HOOK-40 orchestrator env flow.

Mutation tests per augmented plan §5 P4 row: revert the fix and
confirm the tests here would catch the regression. The invariant
(sub-plan 04 §3.11 + HOOK-30 authoritative settings contract at
``harness/hooks/gemini/session_start.py:80-92``):

    Every JANUSMASK_* key a worker hook reads off the environment
    must be populated by ``_build_agent_env`` on every spawn, and
    the Gemini settings pointer the orchestrator chooses by default
    must point at a real file with ``security.folderTrust.enabled=true``
    — otherwise the HOOK-30 session_start hook hard-denies on turn 0.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from unittest import mock

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness import orchestrator as orch_mod  # noqa: E402


REQUIRED_KEYS = {
    "JANUSMASK_AGENT",
    "JANUSMASK_STATE_DIR",
    "JANUSMASK_ROUND",
    "JANUSMASK_MODE",
    "JANUSMASK_TASK_ID",
}


@pytest.fixture(autouse=True)
def _clear_janusmask_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("JANUSMASK_"):
            monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Attack 1: all required keys present on every spawn
# ---------------------------------------------------------------------------

def test_claude_env_contains_all_required_keys():
    env = orch_mod._build_agent_env("claude", "/tmp/sd", round_number=1)
    missing = REQUIRED_KEYS - env.keys()
    assert not missing, f"claude env missing keys: {missing}"


def test_gemini_env_contains_all_required_keys_plus_settings():
    env = orch_mod._build_agent_env("gemini", "/tmp/sd", round_number=1)
    missing = REQUIRED_KEYS - env.keys()
    assert not missing, f"gemini env missing keys: {missing}"
    assert "JANUSMASK_GEMINI_SETTINGS" in env


# ---------------------------------------------------------------------------
# Attack 2: the default gemini settings path must be wire-compatible with
# the HOOK-30 session_start contract (file exists, valid JSON, folderTrust
# enabled). If any of these three fail, the first Gemini spawn denies on
# turn 0 and the orchestrator never gets a submission.
# ---------------------------------------------------------------------------

def test_default_gemini_settings_path_resolves_to_existing_file():
    env = orch_mod._build_agent_env("gemini", "/tmp/sd", round_number=1)
    p = pathlib.Path(env["JANUSMASK_GEMINI_SETTINGS"])
    assert p.is_file(), f"gemini settings path does not exist: {p}"


def test_default_gemini_settings_is_valid_json_object():
    env = orch_mod._build_agent_env("gemini", "/tmp/sd", round_number=1)
    text = pathlib.Path(env["JANUSMASK_GEMINI_SETTINGS"]).read_text(encoding="utf-8")
    data = json.loads(text)
    assert isinstance(data, dict)


def test_default_gemini_settings_has_folder_trust_enabled():
    env = orch_mod._build_agent_env("gemini", "/tmp/sd", round_number=1)
    data = json.loads(
        pathlib.Path(env["JANUSMASK_GEMINI_SETTINGS"]).read_text(encoding="utf-8")
    )
    enabled = data.get("security", {}).get("folderTrust", {}).get("enabled")
    assert enabled is True, (
        "gemini_settings.json must set security.folderTrust.enabled=true "
        "or HOOK-30 denies on turn 0 (session_start.py:160-175)."
    )


# ---------------------------------------------------------------------------
# Attack 3: mutation — revert _build_agent_env to pre-HOOK-40 shape and
# confirm the tests here catch the regression.
# ---------------------------------------------------------------------------

_LEGACY_KEYS = {
    "PYTHONHASHSEED",
    "JANUSMASK_AGENT",
    "JANUSMASK_STATE_DIR",
    "JANUSMASK_ROUND",
}


def _legacy_build_agent_env(agent, state_dir, round_number=1):
    return {
        **os.environ,
        "PYTHONHASHSEED": "0",
        "JANUSMASK_AGENT": agent,
        "JANUSMASK_STATE_DIR": state_dir,
        "JANUSMASK_ROUND": str(round_number),
    }


def test_mutation_revert_drops_mode_and_task_id(monkeypatch):
    with mock.patch.object(orch_mod, "_build_agent_env", _legacy_build_agent_env):
        env = orch_mod._build_agent_env("claude", "/tmp/sd")
        assert "JANUSMASK_MODE" not in env
        assert "JANUSMASK_TASK_ID" not in env

    # Post-fix (un-patched): both keys are present.
    env = orch_mod._build_agent_env("claude", "/tmp/sd")
    assert env["JANUSMASK_MODE"] == "synthesis"
    assert env["JANUSMASK_TASK_ID"] == ""


def test_mutation_revert_drops_gemini_settings_pointer(monkeypatch):
    with mock.patch.object(orch_mod, "_build_agent_env", _legacy_build_agent_env):
        env = orch_mod._build_agent_env("gemini", "/tmp/sd")
        assert "JANUSMASK_GEMINI_SETTINGS" not in env

    env = orch_mod._build_agent_env("gemini", "/tmp/sd")
    assert "JANUSMASK_GEMINI_SETTINGS" in env


# ---------------------------------------------------------------------------
# Attack 4: env adversary — an upstream caller sets a bogus JANUSMASK_MODE
# or a malicious GEMINI_SETTINGS path. The orchestrator must pass these
# through *verbatim*, so the hook can reject them on its own terms.
# Silent normalisation here would mask an upstream contract bug.
# ---------------------------------------------------------------------------

def test_unknown_mode_passed_through_not_silently_normalised(monkeypatch):
    monkeypatch.setenv("JANUSMASK_MODE", "compromised")
    env = orch_mod._build_agent_env("gemini", "/tmp/sd")
    assert env["JANUSMASK_MODE"] == "compromised"


def test_caller_gemini_settings_override_honoured(monkeypatch):
    monkeypatch.setenv("JANUSMASK_GEMINI_SETTINGS", "/opt/override.json")
    env = orch_mod._build_agent_env("gemini", "/tmp/sd")
    assert env["JANUSMASK_GEMINI_SETTINGS"] == "/opt/override.json"


def test_empty_task_id_explicit_not_missing():
    # The hook can distinguish "no task active" (empty string) from
    # "env var dropped entirely" (key missing). Choose the former so
    # contract bugs stand out.
    env = orch_mod._build_agent_env("claude", "/tmp/sd")
    assert env["JANUSMASK_TASK_ID"] == ""


# ---------------------------------------------------------------------------
# Attack 5: spawn_agent threads the env dict through to Popen without
# dropping any key — the orchestrator is only one link in the chain.
# ---------------------------------------------------------------------------

def _spawn_capture(monkeypatch, tmp_path, agent):
    captured: dict = {}

    class _FakePopen:
        def __init__(self, cmd, **kwargs):
            captured["env"] = kwargs.get("env", {})
            captured["cmd"] = cmd
            self.pid = 99

    monkeypatch.setattr(orch_mod.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(orch_mod, "start_stream_threads", lambda *a, **k: ())

    # CONTAIN C5: claude spawns are fail-closed on a PreToolUse-declaring
    # --settings file (orchestrator._assert_claude_hook_config, unconditional for
    # agent=='claude'). Prod claude always carries one; supply the real worker
    # settings so this env-plumbing fixture exercises the spawn path, not the gate.
    args = ["-p"]
    if agent == "claude":
        args += ["--settings", str(PROJECT_ROOT / "config" / "claude_worker_hooks.json")]
    config = {
        "state_dir": str(tmp_path),
        "agents": {
            agent: {
                "command": agent,
                "args": args,
            }
        },
    }
    orch_mod.spawn_agent(agent, "prompt", config, round_number=3)
    return captured


def test_spawn_threads_claude_env_to_popen(tmp_path, monkeypatch):
    captured = _spawn_capture(monkeypatch, tmp_path, "claude")
    env = captured["env"]
    missing = REQUIRED_KEYS - env.keys()
    assert not missing, f"claude spawn dropped: {missing}"


def test_spawn_threads_gemini_env_to_popen_including_settings(tmp_path, monkeypatch):
    captured = _spawn_capture(monkeypatch, tmp_path, "gemini")
    env = captured["env"]
    missing = REQUIRED_KEYS - env.keys()
    assert not missing, f"gemini spawn dropped: {missing}"
    assert "JANUSMASK_GEMINI_SETTINGS" in env
    assert env["JANUSMASK_AGENT"] == "gemini"
    assert env["JANUSMASK_ROUND"] == "3"


# ---------------------------------------------------------------------------
# Attack 6: build call does not mutate os.environ (sandbox isolation)
# ---------------------------------------------------------------------------

def test_build_does_not_mutate_parent_os_environ(monkeypatch):
    # Parent has no JANUSMASK_MODE.
    assert "JANUSMASK_MODE" not in os.environ
    orch_mod._build_agent_env("gemini", "/tmp/sd", round_number=1)
    # Building the child env must not leak keys into the parent.
    assert "JANUSMASK_MODE" not in os.environ
    assert "JANUSMASK_GEMINI_SETTINGS" not in os.environ
