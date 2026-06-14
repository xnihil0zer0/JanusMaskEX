"""RED oracle: drive-backup must back up the REPO BEING PUSHED, not always JanusMask.

Root cause being pinned (2026-06-14): the pre-push shim must ``cd`` into
JANUSMASK_ROOT to import ``tools.drive_backup.hook_runner``; git invokes the
hook with a RELATIVE ``GIT_DIR='.git'``; ``_resolve_repo_root`` resolved that
against the now-JanusMask cwd, so EVERY repo's push backed up the JanusMask
tree (mislabeled with the pushed sha). NobleGreedv2 was never actually backed
up.

The fix has two halves, both pinned here:
1. ``render_shim`` captures the pushed repo top-level via
   ``git rev-parse --show-toplevel`` BEFORE the ``cd`` and exports it as
   ``JM_PUSH_REPO`` to the runner.
2. ``hook_runner._resolve_repo_root`` honors ``$JM_PUSH_REPO`` FIRST.
3. ``run_backup`` scopes the ledger base_sha / record by the pushed repo's
   basename (so a global ledger doesn't hand one repo another repo's sha).

Hermetic: no real git/push/network; render_shim is pure text, _resolve_repo_root
reads env (monkeypatched), run_backup uses injected fakes.
"""
from types import SimpleNamespace

from tools.drive_backup import hook_runner
from tools.drive_backup.hook_runner import run_backup
from tools.drive_backup.install_hooks import render_shim


JM_ROOT = "/home/xnihil0zer0/JanusMaskJR"
ZERO = "0" * 40


# ---- shim captures the pushed repo BEFORE cd ----------------------------

def test_shim_captures_push_repo_before_cd():
    shim = render_shim(JM_ROOT)
    assert "git rev-parse --show-toplevel" in shim
    assert "JM_PUSH_REPO" in shim
    # The capture must happen BEFORE we cd into the JanusMask root, otherwise
    # show-toplevel would resolve to JanusMask itself.
    capture_at = shim.index("JM_PUSH_REPO=\"$(git rev-parse --show-toplevel")
    cd_at = shim.index('cd "$JANUSMASK_ROOT"')
    assert capture_at < cd_at, "JM_PUSH_REPO must be captured before cd"


def test_shim_passes_push_repo_to_runner():
    shim = render_shim(JM_ROOT)
    # The captured value is handed to the python runner process (not just printf).
    assert 'JM_PUSH_REPO="$JM_PUSH_REPO" python -m tools.drive_backup.hook_runner' in shim
    # Still never blocks a push.
    assert "exit 0" in shim


# ---- _resolve_repo_root honors JM_PUSH_REPO first -----------------------

def test_resolve_repo_root_prefers_jm_push_repo(tmp_path, monkeypatch):
    pushed = tmp_path / "NobleGreedv2"
    pushed.mkdir()
    monkeypatch.setenv("JM_PUSH_REPO", str(pushed))
    # GIT_DIR points elsewhere (the JanusMask-cwd trap); it must be ignored.
    monkeypatch.setenv("GIT_DIR", ".git")
    monkeypatch.chdir(tmp_path)
    assert hook_runner._resolve_repo_root() == str(pushed)


def test_resolve_repo_root_falls_back_to_git_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("JM_PUSH_REPO", raising=False)
    repo = tmp_path / "somerepo"
    repo.mkdir()
    monkeypatch.setenv("GIT_DIR", str(repo / ".git"))
    assert hook_runner._resolve_repo_root() == str(repo)


def test_resolve_repo_root_ignores_nonexistent_push_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("JM_PUSH_REPO", str(tmp_path / "does_not_exist"))
    repo = tmp_path / "real"
    repo.mkdir()
    monkeypatch.setenv("GIT_DIR", str(repo / ".git"))
    # A bogus JM_PUSH_REPO must not win over a resolvable GIT_DIR.
    assert hook_runner._resolve_repo_root() == str(repo)


# ---- run_backup scopes the ledger by the pushed repo --------------------

class RepoSpyLedger:
    """Records the repo tag and answers base queries per-repo."""

    def __init__(self, per_repo):
        self.per_repo = dict(per_repo)
        self.records = []

    def last_backed_up_sha(self, repo=None):
        return self.per_repo.get(repo)

    def record(self, sha, archive_name, uploaded, repo=None):
        self.records.append((sha, archive_name, uploaded, repo))


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
        return SimpleNamespace(uploaded=True, queued=False,
                               remote_path="gdrive:x/", error=None)
    return _up


def _refs_for(sha):
    return [SimpleNamespace(local_ref="refs/heads/master", local_sha=sha,
                            remote_ref="refs/heads/master", remote_sha="z" * 40)]


def test_run_backup_scopes_base_and_record_by_repo():
    base_seen = []
    led = RepoSpyLedger({"NobleGreedv2": "n" * 40, "JanusMaskJR": "j" * 40})
    rc = run_backup(
        "/home/xnihil0zer0/NobleGreedv2",
        _refs_for("a" * 40),
        archiver=_ok_archiver(base_seen),
        uploader=_ok_uploader(),
        ledger=led,
        log=lambda *a, **k: None,
    )
    assert rc == 0
    # The archiver got NobleGreedv2's base sha, NOT JanusMask's.
    assert base_seen == ["n" * 40]
    # The new row is tagged with the pushed repo's basename.
    assert led.records and led.records[0][3] == "NobleGreedv2"
    assert led.records[0][0] == "a" * 40
