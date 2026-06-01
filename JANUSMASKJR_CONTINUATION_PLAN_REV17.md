# JanusMaskJR — Continuation Plan (2026-06-01, rev 17)

> **rev 17 — written after the rev-16 Phase-1 pipelineable scope was executed (6 dual-agent landings, 0
> hand-edits, master `74f9b8d..4dff083`, PUSHED to `origin/master`) and then adversarially re-reviewed by a
> 4-agent Antigravity/Gemini panel (reports in `~/janusmask_briefs/review_rev17/R{1..4}_*.md`).**
> Supersedes `JANUSMASKJR_CONTINUATION_PLAN_REV16.md`. **Governing rule (owner directive, carried):** use the
> PIPELINE for every change wherever possible; HAND-EDIT only after a pipeline attempt fails with a PERMANENT
> blocker (never a timeout, never a re-groundable verification failure).
>
> **Verification discipline:** every file:line anchor below was re-verified by the overseer against live code at
> HEAD `4dff083` (the rev-17 Gemini panel reports drift and at least two over-stated "FLAW" verdicts — see §1).
> Re-verify each anchor again before action. **This plan will be adversarially re-reviewed by Claude agents next
> session; trust the verdicts only after that re-verification**, exactly as rev-16 did with its panel.
>
> **Read this first (state):** code-HEAD `4dff083`; this plan was committed on top as `d44ed07` (= current
> `origin/master` / `git HEAD`) — production code is byte-identical between the two (the d44ed07 commit adds only
> this `.md`), so every code anchor below is checkable at the live HEAD. (This session's 6 code commits were
> pushed.) Full suite **6323 passed / 1 failed** — the 1 fail
> (`test_track_record_events::test_sequence_of_random_appends_roundtrips`) PASSES in isolation = a pre-existing
> flaky randomized test in an untouched area, **NOT a regression**. All 5 rev-16 pre-existing failures (ESCMOCK×3
> + FAKEPOPEN×2) are now fixed. Hard invariants re-verified intact (per-file greps, §4): `synthesis_success =
> True` ×1 each, `skip_interface_fuzz` on `test_authoring` only (×1 each in 3 files), `_SENSITIVE_APPLY_GLOBS =
> ('harness/**','config/**','scripts/**')`, `BYPASS_FUZZER_TYPES` unnarrowed, `verify_extra_ro/rw` absent/empty in
> config, **`full_stop` PRESENT**. Phase A (lift `full_stop`) remains **OWNER-ONLY** and was not done.

---

## 0. Landed via PIPELINE this session — VERIFIED (do not re-do)

All dual-agent; production-code fixes shipped an oracle committed RED-first; §1b per-task where `harness/**`; tree
byte-checked after each. Panel R1 confirmed integrate-diff integrity and oracle non-vacuity on all 6 (its two
"FLAW" verdicts are over-stated — see §1). Anchors below re-verified @ `4dff083`.

| Commit | Item | Closes | Note (re-verified) |
|--------|------|--------|--------------------|
| `1dd92f1` (oracle `b4cf3ff`) | VALIDATOR-SIG | multi-symbol partial-edit false `return_type_mismatch` | `_validate_submission` `orchestrator.py:1108-1119`: lazy `_extract_func_name_from_signature`; `blk_sig` only on the matching `kind=='symbol'` entry. **Removes the omit-signature workaround → PATCH_CONVENTIONS #8 now MOOT.** §1b. |
| `8938313` (oracle `692df5b`) | KILL-REAP | stuck child crashes run loop | `kill_agent` final `proc.wait(timeout=3)` `orchestrator.py:446-449` wrapped in `except (TimeoutExpired, ProcessLookupError, PermissionError, OSError)`. §1b. |
| `309b2e0` | FAKEPOPEN-1 | `test_spawn_agent_cwd_relocated_outside_repo` AttributeError | `communicate(self,input=None,timeout=None)->('','')` added to module-level `_FakePopen` (`test_agent_isolation.py`). tests/**, no §1b/oracle (existing RED test = detector). |
| `710362b` (attempt 2) | ESCMOCK GROUP-A (3 tests) | degenerate-escalation false trip | scope `builtins.open` side_effect to `config.yaml` only + `_contain_selfheal` passthrough on the 2 claude `safe_loads_config` tests. **Attempt 1 rejected `unexpected indent` (dotted class-method patch emitted indented) → re-ground to WHOLE-CLASS replacement (col-0).** tests/**, no §1b. |
| `ddf2525` | BWRAP-PATH-MOCK | brittle hardcoded bwrap path | `test_sec5` `mock_which` → `original_which("bwrap") or "/usr/bin/bwrap"`. The 3 `build_jail_argv` STUBS (:90/:158/:216) left untouched (not `shutil.which` mocks). tests/**, no §1b. |
| `4dff083` | FAKEPOPEN-2 | `test_T5` AttributeError on func-local `_P` | **WHOLE-FILE `partial_edit:false` route** (the rev-16 suggested alternative; partial-edit cannot target a function-local class). Added `communicate` to `_P`. tests/**, no §1b. **CAVEAT (verified, R1/R4): the whole-file route let the agent cosmetically reformat (double→single quotes, dropped comment banners, import split; net −47 lines), incl. a PEP-701 nested-same-quote f-string at `:66`. Functionally identical (10 passed); 3.13-only project so PEP-701 is a non-issue, but the byte-identity criterion is NOT harness-enforced — see §1 whole-file guard.** |

**C13/H-WORKER-DAEMON refutation = STANDS as a verification result (no commit) — but the MECHANISM was
mis-stated and is corrected here (rev-17 Claude panel, consensus R1+R3).** The verdict holds; the *reason* in the
rev-16/early-rev-17 text ("a SIGSTOP'd sequential worker is bounded because SIGKILL is delivered to stopped
processes") is **wrong**. Re-verified at `4dff083`: the *sequential* worker is **never SIGSTOP'd** —
`suspend_parallel_workers` is called with `exclude_pid=pid` (`:1366`) and skips the just-launched pid (`:1274`),
so the foreground worker is never in `_suspended_pids`. It is the foreground `proc`, bounded by the wall-clock
watchdog loop `max(1800, 2*timeout+600)` (`autowork_daemon.py:1373`) → `_kill_process_group` SIGKILL of **that
`proc`** (`:1379-1382→:1884`). So the SIGSTOP-budget scenario simply **cannot arise** in sequential prod — not
because SIGKILL reaches a stopped process, but because the watched worker is never stopped. Prod config is
sequential (`active_agents=[claude,gemini]`, `antigravity_mode:false`, `config.yaml:105-108` →
`requires_claude=True` at `:1328`). **Two scope caveats (do not drop):** (1) this watchdog/SIGKILL bound exists
**ONLY in the `requires_claude` sequential branch**; the parallel `_spawn_worker` path (`:1411`) has **no
per-worker watchdog at all** — a hung/stopped worker there is unbounded until daemon-shutdown drain, so flipping
`antigravity_mode:true` / parallel **re-opens C13** (pin this alongside the `antigravity_mode:false` invariant).
(2) The SIGTERM-to-stopped-pid path (`:1388`) that the old refutation conflated with a bound is **itself the
DAEMON-SUSPEND-LEAK bug** — C13 and DAEMON-SUSPEND-LEAK are the SAME `:1388` code viewed two ways, not independent
findings. **R3 did NOT overturn the verdict** — it correctly identified that this `:1388` SIGTERM is ineffective
on a `T`-state pid (tracked as DAEMON-SUSPEND-LEAK in §1).

**MUT-HARNESS-ISO = DEFERRED this session** (low value; the `config.yaml` comment-strip noise is the uncontained
agy process, not this test, which already has crash-recovery snapshot/restore). **R2 argues it is actually
pipeline-viable** via `git worktree` + function-local imports (no new module-level symbols) — credible after
cross-check (see §1/§3); promoted to a Phase-1 attempt in rev-17.

---

## 1. Panel findings — NEW items the rev-17 review surfaced (verify-first)

Cross-checked against live code @ `4dff083`. Over-stated agy verdicts are corrected/down-graded; unverifiable
claims are 【marked】.

| Finding | Sev | Route | Overseer cross-check verdict |
|---------|-----|-------|------------------------------|
| **DAEMON-SUSPEND-LEAK** (R3 Path 1/2) | MED | **PIPELINE→likely hand-edit** | **REAL.** `autowork_daemon.py:1388` sends `SIGTERM` to a suspended (T-state) parallel pid, then drops it from `_suspended_pids` (`:1393-1395`) so `resume_parallel_workers` (`:1283-1292`, SIGCONT) never reaches it; a T-state process defers SIGTERM until SIGCONT → pid leaks in `T`, slot held. Also: daemon death between SIGSTOP/SIGCONT leaves a fresh daemon with empty `_suspended_pids` → no resume. **Contingent on parallel workers actually being suspended (rare in pure-sequential prod). NOT gating for the (i) owner-supervised single run; it IS the residual gating gap for (ii) UNATTENDED autonomous operation (consistent with §2(ii), which lists it).** (Earlier text called it simply "not Phase-A-gating" — that was ambiguous; it gates (ii), not (i).) Fix: SIGKILL (not SIGTERM) the over-aged suspended pid, or keep it in the set / SIGCONT-then-SIGTERM. |
| **DAEMON-SELFHEAL-UNTRACKED** (R3 Path 4) | LOW | **PIPELINE** | **REAL.** Inactivity self-heal spawn `autowork_daemon.py:1816` is `subprocess.Popen` with NO pidfile → `_reap_running`/`_drain_running` don't track it; a hung planning agent leaks. (It IS jailed via `_contain_selfheal`, and it's a planner not a slot-holding worker, so LOW.) Fix: write a pidfile / track it. |
| **PARITY-2 (bare_except)** (R4) | MED | **PIPELINE** | **REAL, same class as PARITY-1.** Submit-time `services/neurosymbolic/ast_verifier.py:160` flags ANY bare `except:` as ERROR; commit-time `harness/ast_enforcer.py:101-103` flags ERROR only when the body is exactly `pass`. So `except: log()` is DENIED at submit but ALLOWED at commit → interceptor ⊄ enforcer (interceptor too strict, blocks valid submissions). Fix: downgrade the verifier's non-`pass` bare-except to WARNING (or align to enforcer's `body==[Pass]` test). services/+tests/, no §1b. |
| **PARITY-NONDET (note only)** (R4) | LOW | observe | **REAL but OPPOSITE direction** (commit stricter than submit): enforcer rejects `import random`/`uuid` (`ast_enforcer.py:48-52`), verifier only flags unseeded random *calls*. This causes wasted late-stage AST-retry failures, not a safety bypass; it does NOT violate `submit ⊆ commit`. Optional alignment; not gating. R4's credential-rule divergence is similar (late-fail, not a bypass). |
| **MUT-HARNESS-ISO-PIPELINE** (R2) | MED | **PIPELINE** | **PLAUSIBLE — route corrected.** `_apply_symbol_patch` (`git_integration.py:993/995`) rejects extra body nodes / renames but DOES allow function-local imports inside a replaced symbol body. R2's `git worktree`-based isolation needs only function-local `import tempfile/shutil/subprocess` inside existing symbols (`_run_eval_suite`/`_apply_and_check_killed`) → no R-anchored-patch required. Verify the worktree approach is sound under a jailed worker before relying on it. |
| **WHOLE-FILE-DRIFT-GUARD** (R4) | MED | **PIPELINE (new oracle)** | **REAL gap — mechanism corrected (consensus R1+R2).** The `partial_edit:false` whole-file route (used by FAKEPOPEN-2) merges via `_ast_merge` (a NAME-KEYED wholesale symbol-replace, NOT a blind whole-file overwrite: `git_integration.py:684`) → `ast.unparse`, which re-emits the merged tree and therefore strips comments + normalizes layout for **every symbol the agent re-emitted, even on a single-symbol change** (truly-unrelated symbols absent from the submission are preserved; the drift is comment-loss/reformat of re-emitted symbols + possible dead-node append on rename, not arbitrary unrelated-scope rewrites). No diff-scope gate exists. **A line-diff/size threshold is NOT viable** — `ast.unparse` comment-loss makes even a legitimate single-symbol whole-file submission a large diff. Add a commit-time guard using an **AST-node-set-vs-`files_touched`** check, located in **`commit_accepted_output` (post-`_ast_merge`)** — NOT `_validate_submission`, which runs at submit-time and never sees the merged AST. |
| 【VALIDATOR-SIG region "FLAW"】 (R1) | LOW | **REFUTED / optional** | **OVER-STATED by agy.** R1 claims a `kind:'region'` patch now bypasses return-type validation. But (a) the per-block return-type check was the very false-positive being fixed; (b) there is NO commit-time return-type enforcement at all (`declared_signature`/`validate_return_type` appear nowhere in `git_integration.py`) — it is a contract convenience, not a security boundary; (c) a region patch is a marker-scoped fragment, not a complete `def F`. Behavior is gated by the oracle + acceptance criteria + scoped tests. NOT a safety regression. Optional hardening only (VALIDATOR-SIG-2: also gate matching-name region patches). |
| 【FAKEPOPEN-2 PEP-701 "FLAW"】 (R1) | INFO | none | **CORRECT-but-moot.** `:66` `f'cwd {captured['cwd']} ...'` is PEP-701 (3.12+). Project is 3.13-only → no action. Captured in the WHOLE-FILE-DRIFT-GUARD item above. |

**Panel verdicts on known items (cross-checked):** R1 — 6/6 landings sound (its 2 FLAWs over-stated above);
oracles non-vacuous; invariants intact. R2 — Phase-2 anchors re-anchored (+22 lines in `orchestrator.py` below
line 1473; see Appendix); `_apply_symbol_patch` capability claim CONFIRMED (no module-level adds, leaf-name
locked, 1–2 part qualnames only → func-local class = permanent blocker). R3 — SEC-1 D-Bus escape CONFIRMED;
C13 refutation stands (R3's contrary verdict actually targets DAEMON-SUSPEND-LEAK). R4 — all 5 hard invariants
PASS; whole-file drift + bare_except parity are the real new items.

---

## 2. Phase-A / daemon-enable gating

- **(i) OWNER-SUPERVISED single foreground run** (`autowork_daemon --once`, operator watching): minimal gating set
  is **COMPLETE** — SEC-3 ✅, MUT-MASK ✅, ATEST-STDERR ✅, C2/ROLLB-A ✅, C5/AGY2D ✅, KILL-REAP ✅ (all landed).
  No remaining blockers; the operator manually reaps any hung worker and runs the Phase-A write-denial suite. R3
  concurs.
- **(ii) UNMONITORED autonomous daemon operation:** remaining gating items are **SEC-1** (D-Bus systemd escape) +
  **DAEMON-SUSPEND-LEAK** (the slot-leak R3 surfaced). **C13/H-WORKER-DAEMON is no longer a gating item** — the
  original SIGSTOP-budget concern is refuted (external SIGKILL watchdog bounds it); DAEMON-SUSPEND-LEAK is the
  real residual daemon-stability gap and supersedes it. KILL-REAP (✅), MUT-HARNESS-ISO and
  DAEMON-SELFHEAL-UNTRACKED are recommended hygiene before un-attended operation.
- **Phase A itself (OWNER-ONLY, unchanged):** `pytest
  tests/adversarial/test_phase_a_selfheal_jail_writedenial.py -v` on the owner host; confirm the bwrap-flip mutant
  → **failures, not skips** (now also asserts EROFS/EACCES stderr); owner 8-pt review + go/no-go; `rm
  state/control/autowork/full_stop`. **Do NOT automate.**

---

## 3. Ordered next steps — PIPELINE-FIRST

Each pipeline item: Gemini drafts brief (`agy` — abs paths + `--add-dir`; no `--model`) → Opus sub-agent
adversarially reviews/corrects vs live code, verifies oracle RED-on-HEAD, confirms repo CLEAN → overseer ingests,
commits oracle RED-first, self-approves §1b (`harness/**` only), runs `.venv/bin/python -m
harness.orchestrator_worker --state-dir state --task-id <ID>`, verifies (`{"skipped":"not_found"}` + integrate
commit scope + both submissions + invariants + targeted suite + tree clean). Apply PATCH_CONVENTIONS #1-#8.
**Note #8 is now MOOT** (VALIDATOR-SIG landed) — multi-symbol partial edits MAY again declare a per-function
signature; the validator scopes it to the matching symbol. Serialize repo-touching work; never run agy/a
sub-agent during a worker run; restore `config.yaml` if agy strips comments.

**Phase 1 — pipeline-viable (do first; ordered):**
1. **PARITY-2 (bare_except)** — downgrade `ast_verifier.py:160` non-`pass` bare-except to WARNING / align to the
   enforcer's `body==[Pass]` test, restoring submit ⊆ commit. services/+tests/, no §1b. (Do early: it removes a
   class of spurious submit-time denials that can stall later pipeline runs.) Oracle: a submission with
   `except: log()` must clear submit-time. PIPELINE.
2. **MUT-HARNESS-ISO** — isolate `test_P2_mutation_kill.py` mutations into a `git worktree`/tmp copy using
   FUNCTION-LOCAL `import tempfile/shutil/subprocess` inside `_run_eval_suite` + `_apply_and_check_killed` (R2
   route; no module-level symbols → no R-anchored-patch needed). tests/**, no §1b. **Attempt the partial-edit
   (whole-symbol) route FIRST; if a func-local-only constraint blocks it, fall back to a `partial_edit:false`
   whole-file submission (then mind WHOLE-FILE-DRIFT-GUARD).** PIPELINE.
3. **BWRAP-PATH-MOCK (residual)** — audit the OTHER oracles R1 flagged that still hardcode `/usr/bin/bwrap`
   (e.g. `test_sec2_jail_extra_ro_prefix.py`) and de-hardcode the `shutil.which` mocks the same way as `ddf2525`.
   tests/**, no §1b. PIPELINE. (LOW; only if any remain RED/brittle on a non-standard host.)
4. **DAEMON-SELFHEAL-UNTRACKED** — write+track a pidfile for the inactivity self-heal spawn
   (`autowork_daemon.py:1816`) so `_reap_running`/`_drain_running` can reap it. §1b (`harness/**`). Oracle: assert
   a pidfile is created for the self-heal child. PIPELINE.
5. **WHOLE-FILE-DRIFT-GUARD** — add a commit-time gate in **`commit_accepted_output` (post-`_ast_merge`)** — NOT
   `_validate_submission`, which is submit-time and never sees the merged AST — rejecting whole-file submissions
   that mutate AST nodes (functions/classes) **outside `files_touched`'s declared symbols** unless the task is
   flagged whole-file/new-file. Use an **AST-node-set-vs-`files_touched`** check, NOT a line-diff/size threshold
   (`ast.unparse` comment-loss makes even a legit single-symbol whole-file submission a large diff → a size gate
   would false-trip). §1b (`harness/**`). Oracle: a whole-file submission that edits an unrelated function is
   rejected; the legitimate single-symbol whole-file case is accepted. PIPELINE.
6. **DAEMON-SUSPEND-LEAK** — fix the SIGTERM-to-stopped-pid leak: SIGKILL (not SIGTERM) the over-aged suspended
   pid at `autowork_daemon.py:1388`, OR keep it in `_suspended_pids` until SIGCONT then SIGTERM; and on daemon
   start, SIGCONT/reap any orphaned `T`-state workers. §1b. **Attempt PIPELINE (whole-symbol replace of the
   sequential-launch block + `resume_parallel_workers`); if it needs new module-level helpers → permanent blocker
   → Phase-2 hand-edit.** Oracle: a suspended pid past the 300s threshold is terminated, not left in `T`.

**Phase 2 — hand-edit ONLY after a pipeline attempt fails with a PERMANENT blocker:**
7. **R-anchored-patch** — upgrade `git_integration._apply_symbol_patch:939` to allow a bounded set of extra body
   nodes (`Import`/`ImportFrom`/`FunctionDef`/`ClassDef`) alongside the single target def (R2 design). **HIGH
   LEVERAGE — converts SEC-1 and any "needs new module-level import/symbol" item into pipeline-viable work.**
   **Bootstrap rule:** the patch upgrading the applier MUST itself obey the OLD applier (single target symbol,
   function-local imports only, nested helpers only) so the in-memory old applier accepts it. Attempt pipeline
   under that constraint first; hand-edit only if even that is blocked. §1b. Oracle: post-upgrade, a patch adding
   a module-level import + helper applies cleanly.
8. **SEC-1** — `xdg-dbus-proxy` sidecar filtering the session bus to `org.freedesktop.secrets`, blocking
   `org.freedesktop.systemd1.StartTransientUnit` (`agent_jail.py:239-245`; bind the proxy socket to
   `<XDG>/bus`). HIGH security, agy-auth-risky. **Needs new subprocess + socket lifecycle + likely new imports**
   → attempt pipeline (much easier AFTER R-anchored-patch lands); expect permanent blocker pre-R → hand-edit.
   **MUST ship a negated-PoC regression test** (`test_sec1_dbus_escape.py`: jailed `StartTransientUnit`/`ListUnits`
   REFUSED; control run with unfiltered bus succeeds). **MUST re-run the agy-auth smoke
   (`~/janusmask_briefs/agy_jail_smoke.py`) after and REVERT if agy auth breaks** (the proxy filter can starve
   gnome-keyring/portal names agy needs). Deserves a dedicated session. §1b.
9. **ROLLB-D** (try/finally over the `_auto_commit_accepted` body — which is **~613 lines, def `:1473-2086`**, NOT
   the ~360-line / `:1716-2084` figure earlier text used; the `:1716` anchor is ~243 lines INTO the function, so a
   try/finally must wrap from the body start near `:1473` through `:2085` to actually protect the staging-worktree
   setup), **ROLLB-E** (13 non-contiguous `_mark_processed` sites in `run_pipeline`). R2 argued both are
   whole-symbol-replace pipeline-viable; attempt the whole-symbol partial-edit route FIRST (`orchestrator.py`
   `_auto_commit_accepted` `:1473-2086`, `run_pipeline` `_mark_processed` ~`:2326-2476`). **For a 613-line symbol,
   expect gemini-truncation of the long function sum or applier reindent-rejection → permanent blocker → hand-edit
   as the LIKELY outcome, not a remote fallback.** §1b.

**Phase A (OWNER-ONLY):** see §2.

> **Sequencing note:** Items 4 + 6 edit `autowork_daemon.py`; items 5 + 9 + (8 post-R) edit `orchestrator.py` /
> `git_integration.py` (different functions). Run serially; re-ground each against the prior HEAD. Land
> R-anchored-patch (item 7) before SEC-1 to keep SEC-1 in-pipeline. Items needing **R-anchored-patch to become
> pipeline-viable**: SEC-1 (new imports/symbols), and any future "add a module-level helper" work.

---

## 4. Invariants carried through EVERY phase (do-NOT) — per-file grep checklist

- Never single-agent / lone-candidate acceptance: `grep -c "synthesis_success = True"` **== 1 in EACH** of
  `harness/orchestrator.py` (`:2320`) and `harness/orchestrator_worker.py` (`:309`). HALT on mismatch. (Bypass
  route: claude is sole *author*, gate syntax intact, §1b is the human backstop.)
- Never narrow `BYPASS_FUZZER_TYPES`; `test_authoring` stays `bypass_fuzzer:False`; `grep -c
  "skip_interface_fuzz"` **== 1 in EACH** of `harness/planner/taxonomies.py` (`:1`), `harness/orchestrator.py`
  (`:2331`), `harness/orchestrator_worker.py` (`:320`) — and ONLY on `test_authoring`. **(Use per-file greps; a
  tree-wide count of 3 is correct and expected, not a violation.)**
- `_SENSITIVE_APPLY_GLOBS == ('harness/**','config/**','scripts/**')` at `git_integration.py:16` — unchanged.
- **`verify_extra_ro` / `verify_extra_rw` must remain ABSENT (→ empty `[]` via `.get(...,[])`) in
  `harness/config.yaml`.** Populating `verify_extra_rw` would re-open a host write path (defeats SEC-2/SEC-5);
  `verify_extra_ro` could expose `~/.ssh`/`/etc`. Any population requires explicit operator audit. (Consumers:
  `orchestrator.py:1677-1678`, `embedded_test_runner.py:125-126`; binds at `agent_jail.py:121-133`.)
- Keep submit-time AST interceptor ⊆ commit-time enforcer (the PARITY-1/PARITY-2/H-INT class): the verifier
  (`services/neurosymbolic/ast_verifier.py`) must not ERROR on anything the enforcer (`harness/ast_enforcer.py`)
  would ACCEPT. (PARITY-2 = the current live violation to fix; do not introduce new ones.)
- **VALIDATOR-SIG invariant:** in `_validate_submission`'s partial-edit branch (`orchestrator.py:1108-1119`), only
  a `kind=='symbol'` patch whose `name` equals the signature's function may receive `declared_signature`; every
  other patch (region patches, unrelated symbols) MUST receive `blk_sig=None`. Do not revert to validating every
  block against the one declared signature.
- **Whole-file submission discipline:** until WHOLE-FILE-DRIFT-GUARD (§3 item 5) lands, a `partial_edit:false`
  whole-file submission can strip comments / normalize layout / append dead nodes via `_ast_merge`+`ast.unparse`.
  Review the integrate diff for out-of-scope changes; prefer partial-edit. Byte-identity is NOT harness-enforced.
- agy-backed agents route submission via STDIN; never argv `-p`+file-write in the jail. agy is NOT tree-isolated
  → after ANY agy run: `repo_snapshot.sh` + verify byte-identical + revert drift. **Known benign nuisance:** an
  external process re-emits `harness/config.yaml` with comments stripped (values identical) — restore with `git
  checkout HEAD -- harness/config.yaml`.
- Never add `*_fix`/any `<task>_fix` to the allowlist. `full_stop` stays present until owner-gated Phase A. §1b
  (`_apply_approval_granted`) is the autonomous-commit boundary; `meta_task_type`/`mutations`/`mutation_target`
  read ONLY from the jail-ro task spec. Mutation-gate fail-closed semantics unchanged. Agents tree-isolated ONLY
  via the bwrap jail.

---

## Appendix — anchors (re-verified @ `4dff083`; RE-VERIFY before use)

- `harness/orchestrator.py`: `_validate_submission` per-patch `declared_signature` **:1105-1120** (sig-scope at
  1108-1118) [VALIDATOR-SIG]; whole-file fallback validation **:1128-1153** / save **:1174**; `kill_agent` final
  wait guard **:446-449** [KILL-REAP]; `_auto_commit_accepted` staging **~:1710**, jailed binds
  **:1834/1959/1983/1997**, SEC-3 verify catch **:1854-1874**, MUT-MASK baseline-in-copy **:1944-1963**; `_auto_commit_accepted`
  def/body span for ROLLB-D **:1473-2086 (~613 lines)** (the **~:1710** staging anchor is mid-function, NOT the
  def); ROLLB-E `_mark_processed` sites in `run_pipeline` **~:2326-2476** (+ single site
  **~:2045**); `verify_extra_ro/rw` reads **:1677-1678**; four-gate `synthesis_success = True` **:2320** (×1);
  `_skip_ifz` **:2331** (×1).
- `harness/orchestrator_worker.py`: `synthesis_success = True` **:309** (×1); `_skip_ifz` **:320** (×1); monotonic
  budget (retry-only) **:244**.
- `harness/autowork_daemon.py`: `requires_claude` **:1328**; sequential launch + suspend **:1354-1409**; watchdog
  timeout `max(1800,2*timeout+600)` **:1373**; `_kill_process_group` call **:1381** / SIGKILL **:1884**;
  suspended-pid SIGTERM **:1388**, drop-from-set **:1393-1395** [DAEMON-SUSPEND-LEAK]; `suspend_parallel_workers`
  **:1265**, `resume_parallel_workers`/SIGCONT **:1283-1292**; `_spawn_worker` **:827/:1411** (parallel branch, no
  watchdog); inactivity self-heal Popen (no pidfile) **:1816** [DAEMON-SELFHEAL-UNTRACKED]; `_reap_running`
  waitpid/kill(0) **~:317-350**.
- `harness/agent_jail.py`: repo ro-bind **:247**; XDG tmpfs + bus/keyring `--bind` **:239-245** [SEC-1]; `extra_ro`
  binds **:121-124**, `extra_rw` binds **:130-133** [SEC-5].
- `harness/ast_enforcer.py`: nondeterminism import reject **:48-59**; `bare_except` (body==Pass only) **:101-103**;
  `_extract_func_name_from_signature` **:251**; `incomplete_ast` **~:222-224**; `validate_code` **:187**.
- `services/neurosymbolic/ast_verifier.py`: `bare_except` (any) ERROR **:160** [PARITY-2]; unseeded-random
  post-pass **:244**.
- `harness/git_integration.py`: `_SENSITIVE_APPLY_GLOBS` **:16**; `_parse_patches` (kinds `symbol`/`region`)
  **:875** (kind set **:888-890/929-933**); `_apply_symbol_patch` **:939** (single-body assert **:993**,
  leaf-name assert **:995**, 1–2-part qualname only) [R-anchored-patch]; `_apply_region_patch` **:1016**;
  `commit_accepted_output` / `_ast_merge` whole-file path [WHOLE-FILE-DRIFT-GUARD].
- `tests/adversarial/test_spawn_cwd_and_prompt_isolation.py`: func-local `_P` **~:39** (PEP-701 f-string **:66**);
  `test_P2_mutation_kill.py`: live-file mutation `_run_eval_suite`/`_apply_and_check_killed` [MUT-HARNESS-ISO].
- `state/control/autowork/full_stop`: **PRESENT** (`halted`).
