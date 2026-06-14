"""RED oracle for leaf `drive-backup-hook-runner`.

Pins `tools/drive_backup/hook_runner.py`:
parse_push_refs(stdin_text) -> list[PushRef{local_ref, local_sha,
remote_ref, remote_sha}], pushed_shas(refs) -> list[str],
run_backup(repo_root, refs, *, archiver, uploader, ledger, log) -> int
(ALWAYS 0, never raises), main(argv=None, *, stdin=None, repo_root=None,
build_deps=None) -> int (ALWAYS 0).

Hermetic: archiver/uploader/ledger/log/stdin/build_deps are injected
fakes/spies. No real subprocess/network/git/clock. The CENTRAL contract:
every failure path STILL returns 0 (a push is never blocked).
"""
from types import SimpleNamespace

import pytest

from tools.drive_backup import hook_runner
from tools.drive_backup.hook_runner import (
    parse_push_refs,
    pushed_shas,
    run_backup,
)


ZERO = "0" * 40


# ---- ref parsing ---------------------------------------------------------

def test_parse_push_refs_basic():
    text = (
        "refs/heads/main aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa "
        "refs/heads/main bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"
    )
    refs = parse_push_refs(text)
    assert len(refs) == 1
    r = refs[0]
    assert r.local_ref == "refs/heads/main"
    assert r.local_sha == "a" * 40
    assert r.remote_ref == "refs/heads/main"
    assert r.remote_sha == "b" * 40


def test_parse_push_refs_skips_blank_lines_and_deletions():
    text = (
        "\n"
        "refs/heads/main " + "a" * 40 + " refs/heads/main " + "b" * 40 + "\n"
        "\n"
        # deletion: all-zero local_sha → skipped
        "(delete) " + ZERO + " refs/heads/old " + "c" * 40 + "\n"
    )
    refs = parse_push_refs(text)
    assert len(refs) == 1
    assert refs[0].local_sha == "a" * 40


def test_pushed_shas_dedupes_and_excludes_deletions():
    refs = [
        SimpleNamespace(local_ref="r1", local_sha="a" * 40,
                        remote_ref="r1", remote_sha="x" * 40),
        SimpleNamespace(local_ref="r2", local_sha="a" * 40,
                        remote_ref="r2", remote_sha="y" * 40),
        SimpleNamespace(local_ref="r3", local_sha=ZERO,
                        remote_ref="r3", remote_sha="z" * 40),
    ]
    shas = pushed_shas(refs)
    assert shas == ["a" * 40]


# ---- orchestration fakes -------------------------------------------------

class SpyLog:
    def __init__(self):
        self.lines = []

    def __call__(self, *a, **kw):
        self.lines.append((a, kw))


class SpyLedger:
    def __init__(self, base=None):
        self._base = base
        self.records = []

    def last_backed_up_sha(self, repo=None):
        return self._base

    def record(self, sha, archive_name, uploaded, repo=None):
        self.records.append((sha, archive_name, uploaded))


def _ok_archiver(base_seen):
    def _arch(repo_root, sha, **kw):
        base_seen.append(kw.get("base_sha"))
        return SimpleNamespace(
            archive_path=f"/tmp/{sha[:7]}.tar.zst",
            diff_path=f"/tmp/{sha[:7]}.diff",
            base_sha=kw.get("base_sha"),
            manifest={"stem": f"repo_{sha[:7]}_ts"},
        )
    return _arch


def _ok_uploader():
    def _up(archive_result, **kw):
        return SimpleNamespace(
            uploaded=True, queued=False,
            remote_path="gdrive:repo-push-backups/repo/", error=None)
    return _up


def _refs_for(sha):
    return [SimpleNamespace(local_ref="refs/heads/main", local_sha=sha,
                            remote_ref="refs/heads/main", remote_sha="z" * 40)]


def test_run_backup_happy_path_wires_base_sha_and_records():
    sha = "a" * 40
    base_seen = []
    led = SpyLedger(base="f" * 40)
    log = SpyLog()
    rc = run_backup(
        "/repo",
        _refs_for(sha),
        archiver=_ok_archiver(base_seen),
        uploader=_ok_uploader(),
        ledger=led,
        log=log,
    )
    assert rc == 0
    # base_sha read from the ledger was passed into the archiver.
    assert base_seen == ["f" * 40]
    # Ledger recorded after a successful archive, with uploaded flag.
    assert led.records and led.records[0][0] == sha
    assert led.records[0][2] is True


def test_run_backup_returns_0_when_archiver_raises():
    log = SpyLog()
    led = SpyLedger()

    def boom_archiver(repo_root, sha, **kw):
        raise RuntimeError("tar exploded")

    rc = run_backup(
        "/repo",
        _refs_for("a" * 40),
        archiver=boom_archiver,
        uploader=_ok_uploader(),
        ledger=led,
        log=log,
    )
    assert rc == 0
    assert log.lines, "failure must be logged loudly"
    # Ledger NOT recorded when the archive failed.
    assert led.records == []


def test_run_backup_returns_0_when_uploader_raises():
    log = SpyLog()
    led = SpyLedger()

    def boom_uploader(archive_result, **kw):
        raise RuntimeError("rclone exploded")

    rc = run_backup(
        "/repo",
        _refs_for("a" * 40),
        archiver=_ok_archiver([]),
        uploader=boom_uploader,
        ledger=led,
        log=log,
    )
    assert rc == 0
    assert log.lines


def test_run_backup_returns_0_when_ledger_record_raises():
    log = SpyLog()

    class BoomLedger(SpyLedger):
        def record(self, *a, **kw):
            raise RuntimeError("disk full")

    rc = run_backup(
        "/repo",
        _refs_for("a" * 40),
        archiver=_ok_archiver([]),
        uploader=_ok_uploader(),
        ledger=BoomLedger(),
        log=log,
    )
    assert rc == 0
    assert log.lines


def test_main_always_returns_0_via_injected_seams():
    log = SpyLog()
    led = SpyLedger(base=None)
    stdin = (
        "refs/heads/main " + "a" * 40 + " refs/heads/main " + "b" * 40 + "\n"
    )

    def build_deps(repo_root):
        return SimpleNamespace(
            archiver=_ok_archiver([]),
            uploader=_ok_uploader(),
            ledger=led,
            log=log,
        )

    rc = hook_runner.main(
        argv=[],
        stdin=stdin,
        repo_root="/repo",
        build_deps=build_deps,
    )
    assert rc == 0


def test_main_returns_0_when_build_deps_raises():
    def boom_build(repo_root):
        raise RuntimeError("cannot wire deps")

    rc = hook_runner.main(
        argv=[],
        stdin="refs/heads/main " + "a" * 40 + " r " + "b" * 40 + "\n",
        repo_root="/repo",
        build_deps=boom_build,
    )
    # Top-level exception swallowed-and-logged; push never blocked.
    assert rc == 0
