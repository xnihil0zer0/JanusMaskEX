"""Adversarial tests for scripts/impl_audit_scope_exceptions.py.

Builds tiny synthetic ledgers + a real mini git repo per tmp_path and
invokes the audit script as a subprocess. Covers Agent-DD's GC policy
edge cases: STALE recognition, LIVE retention, INDETERMINATE-on-glob,
the 150-row window cutoff, and the --strict exit-code contract.

Mini-repo approach (vs mocking subprocess) is preferred because the
audit script makes several distinct git invocations - re-mocking each
would be brittle. Real git is fast enough (<2s for the whole battery).
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "impl_audit_scope_exceptions.py"


def _iso(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _se(task_id: str, paths: list, when: datetime.datetime,
        consume_on: str = "test_pass") -> dict:
    row = {
        "ts": _iso(when),
        "phase": "META",
        "task_id": task_id,
        "event": "scope_exception",
        "detail": "synthetic",
        "files": [],
        "paths": list(paths),
        "exit": 0,
    }
    if consume_on:
        row["consume_on"] = consume_on
    return row


def _tp(task_id: str, when: datetime.datetime) -> dict:
    return {
        "ts": _iso(when),
        "phase": "META",
        "task_id": task_id,
        "event": "test_pass",
        "detail": "synthetic",
        "files": [],
        "exit": 0,
    }


def _filler(when: datetime.datetime, n: int) -> list:
    return [
        {
            "ts": _iso(when + datetime.timedelta(seconds=i)),
            "phase": "META",
            "task_id": f"FILL-{i}",
            "event": "observation",
            "detail": "noise",
            "files": [],
            "exit": 0,
        }
        for i in range(n)
    ]


@pytest.fixture
def mini_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True, env=env)
    (tmp_path / "README.md").write_text("init\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True, env=env)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"],
                   check=True, env=env)
    (tmp_path / "state").mkdir()
    return tmp_path


def _commit_file(repo: pathlib.Path, rel: str, content: str, when: datetime.datetime,
                 *, delete: bool = False) -> None:
    target = repo / rel
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_AUTHOR_DATE": _iso(when),
        "GIT_COMMITTER_DATE": _iso(when),
    }
    if delete:
        subprocess.run(["git", "-C", str(repo), "rm", "-q", rel], check=True, env=env)
        msg = f"rm {rel}"
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        subprocess.run(["git", "-C", str(repo), "add", rel], check=True, env=env)
        msg = f"touch {rel}"
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", msg],
                   check=True, env=env)


def _write_ledger(repo: pathlib.Path, rows: list) -> pathlib.Path:
    ledger = repo / "state" / "impl_progress.jsonl"
    ledger.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return ledger


def _run_audit(repo: pathlib.Path, ledger: pathlib.Path,
               *, strict: bool = False) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT), "--ledger", str(ledger), "--repo", str(repo)]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def test_stale_classification_for_consumed_path(mini_repo):
    """SE + matching test_pass + commit-after touching path -> STALE."""
    t0 = datetime.datetime(2026, 4, 23, 10, 0, 0, tzinfo=datetime.timezone.utc)
    se_row = _se("X1", ["foo/bar.py"], t0)
    tp_row = _tp("X1", t0 + datetime.timedelta(minutes=5))
    ledger = _write_ledger(mini_repo, [se_row, tp_row])
    _commit_file(mini_repo, "foo/bar.py", "x = 1\n",
                 t0 + datetime.timedelta(minutes=10))
    proc = _run_audit(mini_repo, ledger)
    assert proc.returncode == 0, proc.stderr
    assert "STALE" in proc.stdout
    assert "foo/bar.py" in proc.stdout


def test_live_when_no_matching_test_pass(mini_repo):
    """SE without a same-task test_pass -> LIVE, never STALE."""
    t0 = datetime.datetime(2026, 4, 23, 10, 0, 0, tzinfo=datetime.timezone.utc)
    ledger = _write_ledger(mini_repo, [_se("PENDING", ["pkg/mod.py"], t0)])
    proc = _run_audit(mini_repo, ledger)
    assert proc.returncode == 0
    assert "LIVE" in proc.stdout
    assert "0 STALE" in proc.stdout


def test_indeterminate_on_glob(mini_repo):
    """Glob path -> INDETERMINATE even if test_pass + commits exist."""
    t0 = datetime.datetime(2026, 4, 23, 10, 0, 0, tzinfo=datetime.timezone.utc)
    rows = [_se("G1", ["tests/adversarial/test_P5_*.py"], t0),
            _tp("G1", t0 + datetime.timedelta(minutes=1))]
    ledger = _write_ledger(mini_repo, rows)
    _commit_file(mini_repo, "tests/adversarial/test_P5_alpha.py", "x=1\n",
                 t0 + datetime.timedelta(minutes=2))
    proc = _run_audit(mini_repo, ledger)
    assert proc.returncode == 0
    assert "INDETERMINATE" in proc.stdout
    assert "0 STALE" in proc.stdout


def test_window_cutoff_excludes_old_se(mini_repo):
    """SE older than the trailing 150-row window MUST not appear."""
    t0 = datetime.datetime(2026, 4, 23, 9, 0, 0, tzinfo=datetime.timezone.utc)
    old_se = _se("ANCIENT", ["long/gone.py"], t0)
    rows = [old_se, *_filler(t0 + datetime.timedelta(seconds=1), 200)]
    ledger = _write_ledger(mini_repo, rows)
    proc = _run_audit(mini_repo, ledger)
    assert proc.returncode == 0
    assert "long/gone.py" not in proc.stdout
    assert "no scope_exception paths" in proc.stdout


@pytest.mark.parametrize("strict,expected_rc", [(False, 0), (True, 1)])
def test_strict_flag_exit_code(mini_repo, strict, expected_rc):
    """`--strict` flips exit to 1 when any STALE row is present; default 0."""
    t0 = datetime.datetime(2026, 4, 23, 10, 0, 0, tzinfo=datetime.timezone.utc)
    rows = [_se("S1", ["a/b.py"], t0),
            _tp("S1", t0 + datetime.timedelta(minutes=1))]
    ledger = _write_ledger(mini_repo, rows)
    _commit_file(mini_repo, "a/b.py", "x=1\n", t0 + datetime.timedelta(minutes=2))
    proc = _run_audit(mini_repo, ledger, strict=strict)
    assert proc.returncode == expected_rc, proc.stdout + proc.stderr
    assert "STALE" in proc.stdout


def test_strict_with_no_stale_returns_zero(mini_repo):
    """`--strict` + zero STALE -> still exit 0."""
    t0 = datetime.datetime(2026, 4, 23, 10, 0, 0, tzinfo=datetime.timezone.utc)
    ledger = _write_ledger(mini_repo, [_se("OPEN", ["pkg/x.py"], t0)])
    proc = _run_audit(mini_repo, ledger, strict=True)
    assert proc.returncode == 0
    assert "LIVE" in proc.stdout


def test_missing_ledger_returns_two(mini_repo):
    """Unreadable/missing ledger -> exit 2 with stderr message."""
    bogus = mini_repo / "state" / "does-not-exist.jsonl"
    proc = _run_audit(mini_repo, bogus)
    assert proc.returncode == 2
    assert "ledger not found" in proc.stderr
    assert "STALE" not in proc.stdout


def test_audit_never_writes_ledger(mini_repo):
    """Hard invariant: audit must never mutate the ledger byte-for-byte."""
    t0 = datetime.datetime(2026, 4, 23, 10, 0, 0, tzinfo=datetime.timezone.utc)
    rows = [_se("M1", ["foo/bar.py"], t0),
            _tp("M1", t0 + datetime.timedelta(minutes=1))]
    ledger = _write_ledger(mini_repo, rows)
    _commit_file(mini_repo, "foo/bar.py", "x=1\n", t0 + datetime.timedelta(minutes=2))
    before = ledger.read_bytes()
    _ = _run_audit(mini_repo, ledger, strict=True)
    after = ledger.read_bytes()
    assert before == after


def _run_audit_emit(repo: pathlib.Path, ledger: pathlib.Path) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT), "--ledger", str(ledger),
           "--repo", str(repo), "--emit-revoke-rows"]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def test_emit_revoke_rows_emits_one_row_per_stale(mini_repo):
    """--emit-revoke-rows emits a scope_revoke jsonl row per STALE path."""
    t0 = datetime.datetime(2026, 4, 23, 10, 0, 0, tzinfo=datetime.timezone.utc)
    se_row = _se("E1", ["foo/bar.py", "foo/baz.py"], t0)
    tp_row = _tp("E1", t0 + datetime.timedelta(minutes=5))
    ledger = _write_ledger(mini_repo, [se_row, tp_row])
    _commit_file(mini_repo, "foo/bar.py", "x=1\n", t0 + datetime.timedelta(minutes=10))
    _commit_file(mini_repo, "foo/baz.py", "y=1\n", t0 + datetime.timedelta(minutes=11))

    proc = _run_audit_emit(mini_repo, ledger)
    assert proc.returncode == 0, proc.stderr
    lines = [l for l in proc.stdout.splitlines() if l.strip()]
    assert len(lines) == 2, proc.stdout

    rows = [json.loads(l) for l in lines]
    assert {r["paths"][0] for r in rows} == {"foo/bar.py", "foo/baz.py"}
    for r in rows:
        assert r["event"] == "scope_revoke"
        assert r["task_id"] == "E1"
        assert r["approved_by"] == "operator_review_required"
        assert r["phase"] == "META"
        assert len(r["paths"]) == 1
        assert "satisfied_by=" in r["detail"]


def test_emit_revoke_rows_skips_live_and_indeterminate(mini_repo):
    """--emit-revoke-rows only touches STALE paths; LIVE/INDETERMINATE skipped."""
    t0 = datetime.datetime(2026, 4, 23, 10, 0, 0, tzinfo=datetime.timezone.utc)
    rows = [
        _se("L1", ["live/path.py"], t0),  # LIVE: no test_pass
        _se("G1", ["tests/*.py"], t0),    # INDETERMINATE: glob
        _tp("G1", t0 + datetime.timedelta(minutes=1)),
    ]
    ledger = _write_ledger(mini_repo, rows)

    proc = _run_audit_emit(mini_repo, ledger)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "", proc.stdout


def test_emit_revoke_rows_does_not_mutate_ledger(mini_repo):
    """Hard invariant: --emit-revoke-rows must never mutate the ledger."""
    t0 = datetime.datetime(2026, 4, 23, 10, 0, 0, tzinfo=datetime.timezone.utc)
    rows = [_se("M2", ["foo/bar.py"], t0),
            _tp("M2", t0 + datetime.timedelta(minutes=1))]
    ledger = _write_ledger(mini_repo, rows)
    _commit_file(mini_repo, "foo/bar.py", "x=1\n", t0 + datetime.timedelta(minutes=2))

    before = ledger.read_bytes()
    _ = _run_audit_emit(mini_repo, ledger)
    after = ledger.read_bytes()
    assert before == after


def test_malformed_se_row_skipped_not_crashed(mini_repo):
    """SE row with paths=None must be silently skipped - mirrors gate."""
    t0 = datetime.datetime(2026, 4, 23, 10, 0, 0, tzinfo=datetime.timezone.utc)
    bad = _se("BAD", [], t0)
    bad["paths"] = None
    good = _se("GOOD", ["pkg/y.py"], t0 + datetime.timedelta(seconds=1))
    ledger = _write_ledger(mini_repo, [bad, good])
    proc = _run_audit(mini_repo, ledger)
    assert proc.returncode == 0
    assert "pkg/y.py" in proc.stdout
    assert "Traceback" not in proc.stderr
