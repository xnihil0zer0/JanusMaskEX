---
working_dir: "/home/xnihil0zer0/NobleGreedv2"
epic: true
child_epics: true
---

# Title

NobleGreedv2 Epic-4 — rebuild ALL remaining JanusMask-gatable deterministic tooling of the
legacy NobleGreed bug-hunter. This is a deliberately LARGE epic; YOU (the planner) decide how
to decompose it into a multi-level tree.

# Scope

NobleGreedv2 is a clean-room rebuild of an autonomous security bug-hunter, manufactured by
JanusMask's gated pipeline ("JM as factory"). The hunt->triage->poc->detonate->report->
submission SPINE already exists (the committed Epic-1/2/3 modules: ngv2.contracts,
state_machine, detonation, grounding, poc_runner, report, pipeline, plus the intake/grounding/
triage/submission leaves). Epic-4 rebuilds EVERYTHING THAT REMAINS deterministic and
JM-gatable around that spine.

Two correctness regimes define the boundary. DETERMINISTIC tooling (pure functions, stateful-
but-local state machines/stores, and shells around an INJECTED non-deterministic dependency)
is IN — JM gates it with oracle + fuzz/smoke. The dangerous LIVE work is OUT (deferred to the
NobleGreedv2 runtime): actually firing exploit PoCs at live targets, real LLM/model calls,
GPU/model training, live huntr.com HTTP/Playwright, live MCP server processes. The rule for
the in-between: wherever a non-determinism CAN be made an injected parameter (a subprocess
runner, an SMT solver, an HTTP transport, a clock, a model client), the deterministic shell
around it IS in scope and is tested with a mock/scripted seam (the ngv2.poc_runner /
ngv2.semgrep_adapter pattern) — the real dependency is never invoked by the factory.

# Your decomposition task

Decompose this epic into a MULTI-LEVEL tree of your own design (lineage depth up to 4:
root -> ... -> leaf). YOU decide the structure: how many intermediate epic levels each branch
needs, how to group the capabilities into super-epics and sub-epics, where the natural seams
and cohesion lie, and how wide vs deep to go. Mark every non-leaf brief `epic: true` (and
`child_epics: true` when its children are themselves epics). Give every child a kebab-case
slug; NO non-leaf slug may equal any leaf slug. Carry working_dir
/home/xnihil0zer0/NobleGreedv2 on every brief at every level.

Each LEAF is one NEW single-file, whole-file, stdlib-only (or injected-seam) Python module
under the ngv2/ package, IMPL-ONLY (it must NOT author tests — its contract is the oracle
ALREADY COMMITTED at tests/test_<leaf>.py, which the build receives via oracle-injection),
verified with `python -m pytest tests/test_<leaf>.py -q`. Reproduce each leaf's module name
EXACTLY as given below (the committed oracle imports `from ngv2.<name> import ...`, so the
module name is fixed by its contract; the leaf SET and their contracts are the ground truth —
only the HIERARCHY over them is yours to decide). Prefer leaves that are independent (no leaf
should import a sibling Epic-4 leaf); the only known intra-set coupling is that a work-intent
tracker naturally builds on the worker registry, which you should order/scope so the registry
lands first.

# The body of work — 67 capabilities to rebuild

Grouped below ONLY for readability; these four domains are NOT a prescribed structure — regroup,
split, or merge into whatever super-epic/sub-epic hierarchy you judge best.

**Static analysis, grounding & adversarial/neurosymbolic verification** (17 capabilities)

- `ngv2/pattern_scanner.py` [pure] — ngv2.pattern_scanner is a pure-stdlib regex vulnerability pattern scanner exposing VULN_PATTERNS, LANG_EXTENSIONS, scan_file, scan_directory.  (contract: committed oracle `tests/test_pattern_scanner.py`)
- `ngv2/fp_patterns.py` [pure] — ngv2.fp_patterns is a pure, stdlib-only false-positive knowledge base distilled from the legacy services/code_audit/fp_filter.py, with the legacy datetime.now() replaced by an injected `now` string seam for determinism.  (contract: committed oracle `tests/test_fp_patterns.py`)
- `ngv2/portfolio_scanner.py` [pure] — ngv2.portfolio_scanner is a pure, stdlib-only portfolio reconciliation tool that classifies a directory of markdown findings files by huntr eligibility and detects orphaned artifacts.  (contract: committed oracle `tests/test_portfolio_scanner.py`)
- `ngv2/pre_analysis.py` [orchestration-glue] — ngv2.pre_analysis is the deterministic pre-analysis merge layer that orchestrates two static scanners (semgrep adapter + regex pattern scanner) and cross-references their findings into one structured report for prompt injection.  (contract: committed oracle `tests/test_pre_analysis.py`)
- `ngv2/taint_spec_library.py` [pure] — ngv2.taint_spec_library is a pure, stdlib-only loader/validator for the CodeQL taint-spec library that NobleGreedv2 ships.  (contract: committed oracle `tests/test_taint_spec_library.py`)
- `ngv2/codeql_runner.py` [injected-seam] — ngv2.codeql_runner is an INJECTED-SEAM module: a pure, deterministic, stdlib-only shell around the CodeQL CLI that never invokes the real `codeql` binary.  (contract: committed oracle `tests/test_codeql_runner.py`)
- `ngv2/joern_runner.py` [injected-seam] — ngv2.joern_runner is an INJECTED-SEAM wrapper distilling the legacy Joern CPG taint-analysis capability into a pure, deterministic, stdlib-only shell.  (contract: committed oracle `tests/test_joern_runner.py`)
- `ngv2/root_cause.py` [pure] — ngv2.root_cause is a pure, deterministic, stdlib-only adversarial root-cause analyzer that explains why a detection pipeline missed an injected vulnerability and recommends a corrective artifact.  (contract: committed oracle `tests/test_root_cause.py`)
- `ngv2/adversarial_scorer.py` [pure] — ngv2.adversarial_scorer is a pure, deterministic, stdlib-only scorer that compares a sealed adversarial injection log against a scan-results file and reports which pipeline layers detected each injected vulnerability.  (contract: committed oracle `tests/test_adversarial_scorer.py`)
- `ngv2/variant_generator.py` [pure] — ngv2.variant_generator is a pure, deterministic, stdlib-only adversarial evasion-variant generator.  (contract: committed oracle `tests/test_variant_generator.py`)
- `ngv2/mff_root_cause.py` [pure] — ngv2.mff_root_cause is a pure, stdlib-only deterministic root-cause analyzer for model-file-format (MFF) parser fuzz results; it never loads model files or runs parsers, it only classifies score entries and emits detection rules.  (contract: committed oracle `tests/test_mff_root_cause.py`)
- `ngv2/mff_variant_generator.py` [pure] — ngv2.mff_variant_generator is a pure, deterministic, stdlib-only (pickle, struct, zlib, lzma, bz2, zipfile, json, io, os, pathlib) generator of evasion variants of malicious model-file payloads — it NEVER executes any payload (pickle obj...  (contract: committed oracle `tests/test_mff_variant_generator.py`)
- `ngv2/mff_scorer.py` [injected-seam] — ngv2.mff_scorer is an INJECTED-SEAM module that scores ML-model-file parser robustness against crafted malicious files, with all external effects (file crafting + subprocess parser execution) supplied as injected callables so JM never to...  (contract: committed oracle `tests/test_mff_scorer.py`)
- `ngv2/ast_constraint.py` [pure] — ngv2.ast_constraint is a pure, stdlib-only (ast module) code-safety gate that scans Python source strings for dangerous/sloppy patterns and returns a deterministic list of violation dicts.  (contract: committed oracle `tests/test_ast_constraint.py`)
- `ngv2/ast_verifier.py` [pure] — ngv2/ast_verifier.py is a pure, stdlib-only (ast module) symbolic policy verifier for Python source — no network/LLM/subprocess/randomness.  (contract: committed oracle `tests/test_ast_verifier.py`)
- `ngv2/backtrack.py` [stateful] — ngv2.backtrack is a deterministic, stdlib-only stateful retry shell for symbolic code validation driven by an injected verification seam.  (contract: committed oracle `tests/test_backtrack.py`)
- `ngv2/z3_bridge.py` [injected-seam] — ngv2.z3_bridge is an injected-seam neurosymbolic invariant checker: a PURE deterministic shell plus an OPTIONAL injected solver callable so the factory never imports real z3.  (contract: committed oracle `tests/test_z3_bridge.py`)

**Target eligibility/qualification & safety/permission gating** (13 capabilities)

- `ngv2/target_qualify.py` [pure] — ngv2.target_qualify is a pure, deterministic, stdlib-only qualification gate (distilled from legacy services/qualify_target.py) deciding whether a security-hunt target is worth pursuing, with ALL filesystem/clock/network I/O replaced by ...  (contract: committed oracle `tests/test_target_qualify.py`)
- `ngv2/bounty_gate.py` [pure] — ngv2.bounty_gate is a PURE, stdlib-only economic gate deciding GO/SKIP/UNKNOWN for hunting an owner/repo + CWE + severity from an INJECTED bounty-data dict (passed as keyword `bounties` — no disk/network/clock/random in the tested surface).  (contract: committed oracle `tests/test_bounty_gate.py`)
- `ngv2/repo_complexity.py` [pure] — ngv2/repo_complexity.py is a pure deterministic stdlib-only repo triage tool (gate class pure_fuzz).  (contract: committed oracle `tests/test_repo_complexity.py`)
- `ngv2/web_framework_detect.py` [pure] — ngv2.web_framework_detect is a pure, stdlib-only (os/re/pathlib) recon leaf that detects Python web frameworks in a repo by scanning dependency files and .py sources.  (contract: committed oracle `tests/test_web_framework_detect.py`)
- `ngv2/language_patterns.py` [pure] — ngv2.language_patterns is a pure, deterministic, stdlib-only static-pattern database mapping programming languages to CWE-tagged vulnerability regex patterns.  (contract: committed oracle `tests/test_language_patterns.py`)
- `ngv2/deser_detect.py` [pure] — ngv2/deser_detect.py is a pure, deterministic, stdlib-only filesystem scanner for CWE-502 (unsafe deserialization) recon, gate class pure_fuzz.  (contract: committed oracle `tests/test_deser_detect.py`)
- `ngv2/huntr_eligible_cache.py` [pure] — ngv2.huntr_eligible_cache is a pure, deterministic, stdlib-only shell deciding huntr.com bounty eligibility for an "owner/repo" string via a previously-fetched bounties cache.  (contract: committed oracle `tests/test_huntr_eligible_cache.py`)
- `ngv2/batch_qualify.py` [orchestration-glue] — ngv2.batch_qualify is a deterministic, stdlib-only batch target-qualification shell with an INJECTED qualifier seam (it never calls the real target_qualify / network).  (contract: committed oracle `tests/test_batch_qualify.py`)
- `ngv2/permission_model.py` [pure] — ngv2.permission_model is a pure, stdlib-only graduated permission model for NobleGreedv2 workers.  (contract: committed oracle `tests/test_permission_model.py`)
- `ngv2/bash_validator.py` [pure] — ngv2/bash_validator.py is a pure, deterministic, stdlib-only bash-command validation pipeline (no subprocess/network/LLM — it only inspects the command STRING).  (contract: committed oracle `tests/test_bash_validator.py`)
- `ngv2/prompt_integrity.py` [pure] — ngv2.prompt_integrity is a deterministic, stdlib-only SHA-256 integrity registry for protected prompt/template files, distilled from the legacy services/prompt_integrity.py.  (contract: committed oracle `tests/test_prompt_integrity.py`)
- `ngv2/safety_framework.py` [stateful] — ngv2.safety_framework is a deterministic, stdlib-only safety state machine with an injected-seam shell — no clock, network, subprocess, or global on-disk state in its tested paths.  (contract: committed oracle `tests/test_safety_framework.py`)
- `ngv2/prompt_hints.py` [pure] — ngv2.prompt_hints is a pure, stdlib-only manager for an append-only "Operational Hints" section inside a prompt Markdown file.  (contract: committed oracle `tests/test_prompt_hints.py`)

**Deterministic hunt orchestration: state, scheduling, workers, debate** (22 capabilities)

- `ngv2/worker_registry.py` [stateful] — ngv2.worker_registry exposes a deterministic, SQLite-backed WorkerRegistry class plus module constants WORKER_STATUSES=('running','completed','failed','crashed','suspended','resumed','expired'), STALE_THRESHOLD_S=1800, GPU_STALE_THRESHOL...  (contract: committed oracle `tests/test_worker_registry.py`)
- `ngv2/state_update.py` [pure] — ngv2.state_update is a deterministic, stdlib-only, flock-protected JSON state updater (a clean-room distillation of legacy services/state_update.py) with an injected file-path seam so it is hermetic and testable without touching real on-...  (contract: committed oracle `tests/test_state_update.py`)
- `ngv2/anti_entropy.py` [stateful] — ngv2.anti_entropy is a deterministic, stdlib-only anti-entropy reconciliation shell with an INJECTED environment seam so no real DB/clock/network/process inspection is needed.  (contract: committed oracle `tests/test_anti_entropy.py`)
- `ngv2/state_sync.py` [pure] — ngv2.state_sync provides two pure, deterministic, idempotent functions that reconcile a NobleGreedv2 run-state dict against injected data sources, returning a list of human-readable change-description strings while mutating `state` in pl...  (contract: committed oracle `tests/test_state_sync.py`)
- `ngv2/compactor.py` [pure] — ngv2.compactor is a pure, stdlib-only, deterministic context-compaction decision/prompt helper (no network/LLM/clock/random).  (contract: committed oracle `tests/test_compactor.py`)
- `ngv2/fail_fast.py` [pure] — ngv2.fail_fast is a pure, stdlib-only silent-failure-prevention utility with three severity tiers (fatal/warn/trace) plus two boundary assertions, used in place of bare `except: pass`.  (contract: committed oracle `tests/test_fail_fast.py`)
- `ngv2/phase_runner.py` [pure] — ngv2.phase_runner is a PURE, deterministic, stdlib-only phase-dispatch helper for the self-chaining hunt cron orchestrator (distilled from legacy orchestrator/phase_runner.py; NO filesystem reads, NO live state load, NO network, NO clock...  (contract: committed oracle `tests/test_phase_runner.py`)
- `ngv2/task_similarity.py` [pure] — ngv2.task_similarity is a pure, deterministic, stdlib-only module distilling NobleGreed-legacy's worker suspend/resume task-matching core.  (contract: committed oracle `tests/test_task_similarity.py`)
- `ngv2/dynamic_scheduler.py` [pure] — ngv2.dynamic_scheduler is a PURE, deterministic, stdlib-only scheduling advisor (gate: pure_fuzz) that converts evaluation metrics in a state dict into per-chain ROI estimates and threshold-based cron-frequency recommendations.  (contract: committed oracle `tests/test_dynamic_scheduler.py`)
- `ngv2/rate_limiter.py` [pure] — ngv2/rate_limiter.py is a deterministic, stdlib-only cooldown gate for external API calls, distilled from the legacy services/rate_limiter.py.  (contract: committed oracle `tests/test_rate_limiter.py`)
- `ngv2/model_cascade.py` [stateful] — ngv2.model_cascade is a deterministic, stdlib-only model-fallback state machine over an INJECTED clock seam (never the real wall clock, disk, network, or randomness).  (contract: committed oracle `tests/test_model_cascade.py`)
- `ngv2/agent_registry.py` [stateful] — ngv2.agent_registry exposes an AgentRegistry class — a deterministic, stdlib-only (sqlite3) registry of sub-agents and inter-agent messages, mirroring the ngv2.worker_registry pattern with time as the single injected seam.  (contract: committed oracle `tests/test_agent_registry.py`)
- `ngv2/work_intent_tracking.py` [stateful] — ngv2.work_intent_tracking is a deterministic coordination layer over the built ngv2.worker_registry.WorkerRegistry that prevents two RUNNING workers from doing the same kind of work on the same target.  (contract: committed oracle `tests/test_work_intent_tracking.py`)
- `ngv2/worker_command_dispatch.py` [stateful] — ngv2.worker_command_dispatch is a deterministic, stdlib-only (sqlite3) overseer->worker command-delivery shell over a `worker_commands` SQLite table, mirroring the durable legacy capability.  (contract: committed oracle `tests/test_worker_command_dispatch.py`)
- `ngv2/log_watcher.py` [stateful] — ngv2.log_watcher is a deterministic, stdlib-only (json/pathlib/datetime/collections.defaultdict) log-watching rule engine for the NobleGreedv2 overseer.  (contract: committed oracle `tests/test_log_watcher.py`)
- `ngv2/debate_router.py` [pure] — ngv2.debate_router is a pure, deterministic, stdlib-only triage router that decides how a GraphMERT-scored vulnerability finding should be handled, distilled from the legacy debate_pool routing logic (the LLM/MASFactory debate machinery ...  (contract: committed oracle `tests/test_debate_router.py`)
- `ngv2/debate_synthesis.py` [pure] — ngv2.debate_synthesis is a pure, deterministic, stdlib-only module that synthesizes a rule-based multi-agent "debate" verdict for a borderline vulnerability finding — NO LLM/network/clock/random.  (contract: committed oracle `tests/test_debate_synthesis.py`)
- `ngv2/rl_debate_weights.py` [stateful] — ngv2.rl_debate_weights is a pure, deterministic, in-memory multi-armed-bandit (UCB1) controller that learns debate-agent weights from triage outcomes; it has NO file I/O, NO clock, and NO randomness (the legacy JSONL/datetime persistence...  (contract: committed oracle `tests/test_rl_debate_weights.py`)
- `ngv2/trace_parser.py` [pure] — ngv2.trace_parser is a pure, deterministic, stdlib-only module that turns raw NobleGreed execution-log entries (plain dicts) into structured signals for the RLCF training pipeline.  (contract: committed oracle `tests/test_trace_parser.py`)
- `ngv2/tool_recommender.py` [pure] — ngv2.tool_recommender is a pure, stdlib-only deterministic tool-selection scorer distilled from the legacy NobleGreed recommender.  (contract: committed oracle `tests/test_tool_recommender.py`)
- `ngv2/tool_registry.py` [pure] — ngv2.tool_registry is a deterministic, stdlib-only registry for auto-generated tools, distilled from legacy services/tool_forge.py with all impure side-effects pushed behind explicit injected seams so it is fully testable.  (contract: committed oracle `tests/test_tool_registry.py`)
- `ngv2/masf_tool_composer.py` [pure] — ngv2.masf_tool_composer is a pure, stdlib-only tool-composition shell that turns a dispatch_table (dict[str,Callable]) into a list of typed agent-facing tool callables, with all live wiring injected.  (contract: committed oracle `tests/test_masf_tool_composer.py`)

**Knowledge graph, persistence/ledger, submission tooling & analytics** (15 capabilities)

- `ngv2/kg_schema.py` [pure] — ngv2.kg_schema is a pure, deterministic pydantic-v2 data-model module defining the NobleGreedv2 knowledge-graph schema (no clock/network/random; created_at/discovered_at default to None, NOT datetime.utcnow).  (contract: committed oracle `tests/test_kg_schema.py`)
- `ngv2/kg_config.py` [pure] — ngv2/kg_config.py exposes a typed configuration object Settings (a pydantic_settings.BaseSettings subclass) plus a module-level singleton `settings = Settings()`.  (contract: committed oracle `tests/test_kg_config.py`)
- `ngv2/kg_store.py` [stateful] — ngv2.kg_store provides KGStore, a deterministic, stdlib-only (sqlite3) dual-backend knowledge store for the NobleGreed economic domain.  (contract: committed oracle `tests/test_kg_store.py`)
- `ngv2/codebase_graph_extract.py` [pure] — ngv2.codebase_graph_extract is a pure, deterministic, stdlib-only (ast, re, json, pathlib) converter that turns a Python/shell codebase into MASFactory-compatible "vibe graph" JSON — no AI, no network, no code execution; it only reads so...  (contract: committed oracle `tests/test_codebase_graph_extract.py`)
- `ngv2/token_logger.py` [stateful] — ngv2.token_logger is a deterministic, stdlib-only (sqlite3) cost/usage ledger.  (contract: committed oracle `tests/test_token_logger.py`)
- `ngv2/state_ledger.py` [stateful] — ngv2.state_ledger is a deterministic, stdlib-only (json, fcntl, pathlib, sys) atomic JSON state ledger distilled from legacy services/state_update.py.  (contract: committed oracle `tests/test_state_ledger.py`)
- `ngv2/submission_parser.py` [pure] — ngv2.submission_parser is a pure, stdlib-only (re/dataclasses/pathlib) deterministic parser that turns submission-ready markdown files into structured FindingSubmission records (the durable capability distilled from legacy huntr_submitte...  (contract: committed oracle `tests/test_submission_parser.py`)
- `ngv2/js_poc_templates.py` [pure] — ngv2.js_poc_templates is a pure, deterministic, stdlib-only generator of JavaScript/Node.js PoC scaffolding templates for huntr.com submissions (no network/LLM/exploit execution — gate class pure_fuzz).  (contract: committed oracle `tests/test_js_poc_templates.py`)
- `ngv2/crash_analyzer.py` [pure] — ngv2.crash_analyzer is a pure, stdlib-only worker-failure diagnostics shell.  (contract: committed oracle `tests/test_crash_analyzer.py`)
- `ngv2/dedup_novelty.py` [pure] — ngv2.dedup_novelty is a pure, deterministic, stdlib-only similarity/novelty layer distilled from the legacy dedup_checker.  (contract: committed oracle `tests/test_dedup_novelty.py`)
- `ngv2/submission_readiness.py` [pure] — ngv2.submission_readiness is a pure, stdlib-only deterministic submission-readiness scorer for NobleGreedv2.  (contract: committed oracle `tests/test_submission_readiness.py`)
- `ngv2/hunting_roi_tracker.py` [stateful] — ngv2.hunting_roi_tracker is a pure, stdlib-only deterministic session-ROI tracker that decides when a hunting run should stop hunting and switch to PoC work.  (contract: committed oracle `tests/test_hunting_roi_tracker.py`)
- `ngv2/portfolio_intel.py` [pure] — ngv2/portfolio_intel.py is a pure, deterministic, stdlib-only strategic-analytics module distilled from the legacy portfolio_intel tool (all rich/sqlite/yaml/network I/O removed, replaced by an injected data seam).  (contract: committed oracle `tests/test_portfolio_intel.py`)
- `ngv2/ops_analytics.py` [pure] — ngv2/ops_analytics.py is a PURE, deterministic, stdlib-only operational-analytics engine distilled from the legacy CLI tool (all sqlite/yaml/clock/CLI/printing cruft removed; functions operate only on plain list[dict]/dict inputs passed ...  (contract: committed oracle `tests/test_ops_analytics.py`)
- `ngv2/revenue_accelerator.py` [pure] — ngv2.revenue_accelerator is a pure, deterministic, stdlib-only ROI work planner distilled from the legacy revenue_accelerator (drop all sqlite/filesystem/subprocess/printing cruft).  (contract: committed oracle `tests/test_revenue_accelerator.py`)

# Suggested decomposition (a non-binding starting point, not an instruction)

One reasonable shape is four super-epics aligned to the four domains above, each split into a
few cohesive sub-epics (e.g. analysis -> grounding / adversarial / neurosymbolic; gating ->
eligibility / safety; orchestration -> state / scheduling / workers / debate; knowledge-tools
-> knowledge / submission-tools / analytics), each sub-epic decomposing into its leaves. You
are free to adopt, adapt, or reject this — decide based on cohesion, leaf independence, and a
balanced tree. Whatever you choose, every one of the 67 leaf modules above must appear exactly
once as a leaf.

# Non-Goals

No live exploit execution, real LLM/model calls, GPU/RLCF/GraphMERT training, live huntr.com
HTTP/Playwright, or live MCP server processes (all deferred to NobleGreedv2 runtime). No leaf
authors tests (oracles already committed). No third-party imports (stdlib only; injected seams
for any external dependency). No cross-leaf wiring beyond plain imports of the already-committed
spine. No leaf depends on a sibling Epic-4 leaf (except the registry/work-intent ordering noted
above).

# Inputs

The external NobleGreedv2 repo at working_dir /home/xnihil0zer0/NobleGreedv2, already holding
the committed Epic-1/2/3 spine (ngv2.contracts.Finding/PoC/LiveTestReport etc.) AND all 67
Epic-4 leaf oracles under tests/test_<leaf>.py (committed and authoritative). The legacy
NobleGreed corpus at /mnt/ai-data/NobleGreed-legacy (services/, orchestrator/, knowledge/) is
the durable design source each capability distils; only the committed oracle is authoritative
for a build.

# Deliverables

67 NEW single-file whole-file ngv2/*.py modules (the leaf set above), each IMPL-only and
pinned by its committed oracle, each verified with `python -m pytest tests/test_<leaf>.py -q`,
organized under the multi-level epic hierarchy YOU decompose. Every brief at every level carries
working_dir /home/xnihil0zer0/NobleGreedv2.
