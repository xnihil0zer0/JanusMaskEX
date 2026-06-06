---
working_dir: "/home/xnihil0zer0/NobleGreedv2"
epic: true
child_epics: true
---

# Title

Super-epic D — ngv2-e4-knowledge-tools: knowledge graph, persistence, submission tooling & analytics (epic: true, child_epics: true)

# Scope

An epic (`epic: true`, `child_epics: true`, `plan_kind: epic`) that decomposes into EXACTLY
THREE sub-epic children, each itself an epic (`epic: true`, `plan_kind: epic`) decomposing
into leaf modules under the `ngv2/` package of the external NobleGreedv2 repo (working_dir
/home/xnihil0zer0/NobleGreedv2). The three sub-epics:

## Sub-epic D1 — slug `ngv2-e4-knowledge-pkg` (`epic: true`)
SIX leaves: knowledge-graph schema, kg config/settings, idempotent kg store, codebase->graph
AST extraction, token-logging store, run-state ledger (idempotent persistence/resume).

## Sub-epic D2 — slug `ngv2-e4-submission-tools-pkg` (`epic: true`)
FIVE leaves: submission file-format parsing (multiple markdown dialects), JavaScript PoC
template generation, crash & failure analysis, duplicate/novelty detection (string
similarity, NOT live HTTP), submission-readiness scoring & artifact validation.

## Sub-epic D3 — slug `ngv2-e4-analytics-pkg` (`epic: true`)
FOUR leaves: hunting-session ROI tracking, portfolio intelligence analytics, operational
analytics, revenue-acceleration work planning.

Each leaf is a NEW single-file whole-file deterministic stdlib-only Python module, IMPL-only
(its oracle is already committed at tests/test_<leaf>.py), verified with
`python -m pytest tests/test_<leaf>.py -q`. Store-bearing leaves (kg_store, token_logger,
state_ledger, hunting_roi_tracker) are `stateful_fuzz`-gated (local on-disk state, atomic
idempotent writes). Leaves are mutually independent and may build in any order; they consume
only the already-committed ngv2 spine via plain imports.

# Non-Goals

No live huntr.com checks (dedup/novelty uses string similarity over committed corpus, not
HTTP). No GPU/ML training (RLCF/GraphMERT deferred). No graph DB server (kg_store is an
idempotent local store; an external backend would be an injected seam, not built here). No
leaf authors tests. No third-party imports (stdlib only). No cross-leaf wiring.

# Inputs

The external NobleGreedv2 repo with the committed spine and the committed Epic-4
D-super-epic leaf oracles. Legacy design source: /mnt/ai-data/NobleGreed-legacy/knowledge/graph
(schema.py, kg_store.py), /knowledge (config.py), /services (codebase_to_graph.py,
token_logger.py) and /services/tools (submission_pipeline.py, js_poc_template.py,
crash_analyzer.py, dedup_checker.py, hunting_roi_tracker.py, portfolio_intel.py,
ops_analytics.py, revenue_accelerator.py, submission scorer).

# Deliverables

Fifteen NEW single-file whole-file ngv2/ modules across the three sub-epics, each IMPL-only
and pinned by its committed oracle, each verified with
`python -m pytest tests/test_<leaf>.py -q`. Every brief carries working_dir
/home/xnihil0zer0/NobleGreedv2.
