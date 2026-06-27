#!/usr/bin/env python3
"""Agent-3 staleness eval — Step 3: adversarially evaluate the proposed fixes.

We re-implement the candidate accept-staleness GUARD logics as standalone
predicates and drive each against four scenarios. The current source guard is:

    if plan_mtime > 0.0 and accept_ts is not None and accept_ts < plan_mtime:
        remaining.append(tid)        # re-queue (stale)
    else:
        accepted_for_brief.append(...)  # keep accepted

We ask of each candidate guard, for each scenario: does it RE-QUEUE (True) or
KEEP-ACCEPTED (False)?

Scenarios:
  S_landed      : landed multi-task brief — plan mtime bumped 0.949s AFTER the
                  latest accept, brief SHA UNCHANGED. CORRECT answer = KEEP (do
                  not re-queue). This is the bug case.
  S_edited      : brief genuinely re-saved/edited AFTER acceptance => brief SHA
                  CHANGED, and (because the brief was edited then re-planned) the
                  plan mtime is also after the accept. CORRECT answer = RE-QUEUE
                  (feature's legitimate purpose: stale accept must be redone).
  S_old_accept  : a truly old accept far before any plan activity, SHA unchanged.
                  Both signals agree it's fresh. CORRECT = KEEP.
  S_pre_accept  : accept clearly BEFORE the plan (e.g. accepted, then brief
                  re-planned later with SHA change). CORRECT = RE-QUEUE.

We discriminate the BUG case (S_landed) from the FEATURE case (S_edited): a good
fix KEEPs S_landed but RE-QUEUEs S_edited.
"""
import datetime


def iso_to_epoch(ts):
    iso = ts[:-1] + "+00:00" if ts[-1] in "Zz" else ts
    return datetime.datetime.fromisoformat(iso).timestamp()


IMPL = iso_to_epoch("2026-06-22T17:18:04Z")
ORACLE = iso_to_epoch("2026-06-22T17:26:48Z")
LATEST = max(IMPL, ORACLE)

# Each scenario provides the per-task accept_ts plus the contextual signals a
# guard could consult: plan_mtime, brief_sha_changed (did current brief sha differ
# from the plan's stamped source_brief_sha256), brief_mtime.
SCENARIOS = {
    # bug: mtime bumped just after accept, sha UNCHANGED
    "S_landed (BUG: keep)": {
        "accept_ts": LATEST,                 # the oracle, latest accept
        "plan_mtime": LATEST + 0.949,
        "brief_sha_changed": False,
        "brief_mtime": LATEST + 0.897,       # brief touched too (archive co-touch)
        "correct": "KEEP",
    },
    # feature: brief edited after accept => sha changed, replanned later
    "S_edited (FEATURE: requeue)": {
        "accept_ts": LATEST,
        "plan_mtime": LATEST + 3600,          # re-planned an hour later
        "brief_sha_changed": True,
        "brief_mtime": LATEST + 1800,         # brief edited 30 min after accept
        "correct": "REQUEUE",
    },
    "S_old_accept (keep)": {
        "accept_ts": LATEST,
        "plan_mtime": LATEST - 5000,          # plan made long before accept
        "brief_sha_changed": False,
        "brief_mtime": LATEST - 6000,
        "correct": "KEEP",
    },
    "S_pre_accept (requeue)": {
        "accept_ts": IMPL,                    # older accept
        "plan_mtime": LATEST + 7200,          # replanned 2h after, sha changed
        "brief_sha_changed": True,
        "brief_mtime": LATEST + 7000,
        "correct": "REQUEUE",
    },
}


# ---- candidate guards: return True if RE-QUEUE (treated stale) ----

def guard_current(s):
    """CURRENT source logic: raw plan-file mtime."""
    pm, at = s["plan_mtime"], s["accept_ts"]
    return pm > 0.0 and at is not None and at < pm


def guard_sha(s):
    """PROPOSED FIX (3a): gate on brief_sha_changed instead of mtime."""
    # only re-queue when the brief SHA actually changed
    return bool(s["brief_sha_changed"])


def guard_sha_and_mtime(s):
    """FIX variant: re-queue only when SHA changed AND accept precedes plan."""
    pm, at = s["plan_mtime"], s["accept_ts"]
    return bool(s["brief_sha_changed"]) and (pm > 0.0 and at is not None and at < pm)


def guard_brief_mtime(s):
    """ALTERNATIVE (3b-i): compare accept_ts against the BRIEF mtime, not the
    bumped plan-file mtime. Rationale: the brief is the human artifact; if the
    brief was edited after the accept, redo. A mere plan re-serialization at
    integrate does not move the brief mtime... UNLESS archive co-touches it."""
    bm, at = s["brief_mtime"], s["accept_ts"]
    return bm > 0.0 and at is not None and at < bm


def guard_ge(s):
    """ALTERNATIVE (3b-ii): flip strict < to <= ... (does NOT help; shown for
    completeness). Re-queue when accept_ts <= plan_mtime."""
    pm, at = s["plan_mtime"], s["accept_ts"]
    return pm > 0.0 and at is not None and at <= pm


GUARDS = {
    "current (mtime<)": guard_current,
    "FIX-3a sha-only": guard_sha,
    "FIX sha&mtime": guard_sha_and_mtime,
    "ALT brief-mtime": guard_brief_mtime,
    "ALT >= flip": guard_ge,
}


def verdict(requeue: bool, correct: str) -> str:
    got = "REQUEUE" if requeue else "KEEP"
    return "OK" if got == correct else f"WRONG(got {got})"


def main():
    names = list(SCENARIOS.keys())
    print(f"{'guard':<18}" + "".join(f"{n.split()[0]:<14}" for n in names))
    print("-" * (18 + 14 * len(names)))
    summary = {}
    for gname, gfn in GUARDS.items():
        cells = []
        all_ok = True
        for n in names:
            s = SCENARIOS[n]
            rq = gfn(s)
            v = verdict(rq, s["correct"])
            if not v.startswith("OK"):
                all_ok = False
            cells.append(("REQ" if rq else "keep") + "/" + ("ok" if v == "OK" else "X"))
        summary[gname] = all_ok
        print(f"{gname:<18}" + "".join(f"{c:<14}" for c in cells))
    print()
    print("=== correct answers per scenario ===")
    for n in names:
        print(f"  {n:<30} -> {SCENARIOS[n]['correct']}")
    print()
    print("=== which guards discriminate BUG(keep) from FEATURE(requeue) on all 4 scenarios ===")
    for gname, ok in summary.items():
        print(f"  {gname:<18}: {'ALL CORRECT' if ok else 'has a wrong cell'}")


if __name__ == "__main__":
    main()
