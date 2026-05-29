"""Adversarial pins — webui_control.post_brief_autocomplete seam (Plan 04, CASE-M).

Calls ControlHandlers.post_brief_autocomplete DIRECTLY (does NOT import
tools.webui_server / webui.app — psutil is not installed, collection would
error). Uses the class-level _agents_override seam + PATH-staged shell stubs so
no real agy/claude is ever spawned. _agents_override is class-level state that
LEAKS across tests — the teardown fixture resets it to None (a test hazard the
plan calls out explicitly).

Cases:
  1. override + PATH stub echoing valid JSON -> 200 with validation block.
  2. ${PROJECT_ROOT} token in override.command -> _subst resolves it; the argv
     actually spawned contains NO residual token.
  3. req_agent='evil' not in ALLOWED_AGENTS -> 400 agent_invalid.
  4. timeout stub (never exits) -> 504 after SIGTERM/SIGKILL.
  5. parse-fail twice -> 502 (one retry only) and exactly 2 jobs spawned.
  6. bad slug 'Invalid!' -> 422.
"""
from __future__ import annotations

import json
import os
import pathlib
import stat
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tools.webui_control import ControlHandlers  # noqa: E402


@pytest.fixture
def stub_dir(tmp_path, monkeypatch):
    d = tmp_path / "stubbin"
    d.mkdir()
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ.get('PATH', '')}")
    return d


def _write_stub(path: pathlib.Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def handler(tmp_path):
    state_dir = tmp_path / "state"
    logs_dir = tmp_path / "logs"
    state_dir.mkdir()
    logs_dir.mkdir()
    # Pin the config cache so the handler doesn't read the real config.yaml.
    ControlHandlers._config_cache = {
        "autobrief_timeout_sec": 2,
        "autobrief_max_rough_draft_bytes": 16384,
        "autobrief_default_agent": "claude",
    }
    ControlHandlers._config_cache_ts = 9_999_999_999.0
    h = ControlHandlers(state_dir, logs_dir, repo_root=_REPO)
    yield h
    # TEST HAZARD: _agents_override is class-level and leaks across tests.
    ControlHandlers._agents_override = None
    ControlHandlers._config_cache = {}
    ControlHandlers._config_cache_ts = 0.0


_VALID_JSON = '{"slug": "ok_brief", "content": "# Title\\nbody\\n"}'


class TestAutobriefSeam:
    def test_override_stub_returns_200(self, handler, stub_dir):
        _write_stub(stub_dir / "claudestub", f"printf '%s\\n' '{_VALID_JSON}'\nexit 0\n")
        ControlHandlers._agents_override = {"claude": {"command": "claudestub", "args": ["-p"]}}
        status, body = handler.post_brief_autocomplete({"rough_draft": "x"}, {})
        assert status == 200, body
        assert body["slug"] == "ok_brief"
        assert "validation" in body and body["agent"] == "claude"

    def test_project_root_token_substituted_in_argv(self, tmp_path):
        # Stage the stub at an ABSOLUTE path and reference it via ${PROJECT_ROOT}.
        # _subst must turn ${PROJECT_ROOT}/... into the real absolute path.
        # Inject the capturing spawn_fn via the constructor (the agent spawn uses
        # self._spawn_fn, bound at __init__ — monkeypatching subprocess.Popen
        # afterward would only catch the later planner-dry-run subprocess).
        import subprocess
        from harness.paths import PROJECT_ROOT_STR
        rel_name = "stub_under_root.sh"
        abs_stub = pathlib.Path(PROJECT_ROOT_STR) / rel_name
        _write_stub(abs_stub, f"printf '%s\\n' '{_VALID_JSON}'\nexit 0\n")
        captured = {}

        def _capture_popen(argv, *a, **k):
            captured.setdefault("argv", argv)
            return subprocess.Popen(argv, *a, **k)

        state_dir = tmp_path / "state"
        logs_dir = tmp_path / "logs"
        state_dir.mkdir()
        logs_dir.mkdir()
        ControlHandlers._config_cache = {
            "autobrief_timeout_sec": 5,
            "autobrief_max_rough_draft_bytes": 16384,
            "autobrief_default_agent": "claude",
        }
        ControlHandlers._config_cache_ts = 9_999_999_999.0
        h = ControlHandlers(state_dir, logs_dir, spawn_fn=_capture_popen, repo_root=_REPO)
        ControlHandlers._agents_override = {
            "claude": {"command": "${PROJECT_ROOT}/" + rel_name, "args": ["-p"]},
        }
        try:
            status, body = h.post_brief_autocomplete({"rough_draft": "x"}, {})
        finally:
            abs_stub.unlink(missing_ok=True)
            ControlHandlers._agents_override = None
            ControlHandlers._config_cache = {}
            ControlHandlers._config_cache_ts = 0.0
        assert status == 200, body
        assert "argv" in captured
        assert "${PROJECT_ROOT}" not in captured["argv"][0], captured["argv"]
        assert captured["argv"][0] == str(abs_stub)

    def test_unknown_agent_400(self, handler):
        status, body = handler.post_brief_autocomplete(
            {"rough_draft": "x", "agent": "evil"}, {})
        assert status == 400 and body["error"] == "agent_invalid"

    def test_timeout_504(self, handler, stub_dir):
        _write_stub(stub_dir / "hangstub", "sleep 600\nexit 0\n")
        ControlHandlers._agents_override = {"claude": {"command": "hangstub", "args": ["-p"]}}
        status, body = handler.post_brief_autocomplete({"rough_draft": "x"}, {})
        assert status == 504 and body["error"] == "autobrief_timeout"

    def test_parse_fail_twice_502_one_retry(self, handler, stub_dir):
        _write_stub(stub_dir / "garbagestub", "printf '%s\\n' 'NOT JSON'\nexit 0\n")
        ControlHandlers._agents_override = {"claude": {"command": "garbagestub", "args": ["-p"]}}
        jobs_dir = handler.state_dir / "control" / "jobs"
        before = len(list(jobs_dir.glob("autobrief-*"))) if jobs_dir.exists() else 0
        status, body = handler.post_brief_autocomplete({"rough_draft": "x"}, {})
        assert status == 502 and body["error"] == "autobrief_parse_failed"
        after = len(list(jobs_dir.glob("autobrief-*")))
        assert after - before == 2, "parse-fail must retry exactly once (2 spawns)"

    def test_bad_slug_422(self, handler, stub_dir):
        bad = '{"slug": "Invalid!", "content": "# x\\n"}'
        _write_stub(stub_dir / "badslugstub", f"printf '%s\\n' '{bad}'\nexit 0\n")
        ControlHandlers._agents_override = {"claude": {"command": "badslugstub", "args": ["-p"]}}
        status, body = handler.post_brief_autocomplete({"rough_draft": "x"}, {})
        assert status == 422 and body["error"] == "slug_invalid"


class TestOverrideLeakHazard:
    def test_override_resets_to_none_after_teardown(self, handler):
        # Within this test the fixture has already run; assert the seam starts
        # clean (prior tests' teardown reset it). Documents the leak contract.
        assert ControlHandlers._agents_override is None
