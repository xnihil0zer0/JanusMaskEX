"""RED-first oracle for the typed-config WebUI surface on the LIVE sidecar
(leaf: webui-typed-widgets). Targets tools/webui_server.py + tools/webui_control.py
+ tools/webui_static/ — the real stdlib http.server operator WebUI, NOT the dead
webui/app.py Flask tree.

Drives the real sidecar (spun up in a thread on an ephemeral port, exactly like
tests/integration/test_webui_server.py) to constrain:
  - GET /api/config/schema returns the typed schema (fields by dtype, ROLES incl.
    a dual-agent role, PROVIDERS incl. api-backed + cli, and which provider keys
    are present) so the frontend can render typed widgets, per-role dropdowns
    (twin selects for the dual-agent role), per-provider api-key fields, and
    disable keyless api-backed provider options.
  - POST /api/config/typed (auth: X-Operator-Token + X-CSRF-Nonce):
      * 200 + persists atomically on a valid submission;
      * 400 + names the offending field and leaves config UNCHANGED on bad type;
      * 400 on dual-agent-same;
      * 400 on role->keyless-api-provider.
  - tools/webui_static/app.js renders the typed widgets (static-asset assertion:
    a 'Browse' affordance for path fields + the typed-save route id are present).

Authored separately from the implementation; must FAIL until the
get_config_schema / post_save_typed_config handlers + dispatch-table entries +
GET /api/config/schema route exist and the app.js typed-config view ships.
"""
from __future__ import annotations

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


def _seed_config(repo_root: Path) -> Path:
    """Write a sandbox harness/config.yaml the control handlers read+write.

    ControlHandlers resolves config at ``repo_root / 'harness' / 'config.yaml'``;
    the sidecar fixture constructs ControlHandlers with repo_root=tmp so the live
    harness/config.yaml is never touched.
    """
    (repo_root / "harness").mkdir(parents=True, exist_ok=True)
    cfg = repo_root / "harness" / "config.yaml"
    cfg.write_text(yaml.safe_dump({
        "autowork": {"parallel_cap": 5, "poll_interval_sec": 5},
        "synthesis": {"active_agents": ["claude", "gemini"], "antigravity_mode": False},
        "overseer": {"default_backend": "claude", "enabled": True},
        "control": {"autobrief_default_agent": "claude"},
    }), encoding="utf-8")
    return cfg


@pytest.fixture
def sidecar(tmp_path):
    state_dir = tmp_path / "state"
    logs_dir = tmp_path / "logs"
    state_dir.mkdir()
    logs_dir.mkdir()
    repo_root = tmp_path / "repo"
    cfg = _seed_config(repo_root)
    port = _free_port()

    tailer = srv.build_tailer(state_dir, logs_dir, srv.DEFAULT_BUFFER_LINES)
    tailer.start()
    server = srv.WebUIServer(
        ("127.0.0.1", port), srv.WebUIHandler,
        state_dir=state_dir, logs_dir=logs_dir, tailer=tailer,
    )
    # Point the control handlers at the sandbox repo_root so config read/write
    # hits the tmp config.yaml, never the live one.
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
        "logs_dir": logs_dir,
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
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), (e.read() if e.fp else b"")


def _token(sidecar) -> str:
    return webui_auth.load_or_mint_token(sidecar["state_dir"]).decode("ascii")


def _nonce(sidecar) -> str:
    req = urllib.request.Request(sidecar["url"] + "/api/csrf")
    with urllib.request.urlopen(req, timeout=2.0) as r:
        return json.loads(r.read())["nonce"]


def _post(sidecar, path, payload):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(sidecar["url"] + path, method="POST", data=body)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Operator-Token", _token(sidecar))
    req.add_header("X-CSRF-Nonce", _nonce(sidecar))
    try:
        with urllib.request.urlopen(req, timeout=4.0) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}") if e.fp else {}


def _base_submitted():
    return {
        "parallel_cap": "5",
        "synthesis.active_agents": ["claude", "gemini"],
        "overseer.default_backend": "claude",
        "control.autobrief_default_agent": "claude",
    }


# ---------------------------------------------------------------------------
# Schema render contract (GET, drives the frontend widgets)
# ---------------------------------------------------------------------------


def test_schema_endpoint_exposes_typed_fields_roles_providers(sidecar):
    status, _, raw = _get(sidecar["url"], "/api/config/schema")
    assert status == 200, "GET /api/config/schema must serve the typed schema"
    body = json.loads(raw)
    fields = body.get("fields")
    assert isinstance(fields, list) and fields, "schema must carry a non-empty field list"
    valid = {"int", "float", "str", "bool", "path-file", "path-dir", "enum"}
    for f in fields:
        assert f.get("dtype") in valid, f"field {f.get('name')!r} bad dtype {f.get('dtype')!r}"
    # at least one path-typed field exists so the UI can render a Browse button
    assert any(f["dtype"] in ("path-file", "path-dir") for f in fields), \
        "a path-typed field must exist for the Browse affordance"
    roles = body.get("roles")
    assert isinstance(roles, list) and roles, "schema must carry role specs"
    assert any(r.get("dual") for r in roles), "a dual-agent role must be present (twin selects)"
    assert any(r.get("config_key") == "synthesis.active_agents" and r.get("dual")
               for r in roles), "synthesis.active_agents must be the dual-agent role"
    providers = body.get("providers")
    assert isinstance(providers, dict) and providers, "schema must carry provider specs"
    # api-backed providers carry an env var; cli agents are not api-backed
    assert providers.get("deepseek", {}).get("api_backed") is True
    assert providers.get("claude", {}).get("api_backed") is False
    # the schema reports which provider keys are present (empty -> client lock)
    assert "keys_present" in body, "schema must report key-present set for client-side locking"


# ---------------------------------------------------------------------------
# Typed save contract (POST, auth + CSRF, atomic persist / per-field reject)
# ---------------------------------------------------------------------------


def test_valid_typed_save_persists_atomically(sidecar):
    sub = _base_submitted()
    sub["parallel_cap"] = "7"
    status, body = _post(sidecar, "/api/config/typed", sub)
    assert status == 200, f"valid save must be 200, got {status}: {body}"
    loaded = yaml.safe_load(sidecar["cfg"].read_text(encoding="utf-8"))
    assert loaded["autowork"]["parallel_cap"] == 7
    # unrelated block preserved (atomic, non-clobbering save)
    assert loaded["autowork"]["poll_interval_sec"] == 5


def test_invalid_type_rejected_and_config_unchanged(sidecar):
    before = sidecar["cfg"].read_text(encoding="utf-8")
    sub = _base_submitted()
    sub["parallel_cap"] = "not-an-int"
    status, body = _post(sidecar, "/api/config/typed", sub)
    assert status == 400, f"bad-type save must be 400, got {status}"
    # the offending field is named back to the operator
    assert "parallel_cap" in json.dumps(body)
    assert sidecar["cfg"].read_text(encoding="utf-8") == before, \
        "config.yaml must be byte-identical after a rejected save"


def test_dual_agent_same_rejected(sidecar):
    sub = _base_submitted()
    sub["synthesis.active_agents"] = ["claude", "claude"]
    status, body = _post(sidecar, "/api/config/typed", sub)
    assert status == 400, f"dual-agent-same must be 400, got {status}: {body}"


def test_role_keyless_provider_rejected(sidecar):
    sub = _base_submitted()
    sub["overseer.default_backend"] = "deepseek"  # api-backed, no key submitted
    status, body = _post(sidecar, "/api/config/typed", sub)
    assert status == 400, f"role->keyless-provider must be 400, got {status}: {body}"


def test_typed_save_requires_auth(sidecar):
    """The mutation route is gated by the existing operator-token + CSRF posture."""
    body = json.dumps(_base_submitted()).encode("utf-8")
    req = urllib.request.Request(sidecar["url"] + "/api/config/typed", method="POST", data=body)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=2.0) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    assert status in (401, 403), "typed-save must require X-Operator-Token (and CSRF)"


# ---------------------------------------------------------------------------
# Frontend render: the live static app.js ships the typed-config view
# ---------------------------------------------------------------------------


def test_static_app_js_renders_typed_widgets(sidecar):
    status, _, body = _get(sidecar["url"], "/static/app.js")
    assert status == 200
    text = body.decode("utf-8", errors="replace")
    # the typed-config view posts to the typed-save route
    assert "/api/config/typed" in text, "app.js must wire the typed-save route"
    # a Browse affordance for path-typed fields
    assert "Browse" in text or "fs-picker" in text or "fs_picker" in text, \
        "app.js must render a Browse button / fs picker for path fields"
    # it consumes the schema endpoint to drive typed widgets + role dropdowns
    assert "/api/config/schema" in text, "app.js must fetch the typed-config schema"
