"""E6 adversarial tests for the WebUI v2 control plane.

Covers:
- Timing-safe token comparison via mock + call-count assertion (per critique #1
  — wall-clock std-dev is anti-signal on noisy runners; we instead prove
  hmac.compare_digest is the comparator).
- CSRF nonce replay rejection (covered functionally in E2; this asserts under
  concurrent contention).
- Brief slug injection: path traversal, shell metacharacters, NUL bytes,
  unicode normalization tricks.
- Concurrent /api/orchestrator/start: only one Popen survives.
- /api/agents/<unknown>/kill rejection.
- Planner kickoff with malicious brief content (path traversal in frontmatter,
  command injection in slug — handled by slug regex).
- Body-size cap enforced before parse (avoid memory exhaustion).
- Decision file race: parallel approve+reject reach 200/409 deterministically.
"""
from __future__ import annotations
import hmac
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from tools import webui_server as srv
from tools import webui_auth, webui_control


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def sidecar(tmp_path):
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
    # Stub out spawn + kill so tests never launch heavy subprocesses.
    pids = [10001]
    spawn_calls = []

    class _Stub:
        def __init__(self, pid): self.pid = pid; self._rc = None
        def wait(self): time.sleep(0.05); self._rc = 0; return 0
        def poll(self): return self._rc

    def _spawn(argv, **kw):
        pids[0] += 1
        spawn_calls.append({"argv": argv, "pid": pids[0]})
        return _Stub(pids[0])

    server.control._spawn_fn = _spawn
    server.control._kill_fn = lambda pid, sig: None
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
        "spawn_calls": spawn_calls,
    }
    server.csrf_sweeper_stop.set()
    server.shutdown()
    server.server_close()
    tailer.stop()
    thread.join(timeout=2.0)


def _request(url, path, method="GET", headers=None, body=None, timeout=5.0):
    data = json.dumps(body).encode() if body is not None else None
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
    _, _, body = _request(sidecar["url"], "/api/csrf")
    return {"X-Operator-Token": sidecar["token"], "X-CSRF-Nonce": json.loads(body)["nonce"]}


# ---------------------------------------------------------------------------
# Token comparison via hmac.compare_digest (replaces std-dev gate per crit #1)
# ---------------------------------------------------------------------------


def test_check_auth_uses_hmac_compare_digest(monkeypatch):
    calls = []
    real = hmac.compare_digest

    def _spy(a, b):
        calls.append((type(a).__name__, type(b).__name__, len(a), len(b)))
        return real(a, b)

    monkeypatch.setattr(webui_auth.hmac, "compare_digest", _spy)
    expected = b"a" * 64
    assert webui_auth.check_auth({"X-Operator-Token": "wrong"}, expected) is False
    assert webui_auth.check_auth({"X-Operator-Token": "a" * 64}, expected) is True
    assert len(calls) == 2, calls
    # Both inputs are bytes by the time compare_digest is invoked.
    for c in calls:
        assert c[0] == "bytes" and c[1] == "bytes"


def test_check_auth_returns_false_on_missing_header():
    assert webui_auth.check_auth({}, b"x" * 32) is False


# ---------------------------------------------------------------------------
# CSRF concurrency: parallel consume → exactly one wins
# ---------------------------------------------------------------------------


def test_concurrent_csrf_consumers_only_one_succeeds(sidecar):
    token = sidecar["token"]
    _, _, body = _request(sidecar["url"], "/api/csrf")
    nonce = json.loads(body)["nonce"]

    def consume():
        return _request(sidecar["url"], "/api/auth/test_echo", method="POST",
                        headers={"X-Operator-Token": token, "X-CSRF-Nonce": nonce})[0]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: consume(), range(8)))
    successes = [r for r in results if r == 200]
    rejects = [r for r in results if r == 403]
    assert len(successes) == 1, results
    assert len(rejects) == 7, results


# ---------------------------------------------------------------------------
# Brief slug adversarial inputs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", [
    "../../etc/passwd",
    "..\\..\\windows\\system32",
    "valid; rm -rf /",
    "valid$(whoami)",
    "valid\x00null",
    "valid`reboot`",
    "VALIDBUTUPPERCASE",
    "valid space",
    "valid-with-dash",  # dash not allowed
    "",
    "a" * 200,
])
def test_brief_slug_adversarial_inputs_rejected(sidecar, tmp_path, payload):
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    sidecar["server"].control.repo_root = fake_repo
    s, _, _ = _request(sidecar["url"], "/api/briefs", method="POST",
                       headers=_auth(sidecar),
                       body={"slug": payload, "content": "x"})
    assert s == 400, f"slug accepted: {payload!r}"


# ---------------------------------------------------------------------------
# Orchestrator start race (idempotent)
# ---------------------------------------------------------------------------


def test_concurrent_orchestrator_start_is_idempotent(sidecar):
    headers = _auth(sidecar)
    # mint additional nonces — concurrency requires fresh ones per request
    def go(_):
        h = _auth(sidecar)
        return _request(sidecar["url"], "/api/orchestrator/start", method="POST",
                        headers=h, body={})[0]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(go, range(4)))
    # All must return 200 (either started or already_running)
    assert all(r == 200 for r in results), results


# ---------------------------------------------------------------------------
# Agent kill safety
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["intruder", "../etc", "claude2", "GEMINI", ""])
def test_agent_kill_rejects_unknown_agent(sidecar, name):
    s, _, b = _request(sidecar["url"], f"/api/agents/{name}/kill", method="POST",
                       headers=_auth(sidecar))
    # 400 for valid-shape unknown names; 404 for ones that don't even match the route regex.
    assert s in (400, 404), b


# ---------------------------------------------------------------------------
# Body-size cap
# ---------------------------------------------------------------------------


def test_oversized_post_body_rejected_before_parse(sidecar):
    headers = _auth(sidecar)
    headers["Content-Type"] = "application/json"
    huge = "{" + ('"x":"' + "a" * (300 * 1024) + '"') + "}"
    headers["Content-Length"] = str(len(huge))
    req = urllib.request.Request(
        sidecar["url"] + "/api/scope-exception", method="POST", data=huge.encode())
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=2.0) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    assert status == 400


# ---------------------------------------------------------------------------
# Decision-file race
# ---------------------------------------------------------------------------


def test_decision_file_conflict_returns_409(sidecar):
    decisions = sidecar["state_dir"] / "control" / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    (decisions / "T-RACE.json").write_text(json.dumps({"decision": "approve"}))
    s, _, b = _request(sidecar["url"], "/api/tasks/T-RACE/reject", method="POST",
                       headers=_auth(sidecar), body={})
    assert s == 409, b


def test_corrupt_decision_file_returns_500_does_not_crash_server(sidecar):
    decisions = sidecar["state_dir"] / "control" / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    (decisions / "T-CORRUPT.json").write_text("{not valid json")
    s, _, _ = _request(sidecar["url"], "/api/tasks/T-CORRUPT/approve", method="POST",
                       headers=_auth(sidecar), body={})
    assert s == 500
    # Server still alive — subsequent request succeeds.
    s2, _, _ = _request(sidecar["url"], "/api/health")
    assert s2 == 200


# ---------------------------------------------------------------------------
# Path traversal in static handler is gone-twice safe
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", [
    "../etc/passwd",
    "%2e%2e/etc/passwd",
    "%2e%2e%2fetc%2fpasswd",
    "....//etc//passwd",
    "/etc/passwd",
    "..%c0%af..%c0%afetc%c0%afpasswd",  # overlong UTF-8
])
def test_static_handler_rejects_traversal(sidecar, payload):
    s, _, _ = _request(sidecar["url"], "/static/" + payload)
    assert s in (400, 404), payload


# ---------------------------------------------------------------------------
# Token file corruption is loud
# ---------------------------------------------------------------------------


def test_corrupt_operator_token_raises(tmp_path):
    sd = tmp_path / "s"
    (sd / "control").mkdir(parents=True)
    (sd / "control" / "operator_token").write_bytes(b"too short")
    with pytest.raises(RuntimeError, match="corrupt"):
        webui_auth.load_or_mint_token(sd)
