# JanusMaskJR — Continuation Plan (2026-06-01, rev 19)

> **rev 19 — written after the full REV18 §3 pipeline scope was EXECUTED this session (7 dual-agent pipeline
> landings, master `4f6406e..cf3811f`, all PUSHED to `origin/master`) and then adversarially re-reviewed by a
> 4-agent Antigravity/Gemini (`agy`) panel (reports in `~/janusmask_briefs/review_rev19/R{1..4}_*.md`).**
> Supersedes `JANUSMASKJR_CONTINUATION_PLAN_REV18.md`. **Governing rule (owner directive, carried):** use the
> PIPELINE for every change wherever possible; HAND-EDIT only after a pipeline attempt FAILS with a
> permanent/structural blocker (never a timeout, never a re-groundable stale-ground-truth or mis-render).
>
> **Verification discipline:** the `agy` panel over-states / confabulates specifics (a known pattern — this round it
> hallucinated several oracle filenames, e.g. `test_daemon3a_path_alignment.py`/`test_rollbe_crash_safety.py` which do
> NOT exist; the real ones are `test_daemon_parallel_watchdog_pgid.py`/`test_rollbe_crash_terminal_oracle.py`). The §0
> landing audits below were **independently re-verified by the overseer this session** (AST scope checks + full suites)
> and agy's SOUND verdicts corroborate them. Forward-looking findings (§3/§3B) are marked **[agy R#; verify-first]** and
> the cited anchors were re-checked at HEAD `cf3811f` (accurate this round). **This plan will be adversarially
> re-reviewed by Claude agents next session; trust the forward verdicts only after that re-verification.**
>
> **Read this first (state):** last CODE commit = `cf3811f` (= code-state of `origin/master`); repo HEAD = `9ab8bac`
> (the REV19 plan-doc commit, non-code — `cf3811f` is its parent, tree byte-identical for all code anchors). The 7 REV18 §3 landings + their RED-first
> oracle commits are in history `4f6406e..cf3811f`. Hard invariants re-verified intact (§4): `synthesis_success =
> True` ×1 each in orchestrator.py / orchestrator_worker.py; `skip_interface_fuzz` ×1 each (taxonomies / orchestrator
> / worker, `test_authoring` only); `_SENSITIVE_APPLY_GLOBS == ('harness/**','config/**','scripts/**')`;
> `verify_extra_ro/rw` ABSENT in `harness/config.yaml`; `harness/config.yaml` byte-clean (no agy strip);
> **`full_stop` PRESENT**. Phase A (lift `full_stop`) remains **OWNER-ONLY**.

---

## 0. Landed this session — VERIFIED (do not re-do) — ALL VIA PIPELINE, 0 production hand-edits

Each item: a brief authored by `agy` (Gemini 3.5 Flash) inside a worktree-isolated Opus sub-agent that adversarially
reviewed/corrected it, proved the oracle RED on HEAD, and ran the FULL verification_command against fixed scratch to
pre-empt stale-existing-test traps + produce format-tolerant ground-truth alignments. Overseer ingested without
reading the brief: cp taskspec→`state/tasks/<ID>.json`, oracle(+aligned tests)→`tests/`, §1b
`state/control/decisions/<ID>.json` approve, commit oracle RED-first, run worker, Monitor, verify (AST scope + both
submissions + full suite + invariants + tree), push. agy panel R1/R2: **SOUND** (corroborates overseer verification).

| Commit | Item | Note (overseer-verified) |
|--------|------|--------------------------|
| `e9383f5` (oracle `0edae5c`, test-align `1e825e4`) | PARITY-3 | `services/neurosymbolic/ast_verifier.py` `_ASTVisitor.visit_Constant`: `credential_leak` severity ERROR→WARNING → submit ⊆ commit restored. Aligned existing `test_ast_verifier.py::test_credential_leak` (now asserts `valid` + WARNING). **First attempt `auto_commit_failed` from the stale existing test; re-dispatched after ground-truth align (NOT a permanent blocker).** services/, no §1b. |
| `87187d4` (oracle `aec501d`) | STAGING-RM-NOTIMEOUT | `git_integration.py::remove_staging_worktree`: 3-attempt retry + `timeout=60`/`timeout=30` on remove/prune/rev-parse; falls through to `shutil.rmtree(ignore_errors=True)`; no wall-clock sleep. §1b. |
| `87f6346` (oracle `038dbff`) | SELFHEAL-UNTRACKED-2 + STEM-COLLISION | `autowork_daemon.py` `_escalate_to_autobrief` (`:743`) + `_escalate_inactivity` (`:1822`): tracked, proc.pid-uniquified pidfile stem `selfheal_{agent}_{task_id}_{proc.pid}`. Aligned existing `test_selfheal_pidfile_tracked.py` (format-tolerant glob/startswith). §1b. |
| `598f90f` (oracle+align `126f666`) | DAEMON-3A (PGID + parallel watchdog + path-align) | `autowork_daemon.py`: `start_new_session=True` on parallel `_spawn_worker` (`:836`), parallel hung-worker mtime watchdog (1800s) in `_iteration`, running-path alignment to `_running_dir` in `suspend_parallel_workers`. Aligned `test_suspension_manager.py` + `test_antigravity_mode.py` (path move). §1b. |
| `1a03a65` (oracle `a21a9eb`) | DAEMON-3B STARTUP-ORPHAN | NEW helper `_resume_or_kill_orphaned_workers` (`:1528`, `os.kill(pid,0)` liveness + SIGCONT/SIGKILL, NOT waitpid) added **via R-ANCHORED extra** on the `run_daemon` symbol patch + startup call in `run_daemon`. **Landed VIA PIPELINE — refutes the plan's hand-edit anticipation.** §1b. |
| `6574892` (oracle `79b2ae9`) | ROLLB-D | `orchestrator.py::_auto_commit_accepted` (`:1473`) crash-safety: body wrapped so the staging worktree is always cleaned up on exception/early-exit. **Landed VIA PIPELINE despite the 613-line size (359+/342- restructure); comments NET-INCREASED (none stripped); only `_auto_commit_accepted` changed. Refutes "613-line = truncation = hand-edit".** Verified: oracle 3/3, full 16-file suite 157 passed. §1b. |
| `cf3811f` (oracle `6732f2a`) | ROLLB-E | `orchestrator_worker.py::main` finally orphan-guard (routes crash-after-claim `.processing` → `blocked/` `worker_crash_orphan`, +14ln) + `orchestrator.py::run_pipeline` per-iteration crash-safety (`pipeline_crash_orphan`). Multi-file via the `.patches.json` path (the `multi_file_missing_sidecar` warning was a red herring). Verified: oracle 2/2, broad 184-test regression green; orchestrator.py change scoped to ONLY `run_pipeline` (ROLLB-D preserved byte-identical). §1b. |

**Headline lesson:** the REV18 plan's "large-symbol / new-helper / 613-line → likely hand-edit" assumptions **ALL
FAILED** — the R-ANCHORED keystone (`eda9e27`) + capable dual agents made every item pipeline-viable. The dominant
real failure mode is **stale existing-test assertions** encoding OLD behavior (the `auto_commit_failed` cause on
PARITY-3) — always run the full verification_command (incl. existing tests) against fixed scratch and align stale
ground-truth before dispatch. Timeouts (DAEMON-3A timed out once: `1 of 2 futures unfinished`) and stale-test fails
are NOT permanent blockers → clean re-dispatch (`rm blocked/<ID>.json{,.retry.json}` + `<ID>.json.processing` +
`output/<ID>.*` + `sessions/*<ID>*` + `test_results/<ID>_baseline.json`; restore `state/tasks/<ID>.json`).

---

## 1. Daemon-enable gating + Phase A status (re-evaluated @ `cf3811f`)

- **(i) OWNER-SUPERVISED single foreground run:** minimal gating COMPLETE (unchanged from REV18).
- **(ii) UNMONITORED autonomous daemon — the daemon-STABILITY residual is now CLOSED** by this session
  (DAEMON-3A PGID + parallel watchdog, DAEMON-3B startup orphan sweep, SELFHEAL-2 stem-collision, STAGING-RM bounded
  removal, ROLLB-D/E crash-safety). **Remaining (ii) gates are SECURITY, not stability:** **SEC-1** (D-Bus/systemd
  escape — still LIVE at HEAD, agy R3 confirmed) and **SEC-ENV** (host-env leak into the jailed agent). **[agy R3, new;
  verify-first]** also consider a max-total-retries / runaway-loop ceiling for fully unattended operation.
- **Phase A itself (OWNER-ONLY, unchanged):** `pytest tests/adversarial/test_phase_a_selfheal_jail_writedenial.py
  -v`; confirm the bwrap-flip mutant → failures-not-skips; owner 8-pt review; then `rm
  state/control/autowork/full_stop`. **Do NOT lift `full_stop` until SEC-1 + SEC-ENV land** (agy R4 concurs:
  unattended autonomy without D-Bus + host-env isolation exposes the host to containment escape). **Do NOT automate.**

---

## 2. Ordered next steps — PIPELINE-FIRST

Same pipeline workflow as §0. Apply PATCH_CONVENTIONS (#8 MOOT post VALIDATOR-SIG). R-ANCHORED extras (1-part
qualname; Import/ImportFrom/Func/AsyncFunc/ClassDef only; comment-free bodies via ast.unparse; name-collision-
rejected) make new-helper additions pipeline-viable. Always include EVERY test that exercises a changed path in the
`verification_command`, and align stale existing tests as ground-truth (RED-first) before dispatch.

**Phase 1 — security hardening (the remaining (ii) gates; serialize; smoke-gated):**

1. **SEC-1 — D-Bus/systemd escape (HIGH; DEDICATED, partly hand-edit).** **Re-scoped this session: NOT a
   single-symbol patch.** `build_jail_argv` (`agent_jail.py:65`) is a pure argv transformer — it cannot own a proxy
   process lifecycle. Real fix:
   - **NEW module `harness/dbus_proxy.py`** — a context manager `proxied_session_bus()` that spawns `xdg-dbus-proxy
     --filter --talk=org.freedesktop.secrets` (keyring/auth preserved) blocking `org.freedesktop.systemd1`
     (StartTransientUnit), yields the filtered socket path, and reaps on exit. (`/usr/bin/xdg-dbus-proxy` installed.)
     New file → new-file commit route (PIPELINE-VIABLE).
   - **`build_jail_argv`** binds the PROXY socket at `<XDG>/bus` instead of the real bus (`agent_jail.py` ~`:245`).
     Single-symbol partial edit (PIPELINE-VIABLE).
   - **Wrap the 10 execution call sites** in the context manager (overseer re-verified the count = 10, incl.
     `sandbox_smoke.py:122` which the REV18 analysis missed): `orchestrator.py:347` (synth), `autowork_daemon.py:604`
     (daemon synth), `orchestrator.py:1846/1971/1995/2009` (verify/baseline/mutant-apply/mutant-verify),
     `embedded_test_runner.py:159/204`, `sandbox_smoke.py:122`, `narrow_fuzz/validation.py:257`. Multi-site wiring →
     **expect HAND-EDIT after a pipeline attempt** (the lifecycle wrapping spans many files; pipeline a few sites at a
     time if feasible, else hand-edit the mechanical wraps).
   - **Realign existing `tests/adversarial/test_h_jail_c_xdg_isolation.py:72`** (hard-asserts the real `<XDG>/bus` is
     RW-bound — contradicted by the fix) as RED-first ground truth.
   - **Acceptance oracle (PROVEN non-vacuous live this session):** jailed systemd1 call → `ServiceUnknown` (blocked)
     vs unfiltered control → `NoSuchUnit` (reachable); `secrets.Peer.Ping` → `()` (auth preserved). Ship as
     `tests/security/test_sec1_dbus_escape.py`.
   - **GATE:** after landing, run `~/janusmask_briefs/agy_jail_smoke.py` (agy auth) AND a claude auth smoke; **REVERT
     (`git reset --hard`) if either breaks.** The smoke is NECESSARY-BUT-INSUFFICIENT (calls live `build_jail_argv`
     with no sidecar hook, agy-only, OAuth may be cached) — also assert at the proxy-config level.
   - Pair **KEYRING-UNFILTERED** here (mock/throwaway keyring backend vs `--talk=secrets`; do not blindly block).

2. **SEC-ENV — host-env leak (MED; PIPELINE, agy-auth-risky, smoke-gated).** `_build_agent_env`
   (def `orchestrator.py:220`; the `{**os.environ, …}` leak is body line `:260`) copies the FULL operator env (GITHUB_TOKEN/cloud creds) into the
   jailed agent. Replace with an allowlist (`PATH,HOME,LANG,TERM,SHELL,USER,LOGNAME` + the agent's own auth vars +
   `JANUSMASK_*`); also scrub the self-heal spawns (`_escalate_to_autobrief`/`_escalate_inactivity` env build, and
   `_contain_selfheal`). Mostly single-symbol (PIPELINE-VIABLE). **MUST re-run agy+claude auth smoke after; REVERT if
   auth breaks.** Do jointly with / right after SEC-1 (shared smoke gate).

**Optional hardening (verify-first; only if a concrete need appears — do NOT over-engineer):**
- **[agy R3, new]** runaway-loop ceiling: a max total-retries threshold across tasks to bound resource-slot spinning
  under fully unattended daemon operation (the per-task retry budget already mitigates per-task). PIPELINE.
- WFDG-2 (drift-guard coverage limits), R-ANCHORED forward-ref ordering (insert extras after primary) — both LOW,
  defense-in-depth on rarely-used paths.

**Phase A (OWNER-ONLY):** see §1.

---

## 3. External-project capability restoration (§3B / §3B-D) — carried from REV18, anchors refreshed

> Owner-requested capability: run JanusMask autonomously INSIDE an EXTERNAL project, with the self-build gates active
> ONLY when the target IS the JanusMask repo. **§3B-D (brief-driven targeting) is the intended architecture**
> (supersedes the REV18 §3B env-var/T1 + COUPLING-INVARIANT + G1 "required add"); see REV18 §3B-D for the full design.
> agy R4 verdict: **CONCERNS — sound in intent, but NOT zero-plumbing.** Owner design decisions remain (G2). All
> PIPELINE-FIRST; the multi-seam plumbing is largely partial-edits + a stamp, viable via pipeline.

**The 5 plumbing seams [Claude-reviewed @ HEAD `9ab8bac`; anchors corrected]** — `working_dir` (distinct from
`work_dir`) appears 0× in `harness/` today; every seam is GREENFIELD (net-new code, not a re-point):
1. `harness/planner/brief_loader.py` — the DROP is the `if norm_k in REQUIRED_SECTIONS` frontmatter filter at **`:160`**
   (`:66` is the `REQUIRED_SECTIONS` set definition); add `working_dir` to an optional-fields allowlist there.
2. `PlanningBrief` struct + the explicit `json.dump({...})` serialization whitelist at **`harness/planner/blind_draft.py:122`**
   (NOT `:128`, which is the env-mode `for agent in [...]` loop) — carry `working_dir` on the struct, **but keep it OUT of
   this `brief.json` dict / the agent-facing prompt** (this serialization feeds the untrusted planning agent — the trust fork forbids round-tripping `working_dir` through it).
3. **STAMP (trust fork) — NET-NEW DAEMON CODE, not a re-point:** the brief's `working_dir` must be stamped onto each
   task JSON by trusted code. **The cited daemon anchor was WRONG: at `autowork_daemon.py:1103` (the `stage_task(plan_path, tid, …)`
   call; `:1093` is `unstaged = rec.get(...)`) the brief is NOT in scope** — the staging loop only has `rec` from
   `compute_brief_status` (which carries `slug`/task-id lists, NOT `working_dir`) and `plan_path` (the LLM-derived plan JSON).
   Implementing the fork requires: (a) NEW code to load `working_dir` from the operator brief (`brief_hooks_<slug>.md` frontmatter)
   inside the staging loop, (b) a NEW `stage_task` signature param to receive it, (c) the stamp write. **CRITICAL strip step (currently MISSING):**
   `stage_task` writes the task `json.dumps(task)` VERBATIM and `reconciliation.py:73/75` builds it via `copy.deepcopy(item.claude_task/gemini_task)`,
   so an LLM-injected `working_dir` would SURVIVE untouched — trusted code MUST explicitly STRIP any `working_dir` present in the
   LLM-authored task before stamping the brief value. `plan_validator.py` has no extra-field allowlist to do this today. (`blind_draft.py:146` `run_both_agents` spawns the planning agents.)
4. `stage_task` then carries the stamped value into `state/tasks/<id>.json`.
5. The submit hook (`harness/hooks/_decide_common.py:86`) + worker/binds read `task.working_dir`.

**Re-key T2–T5 onto `task.working_dir`.** **PREREQUISITE: the `_target_is_self()` 3-clause fail-safe predicate does
NOT EXIST yet** (grep-confirmed: only the unrelated, module-NAME-based, UNWIRED `oracle_attach.py:30
_target_is_self_modification` exists; the closest path code is the 2-clause raise-guard at `paths.py:62`). It must be
**authored as NEW code** (REV18 §3B design; extend `paths.py:62` to 3 clauses: `==PROJECT_ROOT` OR `PROJECT_ROOT in
root.parents` OR `root in PROJECT_ROOT.parents`; `.resolve()` first; fail-safe True on any error) and gates ALL of T2–T5.
- T2 = §1b decision from `task.working_dir`.
- **T3 is NOT a uniform "re-point the 10 sites":** the 4 verify spawns (`orchestrator.py:1846/1971/1995/2009`) already
  source `repo_root` from a self-derived **staging worktree** (`git rev-parse --show-toplevel` of `state_dir.parent`),
  so re-pointing them to an external target requires the staging/worktree machinery itself rooted at the target — not a
  constant swap. The 2 synth sites (`orchestrator.py:347` via `spawn_agent`, `autowork_daemon.py:604` via
  `_contain_selfheal`) have NO `task`/`working_dir` in scope → require signature plumbing. Add `embedded_test_runner` to
  the target. (SEC-1's proxy-wrap is an ORTHOGONAL axis at the same lines — see §2/G3 coordination note.)
- T4 = `agent_workroot()` writer + the **3 external readers** (`autowork_daemon.py:542-543`, `planner/blind_draft.py:32-33`,
  `scripts/impl_outbox_watcher.py:209/220`; the 4th `agent_workroot()` use is the internal `paths.py:75` composition) follow
  the target (`JANUSMASK_PROJECT_DIR`/`PYTHONPATH` STAY self). NOTE: `agent_workroot()` is hard-anchored on `PROJECT_ROOT`
  today — making it follow the target needs a new per-spawn override mechanism; specify it.
- **T5 = no-op ONLY `_maybe_push_and_rebase_pin`** (`autowork_daemon.py:1479`, called `:1627` — the origin-push + drift-pin
  rebase, the genuinely self-only machinery) when `not _target_is_self(working_dir)`. **Do NOT no-op `_auto_promote`'s whole
  body** — `_auto_promote` (`:1042`) is the GENERIC per-iteration staging engine (runs `_retry_blocked_tasks` `:1075` +
  the `stage_task` extract loop `:1086-1113`, incl. the seam-3 stamp); no-oping it for external targets would DISABLE
  external-task staging — the opposite of the goal. Gate only its self-specific sub-steps. Daemon `repo_root=cwd()` stays self.

**Owner design decisions + dependency-bearing-target work (orthogonal to §3B-D):**
- **G2 (owner) — AST-rule stay-self/relax-external split.** Decide which rules stay strict for all targets
  (`credential_leak` arguably) vs relax for external (`nondeterminism`, `os_system`, `eval`, bare-except). **[agy R4]
  recommend a `config.yaml` toggle** keyed on `_target_is_self`. **CRITICAL: the relax must thread across TWO INDEPENDENT
  AST ENGINES, not three call-sites of one engine.** The submit `validate` (`_decide_common.py:105` → `rpc/submit_code.py`)
  AND the commit enforcer both call `harness/ast_enforcer.py::validate_code` (relax via a new param mirroring the existing
  `allow_nondeterminism`). **But the production interceptor (`harness/interceptors.py:15/53`) uses a SEPARATE engine —
  `services/neurosymbolic/ast_verifier.py::ASTVerifier` — with its own rule/severity table** (this is exactly why PARITY-3
  was landed in `ast_verifier.py` separately). Relaxing only `ast_enforcer.py` leaves the interceptor strict → breaks the
  submit⊆commit / interceptor⊆gate PARITY (F2) invariant. The toggle MUST be wired into BOTH engines. (DROP `oracle_attach.py:30`
  `_target_is_self_modification` — confirmed unwired on production dispatch, and its `harness/`-prefix self-test is inconsistent
  with the path-based `_target_is_self()`; do not confuse the two.)
- **G3 — target-`.venv` binding (one atomic deliverable with B3).** All execute-target stages must bind the target
  interpreter, NOT JM's: the 4 verify spawns (`orchestrator.py:1846/1971/1995/2009`, `extra_ro=[sys.base_prefix,
  sys.prefix]`), the embedded runner, the differential-fuzzer sandbox (`sandbox.py:1358/1543/1666` `sys.executable`),
  and the oracle/mutation gate (`test_author.py:70`). Add `<working_dir>/.venv` prefix/bin to `extra_ro` + jailed PATH.
  **COORDINATION (the 4 verify lines are triple-edited):** `orchestrator.py:1846/1971/1995/2009` each carry BOTH
  `build_jail_argv(...)` (SEC-1's proxy-wrap target) AND `extra_ro=[sys.base_prefix,sys.prefix]` (this G3 edit) AND are
  T3's repo_root re-point — all three changes hit the same physical lines and MUST be landed as one coordinated edit per
  line to avoid double-touching and re-tripping the WHOLE-FILE / symbol-drift guards (§4). Also: `<working_dir>/.venv`
  must be injected in CODE (derived from `task.working_dir`), NOT via `config.yaml verify_extra_ro` (which §4 pins empty).
- **Bootstrap (REV18 §3B-B):** new `harness/target_bootstrap.py` (git init / .gitignore / initial commit / `.venv` +
  target deps / staging worktree) + a one-time `bootstrap_target()` at daemon startup (gate-bearing hand-edit). Key
  idempotency on a recorded marker (not "files present"). Refuse/warn on a dirty external target tree.

**Sequencing [agy R4, verify-first]:** SEC-1 + SEC-ENV first (secure the boundary) → §3B-D 5 seams + trust fork →
T2-T5 re-key → G3 venv binds → G2 rule split → validate against a real external project under the sandbox → owner
Phase A. **§3B-D itself is owner-proposed; to be re-confirmed in next session's Claude review before build.**

---

## 4. Invariants carried through EVERY phase (do-NOT) — per-file grep checklist

- `grep -c "synthesis_success = True"` **==1** in EACH of `harness/orchestrator.py` and `harness/orchestrator_worker.py`.
- Never narrow `BYPASS_FUZZER_TYPES`; `test_authoring` stays `bypass_fuzzer:False`; `grep -c "skip_interface_fuzz"`
  **==1** in EACH of `harness/planner/taxonomies.py`, `harness/orchestrator.py`, `harness/orchestrator_worker.py` (ONLY `test_authoring`).
- `_SENSITIVE_APPLY_GLOBS == ('harness/**','config/**','scripts/**')` at `git_integration.py:16`.
- `verify_extra_ro`/`verify_extra_rw` ABSENT/empty in `harness/config.yaml`.
- Submit-time AST interceptor ⊆ commit-time enforcer (PARITY class). PARITY-3 landed; introduce no new violation.
  Any §3B G2 external relax MUST apply identically across submit/interceptor/commit.
- R-ANCHORED-PATCH (`_apply_symbol_patch`): no-extras path byte-identical; extras only 1-part qualnames, bounded kinds,
  name-collision-rejected. WHOLE-FILE-DRIFT-GUARD (legacy whole-file branch): keep modified-existing-symbol
  intersection semantics.
- agy is NOT tree-isolated → after ANY agy run verify byte-identical + revert drift (esp. `git checkout HEAD --
  harness/config.yaml`). This session agy behaved (live tree clean), but always confirm.
- Never add `*_fix`/any `<task>_fix` to the allowlist. `full_stop` stays present until owner-gated Phase A. §1b
  (`_apply_approval_granted`) is the autonomous-commit boundary; agents tree-isolated ONLY via the bwrap jail.
- External-target safety boundary (§3B): any self-build-gate bypass derives from the RESOLVED target via
  `_target_is_self()` — a **predicate that must be BUILT (does not exist yet; disambiguate from the unrelated unwired
  `oracle_attach.py:30 _target_is_self_modification`)** (3-clause: `== PROJECT_ROOT` OR `PROJECT_ROOT in root.parents` OR
  `root in PROJECT_ROOT.parents`), fail-safe to "self" on any ambiguity. **The `working_dir` INPUT must be hardened:** the
  brief-supplied value MUST be `.resolve()`-normalized and REJECTED if relative / containing `..` / resolving inside
  `agent_workroot()`/`state/`; and any `working_dir` present in the LLM-authored plan task MUST be STRIPPED before the
  trusted brief stamp (verbatim `deepcopy`/`stage_task` copy preserve it otherwise — see §3 seam 3). Ship `_target_is_self()`
  unit tests for the symlink/parent-chain edge cases BEFORE wiring any G2 relax. `JANUSMASK_PROJECT_DIR`/`PYTHONPATH` +
  `${PROJECT_ROOT}` config tokens STAY self.

---

## Appendix — anchors (re-verified @ `cf3811f`; re-check before use)

- `services/neurosymbolic/ast_verifier.py`: `visit_Constant` credential_leak `~:205-210` (now WARNING).
- `harness/git_integration.py`: `_SENSITIVE_APPLY_GLOBS` `:16`; `_apply_symbol_patch` (R-ANCHORED extras);
  `commit_accepted_output` `:569`; `_commit_accepted_output_patches` `:1114`; `remove_staging_worktree`
  `~:1294` (now bounded retry/timeout); `merge_staging_to_parent` fail-closed-on-dirty-parent (whole-tree stash).
- `harness/autowork_daemon.py`: `_reap_running` `:296`; `_escalate_to_autobrief` `:608` (pidfile `:743`);
  `_spawn_worker` `:827` (`start_new_session=True` `:836`); `_resume_or_kill_orphaned_workers` `:1528` (NEW, startup
  sweep); `run_daemon` (startup call to the sweep); `_escalate_inactivity` `:1777` (pidfile `:1822`); `full_stop`
  checks `:1238/:1517`; daemon `repo_root = Path.cwd()` (`run-autowork.sh:33` pins JM repo) — §3B T5.
- `harness/orchestrator.py`: `_build_agent_env` def `:220` (the `{**os.environ}` leak is body line `:260` — SEC-ENV); jail synth bind
  `repo_root=PROJECT_DIR` `:347`; verify spawns `:1846/1971/1995/2009` (`extra_ro=[sys.base_prefix,sys.prefix]` — G3);
  `_auto_commit_accepted` `:1473` (now try/finally crash-safe); `run_pipeline` `:2167` (now per-iteration crash-safe);
  `synthesis_success = True` ×1.
- `harness/orchestrator_worker.py`: `main` finally orphan-guard (ROLLB-E FIX1); `synthesis_success = True` ×1.
- `harness/agent_jail.py`: `build_jail_argv` `:65` (SEC-1 — bind proxy socket); XDG `bus`/`keyring` bind `~:245`
  (SEC-1 / KEYRING-UNFILTERED).
- SEC-1 `build_jail_argv` execution CALL SITES (10, wrap in dbus_proxy ctx mgr — same set as §3B T3): `orchestrator.py:347`,
  `autowork_daemon.py:604`, `orchestrator.py:1846/1971/1995/2009`, `embedded_test_runner.py:159/204`,
  `sandbox_smoke.py:122`, `narrow_fuzz/validation.py:257`. Existing test to realign: `tests/adversarial/test_h_jail_c_xdg_isolation.py:72`.
- §3B-D plumbing: `brief_loader.py:160` (drop filter; `:66` = `REQUIRED_SECTIONS` def), `PlanningBrief`+`blind_draft.py:122`
  (serialization whitelist; `:128` is the `for agent` loop), `staging.py:16` (+ NEW daemon brief-load/stamp at the
  `stage_task` call `autowork_daemon.py:1103`, NOT `:1093`; +STRIP LLM `working_dir`), `_decide_common.py:86`;
  `_target_is_self()` predicate — **TO BE BUILT** (REV18 §3B, paths.py — extends GAP_H3 `:62` from 2→3 clauses).
- `state/control/autowork/full_stop`: **PRESENT** (`halted`).
