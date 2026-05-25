"""Verification oracle for ``harness.hooks._env._work_dir``.

``_work_dir`` resolves the per-session working directory for a worker:

* When ``JANUSMASK_WORK_DIR`` is set (non-empty) it is authoritative — the
  function returns ``pathlib.Path(<that value>).resolve()`` and consults
  nothing else (not the session id, not the agent, neither collaborator).
* Otherwise the session id is the first non-empty of: the ``session_id``
  argument, ``$JANUSMASK_SESSION_ID``, or the literal ``"nosession"``; the
  agent component comes from ``_resolve_agent(agent)``; and the result is
  ``(_paths.state_dir() / "workdirs" / <agent> / <session_id>).resolve()``.

The non-env branch delegates to two collaborators (``_resolve_agent`` in this
module and ``_paths.state_dir``). To keep these tests gating ONLY
``_work_dir``'s own composition logic — and robust while those collaborators
are still ``NotImplementedError`` stubs during reconstruction — they are
replaced with deterministic stand-ins via ``monkeypatch``. Every test calls
the real ``_work_dir`` directly, so the file still fails wholesale against a
stubbed ``_work_dir`` (non-vacuity).

This file is not covered by the ``tests/`` autouse JANUSMASK_* scrub fixture,
so every test sets/clears the relevant env vars explicitly via ``monkeypatch``.
"""
from __future__ import annotations

import pathlib

from harness.hooks import _env


# ---------------------------------------------------------------------------
# JANUSMASK_WORK_DIR branch: authoritative, early return, no collaborators.
# ---------------------------------------------------------------------------

def test_work_dir_env_var_is_authoritative(monkeypatch, tmp_path):
    """A non-empty JANUSMASK_WORK_DIR is returned (resolved) verbatim."""
    monkeypatch.delenv("JANUSMASK_SESSION_ID", raising=False)
    target = tmp_path / "explicit_work"
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(target))

    result = _env._work_dir()

    assert result == pathlib.Path(str(target)).resolve()


def test_work_dir_env_var_overrides_session_and_agent_args(monkeypatch, tmp_path):
    """When the env var is set, session_id/agent arguments are ignored."""
    target = tmp_path / "winning"
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(target))
    monkeypatch.setenv("JANUSMASK_SESSION_ID", "ignored-session")

    result = _env._work_dir(session_id="also-ignored", agent="also-ignored")

    assert result == pathlib.Path(str(target)).resolve()


def test_work_dir_env_var_relative_path_is_resolved_absolute(monkeypatch):
    """A relative env value is made absolute via ``Path.resolve()``."""
    monkeypatch.delenv("JANUSMASK_SESSION_ID", raising=False)
    monkeypatch.setenv("JANUSMASK_WORK_DIR", "rel/work/here")

    result = _env._work_dir()

    assert result.is_absolute()
    assert result == pathlib.Path("rel/work/here").resolve()


def test_work_dir_empty_env_var_falls_through_to_state_dir(monkeypatch, tmp_path):
    """An empty JANUSMASK_WORK_DIR is falsy and must NOT short-circuit."""
    monkeypatch.setenv("JANUSMASK_WORK_DIR", "")
    monkeypatch.delenv("JANUSMASK_SESSION_ID", raising=False)
    base = tmp_path / "state"
    monkeypatch.setattr(_env._paths, "state_dir", lambda: base)
    monkeypatch.setattr(_env, "_resolve_agent", lambda agent: "claude")

    result = _env._work_dir(session_id="s1")

    assert result == (base / "workdirs" / "claude" / "s1").resolve()


# ---------------------------------------------------------------------------
# state_dir branch: collaborators replaced with deterministic stand-ins.
# ---------------------------------------------------------------------------

def test_work_dir_composes_state_workdirs_agent_session(monkeypatch, tmp_path):
    """Path = state_dir() / "workdirs" / <agent> / <session_id>, resolved."""
    monkeypatch.delenv("JANUSMASK_WORK_DIR", raising=False)
    monkeypatch.delenv("JANUSMASK_SESSION_ID", raising=False)
    base = tmp_path / "state"
    monkeypatch.setattr(_env._paths, "state_dir", lambda: base)
    monkeypatch.setattr(_env, "_resolve_agent", lambda agent: "gemini")

    result = _env._work_dir(session_id="sess-123")

    assert result == (base / "workdirs" / "gemini" / "sess-123").resolve()


def test_work_dir_session_id_argument_wins_over_env(monkeypatch, tmp_path):
    """An explicit session_id argument takes precedence over the env var."""
    monkeypatch.delenv("JANUSMASK_WORK_DIR", raising=False)
    monkeypatch.setenv("JANUSMASK_SESSION_ID", "env-session")
    base = tmp_path / "state"
    monkeypatch.setattr(_env._paths, "state_dir", lambda: base)
    monkeypatch.setattr(_env, "_resolve_agent", lambda agent: "claude")

    result = _env._work_dir(session_id="arg-session")

    assert result == (base / "workdirs" / "claude" / "arg-session").resolve()


def test_work_dir_falls_back_to_session_env_var(monkeypatch, tmp_path):
    """With no session_id arg, $JANUSMASK_SESSION_ID supplies the component."""
    monkeypatch.delenv("JANUSMASK_WORK_DIR", raising=False)
    monkeypatch.setenv("JANUSMASK_SESSION_ID", "env-session")
    base = tmp_path / "state"
    monkeypatch.setattr(_env._paths, "state_dir", lambda: base)
    monkeypatch.setattr(_env, "_resolve_agent", lambda agent: "claude")

    result = _env._work_dir()

    assert result == (base / "workdirs" / "claude" / "env-session").resolve()


def test_work_dir_defaults_to_nosession(monkeypatch, tmp_path):
    """No arg and no env -> the literal "nosession" component."""
    monkeypatch.delenv("JANUSMASK_WORK_DIR", raising=False)
    monkeypatch.delenv("JANUSMASK_SESSION_ID", raising=False)
    base = tmp_path / "state"
    monkeypatch.setattr(_env._paths, "state_dir", lambda: base)
    monkeypatch.setattr(_env, "_resolve_agent", lambda agent: "claude")

    result = _env._work_dir()

    assert result == (base / "workdirs" / "claude" / "nosession").resolve()


def test_work_dir_empty_session_id_arg_falls_back(monkeypatch, tmp_path):
    """An empty session_id argument is falsy -> env/default applies."""
    monkeypatch.delenv("JANUSMASK_WORK_DIR", raising=False)
    monkeypatch.delenv("JANUSMASK_SESSION_ID", raising=False)
    base = tmp_path / "state"
    monkeypatch.setattr(_env._paths, "state_dir", lambda: base)
    monkeypatch.setattr(_env, "_resolve_agent", lambda agent: "claude")

    result = _env._work_dir(session_id="")

    assert result == (base / "workdirs" / "claude" / "nosession").resolve()


def test_work_dir_forwards_agent_to_resolve_agent(monkeypatch, tmp_path):
    """The ``agent`` keyword is passed to ``_resolve_agent`` and its return
    value becomes the agent path component."""
    monkeypatch.delenv("JANUSMASK_WORK_DIR", raising=False)
    monkeypatch.delenv("JANUSMASK_SESSION_ID", raising=False)
    base = tmp_path / "state"
    seen = []

    def fake_resolve_agent(agent):
        seen.append(agent)
        return "resolved-" + (agent or "none")

    monkeypatch.setattr(_env._paths, "state_dir", lambda: base)
    monkeypatch.setattr(_env, "_resolve_agent", fake_resolve_agent)

    result = _env._work_dir(session_id="s", agent="claude")

    assert seen == ["claude"]
    assert result == (base / "workdirs" / "resolved-claude" / "s").resolve()


def test_work_dir_returns_resolved_path_object(monkeypatch, tmp_path):
    """The return value is an absolute ``pathlib.Path``."""
    monkeypatch.delenv("JANUSMASK_WORK_DIR", raising=False)
    monkeypatch.delenv("JANUSMASK_SESSION_ID", raising=False)
    base = tmp_path / "state"
    monkeypatch.setattr(_env._paths, "state_dir", lambda: base)
    monkeypatch.setattr(_env, "_resolve_agent", lambda agent: "claude")

    result = _env._work_dir(session_id="s")

    assert isinstance(result, pathlib.Path)
    assert result.is_absolute()
