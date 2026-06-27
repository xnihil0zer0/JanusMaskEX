---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
required_task_ids:
  - planner-review-degrade-oracle
  - planner-review-degrade-impl
interfaces: >
  Two coupled changes so an OPTIONAL adversarial-reviewer crash never poisons an
  otherwise-valid plan. (1) harness/planner/adversarial_review.py: the nested helper
  write_synthetic_failure() (line 73, inside run_adversarial_review; called on reviewer
  timeout :163, unresolved submission :166, spawn/exec exception :188, missing command
  :120) currently writes a finding {finding_id:"synthetic_failure", severity:"error"}.
  Change ONLY the written severity from "error" to "warn" and add logger.warning. (2) The
  oracle proves the REAL end-to-end outcome, not just the severity string: a reviewer
  crash, when the merged plan is otherwise VALID, must NOT cause the planner to drop the
  plan -- i.e. the auto_amend gate leaves a valid plan unchanged and plan_validator.
  validate_plan returns NO violations, so cli.main reaches persist_plan instead of the
  sys.exit(1) at cli.py:498-499. The function signature, return value (critique path),
  and call sites are unchanged.
---

# Title
Reviewer-crash must not drop a valid plan (synthetic_failure severity error -> warn; end-to-end persist proof)

# Scope
Single-file, single-symbol change to `harness/planner/adversarial_review.py`: rewrite
ONLY the nested helper `write_synthetic_failure` (defined at line 73, inside
`run_adversarial_review`) so a reviewer timeout/crash emits a `warn` finding, not an
`error` finding, and logs a WARNING.

# Root cause (CORRECTED -- prior diagnosis was wrong twice)
The reviewer is an OPTIONAL dual-blind critique. Under headless `-p` it intermittently crashes
INSTANTLY (`cost=$0.0000 duration=0.0s in=0 out=0`); the poll loop's `proc.poll() is not None`
branch fires in ~2s and `write_synthetic_failure` runs. Observed: planner_progress went
`adversarial_review(t+452) -> auto_amend_gate(t+454)` (~2s gap, total ~454s); daemon telemetry
for that run reads `planner_validation_rejected ... wall=454.2 reason=rc=1`.

Two prior claims are FALSE; do NOT re-introduce them:
- NOT an 1800s SIGKILL. `rc=1`, NOT `rc=124` (timeout); 454s is far under any wall (the daemon
  rc==124 branch at autowork_daemon.py:1859 never fired).
- The critique severity does NOT drop the plan. NOTHING keys on `severity=="error"` or
  `finding_id=="synthetic_failure"` to abort. The only critique.json consumers are `auto_amend.py`
  (applies `suggested_patch` ops only; a synthetic_failure has no patch -> skipped, plan returned
  UNCHANGED) and `cli.py` (copies the file). `validate_plan`/`plan_normalizer` never read it.

The REAL abort is `cli.py:498-499`: `violations = validate_plan(final_plan); if violations:
sys.exit(1)`. rc=1 -> the daemon (autowork_daemon.py:1883, `rc not in (0,124)`) deletes
`plan_hooks_<slug>.json` and writes `plan_attempts/<slug>.json`. The reviewer crash is a
CO-SYMPTOM: the same degraded `-p` backend that crashed the reviewer also yielded an empty claude
DRAFT -> a gemini-only/unreconciled plan that fails `validate_plan` (e.g. `missing_required_task`).
A VALID merged plan persists DESPITE a reviewer crash.

# Why the severity change AND the end-to-end pin
`error`->`warn` is correct and harmless (an optional degraded guard should not emit `error`) and
forecloses any FUTURE code gating on critique `error` severity. But the oracle MUST prove the real
contract -- "reviewer crash + valid plan => plan NOT dropped" -- or the brief is vacuous (GREEN
while the drop persists). The oracle below asserts BOTH the severity string AND the persist outcome.

# Inputs
READ `harness/planner/adversarial_review.py` FIRST. The CURRENT helper, nested inside
`run_adversarial_review` at line 73, is:

    def write_synthetic_failure(message: str) -> Path:
        synthetic = {
            "findings": [{
                "finding_id": "synthetic_failure",
                "category": "other",
                "severity": "error",
                "message": message
            }]
        }
        with open(critique_out_path, "w", encoding="utf-8") as f:
            json.dump(synthetic, f, indent=2)
        return critique_out_path

`logger` (module logger), `json`, `critique_out_path` (closed-over `planning_dir /
"critique.json"`) are in scope. `CritiqueSchema.validate` accepts `severity in
{"info","warn","error"}` and `category "other"`, so a `warn` finding stays schema-valid.

# Non-Goals
- No integration: this is a unit-level behavior change to a single helper and requires NO
  integration test (the literal word `integration` is here to excuse the integration-test
  requirement).
- Do NOT change the reviewer timeout VALUE, `planner_timeout_sec`, or any config knob.
- Do NOT change `run_adversarial_review`'s signature, its call sites, the four places that
  CALL `write_synthetic_failure` (:120,:163,:166,:188), the resolver, or the `finally`
  cleanup. Change ONLY the body of `write_synthetic_failure`.
- Do NOT touch `harness/planner/cli.py`, `harness/autowork_daemon.py`, `harness/config.yaml`,
  or any other `.py` file. (The cli.py abort is CORRECT -- a truly invalid plan SHOULD be
  rejected; the fix is to stop a reviewer crash from being conflated with a plan defect.)

# Deliverables
1. In `harness/planner/adversarial_review.py`, `write_synthetic_failure` writes the finding
   with `"severity": "warn"` (NOT `"error"`) and calls `logger.warning(...)` with the
   message. It still writes to `critique_out_path` and returns it.
2. The paired oracle `tests/harness/test_planner_review_degrade.py` is GREEN.

# Required plan shape
Emit EXACTLY TWO tasks.

Task 1 - id `planner-review-degrade-oracle`
- meta_task_type: `test_authoring`
- priority: `high`   (bare lowercase word; NOT an integer, NOT `P0`/`P1`)
- Authors `tests/harness/test_planner_review_degrade.py`.
- mutation_target: `harness/planner/adversarial_review.py::write_synthetic_failure`
  (dotted symbol target).
- non_goals MUST contain the literal word `integration`.
- verification_command: `python -m pytest tests/harness/test_planner_review_degrade.py -q`
- The oracle uses normal `from ... import` (NO exec/eval/compile/__import__ - AST-banned).
  Import `run_adversarial_review` from `harness.planner.adversarial_review` and
  `validate_plan` from `harness.planner.plan_validator`, and `auto_amend` from
  `harness.planner.auto_amend`. It SIMULATES a reviewer crash WITHOUT a real agent:
  `monkeypatch.setattr` the module's `spawn_agent` to return a fake proc whose `.poll()`
  returns a non-None exit code and whose `_work_dir` is an empty tmp dir (so
  `_resolve_submission` finds nothing -> the crash branch fires and write_synthetic_failure
  runs); `monkeypatch.setattr` the module's `kill_agent` to a no-op.
- TEST A (RED on HEAD, severity): call `run_adversarial_review(merged_plan={"tasks": []},
  config={}, state_dir=tmp_path)`. Assert `tmp_path/"planning"/"critique.json"` exists and
  json-loads to a dict with a `findings` list; there is a finding with
  `finding_id == "synthetic_failure"`; that finding's `severity == "warn"`; and NO finding
  has `severity == "error"`. (RED on HEAD: HEAD writes `"error"`.)
- TEST B (end-to-end persist contract, the REAL goal): build a VALID one-task `valid_plan`
  whose single task passes `validate_plan`. Use the validated minimal-task shape from
  `tests/adversarial/test_planning_outbox_fallback_adversarial.py::_minimal_valid_task` (READ it
  and reuse that field set; `non_goals` must include "integration_tests"). FIRST
  `assert validate_plan(valid_plan) == []` (precondition). Then
  `run_adversarial_review(valid_plan, {}, tmp_path)` (reviewer crash -> warn critique). Then
  `result = auto_amend(valid_plan, tmp_path/"planning"/"critique.json", {}, tmp_path)` and assert
  `validate_plan(result.amended_plan) == []`. This proves the cli.py:498 abort predicate evaluates
  FALSE after a reviewer crash on a valid plan -> cli reaches persist_plan. Non-vacuous: it pins
  that a reviewer crash injects NO violations and does NOT corrupt the amended plan.
  Keep both tests hermetic and fast (no network, no real agent spawn).

Task 2 - id `planner-review-degrade-impl`
- meta_task_type: `harness_self_fix`   (writes sensitive path harness/planner/adversarial_review.py)
- priority: `high`
- files_touched: `["harness/planner/adversarial_review.py"]`
- dependencies: `["planner-review-degrade-oracle"]`
- spec_author: `null`.
- mutation_target: `harness/planner/adversarial_review.py::run_adversarial_review`
- non_goals MUST contain the literal word `integration`.
- Emit the change as a `__JANUSMASK_PATCHES__` symbol patch targeting the ENCLOSING TOP-LEVEL
  symbol `run_adversarial_review` (NOT a bare nested-name patch: `write_synthetic_failure` is a
  NESTED closure and a 1-part bare-name nested apply is rejected -> `auto_commit_failed`). Patch
  `run_adversarial_review` WHOLE, changing ONLY its inner `write_synthetic_failure` helper so the
  written finding has `"severity": "warn"` instead of `"error"`, and adding, before the file
  write inside that helper, `logger.warning("adversarial review degraded to soft-skip: %s",
  message)`. Keep `finding_id` `"synthetic_failure"`, `category` `"other"`, the `message`, the
  write to `critique_out_path`, the `return critique_out_path`, and the ENTIRE rest of
  `run_adversarial_review` (spawn, resolve, validate, finally-cleanup) BYTE-IDENTICAL. Touch
  nothing else in the file.
- verification_command: `python -m pytest tests/harness/test_planner_review_degrade.py -q`
  (the SAME oracle - the impl makes it GREEN).

NOTE: `harness/planner/adversarial_review.py` is a sensitive `harness/**` path but is NOT in the
irreducible `_NEVER_AUTO_APPROVE` deny-list (harness/orchestrator.py:2577), so it needs no
operator decision file under a widened `autowork.enabled` auto-approve grant; it is written by
the `harness_self_fix` impl task.

TEST_SPEC COUNTS (validator-enforced): `functional_requirements` SMALL (1-2); `unit_tests` len >=
`functional_requirements` len; `minimum_test_count` >= 1.5*len(functional_requirements);
`regression_tests`+`property_tests` total >= 2 (TEST A + TEST B cover these).
