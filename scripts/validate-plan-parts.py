#!/usr/bin/env python3
"""Validate plan-part*.json files against the preamble schema.

Checks per task:
  - required fields present
  - meta_task_type in known taxonomy
  - spec_author / attribution_metadata in bootstrap state
  - test-heavy rule (§7): unit_tests >= functional_requirements,
    >=1 integration_test (unless justified), >=2 edge_cases in
    regression/property, minimum_test_count >= 1.5 * len(FRs)
  - token_budget_ratio.test_tokens >= 1.5 * implementation_tokens
  - dependencies form a DAG (globally, across all parts)
  - no duplicate task_ids
  - cross-part dependency placeholders identified

Prints a summary and exits nonzero on any violation.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PARTS = [
    ("fuzzing-infra", "FI", REPO / "plan-part1-fuzzing-infra-v2.json"),
    ("planner-system", "PS", REPO / "plan-part2-planner-system-v2.json"),
    ("track-record", "TR", REPO / "plan-part3-track-record-v2.json"),
    ("tests", "T", REPO / "plan-part4-tests-v2.json"),
    ("harness-fixes", "HF", REPO / "plan-part5-harness-fixes.json"),
]

META_TAXONOMY = {
    "sandbox_infra", "mcp_server_change",
    "config_schema", "data_model", "cli_tooling", "test_unit",
    "test_integration", "test_e2e", "docs_writing", "refactor",
    "logging_observability",
}

REQUIRED_TASK_FIELDS = [
    "task_id", "title", "meta_task_type", "priority", "dependencies",
    "files_touched", "spec", "test_spec", "acceptance_criteria",
    "token_budget_ratio", "spec_author", "attribution_metadata",
    "estimated_complexity", "verification_command",
]

REQUIRED_SPEC_FIELDS = [
    "objective", "functional_requirements", "interfaces",
    "edge_cases", "non_goals", "implementation_notes",
]

REQUIRED_TEST_SPEC_FIELDS = [
    "unit_tests", "integration_tests", "property_tests",
    "regression_tests", "minimum_test_count", "test_data_requirements",
]


def is_test_task(task: dict) -> bool:
    return task.get("meta_task_type", "").startswith("test_")


def validate_task(task: dict, expected_prefix: str) -> list[str]:
    errors: list[str] = []
    tid = task.get("task_id", "<missing>")

    # Required fields
    for field in REQUIRED_TASK_FIELDS:
        if field not in task:
            errors.append(f"{tid}: missing required field '{field}'")

    # Task ID prefix
    if not re.match(rf"^{expected_prefix}-\d{{3}}$", task.get("task_id", "")):
        errors.append(f"{tid}: task_id doesn't match ^{expected_prefix}-\\d{{3}}$")

    # Meta task type
    mtt = task.get("meta_task_type")
    if mtt not in META_TAXONOMY:
        errors.append(f"{tid}: unknown meta_task_type '{mtt}'")

    # Spec author bootstrap
    if task.get("spec_author") is not None:
        errors.append(f"{tid}: spec_author must be null in bootstrap (got {task['spec_author']!r})")

    am = task.get("attribution_metadata", {}) or {}
    if am.get("proposed_by") is not None:
        errors.append(f"{tid}: attribution_metadata.proposed_by must be null in bootstrap")
    if am.get("reconciled") is not False:
        errors.append(f"{tid}: attribution_metadata.reconciled must be false in bootstrap")

    # Spec fields
    spec = task.get("spec", {}) or {}
    for field in REQUIRED_SPEC_FIELDS:
        if field not in spec:
            errors.append(f"{tid}: spec missing '{field}'")

    # Test spec fields
    ts = task.get("test_spec", {}) or {}
    for field in REQUIRED_TEST_SPEC_FIELDS:
        if field not in ts:
            errors.append(f"{tid}: test_spec missing '{field}'")

    # Test-heavy rule (§7) — exempt test_* tasks from the ratio only
    frs = spec.get("functional_requirements", []) or []
    unit_tests = ts.get("unit_tests", []) or []
    integration_tests = ts.get("integration_tests", []) or []
    prop_tests = ts.get("property_tests", []) or []
    regr_tests = ts.get("regression_tests", []) or []
    edge_cases = spec.get("edge_cases", []) or []
    non_goals = spec.get("non_goals", []) or []
    min_test_count = ts.get("minimum_test_count", 0)

    total_tests = len(unit_tests) + len(integration_tests) + len(prop_tests) + len(regr_tests)

    # Rule 1: coverage >= functional_requirements
    # For test_* tasks, "unit tests" don't apply (the task IS test infra);
    # count total tests across all categories instead.
    if is_test_task(task):
        if total_tests < len(frs):
            errors.append(
                f"{tid}: total tests ({total_tests}) < functional_requirements ({len(frs)})"
            )
    else:
        if len(unit_tests) < len(frs):
            errors.append(
                f"{tid}: unit_tests ({len(unit_tests)}) < functional_requirements ({len(frs)})"
            )

    # Rule 2: at least one integration_test unless justified
    if len(integration_tests) < 1:
        has_justification = any(
            "integration" in (ng or "").lower() for ng in non_goals
        )
        if not has_justification:
            errors.append(f"{tid}: no integration_tests and no non_goals justification")

    # Rule 3: at least 2 edge_cases reflected in regression OR property tests.
    # For test_* tasks, also count integration tests since they are the
    # primary verification vehicle.
    if is_test_task(task):
        edge_guards = len(prop_tests) + len(regr_tests) + len(integration_tests)
    else:
        edge_guards = len(prop_tests) + len(regr_tests)
    if len(edge_cases) >= 2 and edge_guards < 2:
        errors.append(
            f"{tid}: has {len(edge_cases)} edge_cases but only "
            f"{edge_guards} guard tests (need >=2)"
        )

    # Rule 4: minimum_test_count >= 1.5 * functional_requirements
    if frs and min_test_count < 1.5 * len(frs):
        errors.append(
            f"{tid}: minimum_test_count ({min_test_count}) < "
            f"1.5 * functional_requirements ({1.5 * len(frs)})"
        )

    # Rule 5: token budget ratio (test tasks exempt)
    if not is_test_task(task):
        tbr = task.get("token_budget_ratio", {}) or {}
        impl = tbr.get("implementation_tokens", 0)
        test = tbr.get("test_tokens", 0)
        if impl > 0 and test < 1.5 * impl:
            errors.append(
                f"{tid}: test_tokens ({test}) < 1.5 * implementation_tokens ({impl})"
            )

    # Rule 6: Assertion density
    for idx, t in enumerate(unit_tests):
        if len(t.get("assertions", [])) < 2:
            errors.append(f"{tid}: unit_test '{t.get('name', 'unnamed')}' has < 2 assertions")
    
    for t_list, t_name in [(integration_tests, "integration_test"), (prop_tests, "property_test"), (regr_tests, "regression_test")]:
        for idx, t in enumerate(t_list):
            if "assertions" in t:
                count = len(t["assertions"])
            else:
                desc_len = len(t.get("description", "")) + len(t.get("strategy", ""))
                count = 1 if desc_len > 10 else 0
            if count < 1:
                errors.append(f"{tid}: {t_name} '{t.get('name', 'unnamed')}' lacks assertions or meaningful description")

    return errors


def main() -> int:
    all_tasks: dict[str, dict] = {}  # task_id -> task
    all_errors: list[str] = []
    part_summaries: list[dict] = []
    placeholder_deps: dict[str, list[str]] = {}  # task_id -> [placeholders]

    for part_name, prefix, path in PARTS:
        if not path.is_file():
            all_errors.append(f"MISSING FILE: {path}")
            continue

        try:
            with open(path) as f:
                doc = json.load(f)
        except json.JSONDecodeError as e:
            all_errors.append(f"{path.name}: INVALID JSON: {e}")
            continue

        if doc.get("part") != part_name:
            all_errors.append(f"{path.name}: top-level 'part' is {doc.get('part')!r}, expected {part_name!r}")

        tasks = doc.get("tasks", [])
        part_errors: list[str] = []
        priorities: dict[int, int] = {}

        for task in tasks:
            tid = task.get("task_id", "<missing>")
            if tid in all_tasks:
                part_errors.append(f"DUPLICATE task_id: {tid}")
                continue
            all_tasks[tid] = task

            part_errors.extend(validate_task(task, prefix))

            p = task.get("priority")
            if isinstance(p, int):
                priorities[p] = priorities.get(p, 0) + 1

            # Collect placeholder deps (strings that aren't prefix-NNN)
            placeholders = []
            for dep in task.get("dependencies", []):
                if not re.match(r"^(FI|PS|TR|T|HF)-\d{3}$", dep):
                    placeholders.append(dep)
            if placeholders:
                placeholder_deps[tid] = placeholders

        part_summaries.append({
            "part": part_name,
            "prefix": prefix,
            "file": path.name,
            "task_count": len(tasks),
            "priorities": priorities,
            "errors": len(part_errors),
        })
        all_errors.extend(part_errors)

    # Global DAG check
    def has_cycle() -> list[str]:
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {tid: WHITE for tid in all_tasks}
        cycles: list[str] = []

        def dfs(tid: str, path: list[str]) -> None:
            if tid not in all_tasks:
                return  # unknown dep — reported separately below
            if color[tid] == GRAY:
                cycles.append(" -> ".join(path + [tid]))
                return
            if color[tid] == BLACK:
                return
            color[tid] = GRAY
            deps = all_tasks[tid].get("dependencies", [])
            for dep in deps:
                if re.match(r"^(FI|PS|TR|T|HF)-\d{3}$", dep):
                    dfs(dep, path + [tid])
            color[tid] = BLACK

        for tid in sorted(all_tasks):
            if color[tid] == WHITE:
                dfs(tid, [])
        return cycles

    cycles = has_cycle()
    if cycles:
        all_errors.extend(f"DAG CYCLE: {c}" for c in cycles)

    # Unknown dependency references
    unknown_deps: list[tuple[str, str]] = []
    for tid, task in all_tasks.items():
        for dep in task.get("dependencies", []):
            if re.match(r"^(FI|PS|TR|T|HF)-\d{3}$", dep) and dep not in all_tasks:
                unknown_deps.append((tid, dep))

    # -------------------- Print summary --------------------
    print("=" * 70)
    print("  PLAN PART VALIDATION SUMMARY")
    print("=" * 70)
    for s in part_summaries:
        pri = ", ".join(f"P{k}={v}" for k, v in sorted(s["priorities"].items()))
        print(f"  {s['prefix']:<3} {s['file']:<38}  {s['task_count']:>2} tasks  [{pri}]  errors={s['errors']}")
    print(f"\n  TOTAL tasks: {len(all_tasks)}")
    print(f"  TOTAL errors: {len(all_errors)}")
    print(f"  Cross-part dep placeholders: {sum(len(v) for v in placeholder_deps.values())}")
    print(f"  Unknown dep references: {len(unknown_deps)}")

    if placeholder_deps:
        print("\n  --- Placeholder dependencies (to resolve) ---")
        for tid in sorted(placeholder_deps):
            for ph in placeholder_deps[tid]:
                print(f"    {tid} -> {ph}")

    if unknown_deps:
        print("\n  --- Unknown dep references ---")
        for tid, dep in unknown_deps:
            print(f"    {tid} references unknown {dep}")

    if all_errors:
        print("\n  --- Errors ---")
        for e in all_errors[:100]:
            print(f"    {e}")
        if len(all_errors) > 100:
            print(f"    ... and {len(all_errors) - 100} more")
        return 1

    print("\n  OK: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
