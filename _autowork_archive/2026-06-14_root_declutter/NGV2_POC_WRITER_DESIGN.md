# NGv2 Agentic PoC Writer — Design + Port/Build Plan

Authored 2026-06-07 (handoff §9 deliverable; P4 synthesis of research agents P1–P3
plus first-party verification of the NGv2 PoC seams). **Research/design only — no
implementation, no live detonation.**

## 0. Thesis
The legacy PoC writer is *lazy*: `ng-poc-writer` (and NGv2's `js_poc_templates`,
which emits inert CWE-keyed scaffolding strings) stops at a draft and never proves
the exploit. The fix ≈ **port JM's synthesis-worker + Stop-hook architecture, swap
the "compile a module / pass the oracle / commit a patch" gate for "detonate the PoC
/ reproduce the finding," and inject the vuln report as the contract.** Every needed
piece already exists on both sides:

- **JM side** = the synthesis worker: blind **drafter A** → **reconciler B** →
  `ast_retry.synthesize_with_retries` (append-violations-and-retry) → gates → the
  `verification_command` oracle → accept. The **anti-laziness lever** is the Stop hook
  `harness/hooks/claude/stop.py` `_decide()`, which **denies the agent's "stop" until
  acceptance is met** (`stop_hook_active` bounds the loop). Feedback flows via
  `cross_examiner.write_feedback_files`.
- **NGv2 side** = the PoC oracle seam: `detonation.DetonationChamber.detonate(poc,
  target_spec, runner) -> LiveTestReport` treats the exploit as data over an
  **injected runner** (`poc_runner.make_scripted_runner` / `make_mock_runner`), and a
  reproduced verdict + `submission_readiness.check_submission_pkg` + `report`/CWE match
  form the natural acceptance contract.

## 1. The two-agent loop (mirrors JM draft→reconcile→retry)
- **Drafter A** — input: the finding + target spec + a relevant **golden-PoC exemplar**
  (from the harvested `data/ngv2/poc_submissions/`) + the matching **taint spec** (from
  `data/ngv2/taint_specs/`). Writes/edits the PoC (file + entrypoint) to the inbox.
- **Reconciler / adversary B** — critiques against the legacy verifier/adversary
  checklist (P3): *does this actually reach the sink? reproduce the crash? match the
  reported CWE and the report? is the payload harmless (id/whoami, not destructive)?*
  Proposes the concrete fix. Mirrors JM's reconcile pass; B's critique is appended as
  the next-round prompt (the `ast_retry` violations channel).
- The loop is bounded by a retry budget (the `ast_retry` wall-budget guard) AND the
  Stop-hook deny-counter (below).

## 2. The PoC acceptance oracle (anti-laziness Stop hook)
The Stop hook **denies stop** until ALL hold (generalized from JM's "symbols defined"
to "PoC reproduces", the Epic-4 §6 Stop-hook shape):
1. `DetonationChamber.detonate(poc, target_spec, runner)` returns
   `verdict == 'confirmed'` — i.e. `exit_code == 0` **and** the `success_marker`
   (default `'VULNERABLE'`) appears in stdout (verified contract, `detonation.py`).
2. `submission_readiness.check_submission_pkg(finding, resolver)` →
   `ArtifactCheck.exists` (PoC + live-test + package artifacts present).
3. The PoC's CWE/target **match the finding** (`finding.category` vs the PoC's
   declared CWE; `report`/`huntr_form` consistency).

Bounded by a deny-counter so it never loops forever (`stop_hook_active` escape hatch,
copied from `stop.py`). **Inbox/outbox contract:** the drafter must write the PoC file
+ a small evidence record (the detonation stdout/verdict) to the outbox; the gate reads
those. **Feedback channel:** port `cross_examiner.write_feedback_files` (rename the
session-namer + drop `JANUSMASK_TASK_ID`).

## 3. Contract injection (the analog of `_inject_oracle_sources`)
Just as JM's `plan_normalizer._inject_oracle_sources` embeds the committed oracle into
the blind worker's brief, the drafter's brief is injected with: the vuln
finding/report + target spec + the **closest golden-PoC exemplar** + the **taint spec**
for the CWE. All four are now harvested metadata (§3/§5 of the harvest), so injection
is a local file read — no network. This is what makes a blind drafter productive
instead of lazy: it sees a worked example and the exact sink contract.

## 4. Isolation / safety boundary (keep live detonation off by default)
Detonation is *live and dangerous*; honor the deferred-live-I/O posture. The loop runs
with `make_scripted_runner` / `make_mock_runner` **by default** (development + all
research/tests). A **real bwrap runner** (ported `agent_jail.build_jail_argv` +
`dbus_proxy`) sits behind an explicit, owner-gated flag. The real-vs-mock seam is
exactly `handlers['runner']` in `pipeline.run_pipeline` / the `runner` arg to
`DetonationChamber.detonate` — research/build NEVER swaps it for a real runner.

## 5. Where it lives
A new NGv2 **live-runtime layer** — `ngv2/poc_writer.py` (the drafter/reconciler seam
contract) + a `hooks/` dir (the detonation Stop hook) — consuming the **ported** JM
synthesis core. This is distinct from the deterministic clean-room tooling: per the §9
owner authorization, the **agent-orchestration layer may be copied** (JM is trusted);
only net-new NGv2 **deterministic tooling** still goes through the JM pipeline.

## 6. Per-component COPY / ADAPT / BUILD-NEW port table

| Component | JM source | Verdict | NGv2 destination / note |
|---|---|---|---|
| Retry loop (`synthesize_with_retries`) | `harness/ast_retry.py` | **COPY-VERBATIM** | runtime layer; pluggable validator/agent callables, no JM coupling |
| bwrap jail builder | `harness/agent_jail.py` | **COPY-VERBATIM** (or reuse) | the real-runner path only; generic container machinery |
| D-Bus proxy | `harness/dbus_proxy.py` | **COPY-VERBATIM** | pure utility, zero coupling |
| Synthesis driver | `harness/orchestrator_worker.py` | **LIGHT-ADJUST** | strip git/auto-commit/`.no_diff`/ledger; wire the **pluggable acceptance gate** (detonation) at the accept point |
| Feedback channel | `harness/cross_examiner.py` | **LIGHT-ADJUST** | swap `session_namer` + drop `JANUSMASK_TASK_ID`; keep `ExamPacket`/anonymize/serialize |
| Smoke gate | `harness/sandbox_smoke.py` | **LIGHT-ADJUST** | drop bwrap/D-Bus/project-root discovery for the default mock path |
| Embedded-test gate | `harness/embedded_test_runner.py` | **LIGHT-ADJUST** | optional; keep `should_run_embedded_tests` AST logic if PoC self-tests are wanted |
| Stop hook (`_decide`) | `harness/hooks/claude/stop.py` | **REWRITE** | new acceptance = "detonation reproduced" (not "submit_code"); keep `stop_hook_active` escape hatch + deny-counter |
| Hook wiring | `config/claude_worker_hooks.json` | **REWRITE** | repoint to NGv2 hook modules |
| Agent-spawn helpers | `orchestrator.run_agent_phase` / `run_both_agents` / `_validate_submission` | **COPY (light config edits)** | the dual-agent spawn/poll/validate core |
| **Drafter/reconciler seam contract** (`poc_writer`) | — | **BUILD-NEW (pipeline)** | net-new NGv2 deterministic tooling → JM brief (Gap Epic 4) |
| **Acceptance-gate evaluator** | — | **BUILD-NEW (pipeline)** | composes detonation verdict + `submission_readiness` + CWE-match into one boolean + reason |
| PoC drafter prompts | legacy `ng-poc-writer.md` / `ng-verifier.md` / `ng-adversarial.md` (harvested to `.claude/agents/`) | **ADAPT** | source the drafter A / reconciler B system text; drop the outdated "JS-only" rule (corpus is 50/50 JS/Py) |

## 7. Minimal synthesis core (one draft→reconcile→retry→gate loop, no git)
`ast_retry.synthesize_with_retries` (verbatim) + `orchestrator.run_both_agents` +
`_validate_submission` (light) + the **pluggable acceptance gate** in place of
`orchestrator_worker`'s `_auto_commit_accepted`. The gate signature:
```
def acceptance_gate(poc: PoC, finding: Finding, *, runner, target_spec,
                    success_marker='VULNERABLE') -> tuple[bool, str]:
    report = DetonationChamber(success_marker).detonate(poc, target_spec, runner)
    ok = report.verdict == 'confirmed' and _cwe_matches(poc, finding) \
         and check_submission_pkg(finding, resolver).exists
    return ok, report.verdict
```

## 8. Sequenced implementation plan
1. **Port the safe primitives** (COPY-VERBATIM): `ast_retry`, `dbus_proxy`,
   `agent_jail` into the NGv2 runtime layer. No behavior change, no real runner wired.
2. **BUILD-NEW (pipeline, Gap Epic 4):** the `poc_writer` drafter/reconciler seam
   contract + the acceptance-gate evaluator, each with an oracle (drive with
   `make_scripted_runner`).
3. **Rewrite the Stop hook** around the acceptance gate; wire `cross_examiner`
   feedback (light-adjust). Bound by deny-counter.
4. **Adapt the dual-agent driver** (light `orchestrator_worker`) to call
   draft A → reconcile B → `ast_retry` → acceptance gate, no git/commit.
5. **Inject the contract**: finding + target spec + golden exemplar + taint spec into
   drafter A's brief (local reads from harvested `data/ngv2/`).
6. **e2e demo (mock only):** one finding → draft → detonate(scripted) → refine → reach
   `confirmed`. Real bwrap runner stays behind an owner-gated flag, never enabled in
   build/research.

## 9. Guardrails honored
Ported JM agent-orchestration is copied (owner-authorized); net-new NGv2 deterministic
tooling goes through the JM pipeline; oracles/tests/data are hand-authored. The
live-detonation seam stays mocked + owner-gated. B7 (`master`==`janusmask/work`) holds
for anything that lands later.
