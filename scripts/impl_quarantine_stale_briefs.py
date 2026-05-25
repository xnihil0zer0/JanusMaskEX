"""Quarantine stale brief_hooks_*.md (+ companion plan_hooks_*.json) into _archive/briefs/.

Three-phase quarantine per session #22 backlog review (master + sub-reports 01/04/05/06):
  - Tier A: brief slugs whose ALL plan task_ids exist in state/tasks/processed/.
            Auto-move brief + plan to _archive/briefs/complete/.
  - Tier B: name-pattern matches (development_progress_*, session_*_handoff,
            JanusMask-inefficiency-report-*.md at repo root).
            Auto-move to _archive/briefs/documentation/.
  - Tier D: 19 known zombie-task-id slugs from session #21 handoff lines 79-87.
            DO NOT auto-move; report only — operator runs AskUserQuestion review.

Drops repo's active brief count from ~108 → ~50-60.

Usage:
    python scripts/impl_quarantine_stale_briefs.py --dry-run   # default: report only
    python scripts/impl_quarantine_stale_briefs.py --apply     # mkdir + git mv

Exit codes:
    0 — quarantine reported (dry-run) or applied successfully
    1 — git mv failed for at least one path (apply mode)
    2 — usage error
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.impl_common import append_impl_progress_event  # noqa: E402

_ARCHIVE_ROOT = _REPO_ROOT / "_archive" / "briefs"
_BUCKET_COMPLETE = _ARCHIVE_ROOT / "complete"
_BUCKET_DOCS = _ARCHIVE_ROOT / "documentation"
_BUCKET_ZOMBIE = _ARCHIVE_ROOT / "zombie_planned"

# Tier B name-pattern slugs (without brief_hooks_ prefix; matched as p.stem)
_TIER_B_PATTERNS = (
    "brief_hooks_development_progress_",
    "brief_hooks_session_",
)

# Briefs protected from auto-archive even if they match a Tier B pattern.
# The current session's handoff brief is load-bearing until the session closes;
# the NEXT session archives it.
_PROTECTED_STEMS = {
    "brief_hooks_session_23_handoff",
}

# Tier D zombie task_ids → brief slugs per session #21 handoff lines 79-87.
# Work landed manually under DIFFERENT task_ids; original ids never got
# processed/<id>.json markers; auto-archive would lose audit context.
_TIER_D_SLUGS = {
    "meta_test_align_aw10c",
    "autowork_daemon",
    "webui_autobrief_v2",
    "webui_autobrief",
    "orchestrator_verification_required",
    "webui_scoping",
}

# Inefficiency-report root files (NOT brief_hooks_*; quarantined as Tier B).
_INEFFICIENCY_REPORTS = (
    "JanusMask-inefficiency-report-master.md",
    "JanusMask-inefficiency-report_01.md",
    "JanusMask-inefficiency-report_02.md",
    "JanusMask-inefficiency-report_03.md",
    "JanusMask-inefficiency-report_04.md",
    "JanusMask-inefficiency-report_05.md",
    "JanusMask-inefficiency-report_06.md",
)


def _processed_task_ids() -> set[str]:
    processed = _REPO_ROOT / "state" / "tasks" / "processed"
    if not processed.exists():
        return set()
    out: set[str] = set()
    for p in processed.iterdir():
        if not p.name.endswith(".json"):
            continue
        out.add(p.stem)
    return out


def _plan_task_ids(plan_path: pathlib.Path) -> list[str] | None:
    """Return task_ids list, or None if plan is unparseable/missing tasks key."""
    try:
        data = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        return None
    out: list[str] = []
    for t in tasks:
        if isinstance(t, dict) and isinstance(t.get("task_id"), str):
            out.append(t["task_id"])
    return out


def _classify() -> dict:
    """Walk repo_root for brief_hooks_*.md, classify each into a bucket."""
    processed = _processed_task_ids()
    brief_paths = sorted(_REPO_ROOT.glob("brief_hooks_*.md"))
    plan_paths = {p.stem.removeprefix("plan_hooks_"): p for p in _REPO_ROOT.glob("plan_hooks_*.json")}

    tier_a: list[tuple[pathlib.Path, pathlib.Path | None, list[str]]] = []
    tier_b: list[pathlib.Path] = []
    tier_d: list[pathlib.Path] = []
    skip: list[tuple[pathlib.Path, str]] = []  # active briefs left in place

    for bp in brief_paths:
        slug = bp.stem.removeprefix("brief_hooks_")
        stem_name = bp.stem  # e.g. brief_hooks_session_22_handoff

        # Tier B name-pattern (handoffs, development progress)
        if any(stem_name.startswith(prefix) for prefix in _TIER_B_PATTERNS):
            if stem_name in _PROTECTED_STEMS:
                skip.append((bp, "protected_active_handoff"))
                continue
            tier_b.append(bp)
            continue

        # Tier D zombie-task-id slugs (operator-review only)
        if slug in _TIER_D_SLUGS:
            tier_d.append(bp)
            continue

        # Tier A: ALL plan task_ids exist in state/tasks/processed/
        plan = plan_paths.get(slug)
        if plan is None:
            skip.append((bp, "no_plan"))
            continue
        task_ids = _plan_task_ids(plan)
        if not task_ids:
            skip.append((bp, "plan_no_tasks"))
            continue
        unprocessed = [tid for tid in task_ids if tid not in processed]
        if unprocessed:
            skip.append((bp, f"unprocessed:{','.join(unprocessed[:3])}"))
            continue
        tier_a.append((bp, plan, task_ids))

    # Inefficiency-report root files → Tier B (separate non-brief class)
    inefficiency_tier_b: list[pathlib.Path] = []
    for fname in _INEFFICIENCY_REPORTS:
        fp = _REPO_ROOT / fname
        if fp.exists():
            inefficiency_tier_b.append(fp)

    return {
        "tier_a": tier_a,
        "tier_b": tier_b,
        "tier_b_inefficiency": inefficiency_tier_b,
        "tier_d": tier_d,
        "skip": skip,
    }


def _git_mv(src: pathlib.Path, dst: pathlib.Path) -> bool:
    """git mv if src is tracked, else os.rename. Returns True on success."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    # check if tracked
    rc = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(src.relative_to(_REPO_ROOT))],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    tracked = rc.returncode == 0
    if tracked:
        rc = subprocess.run(
            ["git", "mv", str(src.relative_to(_REPO_ROOT)), str(dst.relative_to(_REPO_ROOT))],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )
        if rc.returncode != 0:
            sys.stderr.write(f"git mv FAILED {src} → {dst}: {rc.stderr}\n")
            return False
        return True
    # untracked: plain rename
    try:
        src.rename(dst)
    except OSError as e:
        sys.stderr.write(f"rename FAILED {src} → {dst}: {e}\n")
        return False
    return True


def _apply(classification: dict) -> tuple[int, int]:
    """Apply tier A + tier B moves. Returns (moved, failed)."""
    moved = 0
    failed = 0
    _BUCKET_COMPLETE.mkdir(parents=True, exist_ok=True)
    _BUCKET_DOCS.mkdir(parents=True, exist_ok=True)
    _BUCKET_ZOMBIE.mkdir(parents=True, exist_ok=True)

    for bp, plan, _ids in classification["tier_a"]:
        dst = _BUCKET_COMPLETE / bp.name
        if _git_mv(bp, dst):
            moved += 1
        else:
            failed += 1
        if plan is not None:
            dst_plan = _BUCKET_COMPLETE / plan.name
            if _git_mv(plan, dst_plan):
                moved += 1
            else:
                failed += 1

    for bp in classification["tier_b"]:
        dst = _BUCKET_DOCS / bp.name
        if _git_mv(bp, dst):
            moved += 1
        else:
            failed += 1
        # Companion plan?
        slug = bp.stem.removeprefix("brief_hooks_")
        plan = _REPO_ROOT / f"plan_hooks_{slug}.json"
        if plan.exists():
            dst_plan = _BUCKET_DOCS / plan.name
            if _git_mv(plan, dst_plan):
                moved += 1
            else:
                failed += 1

    for fp in classification["tier_b_inefficiency"]:
        dst = _BUCKET_DOCS / fp.name
        if _git_mv(fp, dst):
            moved += 1
        else:
            failed += 1

    return moved, failed


def _report(classification: dict) -> None:
    a = classification["tier_a"]
    b = classification["tier_b"]
    bi = classification["tier_b_inefficiency"]
    d = classification["tier_d"]
    skip = classification["skip"]

    print(f"\n=== Tier A — shipped-complete (auto-archive: {len(a)} briefs) ===")
    for bp, plan, ids in a:
        ids_short = ",".join(ids[:3]) + (",..." if len(ids) > 3 else "")
        plan_name = plan.name if plan else "<none>"
        print(f"  {bp.name}  plan={plan_name}  task_ids=[{ids_short}]")

    print(f"\n=== Tier B — name-pattern docs (auto-archive: {len(b) + len(bi)} files) ===")
    for bp in b:
        print(f"  {bp.name}")
    for fp in bi:
        print(f"  {fp.name}")

    print(f"\n=== Tier D — zombie-task-id (operator-review-only: {len(d)} briefs) ===")
    for bp in d:
        print(f"  {bp.name}")

    print(f"\n=== Skipped (left in place: {len(skip)} briefs) ===")
    for bp, reason in skip[:30]:
        print(f"  {bp.name}  ({reason})")
    if len(skip) > 30:
        print(f"  ... and {len(skip) - 30} more")

    auto_archive_count = len(a) + len(b) + len(bi)
    print(f"\nSummary: auto-archive={auto_archive_count}  tier-d-review={len(d)}  skip={len(skip)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply moves (default: dry-run report only)")
    parser.add_argument("--dry-run", action="store_true", help="Report only (default behavior; flag kept for clarity)")
    args = parser.parse_args()

    classification = _classify()
    _report(classification)

    if not args.apply:
        print("\n(dry-run; re-run with --apply to move files)")
        return 0

    moved, failed = _apply(classification)
    print(f"\napply: moved={moved}  failed={failed}")

    auto_archive_count = (
        len(classification["tier_a"]) * 2  # brief + plan each
        + len(classification["tier_b"])
        + len(classification["tier_b_inefficiency"])
    )
    append_impl_progress_event(
        event="observation",
        task_id="SESSION_23_QUARANTINE",
        phase="META",
        detail=(
            f"impl_quarantine_stale_briefs.py applied: "
            f"tier_a={len(classification['tier_a'])} brief+plan pairs, "
            f"tier_b={len(classification['tier_b'])} docs + {len(classification['tier_b_inefficiency'])} inefficiency, "
            f"tier_d={len(classification['tier_d'])} held for operator, "
            f"moved={moved} failed={failed}."
        ),
        files=["_archive/briefs/complete/**", "_archive/briefs/documentation/**", "_archive/briefs/zombie_planned/**"],
        exit_code=0 if failed == 0 else 1,
    )

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
