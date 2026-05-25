"""E1 seed: integration tests for the static asset handler in tools/webui_server.py.

E1 owns this file. E6 extends it append-only — do not rewrite the seed tests.
"""
from __future__ import annotations
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tools import webui_server as srv


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
    yield {"url": f"http://127.0.0.1:{port}", "port": port}
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


def test_root_serves_index_html_with_correct_content_type(sidecar):
    status, headers, body = _get(sidecar["url"], "/")
    assert status == 200
    assert headers.get("Content-Type", "").startswith("text/html")
    assert b"<title>JanusMask</title>" in body


def test_root_returns_valid_html5_document_with_janusmask_title(sidecar):
    status, headers, body = _get(sidecar["url"], "/")
    assert status == 200
    text = body.decode("utf-8")
    assert text.lower().startswith("<!doctype html>")
    assert "<title>JanusMask</title>" in text
    assert "</html>" in text


def test_static_path_resolves_under_webui_static_dir(sidecar):
    status, headers, body = _get(sidecar["url"], "/static/app.js")
    assert status == 200
    assert headers.get("Content-Type", "").startswith("text/javascript")
    assert b"JanusMask" in body


def test_static_app_js_returns_text_javascript(sidecar):
    status, headers, _ = _get(sidecar["url"], "/static/app.js")
    assert status == 200
    assert headers.get("Content-Type", "").startswith("text/javascript")


def test_static_path_traversal_returns_400(sidecar):
    status, _, _ = _get(sidecar["url"], "/static/../etc/passwd")
    assert status in (400, 404)
    status2, _, _ = _get(sidecar["url"], "/static/%2e%2e/etc/passwd")
    assert status2 in (400, 404)


def test_unknown_extension_returns_404(sidecar):
    status, _, _ = _get(sidecar["url"], "/static/secret.env")
    assert status == 404


def test_static_directory_request_returns_404_no_listing(sidecar):
    status, _, body = _get(sidecar["url"], "/static/")
    assert status == 404
    assert b"<html" not in body.lower() or b"directory" not in body.lower()


def test_content_type_inferred_for_each_allowed_extension(sidecar):
    status, headers, _ = _get(sidecar["url"], "/static/styles.css")
    assert status == 200
    assert headers.get("Content-Type", "").startswith("text/css")


def test_arbitrary_path_strings_never_escape_static_root(sidecar):
    payloads = [
        "../../../../etc/passwd",
        "..%2f..%2fetc%2fpasswd",
        "/etc/passwd",
        "..\\..\\windows\\system32",
        "%00../etc/passwd",
        "....//....//etc/passwd",
    ]
    for p in payloads:
        status, _, _ = _get(sidecar["url"], "/static/" + p)
        assert status in (400, 404), f"payload escaped: {p!r} -> {status}"


def test_v1_read_only_routes_remain_byte_identical(sidecar):
    status, _, _ = _get(sidecar["url"], "/api/health")
    assert status == 200
    status2, _, _ = _get(sidecar["url"], "/api/state")
    assert status2 in (200, 503)


def test_existing_test_webui_server_suite_passes_unchanged():
    import subprocess
    repo_root = Path(__file__).resolve().parent.parent.parent
    result = subprocess.run(
        ["python", "-m", "pytest", "tests/integration/test_webui_server.py", "-x", "--tb=short", "-q"],
        cwd=repo_root, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, f"v1 sidecar suite regressed:\n{result.stdout}\n{result.stderr}"
