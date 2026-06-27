---
name: ngv2-cleanroom-rebuild-plan
description: "NEXT BIG PROJECT (decided 2026-06-05) — clean-room rebuild NobleGreed as NobleGreedv2 at /home/xnihil0zer0/NobleGreedv2, BUILT BY JanusMaskJR's gated pipeline (JM-as-factory). Driver = reliability (legacy NG was vibe-coded/unstable). Handoff = NOBLEGREEDV2_REBUILD_HANDOFF.md."
metadata:
  node_type: memory
  type: project
  originSessionId: f4f9bbf8-b6f9-43ec-99ba-5c949731b48f
---

DECIDED 2026-06-05 (after a 2-agent assessment of both codebases). The next big
project is a **clean-room rebuild of NobleGreed as "NobleGreedv2"**, not porting the bug
hunter into JanusMaskJR and not keeping legacy NG. **Driver = RELIABILITY**: legacy
NG (`/mnt/ai-data/NobleGreed-legacy`) was built with autoresearch + vibe coding and
is unstable; JM was built to be reliable, so JM BUILDS NobleGreedv2.

**THE MODEL — "JM as factory":** use JM's proven, gated, hands-off pipeline to BUILD
NobleGreedv2's *deterministic tooling* (orchestrator skeleton, detonation-chamber harness,
finding/PoC/report artifact contract, grounding adapters, state machine). NobleGreedv2's
RUNTIME later does the dangerous, non-deterministic work (running exploit PoCs vs live
targets) — JM never runs exploits, it only manufactures the deterministic code that
NobleGreedv2's runtime will use. This SIDESTEPS JM's architectural impedance (AST eval/exec
ban, mutation/determinism gate, commit-as-output all fight a *hunting runtime* but
LOVE deterministic tooling). The antidote to "vibe-coded + unstable" is JM's
oracle-first + mutation-gated build loop.

**WHY NOT host hunting inside JM (assessed + rejected):** JM's three signature gates
are irrelevant/hostile to a hunting workload — eval/exec banned (relax is path-based,
not workload-based: `ast_enforcer.py:70`, `relax_external_for`), mutation gate assumes
determinism (PoCs aren't), output contract is a committed patch (a finding/PoC/report
isn't). And JM's hooks are per-tool SAFETY gates, NOT workflow-sequencing — "hooks
enforce the hunt→PoC→test pipeline" does NOT exist today; it'd be net-new.

**KEEP (NG legacy artifacts — the real value):** the Claude subagent prompts
(`.claude/agents/ng-hunter`, `ng-mff-hunter`=model-file-format, `ng-poc-writer`,
`ng-verifier`, `ng-triage`), huntr eligibility/bounty data (`data/huntr_*.json`), the
grounding approach (semgrep/joern/codeql + taint specs), and the shipped
`huntr-submission-packages/*/_poc.js` as a GOLDEN REGRESSION CORPUS for NobleGreedv2's
detonation harness. **HARVEST from JM (reliability primitives):** bwrap jail +
synthesis-shared-net / `--unshare-net` split (→ reproducible "detonation chamber"),
the hook-dispatch architecture (a clean seam to ADD phase gating), the autowork-daemon
resilience, ledger/state-machine discipline.

**TWO CORRECTNESS REGIMES (the clean architectural seam):** deterministic tooling →
JM oracle+mutation gate; non-deterministic findings/PoCs → live DETONATION verdict
(reproducible, logged, idempotent harness). Build the tooling JM-gated; build the
detonation harness as deterministic code that ORCHESTRATES detonation (test it with a
mock target/PoC).

**SEQUENCING:** Epic #1 = SUBSTRATE BEACHHEAD (detonation chamber + artifact contract
+ minimal state-machine skeleton + NobleGreedv2 project skeleton/venv/test harness) — all
deterministic, hand-authored child DAG, SINGLE LEVEL (do NOT auto-recurse a cold
domain). Epic #2+ = the hunt→triage→PoC→detonate→report pipeline, authored AFTER #1
lands and the leaf shapes in this domain are proven.

**LOCATION + INFRA:** `/home/xnihil0zer0/NobleGreedv2` — needs its OWN git
repo + OWN venv. JM builds INTO it as EXTERNAL-TARGET tasks (`working_dir` injected at
stage-time via trusted `stage_task(working_dir=...)`; dispatch needs
`JANUSMASK_WORKING_DIR` set; jail retargets via `effective_target_root`; external
staging re-roots under `external_staging_root()`). **#1 RISK / DE-RISK FIRST:** JM's
external-target build path is the LEAST-PROVEN capability (almost all JM proving is
self-build). MUST smoke-test a single trivial external build into NobleGreedv2 (stage→dispatch
→jail retarget→commit into NobleGreedv2 git→verify NobleGreedv2 tests in its venv) BEFORE the epic.
Open questions to verify: does the daemon propagate `task.working_dir`→
`JANUSMASK_WORKING_DIR`? Where does built code physically land + does it reach NobleGreedv2's
OWN git? JM's vcmd-sanitize globs JM's cwd `tests/**` (self-rooted) → won't find NobleGreedv2's
suite → specify external vcmd EXPLICITLY.

**KEY JM FINDINGS (from this convo, durable):** (1) JM tests via FRESH oracles +
non-vacuity mutation gate, NOT "run your existing suite"; existing-test regression
mapping is self-rooted (`plan_normalizer.py` globs `Path(cwd).glob('tests/**/test_<leaf>.py')`).
(2) Epic depth budget = STATIC `hierarchical_planning.max_planner_depth: 4` (config
constant, fail-open to sys.maxsize if absent; `depth_validator.check_brief_depth` walks
epic plan_hooks child_slugs/parent_epic_slug edges; >4 or cycle → refuse). Separate
task-decomposition budget = `decomposition.max_depth: 3` (failure-driven splitting).
(3) Budgets are DEPTH guardrails, NOT cost-aware — a shallow-but-wide epic (e.g.
depth-2, 40 children) burns unbounded tokens with no budget stop; watch spend manually.
(4) Multi-level/recursive epic decomposition is SUPPORTED + depth-gated + hermetically
e2e-tested, but only PROVEN hands-off at depth-1 (Phase 2 = epic→5 leaves). Reserve
deep nesting for proven domains; hand-author each level on novel domains.

Builds on [[phase2-session4-pipeline-rebuild]] (JM Phase 2 complete) and
[[test-authoring-oracle-gap]] (FIX #1 — daemon now authors oracles hands-off, which is
what makes JM-as-factory viable).
