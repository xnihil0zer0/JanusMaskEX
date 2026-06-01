"""SEC-ENV — host-environment secret leak in ``_build_agent_env``.

``harness/orchestrator.py::_build_agent_env`` builds the environment dict
handed verbatim to the jailed agent subprocess (``Popen(..., env=env)`` in
``spawn_agent``). On HEAD it does ``{**os.environ, ...}`` — a blanket spread
of the FULL operator environment — so any operator secret on the host
(``GITHUB_TOKEN``, ``AWS_SECRET_ACCESS_KEY``, cloud creds, …) is copied into
the un-trusted agent's environment.

Fix: replace the blanket ``os.environ`` spread with a strict ALLOWLIST so
only known-safe vars (``PATH``/``HOME``/locale, ``JANUSMASK_*``, and the
vendor/CLI auth vars agy/claude actually need: ``XDG_*``, ``DBUS_*``,
``NVM_*``, ``GOOGLE_*``/``GEMINI_*``/``ANTHROPIC_*``/``CLAUDE_*``) pass
through. The keys the function sets EXPLICITLY (PYTHONHASHSEED,
CLAUDE_PROJECT_DIR, JANUSMASK_PROJECT_DIR, PYTHONPATH,
GEMINI_CLI_TRUST_WORKSPACE, every JANUSMASK_*, JANUSMASK_GEMINI_SETTINGS for
gemini) must be unchanged.

RED on HEAD: a sentinel secret placed in ``os.environ`` LEAKS into the
returned env (real assertion failure, not an import/collection error).
GREEN after the allowlist lands: the sentinel is scrubbed while every
required + auth var survives (so the allowlist does not break auth).
"""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from harness.orchestrator import PROJECT_DIR, _build_agent_env  # noqa: E402


# Synthetic operator secrets that must NEVER reach the un-trusted agent.
_LEAK_SENTINELS = {
    "JM_TEST_SHOULD_NOT_LEAK": "topsecret-sentinel-0xDEAD",
    "GITHUB_TOKEN": "ghp_sentinel_should_not_leak",
    "AWS_SECRET_ACCESS_KEY": "aws-sentinel-should-not-leak",
    "OPENAI_API_KEY": "sk-sentinel-should-not-leak",
}


@pytest.fixture
def _seed_secrets(monkeypatch):
    """Put synthetic operator secrets on the host env before the call."""
    for k, v in _LEAK_SENTINELS.items():
        monkeypatch.setenv(k, v)
    return _LEAK_SENTINELS


# ---------------------------------------------------------------------------
# Core leak assertions (RED on HEAD: sentinels leak through the blanket spread)
# ---------------------------------------------------------------------------

def test_host_secrets_do_not_leak_into_claude_env(_seed_secrets):
    env = _build_agent_env("claude", "/tmp/state", round_number=1)
    leaked = [k for k in _seed_secrets if k in env]
    assert not leaked, (
        f"_build_agent_env leaked operator secrets into the agent env: {leaked}. "
        "The env handed to the jailed agent must use a strict allowlist, not a "
        "blanket os.environ spread."
    )


def test_host_secrets_do_not_leak_into_gemini_env(_seed_secrets):
    env = _build_agent_env("gemini", "/tmp/state", round_number=1)
    leaked = [k for k in _seed_secrets if k in env]
    assert not leaked, f"gemini env leaked operator secrets: {leaked}"


def test_sentinel_value_absent_even_if_renamed(_seed_secrets):
    # Defence in depth: the secret VALUE must not appear under any key either.
    env = _build_agent_env("claude", "/tmp/state", round_number=1)
    bad = [k for k, v in env.items() if v in set(_seed_secrets.values())]
    assert not bad, f"a secret VALUE leaked into env under key(s): {bad}"


# ---------------------------------------------------------------------------
# Required vars must survive the allowlist (guards against over-scrubbing)
# ---------------------------------------------------------------------------

_REQUIRED_EXPLICIT = {
    "PYTHONHASHSEED",
    "CLAUDE_PROJECT_DIR",
    "JANUSMASK_PROJECT_DIR",
    "PYTHONPATH",
    "GEMINI_CLI_TRUST_WORKSPACE",
    "JANUSMASK_AGENT",
    "JANUSMASK_STATE_DIR",
    "JANUSMASK_ROUND",
    "JANUSMASK_MODE",
    "JANUSMASK_TASK_ID",
    "JANUSMASK_WORK_DIR",
}


def test_explicitly_set_keys_survive(_seed_secrets):
    env = _build_agent_env("claude", "/tmp/state", round_number=3)
    missing = _REQUIRED_EXPLICIT - env.keys()
    assert not missing, f"allowlist over-scrubbed explicitly-set keys: {missing}"
    # Their values are the ones the function pins, not leaked host values.
    assert env["JANUSMASK_AGENT"] == "claude"
    assert env["JANUSMASK_STATE_DIR"] == "/tmp/state"
    assert env["JANUSMASK_ROUND"] == "3"
    assert env["PYTHONHASHSEED"] == "0"
    assert env["GEMINI_CLI_TRUST_WORKSPACE"] == "true"
    assert env["JANUSMASK_PROJECT_DIR"] == str(PROJECT_DIR)


def test_gemini_settings_pointer_survives(_seed_secrets):
    env = _build_agent_env("gemini", "/tmp/state", round_number=1)
    assert "JANUSMASK_GEMINI_SETTINGS" in env, (
        "the gemini settings pointer must survive the allowlist"
    )


def test_path_and_home_survive(_seed_secrets, monkeypatch):
    # PATH (binary resolution for agy/claude) and HOME (jail bind + CLI config
    # root) are auth/runtime-critical and MUST pass through.
    monkeypatch.setenv("PATH", "/usr/bin:/bin:/home/op/.local/bin")
    monkeypatch.setenv("HOME", "/home/op")
    env = _build_agent_env("claude", "/tmp/state", round_number=1)
    assert env.get("PATH") == "/usr/bin:/bin:/home/op/.local/bin", "PATH must survive"
    assert env.get("HOME") == "/home/op", "HOME must survive"


def test_auth_vars_survive_when_present(_seed_secrets, monkeypatch):
    # The vendor/CLI auth + runtime vars agy(gemini)/claude need from the env
    # (D-Bus keyring, XDG dirs, node runtime, vendor toggles) must NOT be
    # scrubbed — over-scrubbing these breaks OAuth/token-refresh and the
    # overseer's auth smoke gate forces a revert.
    auth_vars = {
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
        "XDG_RUNTIME_DIR": "/run/user/1000",
        "XDG_CONFIG_DIRS": "/etc/xdg",
        "XDG_DATA_DIRS": "/usr/share",
        "NVM_DIR": "/home/op/.nvm",
        "NVM_BIN": "/home/op/.nvm/versions/node/v22/bin",
        "GOOGLE_GENAI_USE_GCA": "true",
        "ANTHROPIC_API_KEY": "sk-ant-survives",
        "GEMINI_API_KEY": "gem-survives",
    }
    for k, v in auth_vars.items():
        monkeypatch.setenv(k, v)
    env = _build_agent_env("gemini", "/tmp/state", round_number=1)
    dropped = {k: v for k, v in auth_vars.items() if env.get(k) != v}
    assert not dropped, (
        f"allowlist scrubbed auth/runtime vars the agent CLIs need: "
        f"{sorted(dropped)}. This would break agy/claude auth."
    )


def test_returned_env_is_a_plain_dict(_seed_secrets):
    env = _build_agent_env("claude", "/tmp/state", round_number=1)
    assert isinstance(env, dict)
    # Mutating the result must not touch os.environ (no aliasing).
    env["JM_TEST_SHOULD_NOT_LEAK"] = "x"
    assert os.environ.get("JM_TEST_SHOULD_NOT_LEAK") == _LEAK_SENTINELS["JM_TEST_SHOULD_NOT_LEAK"]
