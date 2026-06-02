# JanusMaskJR — Continuation Plan (2026-06-01, rev 20)

> **rev 20 — written after the full REV19 §2 Phase 1 security-hardening scope was EXECUTED this session (8 dual-agent
> pipeline landings, code `9ab8bac`→`a2f35a4`, all PUSHED to `origin/master`, 0 hand-edits, 0 regressions) and then
> adversarially re-reviewed by a 4-area cross-vendor `agy` (Antigravity Gemini) panel, Opus-cross-checked (reports in
> `~/janusmask_briefs/review_rev20/R{1..4}_*.md`).** Supersedes `JANUSMASKJR_CONTINUATION_PLAN_REV19.md`.
>
> **Governing rule (owner directive, carried + re-affirmed):** use the JanusMaskJR PIPELINE for every change wherever
> possible; HAND-EDIT only AFTER a pipeline attempt FAILS with a permanent/structural blocker (never a timeout, never a
> re-groundable stale-ground-truth or mis-render). Agents (brief authors, reviewers) should use **codebase-memory-mcp**
> (project `home-xnihil0zer0-JanusMaskJR`, index ready) to understand structure before acting.
>
> **Cadence (owner directive):** this plan will be adversarially **Claude-reviewed NEXT session**, and **executed the
> session AFTER**. The forward-looking findings below are marked **[agy R#; Opus-cross-checked]** — every flagged hole
> was independently CONFIRMED against code at HEAD `a2f35a4` (agy's only inaccuracies were approximate line anchors + a
> wrong-HEAD header label + a "14 sites" miscount → really 12; all caught, no substantive false findings).
>
> **HEADLINE (the honest status):** SEC-1's proxy is now **WIRED into every jailed-spawn site and the filter design is
> sound**, BUT the escape is **NOT fully fail-CLOSED** — three residual vectors (fail-open→host-bus, abstract-socket
> bypass, `--once` path) keep the systemd1/StartTransientUnit escape latent for UNATTENDED operation. These are REV20's
> first priorities (§2 Phase 1) and are all small pipeline-viable fixes. **`full_stop` PRESENT; Phase A OWNER-ONLY —
> do NOT lift until the gate-ii closers (#1–#5) land.**

---

## 0. Landed this session — VERIFIED (do not re-do) — ALL VIA PIPELINE, 0 production hand-edits

REV19 §2 Phase 1 security hardening. Each item: a brief authored by `agy`/Opus inside a worktree-isolated Opus
sub-agent that adversarially reviewed/corrected it, proved the oracle RED on HEAD, ran the full verification_command
against fixed scratch; overseer ingested without reading (cp taskspec→`state/tasks/<ID>.json`, oracle→`tests/`, §1b
approve, commit oracle RED-first, run worker, Monitor, verify AST-scope + both submissions + suite + invariants + tree,
push). agy panel R1: **all 8 CONFIRMED structurally sound, scoped to declared symbols, non-vacuous oracles, invariants intact.**

| Commit | Item | Note (overseer + agy-R1 verified) |
|--------|------|--------------------------|
| `ef83d4d` | SEC-ENV | `orchestrator.py::_build_agent_env` `{**os.environ}` host-secret leak → strict in-body ALLOWLIST. Single-symbol. agy auth-gate PONG-confirmed. |
| `85d9666` | SEC-1a | NEW `harness/dbus_proxy.py` (114ln, stdlib) — `proxied_session_bus()` spawns `xdg-dbus-proxy --filter --talk=org.freedesktop.secrets` (systemd1 blocked, keyring preserved), reaps on exit. New-file route. |
| `d9bd232` | SEC-1b | `agent_jail.py::build_jail_argv` gained keyword-only `dbus_proxy_socket=None`; binds it at in-jail `<xdg>/bus` when set (backward-compat). |
| `ebacb2e` | SEC-1c-EASY3 | 3 SYNC verify spawns wrapped (`run_embedded_tests` ×2, `smoke_import`, `_exec_module` via ExitStack). Fail-open `try/except→None`. Multi-file `.patches.json`. |
| `1d9e8a7` | SEC-1c-ORCHACC | `_auto_commit_accepted` 4 sync verify/baseline/mutant `subprocess.run` sites wrapped (690ln single-symbol repro, clean). |
| `5ee9dc0` | SEC-1c-SPAWN | `spawn_agent` + `kill_agent` — `contextlib.ExitStack`; agy-sync closes on both normal+timeout, claude-detached attaches `proc._dbus_stack` closed by kill_agent. AUTH-critical; agy PONG'd end-to-end through the new path. Large diff = whitespace re-indent only (verified `git diff -w`). |
| `c84c51c` | SEC-1c-DAEMON | `run_daemon` opens daemon-lifetime SINGLETON proxy (module global `_SELFHEAL_DBUS_SOCKET`), `_contain_selfheal` threads it (covers both `_escalate_*`). Backward-compat None keeps 3 Popen-count tests green. |
| `a2f35a4` | SEC-ENV-DAEMON | `_escalate_to_autobrief`/`_escalate_inactivity` `env=dict(os.environ)`→allowlist (identical to `_build_agent_env`). |

**Headline lesson (carried):** every REV19 "DEDICATED / likely hand-edit" prediction for SEC-1 was REFUTED — new-module,
690-line single-symbol reproduction, the auth-critical ExitStack synthesis wrap, and the daemon-singleton all landed via
the dual-agent pipeline with 0 hand-edits. The dominant real risk remains stale existing-test assertions → always run the
full verification_command (incl. existing tests) against fixed scratch before dispatch. **agy is NOT tree-isolated → it
leaks oracle/edit files into the MAIN tree via `--add-dir <abs path>`; verify byte-clean + revert after EVERY agy run.**

---

## 1. Daemon-enable gating + Phase A status (re-evaluated @ `a2f35a4`, agy R2/R4)

- **(i) OWNER-SUPERVISED single run:** essentially met. **Residual: `--once` proxy bypass** (`main()` `--once`→`_iteration`
  never enters `run_daemon`, so `_SELFHEAL_DBUS_SOCKET` is never inited → self-heal under `--once` falls back to the host
  bus). Moderate — supervised path only. Closed by REV20 #4.
- **(ii) UNATTENDED autonomous daemon — STILL NOT MET (the SEC-1 escape is NOT fail-closed):**
  - **Fail-open fallback (HIGH):** `try/except → dbus_proxy_socket=None` → `agent_jail.py:248` binds the REAL unfiltered host
    bus inside the jail → systemd1/StartTransientUnit reachable whenever the proxy can't spawn (binary absent, ENOMEM,
    proxy-pid kill, resource starvation). Opposite of the bwrap-absent fail-CLOSED discipline. **The #1 gate-ii blocker.**
  - **Abstract-socket bypass (HIGH, host-config-dependent):** `agent_jail` deliberately does NOT unshare net/IPC (needed for
    agy OAuth under `--share-net`), and SEC-ENV allowlists `DBUS_SESSION_BUS_ADDRESS` THROUGH verbatim. If the host bus is an
    abstract socket (`unix:abstract=…`), the jailed agent dials it directly, ignoring the `<xdg>/bus` bind. Inert if the host
    bus is a path socket (typical logind desktop) — but undefended in code → latent on an unknown unattended host.
  - **Stability — NO global runaway-loop ceiling (REAL need, agy R4):** per-task retry budgets + quarantine exist; there is no
    cross-task total ceiling. A buggy planner can cascade `task_fix_1→task_fix_2→…` burning slots/API credits unsupervised
    (corroborated by the recurring `EX` phantom-task self-heal loop). REV18 stability items (PGID watchdog, startup orphan reap,
    self-heal collision, staging rollback) are CLOSED.
  - Low-sev: `xdg-dbus-proxy` leak on SIGKILL/crash (no `PR_SET_PDEATHSIG`) — resource cleanliness, not an escape; optional.
- **Phase A (OWNER-ONLY, unchanged):** `pytest tests/adversarial/test_phase_a_selfheal_jail_writedenial.py -v`; bwrap-flip
  mutant → failures-not-skips; owner 8-pt review; then `rm state/control/autowork/full_stop`. **Do NOT lift `full_stop`
  until REV20 #1–#5 (the gate-ii closers) land.** Do NOT automate.

---

## 2. Ordered next steps — PIPELINE-FIRST

Same workflow as §0 (SEED→worktree Opus sub-agent drives agy/Opus brief→adversarial review→prove RED→overseer ingests
UNREAD→worker→verify→push). Apply §4 invariants. **Phase 1 = the gate-ii closers; all pipeline-viable; land BEFORE owner Phase A.**

**Phase 1 — close the SEC-1 residuals + the runaway ceiling (security/stability gate-ii):**

1. **SEC-1-FAILCLOSED (HIGH; PIPELINE).** Make the proxy fail-CLOSED on the daemon/unattended path: when `sandbox_enabled` and
   the proxy can't spawn, REFUSE to spawn the agent (mirror the existing bwrap-absent `RAISE`) instead of falling back to
   `dbus_proxy_socket=None`→host bus. Consider a `config.yaml` flag to keep fail-open ONLY on operator-supervised verify
   spawns if a real need appears; default fail-closed for synthesis + self-heal. Touch the fail-open `except` branches landed
   this session (spawn_agent, _contain_selfheal, the 4 ORCHACC sites, the 3 EASY3 sites). Oracle: assert a forced
   proxy-spawn-failure → refusal (not a host-bus bind).
2. **SEC-1-DBUSADDR (HIGH; PIPELINE).** In the JAIL env, OVERRIDE `DBUS_SESSION_BUS_ADDRESS=unix:path=<xdg>/bus` (point at the
   bound proxy socket) instead of allowlisting the host value through. Kills the abstract-socket bypass. Small edit in
   `_build_agent_env` (and the daemon self-heal env builds) — set the var explicitly rather than passing it from `os.environ`.
   Re-run the agy auth smoke after (auth must still work). Oracle: assert the jail env's `DBUS_SESSION_BUS_ADDRESS` is the
   `<xdg>/bus` path form, not the host value.
3. **SEC-1-AUTHGATE-HARDEN (MED; PIPELINE — test/script).** Strengthen `~/janusmask_briefs/sec1c_spawn_authgate.py` into a real
   escape-regression oracle: (a) force a token refresh / run with cleared-or-stale `~/.gemini/oauth_creds.json` so the keyring
   round-trip over the FILTERED bus is genuinely exercised (a cache hit currently gives a false GREEN), and (b) add a NEGATIVE
   CONTROL — from inside the jail attempt a `StartTransientUnit` D-Bus call and assert it is DENIED (distinguishes a filtered
   bus from an unfiltered one). This also fills R1's missing runtime oracle (`test_sec1_dbus_escape.py` is config-level only —
   asserts the argv, not live filtering). Ship as a live security test.
4. **DAEMON-ONCE-PROXY (MOD; PIPELINE).** Initialize the singleton proxy in `main()` before the `--once`/`run_daemon` branch
   (or lazily in `_iteration`) so `--once` self-heal spawns also get the filtered bus. Closes the gate-i residual.
5. **RUNAWAY-CEILING (MED; PIPELINE).** A global max-total-retries / cascade ceiling across tasks (cost circuit-breaker) for
   fully-unattended operation — bound the `task_fix→task_fix` cascade that evades per-task budgets. Key on a daemon-level
   counter; refuse new self-heal escalations past the ceiling; log what was dropped (no silent cap).

**Optional / deferred (verify-first; agy R4 judged low-priority — do NOT over-engineer):** WFDG-2 (already covered by the
landed WHOLE-FILE-DRIFT-GUARD + `_SENSITIVE_APPLY_GLOBS`), R-ANCHORED forward-ref ordering (cosmetic — Python resolves refs
at call time), SIGKILL proxy-leak `PR_SET_PDEATHSIG` (cleanliness only).

**Phase A (OWNER-ONLY):** after #1–#5. See §1.

---

## 3. External-project capability (§3B-D) — anchors re-verified @ `a2f35a4`; owner authorizations applied

> Owner-requested capability: run JanusMask autonomously INSIDE an EXTERNAL project, with self-build gates active ONLY when
> the target IS the JanusMask repo. **§3B-D (brief-driven targeting) is the intended architecture.** agy R3 verdict:
> **sound IN INTENT; every anchor ACCURATE; the safety hinges ENTIRELY on the four trust-hardening requirements below —
> missing any one re-opens self-modification-without-gates.** All PIPELINE-FIRST where viable.
>
> **OWNER AUTHORIZATIONS (this session):**
> - **G1 (external task origination / work-discovery) — AUTHORIZED to build during execution.** Today there is NO external
>   task source (REV18 §3B-C "biggest hole"); §3B-D's CONFIGURABLE brief source + REQUIRED `working_dir` brief field is the
>   implementation. Build it as part of the §3 buildout.
> - **G2 (AST-rule stay-self/relax-external split) — overseer RECOMMENDATION below; owner to confirm at Claude-review.**

**The 5 plumbing seams [agy R3 — all CONFIRMED accurate at `a2f35a4`]:** `working_dir` (distinct from `work_dir`) is 0× in
`harness/` today — every seam is GREENFIELD.
1. `harness/planner/brief_loader.py:160` (`load_brief` def `:121`) — the frontmatter normalize loop keeps only
   `REQUIRED_SECTIONS` (def `:66`); `working_dir` is silently dropped → add it to an optional-field allowlist.
2. `harness/planner/blind_draft.py:122` (`run_blind_drafts` def `:118`) — the `json.dump({...})` serialization whitelist;
   `working_dir` MUST stay OUT of it (this feeds the untrusted planner — the trust-fork boundary). (`:128` was the old wrong anchor.)
3. **STAMP (trust fork) — NET-NEW DAEMON CODE:** `harness/autowork_daemon.py:1103` region (the `stage_task(plan_path,…)` extract
   loop, `unstaged = rec.get(...)` at `:1103`, `stage_task` call ~`:1113`) does NOT load the operator brief and has NO
   `working_dir` in scope → copies the LLM plan task VERBATIM. Trusted code must: (a) load `working_dir` from the operator brief,
   (b) **STRIP any LLM-authored `working_dir`** from the plan task, (c) stamp the trusted value.
4. `harness/planner/staging.py:16` (`def stage_task(plan_path, task_id, state_dir, canonical=True)`) — dumps the task dict
   verbatim with NO key-stripping/extra-field schema validation; carry the stamped value here.
5. `harness/hooks/_decide_common.py:86` (`decide_submission` def `:80`, `task = _paths.load_inbox_task(...)` at `:86`) — read
   `task.working_dir` to decide self-build-gate relaxation.

**Predicates TO BE BUILT (agy R3 — confirmed greenfield):**
- **`_target_is_self()` — DOES NOT EXIST** (only the unrelated module-name `oracle_attach.py:30 _target_is_self_modification`).
  Build as NEW code: extend the `paths.py:62` 2-clause GAP_H3 guard (`resolved == PROJECT_ROOT or PROJECT_ROOT in resolved.parents`)
  to **3 clauses** (+ `resolved in PROJECT_ROOT.parents` — reject a target that is a PARENT of the repo). **`.resolve()` FIRST.**
- **`effective_target_root()` — DOES NOT EXIST.** Build.

**Re-key T2–T5 onto `task.working_dir`**, gated by `_target_is_self()`: T2 = §1b decision; T3 = re-route the verify/synth spawns
(the 4 verify spawns source `repo_root` from a self-derived staging worktree → need the staging machinery rooted at the target,
not a constant swap; the 2 synth sites need signature plumbing); T4 = `agent_workroot()` writer + the 3 external readers follow
the target while `JANUSMASK_PROJECT_DIR`/`PYTHONPATH` STAY self; T5 = no-op ONLY `_maybe_push_and_rebase_pin` (`autowork_daemon.py:1479`),
NOT `_auto_promote`'s whole body (it is the generic staging engine — no-oping it disables external staging).

**TRUST-MODEL HARDENING — MANDATORY (agy R3; the safety of the whole feature hinges on ALL FOUR):**
1. **Canonical `Path(working_dir).resolve()` BEFORE `_target_is_self()` / any bind** — kills `..` path-traversal AND symlink
   escape (a `/tmp/external→JanusMaskJR` symlink would otherwise read as "external" while file ops resolve into self).
2. **REJECT at the trusted load/stamp stage** any `working_dir` resolving inside `state/`, inside `agent_workroot()`, or inside
   `PROJECT_ROOT` (unless exactly `== PROJECT_ROOT`, an explicit self-build) — prevents clobbering approvals/decisions/session state.
3. **STRIP the LLM-authored `working_dir`** at the daemon stamp seam (seam 3) — without it the untrusted planner injects
   `working_dir`, staging copies it verbatim, the worker runs RELAXED external policy while code still targets the self-repo →
   self-modification without the strict gates. This is the core trust-fork rationale.
4. **FAIL-SAFE-TO-SELF** — if `working_dir` resolution fails (missing path / permission / symlink loop), `_target_is_self()`
   returns **True** (enforce self-build gates, fail-CLOSED to self).
Ship `_target_is_self()` unit tests for traversal/symlink/state-escape/parent-chain BEFORE wiring any G2 relax.

**G2 — AST-rule stay-self/relax-external split [owner decision; OVERSEER RECOMMENDATION]:** the relax MUST thread into BOTH
independent AST engines (agy R3 CONFIRMED both present) — `harness/ast_enforcer.py::validate_code` (submit/commit gate) AND
`services/neurosymbolic/ast_verifier.py::ASTVerifier` (production interceptor) — or the submit⊆commit / interceptor⊆gate parity
(F2 invariant) breaks. **Overseer recommendation (a THREE-way split, not two — from the owner conversation):**
- **STRICT for ALL targets:** `credential_leak`/`security` (never write a secret anywhere) AND **`nondeterminism`** — because the
  nondeterminism rule (`random`/`uuid`/`time.time()`/`datetime.now()`/`os.urandom()`) exists to keep JanusMask's *own verification
  reproducible* (it re-runs the test/mutation command in throwaway copies and needs deterministic pass/fail). That logic applies to
  ANY target JM verifies, self or external — it is NOT a self-protection rule, so it should NOT relax for external.
- **RELAX for external only:** `eval`/`exec`/`__import__`, `os_system`, `bare_except` — legitimate constructs in arbitrary external
  codebases; keeping them strict makes JM refuse valid patches for real projects. (`subprocess_no_check` is already only a warning.)
- Key the toggle on `_target_is_self()`; a `config.yaml` toggle is fine but the relaxed-value injection must be in CODE (the §4
  pin keeps `verify_extra_ro/rw` empty in config).

**G3 — target-`.venv` binding (atomic with B3):** all execute-target stages must bind the TARGET interpreter, not JM's — the 4
verify spawns (`orchestrator.py:1846/1971/1995/2009`, `extra_ro=[sys.base_prefix,sys.prefix]`), the embedded runner, the
differential-fuzzer sandbox, the oracle/mutation gate. Add `<working_dir>/.venv` prefix/bin to `extra_ro` + jailed PATH, injected
in CODE from `task.working_dir`. **COORDINATION:** those 4 verify lines now ALSO carry the SEC-1c proxy wrap — any G3/T3 edit there
must be landed coordinated with the existing wrap to avoid re-tripping the symbol-drift guard.

**Bootstrap (REV18 §3B-B):** new `harness/target_bootstrap.py` (git init/.gitignore/initial commit/`.venv`+deps/staging worktree) +
one-time `bootstrap_target()` at daemon startup (gate-bearing). Idempotent on a recorded marker; refuse/warn on a dirty external tree.

**Sequencing [agy R4]:** §2 Phase-1 gate-ii closers FIRST → then §3: #6 `_target_is_self()`+trust hardening (security foundation,
PIPELINE) → seams 1/2/5 (PIPELINE) → seam 3/4+STRIP (hand-edit-likely, multi-site staging) → G2 split (both engines, hand-edit-likely
/ owner-confirm) → G3 venv+T2-T5 (hand-edit-likely, coincident with the SEC-1 verify lines) → G1 origination → validate against a real
external project under the sandbox → owner Phase A. **§3 is NOT a Phase-A blocker** and can proceed in parallel after #1–#5.

---

## 4. Invariants carried through EVERY phase (do-NOT) — per-file grep checklist (anchors re-verified @ `a2f35a4`)

- `grep -c "synthesis_success = True"` **==1** in EACH of `harness/orchestrator.py` (`:2427`) and `harness/orchestrator_worker.py` (`:310`).
- `grep -c "skip_interface_fuzz"` **==1** in EACH of `harness/planner/taxonomies.py`, `harness/orchestrator.py` (`:2438`),
  `harness/orchestrator_worker.py` (`:321`) (ONLY `test_authoring`); never narrow `BYPASS_FUZZER_TYPES`.
- `_SENSITIVE_APPLY_GLOBS == ('harness/**','config/**','scripts/**')` at `git_integration.py:16`.
- `verify_extra_ro`/`verify_extra_rw` ABSENT/empty in `harness/config.yaml`; `harness/config.yaml` byte-clean.
- **SEC-1 PARITY/wiring:** every `build_jail_argv(...)` execution site threads `dbus_proxy_socket=` (12 textual sites). Submit-time
  AST interceptor ⊆ commit-time enforcer (F2); any §3 G2 external relax MUST apply IDENTICALLY across submit/interceptor/commit
  (BOTH engines). The SEC-1 fail-open `→None` branches are being made fail-CLOSED in REV20 #1 — do not re-introduce a host-bus fallback.
- R-ANCHORED-PATCH: no-extras path byte-identical; extras only 1-part qualnames, bounded kinds, name-collision-rejected.
  WHOLE-FILE-DRIFT-GUARD: keep modified-existing-symbol intersection semantics.
- **agy is NOT tree-isolated** → after ANY agy run verify byte-identical + revert drift (esp. `git checkout HEAD -- harness/config.yaml`;
  rm stray oracle/test files agy drops into the MAIN tree via `--add-dir`).
- Never add `*_fix`/any `<task>_fix` to the allowlist. **`full_stop` PRESENT** (`state/control/autowork/full_stop` = `halted`) until
  owner-gated Phase A. §1b (`_apply_approval_granted`) is the autonomous-commit boundary; agents tree-isolated ONLY via the bwrap jail.
- **External-target safety (§3):** any self-build-gate bypass derives from the RESOLVED target via `_target_is_self()` (TO BE BUILT;
  3-clause; `.resolve()` first; fail-safe-to-self). The `working_dir` input MUST be `.resolve()`-normalized + REJECTED if resolving
  into `state/`/`agent_workroot()`/`PROJECT_ROOT`(≠self); LLM-authored `working_dir` STRIPPED before the trusted stamp.
  `JANUSMASK_PROJECT_DIR`/`PYTHONPATH` + `${PROJECT_ROOT}` config tokens STAY self.

---

## Appendix — anchors (re-verified @ `a2f35a4`; re-check before use)

- `harness/dbus_proxy.py`: `proxied_session_bus()`, `build_proxy_argv()` (`:46` = `[binary,'unix:path='+real,sock,'--filter','--talk=org.freedesktop.secrets']`), `_resolve_real_bus` (parses `unix:path=`; does NOT handle `unix:abstract=` — SEC-1-DBUSADDR).
- `harness/agent_jail.py`: `build_jail_argv` (`:65`); XDG region `:239-251` (`:248` binds proxy socket at `<xdg>/bus` when `dbus_proxy_socket is not None`, ELSE binds the REAL host bus — the fail-open hinge); `:95-97` deliberately does NOT unshare net/IPC (agy OAuth) — abstract-socket vector.
- `harness/orchestrator.py`: `_build_agent_env` (`:220`, allowlist landed; SEC-1-DBUSADDR override target); `spawn_agent` (`:331`, ExitStack proxy + `_dbus_stack`) + `kill_agent` (`:450`, closes stack); `_auto_commit_accepted` 4 wrapped verify sites `~:1867/1998/2028/2048`; `synthesis_success=True` `:2427`; `skip_interface_fuzz` `:2438`.
- `harness/autowork_daemon.py`: singleton proxy in `run_daemon` (`_SELFHEAL_DBUS_SOCKET` global, init ~:1609-1640, reap in shutdown finally); `_contain_selfheal` `:563` (`globals().get('_SELFHEAL_DBUS_SOCKET')` ~:605); `_escalate_to_autobrief` (`:608`, env allowlist), `_escalate_inactivity` (`:1905`, env allowlist); `main()` `--once` `:1723-1731` (bypasses run_daemon → DAEMON-ONCE-PROXY); `_maybe_push_and_rebase_pin` `:1479` (§3 T5); stage_task extract loop `:1103` (§3 seam 3); per-task retry/quarantine ~:757 (RUNAWAY-CEILING).
- §3 seams: `brief_loader.py:160` (`load_brief` :121; `REQUIRED_SECTIONS` :66), `blind_draft.py:122` (`run_blind_drafts` :118), `staging.py:16` (`stage_task`), `_decide_common.py:86` (`decide_submission` :80). Predicates greenfield: `paths.py:62` (2-clause GAP_H3 → extend to 3); `effective_target_root()` (build).
- G2 engines: `harness/ast_enforcer.py` (`validate_code`/`_ValidationVisitor`; rules: `nondeterminism` (random/uuid/time/datetime.now/os.urandom), `security`/credential_leak, `eval`/`exec`/`__import__`, `os_system`, `bare_except`, `subprocess_no_check`=warning) + `services/neurosymbolic/ast_verifier.py` (`ASTVerifier`/`_ASTVisitor`).
- `state/control/autowork/full_stop`: **PRESENT** (`halted`).
- Review reports: `~/janusmask_briefs/review_rev20/R{1..4}_*.md` (agy + Opus-cross-checked); auth gate: `~/janusmask_briefs/sec1c_spawn_authgate.py` (to be hardened — REV20 #3).
