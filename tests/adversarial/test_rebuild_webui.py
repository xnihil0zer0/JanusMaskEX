"""WebUI ControlHandlers for the Rebuild tab: /api/rebuild/{start,status}."""

from __future__ import annotations

from pathlib import Path

from tools.webui_control import ControlHandlers

_REPO = Path(__file__).resolve().parent.parent.parent


def _pypi_unreachable() -> bool:
    """True when the package index is unreachable (the no-network gate jail).

    The harness verification gate runs in a ``bwrap --unshare-net`` jail with no
    off-host network, so a rebuild that pip-installs the replicant's deps cannot
    complete there. Returns False when PyPI IS reachable so a genuine handler
    failure is never masked.
    """
    import socket
    try:
        socket.create_connection(('pypi.org', 443), timeout=3).close()
        return False
    except OSError:
        return True


def _handlers(tmp_path) -> ControlHandlers:
    sd = tmp_path / "state"
    (sd / "control" / "autowork").mkdir(parents=True)
    (sd / "control" / "autowork" / "auto_promote.allowlist").write_text("# a\n", encoding="utf-8")
    return ControlHandlers(state_dir=sd, logs_dir=tmp_path / "logs", repo_root=tmp_path)


def test_rebuild_routes_registered():
    assert ControlHandlers._dispatch_post.get("/api/rebuild/start") == ("post_rebuild_start", "body")


def test_post_rebuild_start_creates_and_allowlists(tmp_path):
    h = _handlers(tmp_path)
    st, body = h.post_rebuild_start(
        {"input_dir": str(_REPO / "samples" / "mathlib"), "output_dir": str(tmp_path / "out")}
    )
    assert st == 200
    assert body["job_id"] == "rebuild_mathlib"
    assert body["units"] == 3
    assert body["allowlisted"] is True
    allow = (tmp_path / "state" / "control" / "autowork" / "auto_promote.allowlist").read_text()
    assert "rebuild_mathlib" in allow


def test_post_rebuild_start_validates(tmp_path):
    h = _handlers(tmp_path)
    st, body = h.post_rebuild_start({"input_dir": "", "output_dir": ""})
    assert st == 400
    st2, body2 = h.post_rebuild_start({"input_dir": "/no/such/dir/xyz", "output_dir": str(tmp_path / "o")})
    assert st2 == 400 and body2["error"] == "input_dir_not_found"


def test_post_rebuild_start_module_slice(tmp_path):
    h = _handlers(tmp_path)
    st, body = h.post_rebuild_start({
        "input_dir": str(_REPO),
        "output_dir": str(tmp_path / "jr"),
        "name": "depth_validator",
        "modules": "harness/depth_validator.py",
        "test_files": "tests/test_depth_validator.py",
        "seed_files": "harness/__init__.py",
    })
    if st == 500 and _pypi_unreachable():
        import pytest
        pytest.skip('no-network gate jail: rebuild venv provisioning needs PyPI')
    assert st == 200
    assert body["job_id"] == "rebuild_depth_validator"
    # exactly the sliced module's units, not the whole repo.
    # Brief 14 (hierarchical planner) added check_brief_depth alongside
    # check_true_depth, so depth_validator.py now slices to 2 units.
    assert body["units"] == 2


def test_get_rebuild_status_lists_jobs(tmp_path):
    h = _handlers(tmp_path)
    h.post_rebuild_start(
        {"input_dir": str(_REPO / "samples" / "mathlib"), "output_dir": str(tmp_path / "out")}
    )
    st, body = h.get_rebuild_status()
    assert st == 200
    assert len(body["jobs"]) == 1
    j = body["jobs"][0]
    assert j["job_id"] == "rebuild_mathlib"
    assert j["total"] == 3 and j["remaining"] == 3 and j["complete"] is False
    assert "running" in body
