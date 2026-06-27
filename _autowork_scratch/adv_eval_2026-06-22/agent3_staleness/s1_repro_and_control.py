#!/usr/bin/env python3
"""Agent-3 staleness eval — Step 2(a)/(b).

Calls the REAL harness.brief_status.compute_brief_status against a SYNTHETIC
brief + plan + ledger in a tmp dir. Proves:
  (a) BUG: plan-file mtime set JUST AFTER both accept timestamps => both tasks
      land in `remaining` (re-queued) and the brief is NOT classified complete.
  (b) CONTROL: same scenario but plan mtime set BEFORE the accept timestamps
      => brief classifies `complete`. Shows the mtime is the trigger.

Read-only on live state; writes only inside its own tmp dir.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path("/home/xnihil0zer0/JanusMaskJR")
sys.path.insert(0, str(REPO))
from harness.brief_status import compute_brief_status  # noqa: E402

SLUG = "synthslug"
TASKS = ["synth-impl", "synth-oracle"]
# Accept timestamps as ISO-Z (exactly like the real ledger rows).
ACCEPT_ISO = {
    "synth-impl": "2026-06-22T17:18:04Z",
    "synth-oracle": "2026-06-22T17:26:48Z",
}
# epoch equivalents (Z => UTC). Both normalize via .timestamp().
import datetime  # noqa: E402


def iso_to_epoch(ts):
    iso = ts[:-1] + "+00:00" if ts[-1] in "Zz" else ts
    return datetime.datetime.fromisoformat(iso).timestamp()


def build_fixture(root: Path, plan_mtime: float):
    repo_root = root / "repo"
    state_dir = root / "state"
    (repo_root).mkdir(parents=True, exist_ok=True)
    (state_dir).mkdir(parents=True, exist_ok=True)

    # brief file
    brief = repo_root / f"brief_hooks_{SLUG}.md"
    brief.write_text("# synthetic brief\nbody\n", encoding="utf-8")
    brief_sha = __import__("hashlib").sha256(brief.read_bytes()).hexdigest()

    # plan file — stamp the CORRECT source_brief_sha256 so plan_stale is False
    plan = repo_root / f"plan_hooks_{SLUG}.json"
    plan.write_text(
        json.dumps(
            {
                "source_brief_sha256": brief_sha,
                "tasks": [{"task_id": t} for t in TASKS],
            }
        ),
        encoding="utf-8",
    )

    # ledger with auto_commit accepted rows for both tasks
    ledger = state_dir / "impl_progress.jsonl"
    with open(ledger, "w", encoding="utf-8") as f:
        for t in TASKS:
            f.write(
                json.dumps(
                    {
                        "ts": ACCEPT_ISO[t],
                        "phase": "accepted",
                        "event": "auto_commit",
                        "task_id": t,
                        "commit_sha": "deadbeef",
                    }
                )
                + "\n"
            )

    # set plan file mtime as requested (atime, mtime)
    os.utime(plan, (plan_mtime, plan_mtime))
    return repo_root, state_dir, plan, brief_sha


def run_case(label: str, plan_mtime: float):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        repo_root, state_dir, plan, brief_sha = build_fixture(root, plan_mtime)
        recs = compute_brief_status(repo_root, state_dir)
        rec = next((r for r in recs if r["slug"] == SLUG), None)
        print(f"--- {label} ---")
        print(f"  plan_mtime set to        : {plan_mtime}  ({datetime.datetime.fromtimestamp(plan_mtime).isoformat()} local)")
        print(f"  accept epoch impl/oracle : {iso_to_epoch(ACCEPT_ISO['synth-impl'])} / {iso_to_epoch(ACCEPT_ISO['synth-oracle'])}")
        assert rec is not None, "record missing"
        print(f"  state        = {rec['state']}")
        print(f"  plan_stale   = {rec['plan_stale']}")
        print(f"  has_plan     = {rec['has_plan']}")
        print(f"  accepted     = {[a['task_id'] for a in rec['accepted']]}")
        print(f"  remaining    = {rec['remaining']}")
        return rec


def main():
    impl_e = iso_to_epoch(ACCEPT_ISO["synth-impl"])
    oracle_e = iso_to_epoch(ACCEPT_ISO["synth-oracle"])
    latest_accept = max(impl_e, oracle_e)

    # (a) BUG: plan mtime JUST AFTER the latest accept (mirrors the real 0.949s gap)
    bug = run_case("(a) BUG repro — plan mtime 0.949s AFTER latest accept", latest_accept + 0.949)
    print()
    # (b) CONTROL: plan mtime BEFORE both accepts
    ctrl = run_case("(b) CONTROL — plan mtime 10s BEFORE earliest accept", min(impl_e, oracle_e) - 10.0)
    print()

    print("=== ASSERTIONS ===")
    bug_ok = bug["state"] != "complete" and set(bug["remaining"]) == set(TASKS) and bug["plan_stale"] is False
    ctrl_ok = ctrl["state"] == "complete" and ctrl["remaining"] == []
    print(f"  (a) bug reproduced (both re-queued, NOT complete, plan_stale False): {bug_ok}")
    print(f"  (b) control complete (no re-queue):                                  {ctrl_ok}")
    print(f"  VERDICT 2a/2b: {'CONFIRMED' if bug_ok and ctrl_ok else 'NOT CONFIRMED'}")


if __name__ == "__main__":
    main()
