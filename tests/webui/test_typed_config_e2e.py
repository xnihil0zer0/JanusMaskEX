"""End-to-end oracle for the typed-config WebUI epic on the LIVE sidecar
(leaf: webui-typed-config-e2e). Targets tools/webui_server.py +
tools/webui_control.py + tools/webui_static/ — the real stdlib http.server
operator WebUI, NOT the dead webui/app.py Flask tree.

Exercises schema + backends + typed widgets + fs-browse TOGETHER through the real
sidecar (spun up in a thread on an ephemeral port, exactly like
tests/integration/test_webui_server.py). This is the integration test: it proves
the full save / reject / unlock / sandbox matrix holds once the upstream leaves
land.

Sandboxes the control handlers' repo_root (and thus harness/config.yaml) and
state_dir (and thus state/secrets) to a tmp dir so the live config + secrets are
never touched.
"""
from __future__ import annotations

import importlib
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from tools import webui_auth
from tools import webui_server as srv


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def env(tmp_path):
    state_dir = tmp_path / "state"
    logs_dir = tmp_path / "logs"
    state_dir.mkdir()
    logs_dir.mkdir()
    repo_root = tmp_path / "repo"
    (repo_root / "harness").mkdir(parents=True)
    (repo_root / "webui").mkdir()
    cfg = repo_root / "harness" / "config.yaml"
    cfg.write_text(yaml.safe_dump({
        "autowork": {"parallel_cap": 5, "poll_interval_sec": 5},
        "synthesis": {"active_agents": ["claude", "gemini"], "antigravity_mode": False},
        "overseer": {"default_backend": "claude", "enabled": True},
        "control": {"autobrief_default_agent": "claude"},
    }), encoding="utf-8")
    port = _free_port()

    tailer = srv.build_tailer(state_dir, logs_dir, srv.DEFAULT_BUFFER_LINES)
    tailer.start()
    server = srv.WebUIServer(
        ("127.0.0.1", port), srv.WebUIHandler,
        state_dir=state_dir, logs_dir=logs_dir, tailer=tailer,
    )
    from tools.webui_control import ControlHandlers
    server.control = ControlHandlers(state_dir, logs_dir, repo_root=repo_root)
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
        "repo_root": repo_root,
        "cfg": cfg,
        "port": port,
    }
    server.shutdown()
    server.server_close()
    tailer.stop()
    thread.join(timeout=2.0)


def _get(url: str, path: str, timeout: float = 2.0):
    req = urllib.request.Request(url + path)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        body = {}
        if e.fp:
            try:
                body = json.loads(e.read() or b"{}")
            except Exception:
                body = {}
        return e.code, body


def _token(env) -> str:
    return webui_auth.load_or_mint_token(env["state_dir"]).decode("ascii")


def _nonce(env) -> str:
    req = urllib.request.Request(env["url"] + "/api/csrf")
    with urllib.request.urlopen(req, timeout=2.0) as r:
        return json.loads(r.read())["nonce"]


def _post(env, path, payload):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(env["url"] + path, method="POST", data=body)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Operator-Token", _token(env))
    req.add_header("X-CSRF-Nonce", _nonce(env))
    try:
        with urllib.request.urlopen(req, timeout=4.0) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, (json.loads(e.read() or b"{}") if e.fp else {})


def _base_form():
    return {
        "parallel_cap": "5",
        "synthesis.active_agents": ["claude", "gemini"],
        "overseer.default_backend": "claude",
        "control.autobrief_default_agent": "claude",
    }


def test_valid_save_persists_atomically(env):
    form = _base_form()
    form["parallel_cap"] = "9"
    status, body = _post(env, "/api/config/typed", form)
    assert status == 200, f"valid save must be 200, got {status}: {body}"
    loaded = yaml.safe_load(env["cfg"].read_text(encoding="utf-8"))
    assert loaded["autowork"]["parallel_cap"] == 9
    assert loaded["autowork"]["poll_interval_sec"] == 5  # unrelated block preserved


def test_invalid_type_rejected_config_untouched(env):
    before = env["cfg"].read_text(encoding="utf-8")
    form = _base_form()
    form["parallel_cap"] = "x"
    status, body = _post(env, "/api/config/typed", form)
    assert status == 400
    assert "parallel_cap" in json.dumps(body)
    assert env["cfg"].read_text(encoding="utf-8") == before


def test_dual_agent_same_rejected(env):
    form = _base_form()
    form["synthesis.active_agents"] = ["claude", "claude"]
    status, _ = _post(env, "/api/config/typed", form)
    assert status == 400


def test_keyless_provider_rejected_then_key_unlocks(env):
    # 1. assign overseer -> deepseek WITHOUT a key -> rejected
    form = _base_form()
    form["overseer.default_backend"] = "deepseek"
    status, _ = _post(env, "/api/config/typed", form)
    assert status == 400, "keyless api-backed provider must be rejected"

    # 2. submit the key alongside the same assignment -> accepted
    form2 = _base_form()
    form2["overseer.default_backend"] = "deepseek"
    form2["api_key__DEEPSEEK_API_KEY"] = "sk-e2e-secret"
    status2, body2 = _post(env, "/api/config/typed", form2)
    assert status2 == 200, f"keyed provider must unlock, got {status2}: {body2}"

    # 3. key must NOT be in config.yaml, and must NOT be echoed in the response;
    #    only in the gitignored state/secrets store.
    assert "sk-e2e-secret" not in env["cfg"].read_text(encoding="utf-8")
    assert "sk-e2e-secret" not in json.dumps(body2), "key must not be echoed back"
    ss = importlib.import_module("harness.secrets_store")
    secrets = ss.load_secrets(env["state_dir"])
    assert secrets.get("DEEPSEEK_API_KEY") == "sk-e2e-secret"


def test_fs_browse_serves_and_sandboxes(env):
    status_ok, body_ok = _get(env["url"], "/api/fs/list")
    assert status_ok == 200 and "entries" in body_ok
    status_bad, _ = _get(env["url"], "/api/fs/list?path=../..")
    assert status_bad in (400, 403)


def test_typed_save_requires_auth(env):
    """The full surface keeps the existing operator-token + CSRF mutation posture."""
    body = json.dumps(_base_form()).encode("utf-8")
    req = urllib.request.Request(env["url"] + "/api/config/typed", method="POST", data=body)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=2.0) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    assert status in (401, 403)
