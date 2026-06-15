---
interfaces: "run_stage(context: dict, seams: dict) -> list[dict]; consumes get_task(session_row: dict) -> {phase, target, prior_findings, parked_package}; artifact dicts parseable by parse_stage_artifact(filename, content, phase)"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

Gate and submission phase workers: novelty, report

# Scope

Build the two finishing phase workers as whole-file modules, each exposing run_stage(context, seams) -> list[dict]: ngv2/workers/novelty.py (composes the injected novelty_gate seam to judge whether a confirmed finding is novel, without weakening the gate) and ngv2/workers/report.py (composes the injected submission_package seam to assemble the final submission package from the parked_package / prior_findings context). Each returns artifact dicts shaped so artifact_harvester.parse_stage_artifact can parse them and so the relevant contracts dataclass can be built. All gate/packaging behavior arrives via the injected seams dict so each module is deterministic and oracle-testable with no real model/network/subprocess. Each module is a single file with a paired test_authoring sibling whose mutation_target is that module and whose verification_command names the authored RED oracle, with at least two edge cases per leaf driven by stub seams (e.g. stub llm-client/submission_package returning empty/malformed output; the novelty_gate seam reporting a duplicate/failure).

# Non-Goals

Do not build StageWorker, the seam assembler (build_default_seams), the conductor loop, or gated_advance. Do not implement get_task. Do not edit ngv2/novelty_gate.py or ngv2/submission_package.py in place — compose them only as injected seams. Do not weaken or bypass the novelty gate, auto-submit to huntr, or contact any external service. No real LLM call, network, or subprocess may run inside any oracle. Do not implement hunt/triage/verify/poc/detonate logic (other children).

# Inputs

Each module exposes run_stage(context: dict, seams: dict) -> list[dict]. context originates from get_task(session_row: dict) -> {phase, target, prior_findings, parked_package} (parked_package / prior_findings supply the material to judge and package). seams carries the injected novelty_gate seam for novelty.py and the injected submission_package seam (plus the injected llm-client seam as needed) for report.py (matching ngv2/novelty_gate.py, ngv2/submission_package.py, ngv2/llm_client.py, all read-only). Reads (does not modify) ngv2/contracts.py dataclasses for output field names, ngv2/artifact_harvester.py parse_stage_artifact(filename, content, phase) for the artifact dict shape, and ngv2/session_db.py insert_report for the persist-side shape.

# Deliverables

ngv2/workers/novelty.py and ngv2/workers/report.py — each exposing run_stage(context, seams) -> list[dict] of artifact dicts parseable by artifact_harvester.parse_stage_artifact(filename, content, phase) and shaped for the relevant contracts dataclass. Freezes the phase contract: run_stage(context: dict, seams: dict) -> list[dict]. Each file has a test_authoring sibling with mutation_target set to that file and a verification_command naming the authored oracle, covering at least two edge cases (stub submission_package empty/malformed output; the novelty_gate seam reporting a duplicate/failure).
