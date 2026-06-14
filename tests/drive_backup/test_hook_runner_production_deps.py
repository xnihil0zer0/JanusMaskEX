"""RED oracle for hook_runner._default_build_deps (the PRODUCTION adapter).

The hermetic oracle in test_hook_runner.py only ever drives ``main`` with an
INJECTED ``build_deps``, so the real production wiring -- which must (a) import
the sibling ``ledger`` module correctly, (b) supply ``build_archive`` its
required ``runner``/``now``/``out_dir`` seams, and (c) supply ``upload`` its
required ``runner``/``queue_dir`` seams -- was never exercised and shipped
broken (ImportError + missing-kwarg TypeErrors).

This oracle pins that adapter without any real subprocess/network: it spies on
the sibling module functions so calling the returned ``archiver``/``uploader``
asserts the seams are wired, never invoking real tar/git/rclone.
"""
import os

from tools.drive_backup import archiver as archiver_mod
from tools.drive_backup import uploader as uploader_mod
from tools.drive_backup import ledger as ledger_mod
from tools.drive_backup.hook_runner import _default_build_deps


def test_build_deps_importable_and_shaped():
    """_default_build_deps must resolve (no ImportError) and expose all seams."""
    deps = _default_build_deps("/tmp/some-repo")
    for attr in ("archiver", "uploader", "ledger", "log"):
        assert hasattr(deps, attr), attr
    assert isinstance(deps.ledger, ledger_mod.BackupLedger)
    assert callable(deps.archiver)
    assert callable(deps.uploader)
    assert callable(deps.log)


def test_archiver_supplies_required_seams(monkeypatch):
    """deps.archiver(repo, sha, base_sha=...) must feed build_archive its seams."""
    captured = {}

    def spy_build_archive(repo_root, sha, *, runner, now, out_dir, base_sha=None, **kw):
        captured.update(
            repo_root=repo_root, sha=sha, runner=runner, now=now,
            out_dir=out_dir, base_sha=base_sha,
        )
        return "ARCHIVE_RESULT"

    monkeypatch.setattr(archiver_mod, "build_archive", spy_build_archive)
    deps = _default_build_deps("/tmp/some-repo")
    result = deps.archiver("/tmp/some-repo", "deadbeef", base_sha="cafe")

    assert result == "ARCHIVE_RESULT"
    assert captured["sha"] == "deadbeef"
    assert captured["base_sha"] == "cafe"
    assert callable(captured["runner"])      # real subprocess seam
    assert callable(captured["now"])         # real clock seam
    assert isinstance(captured["out_dir"], str) and captured["out_dir"]
    # out_dir must NOT live inside the repo working tree (resource hygiene)
    assert os.path.abspath("/tmp/some-repo") not in os.path.abspath(captured["out_dir"])
    # the clock seam returns a tz-aware datetime usable by strftime/isoformat
    moment = captured["now"]()
    assert moment.tzinfo is not None
    moment.strftime("%Y%m%dT%H%M%SZ")


def test_uploader_supplies_required_seams(monkeypatch):
    """deps.uploader(archive_result) must feed upload its runner + queue_dir."""
    captured = {}

    def spy_upload(archive_result, *, runner, queue_dir, **kw):
        captured.update(archive_result=archive_result, runner=runner, queue_dir=queue_dir)
        return "UPLOAD_RESULT"

    monkeypatch.setattr(uploader_mod, "upload", spy_upload)
    deps = _default_build_deps("/tmp/some-repo")
    result = deps.uploader("ARCHIVE_RESULT")

    assert result == "UPLOAD_RESULT"
    assert captured["archive_result"] == "ARCHIVE_RESULT"
    assert callable(captured["runner"])
    assert isinstance(captured["queue_dir"], str) and captured["queue_dir"]


def test_runner_seam_is_real_subprocess(monkeypatch):
    """The injected runner must actually shell out (capture, non-raising)."""
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        seen["kw"] = kw

        class _R:
            returncode = 0
            stdout = b""
            stderr = b""
        return _R()

    import subprocess
    monkeypatch.setattr(subprocess, "run", fake_run)

    captured = {}

    def spy_build_archive(repo_root, sha, *, runner, now, out_dir, base_sha=None, **kw):
        captured["runner"] = runner
        return None

    monkeypatch.setattr(archiver_mod, "build_archive", spy_build_archive)
    deps = _default_build_deps("/tmp/some-repo")
    deps.archiver("/tmp/some-repo", "abc")
    out = captured["runner"](["echo", "hi"])
    assert seen["argv"] == ["echo", "hi"]
    assert getattr(out, "returncode", None) == 0
