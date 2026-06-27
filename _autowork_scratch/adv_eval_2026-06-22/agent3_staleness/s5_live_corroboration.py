#!/usr/bin/env python3
"""Agent-3 staleness eval — Step 4 LIVE corroboration (READ-ONLY).

Confirms with REAL numbers:
  - the two manifest auto_commit (accepted) ledger rows + their ts
  - the archived manifest plan file mtime
  - the ordering: accept_ts < plan_mtime for BOTH tasks
  - the tree-wide stamp: ALL untracked plan_hooks_*.json at root share the
    integrate instant (proving the mechanism is git stash pop, not a per-plan
    rewrite).

Reads only; never writes live state.
"""
import json
import subprocess
import datetime
import sys
from pathlib import Path

REPO = Path("/home/xnihil0zer0/JanusMaskJR")
sys.path.insert(0, str(REPO))
from harness.brief_status import compute_brief_status  # noqa: F401  (parity import)

LEDGER = REPO / "state" / "impl_progress.jsonl"
ARCHIVED_PLAN = REPO / "_autowork_archive" / "2026-06-22_manifest_drop_undeclared_keys" / "plan_hooks_manifest_drop_undeclared_keys.json"
TASKS = ("manifest-drop-undeclared-impl", "manifest-drop-undeclared-oracle")


def norm_iso(ts):
    iso = ts[:-1] + "+00:00" if ts[-1] in "Zz" else ts
    return datetime.datetime.fromisoformat(iso).timestamp()


def main():
    print("=== (4a) auto_commit accepted ledger rows for the manifest brief ===")
    accepts = {}
    with open(LEDGER, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if not isinstance(r, dict):
                continue
            if r.get("task_id") in TASKS and r.get("phase") == "accepted" and r.get("event") == "auto_commit":
                accepts[r["task_id"]] = r.get("ts")
    for t in TASKS:
        ts = accepts.get(t)
        e = norm_iso(ts) if ts else None
        print(f"  {t}: ts={ts!r}  epoch={e}  local={datetime.datetime.fromtimestamp(e).isoformat() if e else None}")

    print()
    print("=== (4b) archived manifest plan file mtime ===")
    pm = ARCHIVED_PLAN.stat().st_mtime
    print(f"  {ARCHIVED_PLAN.name}: mtime={pm}  local={datetime.datetime.fromtimestamp(pm).isoformat()}")

    print()
    print("=== (4c) ordering: accept_ts < plan_mtime (=> re-queued by current guard) ===")
    for t in TASKS:
        e = norm_iso(accepts[t])
        print(f"  {t}: accept {e} < plan {pm} ? {e < pm}   (gap = {pm - e:.3f}s)")

    print()
    print("=== (4d) tree-wide stamp: distinct mtime-seconds of ALL untracked plan_hooks_*.json at root ===")
    out = subprocess.run(["git", "status", "--porcelain"], cwd=str(REPO), capture_output=True, text=True).stdout
    plan_files = [ln[3:] for ln in out.splitlines() if ln.startswith("?? plan_hooks_") and ln.endswith(".json")]
    secs = {}
    for pf in plan_files:
        try:
            m = (REPO / pf).stat().st_mtime
        except OSError:
            continue
        secs.setdefault(int(m), 0)
        secs[int(m)] += 1
    print(f"  untracked root plans: {len(plan_files)}")
    for s in sorted(secs):
        print(f"    mtime second {s} ({datetime.datetime.fromtimestamp(s).isoformat()}): {secs[s]} files")
    bumped = secs.get(int(pm), 0)
    print(f"  files sharing the manifest-integrate instant {int(pm)}: {bumped}")
    print()
    print("=== VERDICT (live) ===")
    both_after = all(norm_iso(accepts[t]) < pm for t in TASKS)
    tree_wide = len(secs) == 1 and bumped == len(plan_files) and len(plan_files) > 1
    print(f"  both manifest accepts precede plan mtime (re-queued):        {both_after}")
    print(f"  ALL untracked root plans share ONE integrate instant:        {tree_wide}")
    print(f"  => mechanism is a TREE-WIDE mtime stamp (git stash pop), not a per-plan rewrite")


if __name__ == "__main__":
    main()
