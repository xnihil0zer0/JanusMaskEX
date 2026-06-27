# PLAN — Resume Autonomous End-to-End Bounty-PoC Hunts (2026-06-17, rev. 5)

**Status:** CANONICAL. Supersedes the stale parts of `DESIGN_self_healing_remediation_agent.md`
and `INTERVENTION_PLAN_v2.md`. Built from successive evidence-backed adversary panels, **CORRECTED
by a 5th forensic 4-agent panel (2026-06-17, all scripted, three independent datasets)** that
overturned the *previous* "source_meta is the money blocker" thesis.

**★ HEADLINE — WHY THIS REVERSES rev. 4 (and why this one is trustworthy):** rev. 4 claimed
"`is_source_driving` needs http `source_meta` and **0/148 findings carry it** → that plumbing is THE
blocker." **That number was queried from the WRONG store** (the campaign sqlite `findings` tables hold
only 14 stale e2e rows, all `source_kind=None`). The authoritative finding stores were re-counted by
**three independent agents on three different datasets** and all refute it:
- Agent A — `state/campaign/out/*/hunt_hunt_*.json`: **7/74 carry `source_kind=='http'`, 69/74 carry
  non-empty `source_meta`.**
- Agent B — fresh litellm clone via `hunt_lead_client._candidate_from_hit`: **13/408 http (4 fastapi).**
- Agent D — `source_localize.localize_source` fires `http/fastapi/high` on the real InvokeAI route.

**The source_meta plumbing WORKS end-to-end** (lead → `_coerce_finding` → `_overlay_source_meta` →
Grounding; the rev. 4 "`_coerce_finding` drop" was a scripted-refuted phantom). The S1 fix rev. 4
named (`hunt_lead_client._normalize_candidate`) targets a **dead code path** — CodeQL leads are
default-ON and short-circuit it (`hunt_lead_client.py:142-143`); **0/74 live findings flow through
`_normalize_candidate`.** So the previously-named money blocker does not exist.

**What is STABLE across every panel (the durable truth):** **0 confirmed PoCs**, BUILT≠WORKS, and an
import-call skeleton ≠ a claimable PoC. What flip-flopped is only the *named* gate. This panel dissolves
the flip-flop: the blocker was never one thing — it is a **downstream cluster of four real walls** that
sit AFTER source_meta, plus a most-efficient concrete first target. Commit SHAs and `file:line` are
load-bearing.

---

## §1. Mission / definition of done

Restore **hands-off, end-to-end autonomous bounty-PoC hunting**: source/brief → hunt → triage → PoC
synthesis → jail-confirmed, **claimable** PoC, with the factory self-healing its own stalls.
**Done = (a)** the NGv2 campaign runner produces a jail-`confirmed` **source-driven** PoC that passes
`poc_authenticity` AND `sink_presence` AND `sink_reachability` AND **`detonation_evidence`
(`ran_target` AND `observed_runtime_effect`)** — i.e. it actually starts the real target app and drives
the real route so the sink fires *from the request*, on a huntr-eligible repo; **(b)** the JanusMask
daemon runs unsupervised long enough to build such fixes test-first; **(c)** owner can submit with one
GO. **NEVER auto-submit a bounty.**

★ Scope note (scripted, Agent B): `sink_presence` (`sink_presence_gate.py`) and `sink_reachability`
(`sink_reachability_gate.py`) are **PURE STATIC** (string/AST scans of the target repo — no runtime,
no taint flow). The **only runtime gate is `detonation_evidence`.** An import-call skeleton passes the
two static gates trivially but produces no real runtime effect → dies at `detonation_evidence`.

---

## §2. Current verified state (LANDED, with SHAs)

**Factory / harness (JanusMaskEX, branch master, HEAD `0234872`):**
- Keystone planner oracle-drop guard — `fa0e188` + **`0fb322f`** (`plan_normalizer.py` red-pair KEEP
  guards, both PASSes). 490 `tests/planner/` green.
- Fix-forward red-pair **acceptance** predicate — `271c4ba` + `d0974bd` (NEW
  `harness/redpair_acceptance.py`, 14/14; wiring vcmd 17) + `0234872` (10-line wire into
  `_auto_commit_accepted`, byte-verified). ⚠️ **BUILT, NOT yet fired live — see §3.A.**
- F1 brief-vs-plan sha-staleness gate — `7181859`. `archive_spent_briefs` default ON — `0ca53fe`.
- Phase-0 backlog: selfheal parallel-isolation `ea6b9db`, deterministic-park `2692818`/`8c2fc73`,
  manifest path-norm `4332b78`, reject-empty-manifest `7b4ea6c`, validate-before-persist `b84f635`,
  meta-type coercion `994182a`/`fecba8b`, required-task-ids `c6b28e0`(+`9582415`).

**Hunt pipeline (NobleGreedv2, HEAD ~`49dcef8`) — structurally complete + HONEST e2e, source_meta
plumbing WORKS, BUT 0 confirmed:**
- `python -m ngv2.run_hunt`, `ngv2.campaign`, `ngv2.poc_writer` all import + run clean.
- Autonomous target selection WORKS: `ngv2/campaign.py` refreshes the huntr eligible cache
  (**151 repos**, refreshed 2026-06-17T05:55Z), ranks by payout, excludes hunted, rotates oversized.
- Gate chain correctly wired + fail-closed (`gate_executor.py:24`, `gated_advance.py:21`). Starved
  upstream, not broken — zero false positives across ~22 repos / 4 campaigns.
- ★ **source_meta plumbing is BUILT AND WORKS** (scripted, three agents): `hunt_lead_client.py:294-300`
  (CodeQL + pattern paths) and `codeql_lead_source.py:364-386` already set http `source_meta`;
  `poc_writer.py:566 _coerce_finding` + `:201 _overlay_source_meta` thread it to the Grounding. No drop.
- ★ **0 confirmed PoCs, empirically (Agents A/B/D):** every `state/campaign/db/*.sqlite` `reports`
  table is EMPTY (no run reached the verdict phase); `campaign_ledger.json` outcomes are
  `completed`/`error`/`blocked:poc_authenticity(...)`. **None `confirmed`.**

**Parked artifacts (NOTHING submitted; owner-gated) — re-audited live (Agent D):** every parked
"confirmed" PoC is a **Python re-implementation, not a real exploit** (vindicates BUILT≠WORKS):
- **modeldb (CWE-89) = IMPOSSIBLE** — `submission.md` "Package Manager: maven"; sink is
  `LineageDAORdbImpl.java`; the PoC reimplements Java primitives against an in-memory Python class. A
  Python source-driving pipeline can never drive it. **Drop it permanently.**
- **mlflow (CWE-918) = NOW INELIGIBLE** — was eligible 2026-06-13, **DROPPED from the 151-repo cache
  today.** Dead.
- **feast (CWE-89)** — transport is **Arrow-Flight gRPC** (not flask/fastapi → `is_source_driving`
  False on the framework gate) AND same-class SQLi already SPAM-marked on huntr. Drop.
- **InvokeAI (CWE-22) — re-audited, NOT the easy win rev.5 thought (scripted).** The parked
  `_autowork_scratch/R2b_pocs/C_out/invokeai_model_image_traversal/` is a **`self_contained_mock`**:
  it imports only stdlib and **reimplements the sink locally** (`base/(key+'.webp')`), never imports
  `invokeai`. Live `classify_poc_authenticity` → `mode=self_contained_mock, may_confirm=False`; the
  current 4-gate chain **BLOCKS it at `poc_authenticity`** (`run_gates('poc','detonate')` →
  `blocked_by:['poc_authenticity']`). Its `detonation_report.json verdict:confirmed` is **STALE** —
  produced by the old `semantic_verdict` (exit-code + fs-diff) path; it lacks every current gate key
  (no `sink_presence`/`sink_reachability`/`poc_authenticity`/`detonation_evidence`). The route IS real,
  but InvokeAI is a **POOR first target**: an honest PoC must import the real handler, which drags the
  full app graph (torch, `ApiDependencies`) → fails offline import in the `--unshare-net` jail (W3); the
  3-round dep budget can't build it. **`0 confirmed` holds.** Lowest-barrier target = §4/§5 (importable).

**Live-system state (verified 2026-06-17 — re-discover at exec time, do NOT hardcode PIDs):**
- NO daemon running (IDLE, not slow — `pgrep` empty). Restart only via `scripts/run-autowork.sh`.
- **`state/control/autowork/full_stop` EXISTS (hard stop) AND `pause` EXISTS.** Dispatch gate
  (`autowork_daemon.py:1793`) blocks on EITHER. The `pause` reason (06-16 18:25):
  *"daemon-wake-impl + mfapb-2 in doomed verification_failed retry loop (oracle test files never
  authored)"*. ✅ **Both doomed briefs EVICTED reversibly this session** (B0, scripted) → 15 untracked
  artifacts `mv`'d to `_autowork_archive/2026-06-17_b0_doomed_briefs/`; `state/` sweep now empty.
- ✅ **`auto_approve_count`/`runaway_ceiling` are INERT (scripted, B0) — earlier "54>50 gates dispatch"
  was WRONG (two unrelated counters):** `runaway_ceiling.json{50}` gates only self-heal escalation
  (`_runaway_counter_bump`); `auto_approve_count.json{54}` gates only sensitive-harness auto-approve
  (`orchestrator.py:2855-2877`, ceiling default 3) and that check is **skipped entirely under widened
  config** (`autowork.enabled=True ⇒ _widened=True`). Neither blocks dispatch; left as-is. `state.lock`
  = normal 0-byte fcntl advisory sentinel (no holder, no daemon) — NOT stale, leave it.
- Dead `git_commit.lock` already cleared this session. `.exhausted` sidecar backlog present. `mfapb-3`
  (separate slug, NOT one of the doomed pair) left in place for owner.
- ⚠️ Uncommitted working-tree: a large unrelated `README.md` edit (442+/421−) — owner: commit or revert.

---

## §3. The honest reckoning (5 adversary panels, all scripted)

### A. The catch-22 / red-pair fix is BUILT but has NEVER fired live
The 3 commits are mechanically clean. BUT `is_fix_forward_redpair` is empirically **False for all three
of its own tasks** — they landed via OLD paths; the new acceptance path has executed in **ZERO live
commits.** The wiring vcmd is non-discriminating (neutralize the insert → still `17 passed`). It fires
live the first time an existing-module fix-forward red-pair lands (H2). Closed by H3 (discriminating e2e).

### B. ★ THE REAL BLOCKER IS A DOWNSTREAM CLUSTER (source_meta is NOT it)
source_meta plumbing works and findings carry http source_meta (§2). `is_source_driving` returns True
**0 times** across every http finding for **four scripted reasons** — these, not plumbing, are the walls:

- **W1 — Source/sink CWE co-location (Agents A+B).** `is_source_driving` (`poc_writer.py:315-327`)
  has a **4th requirement rev. 4 omitted: the CWE must resolve into `payload_bank.supported_cwes()`**
  = `{22, 78, 89, 94, 95, 502, 918, 1336}`. The http-localized findings carry **non-injectable CWEs**
  — litellm's 4 http+fastapi findings are all **CWE-798** (hardcoded creds, correctly excluded — no
  drivable taint); campaign/out http findings are **CWE-79/1333/209/312/215**. The injectable-CWE
  sinks (22/78/89/94/918/502) exist in those repos but carry **no http source_meta** — the http-source
  code and the injectable-sink code are **disjoint nodes.** Closing W1 needs source→sink taint
  *correlation*, not the current independent localization.
- **W2 — Unmountable `app_object` (Agents B+D; mechanism CORRECTED by scripted repro).** `source_localize`
  captures the *local* decorated object, often a **sub-router** (`APIRouter`: litellm `app_object='router'`,
  InvokeAI `'model_manager_router'`). `_app_bootstrap_py` (`poc_writer.py:330-337`) emits `app = <router>`
  then `TestClient(app)`. ★ CORRECTION: `TestClient(router)` does NOT reject at construction (an
  `APIRouter` IS a valid ASGI callable); it crashes DEEPER at handler dispatch —
  `AssertionError: fastapi_middleware_astack not found` (the bare router lacks FastAPI's `AsyncExitStack`
  middleware). Mount fix `app=FastAPI(); app.include_router(router)` clears THAT but exposes **W2b**
  (path-param: `render_source_driving_py` puts `param_name` in `params=`/query, never substitutes a path
  param `{key}` → sink gets the literal `{key}`) and **W2c** (Starlette 404s on `%2F`-encoded path params
  → can't deliver raw-slash traversal). Plus a **faithfulness risk**: a bare-mounted router drops the real
  prefix/auth `Depends`/app state. So the mount fix is CORRECT but INSUFFICIENT — a GENERIC source-driving
  improvement, not the cheapest first-PoC route.
- **W3 — Offline in-jail importability (Agent B) — THIS is what actually killed tsfresh, not
  `sink_reachability` as rev. 4 claimed.** `state/campaign/out/campaign-blue-yonder-tsfresh/
  detonate_report.json`: `ModuleNotFoundError: No module named 'pywt'`, `ran_target:true,
  observed_runtime_effect:false, verdict:error`. The dep installer (`poc_runner_live.py:272,327,373`)
  caps at `MAX_DEP_INSTALL_ROUNDS=3`, is stderr-driven, and pip runs outside the `--unshare-net` jail.
  Real ML repos with deep/native deps exhaust the budget → import fails → `detonation_evidence` fails
  **even with a perfect PoC.** A hard wall rev. 4 omitted entirely.
- **W4 — Template/payload coverage for the CWEs that DO arrive (Agent A).** A partial re-vindication of
  P1: the http findings' CWEs (esp. CWE-79 XSS) aren't in `payload_bank`/`_TEMPLATE_LIST`. But W4 only
  matters for CWEs that are ALSO source-drivable (have a request-reachable taint path) — so it is
  downstream of W1, not independent.

★ **WALL ORDERING + the key reframe (5th panel follow-up, scripted):** **W3 is the FIRST and
UNAVOIDABLE wall** — to get `observed_runtime_effect` you must run the REAL target's vulnerable code in
the `--unshare-net` jail, and that requires it to IMPORT offline (survive the 3-round dep budget). W3
gates *every* honest PoC, including a plain **direct-import** PoC (no HTTP) — proven on InvokeAI
(`invokeai` not installed; importing the handler drags torch/app-graph) and tsfresh (`pywt`). W1/W2/W2b/
W2c are the *additional* walls only for the HTTP **source-driving** shape. **The cheap-vs-expensive
distinction the prior panels muddled:** an import-call PoC that imports the **REAL target** and drives
the **real sink** is `mode=real_target, may_confirm=True` and CAN clear all 4 gates — it dies only when
(a) the PoC is a **mock** that reimplements the sink (InvokeAI parked = `self_contained_mock`,
gate-blocked) or (b) the target won't import offline (W3). So **the most-efficient first `confirmed` is a
real-import PoC against a target that imports cleanly offline in the jail with a statically-reachable
injectable sink** — sidestepping W1/W2/W2b/W2c entirely. Source-driving (HTTP) is a *faithfulness
upgrade* for later / for CWEs where a direct call isn't a convincing demo, NOT the gate-passing minimum.
⚠️ This is a HYPOTHESIS to TEST empirically (target corpus probe + one real build), NOT a 6th declared
thesis — verify before committing (see §5 S0').

- **W5 — Grounding gap: class-method sinks never render a PoC (NEW, scripted S0' probe).**
  `poc_writer.py:default_resolver` (~142-199) scans ONLY module-level `tree.body` functions, so a sink
  that is a **class method** (e.g. bananaml `API.__call`, `Client.call`) grounds to `functions=[]
  symbols=[]` → `write_poc` raises `ValueError: no vulnerable module/symbols` BEFORE any template
  renders. Class-method sinks are extremely common, so this silently kills a broad slice of findings
  upstream of W1/W2/W3. Fix = resolve `ast.ClassDef` method sinks (permanent, reusable harness change);
  ⚠️ may also need instance-construction grounding (a method call needs an instance) — under verification.
- **W3 concrete base-env (scripted):** the jail base env has `numpy/pandas/scipy/requests/yaml/pickle`
  but NOT `stumpy/statsmodels/gradio/loguru`. ★ Also scripted: `_py_ssrf` confirms CWE-918 on
  **request-ATTEMPT via FS-sentinel** (no loopback roundtrip) → **CWE-918 is confirmable with NO
  LoopbackListener** (re-confirms §3.D / #36).
- **★ W3 is CHEAP, not a hard wall (STEP 0, scripted — corrects the probe).** The dep installer runs as a
  plain **host `subprocess` with FULL NETWORK, OUTSIDE** the `--unshare-net` sandbox
  (`poc_runner_live.py:373-384`; only `_run_once`/`build_detonation_jail_argv:82` is net-unshared). The
  install loop (`:268-293`) re-runs jailed after each host pip install; the only cap is
  `MAX_DEP_INSTALL_ROUNDS=3`. So **importability is largely a solved/cheap problem** — this **REVIVES
  gpt_academic + tsfresh**, which the corpus probe wrongly killed on a "no-network" premise. ★ Real
  sub-bug: the installer keys off the `ModuleNotFoundError` *import name*, which ≠ the pip package name
  (tsfresh `pywt` → pip `PyWavelets` FAILS; needs an import→dist name map). Also: a dep that net-fetches
  at import time (bokeh `sampledata`) fails *inside* the jail. **Net: W3 is no longer the blocker; the
  blocker is TARGET FAITHFULNESS + DISCOVERY.**

### C. P1 is generation-only; H2 design is safe but the GENERATED PLAN deadlocks
- **P1 (CWE templates)** only flips `poc_authenticity` (the weakest gate, checks `imports_target`
  only). It produces import-call skeletons that still die at `detonation_evidence`. NOT the money path.
- **H2 (sanitizer red-pair guard) — the §3.C clean route DESIGN is SAFE and builds hands-off
  (Agent C, scripted):** no trust-core (`redpair_acceptance.py` + `plan_normalizer.py` are NOT in
  `_NEVER_AUTO_APPROVE`, `orchestrator.py:2282`), auto-approve ON (`config.yaml:53`) → no decision
  file, and the **sanitizer-immune shape is REAL** — an impl vcmd naming a non-oracle regression pytest
  survives `_sanitize_impl_verification_commands` (`plan_normalizer.py:234,239`) intact (scripted).
- **★ BLOCKER (Agent C): the freshly-generated `_autowork_scratch/h2_drive/h2_plan.json` is NOT the
  clean route — it WILL DEADLOCK.** The brief was never re-authored, so the planner faithfully produced
  the OLD new-module shape (`harness/redpair_vcmd_guard.py`). Scripted: at the impl leaf's acceptance
  the importer is absent → `wired=False` → `orphan_unwired` rollback (`orchestrator.py:2082-2091`); the
  separate wireup leaf that would satisfy the gate depends on the impl that never lands → **permanent
  deadlock. DO NOT DISPATCH `h2_plan.json`.** Fix = re-author the brief to add `references_sibling_oracle`
  as a **FUNCTION inside the already-wired `harness/redpair_acceptance.py`** (tracked at HEAD →
  `_tracked_in_parent` True → orphan gate SKIPPED, `orchestrator.py:2079`), mutation_target
  `harness.redpair_acceptance`, RED via the absent *function* (`ImportError: cannot import name
  'references_sibling_oracle'`), impl vcmd = the sanitizer-immune own-test pytest; then regenerate.

### D. #36 (LoopbackListener) is a RED HERRING — drop it from the critical path (Agent B)
The source-driving template already emits an **in-process test client** (`poc_writer.py:349-353`:
`app.test_client()` / `TestClient(app)`) — no socket, no listener. `LoopbackListener` has **zero
non-test importers** and is an **SSRF out-of-band callback receiver**, relevant only to a narrow
CWE-918-via-loopback variant — NOT a prerequisite for HTTP source-driving. rev. 4's "LoopbackListener
UNWIRED = S3 prerequisite / Leaf 5 substance" was wrong.

---

## §4. IMMEDIATE value / what to do now

- **S0' — corpus probe ✅ DONE → there is NO free first PoC (see §5 OWNER DECISION).** The cheapest
  real-import targets are all unclaimable (bananaml FP, dill known-issue); the only faithful findings are
  HTTP-sourced + heavy-import (bokeh, gpt_academic). The next decisive move is **STEP 0**: size the W3
  wall on `bokeh` (does its vulnerable module import offline in the jail? does the dep installer have
  network?) — cheap, and it determines the cost of the recommended source-driving path (Path 1).
- **I1 — Keep hunting (background, daemon-free, READ-ONLY, never-submits):** `cd ~/NobleGreedv2 &&
  python -m ngv2.campaign --targets 6`. Diagnostic now (which gate / CWE / **does the target import
  offline**), not PoC production.
- **I0 — parked PoCs NOT claimable (re-confirmed scripted; reverses rev.5's InvokeAI exception).** The
  InvokeAI parked artifact is a `self_contained_mock` the live gate BLOCKS (`may_confirm=False`); its
  `confirmed` is a stale `semantic_verdict`. modeldb (Java) / mlflow (now ineligible) / feast (gRPC +
  SPAM) stay dropped. There is **no shortcut via a parked artifact** — the first claimable PoC must come
  from a real-import build (S0'). Any submission gated on live dup-check + non-$0 + owner GO + NEVER
  auto-submit.

---

## §5. Ordered remaining work

### ★ CRITICAL PATH TO THE FIRST CLAIMABLE PoC = real-import PoC against an offline-importable target
- **B0 — Clear the resume blockers. ✅ DONE this session (scripted):** evicted the 2 doomed briefs
  (`daemon-wake-impl`, `mfapb-2`) reversibly to `_autowork_archive/2026-06-17_b0_doomed_briefs/`.
  `auto_approve_count`/`runaway_ceiling` confirmed INERT (§2); `state.lock` normal. (Daemon paused;
  full_stop/pause removal is H5, LAST.)
- **S0' — Corpus probe ✅ DONE (scripted).** Result: NO on-disk corpus candidate ships as-is. Only 3
  eligible templated-CWE Python-sink candidates exist, each blocked: **bananaml** (CWE-918, LOW
  import-weight, imports clean) → **W5 grounding gap** (class-method sink); **tsfresh** + **gpt_academic**
  (CWE-22) render real-import PoCs but die at **W3** (missing stumpy/statsmodels/gradio/loguru offline).
  ★ CLAIMABILITY VERDICT (scripted): both "cheap" paths are DEAD. **(P-a) bananaml REJECTED** — its
  SSRF is a `pattern_scanner_fallback` FALSE POSITIVE (`base_url` hardcoded constant; `client.py` URL is
  caller-supplied = "the SDK makes the request its user asked for"), no external attacker source; AND the
  W5 fix is insufficient (bound-call/instance/mangling wall). **(P-b) dill CWE-502 REJECTED** —
  pickle-semantics unsafe-by-DESIGN = known/wontfix (feast pattern); mature pure-Python libs likely
  known/FP too. ★ **THE HONEST SYNTHESIS:** the corpus has NO target that is simultaneously *faithful*
  (externally-triggerable), *offline-importable* (light deps), AND *templated*. The light targets are
  FPs/known-issues; the only FAITHFUL findings carry an HTTP source (`gpt_academic` `/upload` fastapi
  CWE-1333/209; `bokeh` flask CWE-79/215) and those targets are heavy-import (W3). **So FAITHFULNESS
  forces the source-driving path** — not because plumbing is broken (it works), but because only
  HTTP-sourced findings are claimable, and they need W2 (mount) + W3 (offline dep-staging). The
  "direct-import is cheaper" reframe was mechanically true but every cheap target is unclaimable.
- **S1' — Real-import PoC on the chosen target = the first `confirmed`.** Drive it through the real
  campaign; assert poc_writer emits `mode=real_target` (imports the REAL sink, NOT a mock) and the PoC
  clears ALL 4 gates (`poc_authenticity` AND `sink_presence` AND `sink_reachability` AND
  `detonation_evidence`: `ran_target AND observed_runtime_effect`). **PROVABLE on this box**
  (`bwrap --unshare-net`; no TestClient/LoopbackListener needed). The empirical TEST of the §3.B reframe.
  ⚠️ A gate-`confirmed` PoC must ALSO be a FAITHFUL externally-triggerable vuln before it counts as
  claimable (don't conflate confirmed-gate with claimable — the InvokeAI mock + bananaml caller-URL are
  the cautionary cases).
- **S2' — If W3 (offline import) is what blocks the top target, fix the dep budget.** Raise/parameterize
  `MAX_DEP_INSTALL_ROUNDS` (`poc_runner_live.py:272`) or pre-stage the resolved dep set outside the jail
  before the run; verify against `detonate_report.json`. Build as an external NGv2 pipeline brief
  (sanitizer-immune shape, no H2).
- **S3' — HTTP source-driving (LATER, faithfulness upgrade, NOT first-PoC).** Only for CWEs/targets where
  a direct-import call isn't a convincing demo. Needs W1 (taint co-location) + W2 (mount, incl. W2b
  path-param + W2c `%2F`) — all GENERIC source-driving improvements. Defer until the first `confirmed`
  lands via S1'.
- **S4 — Breadth.** Rank importable + reachable findings across the cache by payout; produce N
  real-import confirmed PoCs; owner GO per-target. NEVER auto-submit.

### SECONDARY — generation coverage (W4; only for surfaced source-drivable untemplated CWEs)
- **P1 — Expand poc_writer CWE templates** (`_TEMPLATE_LIST` `poc_writer.py:377` + `payload_bank`).
  Only invest for CWEs that are ALSO source-drivable (in `payload_bank.supported_cwes()` +
  `SOURCE_DRIVING_FRAMEWORKS`) and that actually co-locate with http source (W1) — otherwise templates
  yield import-call skeletons that die at `detonation_evidence`. Brief
  `brief_hooks_poc_writer_cwe_expansion_v2.md` (CWE-20, authored, RED-on-HEAD verified) is a valid
  red-pair; build via the sanitizer-immune shape (no H2) or after H2. **Parallel-safe with the S-path**
  (P1 touches `ngv2/poc_writer.py`, S1 touches `ngv2/hunt_lead_client.py` — distinct files, Agent D).
  NOT the money gate.

### FACTORY HARDENING — enables building S/P fixes test-first, hands-off
- **H2 — Planner `_sanitize_impl_verification_commands` red-pair guard.** Defect `plan_normalizer.py:277`
  rewrites an impl vcmd referencing a sibling oracle's file to vacuous `python -c "import X"`. Fix via
  §3.C clean route: helper `references_sibling_oracle(vcmd, oracle_files)` ADDED to the **already-wired
  `harness/redpair_acceptance.py`** (no orphan), oracle `tests/harness/test_redpair_sanitize_guard.py`,
  wireup edits `plan_normalizer.py`, impl vcmd = sanitizer-immune own-test pytest. ★ **RE-AUTHOR
  `brief_hooks_redpair_vcmd_sanitize_guard.md` (still targets a NEW module) BEFORE regenerating — the
  current `h2_plan.json` deadlocks (§3.C).** Landing H2 fires `is_fix_forward_redpair` live (closes §3.A).
- **H3 — Discriminating e2e test for the fix-forward branch** (closes §3.A gap): red-before→accepted;
  vacuous-oracle→rejected; adopted as the wiring's true vcmd.
- **H4 — mfapb multi-file additive bundle** — restructure into TWO 1:1 red-pairs; needs H2/immune shape;
  removes new-module orphan friction permanently.
- **H1 — `single_agent_promotion_ceiling: 1`** (`harness/config.yaml:121`, default 3). Flip via a
  `harness_self_fix` pipeline brief with a RED oracle asserting loaded value == 1 (sensitive glob, but
  NOT trust-core → no decision file; MUST go through the pipeline). Cheap, independent.
- **H5 — Daemon de-wedge + hands-off restart (LAST, only for unsupervised operation):** reap self-heal +
  orphan gemini; `kill -TERM` the CHILD only (supervisor `scripts/run-autowork.sh` respawns — NEVER
  nohup a 2nd daemon, NEVER kill the supervisor); clear sidecars/stale specs/locks; re-establish
  self-heal suppression (`inactivity_escalated.json` is gone → respawns); then land trust-core daemon
  items **C**/**B**/**R1** (each needs a decision file + restart); **unpause LAST** (remove BOTH `pause`
  AND `full_stop`).

### ★★ OWNER DECISION — engine is MORE capable than feared; the blocker is TARGET FAITHFULNESS/DISCOVERY.
STEP 0 changed the picture: **W3 (importability) is CHEAP** (host pip, full network) — so the engine
(source_meta ✓, gates ✓, templates render `real_target` ✓, deps install ✓) can produce a confirmed PoC.
What's missing is a target that is **faithful + shipped-code + templated** simultaneously. The dead ends:
InvokeAI (stale mock), bananaml (caller-URL FP), dill (known-by-design), bokeh (findings are in
`examples/` demo code, no attacker input). **Best surviving on-disk candidate = `gpt_academic` CWE-22
tar-slip (`extract_archive`) via the fastapi `/upload` route** — shipped APP code, http source with a real
`param`, CWE-22 is TEMPLATED, and its deps (gradio/loguru) are now known network-installable. The probe
wrongly killed it on the no-network premise. The choice:

- **PATH A (RECOMMENDED) — empirically attempt `gpt_academic` CWE-22 through the real pipeline.** It is
  the only on-disk candidate that survives the faithfulness filter (shipped code + http + param +
  templated) AND is now importable. This is a TEST (run it, see if it reaches `confirmed`), not more
  analysis. First confirm faithfulness (is `extract_archive` reachable from `/upload` with an
  attacker-supplied archive in *shipped* code, not an example?), then drive it: scoped campaign or
  single-shot detonate. May need the import→pip name map (W3 sub-bug) and possibly W2 only if a real
  direct-import call of the sink isn't a convincing demo.
- **PATH B — broaden the autonomous hunt with the PRECISE filter:** `source_meta.kind=='http'` AND sink
  NOT under `examples/`/`tests/`/`release/` AND `param_name != ''` AND CWE ∈ templated set. The on-disk
  5-campaign corpus is thin; more eligible repos likely surface a cleaner faithful target. Run as a
  parallel side-bet (`ngv2.campaign --targets N`, never-submit) — de-risked now that W3 is cheap.
- **PATH C — W5 bound-call grounding** (class-method sinks): real engine capability, but defer until a
  faithful class-method target appears (NOT bananaml).

**Recommended sequence:** Path A (gpt_academic CWE-22) as the first real shot ‖ Path B as a parallel
discovery hunt ‖ H1 (3→1) cheap factory fix. Breadth (S4) + factory hardening (H2 re-authored §3.C →
H3 ‖ H4 → H5 restart → unpause) AFTER the first `confirmed`. Submission ALWAYS owner-GO + live dup-check,
NEVER auto-submit.

Rationale: the money is a real detonation on a FAITHFUL shipped-code finding. The engine can do it (W3
cheap, plumbing works, templates real_target); the gap is finding/confirming a target that survives a
triager. gpt_academic CWE-22 is the cheapest real shot; a broadened filtered hunt is the discovery
backstop. No more reframes — the next move is to RUN.

★★ EXECUTION RESULT (Path A + B ran, scripted) — the gap is DISCOVERY/TRIAGE QUALITY, not the engine:
- **Path A: gpt_academic CWE-22 = CodeQL FALSE POSITIVE.** The tar-slip is already mitigated in shipped
  code (per-member canonical-prefix containment guard + symlink rejection before `extractall`,
  `handle_upload.py:136-142`; zip/rar branches guarded too). Agent stopped at faithfulness, 0 detonation
  cycles. (Also: finding `source_meta.kind=file`, not http.) **Still 0 confirmed.**
- **Path B: 0/74 on-disk findings pass the faithfulness filter; the corpus is MIS-ORDERED, not
  picked-over.** The campaign hunts the eligible cache in cache order → AWS SDK libraries (no HTTP
  surface) before web-apps. Background `campaign_run1` (log `/tmp/hunt_logs/campaign_run1.log`) is alive,
  grinding toward web apps (comfyui ~pos 5). **Recommended next target: `eosphoros-ai/db-gpt` (RCE
  CWE-94/95, web app, eligible, templated)**; runners-up comfyui (CWE-22/78), chuanhuchatgpt.
- **The three TRIAGE-QUALITY fixes that make autonomous faithful-PoC yield real (the actual mission):**
  (i) **#53 web-app/route-density pre-rank** in the target selector (hunt route-bearing repos first);
  (ii) **#52 FP-screen** for guarded/mitigated sinks (cull CodeQL FPs like gpt_academic before detonation);
  (iii) the **`kind=unknown` source_meta gap** (60/74 findings carry no usable source meta). These — not a
  single manual PoC — are what convert the working engine into a hands-off money machine.

---

## §6. Operational runbook

**Single-shot build (daemon paused — default for S/P/H work):**
1. Plan: `python -m harness.planner.cli <brief> --output-plan <plan.json> --output-critique <crit.json>`
   (SLOW = child alive + log advancing; STUCK = child gone / no plan).
2. Verify: `validate_plan(<plan.json>)` == 0 violations; task_ids/deps/files_touched/vcmds match the
   brief's required shape (planner may reorder deps / drop the "integration" non_goal — F5). **For H2,
   confirm the impl leaf edits `redpair_acceptance.py` (NOT a new module) and its vcmd is the own-test
   pytest — else it will deadlock `orphan_unwired` (§3.C).**
3. Stage: `from harness.planner.staging import stage_task; stage_task(Path(plan), tid, Path('state'),
   canonical=True, working_dir=<wd>)` per leaf, in dependency order.
4. Drive: `python -m harness.orchestrator_worker --state-dir state --task-id <tid> --config
   harness/config.yaml`. Verify each commit (diff + scoped vcmd) before the next. External NGv2 edits:
   wire_up gate no-ops (rootless); immune shape keeps the impl vcmd real.
5. Pre-clean: dead `git_commit.lock`; `blocked/*.retry.json` + `.exhausted` sidecars (the 2 doomed
   briefs daemon-wake-impl/mfapb-2 are already evicted, §5 B0); `state/output/*.py`/`.patches.json`/
   `.files.json` sidecars; stale staged specs; in-flight planning files. (auto_approve_count/
   runaway_ceiling are inert — no reset needed, §2.)

**Daemon restart (H5, LAST):** reap self-heal + orphan gemini; `kill -TERM` the CHILD only; re-establish
self-heal suppression; allowlist the slugs; **unpause LAST** by removing BOTH
`state/control/autowork/pause` AND `state/control/autowork/full_stop` (the dispatch gate
`autowork_daemon.py:1793` checks those existence-flags, NOT config `pause_flag_path`).

---

## §7. Known gaps / follow-ups

- **R8 — pause/config split (latent):** `config.yaml:78 pause_flag_path: state/control/orchestrator.flag`
  vs dispatch gate's hardcoded `state/control/autowork/pause` (`autowork_daemon.py:1793`). Unify (R1).
- **F-series:** F2 submission-integrity patches-branch cheat vector; F3 post-run cleanup; F4 backend
  preflight; F5 decompose-vcmd-override (planner reorders deps / drops per-leaf vcmd; it produced the
  deadlocking `h2_plan.json` this session; `436df86` only covers single-task briefs).
- **Anchor-patch (#20)** — sentinel-free line/anchor patch for >150L symbols. Owner-approved, unbuilt.
- **CLAIMABILITY RISKS (gate every submission):** (1) cache eligibility ≠ novelty — per-finding huntr +
  GHSA/CVE/NVD dup search; (2) parked PoCs are docs/sims (modeldb Java = impossible; mlflow now
  ineligible; feast = gRPC + SPAM; InvokeAI = needs real source-driven build); (3) confirm a real
  (non-$0) payout first; (4) NEVER auto-submit (owner GO per-target).
- **CAMPAIGN-FRICTION:** 500MB clone cap (`cloner.py`) errors oversized repos (azure) → `--targets ≥6`.
- **`EPIC_source_driving_poc_synthesis.md`** — canonical S-path design. ★ The 8 leaves should be
  reconciled against the **corrected** wall list (W1 co-location, W2 sub-router mount, W3 offline deps),
  NOT against the refuted "source_meta plumbing" gap.
- **Provenance-injection** (PROVENANCE_REVIEW_04): LOW priority. Do NOT revive.

---

## §8. Document hygiene + this-session work

- **This oversight session (2026-06-17):** ran a 5th 4-agent forensic panel (all scripted, three
  independent datasets) that **reversed the rev. 4 money thesis** — source_meta plumbing WORKS (7/74,
  13/408, InvokeAI route all confirmed); the real blocker is the downstream cluster W1–W3 (+W4); #36 is
  a red herring; the generated `h2_plan.json` deadlocks and the H2 brief needs re-authoring; tsfresh
  died on offline deps, not sink_reachability; the static-vs-runtime gate roles were clarified;
  InvokeAI re-promoted as the lowest-barrier first target. Cleared the dead `git_commit.lock`. Daemon
  left IDLE-PAUSED (pause + full_stop present).
- **Spent briefs archived** `_autowork_archive/2026-06-17_plan_consolidation/`:
  redpair predicate/impl/wiring (`271c4ba`/`d0974bd`/`0234872`); planner oracle-drop guard (`0fb322f`).
- **Frozen supporting evidence:** `INTERVENTION_ANALYSIS_01–04`, `AUTONOMY_GAPS.md`,
  `PROVENANCE_REVIEW_01–04`, `EPIC_source_driving_poc_synthesis.md`.
- **Open owner items:** unrelated uncommitted `README.md` edit (commit or revert); whether to commit
  this plan + briefs (working-tree only, owner-gated); the H2 brief re-author per §3.C (do before any
  H2 dispatch — the existing `h2_plan.json` must be discarded).
