---
interfaces: "StageWorker(task, get_task_fn, stage_fn, write_fn)"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

StageWorker Base Infrastructure

# Scope

Build ngv2/workers/base.py exposing StageWorker which, given (task, get_task_fn, stage_fn, write_fn), fetches the task via get_task_fn, runs stage_fn over the resulting context, and writes the structured artifact dict(s) returned by stage_fn to the task's output_path via write_fn. Write a paired test_authoring sibling test file whose mutation_target is ngv2/workers/base.py to verify it with at least two edge cases.

# Non-Goals

Do not build the seam assembler (build_default_seams), the conductor loop, or gated_advance. Do not implement get_task here. Do not write any phase worker module (hunt.py, triage.py, verify.py, poc.py, detonate.py, novelty.py, report.py).

# Inputs

Consumes get_task(session_row: dict) -> {phase, target, prior_findings, parked_package} from conductor_glue (ngv2/session_get_task.py) as the injected get_task_fn. Consumes `run_stage(context, seams) -> list[dict]` as the injected stage_fn.

# Deliverables

ngv2/workers/base.py which exposes `StageWorker(task, get_task_fn, stage_fn, write_fn)` that fetches via get_task_fn, runs stage_fn over the context, and writes artifact dict(s) to the task output_path via write_fn. Paired test_authoring sibling test file for base.py with mutation_target set to base.py and a verification_command naming the authored oracle.
