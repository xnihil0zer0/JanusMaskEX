---
interfaces: "run_stage(context: dict, seams: dict) -> list[dict]; consumes get_task(session_row: dict) -> {phase, target, prior_findings, parked_package}; artifact dicts parseable by parse_stage_artifact(filename, content, phase) and buildable into contracts.Finding"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

Discovery phase workers: hunt, triage, verify

# Scope

Build the three discovery phase workers as whole-file modules, each exposing run_stage(context, seams) -> list[dict]: ngv2/workers/hunt.py (composes the injected llm-client seam to surface candidate vulnerabilities from the target), ngv2/workers/triage.py (composes the injected llm-client seam to assess/prioritize prior_findings), and ngv2/workers/verify.py (composes the four injected may_confirm gate seams to confirm a finding without weakening any gate). Each returns artifact dicts shaped so artifact_harvester.parse_stage_artifact can parse them and so contracts.Finding can be built from them. All model/gate behavior arrives via the injected seams dict so each module is deterministic and oracle-testable with no real model/network/subprocess. Each of the three modules is a single file with a paired test_authoring sibling whose mutation_target is that module and whose verification_command names the authored RED oracle, with at least two edge cases per leaf driven by a stub llm-client / stub gate seams (e.g. stub llm-client returning empty/malformed output; a may_confirm gate seam reporting failure/denial).

# Non-Goals

Do not build StageWorker, the seam assembler (build_default_seams), the conductor loop, or gated_advance. Do not implement get_task. Do not edit ngv2/llm_client.py or the four may_confirm gate modules in place — compose them only as injected seams. Do not weaken, bypass, or auto-pass any acceptance/may_confirm gate; do not auto-submit to huntr or contact any external service. No real LLM call, network, or subprocess may run inside any oracle. Do not implement poc/detonate/novelty/report logic (other children).

# Inputs

Each module exposes run_stage(context: dict, seams: dict) -> list[dict]. context originates from get_task(session_row: dict) -> {phase, target, prior_findings, parked_package}. seams carries the injected llm-client seam (matching ngv2/llm_client.py, read-only) and, for verify, the four injected may_confirm gate seams (matching the may_confirm gate modules, read-only). Reads (does not modify) ngv2/contracts.py dataclass Finding for output field names, ngv2/artifact_harvester.py parse_stage_artifact(filename, content, phase) for the artifact dict shape, and ngv2/session_db.py insert_finding for the persist-side shape.

# Deliverables

ngv2/workers/hunt.py, ngv2/workers/triage.py, ngv2/workers/verify.py — each exposing run_stage(context, seams) -> list[dict] of Finding-shaped artifact dicts parseable by artifact_harvester.parse_stage_artifact(filename, content, phase) and from which contracts.Finding can be built. Freezes the phase contract: run_stage(context: dict, seams: dict) -> list[dict]. Each file has a test_authoring sibling with mutation_target set to that file and a verification_command naming the authored oracle, covering at least two edge cases (stub llm-client empty/malformed output; a may_confirm gate seam reporting failure).
