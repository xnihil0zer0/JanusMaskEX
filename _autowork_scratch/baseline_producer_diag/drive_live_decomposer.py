"""ANALYTIC (read-only-ish, writes only to a throwaway tmpdir): drive the LIVE
harness.task_decomposer on a representative parent task that carries a
verification_command, then inspect the enqueued sub-task JSON to prove whether
verification_command is propagated the way files_touched/mutation_target now are.

Run: PYTHONPATH=<JM root> python drive_live_decomposer.py
Touches NOTHING in production: state_dir is a fresh tempfile.mkdtemp().
"""
import json
import tempfile
from pathlib import Path

from harness.task_decomposer import decompose_task, enqueue_subtasks

# Representative parent task modeled on p21-cp-baseline-producer-impl:
# carries vcmd + files_touched + mutation_target, depth at max so the
# planner_review path fires (the exact path the baseline task took).
parent_task = {
    "task_id": "demo-baseline-impl",
    "specification": "Implement produce_baseline_input in ngv2/baseline_producer.py",
    "constraints": {"meta_task_type": "implementation"},
    "verification_command": "python -m pytest tests/ngv2/test_baseline_producer.py -q",
    "files_touched": ["ngv2/baseline_producer.py"],
    "mutation_target": "ngv2.baseline_producer.produce_baseline_input",
    "depth": 3,
}

config = {"decomposition": {"max_subtasks": 5, "max_depth": 3}}

print("=== PARENT TASK ===")
print("  verification_command:", repr(parent_task["verification_command"]))
print("  files_touched:       ", parent_task["files_touched"])
print("  mutation_target:     ", parent_task["mutation_target"])

# depth==max_depth -> planner_review branch (the branch the real task hit)
result = decompose_task(parent_task, failures=[], config=config, depth=3)
print("\n=== DECOMPOSE RESULT ===")
print("  strategy:", result.strategy)
print("  reason: ", result.reason)
for st in result.subtasks:
    print("  subtask dataclass fields:")
    print("    task_id:             ", st.task_id)
    print("    files_touched:       ", st.files_touched)
    print("    mutation_target:     ", st.mutation_target)
    print("    has 'verification_command' attr:", hasattr(st, "verification_command"))

# Enqueue to a throwaway state_dir and read back the emitted JSON --
# this is exactly what the orchestrator's _resolve_verification_command
# reads from later.
tmp = Path(tempfile.mkdtemp(prefix="decomp_diag_"))
enqueue_subtasks(result.subtasks, tmp)
print("\n=== ENQUEUED SUB-TASK JSON (what orchestrator reads) ===")
for f in sorted((tmp / "tasks").glob("*.json")):
    d = json.loads(f.read_text())
    print(f"  {f.name}:")
    print("    keys:                ", list(d.keys()))
    print("    verification_command:", repr(d.get("verification_command")))
    print("    files_touched:       ", d.get("files_touched"))
    print("    mutation_target:     ", d.get("mutation_target"))

print("\n=== VERDICT ===")
emitted = json.loads(next((tmp / "tasks").glob("*.json")).read_text())
vc = emitted.get("verification_command")
ft = emitted.get("files_touched")
mt = emitted.get("mutation_target")
print(f"  verification_command propagated to sub-task? {'YES' if vc else 'NO  <-- STRIPPED'}")
print(f"  files_touched propagated to sub-task?        {'YES' if ft else 'NO'}")
print(f"  mutation_target propagated to sub-task?      {'YES' if mt else 'NO  <-- ALSO STRIPPED'}")
