---
interfaces: "extends `compute_epic_status` so it returns 'blocked' for a transitive failed descendant when failure_propagation is enabled"
---

# Title

Read-derived failure propagation in compute_epic_status (flag-gated)

# Scope

Extend the EXISTING compute_epic_status in harness/brief_status.py (item 3 of the epic) so an epic surfaces as `blocked` when a DESCENDANT leaf/child has FAILED — derived purely at READ time from the existing ledger/blocked state that the Phase-1 roll-up already reads. Phase 1 already returns `blocked` when a direct child is blocked/zombie; this child adds transitive descendant-failure propagation on top of that roll-up. Gate the new behavior on config['hierarchical_planning']['failure_propagation']; when off, preserve the existing Phase-1 behavior exactly. Add a small NEW top-level helper if needed (read-derived). IMPLEMENTATION CONSTRAINTS (emit as implementation_notes): land entirely OUTSIDE the _NEVER_AUTO_APPROVE deny-list; do NOT hook orchestrator._mark_blocked and do NOT write ANY new persistence — build only on the existing read-derived roll-up; a BRAND-NEW top-level helper added to harness/brief_status.py must ride as a TRAILING extra node inside an existing symbol's patch block (same patch `code` string, 1-part qualname), NOT a standalone patch entry; do NOT modify existing class methods via partial edit — add NEW top-level functions; keep the verification_command to this child's own oracle plus HERMETIC regression files only (never glob tests/planner/, never network/pip).

# Non-Goals

Do NOT rebuild the Phase-1 compute_epic_status roll-up (it already returns blocked for a blocked/zombie direct child). Do NOT hook orchestrator._mark_blocked or edit any deny-list file. Do NOT add new persistence or any new state file. Do NOT add a new config flag (gate on the existing failure_propagation key). Do NOT touch the symbol ledger, the staging seam, or the planner cli.

# Inputs

harness/brief_status.py — compute_epic_status / compute_brief_status / compute_autowork_eligibility (the read-derived roll-up substrate). The existing blocked/zombie/failed leaf state these helpers already read. harness/config.yaml — hierarchical_planning.failure_propagation flag.

# Deliverables

Extended compute_epic_status in harness/brief_status.py (plus an optional NEW top-level read-derived helper, e.g. epic_has_failed_descendant(...)) that surfaces an epic as `blocked` when a transitive descendant has failed, gated on config['hierarchical_planning']['failure_propagation'] and falling back to exact Phase-1 behavior when off. Plus a NEW HERMETIC oracle test proving: flag on + a failed descendant => epic blocked; flag off => unchanged Phase-1 result; no new files are written. IMPLEMENTATION CONSTRAINTS to emit as implementation_notes: new top-level helper rides as a trailing extra node in an existing symbol's patch block (1-part qualname); no partial edits of class methods; no new persistence; no _mark_blocked hook; stay outside the deny-list; verification_command = this child's own oracle plus hermetic regression files only.
