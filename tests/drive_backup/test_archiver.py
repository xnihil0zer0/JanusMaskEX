"""RED oracle for leaf `drive-backup-archiver` (archiver half).

Pins `tools/drive_backup/archiver.py`: DEFAULT_EXCLUDES (frozenset),
ArchiveResult{archive_path, diff_path, base_sha, manifest}, and
build_archive(repo_root, sha, *, runner, now, out_dir,
exclude=DEFAULT_EXCLUDES, base_sha=None) -> ArchiveResult.

Hermetic: tar/zstd/git are NEVER really executed — the `runner` seam is a
spy that records argv and returns a CompletedProcess-like; `now` is an
injected fixed UTC clock. Tests assert naming, exclude materialization,
argv shape, seam usage, and manifest contents only.
"""
import datetime as dt
from types import SimpleNamespace

import pytest

from tools.drive_backup import archiver
from tools.drive_backup.archiver import (
    DEFAULT_EXCLUDES,
    ArchiveResult,
    build_archive,
)


FIXED_NOW = dt.datetime(2026, 6, 12, 23, 15, 0, tzinfo=dt.timezone.utc)
SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9001122334"
SHA7 = "a1b2c3d"


class SpyRunner:
    """Records every argv passed; returns a success CompletedProcess-like."""

    def __init__(self, rc=0):
        self.calls = []
        self._rc = rc

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        return SimpleNamespace(returncode=self._rc, stdout=b"", stderr=b"")


def _now():
    return FIXED_NOW


def test_default_excludes_is_frozenset_with_cache_dirs():
    assert isinstance(DEFAULT_EXCLUDES, frozenset)
    for item in (
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        "*.pyc",
        "state/output",
        "_autowork_archive",
    ):
        assert item in DEFAULT_EXCLUDES


def test_artifact_stem_is_repo_sha7_compactutc(tmp_path):
    out = tmp_path / "out"
    res = build_archive(
        "/home/xnihil0zer0/AI-Data/JanusMaskEX",
        SHA,
        runner=SpyRunner(),
        now=_now,
        out_dir=str(out),
        base_sha="0" * 40,
    )
    assert isinstance(res, ArchiveResult)
    stem = f"JanusMaskEX_{SHA7}_20260612T231500Z"
    assert res.archive_path.endswith(f"{stem}.tar.zst")
    assert res.diff_path.endswith(f"{stem}.diff")
    assert res.manifest["stem"] == stem
    assert res.manifest["repo"] == "JanusMaskEX"
    assert res.manifest["sha"] == SHA


def test_runner_is_the_only_subprocess_path_and_argv_shape(tmp_path):
    spy = SpyRunner()
    res = build_archive(
        "/repo/JanusMaskEX",
        SHA,
        runner=spy,
        now=_now,
        out_dir=str(tmp_path),
        base_sha="b" * 40,
    )
    assert spy.calls, "runner seam was never invoked"
    flat = [tok for call in spy.calls for tok in call]
    # tar + zstd archive pipeline referenced through the runner.
    assert any("tar" in tok for tok in flat)
    assert any("zstd" in tok for tok in flat)
    # git diff between base..sha invoked through the runner.
    git_call = next((c for c in spy.calls if any("git" in t for t in c)), None)
    assert git_call is not None
    assert "diff" in git_call
    assert any(("b" * 40) in t and SHA in t for t in git_call) or (
        ("b" * 40) in git_call and SHA in git_call
    )
    # Manifest records the constructed argvs (not real execution).
    assert res.manifest["archive_argv"]
    assert res.manifest["diff_argv"]


def test_excludes_are_materialized_as_exclude_args(tmp_path):
    spy = SpyRunner()
    res = build_archive(
        "/repo/JanusMaskEX",
        SHA,
        runner=spy,
        now=_now,
        out_dir=str(tmp_path),
        exclude=frozenset({"node_modules", "__pycache__"}),
        base_sha="c" * 40,
    )
    archive_argv = res.manifest["archive_argv"]
    joined = " ".join(archive_argv)
    assert "--exclude" in archive_argv
    assert "node_modules" in joined
    assert "__pycache__" in joined
    assert set(res.manifest["excludes"]) == {"node_modules", "__pycache__"}


def test_git_dir_included_by_default(tmp_path):
    res = build_archive(
        "/repo/JanusMaskEX",
        SHA,
        runner=SpyRunner(),
        now=_now,
        out_dir=str(tmp_path),
        exclude=DEFAULT_EXCLUDES,
        base_sha="d" * 40,
    )
    # .git is not in the exclude set by default → whole-dir honored.
    assert ".git" not in res.manifest["excludes"]
    assert "--exclude .git" not in " ".join(res.manifest["archive_argv"])


def test_first_ever_backup_uses_empty_base_diff_form(tmp_path):
    spy = SpyRunner()
    res = build_archive(
        "/repo/JanusMaskEX",
        SHA,
        runner=spy,
        now=_now,
        out_dir=str(tmp_path),
        base_sha=None,
    )
    assert res.base_sha is None
    git_call = next(c for c in spy.calls if any("git" in t for t in c))
    assert "diff" in git_call
    # Empty-base full diff form: the sha appears, no `base..sha` range token.
    assert any(SHA in t for t in git_call)
    assert not any(".." in t for t in git_call)
    assert res.manifest["base_sha"] is None


def test_manifest_is_jsonable_and_complete(tmp_path):
    import json

    res = build_archive(
        "/repo/JanusMaskEX",
        SHA,
        runner=SpyRunner(),
        now=_now,
        out_dir=str(tmp_path),
        base_sha="e" * 40,
    )
    m = res.manifest
    for key in (
        "repo",
        "sha",
        "base_sha",
        "stem",
        "excludes",
        "archive_argv",
        "diff_argv",
        "created_at",
    ):
        assert key in m
    # JSON round-trips (no non-serializable objects leaked into the manifest).
    json.dumps(m)


# ---- diff-file contract + REAL integration (catches the unwritten-.diff bug) --

def test_diff_argv_writes_to_diff_path_via_output_flag(tmp_path):
    """git diff must write the file itself (--output=<diff_path>); the runner
    only executes argv and never redirects stdout, so a bare `git diff <sha>`
    would silently produce no .diff file."""
    spy = SpyRunner()
    res = build_archive(
        "/repo/JanusMaskEX", SHA, runner=spy, now=_now,
        out_dir=str(tmp_path), base_sha="b" * 40,
    )
    git_call = next(c for c in spy.calls if any("git" in t for t in c))
    assert any(t == f"--output={res.diff_path}" for t in git_call), git_call


def test_real_git_and_tar_produce_both_artifacts(tmp_path):
    """Integration: run the REAL subprocess runner against a REAL git repo and
    assert the .tar.zst AND .diff are actually written and non-empty. This is
    the end-to-end check the hermetic units could not provide."""
    import os
    import shutil
    import subprocess

    if shutil.which("git") is None or shutil.which("zstd") is None:
        pytest.skip("git/zstd not available")

    repo = tmp_path / "repo"
    repo.mkdir()

    def run(argv, **kw):
        return subprocess.run(argv, capture_output=True, check=False, **kw)

    run(["git", "-C", str(repo), "init", "-q"])
    run(["git", "-C", str(repo), "config", "user.email", "t@t"])
    run(["git", "-C", str(repo), "config", "user.name", "t"])
    (repo / "a.txt").write_text("hello\n")
    run(["git", "-C", str(repo), "add", "."])
    run(["git", "-C", str(repo), "commit", "-q", "-m", "c1"])
    sha = run(["git", "-C", str(repo), "rev-parse", "HEAD"]).stdout.decode().strip()
    # working-tree change so the (base=None) full diff is non-empty
    (repo / "a.txt").write_text("hello\nworld\n")

    out = tmp_path / "out"
    res = build_archive(str(repo), sha, runner=run, now=_now, out_dir=str(out))

    assert os.path.isfile(res.archive_path), "tar.zst not written"
    assert os.path.getsize(res.archive_path) > 0
    assert os.path.isfile(res.diff_path), "diff file not written"
    assert os.path.getsize(res.diff_path) > 0
    assert b"world" in (out / os.path.basename(res.diff_path)).read_bytes()
