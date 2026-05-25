"""META-PHASE3-TEST-ALIGN scope_exception sentinel (2026-05-18, session #7).

Authorizes META-side test edits to align with two harness landings from
session #6 (Phase 3):

* R02H2a (3c07562) — `harness.planner.blind_draft.collect_agent_draft`
  gained a `min_response_seconds=10.0` gate. Tests pre-creating draft
  files with current-time mtime now hit the suspect_hallucination branch
  because spawn_start_epoch is captured AFTER the test wrote the file.
  Fix pattern: set future mtime (now + 60s) on the planted draft so the
  threshold check sees latency ≫ 10s.

* R01H4 (4400ba3) — `harness.planner.reconciliation.run_reconciliation`
  now routes both-silent items to `unresolved_items` with a
  `both_agents_silent` ledger row, replacing the prior silent-concede /
  claude-fallback merge. One pinned test codified the OLD behavior and
  must be flipped to assert the loud-fail contract.

Two source-pin tests in `tests/adversarial/test_planning_outbox_fallback_adversarial.py`
(`test_collect_agent_draft_canonical_first_outbox_last` and
`test_reconciliation_downgrades_phantom_defend`) also need quote-agnostic
regexes — the underlying invariants still hold, but R01H3/R01H4 whole-file
submissions reformatted the source from double to single quotes (cosmetic
diff noise tracked separately).

Touched files:
- tests/planner/test_blind_draft.py            (4 threshold-affected tests)
- tests/adversarial/test_P4_planner_flow_attacks.py
    (3 threshold + 1 silence-semantic; in tests/adversarial/** allow-list
     already, but tracked here for one-stop drain audit)
- tests/adversarial/test_planning_outbox_fallback_adversarial.py
    (2 source-pin tests; in tests/adversarial/** allow-list)

The first path needs scope_exception because tests/planner/ is not in
the META allow-list. Operator: kevin.lindmark0@gmail.com.
"""
