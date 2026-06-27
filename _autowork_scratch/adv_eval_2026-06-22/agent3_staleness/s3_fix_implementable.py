#!/usr/bin/env python3
"""Agent-3 staleness eval — Step 3a implementability proof.

The proposed fix gates the accept-staleness guard on the SAME source_brief_sha256
signal that plan_stale already uses. We prove this is IMPLEMENTABLE in-place by
producing a PATCHED copy of compute_brief_status whose guard fires only when the
brief SHA actually changed, and running it against the SAME synthetic fixtures
plus a genuinely-edited-brief fixture.

We do NOT modify the live harness file. We construct the patched function by
copying the source and applying a targeted text substitution, exec-ing the result
in an isolated module namespace, then driving it.

Proves:
  - patched guard KEEPs the landed brief (SHA unchanged) -> bug fixed
  - patched guard RE-QUEUEs a brief whose SHA changed    -> feature intact
"""
import json
import os
import sys
import tempfile
import types
import datetime
from pathlib import Path

REPO = Path("/home/xnihil0zer0/JanusMaskJR")
sys.path.insert(0, str(REPO))

SRC = (REPO / "harness" / "brief_status.py").read_text(encoding="utf-8")

# The current guard line (verbatim from source). We replace it so that the guard
# requires an additional `plan_stale` truthiness (which is True exactly when the
# stamped source_brief_sha256 != current brief sha). plan_stale is already
# computed earlier in the same function scope.
OLD = "if plan_mtime > 0.0 and accept_ts is not None and accept_ts < plan_mtime:"
NEW = "if plan_stale and (plan_mtime > 0.0 and accept_ts is not None and accept_ts < plan_mtime):"
assert SRC.count(OLD) == 1, f"expected exactly one occurrence of guard, found {SRC.count(OLD)}"
PATCHED_SRC = SRC.replace(OLD, NEW)

# NOTE: when plan_stale becomes True the code sets has_plan=False, which would
# flip state to 'unplanned' and SKIP the accept loop entirely (task_ids stays
# but the accepted/remaining classification still runs on task_ids). To keep the
# discriminator meaningful we DO NOT rely on has_plan; we only inspect whether
# accepted vs remaining places the tasks correctly. (See note in findings.)

mod = types.ModuleType("brief_status_patched")
mod.__dict__["__file__"] = str(REPO / "harness" / "brief_status.py")
exec(compile(PATCHED_SRC, "brief_status_patched", "exec"), mod.__dict__)
compute_patched = mod.compute_brief_status

# also import the real one for side-by-side
from harness.brief_status import compute_brief_status as compute_real  # noqa: E402

SLUG = "synthslug"
TASKS = ["synth-impl", "synth-oracle"]
ACCEPT_ISO = {"synth-impl": "2026-06-22T17:18:04Z", "synth-oracle": "2026-06-22T17:26:48Z"}


def iso_to_epoch(ts):
    iso = ts[:-1] + "+00:00" if ts[-1] in "Zz" else ts
    return datetime.datetime.fromisoformat(iso).timestamp()


def build(root, plan_mtime, sha_matches: bool):
    repo_root = root / "repo"
    state_dir = root / "state"
    repo_root.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    brief = repo_root / f"brief_hooks_{SLUG}.md"
    brief.write_text("# synthetic brief\nbody\n", encoding="utf-8")
    import hashlib
    real_sha = hashlib.sha256(brief.read_bytes()).hexdigest()
    stamped = real_sha if sha_matches else ("0" * 64)
    plan = repo_root / f"plan_hooks_{SLUG}.json"
    plan.write_text(json.dumps({"source_brief_sha256": stamped, "tasks": [{"task_id": t} for t in TASKS]}), encoding="utf-8")
    ledger = state_dir / "impl_progress.jsonl"
    with open(ledger, "w", encoding="utf-8") as f:
        for t in TASKS:
            f.write(json.dumps({"ts": ACCEPT_ISO[t], "phase": "accepted", "event": "auto_commit", "task_id": t, "commit_sha": "x"}) + "\n")
    os.utime(plan, (plan_mtime, plan_mtime))
    return repo_root, state_dir


def run(fn, label, plan_mtime, sha_matches):
    with tempfile.TemporaryDirectory() as td:
        repo_root, state_dir = build(Path(td), plan_mtime, sha_matches)
        recs = fn(repo_root, state_dir)
        rec = next(r for r in recs if r["slug"] == SLUG)
        print(f"  [{label}] sha_matches={sha_matches} plan_mtime>accept={plan_mtime>iso_to_epoch(ACCEPT_ISO['synth-oracle'])}")
        print(f"      state={rec['state']:<10} plan_stale={rec['plan_stale']!s:<6} accepted={[a['task_id'] for a in rec['accepted']]} remaining={rec['remaining']}")
        return rec


def main():
    latest = iso_to_epoch(ACCEPT_ISO["synth-oracle"])
    bump = latest + 0.949

    print("=== REAL (current) function ===")
    print("  bug case (sha unchanged, mtime bumped after accept):")
    real_bug = run(compute_real, "REAL", bump, sha_matches=True)
    print("  feature case (sha CHANGED):")
    real_feat = run(compute_real, "REAL", bump, sha_matches=False)

    print()
    print("=== PATCHED (SHA-gated guard) function ===")
    print("  bug case (sha unchanged, mtime bumped after accept):")
    pat_bug = run(compute_patched, "PATCHED", bump, sha_matches=True)
    print("  feature case (sha CHANGED):")
    pat_feat = run(compute_patched, "PATCHED", bump, sha_matches=False)

    print()
    print("=== ASSERTIONS ===")
    # REAL: bug re-queues even when sha unchanged
    a1 = set(real_bug["remaining"]) == set(TASKS)
    print(f"  REAL re-queues landed brief (bug present):                 {a1}")
    # PATCHED bug case: sha unchanged -> tasks KEPT accepted, complete
    a2 = real_bug["state"] != "complete"  # contrast
    a3 = set(pat_bug["remaining"]) == set() and {a['task_id'] for a in pat_bug['accepted']} == set(TASKS) and pat_bug['state'] == 'complete'
    print(f"  PATCHED keeps landed brief accepted+complete (bug fixed):  {a3}")
    # PATCHED feature case: sha changed -> NOT silently complete; plan_stale True
    a4 = pat_feat["plan_stale"] is True and set(pat_feat["accepted"] and [a['task_id'] for a in pat_feat['accepted']]) != set(TASKS)
    # When sha changed, code path sets has_plan False -> state 'unplanned' and tasks
    # are NOT marked accepted (they go to remaining via the guard). Feature intact.
    feature_intact = (pat_feat["plan_stale"] is True) and (set(pat_feat["remaining"]) == set(TASKS)) and ({a['task_id'] for a in pat_feat['accepted']} == set())
    print(f"  PATCHED re-queues SHA-changed brief (feature intact):      {feature_intact}")
    print()
    print(f"  VERDICT 3a implementable & correct: {a3 and feature_intact}")


if __name__ == "__main__":
    main()
