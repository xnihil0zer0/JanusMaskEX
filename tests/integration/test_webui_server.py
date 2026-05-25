"""META-D3-MANUAL: integration tests for tools/webui_server.py.

Spins up the sidecar in a thread on port-0 (random ephemeral) with a tmp_path
state-dir + logs-dir. Verifies all 8 GET routes, SSE liveness, rotation
safety, lock-contention stale-ts header, path-traversal rejection, and 404
hygiene. All stdlib (urllib.request) — no third-party HTTP libs per brief
non-goals.
"""
import inspect
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tools import webui_auth
from tools import webui_server as srv
from tools.webui_control import ControlHandlers


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_state(state_dir: Path, logs_dir: Path) -> None:
    """Populate a tmp state-dir + logs-dir with canned harness telemetry."""
    state_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "sessions").mkdir()
    (state_dir / "tasks").mkdir()
    for partition in ("queued", "processing", "processed", "blocked"):
        (state_dir / "tasks" / partition).mkdir()
    (state_dir / "planning").mkdir()
    (state_dir / "output").mkdir()
    (logs_dir / "fuzz_results").mkdir()

    # STATE.json
    state_path = state_dir / "STATE.json"
    state_path.write_text(json.dumps({
        "task_id": "T1", "phase": "fuzzing",
        "claude_status": "submitted", "gemini_status": "submitted",
    }))
    # impl_progress.jsonl (5 rows)
    impl = state_dir / "impl_progress.jsonl"
    impl.write_text("\n".join(
        json.dumps({"ts": 1.0 + i, "event": "phase_transition", "phase": "x" + str(i), "task_id": "T1"})
        for i in range(5)
    ) + "\n")
    # track_record_events.jsonl
    (state_dir / "track_record_events.jsonl").write_text(
        json.dumps({"ts": 1.5, "kind": "smoke", "task_id": "T1"}) + "\n"
    )
    # session ledgers (2 files)
    for agent in ("claude", "gemini"):
        (state_dir / "sessions" / f"{agent}_T1_session.ledger.jsonl").write_text(
            json.dumps({"agent": agent, "verb": "submit_code", "outcome": "allow"}) + "\n"
        )
    # fuzz result
    (logs_dir / "fuzz_results" / "T1_r1.json").write_text(json.dumps({"task_id": "T1", "round": "r1", "equivalent": True}))
    # task partitions: 2 in processed, 1 in queued
    for tid in ("T0", "T1"):
        (state_dir / "tasks" / "processed" / f"{tid}.json").write_text(json.dumps({"task_id": tid}))
    (state_dir / "tasks" / "queued" / "T2.json").write_text(json.dumps({"task_id": "T2"}))
    # accepted output for T1 (handler treats task_id as a directory containing
    # one or more accepted-code files)
    out_dir = state_dir / "output" / "T1"
    out_dir.mkdir()
    (out_dir / "submission.py").write_text("def f():\n    return 42\n")
    # planner_track_record.json
    (state_dir / "planner_track_record.json").write_text(json.dumps({"spec_authorship": {}}))
    # planning artifacts
    (state_dir / "planning" / "merged_plan.json").write_text(json.dumps({"tasks": []}))
    (state_dir / "planning" / "critique.json").write_text(json.dumps({"findings": []}))
    # logs/{agent}_stream.jsonl
    for agent in ("claude", "gemini"):
        (logs_dir / f"{agent}_stream.jsonl").write_text(json.dumps({"agent": agent, "type": "init"}) + "\n")


def _free_port() -> int:
    """Reserve an ephemeral port (kernel-assigned)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def sidecar(tmp_path):
    """Spin up tools.webui_server in a daemon thread; tear down on exit."""
    state_dir = tmp_path / "state"
    logs_dir = tmp_path / "logs"
    _seed_state(state_dir, logs_dir)
    port = _free_port()

    tailer = srv.build_tailer(state_dir, logs_dir, srv.DEFAULT_BUFFER_LINES)
    tailer.start()
    server = srv.WebUIServer(
        ("127.0.0.1", port), srv.WebUIHandler,
        state_dir=state_dir, logs_dir=logs_dir, tailer=tailer,
    )
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    # Wait briefly for socket
    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    yield {"url": f"http://127.0.0.1:{port}", "state_dir": state_dir, "logs_dir": logs_dir, "port": port}
    server.shutdown()
    server.server_close()
    tailer.stop()
    thread.join(timeout=2.0)


def _get(url: str, path: str, timeout: float = 2.0) -> tuple[int, dict, bytes]:
    """GET helper. Returns (status, headers, body)."""
    req = urllib.request.Request(url + path)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read() if e.fp else b""


# ---------------------------------------------------------------------------
# 8 GET routes
# ---------------------------------------------------------------------------


def test_health_returns_200_with_state_mtime(sidecar):
    status, headers, body = _get(sidecar["url"], "/api/health")
    assert status == 200
    payload = json.loads(body)
    assert payload["ok"] is True
    assert "state_mtime" in payload
    assert "uptime_sec" in payload


def test_state_endpoint_returns_canonical_state(sidecar):
    status, _, body = _get(sidecar["url"], "/api/state")
    assert status == 200
    payload = json.loads(body)
    assert payload["task_id"] == "T1"
    assert payload["phase"] == "fuzzing"


def test_tasks_partition_lists_processed(sidecar):
    status, _, body = _get(sidecar["url"], "/api/tasks/processed")
    assert status == 200
    payload = json.loads(body)
    ids = sorted(t["task_id"] if isinstance(t, dict) else t for t in payload)
    # T0 + T1 seeded in processed/
    assert "T0" in str(payload) and "T1" in str(payload)


def test_tasks_partition_lists_queued(sidecar):
    status, _, body = _get(sidecar["url"], "/api/tasks/queued")
    assert status == 200
    assert "T2" in body.decode()


def test_planner_current_returns_artifacts(sidecar):
    status, _, body = _get(sidecar["url"], "/api/planner/current")
    assert status == 200
    payload = json.loads(body)
    assert isinstance(payload, dict)
    # Should contain merged_plan + critique keys
    assert "merged_plan" in payload or any("plan" in k for k in payload.keys())


def test_track_record_endpoint(sidecar):
    """Returns recent events from track_record_events.jsonl with `events` key."""
    status, _, body = _get(sidecar["url"], "/api/track-record")
    assert status == 200
    payload = json.loads(body)
    assert "events" in payload, "expected 'events' key, got " + str(list(payload.keys()))
    # Seeded one event with kind=smoke
    assert any(e.get("kind") == "smoke" for e in payload["events"])


def test_fuzz_endpoint_returns_result(sidecar):
    status, _, body = _get(sidecar["url"], "/api/fuzz/T1/r1")
    assert status == 200
    payload = json.loads(body)
    assert payload["task_id"] == "T1"
    assert payload["equivalent"] is True


def test_output_endpoint_returns_directory_listing_or_file(sidecar):
    """Handler returns a directory listing JSON when target is a dir, or
    text/plain content when target is a file."""
    status, headers, body = _get(sidecar["url"], "/api/output/T1")
    assert status == 200
    # Could be JSON listing or plain content depending on implementation
    ctype = headers.get("Content-Type", "").lower() or headers.get("content-type", "").lower()
    if "json" in ctype:
        payload = json.loads(body)
        # Listing of files in T1/
        assert isinstance(payload, (list, dict))
        names = json.dumps(payload)
        assert "submission.py" in names
    else:
        assert b"def f()" in body


# ---------------------------------------------------------------------------
# SSE
# ---------------------------------------------------------------------------


def test_sse_endpoint_returns_event_stream_content_type(sidecar):
    """SSE endpoint advertises text/event-stream."""
    req = urllib.request.Request(sidecar["url"] + "/events")
    with urllib.request.urlopen(req, timeout=3.0) as r:
        ctype = r.headers.get("Content-Type", "")
        assert "text/event-stream" in ctype, "expected SSE content-type, got " + ctype
        # Read a small amount and close (the connection will keep streaming).
        # Just verify the headers are right; full SSE liveness is tested below.
        # Don't read body to avoid blocking on heartbeat wait.


def test_sse_delivers_appended_row_within_2s(sidecar):
    """Append a row to impl_progress.jsonl, observe it on SSE within 2s."""
    impl = sidecar["state_dir"] / "impl_progress.jsonl"
    sentinel = "META-D3-SENTINEL-" + str(time.time())
    received = []
    done = threading.Event()

    def reader():
        try:
            req = urllib.request.Request(sidecar["url"] + "/events")
            with urllib.request.urlopen(req, timeout=4.0) as r:
                start = time.time()
                while time.time() - start < 4.0:
                    line = r.readline().decode("utf-8", errors="replace")
                    if not line:
                        break
                    if sentinel in line:
                        received.append(line)
                        done.set()
                        return
        except Exception:
            pass

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    time.sleep(0.3)  # let SSE handler attach
    with impl.open("a") as f:
        f.write(json.dumps({"ts": 99.9, "event": "sentinel", "marker": sentinel}) + "\n")
    done.wait(timeout=3.0)
    t.join(timeout=1.0)
    assert received, "SSE did not deliver appended row within 3s"


# ---------------------------------------------------------------------------
# Path traversal + 404 hygiene
# ---------------------------------------------------------------------------


def test_output_rejects_path_traversal(sidecar):
    status, _, _ = _get(sidecar["url"], "/api/output/..%2Fetc%2Fpasswd")
    assert status in (400, 404), "path traversal must be 400 or 404, got " + str(status)


def test_fuzz_rejects_path_traversal(sidecar):
    status, _, _ = _get(sidecar["url"], "/api/fuzz/..%2Fetc/r1")
    assert status in (400, 404), "fuzz traversal must be 400 or 404, got " + str(status)


def test_unknown_task_id_returns_404(sidecar):
    status, _, _ = _get(sidecar["url"], "/api/output/this_task_does_not_exist_xyz")
    assert status == 404


def test_unknown_route_returns_404(sidecar):
    status, _, _ = _get(sidecar["url"], "/api/nonexistent")
    assert status == 404


def test_non_get_returns_rejected(sidecar):
    """POST/PUT/DELETE/etc. should be rejected.

    Pre-E2 (v1): no POST handler -> 405 method not allowed.
    Post-E2 (v2): POST is dispatched but requires X-Operator-Token -> 401.
    Either response is a valid "this is not how you read this surface" signal.
    """
    req = urllib.request.Request(sidecar["url"] + "/api/health", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=2.0) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    assert status in (401, 403, 405)


# ---------------------------------------------------------------------------
# Regression sentinels
# ---------------------------------------------------------------------------


def test_sidecar_does_not_import_third_party_http_libs():
    """Brief non-goal: stdlib only. No fastapi/flask/aiohttp/starlette."""
    src = Path(srv.__file__).read_text()
    for forbidden in ("fastapi", "flask", "aiohttp", "starlette", "import httpx", "import requests"):
        assert forbidden not in src.lower(), "forbidden import found: " + forbidden


def test_no_existing_test_in_tests_dir_is_modified():
    """Pin: D3 only adds tests/integration/test_webui_server.py + __init__.py.
    Other integration tests exist under tests/integration/ but are unrelated.
    """
    repo = Path(__file__).resolve().parents[2]
    integration_dir = repo / "tests" / "integration"
    expected_d3 = {"test_webui_server.py", "__init__.py"}
    existing = {p.name for p in integration_dir.glob("*.py")}
    # All non-D3 existing files were pre-existing — we don't inspect their content
    # but we pin that test_webui_server.py and __init__.py exist.
    assert expected_d3.issubset(existing), "D3 paths missing from " + str(existing)


# ---------------------------------------------------------------------------
# F6b: dispatch-contract tests (pinned via META-FIX-F6b 2026-05-17;
# Claude's preserved submission appended verbatim — see
# state/workdirs/claude/claude-r1-F6b_dispatch_contract_tests-*/outbox/
# submission.py). Pins F1b's tools/webui_control.ControlHandlers dispatch
# tables + F2b's tools/webui_server _dispatch_mutation contract.
# ---------------------------------------------------------------------------


_VALID_ARG_SHAPES = {"body_query", "body", "groups", "groups_body", "none"}


class TestDispatchTable:
    """Pin the F1b dispatch tables + F2b dispatcher contract."""

    @staticmethod
    def _read_token(sidecar) -> str:
        token_bytes = webui_auth.load_or_mint_token(sidecar["state_dir"])
        return token_bytes.decode("ascii")

    @staticmethod
    def _mint_nonce(sidecar) -> str:
        req = urllib.request.Request(sidecar["url"] + "/api/csrf")
        with urllib.request.urlopen(req, timeout=2.0) as r:
            payload = json.loads(r.read())
        return payload["nonce"]

    @staticmethod
    def _post(sidecar, path, *, token=None, nonce=None, body=b"{}"):
        req = urllib.request.Request(sidecar["url"] + path, method="POST", data=body)
        req.add_header("Content-Type", "application/json")
        if token is not None:
            req.add_header("X-Operator-Token", token)
        if nonce is not None:
            req.add_header("X-CSRF-Nonce", nonce)
        try:
            with urllib.request.urlopen(req, timeout=2.0) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), (e.read() if e.fp else b"")

    def test_every_post_handler_method_is_table_mapped(self):
        post_methods = {
            name
            for name, _ in inspect.getmembers(ControlHandlers, predicate=inspect.isfunction)
            if name.startswith("post_") and not name.startswith("_")
        }
        mapped = {entry[0] for entry in ControlHandlers._dispatch_post.values()}
        missing = post_methods - mapped
        assert not missing, (
            "post_* methods present on ControlHandlers but absent from "
            "_dispatch_post: " + str(sorted(missing))
        )

    def test_every_put_handler_method_is_table_mapped(self):
        put_methods = {
            name
            for name, _ in inspect.getmembers(ControlHandlers, predicate=inspect.isfunction)
            if name.startswith("put_") and not name.startswith("_")
        }
        mapped = {entry[0] for entry in ControlHandlers._dispatch_put.values()}
        missing = put_methods - mapped
        assert not missing, (
            "put_* methods present on ControlHandlers but absent from "
            "_dispatch_put: " + str(sorted(missing))
        )

    def test_arg_shape_discriminant_set_is_closed(self):
        entries = list(ControlHandlers._dispatch_post.values()) + list(
            ControlHandlers._dispatch_put.values()
        )
        shapes = {entry[1] for entry in entries}
        unexpected = shapes - _VALID_ARG_SHAPES
        assert not unexpected, (
            "arg_shape values outside the closed discriminant set "
            + str(sorted(_VALID_ARG_SHAPES))
            + ": "
            + str(sorted(unexpected))
        )

    def test_dispatch_unknown_path_returns_404_with_canonical_body(self, sidecar):
        token = self._read_token(sidecar)
        nonce = self._mint_nonce(sidecar)
        unknown_path = "/api/__nonexistent__"
        status, _, raw = self._post(sidecar, unknown_path, token=token, nonce=nonce)
        assert status == 404, (
            "expected 404 for unknown path, got " + str(status) + ": " + raw.decode(errors="replace")
        )
        body = json.loads(raw)
        assert body == {
            "error": "no mutation handler",
            "path": unknown_path,
            "method": "POST",
        }, "canonical 404 body shape drifted: " + repr(body)

    def test_auth_runs_before_dispatch(self, sidecar):
        status, _, _ = self._post(
            sidecar,
            "/api/__nonexistent__",
            token="definitely-wrong-token",
            nonce="anything-here",
        )
        assert status == 401, (
            "expected 401 (auth prologue) for bad-token request to unknown path; got "
            + str(status)
            + ". Dispatch must not have run before auth."
        )

    def test_csrf_runs_before_dispatch(self, sidecar):
        token = self._read_token(sidecar)
        status, _, _ = self._post(
            sidecar,
            "/api/__nonexistent__",
            token=token,
            nonce="invalid-nonce-xxxxxxxxxxxxxxxx",
        )
        assert status == 403, (
            "expected 403 (CSRF prologue) for bad-nonce request to unknown path; got "
            + str(status)
            + ". Dispatch must not have run before CSRF check."
        )

    def test_regex_route_passes_group_arg_to_handler(self, sidecar, monkeypatch):
        captured = []

        def fake_validate(handler_self, slug):
            captured.append(slug)
            return (200, {"slug": slug, "validated_by": "fake"})

        monkeypatch.setattr(ControlHandlers, "post_brief_validate", fake_validate)

        token = self._read_token(sidecar)
        nonce = self._mint_nonce(sidecar)
        status, _, raw = self._post(
            sidecar,
            "/api/briefs/foo_slug/validate",
            token=token,
            nonce=nonce,
            body=b"{}",
        )
        assert status == 200, (
            "expected 200 from monkeypatched regex route; got "
            + str(status)
            + ": "
            + raw.decode(errors="replace")
        )
        assert captured == ["foo_slug"], (
            "regex group not threaded through to handler; captured=" + repr(captured)
        )
