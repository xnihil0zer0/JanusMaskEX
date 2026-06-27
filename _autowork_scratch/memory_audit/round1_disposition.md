# Round-1 memory-audit disposition (INPUT TO ROUND-2 ADVERSARIAL)

Ground truth: README.md (2026-06-18, HEAD 4897a3c), harness/config.yaml, git of JM + NobleGreedv2.
Evidence engine: `_autowork_scratch/memory_audit/audit_memory.py` (corrected: dotted-flag lookup, both-repo SHA, UUID/timestamp filtered). Per-file JSON: `evidence.json`.

## Objective engine signals (authoritative, corrected)

REAL config-flag mismatches (8):
- MEMORY_INDEX_ARCHIVE_2026-06-10.md — selfheal_auto_promote claimed=True cfg=False  [EXPECTED: frozen snapshot]
- brief-staleness-reconciler.md — archive_spent_briefs claimed=False cfg=True  [REAL staleness]
- next-mission-live-5poc-e2e-and-hardening.md — archive_spent_briefs claimed=False cfg=True
- overseer-chat-epic-brief.md — overseer.enabled claimed=False cfg=True
- overseer-epic-unblock-attempt.md — overseer.enabled claimed=False cfg=True
- rev28-exec-session.md — auto_approve_sensitive_harness + enable_single_agent_promotion claimed=False cfg=True
- triple-lock-was-claude-invented.md — selfheal_auto_promote claimed=True cfg=False  [DURABLE feedback file — READ THE LINE]
- webui-autobrief-streamjson-and-manual-pipeline-driving.md — selfheal_auto_promote claimed=True cfg=False  [READ THE LINE]

Dead-SHA findings (7) — classify each as real vs false-positive:
- real-bounty-machinery-handoff.md → c59fb3a   (R1: "zilliztech/gptcache @ c59fb3a" = target-repo commit, NOT a build SHA)
- red-gate-silently-stuck-every-harness-fix.md → ae16acba   (R1: originSessionId fragment)
- redesign-analysis-round1-verdict.md → f0cdbb16
- rev27-compiled-session.md → a4e6c422aee3a6399   (R1: OOM-killed sub-agent TASK ID, not a commit)
- selfheal-loop-closure-landed.md → a0253fd4, 454b383b
- untracked-test-poisons-patches-commit.md → 3189ae3   (R1: originSessionId only)
- wire-up-sweep-epic.md → c3a182a3, 62ecde8c

Orphan files (not in MEMORY.md index, 7):
auto-commit-failed-multifile-rootcause.md, deterministic-plan-park-and-daemon-corrections.md,
live-bounty-sourcing-learning-epic-COMPLETE.md, next-mission-live-5poc-e2e-and-hardening.md,
rev15-exec-session.md, rev17-exec-session.md, turn-recurring-failures-into-pipeline-fixes.md

## R1 proposed dispositions

### ARCHIVE (move to memory archive, NEVER delete) — ~72 files
Rev-session logs (group1): rev6-pipeline-routing-decision, rev7-m2-r-aprobe-landed, rev12-exec-session,
rev13-14-exec-session, rev15-exec-session, rev16-exec-session, rev17-exec-session, rev18-exec-session,
rev19-exec-session, rev20-exec-session, rev21-exec-session, rev22-exec-session, rev23-exec-session,
rev24-exec-session, rev25-exec-session, rev25-r3-refactor-session, rev26-exec-session, rev27-compiled-session,
rev27-exec-session, rev28-compiled-session, rev28-exec-session, rev29-unattended-safety-session,
agy-autonomous-single-agent-tamper, agent-isolation-fix-landed, adversarial-test-plans-24h-audit,
agent-isolation-6_3-live-probe-clean
Harness (group2): overseer-chat-epic-brief, overseer-epic-unblock-attempt, overseer-chat-fix-features-session,
hierarchical-planner-phase1-exec, hierarchical-planner-phase1-design, autocompiler-epic-brief,
autocompiler-phase-a-dispatch, cfix-c7-charden-landed, claude-agent-uncontained-cd-into-repo,
claude-jail-fix-first-accept-commit, contain-phase-landed, gap-remediation-progress, ex-phantom-task-no-promote,
handoff-bugfix-session-2026-06-09, bugfix-sweep-2026-06-10
Harness (group3): rebuild-remediation-may29, redesign-analysis-round1-verdict, phase-d-backlog-already-satisfied,
phase-d-drain-authorized, phase2-session4-pipeline-rebuild, owner-handedits-4a-4b-applied,
selfheal-loop-closure-landed, selfheal-deadlock-blocks-all-dispatch, wire-up-sweep-epic, wire-up-phase-built,
phase2-autonomy-security-posture
NGv2/bounty (group4): bounty-hunt-2026-06-13-eligibility-correction, ngv2-financial-viability-parallel-hunt,
real-bounty-machinery-handoff, run-hunt-fsm-rootfix-and-4hunts-2026-06-14, poc-writer-live-finding-chain-2026-06-14,
source-meta-fallback-landed-works, autonomous-campaign-hunt-cwe-template-gap, live-4x-hunt-detonation-env-blocker,
live-bounty-sourcing-learning-epic, live-bounty-sourcing-learning-epic-COMPLETE, ngv2-production-viable-oversight,
ngv2-autonomous-bounty-fsm-epic, ngv2-bounty-fsm-sessionapi-storage-gap, ngv2-e2e-huntr-poc-driven,
verify-harden-5poc-e2e-session, next-mission-live-5poc-e2e-and-hardening, factory-clobber-fix-and-ngv2-resume-2026-06-13,
leaf5-sink-blockers-and-factory-gaps, ngv2-epic1-run-result, ngv2-epic2-run-result, ngv2-epic3-run-result,
ngv2-epic4-authored, ngv2-epic4-run-result, ngv2-metadata-harvest, ngv2-phase0-external-build-proven,
ngv2-wireup-epic-complete, spine-epic-a-and-additive-edit-fixes, concurrency-isolation-and-ngv2-solver-ast-epic,
tmux-claude-default-and-agy-hunt-epic, source-driving-poc-epic-authored

### UPDATE (fix stale claim, keep file) — 3
- brief-staleness-reconciler (archive_spent_briefs now true/ON, not OFF)
- test-tiering-bootstrap ("pipeline brief pending" resolved; tiers live per README §2)
- source-driving-doesnt-fire-on-live-findings (trim resolved push-status/regression; keep is_source_driving diagnosis)

### KEEP — durable rules / current facts / references (~39)
feedback/user durable rules: broad-adversarial-suite-vcmd-is-flaky-gate, dont-conflate-built-with-works,
fixes-are-permanent-and-reusable, implementation-is-not-wired-defect, issue-fix-via-pipeline-then-rerun,
never-hand-edit-production-outside-pipeline, spec-only-pipeline-augment-agents, subagent-ran-pipeline-over-reach,
triple-lock-was-claude-invented, turn-recurring-failures-into-pipeline-fixes (INDEX-ADD), fixes-are-permanent…
Durable project recipes/current facts: daemon-supervisor-respawn, backup-detach-fixes-systemic-autocommit,
blinddraft-workingdir-landed-and-recipe, drive-epic-complete-and-harness-hardening, factory-new-module-wireup-gates,
newmodule-oracle-fix-and-trust-core-approval, autonomous-daemon-run-and-class-method-edit-fragility,
epic-contracts-run-2026-06-17, required-task-ids-enforcement, planner-empty-plan-systemic,
red-gate-silently-stuck-every-harness-fix, stale-sidecar-precedence-gotcha, stale-state-recovery-complete-2026-06-18,
stale-state-cleanup-design (borderline), pipeline-readiness-hardening-program (CANONICAL top entry),
srcdrive-epic-leaf1-and-muttarget-gate-bug, overseer-pillars-and-fsm-wired, overseer-procedure-gates-epic,
webui-autobrief-streamjson-and-manual-pipeline-driving, webui-brief-editor-clobber-and-planner-brief-shaping,
webui-foundation-corrected-plan, untracked-test-poisons-patches-commit, test-authoring-oracle-gap,
autocompiler-default-on, autocompiler-epic-all-phases-built, agy-cli-flags-probe (reference),
auto-commit-failed-multifile-rootcause (INDEX-ADD), deterministic-plan-park-and-daemon-corrections (INDEX-ADD),
ngv2-detonation-jail-loopback-ssrf, ngv2-cleanroom-rebuild-plan, MEMORY_INDEX_ARCHIVE_2026-06-10 (frozen)

### INDEX ops
- INDEX-ADD: deterministic-plan-park-and-daemon-corrections, turn-recurring-failures-into-pipeline-fixes,
  auto-commit-failed-multifile-rootcause
- INDEX-REMOVE: selfheal-deadlock-blocks-all-dispatch (fix ea6b9db landed), live-bounty-sourcing-learning-epic (dispatched; COMPLETE supersedes)
- INDEX-TRIM: collapse the rev-session changelog block (MEMORY.md lines ~73-99). MEMORY.md is 35KB, limit 24.4KB.

## Superseding chains R1 found (verify in R2)
1. NGv2 build epics: phase0 → epic1 → epic2 → epic3 → epic4-authored → epic4-run-result
2. spine-epic-a → ngv2-wireup-epic-complete → concurrency-isolation → factory-clobber-fix (Phase-4 rework subsumes)
3. Bounty→zero: ngv2-financial-viability ("9 parked claimable") → bounty-2026-06-13-eligibility ("only 6, prior WRONG") → rev.5 ("0 confirmed PoCs"); real-bounty-machinery ("1 gptcache PoC") → rev.5 zero
4. Live-hunt blocker MOVED ×3: run-hunt-fsm → campaign-cwe-template-gap → source-meta-fallback-landed-works → source-driving-doesnt-fire → rev.5 ("gap=DISCOVERY/TRIAGE QUALITY")
5. Authored→COMPLETE: live-bounty-sourcing-learning-epic → -COMPLETE; source-driving-poc-epic-authored → leaves landed
6. 5-PoC e2e: next-mission-live-5poc → verify-harden-5poc-e2e-session; ngv2-e2e-huntr-poc-driven → verify-harden (C-2)
