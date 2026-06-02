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
> **Cadence (owner directive):** this plan was adversarially **Claude-reviewed (2026-06-01) in TWO rounds and AMENDED IN-PLACE**
> (uncommitted; corrections marked `[CLAUDE-REV …]` inline): round 1 = 5 reviewers (4 sub-agents + Opus overseer, 3/5-consensus);
> round 2 = 2 more adversarial reviewers re-analyzing every reported issue (7 total, **4/7-consensus** bar). Round 2 ELEVATED 8
> sub-threshold findings to applied (credential-exfil on the execute path, undefined external commit path, missing integration
> test, §3-vs-Phase-A gate contradiction, `services/**` ungated, abstract-socket bypass not fully "killed", bootstrap
> `--once`/dirty-tree) and CAUGHT one round-1 mis-correction (`scripts/impl_plan_to_queue.py` is a SEPARATE inline writer, not a
> `stage_task` chokepoint). It will be **executed the session AFTER**. The forward-looking findings below are marked
> **[agy R#; Opus-cross-checked]** — every flagged hole was independently CONFIRMED against code at HEAD `a2f35a4`.
> **Claude review found agy's "14 sites" was CORRECT (this plan's "→ really 12" was itself the error — there are 14
> textual `build_jail_argv` call sites); plus a cluster of stale §3 line anchors and several greenfield/scope
> under-specifications, all corrected below.**
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
   bound proxy socket) instead of allowlisting the host value through. **[CLAUDE-REV 7/7] This closes the bypass for
   env-respecting D-Bus clients (the realistic agy/keyring case) — it does NOT fully kill it: because the jail does not unshare
   net/IPC (`agent_jail.py:95-101`, required for OAuth under `--share-net`), a NON-cooperative process can still dial a host
   `unix:abstract=…` socket directly, ignoring the env var. A complete fix needs `--unshare-ipc`/net or a netns-scoped proxy
   (conflicts with the OAuth `--share-net` requirement → treat as residual, or pair with `--unshare-ipc` testing).** Small edit in
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
>   task source (REV18 §3B-C "biggest hole"); §3B-D's CONFIGURABLE brief source + a `working_dir` brief field is the
>   implementation. Build it as part of the §3 buildout. **[CLAUDE-REV §3] `working_dir` must be OPTIONAL, not "REQUIRED"**
>   (the seam-1 wording is the correct one) — absent ⇒ self-build, consistent with FAIL-SAFE-TO-SELF; a hard requirement breaks
>   `load_brief` for every existing in-repo brief. G1 must also (a) define the brief-source path resolution (the daemon's
>   hardcoded `repo_root.glob('brief_hooks_*.md')` at `brief_status.py:23` vs the webUI's `state/tasks/queued/*.md` at
>   `webui/app.py:771` are NOT reconciled), and (b) provide an authoring affordance for `working_dir` (e.g. a field in
>   `action_submit_brief`, `webui/app.py:759`, that injects it into the brief frontmatter) — the plan currently names no
>   authoring seam.
> - **G2 (AST-rule stay-self/relax-external split) — overseer RECOMMENDATION below; owner to confirm at Claude-review.**

**The 5 plumbing seams [agy R3 — all CONFIRMED accurate at `a2f35a4`]:** `working_dir` (distinct from `work_dir`) is 0× in
`harness/` today — every seam is GREENFIELD.
1. `harness/planner/brief_loader.py:160` (`load_brief` def `:121`) — the frontmatter normalize loop keeps only
   `REQUIRED_SECTIONS` (def `:66`); `working_dir` is silently dropped. **[CLAUDE-REV §3] NOT a one-line allowlist add:**
   `PlanningBrief` is a **`@dataclass(frozen=True)`** (`:26`) with exactly 8 fixed fields and no `working_dir`, so the
   edit is multi-point — (a) add `working_dir: str | None = None` to the frozen dataclass (`:26`), (b) add an
   `OPTIONAL_FIELDS` allowlist alongside `REQUIRED_SECTIONS` and keep `working_dir` in the normalize loop (`:159-161`),
   (c) pass it into the `return PlanningBrief(...)` construction (`:185`). **`working_dir` is OPTIONAL, NOT required**
   (the G1 wording "REQUIRED" is corrected — see G1): absent ⇒ self-build (consistent with FAIL-SAFE-TO-SELF). A hard
   requirement would break `load_brief` for every existing in-repo `brief_hooks_*.md` (all lack the field).
2. `harness/planner/blind_draft.py:122` (`run_blind_drafts` def `:118`) — the `json.dump({...})` serialization whitelist;
   `working_dir` MUST stay OUT of it (this feeds the untrusted planner — the trust-fork boundary). (`:128` was the old wrong anchor.)
3. **STAMP (trust fork) — NET-NEW DAEMON CODE:** `harness/autowork_daemon.py:1103` region (the `stage_task(plan_path,…)` extract
   loop, `unstaged = rec.get(...)` at `:1103`, `stage_task` call ~`:1113`) does NOT load the operator brief and has NO
   `working_dir` in scope → copies the LLM plan task VERBATIM. Trusted code must: (a) load `working_dir` from the operator brief,
   (b) **STRIP any LLM-authored `working_dir`** from the plan task, (c) stamp the trusted value.
   **[CLAUDE-REV §3] Implementation notes:** the brief path IS recoverable in this loop — `compute_brief_status` records carry
   `rec['brief_filename']` (`brief_status.py:71`), so call `load_brief(repo_root / rec['brief_filename'])` (reuse, do not re-parse)
   to get the validated `working_dir`. **This seam is BLOCKED-ON seam 1** (the value does not exist on `PlanningBrief` until
   seam 1 lands). The "CONFIGURABLE brief source" (G1) collides with the **hardcoded `repo_root.glob('brief_hooks_*.md')`**
   (`brief_status.py:23`, also the daemon mtime scan) — G1 must define the brief-source resolution, not assume the repo-root glob.
   **Alternative trusted stamp point to evaluate:** `harness/planner/cli.py::persist_plan` (`:86`, called `:190`) already holds
   the trusted `brief_obj` and writes the `plan_hooks_*.json` that `stage_task` later reads — stamping/stripping there (once per
   plan, in the trusted producer) may be cleaner than a per-task daemon re-reader. Decide one or the other; do not split.
4. `harness/planner/staging.py:16` (`def stage_task(plan_path, task_id, state_dir, canonical=True)`) — dumps the task dict
   verbatim (`json.dumps(task)`) with NO key-stripping/extra-field schema validation. **[CLAUDE-REV §3] "carry the stamped
   value here" is INERT as written:** `stage_task` has no `working_dir` param and no brief access — it copies the dict verbatim.
   **[CLAUDE-REV 7/7 — corrects the earlier "single chokepoint" claim, caught by re-review]:** `stage_task` is the chokepoint for
   the **daemon path only** (`autowork_daemon.py:1113`). It is NOT the only writer: **`scripts/impl_plan_to_queue.py:56` is a
   SEPARATE inline writer** (`out.write_text(json.dumps(task,…))`) that `staging.py` was lifted FROM and "mirrors exactly" but does
   NOT call — they have drifted-by-design into TWO independent writers. Therefore the **STRIP/validate must be enforced IN
   `stage_task`** (add a trusted `working_dir` param + reject/strip any task-dict `working_dir` not arriving via that param) **AND
   independently in the script's inline writer** (`scripts/impl_plan_to_queue.py:56`), or made single by having the script call
   `stage_task`. Stamping only at the daemon `:1103` loop leaves both the script writer and the re-stage paths able to re-admit an
   LLM-authored `working_dir`. This makes trust-rule #3 unconditional. (See trust-hardening rule #3.)
5. `harness/hooks/_decide_common.py:86` (`decide_submission` def `:80`, `task = _paths.load_inbox_task(...)` at `:86`) — read
   the working_dir to decide self-build-gate relaxation. **[CLAUDE-REV §3] `task` is a DICT** (accessed via `.get()` elsewhere
   in this fn, e.g. `:87/:95/:98`), so it is **`task.get('working_dir')`**, NOT attribute access — and it MUST be the trusted
   **STAMPED** value (seam 3/4 output), with `_target_is_self()` fail-safe-to-self when absent/None. This hook runs in the jailed
   worker context, so `_target_is_self()` must be importable/reachable there (verify `paths.py`/PYTHONPATH reachability); never
   recompute target-trust from any LLM-controlled field.

**Predicates TO BE BUILT (agy R3 — confirmed greenfield):**
- **`_target_is_self()` — DOES NOT EXIST** (only the unrelated module-name `oracle_attach.py:30 _target_is_self_modification`).
  **[CLAUDE-REV §3] Build as a SEPARATE NEW bool predicate — do NOT extend the `paths.py:62` guard in place.** That guard lives
  INSIDE `agent_workroot()`, governs the `JANUSMASK_AGENT_WORKROOT` env override, and **RAISES `ValueError`** (fail-CLOSED by
  aborting the spawn) — the opposite return contract from `_target_is_self()`, which must return a **bool and FAIL-SAFE-TO-SELF
  (return True)** on any resolution error. Reusing/extending that raise-guard would import raise-semantics where return-semantics
  are required and would also mutate `agent_workroot`'s behavior (3 tests assert it). Borrow the boundary *logic* only:
  `Path(working_dir).resolve()` FIRST, then `resolved == PROJECT_ROOT` ⇒ self. The **PARENT-of-repo case
  (`resolved in PROJECT_ROOT.parents`) must be REJECTED at the trusted load/stamp stage** (trust-rule #2 — binding a directory
  that CONTAINS the live repo exposes it); if it ever reaches the predicate, classify as self (fail-closed), NOT as a relaxable
  external target.
- **`effective_target_root()` — DOES NOT EXIST.** Build (same bool/fail-safe-to-self discipline; returns `PROJECT_ROOT` when self).

**Re-key T2–T5 onto `task.working_dir`**, gated by `_target_is_self()`: T2 = §1b decision; T3 = re-route the verify/synth spawns;
T4 = `agent_workroot()` writer + the 3 external readers follow the target while `JANUSMASK_PROJECT_DIR`/`PYTHONPATH` STAY self;
T5 = no-op ONLY `_maybe_push_and_rebase_pin` (`autowork_daemon.py:1489`), NOT `_auto_promote`'s whole body (it is the generic
staging engine — no-oping it disables external staging).

**[CLAUDE-REV §3] T3 is the largest/most-anchor-wrong item — the real control points (verified @ working tree):**
- **The staging-root derivation itself:** `orchestrator.py:1764` does `git rev-parse --show-toplevel` with `cwd=state_dir.parent`
  → resolves to the **JM repo**, then `staging_path = worktree_root.parent / f"{worktree_root.name}_{task_id}_staging"` (`:1774`).
  For an external target this whole derivation must be re-rooted at `effective_target_root()` (NOT a constant swap). This is THE
  controlling T3 site and was unnamed.
- **The 4 verify spawns are at `orchestrator.py:1912/1916, 2043/2047, 2073/2077, 2093/2097`** (the plan's `1846/1971/1995/2009`
  is wrong). Each "spawn" is a **try/except fail-open PAIR** (proxy `dbus_proxy_socket=_sock` branch + fail-open `=None` branch) =
  **8 textual `build_jail_argv` lines**, all carrying `repo_root=worktree_root, extra_ro=[sys.base_prefix, sys.prefix]`.
- **The synthesis spawn `repo_root=PROJECT_DIR` at `orchestrator.py:385`** (`spawn_agent`) — the jail RW root the synthesis agent
  WRITES into. For external work this MUST follow `effective_target_root()` (the agent must edit the TARGET, not self), while
  `JANUSMASK_PROJECT_DIR`/`PYTHONPATH` env STAY self (T4). Distinguish the jail `repo_root` binds (move) from the harness
  self-anchors (stay) explicitly — the plan conflates them. **[CLAUDE-REV 7/7] Both the moving `repo_root` (`:385`) and the
  staying env `JANUSMASK_PROJECT_DIR` (`_build_agent_env:283`) derive from the SAME module-level `PROJECT_DIR` symbol** — the
  retarget must change the `repo_root` use WITHOUT touching the env use, so edit the two call sites independently, do not rebind
  the shared constant.
- **The embedded test runner** `harness/embedded_test_runner.py` (`build_jail_argv` at `:173`/`:219`) imports `PROJECT_ROOT`
  directly (`:115`) as `repo_root` + binds `sys.base_prefix/sys.prefix`. On the accept path (`orchestrator.py:2450`) it would run
  external tests against the wrong repo/interpreter. `run_embedded_tests` needs a target-root/venv arg threaded from `working_dir`
  — a signature change, parallel to the synth sites. ADD it to the T3/G3 edit list (it is only in G3 prose today, not enumerated).
- **COORDINATION:** those 8 verify lines are simultaneously touched by REV20 **#1** (fail-CLOSE the `=None` branch), **#2**
  (DBUSADDR override in `_build_agent_env`, which T3/T4 env work also edits), and **G3** (`extra_ro` venv + `repo_root` retarget).
  Land #1/#2 FIRST, then author G3/T3 against the post-#1 shape — do NOT write them against the current fail-open shape.

**TRUST-MODEL HARDENING — MANDATORY (agy R3; the safety of the whole feature hinges on ALL FOUR):**
1. **Canonical `Path(working_dir).resolve()` BEFORE `_target_is_self()` / any bind** — kills `..` path-traversal AND symlink
   escape (a `/tmp/external→JanusMaskJR` symlink would otherwise read as "external" while file ops resolve into self).
2. **REJECT at the trusted load/stamp stage** any `working_dir` resolving inside `state/`, inside `agent_workroot()`, or inside
   `PROJECT_ROOT` (unless exactly `== PROJECT_ROOT`, an explicit self-build) — prevents clobbering approvals/decisions/session state.
3. **STRIP the LLM-authored `working_dir`** — without it the untrusted planner injects `working_dir`, staging copies it verbatim,
   the worker runs RELAXED external policy while code still targets the self-repo → self-modification without the strict gates.
   This is the core trust-fork rationale. **[CLAUDE-REV §3, amended 7/7] Enforce the STRIP at `staging.py::stage_task` (the daemon
   path's writer) AND at the separate inline writer `scripts/impl_plan_to_queue.py:56` (a drifted copy that does NOT call
   `stage_task`), NOT only at the daemon `:1103` extract loop.** Stamping only at the daemon loop leaves the script writer and any
   re-stage path able to re-admit an LLM-authored value. NOTE: excluding `working_dir` from the
   `blind_draft.py:122` json.dump whitelist (seam 2) does NOT hide it from the planner — `blind_draft.py:135` embeds
   `brief.raw_text` (incl. frontmatter) into the planner prompt verbatim, so the planner can read and echo it; that is precisely
   why this load-bearing STRIP is mandatory.
4. **FAIL-SAFE-TO-SELF** — if `working_dir` resolution fails (missing path / permission / symlink loop), `_target_is_self()`
   returns **True** (enforce self-build gates, fail-CLOSED to self).
5. **[CLAUDE-REV 7/7 — NEW MANDATORY RULE] CREDENTIAL EXFIL ON THE EXECUTE PATH.** The jail is explicitly "a write boundary, NOT
   an exfil boundary" (`agent_jail.py` docstring `:39-42`): it binds `~/.gemini` and `~/.claude` **read-WRITE** (`:150-153`,
   `.claude/.credentials.json` readable per `:172`) and deliberately does NOT unshare net/IPC (`:95-101`, OAuth needs
   `--share-net`). The verify/test/mutation spawns run untrusted planner-authored — and, for §3, **EXTERNAL-repo** — code in that
   same jail, and that execute path does NOT route through the AST submit interceptor at all (it is `/bin/bash -c` via
   `subprocess.run`), so NOTHING stops external code from reading `~/.gemini/oauth_creds.json` / `~/.claude/.credentials.json` and
   exfiltrating over the shared network. **Mitigation (scope to the EXECUTE path only — the synthesis spawn still needs the OAuth
   binds): on the external verify/test/mutation spawns, do NOT bind `~/.gemini`/`~/.claude`, and/or run them `--unshare-net`.**
   This is arguably the single largest §3 hole; the four path-rules above stop at path-resolution and never reach code-execution.
6. **[CLAUDE-REV 7/7] `services/**` IS NOT GATED.** `_SENSITIVE_APPLY_GLOBS == ('harness/**','config/**','scripts/**')`
   (`git_integration.py:16`); `_enforce_apply_scope` (`:43-77`) gates only those three. So a self-path patch touching
   **`services/**` — including `services/neurosymbolic/ast_verifier.py`, the live interceptor engine itself — bypasses the
   `harness_self_fix`+approval gate today, pre-§3.** The G2 external relax widens this blast radius. **Recommend adding
   `services/**` to `_SENSITIVE_APPLY_GLOBS`** (independent of §3, but mandatory before any G2 relax — else a relaxed task can
   rewrite the very engine that enforces the relax).
Ship `_target_is_self()` unit tests for traversal/symlink/state-escape/parent-chain BEFORE wiring any G2 relax.
**[CLAUDE-REV 7/7] Also ship an EXTERNAL-MODE INTEGRATION TEST as a gating deliverable** (the current §3 close — "validate against
a real external project" — is a single hand-wavy line). It must use a throwaway fixture external repo and assert end-to-end:
(a) external relax applies; (b) a self-target (`working_dir==self`) KEEPS strict gates; (c) a malicious `working_dir` (resolving
into `state/`/`agent_workroot()`/parent-of-repo/symlink) is REJECTED end-to-end; (d) the TARGET `.venv` is the interpreter used;
(e) `_target_is_self()` is importable INSIDE the jailed worker hook and fails-safe-to-self when import/resolution fails there
(the predicate's jail-reachability is the security hinge for seam 5 and must be tested, not left a "verify" TODO).

**G2 — AST-rule stay-self/relax-external split [owner decision; OVERSEER RECOMMENDATION]:** the relax must thread into BOTH
independent AST engines — `harness/ast_enforcer.py::validate_code` (submit/commit gate) AND
`services/neurosymbolic/ast_verifier.py::ASTVerifier` (production interceptor; LIVE via `harness/interceptors.py:53`/`:159` —
confirmed, NOT test-only) — or the submit⊆commit / interceptor⊆gate parity (F2 invariant) breaks.

> **[CLAUDE-REV §3 — FACTUAL CORRECTION, the plan's "R3 CONFIRMED both present [share these rules]" is FALSE]:** the two engines
> do **NOT** share a rule set or severities (verified @ working tree). Before any relax can be threaded, the taxonomy must be
> mapped per-engine, because the relaxable rules **differ**:
> - **`ast_enforcer.py` (the submit/commit gate):** `nondeterminism`=**ERROR** (random/uuid imports + time/datetime.now/os.urandom
>   calls, gated by `allow_nondeterminism`), `security`=**ERROR**, `os_system`=ERROR, `bare_except`=ERROR, `subprocess_no_check`/
>   `side_effect`/`unbounded_recursion`=warning. **`eval`/`exec`/`__import__` AND hardcoded-credentials are the SAME rule name
>   `security`** (lines 72, 79, 86) — so you CANNOT relax eval/exec by suppressing the `security` rule without ALSO relaxing
>   credential detection. The eval/exec relax MUST be a NEW targeted sub-flag on the dangerous-call branch only.
> - **`services/neurosymbolic/ast_verifier.py` (the interceptor):** `non_determinism`=**WARNING** (time/uuid; severity differs
>   from the enforcer's ERROR), `os_system`=ERROR (its ONLY non-syntax ERROR), `bare_except`=ERROR-if-`:pass`-else-WARNING,
>   `credential_leak`=WARNING (string-literal regex, NOT variable-name), `subprocess_no_check`/`dangerous_shell`=WARNING.
>   **It has NO `eval`/`exec`/`__import__` rule at all** → the eval/exec external relax is a NO-OP in the interceptor; it only
>   matters at submit/commit. "STRICT nondeterminism for all" must also reconcile against the interceptor's WARNING severity.
> - **The interceptor has NO relax seam:** `ASTVerifier.verify(code, filename)` takes no policy arg, and `interceptors.py:53`
>   calls `ASTVerifier().verify(code)` with NO task/`working_dir` context. Threading a per-target relax requires NET-NEW plumbing:
>   a relax param on `verify()` AND a way to get the active task's resolved `working_dir` into the interceptor (mirror
>   `BashSafetyInterceptor`'s `JANUSMASK_PROJECT_DIR` env read at `interceptors.py:96`). The enforcer's `validate_code` likewise
>   needs a new `relax_external_constructs` param (today it only has `allow_nondeterminism`/`declared_signature`).

**Overseer recommendation (a THREE-way split, not two — from the owner conversation):**
- **STRICT for ALL targets:** `credential_leak`/`security` (never write a secret anywhere) AND **`nondeterminism`** — the
  nondeterminism rule exists to keep JanusMask's *own verification reproducible* (it re-runs the test/mutation command in throwaway
  copies and needs deterministic pass/fail); that applies to ANY target JM verifies, self or external. **[CLAUDE-REV §3 CAVEAT]
  nondeterminism is ALREADY relaxable per-task** via `allow_nondeterminism` (`ast_enforcer.py:187`, fed by `_decide_common.py:98-102`
  from `task.constraints.deterministic is False` / `io_adapter` / `logging_observability` / `test_*`). So "STRICT for all targets"
  means: do NOT add `_target_is_self()` as a NEW relax key for nondeterminism (leave the existing per-task path intact). If external
  *verification reproducibility* must be guaranteed regardless of what the task declares, the external path must instead **FORCE
  `allow_nondeterminism=False`** (ignore the task-supplied `deterministic` flag) — keying on target-self alone is insufficient
  because the planner can already set `deterministic=False`.
- **RELAX for external only:** `eval`/`exec`/`__import__`, `os_system`, `bare_except` — legitimate constructs in arbitrary external
  codebases; keeping them strict makes JM refuse valid patches for real projects. (`subprocess_no_check` is already only a warning.)
- Key the toggle on `_target_is_self()`; a `config.yaml` toggle is fine but the relaxed-value injection must be in CODE (the §4
  pin keeps `verify_extra_ro/rw` empty in config).

**G3 — target-`.venv` binding (atomic with B3):** all execute-target stages must bind the TARGET interpreter, not JM's — the 4
verify spawns (`orchestrator.py:1912/1916, 2043/2047, 2073/2077, 2093/2097` — 8 fail-open-pair lines, `extra_ro=[sys.base_prefix,
sys.prefix]`), the embedded runner (`embedded_test_runner.py:173/:219`), the differential-fuzzer sandbox
(`narrow_fuzz/validation.py:284`), the oracle/mutation gate. Add `<working_dir>/.venv` prefix/bin to `extra_ro` + jailed PATH,
injected in CODE from `task.working_dir`. **[CLAUDE-REV §3] the `.venv` term must be a SEPARATE code-injected list concatenated
alongside the existing `+ list(verify_extra_ro)` — NOT added to `verify_extra_ro` in config** (the §4 pin keeps that empty).
**COORDINATION:** those 8 verify lines ALSO carry the SEC-1c proxy wrap AND are edited by REV20 #1 (fail-close) + #2 (DBUSADDR) —
see the T3 coordination note above; land #1/#2 first, then G3/T3 on the post-#1 shape to avoid re-tripping the symbol-drift guard.

**Bootstrap (REV18 §3B-B):** new `harness/target_bootstrap.py` (git init/.gitignore/initial commit/`.venv`+deps/staging worktree) +
one-time `bootstrap_target()` (gate-bearing). Idempotent on a recorded marker. **[CLAUDE-REV 7/7] (a) Placement:** NOT "at daemon
startup" — the `--once`/`--dry-run` supervised paths call `_iteration` directly and return BEFORE `run_daemon` (`autowork_daemon.py:1718-1731`),
so a startup-only bootstrap is skipped on `--once` → un-bootstrapped external tree. Place it where BOTH `run_daemon` AND the
`--once`/`_iteration` path reach it (mirror the DAEMON-ONCE-PROXY fix #4). **(b) Dirty tree:** REFUSE by default (not "warn" —
warn = proceed = clobber); `.resolve()` the target BEFORE the marker check (symlinked-marker defeats idempotency); never
`git init`/commit into a directory it did not create or that already contains a `.git` it does not own (ownership check).

**[CLAUDE-REV 7/7] External commit/promotion path — UNDEFINED, must be specified:** §3 bootstraps an external target and re-roots
the verify/staging machinery (T3) but never says how ACCEPTED patches get committed/promoted INTO the external repo. The current
landing path is self-specific: `_SENSITIVE_APPLY_GLOBS` (`git_integration.py:16`) and the §1b autonomous-commit boundary are
JM-repo-relative. Add an item defining: where external commits land (the target repo, never JM's HEAD — T5 makes the JM push a
no-op but does NOT define the external commit), whether/how the sensitive-glob apply gate applies for external targets, and where
the §1b approval boundary sits for external work. Without this, accepted external output has no defined landing path.

**Sequencing [agy R4]:** §2 Phase-1 gate-ii closers FIRST → then §3: #6 `_target_is_self()`+trust hardening (security foundation,
PIPELINE) → seams 1/2/5 (PIPELINE) → seam 3/4+STRIP (hand-edit-likely, multi-site staging) → G2 split (both engines, hand-edit-likely
/ owner-confirm) → G3 venv+T2-T5 (hand-edit-likely, coincident with the SEC-1 verify lines) → G1 origination + external commit/promotion
→ external-mode integration test (gating) → owner Phase A. **[CLAUDE-REV 7/7] §3 is not a *task-ordering* blocker for Phase A, BUT it
is NOT safely "parallel" either: §3 RELAXES the AST gates (G2) and adds the `_target_is_self()` bypass predicate — the very gates
Phase A's 8-point owner review inspects, and which §4 folds into the per-phase invariants. So: if any §3 gate-relax lands BEFORE
Phase A, the 8-point review MUST be re-run against the post-§3 gate shape; do not treat §3 as inert background work during Phase A
go/no-go.**

---

## 4. Invariants carried through EVERY phase (do-NOT) — per-file grep checklist (anchors re-verified @ `a2f35a4`)

- `grep -c "synthesis_success = True"` **==1** in EACH of `harness/orchestrator.py` (`:2427`) and `harness/orchestrator_worker.py` (`:310`).
- `grep -c "skip_interface_fuzz"` **==1** in EACH of `harness/planner/taxonomies.py`, `harness/orchestrator.py` (`:2438`),
  `harness/orchestrator_worker.py` (`:321`) (ONLY `test_authoring`); never narrow `BYPASS_FUZZER_TYPES`.
- `_SENSITIVE_APPLY_GLOBS == ('harness/**','config/**','scripts/**')` at `git_integration.py:16`.
- `verify_extra_ro`/`verify_extra_rw` ABSENT/empty in `harness/config.yaml`; `harness/config.yaml` byte-clean.
- **SEC-1 PARITY/wiring:** every `build_jail_argv(...)` execution site threads `dbus_proxy_socket=` (**14 textual sites** —
  [CLAUDE-REV] verified: orchestrator `:385`+8 verify lines `1912/1916/2043/2047/2073/2077/2093/2097`, autowork_daemon `:609`,
  embedded `:173/:219`, sandbox_smoke `:134`, narrow_fuzz/validation `:284`). Submit-time
  AST interceptor ⊆ commit-time enforcer (F2); any §3 G2 external relax MUST apply IDENTICALLY across submit/interceptor/commit
  (BOTH engines). The SEC-1 fail-open `→None` branches are being made fail-CLOSED in REV20 #1 — do not re-introduce a host-bus fallback.
- R-ANCHORED-PATCH: no-extras path byte-identical; extras only 1-part qualnames, bounded kinds, name-collision-rejected.
  WHOLE-FILE-DRIFT-GUARD: keep modified-existing-symbol intersection semantics.
- **agy is NOT tree-isolated** → after ANY agy run verify byte-identical + revert drift (esp. `git checkout HEAD -- harness/config.yaml`;
  rm stray oracle/test files agy drops into the MAIN tree via `--add-dir`).
- Never add `*_fix`/any `<task>_fix` to the allowlist. **`full_stop` PRESENT** (`state/control/autowork/full_stop` = `halted`) until
  owner-gated Phase A. §1b (`_apply_approval_granted`) is the autonomous-commit boundary; agents tree-isolated ONLY via the bwrap jail.
- **External-target safety (§3):** any self-build-gate bypass derives from the RESOLVED target via `_target_is_self()` (TO BE BUILT
  as a SEPARATE bool predicate that FAILS-SAFE-TO-SELF=True — NOT an in-place extension of the `paths.py:62` raise-guard, which has
  the opposite return contract; `.resolve()` first; parent-of-repo ⇒ reject/treat-as-self). The `working_dir` input MUST be
  `.resolve()`-normalized + REJECTED if resolving into `state/`/`agent_workroot()`/`PROJECT_ROOT`(≠self); LLM-authored `working_dir`
  STRIPPED at the `staging.py::stage_task` chokepoint before the trusted stamp.
  `JANUSMASK_PROJECT_DIR`/`PYTHONPATH` + `${PROJECT_ROOT}` config tokens STAY self.

---

## Appendix — anchors (re-verified @ `a2f35a4`; re-check before use)

- `harness/dbus_proxy.py`: `proxied_session_bus()`, `build_proxy_argv()` (`:46` = `[binary,'unix:path='+real,sock,'--filter','--talk=org.freedesktop.secrets']`), `_resolve_real_bus` (parses `unix:path=`; does NOT handle `unix:abstract=` — SEC-1-DBUSADDR).
- `harness/agent_jail.py`: `build_jail_argv` (`:65`); XDG region `:239-251` (`:248` binds proxy socket at `<xdg>/bus` when `dbus_proxy_socket is not None`, ELSE binds the REAL host bus — the fail-open hinge); `:95-97` deliberately does NOT unshare net/IPC (agy OAuth) — abstract-socket vector.
- `harness/orchestrator.py`: `_build_agent_env` (`:220`, allowlist landed; SEC-1-DBUSADDR override target); `spawn_agent` (`:331`; synthesis jail `build_jail_argv(..., repo_root=PROJECT_DIR, dbus_proxy_socket=_dbus_sock)` at **`:385`** — §3 T3 retarget site) + `kill_agent` (`:450`, closes stack); `_auto_commit_accepted` **4 verify spawns = 8 fail-open-pair lines at `1912/1916, 2043/2047, 2073/2077, 2093/2097`** ([CLAUDE-REV] the prior `~:1867/1998/2028/2048` was wrong); `synthesis_success=True` `:2427`; `skip_interface_fuzz` `:2438`.
- `harness/autowork_daemon.py`: singleton proxy in `run_daemon` (`_SELFHEAL_DBUS_SOCKET` global, init ~:1609-1640, reap in shutdown finally); `_contain_selfheal` `:563` (`globals().get('_SELFHEAL_DBUS_SOCKET')` ~:605); `_escalate_to_autobrief` (def **`:613`**, env allowlist), `_escalate_inactivity` (def **`:1824`**, env allowlist) ([CLAUDE-REV] prior `:608`/`:1905` were wrong); `main()` `--once` `:1723-1731` (bypasses run_daemon → DAEMON-ONCE-PROXY); `_maybe_push_and_rebase_pin` **`:1489`** ([CLAUDE-REV] prior `:1479` was wrong) (§3 T5); stage_task extract loop `:1103` (§3 seam 3); per-task retry/quarantine ~:757 (RUNAWAY-CEILING).
- §3 seams: `brief_loader.py:160` (`load_brief` :121; `REQUIRED_SECTIONS` :66), `blind_draft.py:122` (`run_blind_drafts` :118), `staging.py:16` (`stage_task`), `_decide_common.py:86` (`decide_submission` :80). Predicates greenfield: `paths.py:62` (2-clause GAP_H3 → extend to 3); `effective_target_root()` (build).
- G2 engines [CLAUDE-REV — the two are NOT rule-symmetric; map per-engine before threading any relax]:
  - `harness/ast_enforcer.py` (`validate_code(code,*,allow_nondeterminism=False,declared_signature=None)` `:187` / `_ValidationVisitor`): `nondeterminism`=ERROR (random/uuid imports + time/datetime.now/os.urandom calls; gated by `allow_nondeterminism`), **`security`=ERROR covers BOTH `eval`/`exec`/`__import__` (`:72`) AND hardcoded-credentials (`:79`/`:86`) under one rule name**, `os_system`=ERROR, `bare_except`=ERROR, `subprocess_no_check`/`side_effect`/`unbounded_recursion`=warning. No per-rule relax knob exists except `allow_nondeterminism` → eval/exec relax needs a NEW targeted sub-flag (not `security` suppression).
  - `services/neurosymbolic/ast_verifier.py` (`ASTVerifier.verify(code,filename)` `:229` / `_ASTVisitor`; LIVE via `harness/interceptors.py:53`/`:159`): `non_determinism`=**WARNING** (time/uuid), `os_system`=ERROR (only non-syntax ERROR), `bare_except`=ERROR-if-`:pass`-else-WARNING, `credential_leak`=WARNING (string-literal regex), `subprocess_no_check`/`dangerous_shell`=WARNING. **NO `eval`/`exec`/`__import__` rule** + **no relax param / no task context** → relax needs net-new plumbing (see G2).
- `state/control/autowork/full_stop`: **PRESENT** (`halted`).
- Review reports: `~/janusmask_briefs/review_rev20/R{1..4}_*.md` (agy + Opus-cross-checked); auth gate: `~/janusmask_briefs/sec1c_spawn_authgate.py` (to be hardened — REV20 #3).
