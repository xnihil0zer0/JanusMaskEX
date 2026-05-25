#!/usr/bin/env python3
"""
impl_audit_git_churn.py — Audit JanusMask git history for fix-on-fix patterns,
churn hotspots, scope_exception census, and orphan briefs/plans.

READ-ONLY.  Calls `git log`, parses the impl_progress ledger, walks the
working tree.  Produces:
  - A human-readable summary on stdout
  - A JSON blob (after the summary) with:
      * top_churn_hotspots          — files with most commits
      * top_fix_chains              — sequences of consecutive fix commits
                                      touching the same file
      * scope_exception_census      — distinct paths excepted, with counts
                                      and most-recent reason
      * scope_exception_scripts     — scripts/impl_*scope_exception*.py with
                                      first-commit info (or "untracked")
      * orphan_briefs               — brief_hooks_*.md files in working tree
                                      that never produced (or whose plan never
                                      produced) a commit naming them
      * orphan_plans                — same, for plan_hooks_*.json
      * integrate_then_fix_cascades — "Integrate validated code for X" commits
                                      whose touched file(s) were re-touched by a
                                      fix commit within N subsequent commits

Run:   python scripts/impl_audit_git_churn.py
Run with verbose:  python scripts/impl_audit_git_churn.py --verbose
"""

from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import os
import pathlib
import re
import subprocess
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Keywords used to classify a commit as a "fix" commit.  Conservative — we
# want to count compensating commits, not feature commits that happen to
# mention "fix" in passing.
FIX_KEYWORDS = re.compile(
    r"\b(fix|hotfix|patch|carve(?:-?out)?|revert|unblock|lift|"
    r"testfix|nondet|workaround|scope_exception|carveout|"
    r"correct|silent-(?:pass|return)|exception(?:al)?)\b",
    re.IGNORECASE,
)
INTEGRATE_RE = re.compile(r"^Integrate validated code for\s+(.+)$", re.IGNORECASE)

# These prefix paths are noise for churn analysis (briefs, plans, snapshots).
NOISE_PREFIXES = (
    "brief_",
    "plan_",
    "plan-",
    "audit-",
    "comprehensive-",
    "harness-",
    "hooks-implementation",
    "hooks-augmented",
    "janus-mask-",
    "janusmask-",
    "live-",
    "log_",
    "review-plan-",
    "subreport-",
    "sub-test-plan",
    "test-and-fix-results",
    "v2_clean_room",
    "external-usage",
    "PS-011-spec",
    "PS-013-spec",
)


def _is_noise(path: str) -> bool:
    name = path.split("/")[-1]
    if name.startswith("brief_hooks_") or name.startswith("plan_hooks_"):
        return True
    for prefix in NOISE_PREFIXES:
        if name.startswith(prefix):
            return True
    if name.endswith(".log") or name.endswith(".pre-amend"):
        return True
    return False


# ---------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------
def _git(args: list[str]) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, errors="replace"
    )


def _load_commits() -> list[dict[str, Any]]:
    """Return a list of dicts: {sha, date, subject, files}."""
    raw = _git([
        "log",
        "--pretty=format:%H|%ad|%s",
        "--date=short",
        "--name-only",
    ])
    commits: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in raw.splitlines():
        if "|" in line and len(line.split("|", 2)[0]) == 40 and all(
            c in "0123456789abcdef" for c in line.split("|", 2)[0]
        ):
            if cur is not None:
                commits.append(cur)
            sha, date, subject = line.split("|", 2)
            cur = {"sha": sha, "date": date, "subject": subject, "files": []}
        elif line.strip() == "":
            continue
        elif cur is not None:
            cur["files"].append(line.strip())
    if cur is not None:
        commits.append(cur)
    return commits


def _classify(subject: str) -> bool:
    return bool(FIX_KEYWORDS.search(subject))


# ---------------------------------------------------------------------------
# analyses
# ---------------------------------------------------------------------------
def churn_hotspots(commits: list[dict[str, Any]], top_n: int = 15) -> list[dict[str, Any]]:
    by_file: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for c in commits:
        for f in c["files"]:
            if _is_noise(f):
                continue
            by_file[f].append(c)

    rows = []
    for f, cs in by_file.items():
        fix_count = sum(1 for c in cs if _classify(c["subject"]))
        last_fix_date = max(
            (c["date"] for c in cs if _classify(c["subject"])),
            default="",
        )
        last_any = max(c["date"] for c in cs)
        rows.append({
            "file": f,
            "total_commits": len(cs),
            "fix_commits": fix_count,
            "fix_ratio": round(fix_count / len(cs), 3),
            "last_commit_date": last_any,
            "last_fix_date": last_fix_date,
            "exists_on_disk": (ROOT / f).exists(),
        })
    rows.sort(key=lambda r: (-r["total_commits"], -r["fix_commits"]))
    return rows[:top_n]


def fix_chains(commits: list[dict[str, Any]], min_len: int = 2) -> list[dict[str, Any]]:
    """A chain is N>=min_len consecutive (in chronological order) commits where
    each touches the same file AND each is classified as a fix.

    We walk commits in chronological (oldest-first) order per-file.
    """
    by_file: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    # commits are newest-first; reverse for chronological
    for c in reversed(commits):
        for f in c["files"]:
            if _is_noise(f):
                continue
            by_file[f].append(c)

    chains: list[dict[str, Any]] = []
    for f, cs in by_file.items():
        chain: list[dict[str, Any]] = []
        for c in cs:
            if _classify(c["subject"]):
                chain.append(c)
            else:
                if len(chain) >= min_len:
                    chains.append(
                        {"file": f, "length": len(chain), "commits": [
                            {"sha": cc["sha"][:10], "date": cc["date"],
                             "subject": cc["subject"]}
                            for cc in chain
                        ]}
                    )
                chain = []
        if len(chain) >= min_len:
            chains.append({"file": f, "length": len(chain), "commits": [
                {"sha": cc["sha"][:10], "date": cc["date"], "subject": cc["subject"]}
                for cc in chain
            ]})
    chains.sort(key=lambda x: -x["length"])
    return chains[:15]


def integrate_then_fix(
    commits: list[dict[str, Any]], window: int = 8
) -> list[dict[str, Any]]:
    """Find "Integrate validated code for X" commits whose touched non-noise
    files were re-touched by a fix commit within the next `window` commits.
    """
    # newest-first ordering of commits is what we have; build a chronological list
    chrono = list(reversed(commits))
    cascades: list[dict[str, Any]] = []
    for i, c in enumerate(chrono):
        m = INTEGRATE_RE.match(c["subject"])
        if not m:
            continue
        touched = [f for f in c["files"] if not _is_noise(f)]
        followups: list[dict[str, Any]] = []
        for j in range(i + 1, min(i + 1 + window, len(chrono))):
            nxt = chrono[j]
            if not _classify(nxt["subject"]):
                continue
            overlap = [f for f in nxt["files"] if f in touched]
            if overlap:
                followups.append({
                    "sha": nxt["sha"][:10],
                    "date": nxt["date"],
                    "subject": nxt["subject"],
                    "files": overlap,
                })
        if followups:
            cascades.append({
                "integrate_sha": c["sha"][:10],
                "integrate_date": c["date"],
                "integrate_subject": c["subject"],
                "task_id": m.group(1).strip(),
                "touched_files": touched,
                "followup_fixes": followups,
            })
    return cascades


# ---------------------------------------------------------------------------
# scope_exception census from the ledger
# ---------------------------------------------------------------------------
def scope_exception_census() -> dict[str, Any]:
    ledger = ROOT / "state" / "impl_progress.jsonl"
    if not ledger.exists():
        return {"error": f"ledger not found at {ledger}"}

    by_path: dict[str, dict[str, Any]] = {}
    total_rows = 0
    for line in ledger.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("event") != "scope_exception":
            continue
        total_rows += 1
        for p in row.get("paths", []) or []:
            slot = by_path.setdefault(p, {
                "path": p,
                "count": 0,
                "first_ts": row.get("ts", ""),
                "last_ts": row.get("ts", ""),
                "last_reason": row.get("detail", ""),
                "last_task_id": row.get("task_id", ""),
                "is_glob": any(ch in p for ch in "*?["),
                "exists_on_disk": False if any(ch in p for ch in "*?[") else (ROOT / p).exists(),
            })
            slot["count"] += 1
            ts = row.get("ts", "")
            if ts < slot["first_ts"]:
                slot["first_ts"] = ts
            if ts > slot["last_ts"]:
                slot["last_ts"] = ts
                slot["last_reason"] = row.get("detail", "")
                slot["last_task_id"] = row.get("task_id", "")

    rows = sorted(by_path.values(), key=lambda r: -r["count"])
    return {
        "total_scope_exception_rows": total_rows,
        "distinct_paths": len(rows),
        "top_paths": rows[:25],
    }


def scope_exception_scripts() -> list[dict[str, Any]]:
    """List every scripts/impl_*scope_exception*.py and its first-commit
    metadata (or marked 'untracked' if it never landed)."""
    out = []
    for p in sorted((ROOT / "scripts").glob("impl_*scope_exception*.py")):
        rel = str(p.relative_to(ROOT))
        try:
            log = _git([
                "log", "--diff-filter=A", "--format=%H|%ad|%s",
                "--date=short", "--", rel,
            ]).strip()
        except subprocess.CalledProcessError:
            log = ""
        if log:
            sha, date, subject = log.splitlines()[0].split("|", 2)
            out.append({
                "script": rel,
                "tracked": True,
                "first_sha": sha[:10],
                "first_date": date,
                "first_subject": subject,
            })
        else:
            out.append({
                "script": rel,
                "tracked": False,
                "first_sha": None,
                "first_date": None,
                "first_subject": None,
            })
    return out


# ---------------------------------------------------------------------------
# orphan brief / plan analysis
# ---------------------------------------------------------------------------
def orphan_briefs_and_plans(commits: list[dict[str, Any]]) -> dict[str, Any]:
    """Walk working-tree brief_hooks_*.md and plan_hooks_*.json files.  Mark a
    brief or plan as 'orphan' if no commit subject mentions its stem AND no
    commit touches it.
    """
    briefs = sorted(ROOT.glob("brief_hooks_*.md"))
    plans = sorted(ROOT.glob("plan_hooks_*.json"))

    # Build subject-mention index
    subjects = " || ".join(c["subject"].lower() for c in commits)
    touched: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for c in commits:
        for f in c["files"]:
            touched[f].append(c)

    def _classify_file(p: pathlib.Path) -> dict[str, Any]:
        rel = str(p.relative_to(ROOT))
        stem = p.stem
        # strip suffix variants
        canonical = (
            stem.replace("brief_hooks_", "")
                .replace("plan_hooks_", "")
                .replace("_critique", "")
                .replace(".sonnet_v1", "")
                .replace(".haiku_v4", "")
                .replace("_v2", "")
        )
        canonical_lower = canonical.lower()
        produced_commits = [
            {"sha": c["sha"][:10], "date": c["date"], "subject": c["subject"]}
            for c in commits
            if canonical_lower in c["subject"].lower()
        ]
        touched_commits = [
            {"sha": c["sha"][:10], "date": c["date"], "subject": c["subject"]}
            for c in touched.get(rel, [])
        ]
        is_tracked = bool(touched_commits)
        # Orphan = neither tracked in git nor mentioned in any commit subject
        orphan = (not is_tracked) and (not produced_commits)
        # Stale-tracked = tracked but no commit subject mentions it for >7 days
        days_since_touched = None
        if touched_commits:
            last = max(c["date"] for c in touched_commits)
            try:
                days_since_touched = (_dt.date.today() - _dt.date.fromisoformat(last)).days
            except Exception:
                days_since_touched = None
        return {
            "file": rel,
            "tracked_in_git": is_tracked,
            "subject_mentions": len(produced_commits),
            "files_touched_count": len(touched_commits),
            "last_touched_date": (max(c["date"] for c in touched_commits)
                                  if touched_commits else None),
            "days_since_touched": days_since_touched,
            "is_orphan": orphan,
            "stem": canonical,
            "size_bytes": p.stat().st_size,
            "mtime": _dt.datetime.fromtimestamp(p.stat().st_mtime).strftime(
                "%Y-%m-%d"),
        }

    brief_rows = [_classify_file(p) for p in briefs]
    plan_rows = [_classify_file(p) for p in plans]

    return {
        "briefs": brief_rows,
        "plans": plan_rows,
        "orphan_brief_count": sum(1 for r in brief_rows if r["is_orphan"]),
        "orphan_plan_count": sum(1 for r in plan_rows if r["is_orphan"]),
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-n", type=int, default=15)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--json-only", action="store_true",
                    help="Suppress human summary, emit only JSON.")
    args = ap.parse_args()

    commits = _load_commits()
    hot = churn_hotspots(commits, top_n=args.top_n)
    chains = fix_chains(commits)
    se_census = scope_exception_census()
    se_scripts = scope_exception_scripts()
    orphans = orphan_briefs_and_plans(commits)
    cascades = integrate_then_fix(commits)

    payload = {
        "generated_at": _dt.datetime.utcnow().isoformat() + "Z",
        "total_commits": len(commits),
        "first_commit_date": commits[-1]["date"] if commits else None,
        "last_commit_date": commits[0]["date"] if commits else None,
        "fix_commit_count": sum(1 for c in commits if _classify(c["subject"])),
        "integrate_commit_count": sum(
            1 for c in commits if INTEGRATE_RE.match(c["subject"])
        ),
        "top_churn_hotspots": hot,
        "top_fix_chains": chains,
        "scope_exception_census": se_census,
        "scope_exception_scripts": se_scripts,
        "orphan_briefs_and_plans": orphans,
        "integrate_then_fix_cascades": cascades,
    }

    if not args.json_only:
        _print_summary(payload)

    print("\n----- JSON -----")
    print(json.dumps(payload, indent=2, default=str))
    return 0


def _print_summary(p: dict[str, Any]) -> None:
    print("=" * 78)
    print("JanusMask git-churn audit")
    print("=" * 78)
    print(f"Window: {p['first_commit_date']} … {p['last_commit_date']}")
    print(f"Total commits: {p['total_commits']}")
    print(f"Fix-classified commits: {p['fix_commit_count']} "
          f"({p['fix_commit_count']*100//max(p['total_commits'],1)}%)")
    print(f"'Integrate validated code for ...' commits: {p['integrate_commit_count']}")
    print()
    print("--- Top churn hotspots (non-brief, non-plan) ---")
    for r in p["top_churn_hotspots"][:10]:
        flag = "" if r["exists_on_disk"] else " [DELETED]"
        print(f"  {r['total_commits']:>3}  commits  "
              f"({r['fix_commits']:>2} fixes, ratio {r['fix_ratio']:.2f})  "
              f"{r['file']}{flag}")
    print()
    print("--- Top fix chains (>=2 consecutive fix commits same file) ---")
    for ch in p["top_fix_chains"][:10]:
        print(f"  chain of {ch['length']}  on  {ch['file']}")
        for c in ch["commits"][:6]:
            print(f"     {c['sha']}  {c['date']}  {c['subject'][:80]}")
    print()
    se = p["scope_exception_census"]
    print(f"--- scope_exception census "
          f"(total rows: {se.get('total_scope_exception_rows', '?')}; "
          f"distinct paths: {se.get('distinct_paths', '?')}) ---")
    for r in se.get("top_paths", [])[:10]:
        marker = "*glob*" if r["is_glob"] else (
            "exists" if r["exists_on_disk"] else "missing"
        )
        print(f"  {r['count']:>3}x  [{marker:7}]  {r['path']}")
        print(f"        last: {r['last_ts']}  reason: {r['last_reason'][:70]}")
    print()
    print("--- scripts/impl_*scope_exception*.py (count = "
          f"{len(p['scope_exception_scripts'])}) ---")
    for r in p["scope_exception_scripts"]:
        if r["tracked"]:
            print(f"  TRACKED   {r['script']}  ({r['first_date']} {r['first_sha']})")
        else:
            print(f"  UNTRACKED {r['script']}  <-- never committed")
    print()
    o = p["orphan_briefs_and_plans"]
    print(f"--- Orphan briefs/plans  "
          f"({o['orphan_brief_count']} briefs, {o['orphan_plan_count']} plans never produced a tracked commit or subject mention) ---")
    for r in o["briefs"]:
        tag = "ORPHAN" if r["is_orphan"] else (
            "tracked" if r["tracked_in_git"] else "mentioned-only"
        )
        print(f"  [{tag:14}] mentions={r['subject_mentions']:>2}  "
              f"touched={r['files_touched_count']:>2}  "
              f"mtime={r['mtime']}  {r['file']}")
    print("  ---")
    for r in o["plans"]:
        tag = "ORPHAN" if r["is_orphan"] else (
            "tracked" if r["tracked_in_git"] else "mentioned-only"
        )
        print(f"  [{tag:14}] mentions={r['subject_mentions']:>2}  "
              f"touched={r['files_touched_count']:>2}  "
              f"mtime={r['mtime']}  {r['file']}")
    print()
    cas = p["integrate_then_fix_cascades"]
    print(f"--- Integrate-then-fix cascades  ({len(cas)} cascades) ---")
    for c in cas[:8]:
        print(f"  {c['integrate_sha']}  {c['integrate_date']}  "
              f"task={c['task_id'][:50]}")
        print(f"      touched: {', '.join(c['touched_files'][:3])}"
              + (" ..." if len(c['touched_files']) > 3 else ""))
        for f in c["followup_fixes"][:3]:
            print(f"      -> {f['sha']}  {f['date']}  {f['subject'][:65]}")


if __name__ == "__main__":
    sys.exit(main())
