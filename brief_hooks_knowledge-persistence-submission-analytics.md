---
interfaces: "ngv2.kg_config exposes class Settings(pydantic_settings.BaseSettings) plus module-level singleton settings = Settings(). ngv2.kg_schema is a pydantic-v2 schema whose created_at/discovered_at default to None (not datetime.utcnow). ngv2.kg_store exposes class KGStore (sqlite3 dual-backend). ngv2.submission_parser turns markdown into FindingSubmission records (re/dataclasses/pathlib). ngv2.portfolio_intel and ngv2.ops_analytics operate on injected plain list[dict]/dict data seams. All exact signatures are frozen by the committed oracles tests/test_<leaf>.py."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
epic: true
child_epics: true
---

# Title

Knowledge graph, persistence/ledger, submission tooling & analytics super-epic

# Scope

EPIC (epic: true, child_epics: true), working_dir /home/xnihil0zer0/NobleGreedv2. This non-leaf super-epic will be re-planned into sub-epics and leaves. It owns the deterministic knowledge-graph schema/config/store, persistence ledgers, submission-prep tooling, and strategic/operational analytics. Natural sub-seams for the recursive planner: (a) knowledge graph & extraction (kg_schema, kg_config, kg_store, codebase_graph_extract), (b) persistence & ledgers (token_logger, state_ledger), (c) submission tooling (submission_parser, js_poc_templates, crash_analyzer, dedup_novelty, submission_readiness), (d) analytics & ROI (hunting_roi_tracker, portfolio_intel, ops_analytics, revenue_accelerator). It rebuilds EXACTLY these 15 leaf modules, each a NEW single-file, whole-file, stdlib-only (or injected-seam) ngv2/*.py module, IMPL-only, pinned by its committed oracle tests/test_<leaf>.py and verified with `python -m pytest tests/test_<leaf>.py -q`: ngv2/kg_schema.py [pure pydantic-v2 schema; created_at/discovered_at default to None], ngv2/kg_config.py [pure; Settings(pydantic_settings.BaseSettings) + singleton settings=Settings()], ngv2/kg_store.py [stateful, sqlite3 dual-backend KGStore], ngv2/codebase_graph_extract.py [pure; ast/re/json/pathlib; reads source only, no execution], ngv2/token_logger.py [stateful, sqlite3 cost/usage ledger], ngv2/state_ledger.py [stateful; json/fcntl/pathlib/sys atomic JSON ledger], ngv2/submission_parser.py [pure; re/dataclasses/pathlib -> FindingSubmission records], ngv2/js_poc_templates.py [pure, gate pure_fuzz; no exploit execution], ngv2/crash_analyzer.py [pure], ngv2/dedup_novelty.py [pure similarity/novelty], ngv2/submission_readiness.py [pure scorer], ngv2/hunting_roi_tracker.py [stateful session-ROI tracker], ngv2/portfolio_intel.py [pure; injected data seam], ngv2/ops_analytics.py [pure; plain list[dict]/dict inputs], ngv2/revenue_accelerator.py [pure ROI work planner]. NOTE: kg_schema/kg_config are declared pure pydantic/pydantic_settings data models pinned by their committed oracles; honor the oracle's exact import surface for these two.

# Non-Goals

Does NOT author tests (oracles already committed). NO real network/clock/subprocess in tested surfaces (inject data seams; codebase_graph_extract reads source only and never executes code; js_poc_templates emits scaffolding only and never runs exploits), NO real LLM/model calls, NO GPU/training, NO live huntr.com HTTP/Playwright, NO MCP processes. NO leaf may import a sibling Epic-4 leaf. Does NOT build any leaf belonging to the analysis, eligibility/safety, or orchestration super-epics. Aside from the kg_schema/kg_config pydantic data-model surface pinned by their oracles, prefer stdlib-only with injected seams.

# Inputs

The external NobleGreedv2 repo at working_dir /home/xnihil0zer0/NobleGreedv2 with the committed Epic-1/2/3 spine (ngv2.contracts.Finding/PoC/LiveTestReport etc., plus the committed intake/grounding/triage/submission leaves). The 15 committed authoritative oracles tests/test_<leaf>.py for the modules listed in scope. The legacy NobleGreed corpus at /mnt/ai-data/NobleGreed-legacy (services/state_update.py, huntr_submitter, dedup_checker, portfolio_intel, revenue_accelerator, knowledge/) is the durable design source to distil; only the committed oracle is authoritative per build. No sibling-super-epic symbols are consumed.

# Deliverables

15 NEW single-file whole-file ngv2/*.py modules (the leaf roster in scope), each IMPL-only and pinned by its committed oracle, each verified with `python -m pytest tests/test_<leaf>.py -q`, organized under a sub-epic hierarchy the recursive planner decomposes. ngv2.kg_config exposes a typed Settings (pydantic_settings.BaseSettings subclass) plus a module-level singleton `settings = Settings()`; ngv2.kg_schema defines the pydantic-v2 KG schema with created_at/discovered_at defaulting to None; ngv2.submission_parser produces FindingSubmission records. Every brief at every level below this one carries working_dir /home/xnihil0zer0/NobleGreedv2. This super-epic produces NO symbol consumed by a sibling super-epic.
