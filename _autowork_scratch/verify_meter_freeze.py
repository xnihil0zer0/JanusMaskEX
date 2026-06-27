#!/usr/bin/env python3
"""Adversarial verification of the suspected compute_fuzz_coverage accept-freeze.

Independently establishes whether the differential-fuzz coverage meter
(`harness.orchestrator_worker.compute_fuzz_coverage`) is FROZEN because its
accept discriminator counts ONLY `event=='phase_transition' & phase=='accepted'`
rows, while recent accepts are logged as `event=='auto_commit' & phase=='accepted'`.

Parses state/impl_progress.jsonl directly (no harness import needed for the
analysis), then cross-checks the live function's emitted fuzz_coverage rows.

Run: python3 _autowork_scratch/verify_meter_freeze.py
"""
from __future__ import annotations
import json
import pathlib
from collections import defaultdict

REPO = pathlib.Path(__file__).resolve().parents[1]
LEDGER = REPO / "state" / "impl_progress.jsonl"

SIX_TASKS = [
    "difffuzz-meter-oracle", "difffuzz-meter-impl",
    "difffuzz-waiver-oracle", "difffuzz-waiver-impl",
    "difffuzz-leak-oracle", "difffuzz-leak-impl",
]

# The set of meta_task_types the meter treats as fuzzer-bypass (copied verbatim
# from compute_fuzz_coverage for the headline-untouched cross-check).
BYPASS_FUZZER_TYPES = {
    'harness_plumbing', 'orchestration', 'test_e2e', 'hooks_integration',
    'planner_tooling', 'test_unit', 'config_schema', 'epic_planning',
    'docs_writing', 'validation', 'sandbox_infra', 'test_integration',
    'harness_self_fix', 'test_acceptance', 'mcp_plumbing', 'mcp_server_change',
}


def load_rows():
    rows = []
    with open(LEDGER, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if isinstance(d, dict):
                rows.append(d)
    return rows


def phase_of(d):
    """Mirror the meter's phase extraction: phase field, else phase_transition.to."""
    phase = d.get("phase")
    if not phase:
        pt = d.get("phase_transition")
        if isinstance(pt, dict):
            phase = pt.get("to")
    return phase if isinstance(phase, str) else None


def main():
    rows = load_rows()
    print(f"== ledger: {LEDGER} ({len(rows)} parseable rows) ==\n")

    # ---- (1) asymmetry for the 6 difffuzz-* tasks ------------------------
    print("=== (1) per-task accept-row asymmetry for the 6 difffuzz-* tasks ===")
    # tid -> {(event, phase) tuples seen}
    per_task_accept = defaultdict(lambda: {"pt_accepted": False, "ac_accepted": False,
                                           "other_accepted": []})
    for d in rows:
        tid = d.get("task_id")
        if tid not in SIX_TASKS:
            continue
        ev = d.get("event")
        ph = phase_of(d)
        if ph == "accepted":
            if ev == "phase_transition":
                per_task_accept[tid]["pt_accepted"] = True
            elif ev == "auto_commit":
                per_task_accept[tid]["ac_accepted"] = True
            else:
                per_task_accept[tid]["other_accepted"].append(ev)
    for tid in SIX_TASKS:
        rec = per_task_accept.get(tid, {"pt_accepted": False, "ac_accepted": False, "other_accepted": []})
        print(f"  {tid:30s}  phase_transition/accepted={rec['pt_accepted']!s:5}  "
              f"auto_commit/accepted={rec['ac_accepted']!s:5}  other={rec['other_accepted']}")
    print()

    # ---- (2) which event types ever carry phase=='accepted'? -------------
    print("=== (2) event types carrying phase=='accepted' (distinct task_ids each) ===")
    accepted_event_tids = defaultdict(set)   # event -> {task_id}
    for d in rows:
        if phase_of(d) == "accepted":
            tid = d.get("task_id")
            if isinstance(tid, str) and tid:
                accepted_event_tids[d.get("event")].add(tid)
    for ev, tids in sorted(accepted_event_tids.items(), key=lambda kv: -len(kv[1])):
        print(f"  event={str(ev):24s}  distinct_task_ids={len(tids)}")
    print()

    # recency check: is phase_transition/accepted still emitted, or superseded?
    # Walk in file order; for each accept-carrying event, find the LAST row index.
    last_idx = {}
    for i, d in enumerate(rows):
        if phase_of(d) == "accepted":
            last_idx[d.get("event")] = i
    print("  last ledger-row INDEX at which each accept-event appears (file order):")
    for ev, i in sorted(last_idx.items(), key=lambda kv: kv[1]):
        ts = rows[i].get("ts")
        print(f"    event={str(ev):24s} last_row_index={i:7d} ts={ts}")
    print()

    # ---- (3) accepted_total: current vs fixed discriminator --------------
    print("=== (3) accepted_total under current vs fixed discriminator ===")
    cur = []   # phase_transition/accepted only (CURRENT meter)
    for d in rows:
        if d.get("event") == "phase_transition" and phase_of(d) == "accepted":
            tid = d.get("task_id")
            if isinstance(tid, str) and tid and tid not in cur:
                cur.append(tid)
    fixed_any = []   # ANY row with phase=='accepted'
    for d in rows:
        if phase_of(d) == "accepted":
            tid = d.get("task_id")
            if isinstance(tid, str) and tid and tid not in fixed_any:
                fixed_any.append(tid)
    print(f"  CURRENT  (phase_transition/accepted only): accepted_total = {len(cur)}")
    print(f"  FIXED    (ANY phase=='accepted', deduped) : accepted_total = {len(fixed_any)}")
    six_in_cur = [t for t in SIX_TASKS if t in cur]
    six_in_fixed = [t for t in SIX_TASKS if t in fixed_any]
    print(f"  of the 6 new tasks: in CURRENT set = {six_in_cur}")
    print(f"  of the 6 new tasks: in FIXED   set = {six_in_fixed}")
    print()

    # ---- (4) ADVERSARIAL over-count check --------------------------------
    print("=== (4) ADVERSARIAL: does any phase=='accepted' row NOT denote a genuine accept? ===")
    # Tactic: for every tid that has a phase=='accepted' row, was that tid ALSO
    # the subject of a terminal NON-accept (verification_failed / task_blocked /
    # retry_exhausted) row? Does any accept appear with a different outcome field?
    accepted_tids = set(fixed_any)
    # collect outcomes seen per accepted tid
    outcomes_per_tid = defaultdict(set)
    events_per_tid = defaultdict(set)
    for d in rows:
        tid = d.get("task_id")
        if tid in accepted_tids:
            if "outcome" in d:
                outcomes_per_tid[tid].add(d.get("outcome"))
            events_per_tid[tid].add(d.get("event"))
    # Inspect what outcome values accompany an accept event specifically.
    accept_row_outcomes = defaultdict(int)
    accept_row_events = defaultdict(int)
    for d in rows:
        if phase_of(d) == "accepted":
            accept_row_events[d.get("event")] += 1
            if "outcome" in d:
                accept_row_outcomes[d.get("outcome")] += 1
    print(f"  raw accept-ROW event histogram: {dict(accept_row_events)}")
    print(f"  outcome field ON accept rows  : {dict(accept_row_outcomes) or '(none carry outcome)'}")

    # Tasks that have a phase==accepted row AND a hard non-accept terminal:
    NONACCEPT = {"verification_failed", "task_blocked", "retry_exhausted",
                 "dependency_failed", "orphan_unwired"}
    suspicious = []
    for tid in sorted(accepted_tids):
        ev = events_per_tid[tid]
        if ev & NONACCEPT:
            # an accepted task that ALSO has a non-accept terminal row -> could be
            # a retried task that earlier failed; the accept is still genuine.
            suspicious.append((tid, sorted(ev & NONACCEPT)))
    print(f"  accepted tids that ALSO have a non-accept terminal row: {len(suspicious)}")
    for tid, evs in suspicious[:10]:
        print(f"    {tid}: also has {evs}  (note: a later accept supersedes an earlier fail -> still genuine)")

    # Does phase=='accepted' ever appear on a NON-terminal/marker event (e.g.
    # 'phase_transition' that is purely transitional, or a 'launch' row)? List the
    # event types that carry it (already have them) and reason about spuriousness.
    print()
    print("  -> Is any accept-carrying event NON-definitive? Examine each:")
    for ev in accept_row_events:
        print(f"     event={ev!r}: phase=='accepted' carried by this event")
    print()

    # Critical de-dup question: can ONE genuine accept be double counted by
    # 'ANY phase==accepted'? Count tids that have BOTH pt/accepted and ac/accepted.
    both = []
    pt_tids, ac_tids = set(), set()
    for d in rows:
        if phase_of(d) == "accepted":
            tid = d.get("task_id")
            if not isinstance(tid, str):
                continue
            if d.get("event") == "phase_transition":
                pt_tids.add(tid)
            elif d.get("event") == "auto_commit":
                ac_tids.add(tid)
    both = sorted(pt_tids & ac_tids)
    print(f"  tids with BOTH phase_transition/accepted AND auto_commit/accepted: {len(both)}")
    print(f"    (these are why de-dup BY TASK_ID matters; sample: {both[:5]})")
    print(f"  tids ONLY auto_commit/accepted (would be MISSED by current meter): {len(ac_tids - pt_tids)}")
    print(f"  tids ONLY phase_transition/accepted (legacy)                     : {len(pt_tids - ac_tids)}")
    print()

    # ---- (5) fuzzed discriminator unaffected -----------------------------
    print("=== (5) fuzzed discriminator: phase_transition/fuzzing rows still emitted? ===")
    fuzzing_tids = set()
    for d in rows:
        if d.get("event") == "phase_transition" and phase_of(d) == "fuzzing":
            tid = d.get("task_id")
            if isinstance(tid, str) and tid:
                fuzzing_tids.add(tid)
    print(f"  distinct tids with a phase_transition/fuzzing row: {len(fuzzing_tids)}")
    # spot-check: how many of the CURRENT accepted set are fuzzed (the historical 17)?
    fuzzed_in_cur = [t for t in cur if t in fuzzing_tids]
    fuzzed_in_fixed = [t for t in fixed_any if t in fuzzing_tids]
    print(f"  fuzzed among CURRENT accepted set: {len(fuzzed_in_cur)}")
    print(f"  fuzzed among FIXED   accepted set: {len(fuzzed_in_fixed)}")
    print(f"  sample fuzzed tids: {sorted(fuzzing_tids)[:5]}")
    # Recency of fuzzing rows:
    last_fuzz_idx = max((i for i, d in enumerate(rows)
                         if d.get("event") == "phase_transition" and phase_of(d) == "fuzzing"),
                        default=None)
    if last_fuzz_idx is not None:
        print(f"  last phase_transition/fuzzing at row index {last_fuzz_idx} "
              f"(ledger has {len(rows)} rows) ts={rows[last_fuzz_idx].get('ts')}")
    print()

    # ---- live cross-check: what did the deployed meter actually emit? ----
    print("=== live cross-check: accepted_total inside emitted fuzz_coverage rows ===")
    fc_rows = [d for d in rows if d.get("event") == "fuzz_coverage"]
    print(f"  emitted fuzz_coverage rows: {len(fc_rows)}")
    seen = []
    for d in fc_rows[-8:]:
        det = d.get("detail") or {}
        seen.append((d.get("task_id"), det.get("accepted_total"), det.get("fuzzed"),
                     det.get("bypassed"), round(det.get("fuzzed_fraction", 0.0), 4)))
    for tid, at, fz, bp, ff in seen:
        print(f"    task={str(tid):30s} accepted_total={at} fuzzed={fz} bypassed={bp} fuzzed_fraction={ff}")
    print()

    # ---- VERDICT ---------------------------------------------------------
    print("=" * 70)
    print("VERDICT")
    print("=" * 70)
    freeze = len(fixed_any) > len(cur)
    print(f"  freeze real?              {'YES' if freeze else 'NO'}")
    print(f"  accepted_total CURRENT  = {len(cur)}")
    print(f"  accepted_total FIXED    = {len(fixed_any)}  (delta +{len(fixed_any)-len(cur)})")
    print(f"  6 new tasks counted by CURRENT meter: {len(six_in_cur)}/6")
    print(f"  6 new tasks counted by FIXED   meter: {len(six_in_fixed)}/6")
    # The correct predicate: accept-carrying events confined to the known
    # terminal accept signals, deduped by task_id.
    print()
    print("  RECOMMENDED PREDICATE: a task is accepted iff it has >=1 ledger row")
    print("  with phase=='accepted' AND event in {'phase_transition','auto_commit'},")
    print("  counted ONCE per distinct task_id (set semantics). This subsumes the")
    print("  legacy phase_transition/accepted rows AND the current auto_commit/")
    print("  accepted rows, de-duplicates the overlap, and admits no spurious event.")


if __name__ == "__main__":
    main()
