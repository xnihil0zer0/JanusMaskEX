"""B3 F1 follow-up — adversarial coverage for the drain-baseline auto-commit.

Target surface: module-level helpers in ``scripts/impl_drain_capture.py``

  - ``_ledger_append_observation(*, detail, files, approved_by=...)``
  - ``_auto_commit_drain_baseline(*, baseline_path, brief_id, session,
    state_dir, repo_root=_REPO_ROOT) -> bool``

These were wired into ``main()`` after ``save_drain_baseline`` (lines
1419-1430) to close the pre-flight ``git checkout --`` race documented
in ``state/impl_progress.jsonl`` row ``2026-04-20T15:11:00Z``.

The helpers MUST:

  * Never raise (drain is mid-cycle — crashes lose capture).
  * Never touch ``HEAD`` in a non-git cwd.
  * Never sweep unrelated staged changes into their commit.
  * Never emit an empty commit for a no-op diff.
  * Gracefully handle missing/outside-repo baseline paths.
  * Tolerate hostile ``brief_id`` values — newline injection, globs,
    path traversal, command-injection shapes.
  * Keep the real project ledger at
    ``state/impl_progress.jsonl`` pristine when called from tmp-repo
    fixtures (F1 self-reported defect: ``_IMPL_PROGRESS_LEDGER`` is
    a hardcoded module constant).

Import style follows F1's own throwaway-test pattern: load the wrapper
via ``importlib.util`` because it lives under ``scripts/`` (not a
package). This lets the tests exercise the real helpers without
altering ``sys.path`` globally.

Hermeticity rules:

  * Every test uses ``tmp_path`` for its repo.
  * Every test monkey-patches ``_IMPL_PROGRESS_LEDGER`` to a tmp file.
  * Assertions confirm the real ``state/impl_progress.jsonl`` is
    untouched by the helper execution.

Vectors covered (numbered to match the B3 F1 follow-up brief):

  1. Lock contention / parallel drains (sequential serialisation).
  2. Stale ``.git/index.lock``.
  3. Non-git cwd.
  4. Missing baseline path.
  5. Symlink pointing outside repo.
  6. Unrelated staged changes must not be swept.
  7. No-op diff — no empty commit.
  8. Glob injection via ``brief_id``.
  9. ``brief_id`` with slashes / traversal.
 10. Pre-commit hook failure.
 11. Control chars in ``brief_id`` (newline injection).
 12. Concurrent ``_ledger_append_observation``.
 13. Large baseline (scaled down for runtime).
 14. Read-only filesystem (skipped — needs mount).
 15. ``_IMPL_PROGRESS_LEDGER`` leakage / parameterisability.
 16. Disk-full mid-commit (skipped — needs quota).
 17. SIGTERM mid-commit (skipped — needs pgroup harness).
 18. Detached HEAD.
 19. ``brief_id`` collision — second call no-ops.
 20. Ledger append from non-writable target path.
 21. (invented) Helper reports success only when commit actually landed.
 22. (invented) Evidence-file glob escape — ``brief_id`` is NOT injected
     into the sessions glob (helper uses literal ``claude_round*_*``).
 23. (invented) OSError on baseline path (broken symlink) does not crash.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DRAIN_SRC = REPO_ROOT / "scripts" / "impl_drain_capture.py"


def _load_drain_module():
    """Load ``scripts/impl_drain_capture.py`` via importlib.

    F1's own throwaway test confirmed this pattern works; the module
    is not in a package so a plain ``import`` path is awkward.
    """
    # Ensure the repo root is on sys.path so the ``harness.*`` imports
    # inside the module resolve (the module does ``sys.path.insert`` on
    # its own ``_REPO_ROOT`` but we mirror that here for safety).
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    spec = importlib.util.spec_from_file_location(
        "impl_drain_capture_under_test", DRAIN_SRC
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def drain_mod():
    return _load_drain_module()


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.setdefault("GIT_AUTHOR_NAME", "JanusMask Test")
    env.setdefault("GIT_AUTHOR_EMAIL", "test@janusmask.local")
    env.setdefault("GIT_COMMITTER_NAME", "JanusMask Test")
    env.setdefault("GIT_COMMITTER_EMAIL", "test@janusmask.local")
    return subprocess.run(
        ["git", *args], cwd=str(cwd), env=env, check=check,
        capture_output=True, text=True, timeout=30,
    )


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Seed a fresh git repo at ``tmp_path/repo`` with a single commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "JanusMask Test")
    _git(repo, "config", "user.email", "test@janusmask.local")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "seed.txt")
    _git(repo, "commit", "-q", "-m", "seed")
    (repo / "state" / "hooks").mkdir(parents=True)
    (repo / "state" / "sessions").mkdir(parents=True)
    return repo


@pytest.fixture
def tmp_ledger(tmp_path: Path, drain_mod, monkeypatch):
    """Redirect ``_IMPL_PROGRESS_LEDGER`` to a tmp file so the real
    ``state/impl_progress.jsonl`` is never touched during tests.
    """
    tmp_led = tmp_path / "tmp_impl_progress.jsonl"
    # Snapshot real ledger size BEFORE test body runs — assert afterwards.
    real_ledger = REPO_ROOT / "state" / "impl_progress.jsonl"
    before_size = real_ledger.stat().st_size if real_ledger.exists() else 0
    before_mtime = real_ledger.stat().st_mtime_ns if real_ledger.exists() else 0
    monkeypatch.setattr(drain_mod, "_IMPL_PROGRESS_LEDGER", tmp_led)
    yield tmp_led
    # Post-condition: the real ledger must not have been modified by the
    # helper under test. (Tests explicitly appending via the MAIN ledger
    # path — e.g. the write/test_pass rows at teardown — do so OUTSIDE the
    # helper fixture, so this check stays honest.)
    if real_ledger.exists():
        assert real_ledger.stat().st_size == before_size, (
            "real state/impl_progress.jsonl was modified during test — "
            "tmp_ledger monkeypatch leaked"
        )
        assert real_ledger.stat().st_mtime_ns == before_mtime, (
            "real state/impl_progress.jsonl mtime changed during test"
        )


def _make_baseline(repo: Path, brief_id: str = "stab_001") -> Path:
    baseline = repo / "state" / "hooks" / f"drain_baseline_{brief_id}.json"
    baseline.write_text(
        json.dumps({"brief_id": brief_id, "patch_stat": "x"}) + "\n",
        encoding="utf-8",
    )
    return baseline


# ===========================================================================
# Vector 3: non-git cwd
# ===========================================================================

def test_03_non_git_repo_root_returns_false_without_raise(
    tmp_path, drain_mod, tmp_ledger
):
    """Pointing ``repo_root`` at a non-git directory must not raise and
    must return False + leave a ledger breadcrumb.
    """
    non_git = tmp_path / "not_a_repo"
    non_git.mkdir()
    (non_git / "state" / "hooks").mkdir(parents=True)
    (non_git / "state" / "sessions").mkdir(parents=True)
    baseline = non_git / "state" / "hooks" / "drain_baseline_stab_001.json"
    baseline.write_text("{}\n", encoding="utf-8")

    rc = drain_mod._auto_commit_drain_baseline(
        baseline_path=baseline,
        brief_id="stab_001",
        session="sess",
        state_dir=non_git / "state",
        repo_root=non_git,
    )
    assert rc is False
    # Ledger must contain an observation row recording the git failure.
    assert tmp_ledger.exists()
    lines = [json.loads(l) for l in tmp_ledger.read_text().splitlines() if l]
    assert any("git add" in r["detail"] or "git" in r["detail"] for r in lines), (
        f"expected a git-failure observation, got {lines!r}"
    )


# ===========================================================================
# Vector 4: missing baseline path
# ===========================================================================

def test_04_missing_baseline_returns_false_no_commit(
    tmp_repo, drain_mod, tmp_ledger
):
    """Non-existent baseline path: helper returns False, emits ledger row,
    does NOT invoke ``git commit``.
    """
    baseline = tmp_repo / "state" / "hooks" / "drain_baseline_stab_001.json"
    assert not baseline.exists()
    before_head = _git(tmp_repo, "rev-parse", "HEAD").stdout.strip()

    rc = drain_mod._auto_commit_drain_baseline(
        baseline_path=baseline,
        brief_id="stab_001",
        session="sess",
        state_dir=tmp_repo / "state",
        repo_root=tmp_repo,
    )
    assert rc is False
    after_head = _git(tmp_repo, "rev-parse", "HEAD").stdout.strip()
    assert before_head == after_head, "no commit should have been made"
    lines = [json.loads(l) for l in tmp_ledger.read_text().splitlines() if l]
    assert any("not present on disk" in r["detail"] for r in lines)


# ===========================================================================
# Vector 5: symlinked baseline pointing OUTSIDE the repo
# ===========================================================================

def test_05_symlink_outside_repo_is_refused(
    tmp_path, tmp_repo, drain_mod, tmp_ledger
):
    """Baseline is a symlink pointing outside the repo root. The
    ``relative_to(repo_root)`` guard should short-circuit into the
    "escapes repo root" branch IF the absolute path resolves outside —
    otherwise the commit would try to ingest foreign bytes.

    NOTE: the helper only takes ``.relative_to`` when ``baseline_path``
    is already absolute; we hand it the absolute symlink target to
    exercise the guard.
    """
    outside = tmp_path / "outside_bytes.json"
    outside.write_text("{}\n", encoding="utf-8")
    link = tmp_repo / "state" / "hooks" / "drain_baseline_stab_001.json"
    # Point the symlink at the absolute out-of-repo path. The helper is
    # invoked with the symlink path itself (inside the repo) — git will
    # add the symlink-as-file, which may or may not expose the target.
    link.symlink_to(outside)

    rc = drain_mod._auto_commit_drain_baseline(
        baseline_path=link,
        brief_id="stab_001",
        session="sess",
        state_dir=tmp_repo / "state",
        repo_root=tmp_repo,
    )
    # The link IS inside repo_root, so relative_to succeeds — this test
    # documents the observed behaviour: git commits the symlink (mode
    # 120000) pointing at the outside path. That is acceptable (git's
    # own handling) — the tripwire is that the OUTSIDE file's contents
    # are NOT embedded into the repo. Assert the commit stored a symlink,
    # not a regular blob.
    if rc:
        blob_mode = _git(
            tmp_repo, "ls-tree", "HEAD", "--",
            "state/hooks/drain_baseline_stab_001.json",
        ).stdout.strip().split()[0]
        assert blob_mode == "120000", (
            f"symlink committed as non-symlink mode {blob_mode} — "
            "content of outside file was ingested into the repo"
        )


# ===========================================================================
# Vector 6: unrelated staged changes must not be swept
# ===========================================================================

def test_06_unrelated_staged_changes_not_swept(
    tmp_repo, drain_mod, tmp_ledger
):
    """Stage an unrelated file BEFORE calling the helper. The helper's
    commit must NOT include the unrelated file — ``git commit --
    <pathspec>`` is scoped to the baseline + evidence the helper staged.

    F1-HIGH FIXED (2026-04-21 closeout defect #1): the helper now passes
    ``-- baseline_rel *evidence_paths`` to ``git commit``.
    """
    # Unrelated staged change.
    (tmp_repo / "unrelated.txt").write_text("unrelated\n", encoding="utf-8")
    _git(tmp_repo, "add", "unrelated.txt")

    baseline = _make_baseline(tmp_repo)

    rc = drain_mod._auto_commit_drain_baseline(
        baseline_path=baseline,
        brief_id="stab_001",
        session="sess",
        state_dir=tmp_repo / "state",
        repo_root=tmp_repo,
    )
    assert rc is True, "baseline was new — helper should have committed"

    files = _git(
        tmp_repo, "show", "--name-only", "--format=", "HEAD"
    ).stdout.split()
    assert "unrelated.txt" not in files, (
        "regression: helper commit swept unrelated.txt despite pathspec "
        f"scoping; HEAD files={files!r}"
    )
    assert "state/hooks/drain_baseline_stab_001.json" in files
    # Pathspec scoping does not unstage — the unrelated file must still
    # be in the index for the operator to review and commit / reset as
    # they see fit.
    staged = _git(
        tmp_repo, "diff", "--cached", "--name-only"
    ).stdout.split()
    assert "unrelated.txt" in staged, (
        "pathspec scoping should leave unrelated.txt in the index; got "
        f"{staged!r}"
    )


# ===========================================================================
# Vector 7: no-op diff — no empty commit
# ===========================================================================

def test_07_noop_diff_skips_commit(tmp_repo, drain_mod, tmp_ledger):
    """Baseline is already at HEAD: helper must detect via
    ``git diff --cached --quiet`` and skip. No empty commit.
    """
    baseline = _make_baseline(tmp_repo)
    # Pre-commit the baseline so the next helper call is a no-op.
    _git(tmp_repo, "add", "state/hooks/drain_baseline_stab_001.json")
    _git(tmp_repo, "commit", "-q", "-m", "pre-commit baseline")
    before_head = _git(tmp_repo, "rev-parse", "HEAD").stdout.strip()

    rc = drain_mod._auto_commit_drain_baseline(
        baseline_path=baseline,
        brief_id="stab_001",
        session="sess",
        state_dir=tmp_repo / "state",
        repo_root=tmp_repo,
    )
    assert rc is False, "no-op diff must not produce a commit"
    after_head = _git(tmp_repo, "rev-parse", "HEAD").stdout.strip()
    assert before_head == after_head


# ===========================================================================
# Vector 8: glob injection via brief_id
# ===========================================================================

def test_08_brief_id_with_glob_metachars_does_not_expand(
    tmp_repo, drain_mod, tmp_ledger
):
    """``brief_id`` flows into the commit message, NOT into the evidence
    glob (the evidence glob uses literal ``claude_round*_*``). Confirm a
    hostile ``brief_id`` does not expand into unintended file matches
    and does not trigger a shell invocation.
    """
    # Evidence decoys that would match a naive glob.
    (tmp_repo / "state" / "sessions" / "claude_round1_decoy_submission.json"
     ).write_text("{}", encoding="utf-8")
    baseline = _make_baseline(tmp_repo, brief_id="stab_001")

    hostile = "stab_001; rm -rf /"
    rc = drain_mod._auto_commit_drain_baseline(
        baseline_path=baseline,
        brief_id=hostile,
        session="sess",
        state_dir=tmp_repo / "state",
        repo_root=tmp_repo,
    )
    assert rc is True
    # Confirm nothing catastrophic — the repo still exists and HEAD moved.
    assert tmp_repo.exists()
    subject = _git(tmp_repo, "log", "-1", "--format=%s").stdout.strip()
    # subprocess.run with a list arg is exec'd directly, not via shell —
    # the ``; rm -rf /`` is safe as a literal in the subject.
    assert hostile in subject, f"brief_id literal must appear: {subject!r}"


# ===========================================================================
# Vector 9: brief_id with slashes / traversal
# ===========================================================================

def test_09_brief_id_with_slashes_passes_through(
    tmp_repo, drain_mod, tmp_ledger
):
    """The helper does NOT use ``brief_id`` as a path component — it
    only interpolates into the commit subject. Confirm ``../../etc/passwd``
    is harmless (literal text in the commit message) and no files are
    read from outside the repo.
    """
    baseline = _make_baseline(tmp_repo)
    rc = drain_mod._auto_commit_drain_baseline(
        baseline_path=baseline,
        brief_id="../../etc/passwd",
        session="sess",
        state_dir=tmp_repo / "state",
        repo_root=tmp_repo,
    )
    assert rc is True
    # The evidence glob is scoped to state_dir/sessions/ and uses
    # literal prefixes — no traversal possible.
    subject = _git(tmp_repo, "log", "-1", "--format=%s").stdout.strip()
    assert "etc/passwd" in subject  # literal, not resolved


# ===========================================================================
# Vector 10: pre-commit hook failure
# ===========================================================================

def test_10_pre_commit_hook_failure_returns_false(
    tmp_repo, drain_mod, tmp_ledger
):
    """Configure a pre-commit hook that exits 1. Helper must NOT claim
    success; it must return False and leave a ledger breadcrumb.
    """
    hook = tmp_repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    baseline = _make_baseline(tmp_repo)
    before_head = _git(tmp_repo, "rev-parse", "HEAD").stdout.strip()

    rc = drain_mod._auto_commit_drain_baseline(
        baseline_path=baseline,
        brief_id="stab_001",
        session="sess",
        state_dir=tmp_repo / "state",
        repo_root=tmp_repo,
    )
    assert rc is False, (
        "pre-commit hook failed — helper must NOT report success"
    )
    after_head = _git(tmp_repo, "rev-parse", "HEAD").stdout.strip()
    assert before_head == after_head, "no commit must land on hook failure"
    lines = [json.loads(l) for l in tmp_ledger.read_text().splitlines() if l]
    assert any("git commit" in r["detail"] for r in lines)


# ===========================================================================
# Vector 11: control chars / newline injection in brief_id
# ===========================================================================

def test_11_newline_in_brief_id_does_not_split_subject(
    tmp_repo, drain_mod, tmp_ledger
):
    """``brief_id`` is interpolated with an f-string into the commit
    subject/body. Newlines in ``brief_id`` would split the subject from
    the body and smuggle Co-Authored-By / Signed-off-by trailers.

    F1-MED FIXED (2026-04-21 closeout defect #3): the helper now rejects
    any ``brief_id`` containing ``\\n`` or ``\\r`` at entry, returns
    False, and leaves a ledger breadcrumb. No commit lands. HEAD does
    not move.
    """
    baseline = _make_baseline(tmp_repo)
    before_head = _git(tmp_repo, "rev-parse", "HEAD").stdout.strip()
    rc = drain_mod._auto_commit_drain_baseline(
        baseline_path=baseline,
        brief_id="stab_001\nSubject: pwned\n\nBody: malicious",
        session="sess",
        state_dir=tmp_repo / "state",
        repo_root=tmp_repo,
    )
    assert rc is False, "helper must refuse newline-bearing brief_id"
    after_head = _git(tmp_repo, "rev-parse", "HEAD").stdout.strip()
    assert before_head == after_head, "no commit must land on refusal"
    # Confirm the injected ``Subject: pwned`` trailer never reached git.
    body = _git(tmp_repo, "log", "-1", "--format=%B").stdout
    assert "Subject: pwned" not in body, (
        "trailer-injection guard leaked — commit body contains injected "
        f"Subject: pwned; body={body!r}"
    )
    # Ledger breadcrumb confirms the refusal path was taken.
    lines = [json.loads(l) for l in tmp_ledger.read_text().splitlines() if l]
    assert any(
        "trailer-injection guard" in r["detail"]
        or "newline/carriage-return" in r["detail"]
        for r in lines
    ), f"expected trailer-injection refusal breadcrumb; got {lines!r}"


# ===========================================================================
# Vector 12: concurrent _ledger_append_observation
# ===========================================================================

def test_12_concurrent_ledger_append_no_torn_lines(
    tmp_path, drain_mod, monkeypatch
):
    """20 threads × 50 calls each = 1000 lines. Each line must parse as
    valid JSON with the expected shape.

    POSIX append-mode writes are atomic for payloads <= PIPE_BUF (4096
    bytes on Linux). Our rows are ~250 bytes, well under the limit.
    """
    tmp_led = tmp_path / "ledger.jsonl"
    monkeypatch.setattr(drain_mod, "_IMPL_PROGRESS_LEDGER", tmp_led)
    N_THREADS = 20
    N_PER_THREAD = 50

    def worker(idx: int):
        for k in range(N_PER_THREAD):
            drain_mod._ledger_append_observation(
                detail=f"concurrent row t{idx} k{k}",
                files=[f"file_{idx}_{k}.txt"],
            )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    content = tmp_led.read_text().splitlines()
    assert len(content) == N_THREADS * N_PER_THREAD, (
        f"expected {N_THREADS * N_PER_THREAD} rows, got {len(content)} — "
        "torn writes"
    )
    for i, line in enumerate(content):
        row = json.loads(line)  # raises if torn
        assert row["event"] == "observation"
        assert row["phase"] == "META"


# ===========================================================================
# Vector 13: moderately large baseline
# ===========================================================================

def test_13_large_baseline_commits_under_5s(tmp_repo, drain_mod, tmp_ledger):
    """5 MB baseline — well under git.bigFileThreshold (512M) but large
    enough to exercise subprocess buffering. Must complete well under
    the 5s per-test budget.
    """
    import time as _time
    baseline = tmp_repo / "state" / "hooks" / "drain_baseline_stab_001.json"
    baseline.write_bytes(b"{" + b"x" * (5 * 1024 * 1024 - 2) + b"}")
    t0 = _time.monotonic()
    rc = drain_mod._auto_commit_drain_baseline(
        baseline_path=baseline,
        brief_id="stab_001",
        session="sess",
        state_dir=tmp_repo / "state",
        repo_root=tmp_repo,
    )
    elapsed = _time.monotonic() - t0
    assert rc is True
    assert elapsed < 5.0, f"large-baseline commit took {elapsed:.2f}s"


# ===========================================================================
# Vector 15: _IMPL_PROGRESS_LEDGER leakage (F1 self-reported defect)
# ===========================================================================

def test_15a_ledger_is_hardcoded_constant(drain_mod):
    """F1-MED FIXED (2026-04-21 closeout defect #4): the helpers now
    expose a ``ledger_path`` keyword on both
    ``_ledger_append_observation`` and ``_auto_commit_drain_baseline``,
    with module-default fallback. Tests can redirect writes without
    monkeypatching the module constant.
    """
    import inspect
    sig = inspect.signature(drain_mod._ledger_append_observation)
    param_names = set(sig.parameters)
    assert "ledger_path" in param_names, (
        "helper must expose ledger_path kwarg per F1 followup; got "
        f"params={param_names!r}"
    )
    sig2 = inspect.signature(drain_mod._auto_commit_drain_baseline)
    assert "ledger_path" in sig2.parameters, (
        "auto-commit helper must expose ledger_path kwarg per F1 "
        f"followup; got params={set(sig2.parameters)!r}"
    )
    # Both must be keyword-only (kind == KEYWORD_ONLY).
    assert (
        sig.parameters["ledger_path"].kind
        is inspect.Parameter.KEYWORD_ONLY
    ), "ledger_path on _ledger_append_observation must be keyword-only"
    assert (
        sig2.parameters["ledger_path"].kind
        is inspect.Parameter.KEYWORD_ONLY
    ), "ledger_path on _auto_commit_drain_baseline must be keyword-only"


def test_15b_monkeypatch_keeps_real_ledger_pristine(
    tmp_repo, drain_mod, tmp_ledger
):
    """Exercise the helper via the tmp_ledger fixture (which monkey-
    patches the constant) and confirm the real project ledger size is
    unchanged. The tmp_ledger fixture itself asserts this in teardown
    — this test makes the assertion explicit in the test body too.
    """
    real_ledger = REPO_ROOT / "state" / "impl_progress.jsonl"
    before = real_ledger.stat().st_size if real_ledger.exists() else 0

    # Call a failing path so a ledger row IS emitted.
    drain_mod._auto_commit_drain_baseline(
        baseline_path=tmp_repo / "state" / "hooks" / "missing.json",
        brief_id="stab_001",
        session="sess",
        state_dir=tmp_repo / "state",
        repo_root=tmp_repo,
    )
    after = real_ledger.stat().st_size if real_ledger.exists() else 0
    assert after == before, "monkeypatch failed — real ledger was touched"
    assert tmp_ledger.exists() and tmp_ledger.stat().st_size > 0


# ===========================================================================
# Vector 18: detached HEAD
# ===========================================================================

def test_18_detached_head_commits_on_anonymous_chain(
    tmp_repo, drain_mod, tmp_ledger
):
    """F1-MED FIXED (2026-04-21 closeout defect #5): the helper now
    refuses to commit on detached HEAD via ``git symbolic-ref -q HEAD``
    pre-check. An anonymous-chain commit would defeat the race-guard
    (unreachable by branch name, eligible for GC). The helper returns
    False and leaves a ledger breadcrumb. HEAD does not move.
    """
    head_sha = _git(tmp_repo, "rev-parse", "HEAD").stdout.strip()
    _git(tmp_repo, "checkout", "-q", "--detach", head_sha)
    baseline = _make_baseline(tmp_repo)
    before_head = _git(tmp_repo, "rev-parse", "HEAD").stdout.strip()
    rc = drain_mod._auto_commit_drain_baseline(
        baseline_path=baseline,
        brief_id="stab_001",
        session="sess",
        state_dir=tmp_repo / "state",
        repo_root=tmp_repo,
    )
    assert rc is False, "helper must refuse commit on detached HEAD"
    after_head = _git(tmp_repo, "rev-parse", "HEAD").stdout.strip()
    assert before_head == after_head, (
        "no commit must land on detached HEAD refusal"
    )
    # Ledger breadcrumb confirms the refusal path was taken.
    lines = [json.loads(l) for l in tmp_ledger.read_text().splitlines() if l]
    assert any(
        "detached HEAD" in r["detail"] for r in lines
    ), f"expected detached-HEAD refusal breadcrumb; got {lines!r}"


# ===========================================================================
# Vector 19: same brief_id twice — second call no-ops
# ===========================================================================

def test_19_brief_id_collision_second_call_is_noop(
    tmp_repo, drain_mod, tmp_ledger
):
    baseline = _make_baseline(tmp_repo)
    rc1 = drain_mod._auto_commit_drain_baseline(
        baseline_path=baseline,
        brief_id="stab_001",
        session="sess-1",
        state_dir=tmp_repo / "state",
        repo_root=tmp_repo,
    )
    assert rc1 is True
    head1 = _git(tmp_repo, "rev-parse", "HEAD").stdout.strip()
    rc2 = drain_mod._auto_commit_drain_baseline(
        baseline_path=baseline,
        brief_id="stab_001",
        session="sess-2",
        state_dir=tmp_repo / "state",
        repo_root=tmp_repo,
    )
    assert rc2 is False, "identical baseline — second call must no-op"
    head2 = _git(tmp_repo, "rev-parse", "HEAD").stdout.strip()
    assert head1 == head2


# ===========================================================================
# Vector 20: ledger append when target path is non-writable
# ===========================================================================

def test_20_ledger_append_swallows_oserror(tmp_path, drain_mod, monkeypatch):
    """Point the ledger constant at an un-creatable path (parent is a
    file, not a dir). ``_ledger_append_observation`` must swallow the
    OSError silently — the helper's contract is "never raises".
    """
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    # ledger_path inherits from a file-as-parent → mkdir will fail.
    ledger_path = blocker / "ledger.jsonl"
    monkeypatch.setattr(drain_mod, "_IMPL_PROGRESS_LEDGER", ledger_path)
    # Must not raise.
    drain_mod._ledger_append_observation(
        detail="test row that cannot be written",
        files=["x"],
    )
    assert not ledger_path.exists()


# ===========================================================================
# Vector 21 (invented): helper returns True only when a new commit landed
# ===========================================================================

def test_21_return_value_reflects_commit_landed(
    tmp_repo, drain_mod, tmp_ledger
):
    """Property-style: ``rc is True`` implies HEAD advanced by exactly
    one commit; ``rc is False`` implies HEAD did not move.
    """
    baseline = _make_baseline(tmp_repo)
    before = _git(tmp_repo, "rev-parse", "HEAD").stdout.strip()
    rc = drain_mod._auto_commit_drain_baseline(
        baseline_path=baseline,
        brief_id="stab_001",
        session="sess",
        state_dir=tmp_repo / "state",
        repo_root=tmp_repo,
    )
    after = _git(tmp_repo, "rev-parse", "HEAD").stdout.strip()
    if rc:
        # exactly one commit between before and after
        count = int(
            _git(
                tmp_repo, "rev-list", "--count", f"{before}..{after}"
            ).stdout.strip()
        )
        assert count == 1, f"rc=True but {count} commits between before/after"
    else:
        assert before == after


# ===========================================================================
# Vector 22 (invented): evidence glob is NOT brief_id-parameterised
# ===========================================================================

def test_22_evidence_glob_uses_literal_prefix(
    tmp_repo, drain_mod, tmp_ledger
):
    """Read the module source and confirm the evidence globs are
    hardcoded literals (``claude_round*_*_submission.json`` etc.).
    Protects against a future refactor that interpolates ``brief_id``
    into the glob and reintroduces the injection vector.
    """
    src = DRAIN_SRC.read_text(encoding="utf-8")
    # Find the evidence_globs tuple.
    # The 4 patterns we care about:
    expected = [
        '"claude_round*_*_submission.json"',
        '"gemini_round*_*_submission.json"',
        '"claude_*.ledger.jsonl"',
        '"gemini_*.ledger.jsonl"',
    ]
    for pat in expected:
        assert pat in src, (
            f"evidence glob {pat!r} no longer a literal — if brief_id "
            "was interpolated, re-audit vector 8 attack surface"
        )


# ===========================================================================
# Vector 23 (invented): broken symlink as baseline_path
# ===========================================================================

def test_23_broken_symlink_baseline_does_not_raise(
    tmp_repo, drain_mod, tmp_ledger
):
    """Baseline path is a dangling symlink. ``.exists()`` on a dangling
    symlink returns False, so the helper should take the "missing"
    branch and return False cleanly.
    """
    link = tmp_repo / "state" / "hooks" / "drain_baseline_stab_001.json"
    link.symlink_to(tmp_repo / "nonexistent_target.json")
    assert link.is_symlink() and not link.exists()

    rc = drain_mod._auto_commit_drain_baseline(
        baseline_path=link,
        brief_id="stab_001",
        session="sess",
        state_dir=tmp_repo / "state",
        repo_root=tmp_repo,
    )
    assert rc is False
    lines = [json.loads(l) for l in tmp_ledger.read_text().splitlines() if l]
    assert any("not present on disk" in r["detail"] for r in lines)


# ===========================================================================
# Vector 1: parallel drains on DIFFERENT briefs serialise cleanly
# ===========================================================================

def test_01_parallel_calls_serialise_via_index_lock(
    tmp_repo, drain_mod, tmp_ledger
):
    """Two threads calling the helper concurrently with DIFFERENT
    briefs. Git's index.lock serialises the writers, so BOTH commits
    should land (or at least one of them with the other cleanly
    returning False; no raise either way).
    """
    (tmp_repo / "state" / "hooks").mkdir(parents=True, exist_ok=True)
    b1 = tmp_repo / "state" / "hooks" / "drain_baseline_stab_001.json"
    b1.write_text(json.dumps({"id": 1}), encoding="utf-8")
    b3 = tmp_repo / "state" / "hooks" / "drain_baseline_stab_003.json"
    b3.write_text(json.dumps({"id": 3}), encoding="utf-8")

    results = {}
    errors = {}

    def drive(name: str, path: Path, brief: str):
        try:
            results[name] = drain_mod._auto_commit_drain_baseline(
                baseline_path=path,
                brief_id=brief,
                session=f"sess-{brief}",
                state_dir=tmp_repo / "state",
                repo_root=tmp_repo,
            )
        except BaseException as e:  # pragma: no cover
            errors[name] = repr(e)

    t1 = threading.Thread(target=drive, args=("a", b1, "stab_001"))
    t2 = threading.Thread(target=drive, args=("b", b3, "stab_003"))
    t1.start(); t2.start()
    t1.join(timeout=30); t2.join(timeout=30)

    assert not errors, f"helper raised under concurrency: {errors}"
    # At minimum, at least one of the two must have landed a commit.
    assert any(results.values()), (
        f"both concurrent calls returned False: {results}"
    )


# ===========================================================================
# Vector 2: stale .git/index.lock — helper behaviour
# ===========================================================================

def test_02_stale_index_lock_does_not_crash(
    tmp_repo, drain_mod, tmp_ledger
):
    """Pre-create ``.git/index.lock`` (as though a prior git crashed mid-
    operation). Observe whether the helper retries, waits, or returns
    False. Requirement: it must not raise.
    """
    lock = tmp_repo / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    baseline = _make_baseline(tmp_repo)
    before = _git(tmp_repo, "rev-parse", "HEAD").stdout.strip()

    rc = drain_mod._auto_commit_drain_baseline(
        baseline_path=baseline,
        brief_id="stab_001",
        session="sess",
        state_dir=tmp_repo / "state",
        repo_root=tmp_repo,
    )
    # Git should refuse to add while index.lock exists — returncode != 0,
    # helper returns False, no crash, no commit.
    assert rc is False
    after = _git(tmp_repo, "rev-parse", "HEAD").stdout.strip()
    assert before == after
    # Helper left a ledger breadcrumb.
    lines = [json.loads(l) for l in tmp_ledger.read_text().splitlines() if l]
    assert any(
        "git add" in r["detail"] or "git commit" in r["detail"]
        for r in lines
    )
    # Clean up so tmp_path teardown does not re-fire the stale lock
    # against a subsequent test (defensive; fixtures are per-test).
    lock.unlink()


# ===========================================================================
# Vector 14: read-only filesystem — SKIPPED (needs mount)
# ===========================================================================

@pytest.mark.skip(reason=(
    "Requires a read-only mount (e.g. `mount -o remount,ro tmp_path` or a "
    "tmpfs/ro fuse-wrapped dir). Setup needs CAP_SYS_ADMIN; skip in CI."
))
def test_14_readonly_fs_returns_false():
    pass


# ===========================================================================
# Vector 16: disk-full mid-commit — SKIPPED (needs quota)
# ===========================================================================

@pytest.mark.skip(reason=(
    "Requires ENOSPC simulation via a tight filesystem quota or an "
    "ulimit -f bound. Setup needs root + a scratch FS; skip in CI."
))
def test_16_disk_full_mid_commit():
    pass


# ===========================================================================
# Vector 17: SIGTERM mid-commit — SKIPPED (needs process-group harness)
# ===========================================================================

@pytest.mark.skip(reason=(
    "Requires spawning the helper in a subprocess, racing SIGTERM against "
    "the git-commit child, and checking .git/index.lock is cleaned up. "
    "Needs a timing-sensitive harness; skip from the basic unit pass."
))
def test_17_sigterm_mid_commit():
    pass


# ===========================================================================
# Vector 24 (B2-O3 regression): gitignored state/ must not break `git add`
# ===========================================================================

@pytest.fixture
def tmp_repo_gitignore_state(tmp_path: Path) -> Path:
    """Seed a fresh git repo whose seed commit gitignores ``state/``.

    Mirrors the real repo layout where ``.gitignore:15`` excludes
    ``state/``. Kept SEPARATE from ``tmp_repo`` because the shared
    fixture is consumed by 20+ other tests that assume no gitignore.
    """
    repo = tmp_path / "repo_ign"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "JanusMask Test")
    _git(repo, "config", "user.email", "test@janusmask.local")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    (repo / ".gitignore").write_text("state/\n", encoding="utf-8")
    _git(repo, "add", "seed.txt", ".gitignore")
    _git(repo, "commit", "-q", "-m", "seed with gitignored state/")
    (repo / "state" / "hooks").mkdir(parents=True)
    (repo / "state" / "sessions").mkdir(parents=True)
    return repo


def test_24_gitignored_state_does_not_block_auto_commit(
    tmp_repo_gitignore_state, drain_mod, tmp_ledger
):
    """B2-O3 regression: baseline lives under the gitignored ``state/``
    tree. Without the ``-f`` flag ``git add`` returns rc=1 on an ignored
    path and the helper treats that as failure, leaving the baseline
    uncommitted and vulnerable to the pre-flight checkout race. With
    ``-f`` the add succeeds and the baseline is committed.
    """
    repo = tmp_repo_gitignore_state
    baseline = repo / "state" / "hooks" / "drain_baseline_stab_001.json"
    baseline.write_text(
        json.dumps({"brief_id": "stab_001", "patch_stat": "x"}) + "\n",
        encoding="utf-8",
    )
    before_head = _git(repo, "rev-parse", "HEAD").stdout.strip()

    rc = drain_mod._auto_commit_drain_baseline(
        baseline_path=baseline,
        brief_id="stab_001",
        session="sess",
        state_dir=repo / "state",
        repo_root=repo,
    )
    assert rc is True, (
        "helper must report success on gitignored state/ when -f is "
        "used; rc=False indicates the B2-O3 regression has returned"
    )
    after_head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert before_head != after_head, "a new commit must land"
    # Confirm the baseline (under gitignored state/) is actually in the
    # new HEAD commit.
    files = _git(
        repo, "log", "-1", "--name-only", "--format="
    ).stdout.split()
    assert "state/hooks/drain_baseline_stab_001.json" in files, (
        f"baseline not present in HEAD commit files={files!r}"
    )
    # No rc=1-induced failure breadcrumb should be in the ledger.
    # (The success path emits NO ledger row — so an absent/empty ledger
    # file is itself the positive signal.)
    if tmp_ledger.exists():
        lines = [
            json.loads(l) for l in tmp_ledger.read_text().splitlines() if l
        ]
        assert not any(
            "`git add` rc=" in r["detail"] for r in lines
        ), (
            "unexpected git-add rc!=0 breadcrumb — -f flag should "
            f"suppress the rc=1 from gitignored state/; ledger={lines!r}"
        )
