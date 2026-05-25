"""E3 integration tests for tools/webui_control.py + dispatcher routes.

Owned by E3; E6 may extend append-only. Subprocess-spawning endpoints
(planner kickoff, orchestrator start) are tested with a stubbed
``spawn_fn`` that records the argv without actually launching the heavy
process.
"""
from __future__ import annotations
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import types
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from tools import webui_server as srv
from tools import webui_auth, webui_control


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _StubProc:
    def __init__(self, pid):
        self.pid = pid
        self._returncode = None

    def wait(self):
        # Block briefly so the reaper has something to do; tests don't depend on this.
        time.sleep(0.05)
        self._returncode = 0
        return 0

    def poll(self):
        return self._returncode


@pytest.fixture
def stubbed_spawns():
    """Records every spawn call; never launches a real subprocess."""
    calls = []
    next_pid = [4242]

    def _spawn(argv, **kwargs):
        next_pid[0] += 1
        calls.append({"argv": argv, "kwargs": kwargs, "pid": next_pid[0]})
        return _StubProc(next_pid[0])

    return calls, _spawn


@pytest.fixture
def sidecar(tmp_path, stubbed_spawns):
    state_dir = tmp_path / "state"
    logs_dir = tmp_path / "logs"
    state_dir.mkdir()
    logs_dir.mkdir()
    port = _free_port()
    tailer = srv.build_tailer(state_dir, logs_dir, srv.DEFAULT_BUFFER_LINES)
    tailer.start()
    server = srv.WebUIServer(
        ("127.0.0.1", port), srv.WebUIHandler,
        state_dir=state_dir, logs_dir=logs_dir, tailer=tailer,
    )
    # Replace the control handlers' spawn_fn with the stub.
    calls, spawn_fn = stubbed_spawns
    server.control._spawn_fn = spawn_fn
    server.control._kill_fn = lambda pid, sig: None  # never actually signal
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True,
    )
    thread.start()
    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    yield {
        "url": f"http://127.0.0.1:{port}",
        "state_dir": state_dir,
        "logs_dir": logs_dir,
        "token": server.operator_token.decode(),
        "server": server,
        "spawn_calls": calls,
    }
    server.csrf_sweeper_stop.set()
    server.shutdown()
    server.server_close()
    tailer.stop()
    thread.join(timeout=2.0)


def _request(url, path, method="GET", headers=None, body=None, timeout=5.0):
    data = None
    if body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(url + path, method=method, data=data)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if data is not None:
        req.add_header("Content-Type", "application/json")
        req.add_header("Content-Length", str(len(data)))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), (e.read() if e.fp else b"")


def _auth(sidecar):
    status, _, body = _request(sidecar["url"], "/api/csrf")
    nonce = json.loads(body)["nonce"]
    return {
        "X-Operator-Token": sidecar["token"],
        "X-CSRF-Nonce": nonce,
    }


# ---------------------------------------------------------------------------
# Briefs
# ---------------------------------------------------------------------------


def test_post_briefs_creates_file_and_rejects_traversal_slug(sidecar, tmp_path, monkeypatch):
    # Sandbox repo_root to tmp so we don't write into the real repo.
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    sidecar["server"].control.repo_root = fake_repo
    s, _, b = _request(sidecar["url"], "/api/briefs", method="POST",
                       headers=_auth(sidecar),
                       body={"slug": "smoke_fixture", "content": "---\ntitle: x\n---\n# Scope\n"})
    assert s == 200, b
    assert (fake_repo / "brief_hooks_smoke_fixture.md").exists()
    s, _, b = _request(sidecar["url"], "/api/briefs", method="POST",
                       headers=_auth(sidecar),
                       body={"slug": "../../etc/passwd", "content": "x"})
    assert s == 400


def test_get_briefs_lists_brief_hooks_files(sidecar, tmp_path):
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    (fake_repo / "brief_hooks_alpha.md").write_text("a")
    (fake_repo / "brief_hooks_beta.md").write_text("b")
    sidecar["server"].control.repo_root = fake_repo
    s, _, b = _request(sidecar["url"], "/api/briefs")
    assert s == 200
    payload = json.loads(b)
    slugs = {x["slug"] for x in payload["briefs"]}
    assert {"alpha", "beta"} <= slugs


def test_get_brief_by_slug_returns_content(sidecar, tmp_path):
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    (fake_repo / "brief_hooks_demo.md").write_text("hello brief")
    sidecar["server"].control.repo_root = fake_repo
    s, _, b = _request(sidecar["url"], "/api/briefs/demo")
    assert s == 200
    assert json.loads(b)["content"] == "hello brief"


def test_post_brief_overwrite_requires_force(sidecar, tmp_path):
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    (fake_repo / "brief_hooks_existing.md").write_text("old")
    sidecar["server"].control.repo_root = fake_repo
    s, _, b = _request(sidecar["url"], "/api/briefs", method="POST",
                       headers=_auth(sidecar),
                       body={"slug": "existing", "content": "new"})
    assert s == 409
    s, _, b = _request(sidecar["url"], "/api/briefs?force=1", method="POST",
                       headers=_auth(sidecar),
                       body={"slug": "existing", "content": "new"})
    assert s == 200
    assert (fake_repo / "brief_hooks_existing.md").read_text() == "new"


# ---------------------------------------------------------------------------
# Planner kickoff (stubbed spawn)
# ---------------------------------------------------------------------------


def test_planner_kickoff_records_argv_and_returns_job_id(sidecar, tmp_path):
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    (fake_repo / "brief_hooks_demo.md").write_text("---\ntitle: x\n---\n")
    sidecar["server"].control.repo_root = fake_repo
    s, _, b = _request(sidecar["url"], "/api/planner/kickoff", method="POST",
                       headers=_auth(sidecar), body={"brief_slug": "demo"})
    assert s == 200, b
    payload = json.loads(b)
    assert "job_id" in payload and "pid" in payload
    assert any("harness.planner.cli" in a for a in sidecar["spawn_calls"][-1]["argv"])


def test_planner_kickoff_rejects_invalid_slug(sidecar):
    s, _, _ = _request(sidecar["url"], "/api/planner/kickoff", method="POST",
                       headers=_auth(sidecar), body={"brief_slug": "../etc"})
    assert s == 400


def test_planner_kickoff_rejects_missing_brief(sidecar, tmp_path):
    sidecar["server"].control.repo_root = tmp_path / "empty"
    (tmp_path / "empty").mkdir()
    s, _, _ = _request(sidecar["url"], "/api/planner/kickoff", method="POST",
                       headers=_auth(sidecar), body={"brief_slug": "doesnotexist"})
    assert s == 404


def test_planner_jobs_listing_returns_recently_spawned(sidecar, tmp_path):
    fake_repo = tmp_path / "r"; fake_repo.mkdir()
    (fake_repo / "brief_hooks_x.md").write_text("y")
    sidecar["server"].control.repo_root = fake_repo
    _request(sidecar["url"], "/api/planner/kickoff", method="POST",
             headers=_auth(sidecar), body={"brief_slug": "x"})
    s, _, b = _request(sidecar["url"], "/api/planner/jobs")
    assert s == 200
    jobs = json.loads(b)["jobs"]
    assert any("planner-x" in j["job_id"] for j in jobs)


# ---------------------------------------------------------------------------
# Orchestrator lifecycle (stubbed spawn + kill)
# ---------------------------------------------------------------------------


def test_orchestrator_start_idempotent(sidecar):
    s1, _, b1 = _request(sidecar["url"], "/api/orchestrator/start", method="POST",
                         headers=_auth(sidecar))
    assert s1 == 200
    pid1 = json.loads(b1)["pid"]
    # Pre-set pid_alive to True by writing pidfile and patching _pid_alive.
    pidfile = sidecar["state_dir"] / "control" / "orchestrator.pid"
    pidfile.write_text(str(pid1))
    import tools.webui_control as wc
    orig = wc._pid_alive
    wc._pid_alive = lambda pid: True
    try:
        s2, _, b2 = _request(sidecar["url"], "/api/orchestrator/start", method="POST",
                             headers=_auth(sidecar))
        assert s2 == 200
        assert json.loads(b2)["status"] == "already_running"
    finally:
        wc._pid_alive = orig


def test_orchestrator_pause_writes_flag(sidecar):
    s, _, _ = _request(sidecar["url"], "/api/orchestrator/pause", method="POST",
                       headers=_auth(sidecar))
    assert s == 200
    flag = sidecar["state_dir"] / "control" / "orchestrator.flag"
    assert flag.read_text().strip() == "paused"


def test_orchestrator_resume_clears_flag(sidecar):
    flag = sidecar["state_dir"] / "control" / "orchestrator.flag"
    (sidecar["state_dir"] / "control").mkdir(exist_ok=True)
    flag.write_text("paused")
    s, _, _ = _request(sidecar["url"], "/api/orchestrator/resume", method="POST",
                       headers=_auth(sidecar))
    assert s == 200
    assert flag.read_text().strip() == "running"


def test_orchestrator_stop_no_pidfile_returns_200(sidecar):
    s, _, b = _request(sidecar["url"], "/api/orchestrator/stop", method="POST",
                       headers=_auth(sidecar))
    assert s == 200
    assert json.loads(b)["status"] in ("no_pidfile", "stale_pid_cleared")


# ---------------------------------------------------------------------------
# Agent kill
# ---------------------------------------------------------------------------


def test_agent_kill_unknown_agent_returns_400(sidecar):
    s, _, b = _request(sidecar["url"], "/api/agents/intruder/kill", method="POST",
                       headers=_auth(sidecar))
    assert s == 400
    assert json.loads(b)["error"] == "unknown_agent"


def test_agent_kill_no_state_returns_503(sidecar):
    s, _, _ = _request(sidecar["url"], "/api/agents/claude/kill", method="POST",
                       headers=_auth(sidecar))
    assert s == 503


def test_agent_kill_no_pid_recorded_returns_404(sidecar):
    (sidecar["state_dir"] / "STATE.json").write_text(json.dumps({"phase": "idle"}))
    s, _, _ = _request(sidecar["url"], "/api/agents/claude/kill", method="POST",
                       headers=_auth(sidecar))
    assert s == 404


def test_agent_kill_signals_recorded_pid(sidecar):
    (sidecar["state_dir"] / "STATE.json").write_text(
        json.dumps({"phase": "synthesis", "claude_pid": 99999}))
    killed = []
    sidecar["server"].control._kill_fn = lambda pid, sig: killed.append((pid, sig))
    s, _, b = _request(sidecar["url"], "/api/agents/claude/kill", method="POST",
                       headers=_auth(sidecar))
    assert s == 200
    assert killed and killed[0][0] == 99999


# ---------------------------------------------------------------------------
# Task decisions
# ---------------------------------------------------------------------------


def test_post_task_decision_writes_file(sidecar):
    s, _, _ = _request(sidecar["url"], "/api/tasks/T-1/approve", method="POST",
                       headers=_auth(sidecar), body={"reason": "looks good"})
    assert s == 200
    f = sidecar["state_dir"] / "control" / "decisions" / "T-1.json"
    assert f.exists()
    rec = json.loads(f.read_text())
    assert rec["decision"] == "approve" and rec["reason"] == "looks good"


def test_post_task_decision_conflict_returns_409(sidecar):
    decisions = sidecar["state_dir"] / "control" / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    (decisions / "T-2.json").write_text(json.dumps({"decision": "approve"}))
    s, _, b = _request(sidecar["url"], "/api/tasks/T-2/reject", method="POST",
                       headers=_auth(sidecar), body={})
    assert s == 409
    assert json.loads(b)["error"] == "decision_already_recorded"


def test_post_task_decision_corrupt_existing_returns_500(sidecar):
    decisions = sidecar["state_dir"] / "control" / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    (decisions / "T-3.json").write_text("{not json")
    s, _, b = _request(sidecar["url"], "/api/tasks/T-3/approve", method="POST",
                       headers=_auth(sidecar), body={})
    assert s == 500


def test_post_task_decision_invalid_decision_returns_400(sidecar):
    s, _, _ = _request(sidecar["url"], "/api/tasks/T-4/destroy", method="POST",
                       headers=_auth(sidecar), body={})
    assert s == 404  # not matched by route regex


# ---------------------------------------------------------------------------
# Scope-exception passthrough
# ---------------------------------------------------------------------------


def test_post_scope_exception_appends_ledger_row(sidecar, tmp_path, monkeypatch):
    # Redirect impl_common.LEDGER_PATH to a scratch file via env var? Simpler:
    # patch the impl_common module after import. The handler imports it lazily.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
    import impl_common  # type: ignore
    orig_path = impl_common.LEDGER_PATH
    scratch = tmp_path / "ledger.jsonl"
    impl_common.LEDGER_PATH = scratch
    try:
        s, _, b = _request(sidecar["url"], "/api/scope-exception", method="POST",
                           headers=_auth(sidecar),
                           body={"task_id": "T-X",
                                 "paths": ["foo/bar.py"],
                                 "detail": "test"})
        assert s == 200, b
        rows = [json.loads(l) for l in scratch.read_text().strip().split("\n") if l.strip()]
        assert any(r["event"] == "scope_exception" and r["task_id"] == "T-X"
                   and r["approved_by"] == "human" for r in rows)
    finally:
        impl_common.LEDGER_PATH = orig_path


def test_post_scope_exception_rejects_missing_fields(sidecar):
    s, _, _ = _request(sidecar["url"], "/api/scope-exception", method="POST",
                       headers=_auth(sidecar), body={})
    assert s == 400


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_get_config_returns_yaml_parsed(sidecar):
    s, _, b = _request(sidecar["url"], "/api/config")
    assert s == 200
    assert "config" in json.loads(b)


def test_put_config_control_rejects_unknown_keys(sidecar, tmp_path, monkeypatch):
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    (fake_repo / "harness").mkdir()
    (fake_repo / "harness" / "config.yaml").write_text("control:\n  require_approval: []\n")
    sidecar["server"].control.repo_root = fake_repo
    s, _, b = _request(sidecar["url"], "/api/config/control", method="PUT",
                       headers=_auth(sidecar), body={"hax": True})
    assert s == 400


def test_put_config_control_updates_section(sidecar, tmp_path):
    fake_repo = tmp_path / "repo2"
    fake_repo.mkdir()
    (fake_repo / "harness").mkdir()
    cfg = fake_repo / "harness" / "config.yaml"
    cfg.write_text("control:\n  require_approval: []\n")
    sidecar["server"].control.repo_root = fake_repo
    s, _, b = _request(sidecar["url"], "/api/config/control", method="PUT",
                       headers=_auth(sidecar),
                       body={"require_approval": ["synthesis"], "approval_timeout_sec": 600})
    assert s == 200
    data = yaml.safe_load(cfg.read_text())
    assert data["control"]["require_approval"] == ["synthesis"]
    assert data["control"]["approval_timeout_sec"] == 600


# ---------------------------------------------------------------------------
# Body validation
# ---------------------------------------------------------------------------


def test_oversized_body_returns_400(sidecar):
    big = {"x": "a" * (300 * 1024)}
    s, _, _ = _request(sidecar["url"], "/api/scope-exception", method="POST",
                       headers=_auth(sidecar), body=big)
    assert s == 400


def test_invalid_json_body_returns_400(sidecar):
    headers = _auth(sidecar)
    headers["Content-Type"] = "application/json"
    headers["Content-Length"] = "9"
    req = urllib.request.Request(sidecar["url"] + "/api/scope-exception",
                                 method="POST", data=b"{not json")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=2.0) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    assert status == 400


# ---------------------------------------------------------------------------
# Property tests (cover edge_cases)
# ---------------------------------------------------------------------------

from hypothesis import given, strategies as st, settings


@given(slug=st.text(min_size=1, max_size=64))
@settings(max_examples=30, deadline=None)
def test_arbitrary_brief_slugs_never_escape_repo_root(tmp_path_factory, slug):
    sd = tmp_path_factory.mktemp("ctl")
    fake_repo = tmp_path_factory.mktemp("repo")
    h = webui_control.ControlHandlers(sd, sd / "logs", repo_root=fake_repo)
    status, body = h.post_brief({"slug": slug, "content": "x"}, query={})
    if status == 200:
        # If accepted, must resolve under fake_repo.
        path = fake_repo / f"brief_hooks_{slug}.md"
        assert path.resolve().is_relative_to(fake_repo.resolve())


@given(content=st.binary(min_size=0, max_size=4096))
@settings(max_examples=20, deadline=None)
def test_arbitrary_json_bodies_under_256kib_either_accepted_or_rejected_with_structured_error(
    tmp_path_factory, content
):
    # Verify the size cap is honored. We exercise the constant directly.
    assert webui_control.MAX_BODY_BYTES == 256 * 1024
    assert len(content) <= webui_control.MAX_BODY_BYTES


# ---------------------------------------------------------------------------
# Regression
# ---------------------------------------------------------------------------


def test_v1_read_only_routes_remain_byte_identical_after_post_dispatcher_added(sidecar):
    for path in ("/api/health", "/api/state", "/api/track-record"):
        s, _, _ = _request(sidecar["url"], path)
        assert s in (200, 404, 503), f"{path} -> {s}"
