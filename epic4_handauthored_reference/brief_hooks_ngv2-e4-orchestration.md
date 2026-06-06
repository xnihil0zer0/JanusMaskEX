---
working_dir: "/home/xnihil0zer0/NobleGreedv2"
epic: true
child_epics: true
---

# Title

Super-epic C — ngv2-e4-orchestration: deterministic hunt orchestration machinery (epic: true, child_epics: true)

# Scope

An epic (`epic: true`, `child_epics: true`, `plan_kind: epic`) that decomposes into EXACTLY
FOUR sub-epic children, each itself an epic (`epic: true`, `plan_kind: epic`) decomposing
into leaf modules under the `ngv2/` package of the external NobleGreedv2 repo (working_dir
/home/xnihil0zer0/NobleGreedv2). The four sub-epics:

## Sub-epic C1 — slug `ngv2-e4-state-pkg` (`epic: true`)
EIGHT leaves: worker registry & process tracking, atomic state JSON updates, anti-entropy
state reconciliation, distributed state sync, context-compaction decision, fail-fast guards,
phase prompt templating/trigger building, and idempotent resume via task-similarity.

## Sub-epic C2 — slug `ngv2-e4-scheduling-pkg` (`epic: true`)
THREE leaves: dynamic ROI-based cron scheduling, token-bucket rate limiting, model-cascade
& rate-limit fallback accounting (deterministic state; no live model call).

## Sub-epic C3 — slug `ngv2-e4-workers-pkg` (`epic: true`)
FOUR leaves: sub-agent registry & messaging, work-intent collision detection, worker-command
delivery with execution backpressure, log-event watching.

## Sub-epic C4 — slug `ngv2-e4-debate-pkg` (`epic: true`)
SEVEN leaves: debate routing, local debate synthesis, UCB1 RL agent weighting, trace
parsing & outcome inference, tool-recommendation scoring, tool registry/forge, MASF tool
composition.

Each leaf is a NEW single-file whole-file deterministic stdlib-only Python module, IMPL-only
(its oracle is already committed at tests/test_<leaf>.py), verified with
`python -m pytest tests/test_<leaf>.py -q`. State-bearing leaves are `stateful_fuzz`-gated
(local in-process/on-disk state only, atomic writes). Leaves are mutually independent and
may build in any order; they consume only the already-committed ngv2 spine via plain imports.

# Non-Goals

No live model/LLM calls (the model-cascade and debate modules track state and route only;
the actual model call is an injected seam deferred to runtime). No live worker process spawn
(worker registry/dispatch tracks state and builds commands; spawning is runtime). No leaf
authors tests. No third-party imports (stdlib only). No cross-leaf wiring.

# Inputs

The external NobleGreedv2 repo with the committed spine and the committed Epic-4
C-super-epic leaf oracles. Legacy design source: /mnt/ai-data/NobleGreed-legacy/orchestrator
(phase_runner.py, worker_registry.py, state_sync.py, state_machine.py) and /services
(state_update.py, anti_entropy.py, compactor.py, fail_fast.py, task_similarity.py,
dynamic_scheduler.py, rate_limiter.py, model_cascade.py, trace_parser.py, prompt_hints.py,
tool_recommender.py, tool_forge.py, masf_tools.py) and /services/debate_triage
(debate_pool.py, rl_controller.py).

# Deliverables

Twenty-two NEW single-file whole-file ngv2/ modules across the four sub-epics, each IMPL-only
and pinned by its committed oracle, each verified with
`python -m pytest tests/test_<leaf>.py -q`. Every brief carries working_dir
/home/xnihil0zer0/NobleGreedv2.
