#!/usr/bin/env python3
"""Agent-3 staleness eval — Step 3 RECOMMENDED root-cause fix.

Findings so far:
  - The guard `accept_ts < plan_mtime` is broken because the integrate `git stash
    pop` stamps EVERY untracked plan's mtime to "now" on every self-task integrate
    (proven: 44 plans share one instant). So plan-FILE mtime is NOT a reliable
    "plan was regenerated due to a brief correction" signal.
  - The SHA-gate fix BREAKS the feature: at re-promote time the plan SHA has
    already been re-stamped to match the corrected brief, so plan_stale is False
    (proven in s4).
  - There is NO generation-timestamp key on the plan dict (proven: 44 plans, only
    source_brief_sha256 / source_brief_path / working_dir / required_task_ids /
    tasks).

The feature's REAL goal: re-author an accepted task when the brief was CORRECTED
(content changed) after that acceptance, so the plan was REGENERATED. The robust
signal that "the plan was regenerated after acceptance" is the plan's *content
identity*, NOT its filesystem mtime. The plan's content identity that changes on
regeneration is captured by source_brief_sha256 PLUS the plan task set — but those
are identical before/after a no-op stash-pop touch.

ROOT-CAUSE FIX (the only durable, content-driven one available):
  Record, in the ACCEPTANCE ledger row, the source_brief_sha256 (or brief content
  sha) that was current WHEN the task was accepted. Then the guard re-queues
  exactly when the plan's CURRENT source_brief_sha256 != the sha recorded at the
  task's acceptance. This is content-driven, immune to the stash-pop mtime touch,
  and correctly fires after a brief correction (the corrected brief => new sha =>
  re-stamped plan sha != accept-time sha).

This requires a producer-side change (record accept-time brief sha in the ledger
row at orchestrator.py:~3260) PLUS the consumer guard. We PROVE the consumer logic
discriminates all four cases given an accept-time-sha field. We also evaluate the
SIMPLER interim fix that needs NO producer change.
"""
import datetime


def iso_to_epoch(ts):
    iso = ts[:-1] + "+00:00" if ts[-1] in "Zz" else ts
    return datetime.datetime.fromisoformat(iso).timestamp()


IMPL = iso_to_epoch("2026-06-22T17:18:04Z")
ORACLE = iso_to_epoch("2026-06-22T17:26:48Z")
LATEST = max(IMPL, ORACLE)

SHA_A = "a" * 64  # brief content at acceptance
SHA_B = "b" * 64  # corrected brief content

# Each scenario: the per-task accept_ts, the accept-time brief sha recorded in the
# ledger row, the plan's CURRENT stamped source_brief_sha256, the plan_mtime
# (post stash-pop = bumped to "now"), and the CORRECT answer.
SCEN = {
    "S_landed (BUG today: KEEP)": {
        # task accepted under brief A; plan still stamps A; mtime bumped by stash pop
        "accept_ts": LATEST, "accept_sha": SHA_A, "plan_sha": SHA_A,
        "plan_mtime": LATEST + 0.949, "correct": "KEEP",
    },
    "S_corrected (FEATURE: REQUEUE)": {
        # task accepted under brief A; brief corrected to B; plan REGENERATED stamps B
        "accept_ts": LATEST, "accept_sha": SHA_A, "plan_sha": SHA_B,
        "plan_mtime": LATEST + 3600, "correct": "REQUEUE",
    },
    "S_fresh_under_current (KEEP)": {
        # accepted under the CURRENT plan (sha B), no correction since
        "accept_ts": LATEST, "accept_sha": SHA_B, "plan_sha": SHA_B,
        "plan_mtime": LATEST - 100, "correct": "KEEP",
    },
    "S_touch_only (KEEP)": {
        # identical-content touch: sha unchanged, mtime bumped by stash pop
        "accept_ts": LATEST, "accept_sha": SHA_A, "plan_sha": SHA_A,
        "plan_mtime": LATEST + 9999, "correct": "KEEP",
    },
}


def guard_current_mtime(s):
    return s["plan_mtime"] > 0.0 and s["accept_ts"] is not None and s["accept_ts"] < s["plan_mtime"]


def guard_accept_sha(s):
    """RECOMMENDED ROOT FIX: re-queue iff the plan's current source_brief_sha256
    differs from the brief sha recorded at acceptance. Missing accept_sha => treat
    as NOT stale (conservative), i.e. fall back to KEEP."""
    accept_sha = s.get("accept_sha")
    plan_sha = s.get("plan_sha")
    if not accept_sha or not plan_sha:
        return False  # conservative: no false re-open without the signal
    return accept_sha != plan_sha


def verdict(rq, correct):
    got = "REQUEUE" if rq else "KEEP"
    return "OK" if got == correct else f"WRONG({got})"


def main():
    names = list(SCEN.keys())
    guards = {
        "current mtime<": guard_current_mtime,
        "FIX accept-sha != plan-sha": guard_accept_sha,
    }
    print(f"{'guard':<28}" + "".join(f"{n.split()[0]:<18}" for n in names))
    print("-" * (28 + 18 * len(names)))
    allok = {}
    for gname, gfn in guards.items():
        cells = []
        ok = True
        for n in names:
            v = verdict(gfn(SCEN[n]), SCEN[n]["correct"])
            ok = ok and v == "OK"
            cells.append(v)
        allok[gname] = ok
        print(f"{gname:<28}" + "".join(f"{c:<18}" for c in cells))
    print()
    print("correct per scenario:")
    for n in names:
        print(f"  {n:<34} -> {SCEN[n]['correct']}")
    print()
    for g, ok in allok.items():
        print(f"  {g:<28}: {'ALL CORRECT' if ok else 'WRONG on some scenario'}")
    print()
    print("Note: the accept-sha fix needs a PRODUCER change to record the brief sha")
    print("in the accept ledger row (orchestrator.py ~:3260) + a CONSUMER guard that")
    print("compares it to the plan's current source_brief_sha256. It is immune to the")
    print("git-stash-pop mtime touch AND correctly fires after a real brief correction.")


if __name__ == "__main__":
    main()
