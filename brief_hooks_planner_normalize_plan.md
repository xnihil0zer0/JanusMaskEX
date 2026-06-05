---
interfaces: "adds `harness/planner/plan_normalizer.py` exposing `normalize_plan(plan: dict) -> dict`; wires it into `harness/planner/cli.py` main() before persist_plan"
---

# Title

Deterministically normalize merged leaf plans so the daemon's auto-planned child plans are EXECUTABLE with zero operator vetting (dedupe oracles + module-first deps)

# Scope

For fully-hands-off autowork, the daemon auto-plans each child brief and must get an executable plan WITHOUT human vetting. Empirically (symbol_ledger, 2026-06-05) the live 2-agent merge produced two defects that deadlock execution: (1) a DUPLICATE test_authoring oracle — claude proposed `symbol-ledger-oracle` and gemini `oracle-symbol-ledger`, both with mutation_target=harness.symbol_ledger, and the merge kept BOTH (one orphaned); (2) the impl/oracle dependency was INVERTED (impl depended on the oracle, "oracle-first"), but the auto-commit non-vacuity mutation gate REQUIRES the target module to already EXIST in the staging worktree when a test_authoring oracle is verified (it applies the mutant to mutation_target and reruns the test). So an oracle-first ordering makes the oracle un-acceptable -> retried -> .exhausted -> A3 terminally blocks the impl -> the child never completes.

Add a pure deterministic normalizer that runs on the merged plan before it is persisted/staged, so ANY merge (or single-agent draft) is auto-corrected:

* DEDUPE ORACLES: group test_authoring tasks by mutation_target (bare dotted module). For a group with >1, KEEP one (prefer the oracle whose test file path is referenced by the verification_command of the module's impl task, else the first by task_id) and DROP the rest; rewrite every `dependencies` reference to a dropped id to the kept id; never leave a dangling dep.
* ENFORCE MODULE-FIRST: for each surviving test_authoring task O with mutation_target M (module file = M with dots->slashes + '.py'), find the impl task I whose files_touched contains that module file. If found: ensure O.dependencies includes I.task_id, and REMOVE O.task_id from I.dependencies (break the inversion). If the flip would create a cycle, drop the offending edge from I (the oracle is the dependent). If no impl task creates M, leave O as-is (it depends on a pre-existing module).

The normalizer MUST be idempotent (running twice == once), pure (no I/O), and a no-op for already-correct plans. It MUST preserve all task fields it does not touch and keep validate_plan(normalized) violation-free whenever the input was field-complete.

# Non-Goals

Do NOT change the planning prompt or the agents' drafting (the normalizer is the deterministic backstop). Do NOT touch the deny-list / gate code. Do NOT alter epic decomposition (this is leaf-plan only). Do NOT drop a test_authoring task that is the ONLY oracle for its module. Do NOT reorder or renumber unrelated tasks. Do NOT add config flags.

# Inputs

harness/planner/cli.py:240-249 (main(): `merged_plan = {'tasks': stamped_tasks}` then adversarial_review -> auto_amend_gate -> persist_plan; inject `normalize_plan` between attribution_stamp and adversarial_review, or immediately before persist_plan on `final_plan`). harness/planner/plan_validator.py (validate_plan, `_valid_mutation_module`, the test_authoring/mutation_target rule added 6c6c89a — the normalizer's output must satisfy it). The mutation-gate ordering constraint lives in harness/orchestrator.py:_auto_commit_accepted (the `_mtt == 'test_authoring'` block). The corrected plan_hooks_symbol_ledger_module.json (committed 26bc940) is the worked example of the target shape.

# Deliverables

1. NEW module harness/planner/plan_normalizer.py exposing `normalize_plan(plan: dict) -> dict` (dedupe oracles + enforce module-first as above). 2. A NEW HERMETIC oracle (oracle-first) pinning: a plan with two test_authoring tasks sharing a mutation_target -> one dropped + deps rewired; an inverted impl/oracle dependency -> flipped to module-first; an already-correct plan -> unchanged (idempotent); a test_authoring task whose module has no impl task -> untouched. 3. The cli.py wiring (one call site) so every persisted merged leaf plan is normalized. IMPLEMENTATION CONSTRAINTS as implementation_notes: harness/planner/** is NOT on the _NEVER_AUTO_APPROVE deny-list (lands hands-off under the widened autowork.enabled posture once GAP1/GAP2 are in); new module = new file, oracle-first; single-purpose pure function; verification_command = this brief's own oracle plus hermetic regression only (never glob tests/planner/, never network/pip).
