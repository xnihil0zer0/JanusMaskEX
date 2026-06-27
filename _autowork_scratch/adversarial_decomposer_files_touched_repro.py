#!/usr/bin/env python3
"""ADVERSARIAL REPRO: prove the decomposer now propagates files_touched to
decomposed sub-tasks, using the ACTUAL parent health_producer task JSON that
spiralled, driven through the LIVE harness.task_decomposer (not a mock).

VERDICT logic:
- Load the real parent plan task `p21-cp-health-producer-impl` from the held
  plan_hooks_p21_cp_health_producer.json (it carries files_touched=
  ['ngv2/health_producer.py']).
- Synthesize divergent fuzz failures (2+ categories) so decompose_task takes
  the same edge_case path the spiral took.
- Run decompose_task + enqueue_subtasks against a temp state dir.
- Assert every written sub-task JSON now carries files_touched.
- Also reproduce the OLD-bug expectation by checking a held spiral sub-task
  JSON (which lacks files_touched) to confirm the before/after contrast.
"""
import json
import sys
import tempfile
from pathlib import Path

REPO = Path("/home/xnihil0zer0/JanusMaskJR")
sys.path.insert(0, str(REPO))

from harness.task_decomposer import decompose_task, enqueue_subtasks  # live module
from harness.sandbox import ExecutionResult
from harness.task_decomposer import FuzzFailure

HELD = REPO / "_held_health_spiral"
PLAN = json.loads((HELD / "plan_hooks_p21_cp_health_producer.json").read_text())

# 1) Pull the REAL parent impl task from the real plan.
parent_plan_task = next(t for t in PLAN["tasks"] if t["task_id"] == "p21-cp-health-producer-impl")
print("=== PARENT TASK (from real held plan) ===")
print("task_id        :", parent_plan_task["task_id"])
print("files_touched  :", parent_plan_task.get("files_touched"))
print("mutation_target:", parent_plan_task.get("mutation_target", "<none>"))

# Build the task dict the way the orchestrator loads it (json.load of the task
# file). The live worker passes this full dict to decompose_task.
task = {
    "task_id": parent_plan_task["task_id"],
    "specification": parent_plan_task["spec"]["objective"],
    "files_touched": parent_plan_task.get("files_touched"),
    "mutation_target": parent_plan_task.get("mutation_target"),  # impl task has none -> None
    "meta_task_type": parent_plan_task.get("meta_task_type"),
    "constraints": {"meta_task_type": parent_plan_task.get("meta_task_type", "validation")},
    "depth": 0,
}


def mk_failure(input_args, reason="general"):
    return FuzzFailure(
        input_args=input_args,
        input_kwargs={},
        result_a=ExecutionResult(success=True, return_value=1, return_repr="1"),
        result_b=ExecutionResult(success=True, return_value=2, return_repr="2"),
        reason=reason,
    )


# 2) Divergent failures spanning >=2 categories -> edge_case decomposition,
#    exactly the strategy that produced -empty_input / -general / -compose.
failures = [mk_failure([[]]), mk_failure([0]), mk_failure([5, 10])]
config = {"decomposition": {"max_subtasks": 5, "max_depth": 3}}

result = decompose_task(task, failures, config, depth=0)
print("\n=== LIVE decompose_task RESULT ===")
print("strategy :", result.strategy)
print("reason   :", result.reason)
print("subtasks :", [s.task_id for s in result.subtasks])

with tempfile.TemporaryDirectory() as td:
    state_dir = Path(td)
    enqueue_subtasks(result.subtasks, state_dir)
    print("\n=== ENQUEUED SUB-TASK JSON files_touched (POST-FIX, live path) ===")
    all_have = True
    for st in result.subtasks:
        p = state_dir / "tasks" / f"{st.task_id}.json"
        data = json.loads(p.read_text())
        ft = data.get("files_touched", "<MISSING>")
        ok = ft == ["ngv2/health_producer.py"]
        all_have = all_have and ok
        print(f"  {st.task_id:55s} files_touched={ft!r}  {'OK' if ok else 'FAIL'}")

# 3) Before/after contrast: the held spiral sub-task JSON (written by the
#    BUGGY decomposer) lacks files_touched.
print("\n=== HELD SPIRAL SUB-TASK (PRE-FIX, written by buggy decomposer) ===")
spiral = json.loads((HELD / "blocked_p21-cp-health-producer-impl-compose.json").read_text())
print("  p21-cp-health-producer-impl-compose files_touched =",
      spiral.get("files_touched", "<MISSING (this is the bug)>"))

print("\n=== VERDICT ===")
if all_have:
    print("FIX CONFIRMED: every live-path decomposed sub-task inherits "
          "files_touched=['ngv2/health_producer.py'] (pre-fix held artifacts had none).")
    sys.exit(0)
else:
    print("STILL BROKEN: at least one sub-task lacks the correct files_touched.")
    sys.exit(1)
