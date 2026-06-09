"""Wiring oracle: orchestrator applies the agy worker pool to the agy spawn env.

harness/agy_pool.py was built but ORPHANED (no importer). Pillar B makes each
concurrent daemon-spawned agy worker run under a private $HOME so parallel
~/.gemini registries cannot corrupt each other. The daemon assigns a slot via
JANUSMASK_AGY_SLOT; orchestrator._apply_agy_pool_env turns that into the slot's
private HOME on the agy agent's spawn env -- and _build_agent_env must call it,
so the wire cannot silently rot back into an orphan.

All effects are hermetic: HOME is pointed at an empty tmp dir so ensure_seeded
finds no sources and creates nothing on disk; worker_home is just a path.
"""
import inspect
import os

from harness import agy_pool
from harness import orchestrator


def _agy_config():
    # a config whose agent's command basename is 'agy', with the pool enabled.
    return {
        "agents": {"gemini": {"command": "${PROJECT_ROOT}/.agents/agy/agy"}},
        "workers": {"agy_pool": {"enabled": True, "size": 8}},
    }


def test_pooled_home_set_for_agy_agent_with_slot(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))           # empty -> ensure_seeded copies nothing
    monkeypatch.setenv("JANUSMASK_AGY_SLOT", "2")
    env = {"HOME": str(tmp_path), "X": "1"}
    out = orchestrator._apply_agy_pool_env("gemini", env, config=_agy_config())
    assert out["HOME"] == str(agy_pool.worker_home(orchestrator.PROJECT_DIR, 2))
    assert out["GOOGLE_GENAI_USE_GCA"] == "1"
    assert env["HOME"] == str(tmp_path)                 # input never mutated


def test_disabled_pool_leaves_env_unchanged(monkeypatch, tmp_path):
    monkeypatch.setenv("JANUSMASK_AGY_SLOT", "2")
    cfg = _agy_config()
    cfg["workers"]["agy_pool"]["enabled"] = False
    env = {"HOME": str(tmp_path)}
    out = orchestrator._apply_agy_pool_env("gemini", env, config=cfg)
    assert out["HOME"] == str(tmp_path)
    assert "GOOGLE_GENAI_USE_GCA" not in out


def test_non_agy_agent_never_pooled(monkeypatch, tmp_path):
    monkeypatch.setenv("JANUSMASK_AGY_SLOT", "2")
    cfg = _agy_config()
    cfg["agents"]["gemini"]["command"] = "/usr/bin/claude"   # basename != 'agy'
    env = {"HOME": str(tmp_path)}
    out = orchestrator._apply_agy_pool_env("gemini", env, config=cfg)
    assert out["HOME"] == str(tmp_path)


def test_no_slot_leaves_env_unchanged(monkeypatch, tmp_path):
    monkeypatch.delenv("JANUSMASK_AGY_SLOT", raising=False)
    env = {"HOME": str(tmp_path)}
    out = orchestrator._apply_agy_pool_env("gemini", env, config=_agy_config())
    assert out["HOME"] == str(tmp_path)


def test_bad_slot_value_is_tolerated(monkeypatch, tmp_path):
    monkeypatch.setenv("JANUSMASK_AGY_SLOT", "not-an-int")
    env = {"HOME": str(tmp_path)}
    out = orchestrator._apply_agy_pool_env("gemini", env, config=_agy_config())
    assert out["HOME"] == str(tmp_path)


def test_build_agent_env_calls_the_pool_helper():
    # Anti-orphan guard: the production env factory must invoke the pool helper.
    src = inspect.getsource(orchestrator._build_agent_env)
    assert "_apply_agy_pool_env" in src
