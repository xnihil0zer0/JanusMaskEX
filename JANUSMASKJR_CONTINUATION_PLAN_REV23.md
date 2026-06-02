# JanusMaskJR — Continuation Plan (2026-06-02, rev 23)

> **rev 23 — DRAFT.** Compiled by the overseer/compiler from a 4-area **cross-vendor `agy` (Antigravity
> Gemini 3.5 Flash)** adversarial panel (reports `~/janusmask_briefs/review_rev23/R{1..4}_*.md`; agy ran
> read-only — repo HEAD + tracked tree verified byte-UNCHANGED post-run). Supersedes
> `JANUSMASKJR_CONTINUATION_PLAN_REV22.md`. HEAD at compile time = `fa39605`.
>
> **CADENCE — NOT yet Claude-reviewed.** Per the owner's cadence this DRAFT must be **adversarially
> Claude-reviewed NEXT session** (worktree sub-agents + compiler, codebase-memory-mcp grounded, every
> `[agy R#]` anchor re-grepped @ HEAD) and **EXECUTED the session AFTER**. agy is a known anchor/severity
> hallucinator — cross-check every `[agy R#]` claim against live code. **Two findings were already
> compiler-VERIFIED against live code at compile time (flagged `[compiler-VERIFIED @ fa39605]`); treat
> the rest as unverified until the Claude review.**
>
> **Governing rule (owner directive, carried verbatim):** use the JanusMaskJR PIPELINE for every change
> wherever possible; HAND-EDIT only AFTER a pipeline attempt FAILS with a PERMANENT/structural blocker
> (never a timeout, never a re-groundable stale-ground-truth or mis-render). **REV22-exec confirmed
> blockers + their pipeline-first fixes (carry these):**
> - **NEVER patch a class method (2-part qualname).** Gemini reliably emits "SyntaxError: unexpected
>   indent" reproducing a method body → the dual-agent AST gate rejects (3/3). Restructure to TOP-LEVEL
>   function changes (e.g. post-filter results in a top-level fn instead of mutating a visitor method).
>   This is how `G2_RELAX` was recovered after attempt #1 rejected.
> - **A NEW module = a SINGLE-file task** (`files_touched=[the .py]` ONLY; commit the oracle RED-first as a
>   SEPARATE commit; `partial_edit:False`). A multi-file `files_touched` (module + oracle) makes the
>   orchestrator demand a `__JANUSMASK_MANIFEST__` the agents do not reliably emit. For a deterministic
>   module, EMBED the full validated reference source verbatim in `spec.implementation_notes` (single-file
>   tasks do NOT stage the oracle to the agents). This is how `BOOTSTRAP_MODULE` was recovered after two
>   rejections.
> - Mechanical envelope fixes (`files_touched` length, `partial_edit` flag) may be applied directly to the
>   taskspec at ingest (not brief-logic). Do NOT `rm` the `processed/<id>.json` marker before confirming the
>   canonical taskspec still exists — re-cp from `~/janusmask_briefs` first.
>
> **Brief authoring:** delegated to `agy` + an independent Opus review inside a worktree-isolated sub-agent.
> Agents (authors, reviewers) MUST use **codebase-memory-mcp** (project `home-xnihil0zer0-JanusMaskJR`,
> index ready) to understand structure before acting. **agy is NOT tree-isolated → audit byte-clean +
> revert drift after EVERY agy run.** In `verification_command`, QUOTE EACH pytest path SEPARATELY.
>
> **HEADLINE (honest status):** REV22 executed the gate-non-relaxing subset (6 hardening/plumbing landings)
> AND, after the owner confirmed G2 scope + CR-3 + CR-10 (plan REV22 §0.6), the first 3 ACTIVATION-bundle
> landings (`G2_RELAX`, `BOOTSTRAP_MODULE`, `BOOTSTRAP_WIRING`). The agy panel confirms all 9 landings match
> intent with non-vacuous oracles and the §5 invariants hold — but surfaced **one CRITICAL latent hole the
> G2 relax introduced (relax keys on `working_dir`, not the target file → an external `working_dir` editing
> a JM file gets relaxed into the JM codebase)**, a divergent MCP submit path, the still-OPEN M2 foreign-repo
> untracked-scan + zombie-reclamation gaps (the owner's named priority for this plan), and the remaining
> re-rooting bundle re-anchored @ `fa39605`. External capability is **still INERT** (no external brief is
> originated today), so the partial state is safe — but §1(a) must land before any external origination.

---

## 0. Landed in the REV22-exec session — VERIFIED @ `fa39605` (do not re-do) [agy R1, all non-vacuous]

| Commit | Item | agy-R1 verdict |
|--------|------|----------------|
| `eb781d7` | KEYRING_GATE §1a | matches intent (`agent_jail.py:290-291` gate); oracle non-vacuous; defense-in-depth. |
| `2c3d1b1` | SEAM3_STAMP §4-1 | `cli.py:102-104` stamps trusted working_dir; non-vacuous; INERT. |
| `23ef007` | DAEMON_STAMP_PASS §4-2 | `autowork_daemon.py:1219-1227`/`:1251` thread to stage_task; non-vacuous; INERT. |
| `09693d4` | FLAG2_ORCH §3/CR-6 | reader `orchestrator.py:1799` + 4 guards `:1986/2117?/2158?/2189?`; non-vacuous. **embedded+fuzz families still unguarded (→ §3 FLAG2-EMBEDDED-FUZZ).** |
| `417f14c` | BINARY_ABSENT_REFUSE §2b/CR-8 | `run_daemon`+`main` refuse host-bus-without-proxy; non-vacuous. |
| `8d8c4f3` | ZOMBIE_TELEMETRY §2d | `brief_status.py:67-68` state='zombie'; non-vacuous; **observability only — no reclamation (→ §2(b)).** |
| `6de18bf` | G2_RELAX §4-3 | relax eval/exec/`__import__` submit+commit via top-level post-filter (`ast_enforcer.py:225-228` suffix match); non-vacuous. **TWO gaps → §1(a) self-target bypass, §1(b) MCP path.** |
| `1c8aa5c` | BOOTSTRAP_MODULE §4-7 | new `target_bootstrap.py`; non-vacuous. **dir-takeover risk → §4.** |
| `fa39605` | BOOTSTRAP_WIRING §4-7 | `_auto_promote:1228-1246` best-effort bootstrap; non-vacuous. |

**§5 invariants re-verified @ `fa39605` [agy R1 §2, all Verified]:** `synthesis_success = True` ==1 in
`orchestrator.py` + `orchestrator_worker.py`; `_SENSITIVE_APPLY_GLOBS == ('harness/**','config/**','scripts/**','services/**')`
(`git_integration.py:16`); `verify_extra_ro/rw` ABSENT in `config.yaml`; `full_stop` ABSENT (Phase A active).

**Owner decisions standing (REV22 §0.6):** G2 relax scope = `eval`/`exec`/`__import__` ONLY; CR-3 = JM-owned
external staging root (`agent_workroot()/external_staging/`); CR-10 = `janusmask/work` branch via ref-update.

---

## 1. THIS-SESSION REGRESSIONS the landings INTRODUCED — VERIFY-FIRST, fix EARLY (pipeline-viable) [agy R1/R4]

**(a) G2-relax SELF-TARGET BYPASS [agy R4, CRITICAL — `[compiler-VERIFIED @ fa39605]`].**
`relax_external = not _target_is_self(task.get('working_dir'))` keys ONLY on `working_dir`, at BOTH
`harness/hooks/_decide_common.py:109` (submit) AND `harness/orchestrator.py:1151` (`_validate_submission`,
commit). It does NOT consider the actual TARGET FILE. So a task with an EXTERNAL `working_dir` but
`files_touched`/target INSIDE the JM tree (e.g. `harness/agent_jail.py`) is classified external →
`relax_external_constructs=True` → `eval`/`exec`/`__import__` would be allowed into JanusMask's OWN code,
bypassing the self-code security boundary. (Latent today: no external brief is originated — but this MUST
land before any external origination / G1 wiring.)
- **Fix (pipeline, top-level only):** relax must additionally require that the resolved target file does
  NOT reside within `PROJECT_ROOT`. Compute relax as `not _target_is_self(working_dir) AND
  effective_target_root(working_dir) is outside PROJECT_ROOT AND every resolved target path is outside
  PROJECT_ROOT`. Apply at BOTH `_decide_common.py:109` and `orchestrator.py:1151`. Credentials/os_system/
  bare_except/nondeterminism already stay strict.
- Oracle: external `working_dir` + target file inside JM tree → eval BLOCKED (strict); external
  `working_dir` + target file outside JM tree → eval allowed; self → strict.
- New §5 invariant: "G2 relax NEVER applies to a target file resolving within `PROJECT_ROOT`."

**(b) MCP divergent submit path drops the relax [agy R1, HIGH→functional — `[compiler-VERIFIED @ fa39605]`].**
`harness/mcp_server.py:231` `cmd_submit_code` calls `rpc_submit_code.validate(code,
allow_nondeterminism=allow_nondet)` WITHOUT `relax_external_constructs`. An external task whose agent submits
via the MCP `execute`/`submit_code` tool (e.g. claude-code) hits this path → `eval`/`exec`/`__import__`
REJECTED at submit → G2 relax broken for MCP submissions. Fails-CLOSED (over-strict, not a security hole) but
breaks the external workflow.
- **Fix (pipeline):** in `cmd_submit_code`, compute `relax_external = not _target_is_self(<task working_dir>)`
  (the in-scope task) — combined with the §1(a) target-file check — and pass `relax_external_constructs=` to
  `rpc_submit_code.validate`. Coordinate the relax-keying with §1(a) so both submit paths agree.
- Oracle: external-target MCP submit of eval allowed; self/JM-target MCP submit strict.

---

## 2. M2 ↔ `full_stop` gap closure — OWNER PRIORITY for this plan [agy R3]

Removing `full_stop` turned the M2 untracked-test bug from a static halt into an active unattended
credit-burn risk (REV22 §0 causal record). State of the M2 story:

**(a) Self-build untracked-test poisoning — CLOSED [agy R3 §1.1].** `git_integration.py:606-647`
(M2-GAPFILL `94073e8`) initializes `untracked_files`, scans `git status`, and folds generated tests into the
sidecar manifest. No action.

**(b) External foreign-repo untracked scan — OPEN, HIGH [agy R3 §1.2].** Under external mode the
`commit_accepted_output` untracked scan would sweep the USER's untracked test files into `janusmask/work` —
re-opening poisoning in a foreign repo. **Fix = the M2-external gate, FOLDED INTO `COMMIT-REROOT` (§3):**
when `not _target_is_self(<retargeted working_dir/parent>)`, BYPASS the porcelain scan and force
`untracked_files = []` (`git_integration.py:610` region; requires the kw-only `working_dir` threaded through
`commit_accepted_output`). Key on the retargeted parent, NOT `worktree_root` (staging path at the call site).
- Oracle: external `working_dir` + dirty untracked test in the external repo → NOT auto-committed; self → still auto-allowed.

**(c) Zombie-parked brief RECLAMATION — OPEN, MED [agy R3 §1.3] → new task `BRIEF-ZOMBIE-RECLAMATION`.**
`ZOMBIE_TELEMETRY` only CATEGORIZES; a parent brief whose tasks are all parked-unaccepted stays
`queued`/`in_flight` forever under unattended Phase A. **Fix (pipeline):** in the daemon iteration, when a
brief computes `state=='zombie'`, archive its brief file to `state/control/autowork/quarantine/`, release
locks, and clean its in-progress operational state (so it is never re-dispatched). Anchor `[agy R3 §2.2]`:
`autowork_daemon.py:1176` / within `_iteration` (re-grep; AVOID class-method patches — keep it a top-level
function edit). Pairs with `ZOMBIE_TELEMETRY` (consumes its `state=='zombie'` signal).
- Oracle: a fixture brief with all tasks parked-unaccepted → after one daemon iteration the brief is moved
  to `quarantine/` and not re-dispatched; a healthy brief is untouched.

**(d) Other cascades/retries — CLOSED [agy R3 §1.4].** `_runaway_counter_bump` (`autowork_daemon.py:622`)
bounds self-heal cascades; `_retry_blocked_tasks` (`:867`) quarantines to `.exhausted` (1 attempt
deterministic / 3 non-deterministic). No other infinite loop. No action (carry the record).

---

## 3. §4 external-capability ACTIVATION bundle — REMAINING, re-anchored @ `fa39605` [agy R2]

> Each item RELAXES gates / activates external targeting → **every one RE-TRIGGERS the owner's Phase-A
> review.** All touch the large `_auto_commit_accepted` (orchestrator) + their `git_integration.py`
> functions → must land SERIALLY (each re-grounds on the prior). agy R2 confirms ALL remaining symbols are
> top-level (NO class-method patches) → dual-agent-compatible. The FLAG2_ORCH `working_dir` reader at the
> top of `_auto_commit_accepted` is reusable by every step (no repeated `task.get('working_dir')`).

Ordered, pipeline-viable breakdown [agy R2 §5, anchors re-grep before use]:

1. **STAGING-REROOT (CR-3 + T3).** `orchestrator.py` `worktree_root` derivation `:1821-1825` →
   `effective_target_root(working_dir)` for external; `staging_path` `:1831` → `external_staging_root()/<name>_<tid>`;
   `create_staging_worktree` call `:1837`. In `git_integration.py` `create_staging_worktree` (`:1251`):
   relax the sibling-raise (`:1268-1269`) for external — when `not _target_is_self(parent_root_obj)`, assert
   `staging_path.parent == external_staging_root()` INSTEAD of the sibling check. (`--git-common-dir` worktrees
   support arbitrary placement — agy R2 §3.1 verified.)
2. **EXTERNAL DIRTY-GATE.** In `_auto_commit_accepted`, BEFORE `create_staging_worktree` (`:1837`), if external
   and the external repo is dirty → REFUSE (never stage/stash a user repo). [agy R2 §3.2]
3. **COMMIT-REROOT (CR-4 + §2(a) M2-external gate).** `git_integration.py` `commit_accepted_output` (`:569`):
   add kw-only `working_dir`; retarget BOTH `parent_root` derivations (`:604-605` AND `:659-660`) to
   `effective_target_root(working_dir)` for external; thread through `_commit_accepted_output_multi` (`:815`) +
   `_commit_accepted_output_patches`; **§2(a): force `untracked_files=[]` when not `_target_is_self`** (`:610`
   region). `orchestrator.py` commit call `:1876` passes `working_dir`.
4. **MERGE-REROOT (CR-10).** `git_integration.py` `merge_staging_to_parent` (`:1351`): for external, REPLACE the
   local stash/ff-merge/reset path (`:1390/1393-1395/1409/1419/1426/1435/1442`) with a pure ref-update onto
   `janusmask/work` (`git push . HEAD:refs/heads/janusmask/work` without `--force`, or `git update-ref` in the
   parent) — NO checkout, NO working-tree merge, NEVER the user's branch. Keep `--ff-only` semantics (omit
   `--force`). `orchestrator.py` merge call `:2233`. [agy R2 §3.2]
5. **G3-VENV (§4-4).** Code-inject `<working_dir>/.venv` (prefix/bin) on execute `build_jail_argv` sites:
   `orchestrator.py` verify `:1982` / baseline `:2123` / mutant-apply `:2164` / mutant-rerun `:2195`; embedded
   `embedded_test_runner.py:183`/`:231`; fuzz `narrow_fuzz/validation.py` (re-grep). Keep `verify_extra_ro/rw`
   EMPTY in config (inject in code).
6. **GLOBS-EXTERNAL + PATH-CONTAINMENT (CR-9/CR-3).** Define the external `_SENSITIVE_APPLY_GLOBS` mapping +
   where the §1b approval boundary sits for external commits (with an oracle). Add explicit write-containment:
   resolve all bind/commit paths with `.resolve()` and enforce strictly within `effective_target_root()` ∪ the
   JM staging root — reject `..`/symlink escape (the predicate only CLASSIFIES; this ENFORCES).
7. **T-RETARGET (§4-5).** synth `repo_root=PROJECT_DIR` (`orchestrator.py:391`) follows the external target;
   `JANUSMASK_PROJECT_DIR`/`PYTHONPATH` STAY self; embedded `PROJECT_ROOT` (`embedded_test_runner.py:115`,
   used `:185`/`:233`) threaded from `working_dir`; T5 no-op `_maybe_push_and_rebase_pin` for external.
8. **FLAG2-EMBEDDED-FUZZ (CR-5).** Add the FLAG2 fail-closed gate to the two OTHER execute families that still
   run UNJAILED when sandbox off: `embedded_test_runner.py:183` (the `if sandboxed:`-skip raw run) and
   `narrow_fuzz/validation.py:298` (`else: argv=['python3','driver.py']` Popen) — refuse when
   `not _target_is_self(working_dir)` and not `sandbox_enabled()` (thread `working_dir` to those modules).
   **HIGH severity now that G2 relax allows eval/exec for external [agy R4 §2.1].**
9. **INTEGRATION-TEST (§4-8, GATING).** fixture external repo, cases A–K (REV22 §4-8): external relax applies
   but bare_except/os_system blocked (A); self strict (B); malicious `working_dir` rejected + write-containment
   (C); target `.venv` used (D); predicate fail-safe in jail (E); ancestor/descendant=self (F); dirty external
   REFUSED, tree byte-unchanged (G); non-FF external handled (H — now: ref-update onto `janusmask/work`, never
   user branch); e2e lands in `janusmask/work` + nothing in JM repo (I); M2 untracked external not committed
   (J); host-ENV not leaked + sandbox-off external refused in ALL THREE execute families (K). **PLUS a new case
   for §1(a): external `working_dir` + JM-tree target file → relax does NOT apply.**

**THEN owner Phase-A re-review** (§4 checklist).

---

## 4. Cross-cutting security + Phase-A readiness [agy R4]

- **Bootstrap directory-takeover [agy R4 §2.2, MED].** `bootstrap_target` (`target_bootstrap.py:146-182`)
  resolves `working_dir` and will `git init` + write `.gitignore`/`.venv` in ANY folder lacking a `.git` — a
  misconfigured/malicious path (`/etc`, `$HOME`, …) could be mutated. **Fix:** enforce the resolved
  `working_dir` lies within an operator-approved external root (an allowlist, e.g. `auto_promote.allowlist` or a
  dedicated configured external-roots list) BEFORE any init/marker write. Ties to G1 origination.
- **Inert-safety claim [agy R4 §1.1]:** external-targeting-EXTERNAL-file tasks fail closed at commit today
  ("target escapes worktree" — un-re-rooted), so the bundle is safe to land incrementally; the LIVE exposure is
  §1(a) (external `working_dir` + JM-tree target) — fix first.
- **New §5 invariants to add [agy R4 §4]:** (i) a jailed worker NEVER runs unjailed on an external task —
  refuse if `not _target_is_self` and not `sandbox_enabled()` (all THREE execute families); (ii) G2 relax NEVER
  applies to a target file within `PROJECT_ROOT` (§1(a)); (iii) external staging worktrees live strictly under
  `agent_workroot()/external_staging/`.
- **Owner Phase-A 8-point review (updated for the post-relax shape) [agy R4 §3]:** (1) full unit-suite green;
  (2) jail write-denial (`tests/adversarial/test_phase_a_selfheal_jail_writedenial.py` + bwrap-flip mutant →
  failures-not-skips); (3) live no-regression for self synthesis under the jail; (4) §4-8 integration A–K green
  (sandboxed AND sandbox-off); (5) AST scoping — credentials/os_system/bare_except never bypassed + §1(a)
  JM-target never relaxed; (6) staging worktrees under `external_staging/` cleanly destroyed on success AND
  failure; (7) daemon restart clean (no warnings; binary-absent refusal honored); (8) allowlist integrity —
  only operator-approved external roots present. THEN go/no-go on keeping `full_stop` removed for the new shape.

---

## 5. Invariants carried through EVERY phase (do-NOT) — re-verify @ HEAD

Carry ALL REV22 §5 invariants (synthesis_success==1; skip_interface_fuzz only test_authoring;
`_SENSITIVE_APPLY_GLOBS` incl. `services/**`; `verify_extra_*` absent/empty; SEC-1 fail-closed; CRED-EXFIL
binds; FLAG2 orch-family refusal; M2 self auto-allow; predicates fail-safe-to-self + LLM `working_dir`
STRIPPED at `stage_task`+`impl_plan_to_queue.py`; trusted value only via `persist_plan` stamp → daemon →
`stage_task`; `JANUSMASK_PROJECT_DIR`/`PYTHONPATH` STAY self; `full_stop` REMOVED — Phase A active; agy not
tree-isolated → audit+revert). **ADD (rev23):**
- **G2 relax NEVER applies to a target file resolving within `PROJECT_ROOT`** (§1(a)).
- **All FOUR submit/commit relax readers agree** (`_decide_common.py`, `orchestrator._validate_submission`,
  `mcp_server.cmd_submit_code`, and the orchestrator commit-time `validate_code` calls) — submit ⊆ commit, and
  no divergent path drops the relax (§1(b)).
- **FLAG2 fail-closed in ALL THREE execute families** (orch shell=True DONE; embedded + fuzz pending §3-8).
- **External staging worktrees ONLY under `agent_workroot()/external_staging/`**; external accepted output ONLY
  on `janusmask/work` via ref-update — NEVER the user's branch, NEVER a JM-repo commit.
- **M2 untracked auto-detect/commit DISABLED when `not _target_is_self`** (§2(a)).
- **`bootstrap_target` refuses a `working_dir` outside the operator-approved external-root allowlist** (§4).

---

## Appendix — re-verified anchors (@ `fa39605`; re-grep before use) [agy R2]

- `harness/git_integration.py`: `_SENSITIVE_APPLY_GLOBS` `:16`; `commit_accepted_output` def `:569`
  (`parent_root` derivations `:604-605` AND `:659-660`, M2 untracked scan `:606-647`/`:610`);
  `_commit_accepted_output_multi` `:815`; `create_staging_worktree` `:1251` (sibling raise `:1268-1269`);
  `merge_staging_to_parent` `:1351` (status `:1390`, stash `:1393-1395`, ff-merge `:1409`, stash-pop `:1419`,
  reset-hard-HEAD `:1426`, reset-hard-presha `:1435`, stash-drop `:1442`).
- `harness/orchestrator.py`: synthesis `build_jail_argv` `:391`; `_validate_submission` relax `:1151`
  (commit-time `validate_code` `:1159`/`:1198`/`:1219`); `_auto_commit_accepted` working_dir reader `:1799`,
  external guards `:1986`(+3, re-grep); `worktree_root` `:1821-1825`, `staging_path` `:1831`,
  `create_staging_worktree` call `:1837`, `commit_accepted_output` call `:1876`, verify/baseline/mutant
  `build_jail_argv` `:1982`/`:2123`/`:2164`/`:2195`, `merge_staging_to_parent` call `:2233`;
  `synthesis_success = True` `:2529`.
- `harness/orchestrator_worker.py`: `synthesis_success = True` `:310`.
- `harness/hooks/_decide_common.py`: `decide_submission` relax `:109` (`rpc_submit_code.validate` `:110`).
- `harness/mcp_server.py`: `cmd_submit_code` `:198`, `rpc_submit_code.validate` call (no relax) `:231` [§1(b)].
- `harness/ast_enforcer.py`: `validate_code` `:187`; eval/exec/`__import__` suffix post-filter `:225-228`.
- `harness/embedded_test_runner.py`: `build_jail_argv` import `:114`, `PROJECT_ROOT` `:115` (used `:185`/`:233`),
  build_jail_argv `:183`/`:231`. `harness/narrow_fuzz/validation.py`: unjailed `else` branch `:298` (`if` `:276`).
- `harness/target_bootstrap.py`: `bootstrap_target` `:146-182` (dir-takeover guard target).
- `harness/autowork_daemon.py`: `_auto_promote` bootstrap wiring `:1228-1246`; zombie-reclamation seam
  `~:1176`/`_iteration`; `_runaway_counter_bump` `:622`; `_retry_blocked_tasks` `:867`; binary-absent refusals
  `:1760-1762`/`:1904-1906`.
- `state/control/autowork/full_stop`: ABSENT (Phase A active).
- Panel reports: `~/janusmask_briefs/review_rev23/R{1..4}_*.md` (agy; Opus-cross-check at the Claude review —
  verify every `[agy R#]`; §1(a)+§1(b) already `[compiler-VERIFIED @ fa39605]`).
