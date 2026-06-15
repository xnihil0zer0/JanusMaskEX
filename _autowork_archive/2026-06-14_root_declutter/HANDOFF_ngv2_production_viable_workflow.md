# HANDOFF — Oversee NobleGreedv2 to a full, production-viable bounty workflow

You are the overseer. Your mission is to drive **NobleGreedv2 (NGv2)** — an autonomous bug-bounty hunter — from "all 9 phases built + PoC writer proven live" to a **full, production-viable end-to-end workflow**, using the **JanusMaskJR (JM)** code-generation factory at `/home/xnihil0zer0/JanusMaskJR` to build all NGv2 production code. NGv2 lives at `/home/xnihil0zer0/NobleGreedv2`.

Read the JM memory index first (it auto-loads). The load-bearing memories: `real-bounty-machinery-handoff`, `live-bounty-sourcing-learning-epic`, `dont-conflate-built-with-works`, `turn-recurring-failures-into-pipeline-fixes`, `never-hand-edit-production-outside-pipeline`, `ngv2-wireup-epic-complete`. Read `README.md` for how the factory works. Be token-efficient: delegate investigation/build work to sub-agents, keep oversight in your own context, and verify before trusting.

## Definition of "production-viable" (the acceptance bar)
A single live run that, with **zero hand-coded exploits and no auto-submission**, does end-to-end:
**source fresh real bounties (live, not a frozen cache) → select valuable AND pipeline-confirmable targets → clone real repos → scan for the RIGHT bug classes → auto-synthesize a PoC via the LLM repair loop → detonate in the bwrap jail under the STRONG fs-effect oracle → confirm ≥1 real, NOVEL, in-scope, ATTACKER-REACHABLE (i.e. CLAIMABLE) bug → render a SHA-pinned huntr submission package → PARK at `awaiting_submission` for a human → ingest the verdict → re-learn.**

What is already proven: the back half works. The PoC writer + jail now synthesize and confirm a real PoC live (gptcache CWE-78, up from 0/5). **What is NOT yet met: a real *claimable* PoC.** That is the bar. Do not declare done until you have parked at least one.

## Cardinal rules (non-negotiable)
1. **Never hand-edit production outside the pipeline.** All `ngv2/**` and JM `harness/**` code is built by the planner→stage→worker pipeline. Only oracles/tests, briefs (`brief_hooks_*.md`), and NGv2 `_e2e_run/` scratch are hand-authorable. The JM irreducible set (`agent_jail.py`, `git_integration.py`, `orchestrator.py`, `autowork_daemon.py`, `paths.py`, `interceptors.py`, `selfheal.py`, `dbus_proxy.py`, `services/**`) is **owner-hand-edit only** — clear with the owner first.
2. **Never auto-submit** to any platform (no HTTP POST, no Playwright form-fill). Detonate jail-only with harmless payloads. The loop parks at `awaiting_submission`; a human submits.
3. **Never conflate BUILT (green oracles) with WORKS (real claimable PoC).** A green suite is necessary, not sufficient. Prove every capability LIVE.
4. **Verify before you trust.** Memory/agent claims can be stale or wrong — confirm against current code and real runs (this session caught an agent's "verified" lock patch that had a mutual-exclusion hole and a brief that failed validation on a non-`# Title` heading).

## Step 0 — immediate state to reconcile (do this first)
- JM `master` is **ahead of origin by 3 unpushed commits**: `2561d67` (pipeline: planner external-module-creating + cd-prefix fixes, `plan_validator.py`), `feb13ad` (pipeline: redundant-oracle dedupe, `plan_normalizer.py`), `acc7edb` (owner-authorized HAND-EDIT: daemon brief-level dependency gating, `autowork_daemon.py`). Planner suite green (435), daemon suites green (21). **Decide with owner: push these** (one touches the irreducible `autowork_daemon.py` — eyeball the diff).
- The JM **daemon is PAUSED** (`state/control/orchestrator.flag` = `pause`). Resume it (`echo resume > state/control/orchestrator.flag`; ensure no `state/control/autowork/full_stop`; daemon PID in `state/control/autowork.pid`, supervisor `scripts/run-autowork.sh`) when you want building to continue.
- The epic brief `brief_hooks_live_bounty_sourcing_and_learning.md` (slug allowlisted) now validates (was failing on a non-`# Title` heading, fixed). On resume the daemon will decompose it.
- Recurring pipeline-failure patterns: **4 of 5 fixed.** Deferred: the stale `git_commit.lock` reclaim — the drafted fix was unsafe and the bug appears already-mitigated (PEP-446 CLOEXEC fds + bounded retry + manual `rm`); do NOT patch it blind. If it genuinely recurs, instrument/reproduce first, and note it's an irreducible owner-only file.

## The core blocker and strategy
The bottleneck is **discovery, not PoC synthesis.** Two root causes, both measured this session:
- **Sink-taxonomy mismatch.** The eligible corpus is ML/AI infra (sagemaker, triton, autogluon, litellm, gptcache, text-generation-inference, modeldb). The scanner (`ngv2/pattern_scanner.py`) hunts mainly command-injection (CWE-78) — the one *over-saturated* class. But **deserialization (CWE-502) + SSRF (CWE-918) + path-traversal (CWE-22) = 37.9% of all paid huntr findings**, each across 20+ repos. The hunter is blind to the classes that actually pay. `ngv2/deser_detect.py` (CWE-502) already exists but is **unwired** — wiring it is the single highest-leverage move.
- **Reachability gap.** Regex scan + intra-procedural taint cannot surface the deeper inter-procedural, attacker-reachable flows that real bugs in mature repos require. Among 24 eligible repos, every regex-detectable param-derived sink was internal plumbing / dev-config / vendored / admin-gated. A sink that fires but isn't attacker-reachable is NOT claimable.

## Remaining work, sequenced (drive these as epics/phases)
**Phase I — Land the live sourcing + learning epic** (`live_bounty_sourcing_and_learning`, already dispatched).
Builds: a live huntr scraper that PRODUCES the three `data/ngv2/*.json` snapshots the existing loaders already read (huntr is a Next.js SPA — fetch RSC "flight" payloads with an `RSC: 1` header, no full browser needed for bulk; Playwright only for lazy per-disclosure bodies); OSV.dev + GitHub GHSA enrichment fetchers (free APIs, `gh` already authed → 5000/hr; join on `cve_id`/`ghsa_id`); and the learning layer (`title_cwe_classifier`, `bounty_corpus_stats`, `sink_taxonomy` with `demand × confirmability × novelty` weights, `candidate_builder` per-(repo,CWE), `verdict_store`), plus wiring `deser_detect` into the scan catalog and adding `demand_score`/`×confirmability` to `selection_ranker.score_candidate`. The full design is in memory `live-bounty-sourcing-learning-epic` and the recon outputs.

**Phase II — Build the missing detectors** (closes the sink-taxonomy mismatch).
Wire `deser_detect` (CWE-502) into the live scan path FIRST (highest leverage: high demand across 21 repos, detector exists, PoC+jail already works). Then new detectors for CWE-918 (SSRF) and CWE-22 (path-traversal). Until a class's detector + confirm-template exist, the ranker should suppress it (`confirmability=0`).

**Phase III — Close the reachability gap** (OWNER DECISION on direction — surface options, recommend, then build the chosen one).
Options: (a) wire in a real inter-procedural taint engine you don't hand-roll — **Semgrep taint mode or CodeQL**, which ship maintained security query packs incl. ML-relevant ones — feeding the existing confidence cascade; (b) add an **LLM reachability-triage cascade stage** between cheap scan and expensive PoC synthesis (the LLM is proven; it's good at "is this reachable from a public entry point?"); (c) flip to **source-first / entry-point-driven** analysis (enumerate HTTP/gRPC handlers + model-deserialization load paths, forward-trace) to kill the false-positive flood. Recommended start: source-first scoping + LLM triage (both reuse what exists) before standing up Semgrep/CodeQL.

**Phase IV — Live end-to-end to the acceptance bar.**
Run the full `hunt_loop` (`_e2e_run/drive_hunt_loop.py` and friends) against a FRESH, well-targeted corpus (favor low-saturation + high-recent-churn; hunt release deltas, not whole mature repos) until ≥1 real CLAIMABLE PoC is jail-confirmed and parked. Honest negatives are fine and informative — report them. Try several ranked candidates; real HEADs may already be patched.

**Phase V — Close the feedback loop live.**
The Phase-7 modules (`submission_verdict`, `verdict_feedback`, `verdict_reweight`, `novelty_corpus`) are built; drive real verdicts through them so the system re-learns demand and confirmability.

## Operating cadence (how to oversee)
- **One phase per fresh background sub-agent.** Don't reuse a context-full agent. Carry progress in the brief/handoff, not in a live agent (SendMessage is unavailable in this harness — stop + re-dispatch).
- **Git-verify, don't trust "completed."** Confirm each landing as an `Integrate validated code for <slug>` commit in NGv2 git; check the ledger `state/impl_progress.jsonl` for `auto_commit` (phase `accepted`). An agent whose `tool_uses` keeps climbing is ALIVE, not stale.
- **Expect to supervise external-ngv2 epics phase-by-phase.** The planner quirks are partly fixed now: Fix A makes `_is_module_creating` resolve `files_touched` against `working_dir` (external leaves no longer forced to name a `*_wired` oracle) — confirm it behaves on the first external leaf. Still true: a NEW sub-package needs an empty `__init__.py` committed to NGv2 master first; `verification_command` must be CWD-relative (NO `cd` prefix — now rejected fail-fast at plan time); whole-file new modules can get paraphrased (prefer small leaves / sidecar-recovery / worker-friendly additive helpers); order siblings by holding briefs + frontmatter `dependencies: [slug]` (the daemon now honors brief-level deps as a dispatch gate — Fix 2 this session).
- **Pre-commit hand-authored RED oracles** before dispatching any harness/external fix; commit them so an untracked test doesn't poison the patches commit.
- **Watch the budget.** Kill stray `_e2e_run/drive_*.py` processes — one was found burning LLM budget re-confirming a `def eval(self):` false positive.

## Pipeline operation refresher
Allowlist the slug (`state/control/autowork/auto_promote.allowlist`, deny-all when empty), `echo resume > state/control/orchestrator.flag`, remove any `full_stop`, clear a stale `git_commit.lock` if a daemon died, start `scripts/run-autowork.sh --state-dir state --logs-dir logs --config harness/config.yaml`. Tail `state/impl_progress.jsonl` for `plan_kickoff` / `auto_commit` / `task_blocked` / `planner_hallucination_discarded`. Brief shape: five BARE headings (`# Title`, `# Scope`, `# Non-Goals`, `# Inputs`, `# Deliverables`), EDIT tasks put the literal word `integration` in `# Non-Goals`, ≥2 edge_cases.

## Decision points needing the owner
1. Push the 3 unpushed JM commits now (incl. the irreducible `autowork_daemon.py` hand-edit)? Resume the daemon now?
2. Phase III direction (taint engine vs LLM triage vs source-first — recommend, then build).
3. Confirm the human-gated submission boundary stays permanent (recommend: never auto-submit).

## Key references
- Memory: `real-bounty-machinery-handoff` (full 9-phase ledger + the 0/5→1 live-confirm story), `live-bounty-sourcing-learning-epic` (scraper+learning design + 4-agent recon), `ngv2-e2e-huntr-poc-driven`, `verify-harden-5poc-e2e-session`.
- NGv2 code: `ngv2/pattern_scanner.py`, `deser_detect.py`, `selection_ranker.py`, `poc_writer.py`, `poc_repair_loop.py`, `llm_client.py`, `hunt_loop.py`, `huntr_cache_loader.py`, `sourcing/huntr_client.py` (inert — leave as dead code), `contracts.py`; data in `data/ngv2/*.json`; live drivers in `_e2e_run/`.
- Live confirm artifacts (proof the PoC writer works): `/home/xnihil0zer0/NobleGreedv2/_e2e_run/llm_confirm_out/`.
- Legacy lessons (read-only): `/home/xnihil0zer0/AI-Data/NobleGreed-legacy` — flock rate-limiter, verify-at-source rule, `_not_eligible/` quarantine, saturation-dominant ranking, the MFF model-file-format track ($4000/critical).
