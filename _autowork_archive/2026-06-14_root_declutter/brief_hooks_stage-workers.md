---
epic: true
dependencies:
  - "conductor_glue"
interfaces: "StageWorker(task, get_task_fn, stage_fn, write_fn); run_stage(context, seams) -> list[dict]; consumes get_task(session_row: dict) -> {phase, target, prior_findings, parked_package}"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

StageWorker base plus per-phase agent workers (hunt, triage, verify, poc, detonate, novelty, report) over injected seams

# Scope

Build a NEW ngv2/workers/ package as whole-file modules, each over INJECTED SEAMS (llm client, db, sibling module functions all passed in) so each is deterministic and oracle-testable with no real model/network/subprocess. (a) ngv2/workers/base.py exposing StageWorker which, given (task, get_task_fn, stage_fn, write_fn), fetches the task via get_task_fn, runs stage_fn over the resulting context, and writes the structured artifact dict(s) returned by stage_fn to the task's output_path via write_fn (no real filesystem I/O in the oracle — write_fn is injected). (b) Seven phase workers ngv2/workers/hunt.py, triage.py, verify.py, poc.py, detonate.py, novelty.py, report.py, each exposing run_stage(context, seams) -> list[dict] that composes the injected llm-client seam with the relevant existing ngv2 module for that phase (poc.py over poc_writer/poc_repair_loop, detonate.py over detonation, novelty.py over novelty_gate, report.py over submission_package, etc.) and returns artifact dicts shaped so artifact_harvester.parse_stage_artifact can parse them and the contracts dataclasses (Finding, PoC, LiveTestReport) can be built from them. Each module is a single file with a paired test_authoring sibling whose mutation_target is that module so the pipeline authors the RED oracle, with at least two edge cases per leaf (e.g. stub llm-client returning empty/malformed output; a phase module seam reporting failure), driven by a stub llm-client and stub module seams.

# Non-Goals

Do not build the seam assembler (build_default_seams), the conductor loop, or gated_advance. Do not implement get_task here — it is consumed as an injected get_task_fn matching the conductor_glue signature. Do not edit any existing committed module in place; compose poc_writer.py, poc_repair_loop.py, detonation.py, novelty_gate.py, submission_package.py and the four may_confirm gates only as injected seams. Do not weaken any acceptance gate, auto-submit to huntr, or contact any external service. Per the integration policy these worker leaves compose existing seams, so this integration concern requires no separate heavy cross-module integration test; no real LLM call, network, or subprocess may run inside any oracle.

# Inputs

Consumes get_task(session_row: dict) -> {phase, target, prior_findings, parked_package} from conductor_glue (ngv2/session_get_task.py) as the injected get_task_fn that StageWorker calls. Reads (does not modify) the signatures of existing seams it composes via injection: ngv2/llm_client.py (the injected model seam); ngv2/poc_writer.py, ngv2/poc_repair_loop.py, ngv2/detonation.py, ngv2/novelty_gate.py, ngv2/submission_package.py and the four may_confirm gate modules; ngv2/contracts.py dataclasses Finding, PoC, LiveTestReport; ngv2/artifact_harvester.py parse_stage_artifact(filename, content, phase) for the artifact dict shape; ngv2/session_db.py insert_finding/insert_poc/insert_report for the persist-side shape.

# Deliverables

ngv2/workers/base.py exposing StageWorker(task, get_task_fn, stage_fn, write_fn) that fetches via get_task_fn, runs stage_fn over the context, and writes artifact dict(s) to the task output_path via write_fn. ngv2/workers/hunt.py, triage.py, verify.py, poc.py, detonate.py, novelty.py, report.py — each exposing run_stage(context, seams) -> list[dict] of artifact dicts parseable by artifact_harvester.parse_stage_artifact and shaped for the contracts dataclasses. Each file has a test_authoring sibling with mutation_target set to that file and a verification_command naming the authored oracle.
