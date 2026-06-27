"""Analytic repro: does normalize_plan->validate_plan accept priority 'P1'?

Constructs a minimal leaf plan with a single task carrying priority 'P1'
(exactly what a blind-draft agent emits when the brief frontmatter says
`priority: P1`), runs it through the REAL normalize_plan then validate_plan,
and prints whether the priority was normalized and whether validation rejects.
"""
import json
from harness.planner.plan_normalizer import normalize_plan, _PRIORITY_NORMALIZATION_MAP, _normalize_task_priorities
from harness.planner.plan_validator import validate_plan, PRIORITY_CANONICAL

def make_plan(pval):
    return {
        "tasks": [
            {
                "task_id": "demo-impl",
                "title": "Demo",
                "meta_task_type": "harness_self_fix",
                "priority": pval,
                "dependencies": [],
                "files_touched": ["harness/foo.py"],
                "acceptance_criteria": ["it works"],
                "spec_author": None,
                "estimated_complexity": "low",
                "verification_command": "python -m pytest tests/harness/test_foo.py -q",
            }
        ]
    }

print("PRIORITY_CANONICAL =", sorted(PRIORITY_CANONICAL))
print("map has 'P1' ->", _PRIORITY_NORMALIZATION_MAP.get("P1"))
print()

for pval in ["P1", "p1", "P1 ", "P0", "high", "medium"]:
    plan = make_plan(pval)
    # direct helper
    direct = make_plan(pval)
    _normalize_task_priorities(direct["tasks"])
    direct_after = direct["tasks"][0]["priority"]
    # full pipeline normalize_plan (repo_root=None to avoid I/O)
    norm = normalize_plan(plan, repo_root=None)
    norm_tasks = norm.get("tasks", [])
    norm_after = norm_tasks[0]["priority"] if norm_tasks else "<DROPPED>"
    viols = validate_plan(norm)
    pri_viols = [v for v in viols if "priority" in str(getattr(v, "path", ""))]
    print(f"input={pval!r:8} | _normalize_task_priorities-> {direct_after!r:10} | normalize_plan-> {norm_after!r:10} | priority_violations={len(pri_viols)} | total_violations={len(viols)}")
    for v in viols:
        print(f"    VIOLATION code={getattr(v,'code',None)!r} path={getattr(v,'path',None)!r} msg={getattr(v,'message',None)!r}")
