---
interfaces: "calls `check_brief_depth(slug, repo_root, max_depth) -> bool` in harness/planner/cli.py main and gates recursion on config['hierarchical_planning']['max_planner_depth']"
---

# Title

Planner-time depth budget gate + arbitrary-depth epic recursion in cli.py

# Scope

Items 4 and 5 of the epic, combined because both live in harness/planner/cli.py and recursion is bounded BY the depth budget. (4) In harness/planner/cli.py `main`, AFTER the brief loads and BEFORE any pipeline runs, call the already-implemented `check_brief_depth(slug, repo_root, max_depth)` from harness/depth_validator.py using config['hierarchical_planning']['max_planner_depth']; refuse to plan a brief whose epic lineage exceeds the budget by exiting non-zero. (5) Allow a child brief that is itself an epic (epic: true) to be re-decomposed by the normal pipeline rather than treated as a leaf — the Phase-1 _run_epic_pipeline already writes child brief_hooks_<slug>.md files and the daemon re-plans each, so ensure a nested epic child reaches the epic pipeline (via _should_run_epic) and that the depth gate from (4) prevents unbounded recursion. IMPLEMENTATION CONSTRAINTS (emit as implementation_notes): land entirely OUTSIDE the _NEVER_AUTO_APPROVE deny-list (do NOT edit harness/autowork_daemon.py or harness/orchestrator.py); do NOT rebuild check_brief_depth or _run_epic_pipeline (Phase-1); any BRAND-NEW top-level helper added to harness/planner/cli.py must ride as a TRAILING extra node inside an existing symbol's patch block (same patch `code` string, 1-part qualname), NOT a standalone entry; do NOT modify existing class methods via partial edit — add NEW top-level functions; keep the verification_command to this child's own oracle plus HERMETIC regression files only (never glob tests/planner/, never include rebuild dry-runs or anything that pip-installs / touches the network).

# Non-Goals

Do NOT re-implement check_brief_depth (already in harness/depth_validator.py) or _run_epic_pipeline (Phase-1). Do NOT edit harness/autowork_daemon.py or any other deny-list file. Do NOT add a new config flag (use the existing max_planner_depth key). Do NOT implement child-plan garbage collection (deferred). Do NOT touch the symbol ledger, the staging seam, or brief_status failure propagation.

# Inputs

harness/depth_validator.py — `check_brief_depth(slug, repo_root, max_depth)` (already implemented). harness/planner/cli.py — main, _run_epic_pipeline, _should_run_epic. harness/config.yaml — hierarchical_planning.max_planner_depth (4) and enabled.

# Deliverables

harness/planner/cli.py `main` now calls `check_brief_depth(slug, repo_root, max_depth)` after the brief loads and before any pipeline runs, using config['hierarchical_planning']['max_planner_depth'], and exits non-zero when the epic lineage exceeds the budget; and a nested epic child (epic: true) is routed into the epic decomposition pipeline (not treated as a leaf), bounded by that same depth gate. Plus a NEW HERMETIC oracle test proving: a brief at/below budget plans normally; a brief beyond budget is refused with non-zero exit; an epic-flagged child is decomposed rather than treated as a leaf. IMPLEMENTATION CONSTRAINTS to emit as implementation_notes: new top-level helpers ride as trailing extra nodes in an existing symbol's patch block (1-part qualname); no partial edits of class methods; stay outside the deny-list; verification_command = this child's own oracle plus hermetic regression files only (no tests/planner/ glob, no network/pip, no rebuild dry-runs).
