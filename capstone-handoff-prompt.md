# CAPSTONE HANDOFF PROMPT — NobleGreedv2 Closure Program (X1/X2)

**Written:** 2026-06-26 ~09:34 EDT · **Author:** the orchestrating Claude (oversight role)
**Factory state at handoff:** STOPPED GRACEFULLY (see §4). JanusMaskJR HEAD `25660f7`; NobleGreedv2 HEAD `53a97b1`.
**Why this exists:** the program reached the final capstone (X1/X2), the capstone brief was authored + adversarially reviewed + ingested, but the **planner crashed** while planning it. The owner asked to pause, shut down, and hand off. This document is a self-contained resume-prompt: read it top-to-bottom and you can continue with zero loss.

> **READ THIS FIRST, then actually read the three grounding docs in §2 before doing anything.** The owner checks whether you grounded. Do not claim grounded off this handoff alone.

---

## 0. YOUR STANDING DIRECTIVE (verbatim — this is the mission)

> "Ground yourself. Read README.md, really read it, and execute `/home/xnihil0zer0/AI-Data/Research-JanusMask/NobleGreedv2-end2end-gap-analysis.md` and `/home/xnihil0zer0/AI-Data/Research-JanusMask/NGv2-closure-deliverables-and-acceptance-contract.md` through the pipeline. Picking up where it was left off, continuing factory runs. Be maximally efficient with token usage, limiting reading/writing/polling to maximize your oversight. Use the oversight monitor. Delegate brief authorship to sub agents. Bugs must be fixed as they are encountered. Any deviations from the path, to fix bugs, requires an adversarial review from a sub-agent, with test results, from an analytic script. If that agent verifies the bug, they should then draft a brief and have it ingested by the factory factory. Nothing is done until it's wired up, and has actually been demonstrated as running. NobleGreedv2 is in `/home/xnihil0zer0/NobleGreedv2`."

---

## 1. OPERATING DISCIPLINE (binding constraints — owner-given, do not violate)

- **DELEGATE everything; your context = oversight only.** Route + decide; fresh sub-agents execute + return verdicts. Investigation, authoring, verification all go to sub-agents.
- **Use a FRESH agent for divergent sub-tasks — NEVER `fork`.** A fork inherits your context and will pursue the dominant in-context task instead of its prompt. Never let a delegated agent hold an approval gate.
- **BUILT ≠ WORKS. "done" = observed-working, NEVER a green gate.** A green oracle is necessary, not sufficient. The system Goodharts cheap proxies for "works"; you must demonstrate the real capability live.
- **NEVER claim a capability works without EMPIRICAL ledger/runtime proof.** Grep the ledger, read the code, re-measure. The owner has caught false "it works" claims before ("stop lying").
- **PIPELINE-FIRST is mandatory.** The ONLY hand-authorable artifacts are the **brief** and **pre-committed test oracles**. All production code (`harness/**`, `config/**`, `scripts/**`, `services/**`, and all `ngv2/**` target code) is changed through the planner→stage→worker pipeline. Never hand-edit production. An unavoidable hand-edit must be cleared with the owner FIRST. Attempt impure/"irreducible" code through the pipeline ONCE (documented failure) before declaring a hand-edit is needed.
- **Bugs encountered on the path → adversarial review → brief → ingest.** Any deviation to fix a bug REQUIRES: a sub-agent that verifies the bug with **test results from an analytic script**; if verified, that agent drafts a brief; the brief is ingested by the factory. Do not band-aid instances — fix the ROOT CAUSE through the pipeline (it becomes reusable by definition). All fixes are PERMANENT root-cause harness changes.
- **Recurring failure pattern → root-cause brief through the pipeline.** Don't fix each instance.
- **Security (non-negotiable):** untrusted target code NEVER runs un-jailed (NGv2 FLAG2 — "nothing about a target is trusted"); target code runs ONLY inside the bubblewrap detonation jail; **fail-closed** on any jail/namespace-create failure (never degrade to host `--share-net`). Do NOT run `run_hunt` against `/home/xnihil0zer0/NobleGreedv2/targets/*` (untrusted real-target pool) — use only in-repo `_e2e_run/` or `tests/ngv2/_pcapstone_fixtures/` fixtures. Do NOT edit `harness/**`/`config/**`/`scripts/**`/`services/**` without the `harness_self_fix` path + (for the irreducible set) a decision file. Sub-agents must NOT git commit/push, touch the daemon, or read/print secrets.

---

## 2. GROUND YOURSELF (do this before acting — the owner verifies it)

Read these three in full, this session, not from memory:
1. `/home/xnihil0zer0/AI-Data/JanusMaskEX/README.md` — the factory's operator reference (lifecycle, gates, allowlist, submission formats, `meta_task_type` taxonomy, `_NEVER_AUTO_APPROVE`).
2. `/home/xnihil0zer0/AI-Data/Research-JanusMask/NobleGreedv2-end2end-gap-analysis.md` — the gap taxonomy G1–G14, the Environment-Readiness + Detonation-Trust FSM design, the §7 closure roadmap, the PIPELINE-FIRST policy.
3. `/home/xnihil0zer0/AI-Data/Research-JanusMask/NGv2-closure-deliverables-and-acceptance-contract.md` — the exit criteria X1–X17, the per-contract deliverables (P0–P4 + P-CAPSTONE + P-WIREUP), §5 cross-cutting gates.

Also load the operator memory: `/home/xnihil0zer0/.claude/projects/-home-xnihil0zer0-AI-Data-JanusMaskEX/memory/MEMORY.md` (index) and especially the active-program topic file `ngv2-closure-program-active-2026-06-24.md`.

---

## 3. THE MISSION IN ONE PAGE

**The one-sentence finding (from the gap analysis):** *Nothing in the pipeline ever stands up a target's real runtime, so nearly every `verdict=confirmed` to date is a self-contained re-implementation (mock) the oracle cannot distinguish from a real exploit* — exactly one historical confirm (gptcache CWE-78) faithfully detonates, via a direct internal call needing no env. The fix is a deterministic, **fail-closed Environment-Readiness + Detonation-Trust FSM** built through the JanusMask factory and integrated into NGv2's `ngv2/` package.

**JM-as-factory split:** JanusMaskJR (`/home/xnihil0zer0/AI-Data/JanusMaskEX`) is the FACTORY — it compiles briefs → verified code via blind dual-LLM (Claude+Gemini) + differential fuzz + pre-committed oracle gates. NobleGreedv2 (`/home/xnihil0zer0/NobleGreedv2`) is the HUNT ENGINE (the `ngv2/` package). Briefs/plans/ledger live in JM; the code LANDS in NGv2 (via `working_dir`); VERIFY commits happen in `git -C ~/NobleGreedv2`.

**The bar (acceptance contract §2):** DONE = a **safe-fixture-refuses / vuln-fixture-confirms** oracle run through the **REAL `run_hunt`** (the autonomous conductor, NOT a hand-driven `drive_*.py`), with a **CALL-path proof** (X17 — import-reachability is explicitly DISQUALIFIED).
- **X1** = a vuln fixture is `verdict=confirmed` end-to-end through `run_hunt`.
- **X2** = a safe fixture (same shape, patched) is REFUSED with a typed terminal (not `confirmed`, not opaque `blocked`).
- **X5** = a CSPRNG per-run nonce, persisted, passed by the live caller to the verdict gate. **(LANDED — see §5.)**
- **X17** = every FSM handler proven CALLED on the live path (call-trace, not import).

**The spine (sequence):** `P0.1 ☑ → P0.2-JM ☑ → P1.1 ☑ → P1.2 ☑ → P1.3 ☑ → P2.1 (env-FSM front half) → P2.2 → P3.1 → P-CAPSTONE (X1/X2)`.

**What has LANDED + been WORKS-verified (the frontier):**
- P0.1 (G7 fuzz-jail cred-free), P0.2-JM (G8 jailed lockfile install), P1.1 (every transition gated + typed terminals), P1.2 (authenticity/provenance), P1.3 (LoopbackListener wired + per-CWE channels).
- **P2.1 env-FSM FRONT HALF: c0–c6 handlers + cP producers + c7 live integration** — a live unmocked `run_hunt` now traverses `detect→provision→jail_build→health_probe→reachability_probe→baseline_capture→hunt→triage→verify→poc→detonate` data-driven.
- Bug fixes landed along the way: `conductor_seams` os-unbound (`34860c9`), health jailed-import/reachability (`84f9658…f1633ed`).
- **`verify_triage_live_seam_repair` ☑ WORKS** (NGv2 `a3d5806`/`0fef40c`/`ec92898`) — bound 3 dead gate-imports via anti-gaming adapters + killed an agy-dict-crash verify infinite-respawn. Live: vuln→advance, safe→refuse, no rubber-stamp.
- **`detonation_nonce_bound_confirm` (X5) ☑ WORKS** (NGv2 `6a732f0→53a97b1`) — per-run CSPRNG `secrets`-nonce gated on `<<NONCE>>` presence; the forgeable confirm (static `VULNERABLE`/`pwned_marker` constants) is closed. WORKS-verified 5/5 through a real nested-bwrap loopback jail.

> **⚠️ TRUST CAVEAT (audit `a372825bd`):** the landings since ~2026-06-23 (incl. X5, verify-triage) were synthesized by **agy-fallback + gemini, NOT genuine Claude+Gemini** — real Claude was dark (§6 BUG 2). They passed the deterministic gates (oracle / differential-fuzz / jail), but the blind *dual-independent-family* discipline was degraded. Consider a re-verification pass once real Claude is restored.

**What remains for X1/X2:** the capstone — a single continuous `run_hunt` over an in-repo vuln/safe fixture PAIR must reach `detonate` and produce the nonce-bound `confirmed` (vuln) / typed-terminal `refused` (safe). That is `P-CAPSTONE` (§5), which was being ingested when the planner crashed (§6).

---

## 4. FACTORY STATE AS LEFT (2026-06-26 ~09:31 EDT) + HOW TO RESTART

**Stopped gracefully.** Ledger shows `drain_start → drain_complete (killed=0, drained=1) → daemon_stop|shutdown`. The daemon child (was pid 165428) is gone, the pidfile is cleared, and **no** `autowork_daemon`/`run-autowork`/`selfheal` processes remain.

**Stop flags PRESENT (you must remove these to resume):**
- `state/control/autowork/full_stop` — persistent hard stop (halts promotion + dispatch, breaks the loop, disables supervisor respawn).
- `state/control/autowork/pause` — dispatch pause (redundant belt-and-suspenders).
- (`supervisor.stop` was consumed by the supervisor on exit.)

**To restart the factory (AFTER you resolve the planner-crash root cause — see §6/§7; do NOT blind-restart or it will re-crash):**
```bash
cd /home/xnihil0zer0/JanusMaskJR
rm -f state/control/autowork/full_stop state/control/autowork/pause
scripts/run-autowork.sh --state-dir state --logs-dir logs --config harness/config.yaml
# (the supervisor self-respawns the daemon child; PID lands in state/control/autowork.pid)
```
- The daemon **reads `harness/config.yaml` once at startup** and **caches its own code at startup** — any config-knob or daemon-loop change needs an edit+commit+restart (`kill -TERM "$(cat state/control/autowork.pid)"`, supervisor respawns).
- On restart the daemon plans the **newest-mtime allowlisted unplanned** brief. The capstone brief (`brief_hooks_pcapstone_run_hunt_x1_x2.md`, mtime Jun 26 08:55) is the newest — but it is **PARKED** (see §6); a blind restart re-fires the same ~17-min planner run and likely re-crashes.

---

## 5. THE CAPSTONE — `P-CAPSTONE` / slug `pcapstone_run_hunt_x1_x2` (the immediate goal)

**Brief file:** `/home/xnihil0zer0/JanusMaskJR/brief_hooks_pcapstone_run_hunt_x1_x2.md` (28 KB).
**Allowlist:** the slug is **already appended** to `state/control/autowork/auto_promote.allowlist` (tail, with a full provenance comment block). Do NOT re-append.
**Intent:** the program-level proof — closes **X1** (vuln confirmed end-to-end through real `run_hunt`) + **X2** (safe twin refused at a typed terminal). `meta_task_type: test_acceptance`, `working_dir: NGv2`.

**4 SERIAL tasks (deps 1←2←3←4, all pinned in `required_task_ids`):**
1. `pcapstone-health-guard-oracle` — `test_authoring`, `mutation_target = ngv2.health_producer` (RED oracle for fix A).
2. `pcapstone-health-guard-impl` — `io_adapter`, edits `ngv2/health_producer.py` (**engine fix A**) via `__JANUSMASK_PATCHES__` SYMBOL patch.
3. `pcapstone-evidence-nonce-impl` — `io_adapter`, edits `ngv2/conductor_seams.py` (**engine fix B**) via a **dotted-nested** SYMBOL patch `build_default_seams.build_evidence`.
4. `pcapstone-run-hunt-x1-x2-oracle` — `test_acceptance`, the capstone oracle + the 6 fixture files under `tests/ngv2/_pcapstone_fixtures/{vuln,safe}/`.

**Engine fix A (`ngv2/health_producer.py::produce_health_input`, ~:248-250; helper `is_valid_identifier` ~:65):**
Guard `if entry_point and is_valid_identifier(entry_point): modules_to_probe.append(entry_point)` so a repo-**PATH** `entry_point` (which `conductor_seams.py:394` hands in as `state['target']`) is ignored and only the discovered module name (`svc`) is probed → `import_ok=True`. This is a GENUINE all-targets wiring bug (the live FSM stalls at `health_probe → service_no_bind` otherwise). Adversarially proven RED→GREEN two ways (bwrap-free recorder: HEAD probes `['import /tmp/...repo','import svc']` → after guard `['import svc']`; real jail: HEAD `import_ok=False genuine_import_error` → patched `import_ok=True clean`).

**Engine fix B (`ngv2/conductor_seams.py`, the nested `build_evidence` closure inside `build_default_seams`, ~:181-190):**
Thread the nonce from where the worker buries it:
```python
raw = ev.get('detonation_report_raw')
raw_nonce = None
if isinstance(raw, dict):
    raw_nonce = raw.get('nonce')
    if raw_nonce is None and isinstance(raw.get('raw_result'), dict):
        raw_nonce = raw['raw_result'].get('nonce')
    if raw_nonce is not None:
        ev['detonation_nonce'] = raw_nonce
```
The top-level `raw.get('nonce')` (X5 path) is read first; the `raw_result.nonce` fallback is the continuous-run path. **The dotted-nested patch APPLIES** (review-confirmed): `_apply_symbol_patch(src,'build_default_seams.build_evidence',...)` via `harness/git_integration.py:1206` (dotted 2-part branch `:1350-1354`) yields exactly 1 `build_evidence` def, no duplication, correct reindent at col 8. (`build_evidence` is a *direct* child of `build_default_seams`, col_offset 4.)

**Fixture design (why under `tests/`):** `test_acceptance` is NOT in the `_split_multifile_module_tasks` skip-set, BUT the `'tests/' in f` exclusion (`harness/planner/plan_normalizer.py:1172`) saves the 6 fixture files from the split (so the pinned `required_task_id` survives — otherwise `missing_required_task` rc=1), and the orphan_unwired gate skips `'tests' in Path(rel).parts` (`harness/orchestrator.py:2357`) + non-`.py` (`:2355`). The oracle uses the REAL `poc_writer.write_poc(client=None)` (AST-grounds a faithful CWE-78 PoC carrying `<<NONCE>>`) + the REAL `pattern_scanner.scan_directory`.

**Adversarial review (`aa271f3a`, INGEST WITH EDITS — all empirical):**
- Both engine fixes RED→GREEN proven (bwrap-free + real nested-bwrap jail). Dotted-closure patch applies. tests/ gate-evasion confirmed in source. Honesty clean.
- **NON-VACUITY CONFIRMED:** both twins are produced by the IDENTICAL offline floor and an IDENTICAL sink bridge, so `sink_presence`/`sink_reachability` evaluate identically; **ONLY `detonation_evidence`** (the real bwrap-jailed detonation of the differing `svc.py`) differentiates them. VULN → `run_gates(detonate→novelty) advance=True`; SAFE → `advance=False blocked_by=['detonation_evidence']` with `exit_code=0` (genuinely ran-and-inert, not a short-circuit). Both twins pass `poc_authenticity`, so X2's refute genuinely lands AT detonate.
- **The ONE blocking edit (applied):** TASK 4's hunt-rollup enrichment originally listed only `category`/`evidence`/`target`, which left `sink_name`/`call_sites` unset → the VULN twin blocked at detonate→novelty on `sink_presence/sink_reachability: missing_evidence` → X1 RED forever. The edit bridges `sink_name='os.system'` + `call_sites=['os.system("getent hosts " + host)']` (**a LIST OF CODE-SNIPPET STRINGS, never dicts** — a dict crashes `assess_sink_reachability` with `TypeError: unhashable type: 'dict'`; the snippet must contain the sink with a NON-CONSTANT arg), applied **identically for both twins**. Do NOT add `expected_signature` (it auto-derives from `sink_name` at `conductor_seams.py:159`).
- **Verdict-source caveat:** the oracle reads `confirmed`/`refuted` from the **conductor/gate-level** adjudication (advance→confirmed; `gate_executor` `REFUTED='refuted'`), NOT the raw detonate-worker `report['verdict']` (which is `'success'`/`'failure'`).

**Author re-validation (`ab28e7c5`, PASS):** applied the blocking edit, added the non-vacuity-invariant + verdict-source notes, re-ran `load_brief` (no `BriefValidationError`; 5 sections non-empty; all 4 `required_task_ids` present in serial order; `integration` in every `non_goals`), confirmed the enrichment now emits `sink_name='os.system'` + a string `call_sites` for both twins.

**→ The brief is READY and ingested. It only needs to PLAN.** That is where it broke (§6).

---

## 6. THE BLOCKER — planner crashed planning the capstone (RESOLVE THIS FIRST)

When the daemon planned `pcapstone_run_hunt_x1_x2`, the **planner subprocess crashed `rc=1` after ~17 min** (`wall=1024.8s`). Ledger row (`event: planner_validation_rejected`, mislabeled — it is a CRASH, not a brief-validation refusal):
```
File ".../harness/planner/cli.py", line 72, in attribution_stamp
    return _stamp(merged_tasks, plan_diff, recon_result, bootstrap)
File ".../harness/planner/attribution.py", ...   <-- truncated by the 512B ledger stderr_tail
```
So the crash is inside `harness/planner/attribution.py::stamp_attribution` (imported as `_stamp`), AFTER blind-drafts + diff + reconciliation succeeded. **PINNED by offline analytic repro (adversarial audit `a372825bd`): the failing line is `attribution.py:69` — `raise StampingError(f"Task {task_id} already has a non-null spec_author.")`.** Gemini emitted draft tasks with `spec_author='gemini'` PRE-SET (the pcapstone brief's `# Required plan shape` discusses `spec_author`, which plausibly induced it), violating `stamp_attribution`'s contract that merged tasks arrive with a NULL `spec_author` (the stamper is what assigns it). Feeding the preserved crash diff `state/planning/current_diff.json` (the 4 pcapstone tasks, every `gemini_task.spec_author='gemini'`) through `stamp_attribution` raises verbatim `StampingError: Task pcapstone-evidence-nonce-impl already has a non-null spec_author.` on the FIRST task — consistent with **zero** attribution lifecycle rows for any `pcapstone-*` task (the `_emit_attribution_lifecycle` call is at :78, after the :69 raise).

**Park state:** `state/control/autowork/plan_attempts/pcapstone_run_hunt_x1_x2.json` = `{"attempts":1,"deterministic":false,"last_ts":1782479602.65}`. `deterministic:false` ⇒ non-deterministic backoff (300s→3600s→86400s), NOT 24h-suppressed → a restart will RE-PLAN (and likely re-crash if the cause is deterministic).

**CONFIRMED ROOT CAUSE — there are TWO DISTINCT bugs (adversarial audit `a372825bd`, analytic-script repro + quoted artifacts; verdict PARTIALLY-TRUE on my original lead — the single-agent attribution was an over-reach):**

**BUG 1 — the proximate crash (blocks the capstone): gemini draft-contract violation + brittle `:69` invariant.** Gemini emits draft tasks with `spec_author='gemini'` pre-set; `stamp_attribution` requires null and fatally raises at `attribution.py:69`. **Single-agent degeneration is NOT the root cause** — 40 prior `gemini_only` plans stamped FINE (their tasks had null spec_author), so gemini-only is provably not sufficient to crash. Empty-Claude only *removed the masking*: with Claude empty, reconciliation routes gemini's poisoned task straight into `merged_tasks` (a convergent dual-agent task would take Claude's null-spec_author version first — `reconciliation.py:90`). FIX SURFACE: (a) blind-draft/normalizer STRIPS/nulls any agent-supplied `spec_author` before `stamp_attribution`, and/or (b) `attribution.py:68-69` OVERWRITES a pre-set spec_author instead of raising. (The run is `--bootstrap` by default — `cli.py:404` / `autowork_daemon.py:1604` — which is why an empty-Claude draft sails past the `cli.py:464` `PLANNER_LOUD_FAIL_EMPTY_DRAFT` exit-2 guard and reaches the stamper at all.)

**BUG 2 — the SYSTEMIC factory-health failure (worse than BUG 1; affects EVERYTHING): real Claude has been DARK since ~2026-06-23, in BOTH planner AND synthesis, silently masked.** The live `state/planning/sessions/logs/claude_stream.jsonl` (crash run) ends with four `{"is_error":true,"result":"Not logged in · Please run /login"}` results at ~42ms/0 tokens = an AUTH failure (missing-credentials `CLAUDE_CONFIG_DIR` under the headless backend). 40/40 `gemini_only` with ZERO `claude_only` confirms genuine emptiness, not task_id mismatch. **The "synthesis proves Claude works" counter-argument is REFUTED:** real Claude is dead in synthesis too — newest genuine `state/sessions/claude_round1_*_submission.json` = 2026-06-23 16:21:34; after that **0** real claude + **134** `claude_fallback_round1_*` (the fallback binary = `agy`/Gemini per `config.yaml`+README §2), substituted at `orchestrator.py:1138` yet still logged as `agent=claude status=submitted`. So tasks landed via **agy-fallback + gemini = NO genuine Claude, and not a blind dual-agent of two independent families** — the "author never grades its own exam" guarantee (the program's foundation) has been SILENTLY VIOLATED for ~3 days, including the recent X5/verify-triage landings. Real Claude went dark right around the headless cutover `b47e8ad` (2026-06-23 17:21). `fa9f44d`'s premise (Claude dark, need tmux) was CORRECT; the **manual** revert `25660f7` (see §8) dismissed it by MISCOUNTING fallback rows as Claude. FIX SURFACE: restore real Claude auth under headless — seed creds into the per-task `CLAUDE_CONFIG_DIR` (memory `claudecap-landed-split-and-configdir-contract`, `factory-backend-headless-cutover-2026-06-23`), **likely an OPERATOR action** (interactive `claude /login` / credential seed), OR re-flip to the tmux PTY backend (subscription auth) + restart the daemon. Until BUG 2 is fixed the factory is NOT running the dual-agent discipline the program requires.

**Evidence preserved for the root-cause agent:** `/home/xnihil0zer0/JanusMaskJR/_autowork_scratch/pcapstone_planner_crash_2026-06-26/` (`planner_progress.jsonl`, `sessions/`, `park_marker.json`). The full `stamp_attribution` source is at `harness/planner/attribution.py:34-135`.

---

## 7. EXACT NEXT STEPS (resume here, in order)

**Step A — Ground (read §2's three docs + memory). The owner verifies grounding.**

**Step B — Fix the TWO confirmed bugs from §6 (root-cause is ALREADY DONE by audit `a372825bd`; do NOT re-investigate from scratch).**
- **BUG 2 FIRST (systemic — restores the trust guarantee AND removes BUG 1's amplifier):** real Claude is dead under headless (`Not logged in`). This is most likely an OPERATOR/auth fix, not a pipeline-buildable code change — **surface it to the owner**: either seed real Claude credentials into the headless per-task `CLAUDE_CONFIG_DIR`, or re-flip `harness/config.yaml claude_backend: headless→tmux` (PTY/subscription auth) + commit + restart the daemon. (Suggest the owner run an interactive login in-session via `! claude /login` if creds are the issue.) **VERIFY empirically after the fix:** a fresh planner run must show `claude_only`/`convergent`/`divergent` attribution rows (NOT 40/40 `gemini_only`) AND `state/sessions/claude_round1_*` (NOT `_fallback_`) submissions. Do NOT resume the program's trust-critical work until genuine dual-agent (Claude+Gemini) is restored — everything landed since ~2026-06-23 was agy-fallback+gemini and may warrant a re-verification pass.
- **BUG 1 (the capstone crash — `attribution.py:69`):** draft a `harness_self_fix` brief (the bug is in `harness/planner/` — sensitive `harness/**` but NOT in `_NEVER_AUTO_APPROVE`, so auto-approvable, no decision file) that makes the planner robust to an agent-supplied `spec_author`: strip/null it in the blind-draft/normalizer before `stamp_attribution`, and/or make `attribution.py:68-69` overwrite-not-raise. Pre-committed RED oracle = feed a draft/diff whose merged task carries `spec_author='gemini'` and assert `stamp_attribution` stamps cleanly (today it raises `StampingError`). Ingest, build, **restart the daemon** (harness change). This fix should hold even once dual-agent is restored (a `gemini_only` task can still arrive spec_author-set).
- **Order/why:** BUG 2 is the higher-stakes systemic fix and may be a quick operator login; BUG 1 unblocks capstone PLANNING specifically. Do BOTH before re-ingesting the capstone. Once both land, clear the park (`rm state/control/autowork/plan_attempts/pcapstone_run_hunt_x1_x2.json`) and restart — the capstone should then plan clean. (This whole step already satisfies the "bug on the path → adversarial review with analytic-script test results → brief → ingest" directive: audit `a372825bd` IS that review.)

**Step C — Once the capstone PLANS clean:** it builds the 4 serial tasks. Monitor with the oversight monitor scoped to the slug (`MON_SLUGS=pcapstone_run_hunt_x1_x2`) — do not poll. On all-4-landed, do NOT call it done.

**Step D — WORKS-verify X1/X2 on the LANDED code** via a FRESH agent (this is the milestone, not the green oracle): drive a **live continuous `run_hunt`** over the in-repo `tests/ngv2/_pcapstone_fixtures/{vuln,safe}/` pair and confirm:
- VULN → `verdict=='confirmed'` with the CSPRNG nonce ∈ stdout ∧ ∈ fs_snapshot_diff ∧ `ev['detonation_nonce']==nonce` (X1), via the real nested-bwrap jail.
- SAFE → `'detonation_evidence' in blocked_by` / typed-terminal `refuted` (X2).
- NON-VACUITY holds: the verdict difference comes ONLY from `svc.py` via the real jailed detonation (the bridged metadata is identical for both twins).
That live demonstration closes the **X1/X2 milestone** ("it now WORKS").

**Step E — After the capstone WORKS:** update memory + the acceptance-contract checkboxes (X1/X2/X17). Then the tracked-deferred siblings and remaining spine:
- Extend `<<NONCE>>` to the other 6 CWE templates (full per-CWE nonce-binding).
- `python_bin ↔ resolved_python_bin` key mismatch in `_assemble_target_spec` (breaks pinned-interp targets).
- `poc` seam `complete` vs `complete_text` (LLM-refine dead, harmless); `reachability_producer` 2nd unjailed import; `detect_producer:159` no-exists-check.
- Verify P2.2 (`detonation_seam_full_target_spec`) and P3.1 (`authz_idor_two_actor`, slug `p31_authz_idor_two_actor` was allowlisted) landed; then P3.2 (JS first-class), P4.x, and the cross-cutting P-WIREUP sub-program.
- 3 pre-existing `test_p11_build_evidence_perphase` failures are unrelated/out-of-scope (`_PHASE_COUNT_KEY` env_artifact gap).

---

## 8. KEY STATE REFERENCES & GOTCHAS

- **Real ledger:** `state/impl_progress.jsonl`. Authoritative "done" = an `auto_commit` row (`phase:accepted`, with `commit_sha`). `ts` can be a float. **Cross-check the ledger + `git -C ~/NobleGreedv2 log` before acting on any monitor snapshot — snapshots can be stale.**
- **Allowlist:** `state/control/autowork/auto_promote.allowlist` (deny-all when empty; one slug per line; `#` comments). The capstone slug is appended at the tail with provenance. Touch the file to wake an idle daemon.
- **External roots:** `state/control/autowork/external_roots.allow` lists `/home/xnihil0zer0/NobleGreedv2` (approved). NGv2 tree must be CLEAN before any external staging (`EXTERNAL_DIRTY_GATE`); it was clean (0 porcelain) at handoff.
- **Backend:** `harness/config.yaml:183 claude_backend: headless` (see §6 BUG 2). `fa9f44d` flipped it headless→tmux 2026-06-25 20:39 ("restore dual-agent auth"); the **manual** revert `25660f7` (2026-06-25 21:04, "Revert … fa9f44d premise was false") flipped it back — but that revert's premise MISCOUNTED agy-fallback rows as real Claude, so `fa9f44d` was right and `25660f7` was wrong. Config is read once at daemon startup. The headless cutover `b47e8ad` (2026-06-23 17:21) is when real Claude went dark (`Not logged in` / missing-creds `CLAUDE_CONFIG_DIR`).
- **Oversight monitor:** `_autowork_scratch/oversight_monitor.py`. Env: `MON_SLUGS`, `MON_TASKS` (comma-sep), `MON_MAX_SECS`, `MON_POLL`. Exit codes: 0=SUCCESS, 2=STALL, 3=THRASH, 4=DEADLOCK, 5=HEARTBEAT, 6=DAEMON_DEAD. (It has been killed externally in past sessions — fall back to event-driven `grep` of the ledger.)
- **Daemon idle sleep (1800s) can outlast retry backoff (300s)** — `touch` the allowlist to wake it now.
- **Sensitive paths:** `_NEVER_AUTO_APPROVE` = `agent_jail.py, dbus_proxy.py, paths.py, git_integration.py, orchestrator.py, interceptors.py, selfheal.py, autowork_daemon.py, services/**` — these need a pre-authored `state/control/decisions/<task_id>.json` `{"decision":"approve"}` (pin `required_task_ids`). `harness/planner/*.py`, `harness/wire_up.py`, `state_reconciler.py` are sensitive but auto-approvable.
- **Brief hard rules (so a brief plans, doesn't crash/park):** five bare headings (`# Title/# Scope/# Inputs/# Non-Goals/# Deliverables`), impl-first RED-pair (one impl task per file via `__JANUSMASK_PATCHES__` SYMBOL patch + a terminal `test_authoring` oracle), self-contained `python -c` smoke vcmds (no `.py`/`cd`/pytest token → else `_circular_vcmd`; no `cd ` → `cd_prefixed_verification_command`), each impl `test_spec` ≥2 regression + ≥1 property/edge, `non_goals` must contain the literal word `integration`, `ngv2/**` is EXTERNAL (`io_adapter`, no decision file), new top-level symbols need an R-anchor, nested closures patched via dotted `Enclosing.nested`, `required_task_ids` neutralizes `_drop_committed_module_impls` + `_drop_redundant_precommitted_oracles`. For external ngv2 code, `os.urandom`/`uuid`/`random`/clock are AST-banned (ast_enforcer coerces `allow_nondeterminism=False`) but `secrets` passes.
- **Memory:** write durable facts to `/home/xnihil0zer0/.claude/projects/-home-xnihil0zer0-AI-Data-JanusMaskEX/memory/`. The active-program file is `ngv2-closure-program-active-2026-06-24.md`. (MEMORY.md is over its size limit — keep index hooks short; move detail into topic files.)

---

## 9. ADVERSARIAL-REVIEW / AGENT RECORD (traceability)

- `aa271f3a521bef559` — P-CAPSTONE brief review → **INGEST WITH EDITS** (one blocking sink-bridge edit; everything else empirically sound). Output: `tasks/aa271f3a521bef559.output`.
- `ab28e7c5efadf9f0d` — P-CAPSTONE author → applied the blocking edit + re-validated → **PASS**. Output: `tasks/ab28e7c5efadf9f0d.output`.
- `b576dcc71` — oversight monitor on the slug → **STALL** (brief stuck `unplanned`; the planner crash). Output: `tasks/b576dcc71.output`.
- (Earlier, all WORKS-verified: `verify_triage_live_seam_repair`, `detonation_nonce_bound_confirm`/X5.)

---

## 10. THE ONE-LINE SUMMARY

The env-FSM is built and the live `run_hunt` traverses end-to-end; X5 nonce-binding is done and demonstrated; the X1/X2 capstone brief is authored, adversarially reviewed, edited, and ingested. Two confirmed bugs block it (audit `a372825bd`): **BUG 1** — the planner crashes at `attribution.py:69` because gemini emits tasks with `spec_author` pre-set (harden the stamper / strip it upstream); **BUG 2 (worse)** — real Claude has been DARK (`Not logged in`, headless creds) since ~2026-06-23 in BOTH planner and synthesis, masked by the agy-fallback that logs as "claude", so the dual-agent trust guarantee has been silently violated for ~3 days (restore Claude auth — likely an operator login or a tmux re-flip). Fix BUG 2 (restore genuine dual-agent) + BUG 1 (harden `stamp_attribution`), let the capstone plan + build, then WORKS-verify the live vuln→confirmed / safe→refused pair. Nothing is done until it's demonstrated running.
