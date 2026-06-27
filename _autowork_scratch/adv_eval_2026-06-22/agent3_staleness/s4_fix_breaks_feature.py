#!/usr/bin/env python3
"""Agent-3 staleness eval — adversarial test of the PROPOSED FIX against the
feature's ACTUAL intended use case (per the original brief, lines 171-178).

The original brief's design (brief_hooks_briefstatus_accept_staleness.md) argues:
  "by the time _auto_promote runs, the plan has ALREADY been re-persisted to match
   the corrected brief (so plan_stale is False again -- a SHA compare at this point
   would NOT detect the past correction), whereas the plan mtime DURABLY records
   WHEN that regeneration happened."

So the feature's REAL target scenario is:
  1. oracle task accepted at T1 (sha matches plan)
  2. brief CORRECTED (content changes) -> plan_stale True momentarily -> RE-PLAN
  3. re-plan re-persists plan_hooks_<slug>.json at T2 > T1, RE-STAMPING
     source_brief_sha256 to match the NEW brief content.
  4. Now compute_brief_status runs again: plan_stale is FALSE (sha re-matched),
     BUT the oracle's accept T1 < plan mtime T2 => the CURRENT guard re-queues it.
     <-- THIS is the legitimate behavior the feature delivers.

We test whether the PROPOSED FIX (gate guard on plan_stale) still re-queues this
LEGITIMATE corrected-brief case. If plan_stale is False at re-promote time, the
SHA-gated guard will FAIL to re-queue => FIX BREAKS THE FEATURE.
"""
import json
import os
import sys
import tempfile
import types
import datetime
import hashlib
from pathlib import Path

REPO = Path("/home/xnihil0zer0/JanusMaskJR")
sys.path.insert(0, str(REPO))

SRC = (REPO / "harness" / "brief_status.py").read_text(encoding="utf-8")
OLD = "if plan_mtime > 0.0 and accept_ts is not None and accept_ts < plan_mtime:"
NEW = "if plan_stale and (plan_mtime > 0.0 and accept_ts is not None and accept_ts < plan_mtime:"  # placeholder
NEW = "if plan_stale and plan_mtime > 0.0 and accept_ts is not None and accept_ts < plan_mtime:"
PATCHED_SRC = SRC.replace(OLD, NEW)
assert PATCHED_SRC != SRC

mod = types.ModuleType("bs_patched_sha")
mod.__dict__["__file__"] = str(REPO / "harness" / "brief_status.py")
exec(compile(PATCHED_SRC, "bs_patched_sha", "exec"), mod.__dict__)
compute_sha_gated = mod.compute_brief_status
from harness.brief_status import compute_brief_status as compute_real  # noqa: E402

SLUG = "acstale"
TASK = "oracle_1"
ACCEPT_ISO = "2026-01-01T00:00:00Z"


def iso_epoch(ts):
    iso = ts[:-1] + "+00:00" if ts[-1] in "Zz" else ts
    return datetime.datetime.fromisoformat(iso).timestamp()


def build_corrected_brief_scenario(root):
    """The feature's real target: brief was corrected then re-planned; the plan's
    stamped sha NOW MATCHES the current (corrected) brief content (plan_stale False),
    but plan mtime T2 > acceptance T1."""
    repo_root = root / "repo"
    state_dir = root / "state"
    repo_root.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    brief = repo_root / f"brief_hooks_{SLUG}.md"
    # the CURRENT (already-corrected) brief content
    brief.write_text("# corrected brief v2\nnew body after correction\n", encoding="utf-8")
    cur_sha = hashlib.sha256(brief.read_bytes()).hexdigest()

    plan = repo_root / f"plan_hooks_{SLUG}.json"
    # re-plan already re-stamped the sha to match the corrected brief => NOT stale
    plan.write_text(json.dumps({"source_brief_sha256": cur_sha, "tasks": [{"task_id": TASK}]}), encoding="utf-8")

    ledger = state_dir / "impl_progress.jsonl"
    with open(ledger, "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ACCEPT_ISO, "phase": "accepted", "event": "auto_commit", "task_id": TASK, "commit_sha": "x"}) + "\n")

    accept_e = iso_epoch(ACCEPT_ISO)
    # plan re-persisted AFTER acceptance (the correction regenerated it)
    plan_mtime = accept_e + 5000.0
    os.utime(plan, (plan_mtime, plan_mtime))
    # brief mtime also after acceptance (it was edited)
    os.utime(brief, (accept_e + 4000.0, accept_e + 4000.0))
    return repo_root, state_dir


def run(fn, label, root_builder):
    with tempfile.TemporaryDirectory() as td:
        repo_root, state_dir = root_builder(Path(td))
        recs = fn(repo_root, state_dir)
        rec = next(r for r in recs if r["slug"] == SLUG)
        reopened = TASK in rec["remaining"] and TASK not in [a["task_id"] for a in rec["accepted"]]
        print(f"  [{label}] plan_stale={rec['plan_stale']!s:<6} state={rec['state']:<10} "
              f"accepted={[a['task_id'] for a in rec['accepted']]} remaining={rec['remaining']} unstaged={rec['unstaged_task_ids']}")
        print(f"         -> task re-opened (legit feature behavior)? {reopened}")
        return reopened


def main():
    print("=== FEATURE'S REAL TARGET: corrected brief, plan RE-STAMPED (plan_stale False at re-promote) ===")
    print("  Per original brief lines 171-178: at re-promote time the SHA has ALREADY re-matched.")
    print()
    print("  CURRENT (mtime) guard:")
    real_reopened = run(compute_real, "REAL/mtime", build_corrected_brief_scenario)
    print()
    print("  PROPOSED FIX (plan_stale/SHA-gated) guard:")
    fix_reopened = run(compute_sha_gated, "FIX/sha-gate", build_corrected_brief_scenario)
    print()
    print("=== VERDICT ===")
    print(f"  CURRENT guard re-opens the corrected-brief task (feature works): {real_reopened}")
    print(f"  SHA-GATED FIX re-opens it (feature preserved):                   {fix_reopened}")
    if real_reopened and not fix_reopened:
        print("  *** THE PROPOSED FIX BREAKS THE FEATURE in its real target scenario. ***")
        print("  Reason: at re-promote time plan_stale is already False (sha re-matched),")
        print("  so the SHA-gate suppresses the legitimate re-open the mtime guard delivers.")
    elif real_reopened and fix_reopened:
        print("  Both preserve the feature.")
    else:
        print("  CURRENT guard did NOT re-open even the legit case -- re-examine fixture.")


if __name__ == "__main__":
    main()
