"""RED oracle for leaf `drive-backup-uploader`.

Pins `tools/drive_backup/uploader.py`: DEFAULT_REMOTE ('gdrive:'),
remote_dir_for(repo, *, remote=DEFAULT_REMOTE) -> str,
UploadResult{uploaded, queued, remote_path, error},
upload(archive_result, *, remote=DEFAULT_REMOTE, runner, queue_dir, now)
-> UploadResult (never raises; success→uploaded, failure→queued), and
drive_backup_drain(queue_dir, *, remote=DEFAULT_REMOTE, runner)
-> list[UploadResult] (idempotent retry).

Hermetic: rclone is NEVER really invoked — the `runner` seam is a spy /
failing-fake; the only filesystem effects are under tmp_path queue_dir.
"""
import datetime as dt
import json
from types import SimpleNamespace

import pytest

from tools.drive_backup import uploader
from tools.drive_backup.uploader import (
    DEFAULT_REMOTE,
    UploadResult,
    drive_backup_drain,
    remote_dir_for,
    upload,
)


FIXED_NOW = dt.datetime(2026, 6, 12, 23, 15, 0, tzinfo=dt.timezone.utc)


def _now():
    return FIXED_NOW


class OkRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


class FailRunner:
    """Simulates rclone failure (nonzero rc)."""

    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        return SimpleNamespace(returncode=1, stdout=b"", stderr=b"boom")


class RaisingRunner:
    """Simulates rclone-not-found (runner itself raises)."""

    def __call__(self, argv, **kw):
        raise FileNotFoundError("rclone")


def _make_archive_result(tmp_path, repo="JanusMaskEX"):
    arc = tmp_path / f"{repo}_aaaaaaa_20260612T231500Z.tar.zst"
    dif = tmp_path / f"{repo}_aaaaaaa_20260612T231500Z.diff"
    arc.write_bytes(b"ARCHIVE")
    dif.write_text("DIFF")
    return SimpleNamespace(
        archive_path=str(arc),
        diff_path=str(dif),
        base_sha="0" * 40,
        manifest={"repo": repo, "sha": "a" * 40, "stem": arc.stem},
    )


def test_default_remote_constant():
    assert DEFAULT_REMOTE == "gdrive:"


def test_remote_dir_for_path_construction():
    assert (
        remote_dir_for("JanusMaskEX")
        == "gdrive:repo-push-backups/JanusMaskEX/"
    )
    assert (
        remote_dir_for("NobleGreedv2", remote="other:")
        == "other:repo-push-backups/NobleGreedv2/"
    )


def test_upload_success_marks_uploaded_and_calls_rclone_copyto(tmp_path):
    ar = _make_archive_result(tmp_path)
    runner = OkRunner()
    res = upload(
        ar,
        runner=runner,
        queue_dir=str(tmp_path / "q"),
        now=_now,
    )
    assert isinstance(res, UploadResult)
    assert res.uploaded is True
    assert res.queued is False
    assert res.error is None
    assert "repo-push-backups/JanusMaskEX/" in res.remote_path
    # Both archive and diff are copied via rclone copyto through the runner.
    assert len(runner.calls) >= 2
    flat = [tok for call in runner.calls for tok in call]
    assert any("rclone" in t for t in flat)
    assert any("copyto" in t for t in flat)
    assert any(t.endswith(".tar.zst") for t in flat)
    assert any(t.endswith(".diff") for t in flat)


def test_upload_failure_queues_and_never_raises(tmp_path):
    ar = _make_archive_result(tmp_path)
    qdir = tmp_path / "q"
    res = upload(
        ar,
        runner=FailRunner(),
        queue_dir=str(qdir),
        now=_now,
    )
    assert res.uploaded is False
    assert res.queued is True
    assert res.error  # structured non-empty error string
    # Both artifacts copied into the local queue dir.
    names = {p.name for p in qdir.iterdir()}
    assert any(n.endswith(".tar.zst") for n in names)
    assert any(n.endswith(".diff") for n in names)
    # A queued sidecar records the intended remote_path + error.
    sidecars = [p for p in qdir.iterdir() if p.name.endswith(".queued.json")]
    assert sidecars
    meta = json.loads(sidecars[0].read_text())
    assert "remote_path" in meta
    assert meta.get("error")


def test_upload_rclone_not_found_also_queues_never_raises(tmp_path):
    ar = _make_archive_result(tmp_path)
    qdir = tmp_path / "q"
    res = upload(
        ar,
        runner=RaisingRunner(),
        queue_dir=str(qdir),
        now=_now,
    )
    assert res.uploaded is False
    assert res.queued is True
    assert list(qdir.iterdir())  # artifacts landed in the queue


def test_drain_retries_and_clears_on_success(tmp_path):
    # First, force-queue an artifact via a failing upload.
    ar = _make_archive_result(tmp_path)
    qdir = tmp_path / "q"
    upload(ar, runner=FailRunner(), queue_dir=str(qdir), now=_now)
    assert list(qdir.iterdir())
    # Now drain with a succeeding runner → queue clears, results uploaded.
    ok = OkRunner()
    results = drive_backup_drain(str(qdir), runner=ok)
    assert isinstance(results, list)
    assert results and all(r.uploaded for r in results)
    # Queue artifacts + sidecars removed after successful drain.
    remaining = {
        p.name
        for p in qdir.iterdir()
        if p.name.endswith((".tar.zst", ".diff", ".queued.json"))
    }
    assert remaining == set()


def test_drain_is_idempotent_on_empty_queue(tmp_path):
    qdir = tmp_path / "q"
    qdir.mkdir()
    # Empty queue → no-op, never raises, empty result list.
    assert drive_backup_drain(str(qdir), runner=OkRunner()) == []
    # Second drain is still a clean no-op (idempotent).
    assert drive_backup_drain(str(qdir), runner=OkRunner()) == []


def test_drain_keeps_artifacts_queued_on_repeated_failure(tmp_path):
    ar = _make_archive_result(tmp_path)
    qdir = tmp_path / "q"
    upload(ar, runner=FailRunner(), queue_dir=str(qdir), now=_now)
    before = {p.name for p in qdir.iterdir()}
    results = drive_backup_drain(str(qdir), runner=FailRunner())
    # Drain itself never raises; failures stay queued.
    assert all(not r.uploaded for r in results)
    after = {p.name for p in qdir.iterdir()}
    assert before <= after
