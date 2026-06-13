"""RED-first oracle for the sandboxed filesystem-browse endpoint on the LIVE
sidecar (leaf: webui-fs-browse). Targets tools/webui_server.py +
tools/webui_control.py + tools/webui_static/ — the real stdlib http.server
operator WebUI, NOT the dead webui/app.py Flask tree.

Constrains GET /api/fs/list?path= (a read-only route on the live sidecar):
  - lists entries under the sandbox root (the control handlers' repo_root)
  - returns JSON {root, path, parent, entries:[{name, is_dir}, ...]} dirs-first
  - rejects (4xx) any path escaping the root via .. traversal or an absolute path
  - does not follow a symlink whose real target escapes the root
  - rejects a non-existent / non-dir path
  - the live app.js ships an fs picker that GETs this endpoint

Authored separately from the implementation; must FAIL until the get_fs_list
handler + GET /api/fs/list route exist and app.js ships the picker.
"""
from __future__ import annotations

import json
import os
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
    # Sandbox root for the browse endpoint = the control handlers' repo_root.
    repo_root = tmp_path / "repo"
    (repo_root / "harness").mkdir(parents=True)
    (repo_root / "webui").mkdir()
    (repo_root / "tools").mkdir()
    (repo_root / "top.txt").write_text("x", encoding="utf-8")
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
    yield {"url": f"http://127.0.0.1:{port}", "repo_root": repo_root, "port": port}
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


def test_list_root_returns_entries(sidecar):
    status, data = _get(sidecar["url"], "/api/fs/list")
    assert status == 200, "GET /api/fs/list (no path) must list the sandbox root"
    assert "entries" in data and isinstance(data["entries"], list)
    names = {e["name"] for e in data["entries"]}
    # known seeded dirs are visible under the root
    assert "harness" in names or "webui" in names or "tools" in names
    for e in data["entries"]:
        assert "name" in e and "is_dir" in e


def test_traversal_dotdot_rejected(sidecar):
    status, _ = _get(sidecar["url"], "/api/fs/list?path=../..")
    assert status in (400, 403)


def test_absolute_outside_root_rejected(sidecar):
    status, _ = _get(sidecar["url"], "/api/fs/list?path=/etc")
    assert status in (400, 403)


def test_nonexistent_path_rejected(sidecar):
    status, _ = _get(sidecar["url"], "/api/fs/list?path=definitely_not_a_real_dir_xyz")
    assert status in (400, 403, 404)


def test_non_dir_path_rejected(sidecar):
    # top.txt exists but is a file, not a directory.
    status, _ = _get(sidecar["url"], "/api/fs/list?path=top.txt")
    assert status in (400, 403, 404)


def test_symlink_escape_not_followed(sidecar, tmp_path):
    base = sidecar["repo_root"]
    link = base / "_fs_browse_escape_test_link"
    outside = tmp_path / "outside_target"
    outside.mkdir()
    try:
        if link.exists() or link.is_symlink():
            link.unlink()
        os.symlink(str(outside), str(link))
        status, _ = _get(sidecar["url"], "/api/fs/list?path=_fs_browse_escape_test_link")
        assert status in (400, 403), "symlink escaping the sandbox root must be refused"
    finally:
        if link.is_symlink() or link.exists():
            link.unlink()


def test_static_app_js_ships_fs_picker(sidecar):
    req = urllib.request.Request(sidecar["url"] + "/static/app.js")
    with urllib.request.urlopen(req, timeout=2.0) as r:
        text = r.read().decode("utf-8", errors="replace")
    assert "/api/fs/list" in text, "app.js must GET the fs-browse endpoint from the picker"
