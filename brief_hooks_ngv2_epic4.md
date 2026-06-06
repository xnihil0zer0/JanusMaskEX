---
working_dir: "/home/xnihil0zer0/NobleGreedv2"
epic: true
child_epics: true
---

# Title

NobleGreedv2 Epic-4: the COMPLETE remaining deterministic tooling — a maximal, FOUR-LEVEL
epic (root -> super-epic -> sub-epic -> leaf) that rebuilds every remaining JM-gatable
capability of the legacy NobleGreed bug-hunter into the external NobleGreedv2 repo.

# Scope

Decompose this epic into EXACTLY FOUR child briefs, and EACH child is ITSELF AN EPIC
(`epic: true`, `child_epics: true`, `plan_kind: epic`) that further decomposes into
SUB-EPICS, each of which decomposes into LEAF module briefs. This is a THREE-LEVEL
decomposition (epic -> super-epic -> sub-epic -> leaf; a depth-4 lineage). Every leaf is
a NEW single-file, whole-file, deterministic stdlib-only (or injected-seam) Python module
under the `ngv2/` package of the external NobleGreedv2 repo (its own git + venv), pinned
by a HAND-AUTHORED ORACLE ALREADY COMMITTED to the repo at `tests/test_<leaf>.py`, so
every leaf is IMPL-ONLY (must NOT author tests) and is verified with
`python -m pytest tests/test_<leaf>.py -q`.

This epic manufactures only the DETERMINISTIC, mock-testable tooling that surrounds
hunting — the dangerous LIVE work (firing real exploit PoCs at real targets, real
LLM/model calls, real GPU training, live huntr.com HTTP/Playwright) stays data-driven at
NobleGreedv2 runtime and is NOT built here. Where a non-deterministic dependency exists
(an external analyzer subprocess, an SMT solver, an HTTP transport), the leaf exposes a
PURE deterministic shell plus an INJECTED callable and is tested with a mock/scripted seam
(exactly the `ngv2.poc_runner` / `ngv2.semgrep_adapter` pattern). Leaves build ON TOP of
the ALREADY-COMMITTED Epic-1/2/3 spine (`ngv2.contracts`, `ngv2.state_machine`,
`ngv2.detonation`, `ngv2.grounding`, `ngv2.poc_runner`, `ngv2.report`, `ngv2.pipeline`,
and the Epic-3 intake/grounding/triage/submission modules), consumed only via plain
imports of stable, already-tested public shapes.

Produce these FOUR super-epic children with these exact slugs:

## Super-epic A — slug `ngv2-e4-analysis` (`epic: true`, `child_epics: true`)
Vulnerability DETECTION & grounding & adversarial verification. Decomposes into THREE
sub-epics: `ngv2-e4-grounding-pkg` (rule/AST scanners, false-positive knowledge base,
portfolio scan, pre-analysis cross-validation, taint-spec library, and the CodeQL/Joern
injected-runner shells), `ngv2-e4-adversarial-pkg` (root-cause classification, injection
scoring, evasion variant generation incl. model-file-format variants), and
`ngv2-e4-neurosymbolic-pkg` (AST constraint/verification, backtracking search, and the
z3 solver bridge with a rule-based fallback).

## Super-epic B — slug `ngv2-e4-gating` (`epic: true`, `child_epics: true`)
Target ELIGIBILITY/qualification & SAFETY validators. Decomposes into TWO sub-epics:
`ngv2-e4-eligibility-pkg` (target qualification, bounty payout lookup, repo-complexity &
web-framework & language & deserialization detection, the huntr-eligibility cache replay,
batch qualification) and `ngv2-e4-safety-pkg` (graduated permission model, bash-command
validation, prompt-integrity verification, the safety framework, prompt-hint accumulation).

## Super-epic C — slug `ngv2-e4-orchestration` (`epic: true`, `child_epics: true`)
Deterministic hunt ORCHESTRATION machinery (no live model/GPU). Decomposes into FOUR
sub-epics: `ngv2-e4-state-pkg` (worker registry, atomic state updates, anti-entropy
reconciliation, state sync, context compaction, fail-fast guards, phase prompt templating,
idempotent resume/task-similarity), `ngv2-e4-scheduling-pkg` (ROI cron scheduling, token-
bucket rate limiting, model-cascade fallback accounting), `ngv2-e4-workers-pkg` (sub-agent
registry & messaging, work-intent collision detection, worker-command dispatch/backpressure,
log-event watching), and `ngv2-e4-debate-pkg` (debate routing/synthesis, UCB1 RL agent
weighting, trace parsing, tool recommendation/registry/composition).

## Super-epic D — slug `ngv2-e4-knowledge-tools` (`epic: true`, `child_epics: true`)
KNOWLEDGE graph, persistence, submission TOOLING & analytics. Decomposes into THREE
sub-epics: `ngv2-e4-knowledge-pkg` (kg schema/config, idempotent kg store, codebase->graph
extraction, token-logging store, run-state ledger), `ngv2-e4-submission-tools-pkg`
(submission format parsing, JS PoC templating, crash analysis, duplicate/novelty detection,
submission-readiness scoring) and `ngv2-e4-analytics-pkg` (hunting-ROI tracking, portfolio
intelligence, operational analytics, revenue-acceleration planning).

# Non-Goals

No live exploit execution, no real LLM/model calls, no GPU training (RLCF/GraphMERT), no
live huntr.com HTTP or Playwright automation, no live MCP server processes — all deferred
to NobleGreedv2 runtime. No leaf authors tests (oracles already committed). No third-party
imports (stdlib only; injected seams for any external dependency). No cross-leaf wiring or
integration glue beyond plain imports of the already-committed spine. Slug discipline: no
sub-epic slug equals any leaf slug.

# Inputs

The external NobleGreedv2 repo at working_dir /home/xnihil0zer0/NobleGreedv2, already
containing the committed Epic-1/2/3 spine and, before execution, ALL Epic-4 leaf oracles
committed under tests/test_<leaf>.py. The legacy NobleGreed corpus at
/mnt/ai-data/NobleGreed-legacy/services (the durable design source) informs each leaf's
contract, but only the committed oracle is authoritative.

# Deliverables

Approximately SIXTY-SEVEN NEW single-file whole-file ngv2/ modules across 4 super-epics
and 12 sub-epics, each IMPL-only and pinned by its committed oracle, each verified with
`python -m pytest tests/test_<leaf>.py -q`. Every brief at every level carries
working_dir /home/xnihil0zer0/NobleGreedv2.
