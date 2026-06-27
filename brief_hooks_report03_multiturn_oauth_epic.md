---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
epic: true
required_child_slugs:
  - report03_p0_agy_seed_history
  - report03_p0_jail_recarve
  - report03_p0_orch_home
interfaces: "Epic of INTEGRATION_REPORT_03 (multi-turn agent stages + OAuth). Decomposes into phased child briefs P0..P3. ONLY the two P0 children are activated this round; P1/P2/P3 are documented-but-deferred behind Int 2 per PRIORITIZATION_VERDICT_v3 §4. Each child follows the STEP ZERO rollout pattern: default-OFF flag (where it introduces new behavior) + RED oracle proving the off-flag path is BYTE-IDENTICAL to HEAD + shadow-mode + real-bwrap verify."
---

# Title
INTEGRATION_REPORT_03 — Multi-turn agent stages + OAuth hardening (epic)

# Scope
This epic decomposes INTEGRATION_REPORT_03 (`/home/xnihil0zer0/AI-Data/Research-JanusMask/INTEGRATION_REPORT_03_multiturn_oauth.md`) into its §6 phased roadmap as a child-brief set. It is the design-of-record and sequencing contract.

ACTIVATED THIS ROUND (authored as standalone allowlisted leaf briefs, built now):
- STEP ZERO rollout pattern, applied to each P0 fix: a default-OFF posture, a RED oracle proving the off-flag / pool-disabled path is byte-identical to HEAD, and verification in the REAL bwrap jail (loopback UP), never `unshare -n -r`.
- P0 fix (b): `report03_p0_agy_seed_history` — add `.gemini/antigravity-cli/history.db` to `_SEED_RELS` in `harness/agy_pool.py`. Single file, auto-approve-eligible. The cheap today-win; built FIRST to prove the pipeline + STEP ZERO pattern.
- P0 fix (a): `report03_p0_jail_home_thread` — thread `home=` (from the pooled env) into the `build_jail_argv(...)` call at `harness/orchestrator.py` and re-carve the slot-home rw-bind AFTER the repo ro-bind in `harness/agent_jail.py`. Both files are in the irreducible `_NEVER_AUTO_APPROVE` set → each gated task needs a pre-authored operator decision file.

DEFERRED (declared as epic children for structure ONLY; NOT allowlisted, NOT built this round):
- P1: `CLAUDE_CODE_OAUTH_TOKEN` env injection + per-task cwd/agy-slot pinning.
- P2: multi-turn `--resume` loop from the pinned cwd.
- P3: host-side single-flight token broker (`harness/token_broker.py`) + `apiKeyHelper`.
P1/P2/P3 are sequenced AFTER Int 2 (the fuzzable-surface program) per PRIORITIZATION_VERDICT_v3 §4 (FIFTH) and §6. They are documented here but withheld from the allowlist; do not write/allowlist their leaf briefs until Int 2 lands.

# Inputs
SPEC: `/home/xnihil0zer0/AI-Data/Research-JanusMask/INTEGRATION_REPORT_03_multiturn_oauth.md` §6 (P0–P3 roadmap) and §8 (binding process rule: design + PoC only; all harness changes route through the pipeline with RED oracles proving off-flag byte-identity, shadow-mode first, fail-closed, verified in the real bwrap jail).
SEQUENCE: `/home/xnihil0zer0/AI-Data/Research-JanusMask/PRIORITIZATION_VERDICT_v3.md` §4 (Int 3 P0 FIRST; Int 3 efficiency/P1-P3 FIFTH, after Int 2) and §6 (backlog tags).
GROUND TRUTH (verified at HEAD 2cadab5): `harness/agy_pool.py:19` `_SEED_RELS` = 7 paths, no `antigravity-cli/history.db`; `harness/orchestrator.py:380` calls `agent_jail.build_jail_argv(...)` WITHOUT `home=`; `harness/agent_jail.py:71` already HAS a `home` param resolved at :107 as `home or os.environ['HOME']`; `workers.agy_pool.enabled: false` (ships OFF).

# Non-Goals
This epic brief itself authors NO code and edits NO file (epic_planning / decomposition only) — integration of any child is out of scope at the epic level. It does NOT activate P1/P2/P3; those children are deferred behind Int 2 and MUST NOT be allowlisted or built this round. It does NOT enable `workers.agy_pool.enabled` (stays false). It does NOT introduce multi-turn or token-broker behavior. The word `integration` appears here to satisfy the integration-test excuse for any decomposition task.

# Deliverables
A persisted epic plan (`plan_hooks_report03_multiturn_oauth_epic.json`, `plan_kind: epic`) declaring the four phased children, with the two P0 children (`report03_p0_agy_seed_history`, `report03_p0_jail_home_thread`) named as required child slugs and the P1/P2/P3 phases documented as deferred. The activated work lands via the two standalone P0 leaf briefs (authored and allowlisted directly, since allowlisting an epic transitively admits ALL children and would wrongly activate the deferred P1/P2/P3 phases).

# Required plan shape
This is an `epic_planning` decomposition. Emit child briefs for the report's phases:
- `report03_p0_agy_seed_history` (P0 fix b) and `report03_p0_jail_home_thread` (P0 fix a) — the two ACTIVATED children (required_child_slugs).
- `report03_p1_oauth_token_cwd_pin` (P1), `report03_p2_multiturn_resume` (P2), `report03_p3_token_broker` (P3) — DEFERRED children, documented only.
No code task is authored at the epic level (meta_task_type: epic_planning; bypass_fuzzer). Cross-phase ordering is brief-level: a deferred child is not built until its prerequisite phase and Int 2 have landed. non_goals MUST contain the literal word `integration`.
