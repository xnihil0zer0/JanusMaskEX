#!/usr/bin/env python3
"""Audit stale scope_exception (SE) rows in state/impl_progress.jsonl.

READ-ONLY. Never appends, rewrites, or deletes ledger rows. Implements the
Agent-DD GC policy as a *report*, not an actuator. See
``brief_hooks_schema_drift_fix_plan.md`` for the surrounding remediation.
*** Do not auto-clean — see Agent-DD risk register below. ***

GC policy (an SE path is STALE iff *all three* hold)
----------------------------------------------------
1. The SE row carries ``consume_on: "test_pass"`` AND a later ``test_pass``
   row with the same ``task_id`` exists at ts >= SE row's ts.
2. A git commit exists whose committer-ts >= that test_pass ts AND whose
   diff touches the SE path.
3. The path either (a) exists on disk with
   ``git log -1 --format=%ct -- <path>`` older than the test_pass ts, OR
   (b) has been deleted via a tracked commit after the test_pass.

If any condition fails the path is LIVE. Globs and SE rows missing a
matching test_pass classify as INDETERMINATE — never STALE.

Five Agent-DD risks (all reflected in classification logic)
-----------------------------------------------------------
R1. Load-bearing gate: ``scripts/impl_common.py`` (``scope_exception_paths``)
    reads only the **last 150 rows**. Older SE rows have already aged out
    via passive expiry. This audit honours the same window — SE rows older
    than the 150-row tail are out of scope and not reported (they are no
    longer authorising anything).
R2. Glob false-positives: SE rows can carry path globs
    (e.g., ``tests/adversarial/test_P5_*.py``). A glob's authorisation
    intent cannot be proven exhausted by a single commit. Globs always
    classify as INDETERMINATE.
R3. Append-only invariant: this script never mutates the ledger. Even
    ``--strict`` only changes the exit code; it never rewrites rows.
R4. Passive expiry already works: rows older than 150 effectively no
    longer authorise writes. The intent of this audit is operator
    hygiene (visibility), not GC correctness.
R5. ``scope_revoke`` IS honoured by the write-gate in
    ``scripts/impl_pre_write.py`` (via ``_effective_scope_exception_paths``),
    but this audit deliberately does NOT consult it. Staleness here is a
    git-history claim ("a commit satisfied this SE"), not a ledger-state
    claim ("the operator revoked this SE"). The two views are
    complementary: this audit surfaces stale rows the operator *could*
    revoke; ``--emit-revoke-rows`` (below) generates the jsonl payload
    to make that revocation cheap.

Usage
-----
    python3 scripts/impl_audit_scope_exceptions.py
    python3 scripts/impl_audit_scope_exceptions.py --strict   # CI mode
    python3 scripts/impl_audit_scope_exceptions.py --ledger /path/to.jsonl
    python3 scripts/impl_audit_scope_exceptions.py --emit-revoke-rows  # jsonl draft

Exit codes
----------
    0 — audit completed (default; STALE rows reported but not enforced).
    1 — only with ``--strict`` and at least one STALE row found.
    2 — ledger could not be read (printed to stderr).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import subprocess
import sys
from typing import Iterable, Optional, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from impl_common import _ts_to_epoch  # consolidated; see scripts/impl_common.py:639

WINDOW = 150  # MUST mirror scripts/impl_common.py::scope_exception_paths.


def _project_dir() -> pathlib.Path:
    raw = os.environ.get("JANUSMASK_PROJECT_DIR") or os.environ.get("CLAUDE_PROJECT_DIR")
    if raw:
        return pathlib.Path(raw).resolve()
    return pathlib.Path(__file__).resolve().parent.parent


PROJECT_DIR = _project_dir()
LEDGER_PATH = PROJECT_DIR / "state" / "impl_progress.jsonl"

_GLOB_CHARS = set("*?[")


def _load_ledger(path: pathlib.Path) -> list:
    if not path.exists():
        raise FileNotFoundError(f"ledger not found: {path}")
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            rows.append(json.loads(s))
        except json.JSONDecodeError:
            continue
    return rows


def _is_glob(path: str) -> bool:
    return any(c in _GLOB_CHARS for c in path)


def _git(args: list, cwd: pathlib.Path) -> Optional[str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def _commits_touching_path_since(
    path: str, since_epoch: float, repo: pathlib.Path
) -> list:
    raw = _git(
        ["log", f"--since=@{int(since_epoch)}", "--pretty=format:%H %ct",
         "--diff-filter=ACDMRT", "--", path],
        cwd=repo,
    )
    if raw is None:
        return []
    out = []
    for line in raw.splitlines():
        parts = line.strip().split(" ", 1)
        if len(parts) != 2:
            continue
        sha, ts_s = parts
        try:
            out.append((sha, float(ts_s)))
        except ValueError:
            continue
    return [c for c in out if c[1] >= since_epoch]


def _path_last_commit_epoch(path: str, repo: pathlib.Path) -> Optional[float]:
    raw = _git(["log", "-1", "--format=%ct", "--", path], cwd=repo)
    if not raw:
        return None
    s = raw.strip().splitlines()[0] if raw.strip() else ""
    try:
        return float(s)
    except ValueError:
        return None


def _path_deleted_after(path: str, since_epoch: float, repo: pathlib.Path) -> bool:
    raw = _git(
        ["log", f"--since=@{int(since_epoch)}", "--diff-filter=D",
         "--pretty=format:%H", "--", path],
        cwd=repo,
    )
    return bool(raw and raw.strip())


def _matching_test_pass(
    rows: list, task_id: str, after_epoch: float
) -> Optional[dict]:
    best = None
    best_ts: Optional[float] = None
    for r in rows:
        if r.get("event") != "test_pass":
            continue
        if r.get("task_id") != task_id:
            continue
        ts = _ts_to_epoch(r.get("ts", ""))
        if ts is None or ts < after_epoch:
            continue
        if best_ts is None or ts < best_ts:
            best_ts = ts
            best = r
    return best


def classify_path(
    path: str,
    se_row: dict,
    se_epoch: float,
    rows: list,
    repo: pathlib.Path,
) -> Tuple[str, str, str]:
    """Return (classification, satisfied_by, reason).

    classification in {"STALE", "LIVE", "INDETERMINATE"}.
    satisfied_by = "<sha>@<ts>" or "" when not applicable.
    """
    if _is_glob(path):
        return ("INDETERMINATE", "",
                "glob pattern; intent cannot be proved exhausted by a single commit")

    if se_row.get("consume_on") != "test_pass":
        return ("INDETERMINATE", "",
                "SE row has no consume_on=test_pass trigger")

    task_id = se_row.get("task_id") or ""
    if not task_id:
        return ("INDETERMINATE", "",
                "SE row has empty task_id; cannot bind to a test_pass")

    tp_row = _matching_test_pass(rows, task_id, se_epoch)
    if tp_row is None:
        return ("LIVE", "",
                f"no test_pass for task_id={task_id} at ts >= SE")
    tp_epoch = _ts_to_epoch(tp_row.get("ts", "")) or se_epoch

    commits = _commits_touching_path_since(path, tp_epoch, repo)
    if commits:
        sha, c_ts = commits[0]
        sat = f"{sha[:8]}@{int(c_ts)}"
        return ("STALE", sat,
                f"commit touched {path} at {int(c_ts)} >= test_pass {tp_row.get('ts')}")
    if _path_deleted_after(path, tp_epoch, repo):
        return ("STALE", "",
                f"path deleted in tracked commit after test_pass {tp_row.get('ts')}")
    return ("LIVE", "",
            f"no commit touching {path} after test_pass {tp_row.get('ts')}")


def _se_rows_in_window(rows: list) -> list:
    return [r for r in rows[-WINDOW:] if r.get("event") == "scope_exception"]


def _iter_se_paths(se_rows: Iterable) -> Iterable:
    for row in se_rows:
        paths = row.get("paths")
        if not isinstance(paths, list):
            continue
        for p in paths:
            if isinstance(p, str) and p:
                yield p, row


def _format_table(rows: list) -> str:
    if not rows:
        return "(no scope_exception paths in the last %d ledger rows)\n" % WINDOW
    cols = ["path", "task_id", "ts_added", "satisfied_by", "classification", "reason"]
    widths = {c: len(c) for c in cols}
    for r in rows:
        for c in cols:
            widths[c] = max(widths[c], len(r.get(c, "")))
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    rule = "  ".join("-" * widths[c] for c in cols)
    body = "\n".join(
        "  ".join(r.get(c, "").ljust(widths[c]) for c in cols) for r in rows
    )
    return header + "\n" + rule + "\n" + body + "\n"


def audit(ledger_path: pathlib.Path, repo: pathlib.Path) -> Tuple[list, int]:
    rows = _load_ledger(ledger_path)
    se_rows = _se_rows_in_window(rows)
    out = []
    stale = 0
    for path, se_row in _iter_se_paths(se_rows):
        epoch = _ts_to_epoch(se_row.get("ts", ""))
        if epoch is None:
            out.append({
                "path": path,
                "task_id": se_row.get("task_id", ""),
                "ts_added": se_row.get("ts", ""),
                "satisfied_by": "",
                "classification": "INDETERMINATE",
                "reason": "unparseable SE ts",
            })
            continue
        cls, sat, reason = classify_path(path, se_row, epoch, rows, repo)
        if cls == "STALE":
            stale += 1
        out.append({
            "path": path,
            "task_id": se_row.get("task_id", ""),
            "ts_added": se_row.get("ts", ""),
            "satisfied_by": sat,
            "classification": cls,
            "reason": reason,
        })
    return out, stale


def _emit_revoke_rows(table: list) -> None:
    """Print one draft ``scope_revoke`` jsonl row per STALE path.

    Read-only: this function never mutates the ledger. Output is intended
    for operator review; if accepted, the operator appends rows to
    ``state/impl_progress.jsonl`` manually. Rows with empty ``task_id``
    or ``path`` are skipped (cannot be bound to a revocation target).
    """
    now = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    for row in table:
        if row.get("classification") != "STALE":
            continue
        task_id = row.get("task_id") or ""
        path = row.get("path") or ""
        if not task_id or not path:
            continue
        sat = row.get("satisfied_by") or "deleted"
        out = {
            "ts": now,
            "phase": "META",
            "task_id": task_id,
            "event": "scope_revoke",
            "detail": f"closes stale SE for {path} (satisfied_by={sat})",
            "files": [],
            "paths": [path],
            "approved_by": "operator_review_required",
            "exit": 0,
        }
        sys.stdout.write(json.dumps(out) + "\n")


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--ledger", type=pathlib.Path, default=LEDGER_PATH,
        help="Path to impl_progress.jsonl (default: %(default)s).",
    )
    parser.add_argument(
        "--repo", type=pathlib.Path, default=PROJECT_DIR,
        help="Repo root for git lookups (default: %(default)s).",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit 1 if any STALE rows are reported (CI gate). Audit is "
             "still read-only; no ledger mutation occurs.",
    )
    parser.add_argument(
        "--emit-revoke-rows", action="store_true",
        help="Instead of the human report, emit one draft scope_revoke "
             "jsonl row to stdout per STALE path. Read-only: the operator "
             "reviews and manually appends accepted rows to the ledger.",
    )
    args = parser.parse_args(argv)

    try:
        table, stale = audit(args.ledger, args.repo)
    except FileNotFoundError as e:
        sys.stderr.write(f"error: {e}\n")
        return 2
    except OSError as e:
        sys.stderr.write(f"error reading ledger: {e}\n")
        return 2

    if args.emit_revoke_rows:
        _emit_revoke_rows(table)
        return 0

    sys.stdout.write(_format_table(table))
    sys.stdout.write(f"\nSummary: {stale} STALE / {len(table)} total SE paths "
                     f"(window=last {WINDOW} rows)\n")
    if args.strict and stale > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
