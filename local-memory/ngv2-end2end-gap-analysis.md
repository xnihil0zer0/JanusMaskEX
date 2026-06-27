---
name: ngv2-end2end-gap-analysis
description: "2026-06-19 4-agent study of the NobleGreedv2 end-to-end bug hunt: the ONE gap is no live-environment stand-up + a self-graded detonation oracle; all 8 'confirmed' PoCs are mocks. Full report + closure roadmap at AI-Data/Research-JanusMask/NobleGreedv2-end2end-gap-analysis.md"
metadata: 
  node_type: memory
  type: project
  originSessionId: ab1a855a-f5fb-4dc6-bfee-325a57df1427
---

🎯 **NGv2 END-TO-END BUG-HUNT GAP ANALYSIS (4 parallel agents, 2026-06-19).** Master report:
`/home/xnihil0zer0/AI-Data/Research-JanusMask/NobleGreedv2-end2end-gap-analysis.md` (+ 4 sub-reports
`ngv2-gap-report-0{1,2,3,4}-*.md`).

**THE finding (unanimous):** nothing ever stands up a target's real runtime, so confirmation is
self-graded. ★CORRECTED by the 2026-06-19 waves-3+4 re-audit (8 agents, scripts under
`AI-Data/Research-JanusMask/_adversarial_audit{3,4}/`): there are **12 `verdict=confirmed` reports → 11
distinct findings**, of which **exactly ONE is faithful (≈1, not 0)** — the **gptcache cmd-injection
(CWE-78)** PoC, EXECUTION-proven to `spec_from_file_location`-load the REAL cloned
`gptcache/utils/dependency_control.py` and run its real `prompt_install()`→`subprocess(shell=True)`. The
other ~10 are self-contained MOCKS; **h2ogpt is a separate non-confirmed source-assertion (not one of the
12).** The env-setup thesis SURVIVES: the lone faithful case fires via a **direct internal-function call**
(runs on `sys.modules` stubs, no venv/service/auth) and is parked `CONFIRMED_NON_CLAIMABLE` (all real callers
pass literals) — it proves the engine can hit a plain importable sink, NOT stand up an externally-reachable
live target. Reconciles with "BUILT≠WORKS" [[dont-conflate-built-with-works]]. Also corrected: the
`classify_poc_authenticity` gate is **near-vacuous** (a bare attribute ref to a target name flips a mock to
`may_confirm=True`; `network_live` mode confirms a non-localhost PoC with NO target import; no downstream live
check catches it — source-meta/nonce-listener checks are SPEC, unwired).

**Architecture reconciliation (resolves the stale source_meta confusion):** the hunt/detonation engine
lives in **NobleGreedv2's `ngv2/` package** (+ a staging copy in JanusMask `_autowork_scratch/ngv2_fsm/`,
`_c3_pending/`). JanusMask production `harness/` has **NO** detonate path — it only build/edits + verifies
external repos (stage→oracle→RO-parent→ff-merge). So: author the fix as JM briefs → factory builds+verifies
→ integrate into `ngv2/`. `is_source_driving`/`source_meta` are in NGv2 (now wired into the default agy
hunt), absent from JM harness — see [[source-driving-doesnt-fire-on-live-findings]] (corrected).

**The fix = a deterministic, fail-closed Environment-Readiness + Detonation-Trust FSM** (honors
LLM-propose/verifier-decide): DETECT→PROVISION→JAIL-BUILD→HEALTH-PROBE→REACHABILITY-PROBE→
BASELINE-CAPTURE→DETONATE→DIFFERENTIAL-CONFIRM→TEARDOWN, every transition a pure gate over hashed
evidence, typed terminals. Trust = per-CWE proof channel + unforgeable per-run nonce + differential
(effect present post ∧ absent in benign baseline) + reproduced. Wire dead `LoopbackListener` (SSRF) +
`auth_bootstrap` (the two-actor IDOR/BOLA replay = highest finding-ROI, the class all 8 mocks faked).

**Roadmap (sequenced briefs):** W0 cheap holes — route the **3** un-jailed diff-fuzz Popen sites
(sandbox.py:892/:1077/:1281) through `agent_jail.build_jail_argv(bind_credentials=False)` (G7, see
[[fuzz-sandbox-reads-host-files]]); lockfile-only network-restricted dep install (G8: host-net unjailed pip
in target_bootstrap._ensure_venv:162-184). W1 trustworthy confirm (gate every transition + differential +
positive target-provenance check → retro-un-confirms the mocks). W2 the env-FSM. W3 authz template +
first-class JS/TS. ★Effort warning (re-confirmed): **3 of 9 FSM states are NET-NEW** (PROVISION,
HEALTH-PROBE service-start = the long pole, parts of REACHABILITY); only JAIL-BUILD is clean reuse.

**Language coverage:** YES it helps. JS/TS FIRST (38% of corpus = 13/34 unhuntable). ★CORRECTED:
`autocompiler.js` is **already ON** (`config/autocompiler.yaml:21` js:true; `ac_enabled('js')==True`) —
"flip the flag" is a NO-OP; the real blockers are un-populated `js_inputs`, the Python-AST gate, and
(NGv2-side) unwired **npm dependency staging** (`poc_runner_live._default_pip_installer` is pip-only). Needs
language-keyed validity gate + JS input gen + JS oracle runner. New langs by ROI: Java→Go→(PHP vs Ruby).
Sequence env-FSM BEFORE language expansion (G1 is language-orthogonal).

**OSS stack [from report 03]:** SWE-bench/RepoLaunch agentic env construction; time-machine pip/npm proxy
(versions ≤ commit ts) = highest-ROI reproducibility; bwrap+mount-ns default isolation, Firecracker
snapshot for untrusted RCE/outbound-net startup; readiness = pre-attack probe of the exact vuln route, never
a bare port; PoC proof = Metasploit `Vulnerable`-tier never `Appears` + OAST nonce + ≥2 signals. "Built ≠
runnable" — gate every provisioning tier on a real run.
