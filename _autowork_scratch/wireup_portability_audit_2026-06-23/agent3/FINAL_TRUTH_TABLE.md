# Wire-Up Static Floor — Reconciled FP/TP Truth Table @ HEAD fc8167a
# Surface: last 120 JM-self commits, new top-level callables in ALREADY-TRACKED .py files,
# GATE-REAL (excludes test_*.py / *_test.py the gate skips at file level).
# Ground truth = manual call-graph verification (grep), NOT floor-as-oracle.

GATE-EMITTING new callables (120 commits):           35
  TN  reachable@intro & wired (correct silence):     28
  FLAGGED would_be_orphan @intro:                     7
    Of those 7:
      4 = staged-build FP  (wire_up.py primitives, wired in later commit; HEAL at HEAD -> B7 rescues)
      1 = persistent FP    (orchestrator.py::_promote_fallback_candidate; module-alias-attr call; does NOT heal)
      2 = TRUE orphan TP   (agy_pool.py::assert_pool_invariant, effective_pool_size; permanent orphans)

NAIVE intro FP rate           = 5/7  = 71.4%   (4 staged + 1 persistent, of 7 flagged)
POST-B7-RECHECK FP rate       = 1/3  = 33.3%   (staged 4 rescued; persistent 1 remains; vs 3 surviving flags)
  -> the 1 surviving FP is a STATIC-ANALYSIS BLIND SPOT, not a staged build:
     orchestrator.py::_promote_fallback_candidate is called ONLY via
     `orch._promote_fallback_candidate(...)` (module-object alias attribute) in
     orchestrator_worker.py (4 sites). Floor rule (b) requires an explicit
     `from harness.orchestrator import _promote_fallback_candidate`; the alias-attr
     pattern is unresolved => false orphan that NEVER self-heals.

PERMANENT-ORPHAN TP CHECK (the gate's value):
  agy_pool.py::assert_pool_invariant   -> FLAGGED (TP) PASS
  agy_pool.py::effective_pool_size     -> FLAGGED (TP) PASS
  diff_fuzzer.py::_one_sided_fuzz      -> not in 120-commit window (predates); spot-check below
  diff_fuzzer.py::_capture_golden      -> not in 120-commit window (predates); spot-check below
