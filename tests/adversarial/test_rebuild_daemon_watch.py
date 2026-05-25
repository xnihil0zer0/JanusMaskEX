"""The autowork daemon's rebuild-watcher (Model A) supervises rebuild jobs."""

from __future__ import annotations

from pathlib import Path

import harness.autowork_daemon as daemon
import harness.rebuild.job as job

_REPO = Path(__file__).resolve().parent.parent.parent


def _make_job(tmp_path) -> tuple[Path, dict]:
    sd = tmp_path / "state"
    (sd / "control" / "autowork").mkdir(parents=True)
    (sd / "control" / "autowork" / "auto_promote.allowlist").write_text("# allow\n", encoding="utf-8")
    j = job.create_job(
        input_dir=_REPO / "samples" / "mathlib",
        output_dir=tmp_path / "out",
        state_dir=sd,
        stash_dir=tmp_path / "stash",
        repo_root=tmp_path,
    )
    return sd, j


def _spy(monkeypatch, pid=4242):
    calls = []
    monkeypatch.setattr(daemon, "_spawn_rebuild_worker", lambda state_dir, jb: (calls.append(jb), pid)[1])
    return calls


def test_build_loop_command_used_by_spawn(tmp_path):
    # The loop runs in the parent (needs import harness) -> -m, with --resume.
    _sd, j = _make_job(tmp_path)
    cmd = job.build_loop_command(j)
    assert "-m" in cmd and "harness.rebuild.loop" in cmd and "--resume" in cmd


def test_watcher_spawns_resumable_loop_for_allowlisted_pending_job(tmp_path, monkeypatch):
    sd, j = _make_job(tmp_path)
    calls = _spy(monkeypatch)
    daemon._watch_rebuild_jobs(tmp_path, sd, set(), dry_run=False)
    assert len(calls) == 1, "should launch exactly one rebuild loop"
    pidfile = sd / "control" / "autowork" / "running" / f"rebuild__{j['job_id']}.pid"
    assert pidfile.exists() and pidfile.read_text().strip() == "4242"
    updated = job.load_job(sd, j["job_id"])
    assert updated["status"] == "running"
    assert updated["attempts"] == 1


def test_watcher_skips_when_already_running(tmp_path, monkeypatch):
    sd, j = _make_job(tmp_path)
    calls = _spy(monkeypatch)
    daemon._watch_rebuild_jobs(tmp_path, sd, {f"rebuild__{j['job_id']}"}, dry_run=False)
    assert calls == []


def test_watcher_skips_non_allowlisted_job(tmp_path, monkeypatch):
    sd, j = _make_job(tmp_path)
    (sd / "control" / "autowork" / "auto_promote.allowlist").write_text("# none\n", encoding="utf-8")
    calls = _spy(monkeypatch)
    daemon._watch_rebuild_jobs(tmp_path, sd, set(), dry_run=False)
    assert calls == []


def test_watcher_skips_complete_job(tmp_path, monkeypatch):
    sd, j = _make_job(tmp_path)
    real = (_REPO / "samples" / "mathlib" / "mathlib.py").read_text(encoding="utf-8")
    (tmp_path / "out" / "mathlib.py").write_text(real, encoding="utf-8")
    calls = _spy(monkeypatch)
    daemon._watch_rebuild_jobs(tmp_path, sd, set(), dry_run=False)
    assert calls == []


def test_watcher_parks_after_max_attempts(tmp_path, monkeypatch):
    sd, j = _make_job(tmp_path)
    daemon._mark_rebuild_job(sd, j["job_id"], attempts=daemon.MAX_REBUILD_ATTEMPTS)
    calls = _spy(monkeypatch)
    daemon._watch_rebuild_jobs(tmp_path, sd, set(), dry_run=False)
    assert calls == []
    assert job.load_job(sd, j["job_id"])["status"] == "blocked"


# ----- B9: a pending/running rebuild job keeps the daemon non-idle -----

def test_has_active_rebuild_job_true_for_pending(tmp_path):
    sd, j = _make_job(tmp_path)
    assert daemon._has_active_rebuild_job(sd) is True


def test_has_active_rebuild_job_false_when_complete(tmp_path):
    sd, j = _make_job(tmp_path)
    real = (_REPO / "samples" / "mathlib" / "mathlib.py").read_text(encoding="utf-8")
    (tmp_path / "out" / "mathlib.py").write_text(real, encoding="utf-8")
    assert daemon._has_active_rebuild_job(sd) is False


def test_has_active_rebuild_job_false_when_blocked(tmp_path):
    sd, j = _make_job(tmp_path)
    daemon._mark_rebuild_job(sd, j["job_id"], status="blocked")
    assert daemon._has_active_rebuild_job(sd) is False


def test_has_active_rebuild_job_false_when_no_jobs(tmp_path):
    sd = tmp_path / "state"
    (sd / "control" / "autowork").mkdir(parents=True)
    assert daemon._has_active_rebuild_job(sd) is False
