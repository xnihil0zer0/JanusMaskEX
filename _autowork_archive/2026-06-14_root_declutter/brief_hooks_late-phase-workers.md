---
dependencies:
  - "base_worker"
interfaces: "run_stage(context, seams) -> list[dict]"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

Late-Phase Workers: PoC, Detonate, Novelty, and Report

# Scope

Build four phase workers: ngv2/workers/poc.py, detonate.py, novelty.py, and report.py, each exposing run_stage(context, seams) -> list[dict] that composes the injected llm-client seam with the relevant existing ngv2 module for that phase (poc.py over poc_writer/poc_repair_loop, detonate.py over detonation, novelty.py over novelty_gate, report.py over submission_package). Each module is a single file with a paired test_authoring sibling whose mutation_target is that module to verify it with at least two edge cases driven by stub llm-client and stub seams.

# Non-Goals

Do not build the seam assembler (build_default_seams), the conductor loop, or gated_advance. Do not edit any existing committed module in place. Do not write the StageWorker base runner or the early-phase workers (hunt.py, triage.py, verify.py).

# Inputs

Consumes get_task(session_row: dict) -> {phase, target, prior_findings, parked_package} from conductor_glue (ngv2/session_get_task.py). Consumes `StageWorker(task, get_task_fn, stage_fn, write_fn)` from base_worker. Reads (does not modify) the signatures of existing seams it composes via injection: ngv2/llm_client.py (the injected model seam); ngv2/poc_writer.py, ngv2/poc_repair_loop.py, ngv2/detonation.py, novelty_gate.py, submission_package.py; ngv2/contracts.py dataclasses Finding, PoC, LiveTestReport; ngv2/artifact_harvester.py parse_stage_artifact(filename, content, phase) for the artifact dict shape.

# Deliverables

ngv2/workers/poc.py, detonate.py, novelty.py, report.py — each exposing `run_stage(context, seams) -> list[dict]` of artifact dicts parseable by artifact_harvester.parse_stage_artifact and shaped for the contracts dataclasses. Each file has a test_authoring sibling with mutation_target set to that file and a verification_command naming the authored oracle.
