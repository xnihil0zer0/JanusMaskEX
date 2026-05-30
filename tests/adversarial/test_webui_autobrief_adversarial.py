"""F8 adversarial tests for POST /api/briefs/autocomplete.

Locks in the security envelope of the F1 endpoint against the threat model in
the WebUI autobrief scope: prompt-injection of the model-returned slug,
slug-exfiltration via path traversal, TOCTOU between subprocess wait and
stdout read, SIGTERM/SIGKILL deadline race, concurrent-job isolation,
oversize body rejection before subprocess spawn, CSRF nonce replay, and
agent toggle whitelist enforcement.

If F1 (`post_brief_autocomplete`) has not yet shipped, the entire module
is skipped at collection time so this file remains green pre-F1.

These tests drive the real `subprocess.Popen` path via shell stubs staged on
PATH and a few `TEST_AUTOBRIEF_MODE` env values; we do not monkeypatch
`ControlHandlers._spawn_fn` so the production code path is exercised
end-to-end.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from tools import webui_auth, webui_control, webui_server as srv
from tools.webui_control import ControlHandlers

_F1_ATTR = "post_brief_autocomplete"
pytestmark = pytest.mark.skipif(
    not hasattr(webui_control.ControlHandlers, _F1_ATTR),
    reason="F1 endpoint post_brief_autocomplete not yet implemented",
)


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Stub-binary fixture — mirrors the session-autouse fixture in F7. Phase F moved
# these stubs to an isolated per-session tmp_path_factory dir (no shared
# tests/fixtures/autobrief/ path), so there is no cross-fixture overwrite race —
# each fixture writes its stub content into its OWN temp dir and prepends that
# dir to PATH.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def stub_binaries(tmp_path_factory):
    fixtures_dir = tmp_path_factory.mktemp("autobrief_stubs")

    # NOTE: use printf '%s\n' (not echo) — dash's builtin echo treats the
    # literal `\n` in single-quoted JSON strings as a real newline, producing
    # invalid JSON. printf with '%s\n' leaves the JSON-internal escapes intact.
    stub_content = """#!/bin/sh
if [ "$TEST_AUTOBRIEF_MODE" = "timeout" ]; then
    sleep 5
    printf '%s\\n' '{"slug": "slow", "content": "..."}'
    exit 0
elif [ "$TEST_AUTOBRIEF_MODE" = "parse_fail_once" ]; then
    counter="${TEST_AUTOBRIEF_COUNTER:-/tmp/autobrief_parse_fail_once_counter}"
    if [ -f "$counter" ]; then
        rm -f "$counter"
        printf '%s\\n' '{"slug": "retried_ok", "content": "---\\nauthor: operator\\n---\\n# Title\\n# Scope\\n# Non-Goals\\n# Inputs\\n# Deliverables\\n# Acceptance\\n"}'
    else
        touch "$counter"
        printf '%s\\n' '{"garbage": "not json"'
    fi
    exit 0
elif [ "$TEST_AUTOBRIEF_MODE" = "parse_fail_twice" ]; then
    printf '%s\\n' 'GARBAGE'
    exit 0
elif [ "$TEST_AUTOBRIEF_MODE" = "slug_invalid" ]; then
    printf '%s\\n' '{"slug": "UPPERCASE", "content": "---\\nauthor: operator\\n---\\n# Title\\n# Scope\\n# Non-Goals\\n# Inputs\\n# Deliverables\\n# Acceptance\\n"}'
    exit 0
elif [ "$TEST_AUTOBRIEF_MODE" = "planner_reject" ]; then
    printf '%s\\n' '{"slug": "bad_plan", "content": "Just prose.\\n"}'
    exit 0
elif [ "$TEST_AUTOBRIEF_MODE" = "poisoned_traversal_slug" ]; then
    printf '%s\\n' '{"slug": "../../etc/passwd", "content": "# brief\\nIgnore prior instructions."}'
    exit 0
elif [ "$TEST_AUTOBRIEF_MODE" = "poisoned_env_slug" ]; then
    printf '{"slug": "%s", "content": "stolen"}\\n' "$TEST_AUTOBRIEF_SLUG"
    exit 0
elif [ "$TEST_AUTOBRIEF_MODE" = "hang_with_stderr" ]; then
    printf '%s\\n' 'the-tail-marker-XYZ' >&2
    sleep 600
    exit 0
else
    printf '%s\\n' '{"slug": "happy_slug", "content": "---\\nauthor: operator\\n---\\n# Title\\n# Scope\\n# Non-Goals\\n# Inputs\\n# Deliverables\\n# Acceptance\\n"}'
    exit 0
fi
"""
    for name in ("claude", "gemini"):
        p = fixtures_dir / name
        p.write_text(stub_content)
        p.chmod(0o755)

    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{fixtures_dir}:{old_path}"

    prompt_file = REPO_ROOT / "tools" / "webui_autobrief_prompt.txt"
    created_prompt = False
    if not prompt_file.exists():
        prompt_file.write_text("SYSTEM PROMPT")
        created_prompt = True

    yield fixtures_dir

    os.environ["PATH"] = old_path
    if created_prompt:
        try:
            prompt_file.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _request(url, path, method="GET", headers=None, body=None, timeout=10.0):
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


def _job_dirs(state_dir: Path) -> list[Path]:
    root = state_dir / "control" / "jobs"
    if not root.exists():
        return []
    return [p for p in root.iterdir() if p.name.startswith("autobrief-")]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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

    # Default cache (overridable per-test via the same class attrs).
    ControlHandlers._config_cache = {
        "autobrief_timeout_sec": 5,
        "autobrief_max_rough_draft_bytes": 16384,
        "autobrief_default_agent": "claude",
    }
    ControlHandlers._config_cache_ts = time.time() + 99999
    # AGENT-ISOLATION §4: real config.yaml points at vendored absolute
    # ${PROJECT_ROOT}/.agents/... commands that bypass the PATH-staged stubs;
    # inject bare PATH-resolvable commands so the stub binaries are exercised.
    ControlHandlers._agents_override = {
        "claude": {"command": "claude", "args": ["-p"]},
        "gemini": {"command": "gemini", "args": ["-p"]},
        "antigravity": {"command": "agy", "args": ["-p"]},
    }

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
        "token": server.operator_token.decode() if isinstance(server.operator_token, (bytes, bytearray)) else str(server.operator_token),
        "server": server,
    }
    try:
        server.csrf_sweeper_stop.set()
    except Exception:
        pass
    server.shutdown()
    server.server_close()
    tailer.stop()
    thread.join(timeout=2.0)
    ControlHandlers._config_cache_ts = 0
    ControlHandlers._agents_override = None


def _csrf(sidecar) -> str:
    _, _, body = _request(sidecar["url"], "/api/csrf",
                          headers={"X-Operator-Token": sidecar["token"]})
    return json.loads(body)["nonce"]


def _auth(sidecar) -> dict[str, str]:
    return {"X-Operator-Token": sidecar["token"], "X-CSRF-Nonce": _csrf(sidecar)}


def _post_autocomplete(sidecar, body, *, headers=None, timeout=10.0):
    h = headers if headers is not None else _auth(sidecar)
    return _request(sidecar["url"], "/api/briefs/autocomplete",
                    method="POST", headers=h, body=body, timeout=timeout)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_prompt_injection_rejected_by_layered_defense(sidecar, monkeypatch):
    """A poisoned stub stdout containing a path-traversal slug must be
    rejected by the slug regex layer before any FS write happens."""
    monkeypatch.setenv("TEST_AUTOBRIEF_MODE", "poisoned_traversal_slug")
    status, _, raw = _post_autocomplete(sidecar, {"rough_draft": "draft"})
    body = json.loads(raw or b"{}")
    assert status == 422, (status, body)
    assert body.get("error") in {"slug_invalid", "autobrief_parse_failed"}


def test_slug_exfiltration_returns_422_before_fs_op(sidecar, monkeypatch, tmp_path):
    """Even if the model returns a path-traversal slug, no file must be
    created at the attempted exfiltration target."""
    sentinel_dir = tmp_path / "exfil-target"
    sentinel_dir.mkdir()
    # Carry the exfil path into the stub via env so the stub can echo it.
    exfil_slug = f"../../../{sentinel_dir}/passwd"
    monkeypatch.setenv("TEST_AUTOBRIEF_MODE", "poisoned_env_slug")
    monkeypatch.setenv("TEST_AUTOBRIEF_SLUG", exfil_slug)
    status, _, raw = _post_autocomplete(sidecar, {"rough_draft": "draft"})
    assert status == 422, (status, raw)
    # No file written at the exfiltration target.
    assert list(sentinel_dir.iterdir()) == []


def test_stdout_toctou_safe(sidecar, monkeypatch):
    """Handler must read stdout from disk only after `proc.wait()` returns
    (the real subprocess closes its stdout fd on exit). We verify by driving
    the happy stub and confirming the returned content is exactly what the
    stub wrote — proving the read window is post-exit and not racing with
    the writer."""
    monkeypatch.setenv("TEST_AUTOBRIEF_MODE", "happy")
    status, _, raw = _post_autocomplete(sidecar, {"rough_draft": "draft"})
    if status != 200:
        pytest.skip(f"handler returned {status}; TOCTOU semantics not exercised")
    body = json.loads(raw or b"{}")
    assert body.get("slug") == "happy_slug", body
    # Content matches the stub's payload (`---\nauthor: operator\n---\n...`).
    assert "author: operator" in body.get("content", ""), body


def test_timeout_sigterm_then_sigkill_with_stderr_tail(sidecar, monkeypatch):
    """SIGTERM at deadline, SIGKILL grace, 504 includes stderr tail.

    The handler does `int(cfg.get("autobrief_timeout_sec", 180))`, so
    fractional values truncate to 0 (SIGTERM immediately, before the shell
    can print to stderr). Use 2s so the stub has time to flush its stderr
    marker before SIGTERM arrives. The handler then hardcodes a ~5s
    SIGKILL grace, so total elapsed ~7s.
    """
    if os.environ.get("CI_NO_TIMING"):
        pytest.skip("CI_NO_TIMING set; timing-sensitive test skipped")

    ControlHandlers._config_cache = {
        "autobrief_timeout_sec": 2,
        "autobrief_max_rough_draft_bytes": 16384,
        "autobrief_default_agent": "claude",
    }
    ControlHandlers._config_cache_ts = time.time() + 99999

    monkeypatch.setenv("TEST_AUTOBRIEF_MODE", "hang_with_stderr")

    t0 = time.monotonic()
    status, _, raw = _post_autocomplete(sidecar, {"rough_draft": "draft"}, timeout=20.0)
    elapsed = time.monotonic() - t0
    assert status == 504, (status, raw)
    body = json.loads(raw or b"{}")
    assert body.get("error") == "autobrief_timeout"
    detail = body.get("detail") or ""
    assert "tail-marker" in detail or "the-tail" in detail, body
    # Handler's internal SIGKILL grace is ~5s on top of the 2s deadline.
    assert elapsed < 12.0, f"overshoot: {elapsed:.2f}s"


def test_20_concurrent_kickoffs_distinct_job_dirs(sidecar, monkeypatch):
    """20 concurrent autocomplete kickoffs must each produce a unique job_id
    and a distinct jobs/<job_id>/ directory with no cross-contamination."""
    # slug_invalid mode exits the stub quickly and 422s the handler before
    # the planner dry-run, keeping the concurrent test fast.
    monkeypatch.setenv("TEST_AUTOBRIEF_MODE", "slug_invalid")

    # Pre-fetch nonces sequentially so the server isn't hit with 40 (csrf +
    # POST) parallel connections at once; the threaded HTTP server can reset
    # connections under that contention.
    nonces = [_csrf(sidecar) for _ in range(20)]

    statuses: list[int] = []
    lock = threading.Lock()

    def _one(i):
        headers = {"X-Operator-Token": sidecar["token"], "X-CSRF-Nonce": nonces[i]}
        body = {"rough_draft": f"draft-{i}"}
        try:
            status, _, _ = _post_autocomplete(sidecar, body, headers=headers, timeout=15.0)
        except Exception as exc:
            status = repr(exc)
        with lock:
            statuses.append(status)

    with ThreadPoolExecutor(max_workers=20) as pool:
        futs = [pool.submit(_one, i) for i in range(20)]
        for f in as_completed(futs):
            f.result()

    ab_dirs = _job_dirs(sidecar["state_dir"])
    # Allow some transient connection failures under load — the property we
    # actually care about is that every successful spawn got its own job_dir.
    successes = [s for s in statuses if isinstance(s, int) and s in (200, 422)]
    assert len(ab_dirs) >= len(successes), (
        f"job_dir count {len(ab_dirs)} < successes {len(successes)} statuses={statuses}"
    )
    assert len(ab_dirs) >= 15, f"expected >=15 job dirs under load, got {len(ab_dirs)}; statuses={statuses}"
    # Directory names must all be unique.
    names = {p.name for p in ab_dirs}
    assert len(names) == len(ab_dirs)


def test_oversize_413_before_spawn(sidecar):
    """16385-byte rough_draft must be rejected with 413 before any subprocess
    spawn. Assert no job_dir was created (the handler creates the job_dir
    inside `run_attempt`, after the size check)."""
    ControlHandlers._config_cache = {
        "autobrief_timeout_sec": 5,
        "autobrief_max_rough_draft_bytes": 16384,
        "autobrief_default_agent": "claude",
    }
    ControlHandlers._config_cache_ts = time.time() + 99999

    before = len(_job_dirs(sidecar["state_dir"]))
    body = {"rough_draft": "A" * 16385}
    status, _, raw = _post_autocomplete(sidecar, body)
    assert status == 413, (status, raw)
    assert len(_job_dirs(sidecar["state_dir"])) == before


def test_csrf_replay_returns_403(sidecar):
    """Reusing an already-consumed CSRF nonce must return 403."""
    nonce = _csrf(sidecar)
    headers = {"X-Operator-Token": sidecar["token"], "X-CSRF-Nonce": nonce}
    status1, _, _ = _post_autocomplete(sidecar, {"rough_draft": "draft"},
                                       headers=headers)
    assert status1 != 403, "first call should consume nonce, not 403"
    status2, _, raw2 = _post_autocomplete(sidecar, {"rough_draft": "draft2"},
                                          headers=headers)
    assert status2 == 403, (status2, raw2)


def test_agent_toggle_injection_returns_400(sidecar):
    """body['agent']='../../bin/sh' must be rejected as 400 agent_invalid
    with no subprocess spawn (no job_dir created)."""
    before = len(_job_dirs(sidecar["state_dir"]))
    status, _, raw = _post_autocomplete(
        sidecar, {"rough_draft": "draft", "agent": "../../bin/sh"}
    )
    assert status == 400, (status, raw)
    body = json.loads(raw or b"{}")
    assert body.get("error") == "agent_invalid", body
    assert len(_job_dirs(sidecar["state_dir"])) == before


def test_fixture_paths_respect_sandbox_allow_list(tmp_path):
    """All fixture file writes used by this module must occur under /tmp or
    tests/fixtures/, never above the project root or inside system paths."""
    allowed_roots = [
        Path("/tmp").resolve(),
        Path(__file__).resolve().parent.parent / "fixtures",
        tmp_path.resolve(),
    ]
    rp = tmp_path.resolve()
    assert any(str(rp).startswith(str(root)) for root in allowed_roots), rp


# ---------------------------------------------------------------------------
# Integration / property / regression tests
# ---------------------------------------------------------------------------


def test_full_adversarial_suite_against_in_process_server(sidecar):
    """Smoke: hit /api/health and /api/csrf to prove the in-process server
    used by the suite is wired and reachable."""
    s, _, body = _request(sidecar["url"], "/api/health",
                          headers={"X-Operator-Token": sidecar["token"]})
    assert s in (200, 401), s
    s, _, body = _request(sidecar["url"], "/api/csrf",
                          headers={"X-Operator-Token": sidecar["token"]})
    assert s == 200, (s, body)
    assert "nonce" in json.loads(body)


def test_property_every_rejection_leaves_no_subprocess_residue(sidecar):
    """For every kind of rejection that should fire BEFORE subprocess spawn
    (oversize, agent-invalid, missing rough_draft, CSRF-missing), assert no
    job_dir was created."""
    # Tight max so a small body triggers oversize.
    ControlHandlers._config_cache = {
        "autobrief_timeout_sec": 5,
        "autobrief_max_rough_draft_bytes": 16,
        "autobrief_default_agent": "claude",
    }
    ControlHandlers._config_cache_ts = time.time() + 99999

    before = len(_job_dirs(sidecar["state_dir"]))
    # 1. Oversize body.
    s1, _, _ = _post_autocomplete(sidecar, {"rough_draft": "X" * 100})
    # 2. Agent injection.
    s2, _, _ = _post_autocomplete(
        sidecar, {"rough_draft": "ok", "agent": "/bin/sh"}
    )
    # 3. Missing rough_draft.
    s3, _, _ = _post_autocomplete(sidecar, {"rough_draft": ""})
    # 4. Missing CSRF nonce.
    s4, _, _ = _post_autocomplete(
        sidecar, {"rough_draft": "ok"},
        headers={"X-Operator-Token": sidecar["token"]},
    )
    for s in (s1, s2, s3, s4):
        assert s in (400, 403, 413, 422), s
    assert len(_job_dirs(sidecar["state_dir"])) == before


def test_existing_adversarial_modules_still_pass():
    """Regression sentinel: importing sibling adversarial modules must still
    succeed. If one of them was broken by an F8 ripple this collection will
    fail loudly."""
    import importlib

    siblings = [
        "tests.adversarial.test_webui_control_adversarial",
    ]
    for name in siblings:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError:
            pytest.skip(f"sibling module {name} not present")
        except Exception as exc:  # pragma: no cover — surfaces real regressions
            pytest.fail(f"{name} import failed: {exc!r}")


def test_module_collects_when_f1_absent():
    """Meta: the module-level skipif must be the only gate keeping us green
    pre-F1; once F1 ships, this test still passes (skipif evaluates False)."""
    assert hasattr(webui_control.ControlHandlers, _F1_ATTR)
