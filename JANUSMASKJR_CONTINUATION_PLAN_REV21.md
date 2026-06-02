# JanusMaskJR — Continuation Plan (2026-06-02, rev 21)

> **rev 21 — DRAFT. Written after the REV20 §2 Phase-1 gate-ii closer scope was EXECUTED this session (8 dual-agent
> pipeline landings + 1 justified hand-edit + the §3 trust foundation, code `a2f35a4`→`b5eb8b5`, all PUSHED to
> `origin/master`) and then adversarially re-reviewed by a 4-area cross-vendor `agy` (Antigravity Gemini) panel
> (reports in `~/janusmask_briefs/review_rev21/R{1..4}_*.md`).** Supersedes `JANUSMASKJR_CONTINUATION_PLAN_REV20.md`.
>
> **CADENCE — CLAUDE-REVIEWED 2026-06-02 (amended IN-PLACE).** A 5-reviewer adversarial Claude pass (4 worktree sub-agents +
> compiler, codebase-memory-mcp grounded, all anchors re-grepped @ `b5eb8b5`) applied every 3/5-consensus correction below as
> `[CLAUDE-REV]` markers, focus on §4 (external-project capability). Strong code-verified but below-consensus security findings
> are flagged `[CLAUDE-REV — single-reviewer, verify]` (do NOT skip them: keyring-socket exfil §3(b), disabled-sandbox bypass
> §3(b)). NEXT session: execute. Nothing below is "executed this session" beyond §0 (git-verified). Forward items are proposals.
>
> **Governing rule (owner directive, carried):** use the JanusMaskJR PIPELINE for every change wherever possible;
> HAND-EDIT only AFTER a pipeline attempt FAILS with a PERMANENT/structural blocker (never a timeout, never a
> re-groundable stale-ground-truth or mis-render). **THIS SESSION'S CONCRETE LESSON (justifies the one hand-edit):** a
> module-level CONSTANT edit (`_SENSITIVE_APPLY_GLOBS`, an `ast.AnnAssign`) is a PERMANENT pipeline blocker — the symbol
> route `_apply_symbol_patch` only resolves `def`/`class` nodes and KeyErrors on `AnnAssign`, while the whole-file route
> AST-unparses and STRIPS comments (which carry the security rationale). Both routes exhausted ⇒ hand-edit justified
> (`03fc91a`). Cite this pattern before any future constant hand-edit.
>
> **Brief authoring:** delegated to `agy` + an independent Opus review inside a worktree-isolated sub-agent.
> Agents (authors, reviewers) MUST use **codebase-memory-mcp** (project `home-xnihil0zer0-JanusMaskJR`, index ready) to
> understand structure before acting. **agy is NOT tree-isolated → it leaks oracle/edit files into the MAIN tree via
> `--add-dir <abs path>`; verify byte-clean + revert drift after EVERY agy run.** In `verification_command`, QUOTE EACH
> pytest path SEPARATELY (a single concatenated path string mis-collects).
>
> **HEADLINE (honest status):** Owner has REMOVED `state/control/autowork/full_stop` — **Phase A is ACTIVE, the daemon
> may run unattended.** That makes the residual gate-ii holes URGENT, not deferred. SEC-1 is wired everywhere but
> **only PARTIALLY fail-closed** (synthesis + self-heal fail-closed; the 8 verify spawns + embedded/smoke/fuzz still
> fail-OPEN to the host bus). The M2 untracked-test-poisoning gap is now a **permanent unattended-queue deadlock** risk.
> Credential-exfil on the verify/execute path is undefended (creds bound RW, net not unshared). These are REV21's first
> priorities. **§3 external-project capability remains owner-authorized but every G2 gate-relax that lands re-opens the
> Phase A 8-point review.**

---

## 0. Landed this session — VERIFIED @ `b5eb8b5` (do not re-do)

REV20 §2 Phase-1 gate-ii closers + the §3 trust foundation. Same workflow as prior sessions (SEED → worktree Opus
sub-agent drives an `agy`/Opus brief → adversarial review → prove oracle RED on HEAD → overseer ingests UNREAD → worker
→ Monitor → verify scope+GREEN+invariants+submissions+tree → push). agy panel R1: all 8 commits CONFIRMED scoped to
declared symbols, non-vacuous oracles, invariants intact — **with the honest caveats called out below.**

| Commit | Item | Note (overseer + agy-R1 verified) |
|--------|------|--------------------------|
| `a3c6669` | SEC-1 AUTHGATE-HARDEN | Live D-Bus escape-regression test. **CAVEAT (R1 §2.6): partially VACUOUS** — uses `org.freedesktop.DBus.Peer.Ping` for keyring reachability; does NOT force a token refresh, so a credential cache-hit gives a false GREEN. Test-only, no production change. Completion = REV21 §3(d). |
| `4ed4c4c` | DAEMON-ONCE-PROXY | `autowork_daemon.py::main` `--once` mirrors `run_daemon`'s singleton-proxy startup (`:1756-1804` [verified @ b5eb8b5]) so `--once` self-heal spawns get the filtered bus. SOUND. |
| `126e1b5` | SEC1-FAILCLOSED | `orchestrator.py::spawn_agent` (`:384-385`) + daemon `_contain_selfheal` (`:617`) fail-CLOSED. **CAVEAT (R1 §2.1, R4 §1.1): INCOMPLETE** — the 8 `_auto_commit_accepted` verify lines + embedded/smoke/fuzz still fail-OPEN to `dbus_proxy_socket=None`→host bus. Completion = REV21 §3(a). |
| `0e5edd3` | RUNAWAY-CEILING | Global self-heal escalation ceiling in `_escalate_to_autobrief`/`_escalate_inactivity` (`:661-675`, `:1943-1957` [verified @ b5eb8b5]). **CAVEAT (R1 §2.3, R4 §1.4): in-memory-only** (`_SELFHEAL_ESCALATION_COUNT` module global, wiped on restart/`--once`) AND counts only SELF-HEAL escalations, NOT normal-task fix-cascades. Hardening = REV21 §3(c). |
| `74cd149` | SEC1-DBUSADDR | `agent_jail.py::build_jail_argv` overrides `DBUS_SESSION_BUS_ADDRESS=unix:path=<xdg>/bus` (`dbus_proxy_socket` kwarg `:74`). **CAVEAT (R1 §2.2): does NOT kill the abstract-socket bypass** — net/IPC not unshared (`agent_jail.py:95-97` [verified]), a non-cooperative process reads `/proc/net/unix` and dials `unix:abstract=…` directly. Residual = REV21 §3(e). |
| `83a1298` | SEC1-ONCE-FAILFLAG | `--once` sets the proxy-failed flag on proxy exception. SOUND. |
| `03fc91a` | SEC_SERVICES_GLOB | **HAND-EDIT (justified — see governing rule).** Added `services/**` to `_SENSITIVE_APPLY_GLOBS` (`git_integration.py:16` [verified: `('harness/**','config/**','scripts/**','services/**')`]). Pipeline routes exhausted (AnnAssign symbol-route KeyError + whole-file comment-strip). |
| `b5eb8b5` | TARGET_PREDICATE | §3 keystone: `paths.py::_target_is_self` (`:73-101`) + `effective_target_root` (`:103-115`) [verified]. resolve-first, fail-safe-to-self=True; parent/sub/STATE_DIR/workroot all ⇒ self. Exhaustive unit tests. SOUND. |

**Owner decisions confirmed this session:**
- **`full_stop` REMOVED — Phase A ACTIVE.** The daemon may run unattended. (Verify: `state/control/autowork/full_stop` ABSENT.)
- **G2 CONFIRMED (3-way AST relax):** `eval`/`exec`/`__import__` + `os.system` + `bare_except` RELAX **external-only**;
  `credentials` ALWAYS strict (self AND external); FORCE `allow_nondeterminism=False` on external (verification
  reproducibility). Thread IDENTICALLY into BOTH engines for submit⊆commit parity. (Implementation = §4 G2.)

**Headline lesson (carried):** the dominant real auto-commit-failure cause remains stale existing-test assertions →
always run the FULL verification_command (incl. existing tests) against fixed scratch before dispatch.

---

## 1. M2-GAP-FILL — HIGH PRIORITY (now that `full_stop` is removed) [agy R3]

**The gap (R3):** when a task writes a new test file during verification, `commit_accepted_output` auto-detects untracked
`tests/test_*.py` via a git-porcelain scan, appends them to the multi-file manifest, and routes through
`_commit_accepted_output_multi` → `_enforce_apply_scope(allowed_files=set(files_touched))`. Because the new test was NOT
predicted in the task's `files_touched` (and the agent cannot edit the read-only staged task JSON), the scope check
REJECTS the whole accepted commit. **Under unattended operation this is a PERMANENT queue deadlock + self-heal credit
burn** (the agent regenerates the same test → same rejection → infinite retry/escalation). A second poisoning path:
leftover scratch `tests/test_*.py` in the PARENT repo poison EVERY task because the porcelain scan runs against
`parent_root`.

**RE-VERIFIED anchors @ `b5eb8b5` (R3's were ~off-by-a-few):**
- Porcelain scan: `harness/git_integration.py:607` — `_run_streamed_command(['git','status','--porcelain','tests/'], cwd=str(parent_root), …)` [verified]. (R3 said `:607` — correct.)
- Untracked-file build loop: `:608-615` (`fnmatch 'tests/test_*.py'`) [verified].
- Manifest write + multi-dispatch: `:618-647` — `sidecar_path` written at `:642`; `if sidecar_path.exists(): return _commit_accepted_output_multi(..., allowed_files=allowed_files, ...)` at `:646-647` [verified]. (R3 said `~:645-647` — correct.)
- The scope check that rejects: `_enforce_apply_scope` at `_commit_accepted_output_multi:853` [verified] (and the single-file path at `:665`).

**Remedy A — auto-allow harness-detected test files (R3 §3.1):** when the harness itself auto-detects and packages the
untracked `tests/test_*.py`, add them to the local `allowed_files` set before the multi-file dispatch. Since `tests/**`
is NOT in `_SENSITIVE_APPLY_GLOBS`, allowing harness-detected test ADDITIONS bypasses no security gate.
- At `git_integration.py:646-647`, before dispatching to `_commit_accepted_output_multi`, extend the passed
  `allowed_files`: `extended = set(allowed_files) | set(untracked_files)` when `allowed_files is not None and
  untracked_files`, and pass `allowed_files=extended`. Note `untracked_files` is in scope here (built `:608-615`) and is a
  list of repo-relative strings already shaped as `_enforce_apply_scope` expects.
  - **[CLAUDE-REV — code-verified, 2/5 but apply]** `untracked_files` is bound at `:608`, which is INSIDE the `try:` opened
    at `:606`, AFTER the raising `git status` call at `:607`. If `:607` raises (timeout/git error → `except` at `:643`),
    `untracked_files` is UNBOUND when the dispatch at `:645-647` references it → `NameError` crashes the whole accept.
    Initialize `untracked_files = []` BEFORE the `try` at `:606` as part of this edit.

**Remedy B — narrow the porcelain scan to the staging worktree (R3 §3.2):** at `git_integration.py:607`, change
`cwd=str(parent_root)` → `cwd=str(worktree_root)` so detection sees ONLY the tests the agent authored during the task,
not pre-existing dirty parent-repo files. (`worktree_root` is in scope — resolved `:600-603`.)
- **[CLAUDE-REV — caller-verified; a "no-op" objection was RAISED and REFUTED]** Two reviewers initially flagged Remedy B as
  a no-op on the premise that `worktree_root == parent_root` (both from `git rev-parse --show-toplevel` cwd=`state_dir`). That
  is FALSE on the live accept path: the sole caller `orchestrator.py:1825` passes `worktree_root=staging_path` EXPLICITLY,
  so the `else` branch at `:603` binds `worktree_root` to the per-task `{name}_{task_id}_staging` git worktree (created
  `orchestrator.py:1780/:1786`), which is a DIFFERENT directory from `parent_root` (the JM toplevel, always derived `:604-605`).
  So narrowing the scan to `worktree_root` IS meaningful — it scopes detection to the agent's staging worktree. Remedy B stands.
- **[CLAUDE-REV — 3/5 consensus, PROMOTE the old caveat to a MANDATORY paired edit]** The manifest READ at `:638`
  (`file_in_parent = parent_root / filepath`) and `:640` MUST change to `worktree_root / filepath` IN LOCKSTEP with the `:607`
  cwd change. Otherwise a worktree-authored test that does not exist under `parent_root` yields `file_in_parent.exists()==False`
  at `:639` → silently dropped from the manifest → the test is never committed (a quieter deadlock; the M2 fix no-ops for the
  very files it detected). Also re-check the `target_path.relative_to(parent_root)` fallback (`:626-633`) for consistency.
  Oracle must assert the worktree-authored test's CONTENT lands in the manifest, not merely that no parent-dirty file poisons.
- **[CLAUDE-REV — §1↔§4 interaction, 1/5 — flag for review]** Under §4 external mode, `parent_root` becomes the EXTERNAL repo,
  so M2 auto-allow would scan/commit external untracked test files with no `allowed_files` membership — re-opening the
  poisoning vector in a foreign repo. Decide: DISABLE untracked-test auto-detect/commit when `not _target_is_self(working_dir)`.

**Pipeline tractability:** both edits live INSIDE `commit_accepted_output` (`def` at `:569`) — a single large `def`
symbol, NOT a module constant. The symbol route should apply cleanly (cf. the 690-line single-symbol
SEC-1c-ORCHACC repro). **Do NOT preemptively hand-edit** — only fall back if the symbol route fails with a permanent
blocker. Oracle: stage a task whose `files_touched` omits a `tests/test_*.py` the agent then writes; assert the commit
SUCCEEDS (Remedy A); and assert a dirty `tests/test_scratch.py` left in the PARENT does NOT poison an unrelated task
(Remedy B). Verification_command: the new oracle + the existing
`tests/.../test_*commit*` suite, each path quoted SEPARATELY.

---

## 2. Daemon-enable gating + Phase A status (re-evaluated @ `b5eb8b5`)

- **(i) OWNER-SUPERVISED single run:** met (`--once` proxy parity landed `4ed4c4c`).
- **(ii) UNATTENDED autonomous daemon — STILL NOT MET.** `full_stop` is removed so the daemon CAN run unattended, but it
  is NOT yet safe (R4 §2). Residuals, all addressed in §3:
  - **Verify-spawn fail-open (HIGH, R1 §2.1 / R4 §1.1):** the 8 `_auto_commit_accepted` verify lines + embedded/smoke/fuzz
    silently fall back to `dbus_proxy_socket=None`→host bus on proxy-spawn failure → systemd1/StartTransientUnit reachable.
  - **Credential-exfil on the execute path (HIGH, R4 §1.3):** verify/test/fuzz/smoke run untrusted (and, under §4, EXTERNAL)
    code in a jail that binds `~/.gemini`/`~/.claude` RW and does NOT unshare net → creds exfiltrable. The execute path is
    `/bin/bash -c` via `subprocess.run` and never routes through the AST interceptor.
  - **Runaway ceiling weak (MED, R1 §2.3 / R4 §1.4):** in-memory-only + self-heal-only; normal-task fix-cascades unbounded.
  - **Abstract-socket bypass (HIGH host-config-dependent, R1 §2.2 / R4 §1.2):** net/IPC not unshared; latent on a host
    whose session bus is `unix:abstract=…`.
- **Phase A (ACTIVE).** Owner has lifted `full_stop`. **Re-run trigger:** any §4 G2 gate-relax that lands MUST re-run the
  Phase A 8-point owner review against the post-relax gate shape (§4 sequencing note). Do NOT treat §4 as inert background.

---

## 3. Gate-ii / unattended-safety priorities — ORDERED PIPELINE TASKS [agy R1+R4]

Same workflow as §0. **Phase 1 = these closers; land BEFORE any §4 external buildout.** Now that `full_stop` is removed
these are PRIORITY, not deferred.

**(a) PHASE_SEC1_FAILCLOSED_VERIFY (HIGH; PIPELINE) — PROMOTED from deferred [seed: `~/janusmask_briefs/rev20_exec/DEFERRED_SEED_PHASE_SEC1_FAILCLOSED_VERIFY.md`].**
Complete the SEC-1 fail-close on the remaining verify/mutant/embedded/smoke/fuzz spawns: when `sandbox_enabled` and the
proxy binary RESOLVES (`shutil.which`) but `proxied_session_bus()` RAISES, REFUSE (raise the same "filtered D-Bus proxy
failed to start" `RuntimeError`) instead of falling back to `dbus_proxy_socket=None`→host bus. Preserve the
proxy-binary-ABSENT graceful degrade (tests mock `which`).
- Sites [RE-VERIFIED @ `b5eb8b5`]:
  - `harness/orchestrator.py::_auto_commit_accepted` — the 4 verify/baseline/accept/mutant try/except PAIRs =
    **8 textual `build_jail_argv` lines**: proxy branch `1918/2049/2079/2099`, fail-open `=None` branch `1922/2053/2083/2103`
    [verified — matches R1/R2/R4 exactly]. Single large `def` (`_auto_commit_accepted` at `:1542`).
  - `harness/embedded_test_runner.py:144` (`_dbus_sock = None` fallback; the two `build_jail_argv` at `:173`/`:219`) [verified].
  - `harness/sandbox_smoke.py:128` (`_dbus_sock = None` fallback; `build_jail_argv` at `:134`) [verified].
  - `harness/narrow_fuzz/validation.py:282` (`_dbus_sock = None` fallback; `build_jail_argv` at `:284`) [verified].
- Likely SPLIT: (i) VERIFY-ORCHACC = single-symbol `_auto_commit_accepted`; (ii) VERIFY-EASY3 = embedded/smoke/fuzz
  (multi-file `.patches.json`). Oracle per group: force `proxied_session_bus` to raise, sandbox on, proxy binary
  resolvable → assert REFUSAL (not a `dbus_proxy_socket=None` build_jail_argv call). Negative control: binary-absent →
  graceful path preserved.
- **[CLAUDE-REV — single-reviewer (1/5), implementation caution]:** the existing `try` at each verify site reportedly wraps
  BOTH the `proxied_session_bus()` context entry AND the `subprocess.run(...)`, so a naive "raise instead of fall back to
  `=None`" would ALSO convert unrelated subprocess failures into spawn refusals. NARROW the `try` to the proxy
  context-manager ENTRY only (capture `_sock`, then run `subprocess.run` outside it); apply the same narrowing at
  embedded/smoke/fuzz. Verify the try-scope at each site before authoring.

**(b) CREDENTIAL-EXFIL on the verify/execute path (HIGH; PIPELINE) — trust-rule #5 [agy R4 §1.3].**
The jail binds `~/.gemini`/`~/.claude` RW (`agent_jail.py:147-153` region, `_sub in (".nvm",".gemini",".claude")` at
`:150` [verified]) and does NOT unshare net/IPC (`:95-97` [verified]). The synthesis spawn legitimately needs these
(OAuth refresh); the VERIFY/test/fuzz/smoke spawns do NOT.
- Add `bind_credentials: bool = True` to `agent_jail.py::build_jail_argv` (`:65`); when False, SKIP the `.gemini`/`.claude`
  binds. Set `bind_credentials=False` on the 8 verify lines + embedded (`:173`/`:219`) + smoke (`:134`) + fuzz (`:284`).
  AND/OR add `--unshare-net --unshare-ipc` for those execute spawns (they need neither network nor host IPC). Keep
  synthesis (`spawn_agent`, `repo_root=PROJECT_DIR` `:391`) UNCHANGED (it needs OAuth + net).
- **[CLAUDE-REV — single-reviewer (1/5), NOT independently verified; OWNER VERIFY before relying on `bind_credentials` alone]:**
  one reviewer reports that dropping the `.gemini`/`.claude` directory binds does NOT close the exfil surface, because the jail
  ALSO RW-binds the session keyring socket (`agent_jail.py:241-250` region) and a copy/ro-bind of `~/.claude.json`
  (`:175-183` region) into EVERY spawn — both independent of `bind_credentials`. If true, `--unshare-net` (NOT "AND/OR") is the
  load-bearing control: without net, any cred read in-jail cannot leave. RECOMMENDATION pending verification: make
  `--unshare-net --unshare-ipc` MANDATORY on all execute spawns AND drop the keyring/bus/`.claude.json` binds there too;
  re-verify the exact bind line numbers before authoring.
- **[CLAUDE-REV — single-reviewer (1/5), NOT independently verified; HIGH if true]:** when `agent_sandbox.bwrap` is false,
  the verify command reportedly runs UNJAILED via `subprocess.run(..., shell=True, executable='/bin/bash')` (e.g.
  `orchestrator.py:1924` `else` branch) — bypassing the jail, AST interceptor, and SEC-1 entirely. For EXTERNAL mode this
  would let attacker-controlled `verification_command`/tests run on the host with full creds + net. RECOMMENDATION: add a hard
  fail-closed gate — when `not _target_is_self(working_dir)`, REFUSE any verify/execute spawn unless `sandbox_enabled()` is
  true (raise; never fall through to `shell=True`). Add to §5 invariants. Verify the `else`-branch anchors before authoring.
- **[CAVEAT for review]** confirm the `bind_credentials` edit is a `def`-signature + body change (pipeline-viable) and
  does not collide with the SEC1-DBUSADDR `dbus_proxy_socket` kwarg or the §4 G3 `extra_ro` venv work. Coordinate: this
  edit touches the SAME 8 verify lines as §3(a) and §4 G3 — sequence (a)→(b)→G3 on the post-(a) shape.
- Oracle: assert the verify build_jail_argv argv does NOT contain `--bind <home>/.gemini` (and/or contains
  `--unshare-net`); assert the synthesis argv STILL binds them. Re-run the agy auth smoke after (synthesis OAuth must
  still work).

**(c) RUNAWAY-CEILING hardening (MED; PIPELINE) [agy R1 §2.3 / R4 §1.4].**
Two defects: (i) `_SELFHEAL_ESCALATION_COUNT` is an in-memory module global (`autowork_daemon.py:667/674-675`,
`:1949/1956-1957` [verified]) → wiped on restart/`--once`; (ii) it counts ONLY self-heal escalations, not normal-task
fix-cascades.
- Persist the counter in `state/control/autowork/runaway_ceiling.json` (survives restart). On daemon start, load; on each
  trip, write. Decide a reset policy (e.g. operator-cleared, or windowed) — document it; no silent cap.
- Also bound NORMAL-task cascades: count ALL worker task executions within a session window (or a `task_fix→task_fix`
  chain-depth ceiling), not just `_escalate_*`. Wire the check at the iteration dispatch in `_iteration`/`_auto_promote`
  (re-verify the exact dispatch anchor at review; the existing per-task retry/quarantine machinery is near the daemon
  iteration body — DO NOT assume a line number, grep at HEAD).
- Oracle: simulate N+1 escalations / N+1 cascade tasks → assert the (N+1)th is REFUSED + a `runaway_ceiling_tripped`
  telemetry row; assert the counter survives a simulated process restart (re-read the state file).

**(d) AUTHGATE-HARDEN completion (MED; PIPELINE — test/script) [agy R1 §2.6].**
`a3c6669`'s test is partially vacuous (Ping-only). Strengthen `~/janusmask_briefs/sec1c_spawn_authgate.py` / the live
test into a real escape-regression oracle: (i) FORCE a token refresh (or run with cleared/stale
`~/.gemini/oauth_creds.json`) so the keyring round-trip over the FILTERED bus is genuinely exercised — a cache-hit must
not give a false GREEN; (ii) add a NEGATIVE CONTROL — from inside the jail attempt a `StartTransientUnit` D-Bus call and
assert it is DENIED (distinguishes a filtered bus from an unfiltered one). Ship as a live security test.

**(e) Abstract-socket residual (ACKNOWLEDGE; host-config-dependent) [agy R1 §2.2 / R4 §1.2].**
The `DBUS_SESSION_BUS_ADDRESS=unix:path=<xdg>/bus` override (`74cd149`) defeats env-respecting clients only. Because the
jail does NOT unshare net/IPC (required for OAuth under `--share-net`), a non-cooperative process can dial a host
`unix:abstract=…` session bus directly via `/proc/net/unix`. Inert if the host bus is a path socket (typical logind
desktop), latent otherwise. A complete fix needs `--unshare-ipc`/net or a netns-scoped proxy (conflicts with the OAuth
`--share-net` need). **Treat as a documented residual; §3(b)'s `--unshare-net --unshare-ipc` on the EXECUTE spawns
removes it for those spawns specifically** (they don't need net), narrowing the exposure to the synthesis spawn (which
holds the creds it would exfil anyway). Detect-and-warn at daemon start if the host bus address is `unix:abstract=` and
the synthesis path is unattended.

**Phase A re-review trigger (carried):** after these land, owner may re-affirm Phase A. Any §4 G2 relax that lands
later re-triggers the 8-point review.

---

## 4. External-project capability (§3B-D) — re-anchored @ `b5eb8b5`; owner authorizations applied [agy R2 + REV20 §3]

> Owner-requested: run JanusMask autonomously INSIDE an EXTERNAL project, with self-build gates active ONLY when the
> target IS the JanusMask repo. The trust primitive `_target_is_self()`/`effective_target_root()` now EXISTS
> (`paths.py:73/:103`, landed `b5eb8b5`) — the foundation is in place; the seams are still to be wired. **G1 (external
> task origination) AUTHORIZED to build. G2 (AST relax) CONFIRMED (§0). The safety of the whole feature hinges on ALL SIX
> trust rules below.** All PIPELINE-FIRST where viable. **Sequence: §1 (M2) + §3 (gate-ii) FIRST; §4 is unsafe to author
> in parallel because it RELAXES the very gates Phase A inspects.**

**The 5 plumbing seams [RE-VERIFIED @ `b5eb8b5`; `working_dir` is OPTIONAL, absent ⇒ self-build, FAIL-SAFE-TO-SELF]:**
1. `harness/planner/brief_loader.py:160` (frontmatter normalize loop; `load_brief` def `:121`) [verified]. **Multi-point edit
   — [CLAUDE-REV 3/5: the prior 3-bullet recipe is a NO-OP as written; it is FOUR coordinated edits]:** `PlanningBrief` is
   `@dataclass(frozen=True)` (`:26-27` [verified]). (a) add `working_dir: str | None = None` to the frozen dataclass; (b) add
   `OPTIONAL_FIELDS = {"working_dir"}`; (c) **WIDEN the hard filter at `:160`** — the normalize loop discards every key NOT in
   `REQUIRED_SECTIONS` (`if norm_k in REQUIRED_SECTIONS: fm_normalized[norm_k]=...`), so "keep `working_dir` in the loop" does
   nothing unless `:160` becomes `if norm_k in REQUIRED_SECTIONS or norm_k in OPTIONAL_FIELDS`; (d) the construction loop
   `for req in REQUIRED_SECTIONS` (`:169-183`) builds `data` from required keys ONLY and the `PlanningBrief(...)` constructor
   (`:185-194` [verified]) passes only the 5 required fields + raw_text/source_path/sha256 — so `working_dir` needs an
   EXPLICIT `working_dir=fm_normalized.get('working_dir')` pull OUTSIDE that loop, passed to the constructor. Note `working_dir`
   is FRONTMATTER-ONLY (`_parse_markdown_sections` only recognizes `REQUIRED_SECTIONS` headings). OPTIONAL not REQUIRED (a hard
   requirement breaks every existing in-repo `brief_hooks_*.md`).
2. `harness/planner/blind_draft.py:122` (the `json.dump({...})` whitelist; `run_blind_drafts` def `:116`) [verified] —
   `working_dir` MUST stay OUT (this feeds the untrusted planner = the trust-fork boundary). NOTE: excluding it here does
   NOT hide it — `blind_draft.py:135` embeds `brief.raw_text` (incl. frontmatter) into the planner prompt verbatim
   [verified], so the planner can read & echo it; hence the load-bearing STRIP (rule #3).
3. **STAMP (trust fork). [CLAUDE-REV 3/5: the PRIMARY stamp point is `persist_plan`, NOT net-new daemon code — the plan had
   these backwards]:** `harness/planner/cli.py::persist_plan` (`:86` [verified]) is the single trusted producer that writes the
   exact `plan_hooks_<slug>.json` that `stage_task` later reads (daemon invokes the planner as a subprocess at
   `autowork_daemon.py:1020` → output `:1184`; `stage_task` reads `:1131/:1137`). It ALREADY holds `brief_obj` (loaded
   `cli.py:148`) and ALREADY injects brief-derived trusted fields (`source_brief_path`/`source_brief_sha256` at `:98-101`),
   and is called with `brief_obj` at `:190` [all verified]. STAMP the trusted `working_dir` there, alongside the existing
   source_brief_* injection — one edit at the trusted source, no per-task brief re-reader.
   - The daemon extract loop — `unstaged = rec.get('unstaged_task_ids') or []` at **`:1127`** [verified],
     `stage_task(plan_path, tid, state_dir, canonical=True)` at **`:1137`** [verified] — does NOT load the operator brief and
     copies the LLM plan task VERBATIM. Keep a daemon-loop STRIP of any LLM-authored `working_dir` here as DEFENSE-IN-DEPTH,
     not as the authoritative stamp. **[CLAUDE-REV anchor fix, 3/5]** the brief IS recoverable if needed, but NOT via the
     cited `:1166` — `rec['brief_filename']` at `:1166` is in a SEPARATE, later (`unplanned`) loop, not the `:1127`/`:1137`
     stamp loop. `brief_filename` is nonetheless present on EVERY record (`brief_status.py:71`), so the staging-loop `rec`
     carries it directly. **BLOCKED-ON seam 1.** Stamp at `persist_plan`; strip (defense-in-depth) at the daemon loop AND
     `staging.stage_task` (seam 4). Do NOT rely on the daemon re-reader as the trust fork.
4. `harness/planner/staging.py:16` (`def stage_task(plan_path, task_id, state_dir, canonical=True)`) [verified] — dumps the
   task dict verbatim, NO key-stripping. **TWO independent writers, the STRIP must hit BOTH:** (a) add a trusted
   `working_dir` param to `stage_task` + reject/strip any task-dict `working_dir` not arriving via that param; AND (b) the
   SEPARATE inline writer **`scripts/impl_plan_to_queue.py:56`** (`out.write_text(json.dumps(task, indent=2) + "\n", …)`
   [verified] — a drifted copy `staging.py` was lifted from that does NOT call it) must enforce the same strip, OR be
   unified to call `stage_task`. Stamping only at the daemon `:1127` loop leaves the script writer + re-stage paths able to
   re-admit an LLM `working_dir`.
5. `harness/hooks/_decide_common.py:86` (`task = _paths.load_inbox_task(inbox_dir)`; `decide_submission` def `:80`) [verified] —
   read the working_dir to decide self-build-gate relaxation. `task` is a DICT (`.get()` accessed elsewhere) → use
   `task.get('working_dir')`, the trusted STAMPED value (seam 3/4 output), with `_target_is_self()` fail-safe-to-self when
   absent. This hook runs in the jailed worker → `_target_is_self()` must be importable/reachable there (TEST it, don't
   assume); NEVER recompute target-trust from any LLM-controlled field.
   - **[CLAUDE-REV 3/5: seam-5 is NOT a single dict-read; the construct-relax is multi-site signature plumbing]** The G2
     external construct-relax must be threaded through the chain `decide_submission` actually calls: `rpc_submit_code.validate`
     (`submit_code.py:71` — signature `validate(code, *, allow_nondeterminism=False)`, NO construct-relax param) → also
     `rpc_submit_code.ensure_valid` (`:78`, persist-time gate) → `ast_enforcer.validate_code` (`:187`). All three need a new
     `relax_external_constructs` (or equivalent) param forwarded, and `decide_submission` computes it from the stamped
     `working_dir` via `_target_is_self()`. [verified anchors]
   - **[CLAUDE-REV anchor fix 3/5]** `allow_nondet` is COMPUTED at `:98`, CONSUMED at the `validate(...)` call at `:105` (the
     plan's "plumbed at `:105`" conflated the two).
   - **[CLAUDE-REV 3/5: forcing determinism external must override the meta-task auto-relax too]** `allow_nondet` is set True
     not only by the task's `constraints.deterministic` (`:98`) but ALSO unconditionally for
     `meta_task_type in {io_adapter, logging_observability}` or `test_*` (`:99-102` [verified]). For external
     (`not _target_is_self`), force `allow_nondet=False` AFTER the `:99-102` block — ignoring BOTH the `deterministic` flag AND
     the `meta_task_type` auto-relax, not just the former.

**Predicates — NOW EXIST [verified @ `b5eb8b5`]:** `_target_is_self()` (`paths.py:73-101`) and `effective_target_root()`
(`:103-115`). Both resolve-first, fail-safe-to-self=True, parent/sub/STATE_DIR/workroot ⇒ self (R1 §2.4 audited exhaustive).
This is the §3 keystone and is DONE — the remaining §4 work is wiring it into the seams + spawns.
**[CLAUDE-REV 4/5 — document the ANCESTOR-IS-SELF usability constraint]:** `:89` classifies any ANCESTOR/parent of the JM
checkout as self (`resolved in project_root.parents`), and the sub-dir clause (`:91`) classifies any subdir of PROJECT_ROOT as
self. So an external target that is an ancestor of — OR contains, OR is contained by — the JM checkout silently demotes to
strict self-gates and `effective_target_root()` rewrites it to PROJECT_ROOT (the external feature SILENTLY no-ops). This is
fail-safe (never a security hole) but a real limitation: **external targets MUST live OUTSIDE the JM tree (neither ancestor
nor descendant).** Add this as a known constraint AND an integration-test case (an ancestor `working_dir` is treated as self).

**Re-key T2–T5 onto the STAMPED `task.working_dir`, gated by `_target_is_self()`:** T2 = §1b decision; T3 = re-route the
verify/synth spawns + staging-root derivation; T4 = `agent_workroot()` writer + the external readers follow the target while
`JANUSMASK_PROJECT_DIR`/`PYTHONPATH` STAY self; T5 = no-op ONLY `_maybe_push_and_rebase_pin` (`autowork_daemon.py:1513`
[verified @ b5eb8b5 — was `:1489` in REV20, DRIFTED]), NOT `_auto_promote`'s whole body (generic staging engine).

**T3 — the largest/most-anchor-sensitive item [RE-VERIFIED @ `b5eb8b5`]:**
- **Staging-root derivation [CLAUDE-REV 5/5 — anchors NOW VERIFIED @ b5eb8b5]:** inside `_auto_commit_accepted` (`:1542`),
  `orchestrator.py:1770` does `git rev-parse --show-toplevel` with **`cwd=str(state_dir.parent)`** (→ always the JM toplevel)
  then `:1780` derives `staging_path = worktree_root.parent / f"{worktree_root.name}_{task_id}_staging"`. (REV20's `:1764`/`:1774`
  were DRIFTED.) For an external target BOTH the `:1770` derivation (use `effective_target_root()`, not `state_dir.parent`) AND
  the `create_staging_worktree(parent_root=worktree_root)` call at `:1786` must re-root — see the external-commit section: this
  is the load-bearing retarget, because everything downstream (the staging worktree's `--git-common-dir`, the merge) follows
  whichever repo `worktree_root` points at.
- **The 8 verify lines** at `orchestrator.py:1918/1922, 2049/2053, 2079/2083, 2099/2103` [verified — `repo_root=worktree_root,
  extra_ro=[sys.base_prefix, sys.prefix] + list(verify_extra_ro)`].
- **Synthesis spawn `repo_root=PROJECT_DIR` at `orchestrator.py:391`** [verified — `spawn_agent`]. For external work the jail
  `repo_root` MUST follow `effective_target_root()` (agent edits the TARGET), while `JANUSMASK_PROJECT_DIR`/`PYTHONPATH`
  STAY self (T4). Both derive from the same module-level `PROJECT_DIR` symbol — edit the two USES independently, do NOT
  rebind the constant.
- **Embedded test runner:** `harness/embedded_test_runner.py` imports `PROJECT_ROOT` (`:115`) as `repo_root` for the two
  `build_jail_argv` (`:173`/`:219` [verified]) + binds `sys.base_prefix/sys.prefix`. Needs a target-root/venv arg threaded
  from `working_dir` (signature change, parallel to synth). ADD to the T3/G3 edit list.
- **COORDINATION:** those 8 verify lines are simultaneously touched by §3(a) fail-close (the `=None` branches become
  refusals), §3(b) `bind_credentials`/`--unshare-net`, the SEC1-DBUSADDR env, AND G3 (`extra_ro` venv + `repo_root`
  retarget). Land §3(a)/(b) FIRST, author G3/T3 against the POST-§3 shape.

**TRUST-MODEL HARDENING — MANDATORY (6 rules; the predicate `_target_is_self()` already implements #1/#2/#4 internally —
the wiring rules #3/#5/#6 are the gap):**
1. Canonical `Path(working_dir).resolve()` BEFORE any classify/bind — IMPLEMENTED in `_target_is_self` (`:85`). Kills `..` + symlink escape.
2. REJECT (at the trusted load/stamp stage) any `working_dir` inside `state/`/`agent_workroot()`/`PROJECT_ROOT`(≠self) — the
   predicate classifies all these as SELF (`:89-98`), so they get strict gates; the trusted stamp should additionally
   REFUSE to bind them as an external root.
3. **STRIP the LLM-authored `working_dir`** at `staging.py::stage_task` (`:16`) AND `scripts/impl_plan_to_queue.py:56` (seam 4) —
   the core trust-fork. Without it the planner injects `working_dir`, the worker runs RELAXED policy while code targets self.
4. FAIL-SAFE-TO-SELF — IMPLEMENTED (`_target_is_self` returns True on any resolution error, `:100-101`).
5. **CREDENTIAL EXFIL ON THE EXECUTE PATH** — the §3(b) item. The four path-rules stop at resolution and never reach
   code-EXECUTION; the verify/test/mutation spawns run external code in the cred-bound, net-shared jail. Mitigate via
   `bind_credentials=False` + `--unshare-net/ipc` on the EXECUTE spawns (synthesis keeps the binds). Largest §4 hole.
6. **`services/**` GATED — DONE** (`03fc91a`, `_SENSITIVE_APPLY_GLOBS` now 4 globs incl. `services/**` `:16` [verified]). This
   was mandatory before any G2 relax (else a relaxed task could rewrite `services/neurosymbolic/ast_verifier.py`, the live
   interceptor). Carry as an invariant (§5).
Ship `_target_is_self()` unit tests (DONE for the predicate) PLUS an **EXTERNAL-MODE INTEGRATION TEST as a gating deliverable**
(R2 §2.4): a throwaway fixture external repo asserting end-to-end — (a) external relax applies; (b) a self-target KEEPS strict
gates; (c) a malicious `working_dir` (resolving into `state/`/`agent_workroot()`/parent/symlink) is REJECTED; (d) the TARGET
`.venv` is the interpreter used; (e) `_target_is_self()` is importable INSIDE the jailed worker hook and fails-safe-to-self.

**G2 — AST-rule split [CONFIRMED §0]; thread into BOTH engines or submit⊆commit parity (F2) breaks.** The two engines do
NOT share rules [RE-VERIFIED @ `b5eb8b5`]:
- **`harness/ast_enforcer.py` (submit/commit gate):** `validate_code(code, *, allow_nondeterminism=False, declared_signature=None)`
  at `:187` [verified]. **`eval`/`exec`/`__import__` (`:71-72`) AND hardcoded-credentials (`:79`/`:86`) are the SAME rule
  name `'security'`** [verified] — you CANNOT relax eval/exec by suppressing `security` without ALSO relaxing credentials.
  **The eval/exec relax MUST be a NEW targeted sub-flag on the dangerous-call branch only.** **[CLAUDE-REV 3/5 — prefer the
  param over a rule rename]:** add a `relax_external_constructs` param that SUPPRESSES ONLY the eval/exec/`__import__` `:71-72`
  branch, keeping the `'security'` rule NAME intact for credentials — do NOT rename `'security'`→`'dangerous_calls'`, because
  the rule string is surfaced downstream (`_decide_common.py` rejection payloads + `emit_ast_rejection` telemetry); renaming
  can break tests/telemetry consumers asserting on `'security'`. NOTE `os_system` (`:108`) and `bare_except` (`:103`) are
  ALREADY their own rule names → relax them via a rule-name allowlist; no AST surgery needed for those two. `nondeterminism`
  is ERROR (`:52/:59/:98`), gated by `allow_nondeterminism`.
- **`services/neurosymbolic/ast_verifier.py` (interceptor):** `ASTVerifier.verify(code, filename="<string>")` at `:229`
  [verified]. `non_determinism`=WARNING (`:91/:98`), `os_system`=ERROR (`:138`), `credential_leak`=WARNING (`:206`,
  string-literal regex). **NO `eval`/`exec`/`__import__` rule** → the eval/exec external relax is a NO-OP here; it only
  matters at submit/commit. The interceptor has **NO relax seam** — `interceptors.py:53` calls `ASTVerifier().verify(code)`
  with NO task/`working_dir` context [verified]; threading a per-target relax requires NET-NEW plumbing: a relax param on
  `verify()` + a way to read the active task's resolved `working_dir` (mirror `BashSafetyInterceptor`'s
  `JANUSMASK_PROJECT_DIR` env read at `interceptors.py:96` [verified]).
  **[CLAUDE-REV 3/5 — this is a DECISION, not just an observation]:** `os_system` IS an ERROR rule HERE (`:138`), so external
  code using `os.system` is BLOCKED at the live SUBMIT-time interceptor regardless of any `ast_enforcer` relax → external
  tasks that legitimately need `os.system` would DEADLOCK at submit (commit ⊋ submit, the inverse of F2). Resolve explicitly:
  EITHER (i) build the interceptor relax plumbing (`verify()` relax param + env-based `working_dir` read) as a REQUIRED G2
  sub-deliverable, OR (ii) DROP `os_system` from the external-relax set and keep it strict everywhere. Do not leave it as a
  noted NO-OP.
- **The CONFIRMED 3-way split:** credentials STRICT for all (self + external); `eval`/`exec`/`__import__` + `os_system` +
  `bare_except` RELAX external-only; **FORCE `allow_nondeterminism=False` on external** (verification reproducibility —
  do NOT add `_target_is_self()` as a new nondeterminism relax key; nondeterminism is already per-task relaxable via
  `allow_nondeterminism`, so external must IGNORE the task-supplied `deterministic` flag and force False). Key the toggle on
  `_target_is_self()`; relaxed-value injection in CODE (the §5 pin keeps `verify_extra_ro/rw` empty in config).
- **Any G2 relax landing RE-TRIGGERS the Phase A 8-point owner review** (§2).

**G3 — target-`.venv` binding (atomic with the synth retarget):** all execute-target stages must bind the TARGET interpreter
— the 8 verify lines (`orchestrator.py:1918/1922, 2049/2053, 2079/2083, 2099/2103`, each `extra_ro=[sys.base_prefix, sys.prefix]
+ list(verify_extra_ro)`), the embedded runner (`embedded_test_runner.py:173/:219`), the differential-fuzzer
(`narrow_fuzz/validation.py:284`). Add `<working_dir>/.venv` prefix/bin as a SEPARATE code-injected list concatenated
alongside the existing `+ list(verify_extra_ro)` (NOT added to `verify_extra_ro` in config — the §5 pin keeps it empty) +
jailed PATH. Coordinate with §3(a)/(b) per the T3 note.

**Bootstrap (REV18 §3B-B):** new `harness/target_bootstrap.py` (git init/.gitignore/initial commit/`.venv`+deps/staging
worktree) + one-time `bootstrap_target()` (gate-bearing, idempotent on a recorded marker). **(a) Placement:** reachable
from BOTH `run_daemon` AND the `--once`/`_iteration` path (mirror DAEMON-ONCE-PROXY — re-verify the `--once` return-early
anchor at review; the `--once` proxy block is now `autowork_daemon.py:1756-1804` [verified]). **(b) Dirty tree:** REFUSE by
default (warn = proceed = clobber); `.resolve()` the target BEFORE the marker check; never `git init`/commit into a
directory it did not create or that contains a `.git` it does not own (ownership check).

**External commit/promotion path — UNDEFINED; the KEY GAP (R2 §2.1). [CLAUDE-REV 3/5: this is DEEPER than a "retarget
`merge_staging_to_parent`" item — it is a re-rooting of the whole staging/merge subsystem, and is the single largest §4
deliverable.]** The blocker is structural: the staging worktree is itself a `git worktree` OF the JM repo. `create_staging_worktree`
(`git_integration.py:1245`) ENFORCES sibling placement vs `parent_root` (`:1262` raise) and runs `git worktree add cwd=parent_root`
(`:1287`); `_auto_commit_accepted` creates it as a sibling of the JM `worktree_root` (`:1780`, `parent_root=worktree_root` `:1786`).
So `merge_staging_to_parent` (def **`git_integration.py:1345`** [CLAUDE-REV — resolves the "could not confirm" anchor]; its
`--git-common-dir` derivation `:1362-1370` + ~7 `cwd=parent_root` subprocess sites `:1384/:1389/:1402/:1403/:1413/:1420/:1429`)
will FF-merge into whatever repo the staging worktree belongs to — which, unretargeted, is JM, NOT the external target.
Retargeting only `merge_staging_to_parent`'s `parent_root` arg is INSUFFICIENT. **The item must re-root the full chain for
external tasks:** (0) the `worktree_root` derivation at `orchestrator.py:1770` (use `effective_target_root()`, not
`cwd=state_dir.parent`) so the staging worktree is created INSIDE the external repo; (0b) the same self-anchored derivation in
`commit_accepted_output` (`git_integration.py:604`, `cwd=state_dir`); (1) `create_staging_worktree`/`remove_staging_worktree`
+ `merge_staging_to_parent` follow from (0); (2) external commits land in the TARGET repo, never JM's HEAD (T5 makes the JM
push a no-op but does NOT define the external commit); (3) whether/how the `_SENSITIVE_APPLY_GLOBS` (`git_integration.py:16`)
apply gate maps for an external repo; (4) where the §1b approval boundary sits for external work; (5) the pre-merge
stash/dirty-tree refuse policy (`:1384-1396`) acting on a user's working repo. Without (0)/(0b), accepted external output is
committed into a JM-rooted worktree and silently lands in the WRONG repo.

**Sequencing [agy R2 §3]:** §1 (M2) + §3 (gate-ii closers a–e) FIRST → then §4: trust wiring (seams 1/2/5, PIPELINE) →
seam 3/4 + STRIP (hand-edit-likely, multi-site) → G2 split (BOTH engines, hand-edit-likely / owner-confirm) → G3 venv +
T2–T5 (coincident with the §3 verify lines) → G1 origination + external commit/promotion path → external-mode integration
test (GATING) → owner Phase A re-review. **§4 is NOT safely parallel with Phase A** — any G2 gate-relax re-triggers the
8-point review.

---

## 5. Invariants carried through EVERY phase (do-NOT) — per-file grep checklist [RE-VERIFIED @ `b5eb8b5`]

- `grep -c "synthesis_success = True"` **==1** in EACH of `harness/orchestrator.py` (`:2433` [verified]) and `harness/orchestrator_worker.py`.
- `grep -c "skip_interface_fuzz"` in `harness/orchestrator.py` (`:2444` [verified]), `harness/orchestrator_worker.py`,
  `harness/planner/taxonomies.py` — ONLY `test_authoring`; never narrow `BYPASS_FUZZER_TYPES`.
- **`_SENSITIVE_APPLY_GLOBS == ('harness/**','config/**','scripts/**','services/**')` at `git_integration.py:16`** [verified —
  UPDATED: now 4 globs incl. `services/**`, landed `03fc91a`]. NEVER remove `services/**` (rule #6 — guards the live
  interceptor engine).
- `verify_extra_ro`/`verify_extra_rw` ABSENT/empty in `harness/config.yaml`; `harness/config.yaml` byte-clean. (§4 G3
  injects the target `.venv` in CODE, NOT via these config keys.)
- **SEC-1 wiring:** every `build_jail_argv(...)` EXECUTION site threads `dbus_proxy_socket=`. The synthesis spawn (`:391`)
  + daemon self-heal (`_contain_selfheal:617`) are fail-CLOSED; **the 8 verify lines (`1918/1922, 2049/2053, 2079/2083,
  2099/2103`) + embedded (`:144`) + smoke (`:128`) + fuzz (`:282`) are STILL fail-OPEN (`=None`)** — §3(a) makes them
  fail-closed; AFTER §3(a) lands, update this invariant: the `=None` fail-open branches become REFUSALS, do NOT
  re-introduce a host-bus fallback.
- **`DBUS_SESSION_BUS_ADDRESS` override:** `build_jail_argv` sets it to `unix:path=<xdg>/bus` when `dbus_proxy_socket` is
  set (`74cd149`); do NOT allowlist the host value back through.
- **`_target_is_self`/`effective_target_root` EXIST** (`paths.py:73`/`:103`) — fail-safe-to-self=True, resolve-first. Any
  §4 self-build-gate bypass MUST derive from these (NOT a re-extension of the `agent_workroot` raise-guard at `:63`, which
  has the opposite raise-contract). `working_dir` REJECTED if resolving into `state/`/`agent_workroot()`/`PROJECT_ROOT`(≠self);
  LLM-authored `working_dir` STRIPPED at `staging.py::stage_task` (`:16`) AND `scripts/impl_plan_to_queue.py:56`.
  `JANUSMASK_PROJECT_DIR`/`PYTHONPATH` + `${PROJECT_ROOT}` config tokens STAY self.
- **G2 parity:** submit-time interceptor (`ast_verifier.py`) ⊆ commit-time enforcer (`ast_enforcer.py`); any external relax
  MUST apply IDENTICALLY across BOTH (credentials NEVER relaxed; external forces `allow_nondeterminism=False`).
- R-ANCHORED-PATCH: no-extras path byte-identical; extras only 1-part qualnames, bounded kinds. WHOLE-FILE-DRIFT-GUARD:
  keep modified-existing-symbol intersection semantics.
- **agy is NOT tree-isolated** → after ANY agy run verify byte-identical + revert drift (esp.
  `git checkout HEAD -- harness/config.yaml`; rm stray oracle/test files agy drops via `--add-dir`).
- Never add `*_fix`/any `<task>_fix` to the allowlist. **`full_stop` REMOVED — Phase A ACTIVE** (owner decision §0); any G2
  gate-relax re-triggers the Phase A 8-point review. §1b (`_apply_approval_granted`) is the autonomous-commit boundary;
  agents tree-isolated ONLY via the bwrap jail.

---

## Appendix — re-verified anchors (@ `b5eb8b5`; re-check before use)

- `harness/git_integration.py`: `_SENSITIVE_APPLY_GLOBS` `:16` (4 globs); `_enforce_apply_scope` def `:43`;
  `commit_accepted_output` def `:569`; **M2: porcelain scan `:607` (`cwd=parent_root`→fix `worktree_root`), untracked build
  `:608-615`, multi-dispatch `:646-647`**; `_commit_accepted_output_multi` def `:809` (scope check `:853`);
  **[CLAUDE-REV] `commit_accepted_output` def `:569` (`parent_root` derive `:604-605`, manifest read `parent_root/filepath`
  `:638`); `create_staging_worktree` `:1245` (sibling-placement raise `:1262`); `merge_staging_to_parent` `:1345`**.
- `harness/orchestrator.py`: `_build_agent_env` `:220`; `spawn_agent` `:331` (synthesis jail `repo_root=PROJECT_DIR,
  dbus_proxy_socket=_dbus_sock` at **`:391`**, fail-closed proxy at `:384-385`); `kill_agent` `:480`; `_auto_commit_accepted`
  def `:1542` (**8 verify lines: proxy branch `1918/2049/2079/2099`, fail-open `=None` branch `1922/2053/2083/2103`**);
  `synthesis_success = True` `:2433`; `skip_interface_fuzz` `:2444`; **[CLAUDE-REV] staging-root `git rev-parse` `:1770`
  (`cwd=state_dir.parent`), `staging_path=` `:1780`, `create_staging_worktree` `:1786`; `commit_accepted_output` call `:1825`
  (passes `worktree_root=staging_path`); `merge_staging_to_parent` call `:2137`**.
- `harness/agent_jail.py`: `build_jail_argv` def `:65` (`dbus_proxy_socket` kwarg `:74`; add `bind_credentials` here for
  §3(b)); cred binds `_sub in (".nvm",".gemini",".claude")` `:150`; deliberately NOT unshare net/IPC `:95-97`.
- `harness/autowork_daemon.py`: `_contain_selfheal` def `:563` (proxy socket `:617`); RUNAWAY-CEILING checks `:661-675` +
  `:1943-1957` (`_SELFHEAL_ESCALATION_COUNT` in-memory global — §3(c) persists); `_escalate_to_autobrief` def `:622`;
  **seam-3 stamp: `unstaged` `:1127`, `stage_task` call `:1137`, `brief_filename` use `:1166`**; `run_daemon` def `:1620`
  (singleton proxy init `:1649-1672`, reap `:1731`); `_maybe_push_and_rebase_pin` def **`:1513`** (T5; DRIFTED from REV20's
  `:1489`); `main` `:1737`, `--once` proxy block `:1756-1804`.
- `harness/paths.py`: `agent_workroot` def `:27` (raise-guard `:63`); **`_target_is_self` def `:73`** (resolve `:85`,
  classify `:87-99`, fail-safe `:100-101`); **`effective_target_root` def `:103`**.
- §4 seams: `harness/planner/brief_loader.py` — `PlanningBrief` `@dataclass(frozen=True)` `:26-27`, `REQUIRED_SECTIONS`
  `:66`, `load_brief` `:121`, normalize loop `:160`; `harness/planner/blind_draft.py` — `run_blind_drafts` `:116`, json.dump
  whitelist `:122`, raw_text-in-prompt `:135`; `harness/planner/staging.py` — `stage_task` `:16`;
  `scripts/impl_plan_to_queue.py:56` (separate inline writer); `harness/hooks/_decide_common.py` — `decide_submission` `:80`,
  `load_inbox_task` `:86`, `allow_nondet` `:105`.
- G2 engines: `harness/ast_enforcer.py` — `validate_code` `:187`, `'security'` covers eval/exec/`__import__` `:71-72` AND
  credentials `:79`/`:86`, `os_system` `:108`, `bare_except` `:103`, nondeterminism `:52/:59/:98`.
  `services/neurosymbolic/ast_verifier.py` — `ASTVerifier.verify` `:229` (NO relax param, NO eval/exec rule);
  `non_determinism` `:91/:98`, `os_system` `:138`, `credential_leak` `:206`. Live wiring `harness/interceptors.py:53`
  (`ASTVerifier().verify(code)`, no context), `JANUSMASK_PROJECT_DIR` env read `:96`.
- `harness/embedded_test_runner.py`: `build_jail_argv` `:173`/`:219` (`repo_root=PROJECT_ROOT` `:175`/`:221`), fail-open
  `_dbus_sock=None` `:144`. `harness/sandbox_smoke.py`: `build_jail_argv` `:134`, fail-open `:128`.
  `harness/narrow_fuzz/validation.py`: `build_jail_argv` `:284`, fail-open `:282`.
- `state/control/autowork/full_stop`: **ABSENT** (owner removed — Phase A active).
- Review reports: `~/janusmask_briefs/review_rev21/R{1..4}_*.md` (agy; to be Opus-cross-checked at the next-session
  Claude review). Deferred seed: `~/janusmask_briefs/rev20_exec/DEFERRED_SEED_PHASE_SEC1_FAILCLOSED_VERIFY.md` (= §3(a)).

### Anchors NOW resolved by the Claude review (were "could not confirm" in the draft)
- **[CLAUDE-REV 5/5 — RESOLVED]** Staging-root: `orchestrator.py:1770` (`git rev-parse --show-toplevel`, `cwd=state_dir.parent`)
  and `:1780` (`staging_path = worktree_root.parent / f"{worktree_root.name}_{task_id}_staging"`). REV20's `:1764`/`:1774` were
  DRIFTED. `create_staging_worktree(parent_root=worktree_root)` call at `:1786`.
- **[CLAUDE-REV 4/5 — RESOLVED]** `merge_staging_to_parent` def = **`git_integration.py:1345`**; `--git-common-dir` parent
  derivation `:1362-1370`; ~7 `cwd=parent_root` subprocess sites `:1384/:1389/:1402/:1403/:1413/:1420/:1429`. Sole caller
  `orchestrator.py:2137` (`merge_staging_to_parent(staging_path, worktree_root)`). See the rewritten external-commit section.
- **The normal-task cascade dispatch anchor in `_iteration`/`_auto_promote`** for §3(c) — STILL NOT pinned (grep at HEAD).
  **[CLAUDE-REV note]** the `task_fix→task_fix` cascade is generated by self-heal/autobrief escalation, NOT by the
  `_auto_promote` extract/stage loop (`:1120-1147`, which only stages already-planned tasks); a session-window count of ALL
  worker task executions belongs at the orchestrator worker-spawn/`_decide` dispatch, not the daemon `_auto_promote`. Pin the
  cascade SOURCE concretely and check for double-counting against the existing per-task retry/quarantine machinery before
  authoring §3(c). **[unverified @ b5eb8b5]**
