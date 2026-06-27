# ROUND-2 DOC-AUDIT — DECISION SPEC (operator's final say)

Adjudicated 2026-06-24 from 4 script-backed audit agents (agent1 citations / agent2 status+roadmap /
agent3 trust-model+new-gaps / agent4 env-FSM buildability) under
`_autowork_scratch/ngv2_doc_audit_2026-06-24_round2/agent{1..4}/`. Every item below is a finding I am
ACCEPTING for application, with the script evidence behind it. Items I rejected/narrowed are marked.

**END GOAL:** both docs must read as a fresh, current-state description. **DELETE the `## ADDENDUM —
2026-06-24` sections entirely**, fold their retained substance into the body, **collapse the append-only
audit history** (DOC-B §8 log, DOC-A §8A/§8B, all `[AUDIT]/[AUDIT2/3/4]/STATUS UPDATE/RE-AUDIT` inline
"was-X-now-Y" narration) into settled current-state statements. Preserve the strategic thesis and all
forward-looking content. Do NOT reference "audits," "rounds," "addendum," or "this correction" anywhere in
the final docs — state facts directly.

DOC-A = `NobleGreedv2-end2end-gap-analysis.md`. DOC-B = `NGv2-closure-deliverables-and-acceptance-contract.md`.
Repos: NGv2 HEAD `203d007`, JM HEAD `5ee8fa3`.

---

## 0. GLOBAL FACTS (verified by operator; use these verbatim, both docs)

- **Config (live `harness/config.yaml`):** `autowork.parallel_cap: 5`, `autowork.claude_parallel_cap: 4`,
  `workers.agy_pool {enabled: true, size: 8}`, `workers.claude_backend: headless`,
  `synthesis.active_agents: [claude, gemini]`.
  → The "default operating point = 4 pairs / `parallel_cap: 4`" line is STALE: state **`parallel_cap: 5`
    (with `claude_parallel_cap: 4`)**. The agy_pool "OFF by default / set it explicitly" caveat is OBSOLETE
    (pool is enabled, size 8 ≥ cap). Backend is **headless (API-billed)**, not "tmux". **`active_agents` is
    `[claude, gemini]` — the dual-agent anti-self-exam premise IS config-valid** (the ADDENDUM's `[claude]`
    claim was WRONG; do not hedge the dual-agent guarantee on this).
- **Citations:** the 7 high-churn modules (`transition_planner.py`, `detonation.py`, `gate_executor.py`,
  `conductor_seams.py`, NGv2 `workers/_runner.py`, JM `sandbox.py`/`orchestrator.py`/`target_bootstrap.py`)
  must be cited as **`file::symbol`**, NOT raw line numbers (every raw line in these has drifted). Specific
  fixes in §3 below.
- **orphan_unwired** rejection count = **32** (doc says 16). **`wireup_symbol_verdict` rows = 0** (correct).
- **Fabricated SHA:** `0795605` does NOT exist. The JM-side P0.2 is `target_bootstrap` (oracle `6f08eeb`,
  impl `2049f78`) — a DIFFERENT module from the NGv2 installer. There is **no NGv2-installer oracle yet**.

## 1. VERIFIED STATUS (ground truth — apply to all checkboxes/ledgers/gap-status columns)

LANDED ☑: P0.1 (`8ef60e9`/`a400a38`); **P0.2 JM-side only** (`6f08eeb`/`2049f78`); P1.1 cross-process wiring
(`eb113f5`/`fe8384c`); P1.2 (`5ab82c2`/`aa718c9`); P1.3 (`80722d6`/`2a83d06`); **P2.1 c0/c1/c2/c3**
(scaffold `9a712e6`/`dc07188`; c1 `4f299a1`/`203d007`; c2 `a27ca22`/`59b8b15`; c3 `e4280e1`/`e6a7f38`) —
**but all four are PURE adjudicators with NO producers and ZERO live call-sites (functionally ORPHANED).**

OPEN ☐: P0.2-NGv2; P2.1 c4/c5/c6/c7/cP; P2.2; P3.1; P3.2; P3.3; P4.1; P4.2; P4.3; P-CAPSTONE.
P-WIREUP ◐ (module gate LIVE/portable, 32 orphan_unwired; per-symbol floor BUILT-not-portable, runtime gate
default-OFF, 0 verdict rows; no Tier-0/roots/wire_exempt/alias-attr work landed).

X-criteria: X1 named dead-end CLOSED but **capstone (a real `run_hunt` `confirmed` row) PENDING** (zero such
ledger rows; `_INITIAL_PHASE='hunt'`). X4 GREEN. G10/X(empty-sig) GREEN. X5/X6/X7/X8/X9(teardown half)/X10/
X11/X12/X13/X14/X15/X16 RED or untested.

**Strategic thesis UNCHANGED and re-confirmed:** BUILT≠WORKS; the env-FSM is the live gap; trust =
reproducibility + nonce-bound per-CWE differential; no `run_hunt` `confirmed` detonation exists yet.

## 2. ADDENDUM disposition (fold the survivors, delete the section)

- **M1** (X1 dead-end closed via `count_fields`; `_PHASE_COUNT_KEY` "3-of-7" is a red herring) → FOLD into
  DOC-A §2 G5 + the deviation/current-state prose. State as fact: middle-phase plumbing closed
  (`eb113f5`/`fe8384c`); capstone pending.
- **M2** (empty-sig vacuity closed) → FOLD; mark G10 CLOSED; delete the old "[AUDIT3/AUDIT4] hardening edge
  case" sub-block. **Re-verified by execution (agent3/d1).**
- **M3** (LoopbackListener WIRED; `_make_detonation_seam` threads SSRF env) → FOLD; G3/SSRF DONE for
  loopback; **`auth_bootstrap` and `sink_instrument` remain DEAD (0 prod importers)** — keep that half open.
  Drop `loopback_listener` from every dead-code list.
- **M4** (P1.2/P1.3 landed; 3 residual holes) → FOLD statuses; **KEEP the residuals as OPEN** (see §4 new
  trust-residuals — confirmed by execution agent3/d1,d2,d3).
- **M5** (answer-key leak) → NARROW then fold: leak fix `3f9af36` = 2026-06-24 10:50 EDT; the **06-24 wave
  impls synthesized AFTER the fix** (workers started 15:09–19:49Z); leak exposure applies to the **06-21
  P1.1 items** (`ed91619` etc.) only. Fold a scoped one-time recheck (X3.5), not a blanket pre-14:50 caveat.
- **M6** (env-FSM is the live gap; handlers orphaned; content-hash zero consumers) → FOLD and PROMOTE to lead
  current-state text in DOC-A §2 G1 + §7 Wave-2 (no longer an addendum bullet). Still fully valid post-c1-c3.
- **ADDENDUM op-note** → FOLD config facts (§0) AFTER fixing `active_agents → [claude, gemini]`.
- **DOC-B ADDENDUM "P2.1 deviation + cP/c7/phase-literal/content-hash bridge"** → FOLD as the §4 P2.1
  rewrite (§5 below). All four added deliverables VALIDATED real & necessary (agent4).
- **DOC-B ADDENDUM "P0.2-NGv2 prereq"** → FOLD as an enumerated `P0.2-NGv2` task; FIX the false claims
  (drop `0795605`; JM impl `2049f78` DID land; the JM side is `target_bootstrap`, the NGv2 side is
  `poc_runner_live` and is fully unbuilt — no oracle).
- **DOC-B ADDENDUM "§5.5 wire-up correction"** → FOLD into P-WIREUP/§5; neither layer is teeth-bearing on
  external NGv2; module gate passes NGv2 FSM modules by REAL BFS (they ARE import-reached) — the correct
  framing is "import-reachability ≠ called" (see new G14), NOT "lands via the no-op latch."
- **DOC-B ADDENDUM "X3.5"** → KEEP, narrowed to 06-21 pre-leak-fix items; textual screen is insufficient,
  the mutation recheck is genuinely required (agent3/d6).

## 3. CITATION FIXES (apply; prefer `file::symbol`)

- `transition_planner.py:64-72` / `:66,67,70,71` / `:36` / `:40`  → **DEAD (file is 60 lines).** Replace all
  with `ngv2/transition_planner.py::plan_next_action` (spawn set = the `worker_phases` table).
- `ngv2/detonation.py:3` / `:21` / `semantic_verdict:21` → `ngv2/detonation.py::semantic_verdict`
  (def at line 4; empty-sig guard inside it).
- `ngv2/gate_executor.py:24` → `::TypedTerminal` (class at 25). `:39`/`:25-38`/`:41-93` are OK but prefer
  `::_TRANSITION_GATES` / `::TypedTerminal` / `::run_gates`.
- `workers/_runner.py:267` → `ngv2/workers/_runner.py::_make_detonation_seam` (the `target_spec` payload is
  built there; it now threads SSRF env + `loopback=True`, no longer just `{'repo_root'}`).
- `conductor_seams.py:86` (as "build_default_seams") → `ngv2/conductor_seams.py::build_default_seams`.
  `:86-117` (as build_evidence) → `::build_evidence`. `:48-84`/`:56-58` → `::persist`. `:20` (`_PHASE_COUNT_KEY`)
  may stay but cite `::_PHASE_COUNT_KEY`.
- JM `sandbox.py:892`/`:1077`/`:1281` → cite the methods `Sandbox.execute` / `BatchRunner.execute_batch` /
  `BatchWorkerPool._spawn_worker` routing through `harness/sandbox.py::_jailed_popen` (the real Popen seam).
- JM `orchestrator.py:2969/3072/3104/3126` → `harness/orchestrator.py` `build_jail_argv(bind_credentials=False)`
  sites (cite the function, not lines). `:1483` → `:1484`-area detonation-prompt block (cite symbol/region).
- JM `target_bootstrap._ensure_venv:162-184` → `harness/target_bootstrap.py::_ensure_venv` AND **fix the stale
  fact**: it is ALREADY jailed (`build_jail_argv(bind_credentials=False)`, lockfile-pinned). DOC-A G8 must
  state the JM side as CLOSED; DOC-B P0.2 "replace host pip install" is DONE for JM — only NGv2 remains.
- `loopback_listener` dead-code claim → DELETE (now 3 production importers).
- Keep (valid): `wire_up.py::symbol_reachable_from_live_root`, `::check_wired`, `config/autocompiler.yaml:21`
  (`js: true`), `poc_writer.py::is_source_driving`/`::render_source_driving_py`/`::_TEMPLATE_LIST`,
  `auth_bootstrap.py`, `pattern_scanner.py`.

## 4. NEW / STRENGTHENED GAPS & CRITERIA (apply)

### G14 (new gap row, DOC-A §2) + X17 (new exit criterion, DOC-B §2) — ACCEPT (highest-leverage)
G14 text: **"The acceptance (wire-up reachability) gate conflates import-reachability with live-execution."**
The wire-up gate green-lights modules that are import-reachable but never CALLED on the live `run_hunt` path.
The env-FSM handlers (P2.1 c0–c3: `fsm_detect.detect`, `fsm_provision.provision_gate`,
`fsm_jail_build.jail_build_gate`, `fsm_evidence.advance_gate`) landed GREEN with **0 conductor call-sites**,
**0/6** `ENV_PHASE_ORDER` members present in the live `PHASE_ORDER`, and `_INITIAL_PHASE='hunt'`. This
re-introduces the BUILT≠WORKS failure mode the program exists to kill, at the gate layer. Status: CONFIRMED
(execution + AST, agent3/d4, agent4). Evidence: `ngv2/fsm_*.py` handlers have 0 live callers; no env phase
in `gate_executor`/`transition_planner`/`stage_command_map`/`workers/`.
X17 text: **"Every FSM handler is proven CALLED on the live path, not merely imported."** Driving real
`run_hunt` over a fixture executes each env-state handler (asserted via call-trace/settrace, NOT an import
check); each module landed under the trust program ships a CALL-path oracle. Closes G14. Add a §3 traceability
row (G14 → P2.1-c7 + P-CAPSTONE → CALL-path oracle → X17/X1).

### Trust-model residuals (DOC-A §4 + DOC-B X5/X9) — ACCEPT (execution-verified OPEN)
Add a **"Residual trust holes (OPEN)"** paragraph to DOC-A §4 anti-self-exam:
1. **Provenance asserted, not proven** — `detonation_evidence_gate` keys `may_confirm` on caller-set
   `ran_target`/`observed_runtime_effect` booleans the detonation seam stamps on itself (`ran_target`
   unconditionally True); the gate consults no baseline/nonce/differential (agent3/d3).
2. **Nonce backstop absent on the wired path** — `DetonationChamber.detonate` does not accept a nonce; no
   live caller passes one to `semantic_verdict`; the SSRF nonce is a deterministic `ssrf_<finding_id>`; the
   payload nonce slot equals the success marker; the nonce is never persisted (agent3/d1,d7).
3. **No benign-baseline differential** — `detonate_live` self-diffs the SAME malicious run, not a separate
   benign control; `baseline_capture` is orphaned → "absent in baseline" is vacuous on the wired path
   (agent3/d4).
4. **Authenticity AST check necessary-not-sufficient** — `network_live` mode confirms a non-localhost HTTP
   PoC with no target import, and a target call inside `if False:` still classifies `real_target` (agent3/d2).
DOC-B X5: amend "How to test" to additionally require (a) CSPRNG per-run nonce (os.urandom; not derived from
`finding_id`, not equal to the success marker), (b) nonce PERSISTED in the sealed bundle, (c) the live
fs-signature caller actually PASSES the nonce to `semantic_verdict`. Mark X5 RED with this status note.
DOC-B X9: amend with "teardown byte-identity is UNIMPLEMENTED — `detonate_live` rmtrees scratch but never
verifies the RO-bound target vs `target_sha`; no `target_unchanged` evidence emitted; needs a STATE-8
producer + oracle." (The G7 fuzz-jail half of X9 IS landed via P0.1.)

(I am NOT minting G15/G16/G17 as separate gap numbers — they are residuals/strengthenings folded under the
trust model + X5/X9 above, to keep the taxonomy disciplined. Only G14 is a genuinely new class.)

### X3.5 (DOC-B §2) — KEEP, narrowed
Retro non-vacuity mutation recheck of the **06-21 pre-leak-fix** closure items (`3f9af36` landed 10:50 EDT
2026-06-24; the 06-24 wave synthesized after it). A textual value-echo screen is insufficient (agent3/d6) —
a real per-oracle mutation recheck is required.

## 5. P2.1 RESTRUCTURE (DOC-B §4 + DOC-A §7 Wave-2) — ACCEPT (central correction)

Replace the P2.1 child set with: **c0 (scaffold ☑) · c1/c2/c3 (pure handlers ☑) · c4/c5/c6 (remaining pure
handlers ☐, parallel) · cP `env_phase_producers` (☐ — the 6 IMPURE producer seams that fill the handler
input dicts; net-new env stand-up; parallel per-state; `cP-provision` blocks on P0.2-NGv2) · c7
`fsm_live_integration` (☐ — STRICTLY SERIAL: flips `run_hunt._INITIAL_PHASE 'hunt'→'detect'`, inserts the env
phases into ALL live phase literals, registers the env-state gates that CALL the handlers, adds
`workers/<phase>.py`, bridges env-artifact→flat-gate-evidence)**.

Mandatory adds:
- **Phase-literal unification (part of c7):** the live phase sequence is duplicated in **6 tuples across 3
  modules** (`fsm_evidence.PHASE_ORDER`, `session_api.PHASE_ORDER`, `session_api._PHASES`,
  `state_machine.LIFECYCLE_PHASES`, `state_machine.PHASES`, `state_machine.ALLOWED_TRANSITIONS`), none
  deriving from c0. c7 must make all live literals DERIVE from the c0 source with an equality + in-order
  traversal oracle, else inserting env phases silently desyncs the advance loop.
- **Content-hash bridge (part of c7):** c0's `phase_artifact_hash`/`advance_gate` have ZERO live consumers
  (`gate_executor.run_gates` adjudicates a flat evidence dict via `classify_*`). c7 must bridge
  env-artifact→flat-gate-evidence and re-validate via `advance_gate`, with a tampered-artifact-refused oracle.
- **WORKS bar (load-bearing):** the P2.1 EPIC oracle MUST assert a **CALL-path by driving REAL `run_hunt`
  over a REAL fixture target**, proving `detect→provision→jail_build→health_probe→reachability_probe→
  baseline_capture→hunt` traversal with genuine per-state content-hashed evidence, each `advance_gate`
  fail-closed, plus a tampered-artifact-refused control and a safe-fixture-refuses-at-earliest-failing-state
  control. **Import-reachability is explicitly DISQUALIFIED** (this is X17/G14). Do NOT mark P2.1 done on
  green c1–c6 oracles.
- **Dependencies:** `cP-provision ⟶ P0.2-NGv2`; `c7 ⟶ {c1..c6 handlers} ∧ {cP producers}`; `P2.2 ⟶ c7`.
- **Effort/§7:** the §7 rollup hides the producer + integration mass. The 6 pure handlers are the cheap half
  (4 landed in 1–2 attempts). The uncosted work is cP (6 impure producers = the actual env stand-up: jailed
  lockfile venv build, in-jail import + loopback service-start probe, settrace benign-ping, FS+stdout baseline
  snapshot) + c7 (one multi-file SERIAL leaf touching 8+ shared symbols). True net-new surface ≈ 3 handlers +
  6 producers + 1 serial integration — NOT "mostly wiring." c7 cannot fan out (serial bottleneck). c4
  (HEALTH-PROBE service-start) remains the long pole and its producer doubles the net-new service-startup
  surface. Budget the producer half at the §6 "1.5–2× attempts/landed" net-new rate.

### P0.2-NGv2 (DOC-B §4, new enumerated Wave-0 prereq node, sibling of P0.2-JM)
`ngv2/poc_runner_live.py::_default_pip_installer` is still host-side, network-ON, single attacker-named-package
(reactive `_missing_modules_from_stderr` loop, `MAX_DEP_INSTALL_ROUNDS=3`), no `--unshare-net`/lockfile.
Fully unbuilt — NO oracle, NO impl. Reuse the JM `target_bootstrap` technique. Hard-gates cP-provision.

## 6. ROADMAP / FORWARD SEQUENCE (apply)

Drop every spent "next action = P0.1/P1.1" pointer. Corrected spine to state as current:
`P0.1 ☑ → P0.2-JM ☑ → P1.1-wiring ☑ → P1.2 ☑(+residuals) → P1.3 ☑ → [P0.2-NGv2 → P2.1-cP] → P2.1-c4/c5/c6
→ P2.1-c7 (the BUILT→WORKS gate: real run_hunt detect→…→baseline traversal) → P2.2 → P3.1 → P-CAPSTONE(X1)`.
The single load-bearing next deliverable is **P0.2-NGv2 → P2.1-cP** (unblocks the producer layer X1 needs).
The reordering (P2.1 children landing before P2.2/P3.x) is the PLANNED fan-out, not scope drift — but note
that what fanned out was the cheap pure-handler half, leaving the producers + serial integration (the real
env stand-up) ahead.

## 7. DEVIATION-LOG TREATMENT (apply)

Replace DOC-B §8 append-only log and DOC-A §8A/§8B with a single concise **current-state** subsection in each
("Deviations from the original plan & how the forward plan accounts for them"). Keep only durable lessons:
(1) a prerequisite-hardening phase ran first (agy_pool config-dir keystone `b0d6999` restored dual-agent
synthesis — RESOLVED); (2) P2.1 shipped pure adjudicators with producers + live integration deferred → green
orphans → the WORKS bar must be a real run_hunt CALL-path (G14/X17); (3) wire-up portability (G13/P-WIREUP)
is a self-contained JM sub-program. Drop all dated blow-by-blow, nested-symbol-patch saga, depth-4 escalation
narration, and self-contradicting "zero contracts landed" entries.
