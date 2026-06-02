# JanusMaskJR — Continuation Plan (2026-06-02, rev 22)

> **rev 22 — DRAFT.** Compiled after the REV21 §1 + §3(a–e) + §4-non-activating-seams scope was EXECUTED
> this session (13 commits via the JanusMask pipeline, code `1adf139`→`c31c7b4`, all PUSHED to
> `origin/master`, 0 production hand-edits, final 330-test sweep green) and then adversarially
> re-reviewed by a 4-area **cross-vendor `agy` (Antigravity Gemini)** panel (reports in
> `~/janusmask_briefs/review_rev22/R{1..4}_*.md`, agy ran strictly read-only — repo HEAD + tree status
> verified UNCHANGED post-run). Supersedes `JANUSMASKJR_CONTINUATION_PLAN_REV21.md`.
>
> **CADENCE — NOT yet Claude-reviewed.** This DRAFT was COMPILED from the agy panel by the overseer;
> per the owner's cadence it must be **adversarially Claude-reviewed NEXT session** (4 worktree
> sub-agents + compiler, codebase-memory-mcp grounded, every anchor re-grepped @ `c31c7b4`), and
> **EXECUTED the session AFTER**. agy is a known hallucinator on anchors/severities — the Claude review
> MUST cross-check every `[agy R#]`-tagged claim against live code before acting. Two findings are
> flagged **`[VERIFY-FIRST — possible THIS-SESSION regression]`** (R1-2 keyring bind, R1-5/R3-2 counter
> `a+` mode): confirm or refute these against `c31c7b4` at the TOP of the review.
>
> **Governing rule (owner directive, carried verbatim):** use the JanusMaskJR PIPELINE for every change
> wherever possible; HAND-EDIT only AFTER a pipeline attempt FAILS with a PERMANENT/structural blocker
> (never a timeout, never a re-groundable stale-ground-truth or mis-render). **THIS SESSION'S CONCRETE
> CONFIRMATION:** a NEW top-level symbol (`_runaway_counter_bump`) is a PERMANENT blocker as its OWN
> partial-edit patch block (`_apply_symbol_patch` KeyErrors on an unknown qualname) — it MUST ride as an
> EXTRA top-level node inside an EXISTING edited symbol's patch block (R-ANCHORED 1-part-qualname extras;
> Assign/AnnAssign are NOT allowed extras → keep new module constants out, fold into a function body or a
> class). RUNAWAY-CEILING failed once this way and was fixed by RE-AUTHORING the brief, not hand-editing.
>
> **Brief authoring:** delegated to `agy` + an independent Opus review inside a worktree-isolated
> sub-agent. Agents (authors, reviewers) MUST use **codebase-memory-mcp** (project
> `home-xnihil0zer0-JanusMaskJR`, index ready) to understand structure before acting. **agy is NOT
> tree-isolated → audit byte-clean + revert drift after EVERY agy run.** In `verification_command`, QUOTE
> EACH pytest path SEPARATELY.
>
> **HEADLINE (honest status):** `state/control/autowork/full_stop` is REMOVED — **Phase A is ACTIVE; the
> daemon may run unattended.** The REV21 gate-ii closers (SEC-1 verify-spawn fail-close, credential-exfil
> net-unshare, runaway-ceiling persistence, abstract-bus warn) + the M2 untracked-test deadlock fix ALL
> landed. The agy panel found the closers SOUND in their stated scope but surfaced **one CRITICAL latent
> hole (FLAG#2 unjailed `shell=True` when sandbox is OFF), two possible THIS-SESSION regressions (keyring
> bind not gated by `bind_credentials`; runaway-counter `a+`-mode reset-to-0 race), and a mandatory
> §1↔§4 gate (M2 untracked-test auto-commit re-opens in a FOREIGN repo under external mode).** §4
> external capability has its non-activating plumbing in place (seams 1/2/4); the remaining ACTIVATION
> bundle relaxes gates and **re-triggers the owner's Phase-A 8-point review**.

---

## 0.5 CLAUDE REVIEW (rev22, 2026-06-02) — APPLIED CORRECTIONS [4 worktree sub-agents + compiler, codebase-memory-grounded]

> This DRAFT was adversarially Claude-reviewed per cadence: 4 worktree sub-agents (distinct lenses, all
> codebase-memory-mcp grounded + live-grep) + the compiler. Every `[agy R#]` anchor was re-grepped at the
> live tree. **HEAD is `1a447c4`, NOT `c31c7b4`** — but `git diff c31c7b4..1a447c4` touches ONLY this plan
> file (`afa64de` add + `1a447c4` §2(e) edit); **production code is byte-identical to `c31c7b4`, so all
> code anchors below remain valid**. Re-grep at `1a447c4` before editing. Corrections applied at ≥3/5
> consensus; CRITICAL/HIGH findings caught by 1 lens + compiler-verified-against-live-code are ELEVATED
> (division-of-labor artifact, not weak consensus — matches prior round-2 practice). Verdicts:
>
> **VERIFY-FIRST resolved:** §1(a) keyring-ungated = **CONFIRMED** (5/5; `agent_jail.py:284-288` binds
> `bus`/`keyring` with NO `bind_credentials` guard — anchor `~:280`→keyring bind `:287-288`); severity =
> defense-in-depth (the load-bearing control is `--unshare-net`, applied on execute spawns; `--unshare-ipc`
> does NOT protect a filesystem keyring socket). §1(b) `a+`-mode race = **REFUTED** (5/5; `:664` IS `a+`,
> agy read the mode right, but `fcntl.flock(LOCK_EX)` `:665-669` + `seek(0)+truncate()+write` `:685-688`
> already make it monotonic/well-formed on Linux — empirically reproduced). **§1(b) DOWNGRADED to "no live
> defect on Linux; do NOT spend a pipeline cycle rewriting"** — at most add the monotonicity oracle (seed a
> CORRUPT file, assert no reset below prior count) as a cheap regression guard for the non-`fcntl` fallback.
>
> **CRITICAL corrections to §4 (external) — APPLIED inline below:**
> - **[CR-1] bare_except CANNOT be relaxed only at commit (Agent1 + compiler, ELEVATED).** `bare_except` IS
>   a LIVE interceptor rule (`ast_verifier.py:167`, ERROR) running at submit/write via `interceptors.py:53`
>   (`ASTVerifier()`, no task context, no relax seam). Relaxing it only in the commit-time enforcer makes
>   submit STRICTER than commit for external → an external task using `except: pass` is denied at synthesis.
>   **FIX: DROP `bare_except` from the external-relax set.** External relax = **`eval`/`exec`/`__import__`
>   ONLY**. THEN "the interceptor needs no change" becomes TRUE (eval/exec/__import__ are not interceptor
>   rules; os_system + bare_except stay strict everywhere). See revised §4(3) + §5.
> - **[CR-2] seam5 misses the orchestrator COMMIT-TIME validate_code sites (Agent1 + compiler, ELEVATED).**
>   `validate_code` is also called directly at `orchestrator.py:1149` (manifest) + `:1188` (partial-edit
>   `__JANUSMASK_PATCHES__`) + `:1209` — the dominant commit path (nearly every landing is a partial edit).
>   Threading the relax only through `harness/hooks/rpc/submit_code.py::validate`/`ensure_valid` (NOT
>   "rpc_submit_code" — real path is `harness/hooks/rpc/submit_code.py:71`/`:78`) → `ast_enforcer.validate_code:187`
>   covers submit only. For external eval/exec to be "allowed at commit" the relax MUST also reach the
>   orchestrator wrapper around `:1149`/`:1188`/`:1209` (reads external-ness from the in-scope `task` dict).
>   Audit `mcp_server.py:23` as a 4th `validate_code` reader (confirm it isn't a divergent submit path).
> - **[CR-3] §4(6) re-rooting `worktree_root` BREAKS path-containment (Agent2 + compiler, ELEVATED — CRITICAL,
>   core mechanism unspecified).** Staging is a SIBLING: `orchestrator.py:1809`
>   `staging_path = worktree_root.parent / "<name>_<tid>_staging"`, and `create_staging_worktree` HARD-RAISES
>   if it isn't a sibling (`git_integration.py:1268`). Re-rooting `worktree_root` to the external repo forces
>   the staging worktree into the external repo's PARENT dir — OUTSIDE `effective_target_root()`, contradicting
>   §4(6)'s own CRITICAL path-containment rule. **DECISION REQUIRED before any §4(6) brief:** either (i) relax
>   the sibling constraint for external mode + place staging in a dedicated `.janusmask_staging/` under the
>   external repo (gitignored, cleaned), or (ii) keep the sibling and document it as a contained-by-design
>   exception NOT under `effective_target_root()`. The plan as written cannot be implemented.
> - **[CR-4] §4(6) `commit_accepted_output` needs a SIGNATURE change, not a one-line `:604` edit (Agent2 +
>   compiler, ELEVATED — CRITICAL).** `parent_root` is derived from `cwd=state_dir` (always JM) at BOTH `:605`
>   AND `:659`; signature `(task_id, target_file, state_dir, worktree_root=None, *, ...)` has NO `working_dir`.
>   External target files then `relative_to(parent_root)` (`:631`/`:662`) → ValueError or mis-rebase. **FIX:
>   thread a kw-only `working_dir`/`parent_root` through `commit_accepted_output` + `_commit_accepted_output_multi`
>   + `_commit_accepted_output_patches`; retarget BOTH derivations (`:605` AND `:659`).** The §2(a)
>   `untracked_files=[]` gate must key on the retargeted parent/`working_dir`, NOT on `worktree_root` (which is
>   often the staging path at the call site).
> - **[CR-5] FLAG#2 fix is INCOMPLETE — embedded + fuzz also run UNJAILED when sandbox off (Agent3 + compiler,
>   ELEVATED — CRITICAL).** Beyond the 4 `_auto_commit_accepted` shell sites, `embedded_test_runner.py` runs
>   raw when `not sandboxed` (the `if sandboxed:` jail block is simply skipped → bare `subprocess.run`) and
>   `narrow_fuzz/validation.py:298` does `else: argv=['python3','driver.py']` → Popen unjailed — both execute
>   ATTACKER-controlled code on the host. **The external hard-fail-closed gate (refuse unless `sandbox_enabled()`)
>   must cover ALL THREE execute families**, and all three go in §5 invariants.
> - **[CR-6] FLAG#2 (and G3/T3/re-rooting/§2(a)) all need a `working_dir` reader in `_auto_commit_accepted`
>   that does NOT exist yet (Agents 1/2/3/4 + compiler, 5/5).** `_auto_commit_accepted(state_dir, task, task_id)`
>   (`:1542`) has ZERO `working_dir` refs today. `working_dir` is reachable only via `task.get('working_dir')`,
>   which is populated ONLY after seam3-stamp (§4-1) + daemon stamp-passing (§4-2) land. **Therefore FLAG#2's
>   refusal is INERT until §4(1)(2) land** (`task.get('working_dir')` is None → `_target_is_self(None)`==True →
>   refusal never fires). **Land a step-0 (inert, self-only): read `working_dir = task.get('working_dir')` at
>   `_auto_commit_accepted:1542` and thread it to all four sandbox branches + staging derivation + commit
>   calls, FIRST; then FLAG#2 gate; then re-rooting.** FLAG#2 must NOT land before the stamp wiring.
> - **[CR-7] The 5 overlapping edits to `_auto_commit_accepted`/`commit_accepted_output` must land as ONE
>   coordinated bundle (Agent4 + compiler + Agent2-ordering, 3/5).** FLAG#2 gate, §2(a) untracked-skip, G3
>   `.venv` inject, T3 retarget, and §4(6) re-root ALL edit the same symbol/region (`:1799/1809/1854/1960..`,
>   `commit_accepted_output`). Sequence them as one bundle so each pipeline edit doesn't re-ground on a shifted
>   symbol.
>
> **OTHER corrections (≥3/5) — APPLIED:**
> - **[CR-8] §2(b) binary-absent fail-open is a HARD §4 prerequisite, INDEPENDENT of FLAG#2 (Agents 3/4 +
>   compiler, 3/5).** sandbox can be ENABLED while `xdg-dbus-proxy` is absent → jail mounts the REAL host bus
>   (`agent_jail.py:287` region; `dbus_proxy_socket=None`) → systemd1 escape, even though `sandbox_enabled()`
>   passes the FLAG#2 check. For external these are two independent gates; both are required. Moved §2(b) into
>   the §4 prereq set.
> - **[CR-9] `_SENSITIVE_APPLY_GLOBS` external mapping is a NAMED §4 deliverable, not a parenthetical "decide"
>   (Agents 2/4 + compiler, 3/5).** The globs are JM-repo-relative; for an external repo the §1b approval
>   boundary either misfires or vanishes. Elevated to a §4(6) sub-deliverable with an oracle.
> - **[CR-10] §4(8) integration test is missing the hardest real cases (Agents 2/3 + compiler, 3/5).** Add:
>   (G) dirty external repo → stage/merge REFUSED, user tree byte-unchanged; (H) non-FF/diverged external repo
>   → `--ff-only` merge REFUSED, no corruption; (I) end-to-end accepted external output lands in the EXTERNAL
>   repo history AND nothing is written into the JM repo; (J) M2 untracked external test files NOT
>   auto-committed end-to-end; (K) host-ENV not leaked to the external verify spawn (see CR-11).
> - **[CR-11] Host-ENV leak is part of FLAG#2's blast radius (Agent3 + compiler, ELEVATED).** the unjailed
>   `shell=True` path passes `_vcmd_scrubbed_env()` which drops only `JANUSMASK_*` and copies the rest of
>   `os.environ` → an external attacker's `verification_command` gets the full host env (cloud creds,
>   `SSH_AUTH_SOCK`, etc.) if FLAG#2's refusal doesn't fire. Reinforces CR-5/CR-6.
>
> **ANCHOR FIXES (compiler-verified) — APPLIED to the Appendix:** `commit_accepted_output` def `:597`→**`:569`**;
> manifest read `:641`→**`:625`**; `staging.py` pop `:59`→**`:62`**; keyring bind `~:280`→**`:287-288`**.
> Confirmed-EXACT (no change): FLAG#2 `:1964/2103/2142/2171`; predicates `paths.py:73`/`:103`;
> `_SENSITIVE_APPLY_GLOBS:16`; ast_enforcer `:72`/`:79`/`:187` + os_system is its OWN `'os_system'` rule
> (`_check_os_system`, NOT fused into `'security'`); ast_verifier `verify:229`/os_system`:138`/bare_except`:167`.
>
> **NOT applied (below consensus / plan already correct):** §1(b) rewrite (refuted, 5/5 — keep only the oracle);
> §2(c) second session-budget counter (Agent4 + compiler, plan's "do NOT over-engineer" is right — explicitly
> DROP the second-counter option; `max_attempts`+quarantine+escalation-ceiling already bound it). The
> destructive-stash / dirty-tree-REFUSE claim (§4-6) was CONFIRMED accurate (4/5) — no correction, but add the
> dirty-check BEFORE `create_staging_worktree` (orchestrator `:1815`), not only inside `merge_staging_to_parent`.

---

## 0. Landed this session — VERIFIED @ `c31c7b4` (do not re-do) [agy R1 confirmed scope]

REV21 §1 + §3(a–e) + §4 non-activating seams. Workflow: SEED → worktree Opus sub-agent drives an
`agy`/Opus brief → adversarial review → prove oracle RED on HEAD → overseer ingests UNREAD (cp taskspec
→ `state/tasks`, oracle → `tests/`, write §1b decision, commit oracle RED-first, `impl_dispatch_once.sh`,
verify scope+GREEN+invariants+tree, push). All 13 commits below; agy R1 confirmed each is scoped to its
declared symbols with non-vacuous oracles.

| Commit | Item | Note (overseer + agy-R1) |
|--------|------|--------------------------|
| `94073e8` | §1 M2-GAPFILL | untracked-test poisoning deadlock fixed (Remedy A auto-allow + `untracked_files=[]` init; Remedy B scan+manifest → `worktree_root`). **R1/R3 caveat: re-opens in a FOREIGN repo under §4 — see §2(a).** |
| `53bf022` | §3(a) ORCHACC | `_auto_commit_accepted` 4 verify/baseline/accept/mutant pairs fail-CLOSED; try narrowed to proxy ctx-entry (R1 §2.1 confirmed correct). |
| `f5b7ad6` | §3(a) EASY3 | embedded/smoke/fuzz fail-close. |
| `50dc6c3`, `5b6fc80` | H2 realign | TEST-ONLY: mock `proxied_session_bus` to a succeeding fake CM. **R1 §2.2: does NOT weaken the oracles** (structural bwrap-argv assertions still run; fail-close itself is covered by `test_sec1c_*`). |
| `27dea44` | §3(b) CRED-EXFIL | `build_jail_argv(bind_credentials=)`; execute spawns drop cred dir binds + add `--unshare-net --unshare-ipc`; synthesis unchanged. **R1 §2.3 caveat: keyring socket bind NOT gated — see §1(a).** |
| `b09985c` | §3(c) RUNAWAY-CEILING | persisted counter + `_runaway_counter_bump` extra-node + both `_escalate_*`. **R1/R3 caveats: `a+`-mode race (§1(b)) + only bounds self-heal, not normal-task cascades (§2(c)).** |
| `b7b3afc` | §3(d) AUTHGATE-NEGCTRL | test-only proxy-filter policy guard (denies systemd1). SOUND. |
| `70e1384` | §3(e) ABSTRACT-WARN | `run_daemon`+`main` abstract-bus residual warning. SOUND. |
| `449d575` | §4 seam1 | `PlanningBrief.working_dir` OPTIONAL frontmatter field (no module constant). INERT. |
| `af68201` | §4 seam2 | TEST-ONLY keepout guard (planner dump excludes `working_dir`). |
| `c31c7b4` | §4 seam4 | trust-fork STRIP at `stage_task` + `impl_plan_to_queue.py` (strips ALL `working_dir` → self until a trusted caller passes the kw-only param). SOUND (R1 §2.6). |

**Owner decisions standing:** `full_stop` REMOVED (Phase A ACTIVE). G1 (external task origination)
AUTHORIZED. G2 (3-way AST relax) CONFIRMED — but see §4 G2 for the agy-recommended **`os_system`-stays-strict**
refinement.

**The M2 ↔ `full_stop` causal record [agy R3 §3.3] (owner-requested):** before M2-GAPFILL, a task that
wrote a new test during verification hit a scope-check rejection → auto-commit rejected. With `full_stop`
PRESENT this was a *static* halt (daemon stopped; operator restarts). With `full_stop` REMOVED, the same
rejection no longer halts the daemon: the task is marked `processed` (parked as a zombie) and, if it was
a self-heal run, triggers a retry/self-heal-escalation **credit-burn loop**. So removing `full_stop`
turned the M2 bug from a static failure into an **active unattended credit-burn risk** — which is why M2
was the #1 priority and was fixed this session (`94073e8`). The §4 foreign-repo residual (§2(a)) is the
last piece of the M2 story.

---

## 1. THIS-SESSION REGRESSION CANDIDATES — VERIFY FIRST, fix early [agy R1/R3]

These two are flagged as possible defects in code landed THIS session. The Claude review must CONFIRM or
REFUTE each against `c31c7b4` before anything else; if confirmed, fix early (small, pipeline-viable).

**(a) Keyring socket bind not gated by `bind_credentials` [agy R1-2, HIGH; VERIFY-FIRST].**
`agent_jail.py` reportedly ALWAYS binds the XDG keyring socket (`/run/user/<uid>/keyring`) and `bus` (or
proxy socket) when present, INDEPENDENT of `bind_credentials` (anchor cited ~`agent_jail.py:280`; the
CRED-EXFIL brief verified this region as FLAG#1=TRUE). With `bind_credentials=False` on execute spawns,
the `.gemini`/`.claude`/`.claude.json` binds are skipped but the keyring socket is not. **Mitigation
already present:** the execute spawns also get `--unshare-net --unshare-ipc`, so a cred read in-jail
cannot leave the host — net-unshare is the load-bearing control and IS applied. So this is a
defense-in-depth gap, NOT a live exfil hole (downgrade severity accordingly during review).
- **Fix:** wrap the keyring-socket bind inside the `if bind_credentials:` block (re-verify the exact
  bind lines @ HEAD — the CRED-EXFIL edit reshaped `build_jail_argv`). Single-symbol partial edit.
- Oracle: assert an execute-spawn argv (`bind_credentials=False`) does NOT bind `<xdg>/keyring`; assert a
  synthesis argv still does.

**(b) Runaway-counter `a+`-mode reset-to-0 race [agy R1-5 / R3-2 — REFUTED 5/5 by Claude review; DOWNGRADED].**
~~`_runaway_counter_bump` reportedly opens … in `a+` mode → malformed JSON → reset-to-0.~~ **RESOLVED: the
mode IS `a+` (`autowork_daemon.py:664`; agy read it right), but the function ALREADY holds
`fcntl.flock(LOCK_EX)` (`:665-669`) and does `seek(0)+truncate()+write` (`:685-688`) — after `truncate()`
EOF is 0, so the `O_APPEND` write lands at 0 and the JSON stays well-formed + monotonic on Linux
(empirically reproduced across simulated restarts; trips the ceiling correctly). NO live defect; the
proposed `r+`/atomic-replace rewrite is REDUNDANT.** Do NOT spend a pipeline cycle here.
- **Only residual:** the non-`fcntl` fallback path (`fcntl=None`) + a pre-existing corrupt file → the
  `except (ValueError, OSError): count=0` read (`:680`) silently resets to 1, losing the prior high count.
- **Optional (cheap, not required):** add a monotonicity oracle — seed a CORRUPT `runaway_ceiling.json`,
  assert the persisted count is NOT reset below the prior value. No production change otherwise.

---

## 2. M2 foreign-repo gating + unattended-safety residuals (Phase A active) [agy R1/R3]

**(a) M2 untracked-test auto-commit re-opens in a FOREIGN repo — MANDATORY before §4 external [agy R1-3 / R3 §1.3, HIGH].**
Under §4 external mode `parent_root`/`worktree_root` retarget to the external repo, so M2's
`git status --porcelain tests/` scan + auto-commit would sweep + commit the user's untracked test files
with NO `allowed_files` membership — re-opening the very poisoning vector M2 closed, in a foreign repo.
- **Fix (firm, agy R3 §1.2; REVISED by CR-4):** in `commit_accepted_output` (`git_integration.py`, inside the
  status `try` ~`:610`), when `not _target_is_self(<retargeted parent/working_dir>)` set `untracked_files = []`
  (better: skip the porcelain SCAN entirely so the user's repo isn't even scanned). **Key on the threaded
  `working_dir`/retargeted `parent_root`, NOT on the `worktree_root` arg** — at the `:1854` call site
  `worktree_root` is often the staging path, not the external root [CR-4]. Self-build keeps the M2 behavior.
  Accepted side-effect: an external task that legitimately authors a NEW test file will NOT have it committed
  (external test files must be pre-tracked) — document this. **This is a §4 prerequisite — land it WITH the
  external-commit re-rooting + the CR-4 signature change (§4-6), not before.**
- Oracle: external `working_dir` + dirty untracked test in the external repo → NOT auto-committed; self
  target → still auto-allowed.

**(b) Binary-absent fail-OPEN to the host D-Bus under unattended Phase A [agy R1-6, MEDIUM].**
When `xdg-dbus-proxy` is ABSENT (`shutil.which`→None) the jail degrades to `dbus_proxy_socket=None` and
mounts the REAL host session bus (`agent_jail.py:287` region) — the documented graceful-degrade. With
`full_stop` gone, unattended execution on a host lacking the proxy is fully fail-open to systemd1/D-Bus
escapes.
- **Fix (decide during review):** at daemon start (`run_daemon` + `--once`), if the host bus is active and
  `xdg-dbus-proxy` is absent, REFUSE to run unattended (raise) OR require an explicit operator opt-in
  flag. Coordinate with the §3(e) abstract-bus warn (same daemon-start hook). Verify whether the dev host
  HAS the proxy installed (it does this session) so this doesn't block the common path.
- **[CR-8] ELEVATED to a HARD §4 prerequisite, INDEPENDENT of FLAG#2.** `sandbox_enabled()` can be True while
  the proxy is absent → `dbus_proxy_socket=None` → host bus mounted → systemd1 escape, even though the FLAG#2
  (§3) sandbox-enabled check PASSES. For external these are two independent gates and BOTH are required. (3/5)

**(c) Runaway ceiling does not bound NORMAL-task fix-cascades [agy R1-4 / R3-1, MED/HIGH — CROSS-CHECK].**
The persisted ceiling (`b09985c`) sits at the two `_escalate_*` chokepoints (`:752`, `:2062`) — it bounds
SELF-HEAL cascades. agy claims it does NOT bound a normal user task that loops generate→fail→retry.
**Nuance to adjudicate in review:** a single normal task IS bounded by `max_attempts` (≈3) then
quarantined; the cascade *source* (`_retry_blocked_tasks`→`_escalate_to_autobrief`) IS under the ceiling.
The genuine residual is the ZOMBIE-parked brief (§2(d)), not infinite credit-burn. **Decide:** is a
session-window execution budget across ALL worker tasks warranted, or is `max_attempts`+quarantine+the
escalation ceiling already sufficient? Do NOT over-engineer; confirm a concrete unbounded path exists
before adding a second counter (and avoid double-counting the existing retry/quarantine machinery).
- **RESOLVED by Claude review (Agent4 + compiler):** verified there is NO unbounded credit-burn path —
  `_retry_blocked_tasks(max_attempts=3)` (`:867`) parks past the cap, and BOTH escalation funnels
  (`:700`/`:2006`) already call `_runaway_counter_bump` under the ceiling. **DROP the second-counter option.**
  The genuine residual is the ZOMBIE-parked brief (§2(d)) — observability, not safety.

**(d) Zombie parked briefs [agy R3-3, LOW].**
A task that fails auto-commit is moved to `tasks/processed/` unaccepted; its parent brief can remain
`queued`/`in_flight` forever, requiring manual cleanup. Add an operator-visible telemetry/alert when a
task is parked unaccepted (`brief_status.py` region ~`:95`), and/or a reclamation path. Low priority,
observability not safety.

**(e) `state/tasks/blocked/` garbage-collection cleanup pass [OVERSEER / NON-PIPELINE housekeeping, LOW].**
Surveyed end of the REV21-exec session: the active queue is CLEAN (0 queued, 0 outbox, this session's 8
tasks all processed-accepted), but `state/tasks/blocked/` holds **18 distinct stale task IDs (28 files
incl. `.retry`/`.exhausted` variants), dated 2026-05-21 → 2026-06-01 — NONE from REV21-exec**. Several are
ORPHANED: the work shipped later under a different attempt while the old blocked taskspec was never GC'd
(e.g. `PHASE_WHOLE_FILE_DRIFT_GUARD` blocked but landed `862f329`; `PHASE_FIX_ESCALATE_AUTOBRIEF_MOCKS_B`
landed `34c32d7` while `_MOCKS`/`_MOCKS_A` sit blocked). They carry `.exhausted`/retry-budget markers and
the queue is empty, so they do NOT burn credits or block dispatch even under unattended Phase A — this is
hygiene, not safety.
- **This is NOT a pipeline task** (no production code, no oracle): `state/` is gitignored operational
  state. Do it as an overseer/operator pass, NOT via `impl_dispatch_once.sh`.
- **Procedure:** for each distinct blocked ID, check `git log --all --oneline | grep <id>` for an
  `Integrate validated code for <id>` (or sibling) landing. If the work SHIPPED → the blocked entry is
  orphaned → remove its `.json`/`.retry.json`/`.exhausted` files. If NOT shipped and still relevant →
  KEEP and list it (with a one-line "what it was + why still open") so the owner can decide to re-brief or
  abandon. If superseded by a renamed/re-scoped task → remove + note the supersessor. Produce a short
  `~/janusmask_briefs/blocked_triage_<date>.md` report (kept survivors + removed orphans + their landing
  shas). Do NOT touch `state/tasks/processed/` (324, normal history) or anything currently queued.
- Pairs with (d): if a reclamation/telemetry path is added, wire it to also surface long-stale `blocked/`
  entries so this graveyard does not silently re-accumulate.

---

## 3. FLAG#2 — unjailed `shell=True` when sandbox is OFF [agy R1-1, CRITICAL]

When `sandbox_enabled` is False, the verify/baseline/mutant runs fall back to
`subprocess.run(..., shell=True, executable='/bin/bash')` on the HOST (anchors `orchestrator.py:1964`,
`2103`, `2142`, `2171`). For SELF-builds on a trusted host this is the existing behavior. **For §4
external mode it is a severe hole: attacker-controlled `verification_command`/tests would run UNJAILED on
the host with full creds + network** — AND the unjailed path passes `_vcmd_scrubbed_env()` which drops
only `JANUSMASK_*` and copies the rest of `os.environ`, so the host env (cloud creds, `SSH_AUTH_SOCK`, …)
leaks to attacker code too [CR-11].
- **[CR-5] SCOPE CORRECTION — THREE execute families run unjailed when sandbox is OFF, not one:** (i) the
  4 `_auto_commit_accepted` `shell=True` sites above; (ii) `embedded_test_runner.py` — the `if sandboxed:`
  jail block is simply SKIPPED → bare `subprocess.run(collect_argv/run_argv)`; (iii) `narrow_fuzz/validation.py:298`
  `else: argv=['python3','driver.py']` → Popen. The hard gate MUST cover all three.
- **Fix (hard fail-closed gate):** when `not _target_is_self(working_dir)`, REFUSE any verify/execute
  spawn unless `sandbox_enabled()` is True (raise; never fall through to `shell=True`/raw run) — in ALL
  THREE families. Add all three to §5 invariants.
- **[CR-6] ORDERING — this gate is INERT until §4(1)(2) land.** `_auto_commit_accepted(state_dir, task,
  task_id)` (`:1542`) has NO `working_dir` today; it is reachable only via `task.get('working_dir')`, which
  is populated only after seam3-stamp + daemon stamp-passing. Before that, `task.get('working_dir')` is None
  → `_target_is_self(None)`==True → the refusal NEVER fires. So FLAG#2 must land WITH/AFTER §4(1)(2), never
  before. **Step-0 prereq:** add `working_dir = task.get('working_dir')` at `_auto_commit_accepted:1542` and
  thread it to the four sandbox branches + staging derivation + commit calls (inert, self-only) FIRST.
- **[CR-7]** Coordinate as ONE bundle with §4 G3/T3/re-rooting/§2(a) — they all edit this same symbol/region.
- This is a PREREQUISITE for activating §4 external execution.
- Oracle: external `working_dir` + sandbox disabled → RuntimeError refusal, NO `shell=True` host run AND no
  raw embedded/fuzz run, NO host-env leak; self target + sandbox disabled → existing behavior preserved.

---

## 4. External-project capability — ACTIVATION bundle (re-anchored @ `c31c7b4`) [agy R2 + R4]

> Non-activating plumbing DONE this session (seams 1/2/4). The items below ACTIVATE gate-relaxation /
> external targeting. **Every G2 relax that lands RE-TRIGGERS the owner's Phase-A 8-point review; §4 is
> NOT safely parallel with Phase A.** Predicates `_target_is_self`/`effective_target_root` EXIST
> (`paths.py:73`/`:103`). Ordered sequence (agy R2 §2), all PIPELINE-FIRST:

**Prereqs (land before/with activation) [revised by Claude review]:** **step-0** `working_dir` reader in
`_auto_commit_accepted:1542` [CR-6] (inert, self-only, FIRST); §1(a) keyring gate (**CONFIRMED**, defense-in-depth);
§3 FLAG#2 hard gate over ALL THREE execute families [CR-5]; §2(a) M2 foreign-repo gate (with the re-rooting);
**§2(b) binary-absent fail-open refusal [CR-8] — a HARD prereq, INDEPENDENT of FLAG#2 (sandbox can be ON while
the proxy is absent → host bus).** The §3/§2(a)/G3/T3/§4(6) edits collide on `_auto_commit_accepted`/
`commit_accepted_output` → land as ONE coordinated bundle [CR-7].

**(1) seam3 STAMP — `persist_plan` [agy R2 §1.1].** `harness/planner/cli.py::persist_plan` (`:86`, holds
`brief_obj`; injects `source_brief_*` at `:95-101`). Stamp the trusted `working_dir` from `brief_obj` into
the plan JSON there (NOT from any LLM field). INERT until the daemon passes it (next item).
- Oracle: a brief with `working_dir` → the persisted plan JSON carries it; absent → not present.

**(2) DAEMON stamp-passing wiring [agy R2 §1.2].** `autowork_daemon.py:1223` calls
`stage_task(plan_path, tid, state_dir, canonical=True)` without `working_dir`. Read `working_dir` from the
plan JSON and pass it to the seam-4 trusted kw-only param: `stage_task(..., working_dir=working_dir)`.
This connects seam3→seam4 (the trusted value survives the strip; any LLM dict value is still stripped).
- Oracle: a plan with a stamped `working_dir` → the staged task JSON carries exactly that value; a plan
  with an LLM-injected task-dict `working_dir` but no stamp → stripped.

**(3) seam5 / G2 — `decide_submission` + AST relax [agy R2 §1.3; REVISED by Claude review CR-1/CR-2]. RE-TRIGGERS PHASE A.**
`harness/hooks/_decide_common.py::decide_submission` (`:80`) reads the stamped `task.working_dir` and
computes `relax_external = not _target_is_self(working_dir)` (fail-safe-to-self when absent). Thread a NEW
`relax_external_constructs` param through `harness/hooks/rpc/submit_code.py::validate`/`ensure_valid`
(`:71`/`:78` — the real file; NOT a `rpc_submit_code` module) → `ast_enforcer.validate_code` (`:187`).
- **[CR-2] ALSO thread it to the orchestrator COMMIT-TIME `validate_code` calls** — `orchestrator.py:1149`
  (manifest), `:1188` (partial-edit `__JANUSMASK_PATCHES__`), `:1209` — these are the dominant commit path
  (nearly every landing is a partial edit) and read external-ness from the in-scope `task` dict. Threading
  only through `submit_code.py` covers SUBMIT but not COMMIT → eval/exec would be allowed at submit yet
  REJECTED at the orchestrator commit, breaking the oracle. Audit `mcp_server.py:23` (4th `validate_code`
  reader) as not-a-divergent-submit-path.
- **ast_enforcer:** the `'security'` rule fuses `eval`/`exec`/`__import__` (`:72`) AND credentials (`:79`);
  `os_system` is its OWN separate `'os_system'` rule (`_check_os_system`, NOT fused into `'security'`).
  The new param must suppress ONLY the eval/exec/`__import__` branch — keep the `'security'` rule NAME
  (downstream telemetry/consumers depend on it) and KEEP credential scanning strict.
- **Live interceptor `services/neurosymbolic/ast_verifier.py` (`verify` `:229`):** has NO relax seam and
  flags `os_system` as a hard ERROR (`:138`) AND `bare_except` as a hard ERROR (`:167`). **DECISION
  [agy R2 §1.3, R1-cross]: DROP `os_system` from the external-relax set — keep it STRICT everywhere.**
- **[CR-1] DECISION (Claude review): ALSO DROP `bare_except` from the external-relax set.** `bare_except`
  IS a live interceptor rule (`:167`, ERROR) that runs at submit/write via `interceptors.py:53`
  (`ASTVerifier()`, no task context, no relax seam). Relaxing it only in the commit-time enforcer would make
  submit STRICTER than commit → an external task using `except: pass` is denied at synthesis, breaking the
  workflow AND inverting submit ⊆ commit. So the external relax = **`eval`/`exec`/`__import__` ONLY**;
  credentials + `os_system` + `bare_except` + nondeterminism stay STRICT (force `allow_nondeterminism=False`
  external, ignoring the meta-task auto-relax).
- F2 parity: with `os_system` AND `bare_except` kept strict, the interceptor needs NO change (eval/exec/
  `__import__` are genuinely not interceptor rules) — so NO interceptor-level relax plumbing or task-context
  threading is required. This is the whole point of the CR-1 decision.
- Oracle: external target → eval/exec/`__import__` allowed at submit AND commit (incl. the partial-edit
  path); credentials + os_system + bare_except blocked; self target → all strict.

**(4) G3 — target `.venv` binding [agy R2 §1.4].** Bind `<working_dir>/.venv` (prefix/bin) as a
CODE-injected list on the execute spawns — `orchestrator.py` verify/baseline/mutant `build_jail_argv` at
**`1960`/`2099`/`2138`/`2167`** (proxy-branch; the `=None` branches are now refusals), embedded
`embedded_test_runner.py:183`/`:231`, fuzz `narrow_fuzz/validation.py:292`. Keep `verify_extra_ro/rw`
EMPTY in config (inject in code). Coordinate with §1(a)/§3/T3 (same region).

**(5) T2–T5 retarget [agy R2 §1.5].** T3 staging-root: `orchestrator.py:1799`
(`git rev-parse --show-toplevel cwd=state_dir.parent`) + `:1809` (`staging_path=`) — for external, derive
from `effective_target_root(working_dir)` not `state_dir.parent`. Synthesis `repo_root=PROJECT_DIR`
(`:391`) follows the target for external; `JANUSMASK_PROJECT_DIR`/`PYTHONPATH` STAY self. Embedded
`PROJECT_ROOT` (`embedded_test_runner.py:115`, used `:185`/`:233`) threaded from `working_dir`. T5 no-op
ONLY `_maybe_push_and_rebase_pin` (`autowork_daemon.py:1599` def / `:1791` call) for external.

**(6) External-commit RE-ROOTING — the largest deliverable [agy R4; HEAVILY REVISED by Claude review]. RE-TRIGGERS PHASE A.**
The staging worktree is a `git worktree` OF the JM repo; unretargeted, accepted external output FF-merges
into JM master (HIGH corruption risk, R4 §3.1). Re-root the WHOLE chain for `not _target_is_self`:
- **[CR-3] BLOCKER — staging placement contradiction (MUST be resolved before any §4(6) brief).** Staging is
  a SIBLING of `worktree_root`: `orchestrator.py:1809`
  `staging_path = worktree_root.parent / "<name>_<tid>_staging"`, and `create_staging_worktree` HARD-RAISES
  (`git_integration.py:1268`: "Staging worktree must be placed in a sibling directory of the repository
  root.") if it isn't. So re-rooting `worktree_root` → `effective_target_root(working_dir)` would put the
  staging worktree in the external repo's PARENT dir — OUTSIDE `effective_target_root()`, contradicting the
  path-containment rule below. **DECIDE first:** (i) relax the sibling constraint for external mode + place
  staging in a dedicated gitignored `.janusmask_staging/` INSIDE the external repo (then clean it), re-speccing
  the `:1268` check; OR (ii) keep the sibling and document it as a contained-by-design exception NOT under
  `effective_target_root()`. As written, item (6) is not implementable.
- `orchestrator.py:1799` `worktree_root` → `effective_target_root(working_dir)`. `create_staging_worktree`
  call `:1815`; `commit_accepted_output` call `:1854`; `merge_staging_to_parent` call `:2203` follow.
- **[CR-4] `commit_accepted_output` needs a SIGNATURE change, not a one-line edit.** `parent_root` is derived
  from `cwd=state_dir` (always JM) at BOTH `:605` AND `:659`; the signature
  `(task_id, target_file, state_dir, worktree_root=None, *, allowed_files, meta_task_type, approval_ok)`
  has NO `working_dir`. External target files then `relative_to(parent_root)` (`:631`/`:662`) → ValueError /
  mis-rebase. Thread a kw-only `working_dir` (or explicit `parent_root`) through `commit_accepted_output` +
  `_commit_accepted_output_multi` (`:815`) + `_commit_accepted_output_patches`; retarget BOTH derivations
  (`:605` AND `:659`) to `effective_target_root(working_dir)` for external. The §2(a) `untracked_files=[]`
  gate must key on THIS retargeted parent/`working_dir`, NOT on `worktree_root` (which is the staging path at
  the call site).
- `git_integration.py`: `create_staging_worktree` (`:1251`, sibling check `:1268-1269` — see CR-3, `git
  worktree add` `:1294`); `merge_staging_to_parent` (`:1351`, `--git-common-dir` `:1368`, status `:1390`,
  stash `:1395`, ff-merge `:1409`).
- **Dirty-tree REFUSE [agy R4 §3.2, HIGH — CONFIRMED 4/5]:** `merge_staging_to_parent` stashes parent changes
  with `-u` (`:1395`) and on pop-conflict does `git reset --hard HEAD` (`:1426`) + `git stash drop` (`:1442`)
  — genuinely DESTRUCTIVE of a user's external working changes. In external mode, REFUSE to stage/merge if the
  external repo is dirty (fail closed; never stash/pop-drop a user repo). **Put the dirty-check BEFORE
  `create_staging_worktree` (orchestrator `:1815`), not only inside `merge_staging_to_parent`** — so no staging
  worktree is even created against a dirty external repo.
- **[CR-10] Non-FF / diverged external history:** `:1409` uses `git merge --ff-only`. For SELF-builds the
  detached staging base always FF-merges; an EXTERNAL repo with concurrent user commits (or a diverged base)
  will NOT be FF-able → `RuntimeError` (`:1411`) → task blocked. Spec this explicitly: keep `--ff-only`
  (fail-closed, never auto-merge into a user's diverged branch) and document non-FF external as REFUSED, OR
  have the bootstrap create a dedicated JanusMask branch to merge onto. Add a test case (§4(8) H).
- **Path-containment [agy R4 §3.3, CRITICAL]:** resolve all paths via `.resolve()` and enforce all writes
  strictly within `effective_target_root()` (the predicate already resolves-first, but it only CLASSIFIES —
  it does NOT enforce write-containment; add an explicit assert that bind + commit paths cannot escape via
  `..`/symlink, and exercise it in §4(8) case C).
- **[CR-9] `_SENSITIVE_APPLY_GLOBS` external mapping — a NAMED sub-deliverable, not a deferred "decide".** The
  globs (`harness/**`,`config/**`,`scripts/**`,`services/**`) are JM-repo-relative; for an external repo they
  are meaningless → either an external target with its own `harness/` trips self-protection, or the §1b
  approval boundary VANISHES for external commits. Define the external mapping (and where the §1b approval
  boundary sits for external commits) WITH an oracle, before activation.

**(7) Bootstrap `harness/target_bootstrap.py`.** idempotent git-init/`.gitignore`/initial-commit/`.venv`+deps/
staging worktree, gate-bearing on a recorded marker; REFUSE a dirty/foreign-`.git`-it-doesn't-own tree
(ownership check); `.resolve()` before the marker check; reachable from BOTH `run_daemon` AND `--once`.

**(8) External-mode INTEGRATION TEST — GATING deliverable [agy R4 §4; cases G-K added by Claude review CR-10].** fixture external repo, cases:
(A) external relax applies (eval/exec/`__import__` allowed; bare_except + os_system STILL blocked — see CR-1);
(B) self-target KEEPS strict gates; (C) malicious `working_dir` (into `state/`/`agent_workroot()`/`..`/symlink)
REJECTED/demoted-to-self **AND write-containment enforced (not just predicate classification)**; (D) target
`.venv` is the interpreter used; (E) `_target_is_self` importable + fail-safe INSIDE the jailed worker hook;
(F) ancestor-OR-descendant `working_dir` (inside the JM tree) treated as SELF (known usability constraint
— external targets MUST live OUTSIDE the JM tree).
- **(G)** dirty external repo → stage/merge REFUSED, the user's external working tree byte-UNCHANGED (CR-4/§4-6 dirty-REFUSE).
- **(H)** non-FF / diverged external repo → `--ff-only` merge REFUSED, no corruption (CR-10).
- **(I)** end-to-end: accepted external output lands in the EXTERNAL repo's git history AND NOTHING is written into the JM repo (proves CR-3/CR-4 re-rooting end-to-end).
- **(J)** M2 untracked external test files NOT auto-committed end-to-end (not just the unit predicate).
- **(K)** host-ENV NOT leaked to the external verify spawn; sandbox-OFF external → refusal in all three execute families (CR-5/CR-11).

**THEN owner Phase-A 8-point re-review** against the post-relax gate shape.

---

## 5. Invariants carried through EVERY phase (do-NOT) — re-verified @ `c31c7b4`

- `grep -c "synthesis_success = True"` **==1** in `harness/orchestrator.py` and `harness/orchestrator_worker.py`.
- `skip_interface_fuzz` ONLY `test_authoring`; never narrow `BYPASS_FUZZER_TYPES`.
- `_SENSITIVE_APPLY_GLOBS == ('harness/**','config/**','scripts/**','services/**')` (`git_integration.py:16`).
  Never remove `services/**`.
- `verify_extra_ro`/`verify_extra_rw` ABSENT/empty in `harness/config.yaml`; config byte-clean. §4 G3
  injects the target `.venv` in CODE.
- **SEC-1:** every EXECUTE `build_jail_argv` threads `dbus_proxy_socket=`; synthesis + self-heal + the 4
  verify/baseline/accept/mutant pairs + embedded/smoke/fuzz are fail-CLOSED (raise when proxy resolves but
  fails to start). Do NOT re-introduce a `=None` host-bus fallback. (Binary-ABSENT degrade is the §2(b)
  residual.)
- **CRED-EXFIL:** execute spawns carry `bind_credentials=False` + `--unshare-net --unshare-ipc`; synthesis
  spawn keeps creds+net. (§1(a): also gate the keyring-socket bind once confirmed.)
- **NEW (FLAG#2) [CR-5]:** when `not _target_is_self(working_dir)`, NEVER run a verify/execute spawn unjailed;
  refuse unless `sandbox_enabled()` — in ALL THREE execute families: `_auto_commit_accepted` `shell=True`
  (`:1964/2103/2142/2171`), `embedded_test_runner` (`if sandboxed:`-skip raw run), and
  `narrow_fuzz/validation.py` (`else: argv=['python3','driver.py']` Popen). No host-env leak on the refused path.
- **NEW (M2 external):** untracked-test auto-detect/commit DISABLED when `not _target_is_self`.
- `_target_is_self`/`effective_target_root` fail-safe-to-self, resolve-first; LLM `working_dir` STRIPPED at
  `stage_task` + `scripts/impl_plan_to_queue.py`; trusted value travels ONLY via the `persist_plan` stamp →
  daemon → `stage_task` kw-only param. `JANUSMASK_PROJECT_DIR`/`PYTHONPATH` STAY self.
- **G2 parity [CR-1]:** submit-time interceptor ⊆ commit-time enforcer; external relax = **eval/exec/`__import__`
  ONLY**; credentials + `os_system` + **`bare_except`** + nondeterminism STRICT for all (bare_except is a live
  interceptor ERROR with no relax seam — relaxing it only at commit would invert submit ⊆ commit); force
  `allow_nondeterminism=False` external. Thread the relax to BOTH submit (`submit_code.py`) AND commit
  (`orchestrator.py:1149/1188/1209`) [CR-2]. Any G2 relax RE-TRIGGERS Phase A.
- `full_stop` REMOVED — Phase A ACTIVE. §1b (`_apply_approval_granted`) is the autonomous-commit boundary;
  agents tree-isolated ONLY via the bwrap jail.
- **agy is NOT tree-isolated** → after any agy run verify byte-identical + revert drift.

---

## Appendix — re-verified anchors (@ `c31c7b4`; re-grep before use) [agy R2 + R4]

- `harness/orchestrator.py`: `spawn_agent` synthesis `repo_root=PROJECT_DIR` `:391`; `_auto_commit_accepted`
  fail-closed raises `:1948`/`2087`/`2126`/`2155`; proxy-branch verify `build_jail_argv` `:1960`/`2099`/
  `2138`/`2167`; **unjailed `shell=True` fallback (FLAG#2) `:1964`/`2103`/`2142`/`2171`**; T3 staging-root
  `git rev-parse cwd=state_dir.parent` `:1799`, `staging_path=` `:1809`, `create_staging_worktree` call
  `:1815`, `commit_accepted_output` call `:1854`, `merge_staging_to_parent` call `:2203`.
- `harness/git_integration.py`: `_SENSITIVE_APPLY_GLOBS` `:16`; `commit_accepted_output` **def `:569`**
  (`parent_root` derive `:605` AND again `:659` [CR-4], M2 untracked init `:609`, status scan `:611`
  `cwd=worktree_root`, manifest read **`:625`**); `_commit_accepted_output_multi` `:815`;
  `create_staging_worktree` `:1251` (sibling raise `:1268-1269`, worktree add `:1294`);
  `merge_staging_to_parent` `:1351` (common-dir `:1368`, status `:1390`, stash `:1395`, ff-merge `:1409`).
- `harness/agent_jail.py`: `build_jail_argv` (`bind_credentials` kwarg; keyring/bus bind loop **`:280-288`**,
  keyring bind **`:287-288`** — UNGATED by `bind_credentials`, wrap in `if bind_credentials:` [§1(a) CONFIRMED];
  `--unshare-net --unshare-ipc` for `bind_credentials=False` `:129-130`; binary-absent `dbus_proxy_socket=None`
  host-bus mount `:287` [§2(b)/CR-8]).
- `harness/autowork_daemon.py`: `_runaway_counter_bump` `:622` (counter write ~`:664`, default-0 read
  ~`:680`); `_escalate_to_autobrief` ceiling check `:752`; `_escalate_inactivity` `:2062`; daemon
  `stage_task` call `:1223`; `_maybe_push_and_rebase_pin` def `:1599` / call `:1791`.
- `harness/planner/cli.py`: `persist_plan` `:86` (source_brief_* inject `:95-101`).
- `harness/planner/staging.py`: `stage_task` (kw-only `working_dir` `:16`, `task.pop('working_dir')` **`:62`**, trusted reinject `:63-64`).
- `scripts/impl_plan_to_queue.py:56` (`task.pop('working_dir')`).
- `harness/hooks/_decide_common.py`: `decide_submission` `:80`. `harness/hooks/rpc/submit_code.py`:
  `validate` `:71`, `ensure_valid` `:78` (both call `validate_code`) [CR-2 — the real file; not "rpc_submit_code"].
- `harness/orchestrator.py`: COMMIT-TIME `validate_code` calls `:1149` (manifest) / `:1188` (partial-edit) /
  `:1209` [CR-2 — relax MUST reach these]; `mcp_server.py:23` 4th reader (audit).
- `harness/ast_enforcer.py`: `validate_code` `:187`; `'security'` rule fuses eval/exec/`__import__` `:72` +
  credentials `:79`; `os_system` is its OWN `'os_system'` rule (`_check_os_system`, NOT under `'security'`).
  `services/neurosymbolic/ast_verifier.py`: `verify` `:229`; `os_system` ERROR `:138` AND **`bare_except`
  ERROR `:167`** — instantiated `interceptors.py:53` with NO relax seam → keep BOTH `os_system` AND
  `bare_except` strict (decision §4 G2 / CR-1).
- `harness/embedded_test_runner.py`: `PROJECT_ROOT` import `:115`, `build_jail_argv` `:183`/`:231`
  (`repo_root=PROJECT_ROOT` `:185`/`:233`). `harness/narrow_fuzz/validation.py`: `build_jail_argv` `:292`.
- `state/control/autowork/full_stop`: **ABSENT** (Phase A active).
- Review reports: `~/janusmask_briefs/review_rev22/R{1..4}_*.md` (agy; Opus-cross-check at the next-session
  Claude review — verify every `[agy R#]` claim, esp. the §1 VERIFY-FIRST pair, against `c31c7b4`).
