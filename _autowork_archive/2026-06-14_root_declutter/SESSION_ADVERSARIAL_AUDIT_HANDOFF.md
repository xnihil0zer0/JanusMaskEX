# Adversarial Audit Handoff — JanusMaskJR → NobleGreedv2 "Agentic Spine" build session (2026-06-10/11)

**You are an adversarial reviewer.** Your job is to find GAPS and DAMAGE caused by the work below —
not to take the prior agent's word for anything. Treat every "✅ done / verified" claim as a
hypothesis to be falsified. The prior agent fixed bugs by editing **JanusMaskJR's own pipeline
harness** and by **driving a blind dual-agent (Claude Code + Gemini CLI) builder** against an external
repo; both are high-blast-radius. Assume subtle silent corruption is possible and hunt for it.

Two repos are in play:
- **JanusMaskJR (JM)** = the factory/harness at `/home/xnihil0zer0/JanusMaskJR` (this dir). Branch `master`.
- **NobleGreedv2 (NGv2)** = the external build target at `/home/xnihil0zer0/NobleGreedv2`. Branch `master`.

The build was driven by `/home/xnihil0zer0/NobleGreedv2/agentic_spine_research/spine_build/SPINE_HANDOFF.md`
(read it). Session memory is in `~/.claude/projects/-home-xnihil0zer0-JanusMaskJR/memory/spine-epic-a-and-additive-edit-fixes.md`.

---

## 0. TL;DR of what to audit

1. **5 JanusMaskJR harness self-edits** modified the pipeline that builds everything. A defect here
   silently corrupts ALL future builds. HIGHEST PRIORITY. (§2c, §5a)
2. **12 NGv2 "spine" leaves** were built by a blind dual-agent worker via partial-edit/whole-file
   patches. One EDIT leaf (A5) was already caught **silently gutting an existing class** (security
   checker) while its oracle stayed green. Assume others may have similar undetected clobbers. (§5b)
3. **~16 hand-authored oracle files** are the only correctness gate for the bypass-fuzzer leaves. One
   was proven too weak (missed the A5 regression). Hunt for other vacuous/weak oracles. (§5c)
4. **Many hand-edits to NGv2 plan-state JSON** (`plan_hooks_*.json`) and **NGv2 test files** were made
   to steer the blind worker. Verify none corrupted state or masked failures. (§2d, §5e)
5. **The daemon was killed & respawned** mid-session; the NGv2 tree had a README + .gitignore
   hand-committed. Verify hygiene. (§5e)

---

## 1. Session goal (context)

Build Epics A→D of the NGv2 "Agentic Spine" (a session-gated `hunt→triage→poc→detonate→report→done`
bug-hunting pipeline + an MCP control surface + a feedback-guided PoC/detonation system) as free-tier
NGv2 work through the JM pipeline. Rules from SPINE_HANDOFF.md: hand-author each RED oracle and commit
it BEFORE dispatch; NGv2 core is stdlib-only (no net/LLM/subprocess/3rd-party); the live bwrap
detonation runner is QUARANTINED (owner-hand-authored, never dispatched); root-cause every blocker
before resuming. Epic E is optional/no-op unless a real divergence is observed.

---

## 2. Complete inventory of changes (verify each independently)

### 2a. NGv2 production commits — the 12 spine leaves (all claimed green)
```
c2d8e84 A1 payload_selection (NEW)      ngv2/payload_selection.py   PUCT+Elo selection
971673d A2 ablation (NEW)               ngv2/ablation.py            source minify/obfuscate
b56a95a A3 swiss_tournament (NEW)       ngv2/swiss_tournament.py    O(R·N) ranking
2ab9ddf A4 debate_router_entropy (EDIT) ngv2/debate_router.py       +entropy/KL/early_stop
e55ac66 A5 ast_verifier_marker (EDIT)   ngv2/ast_verifier.py        +PocMarkerStubChecker  ⚠ SEE §3.1
41b922c B1 session_gate (NEW)           ngv2/session_gate.py        transition gates
6ac449c B2 session_db (NEW)             ngv2/session_db.py          SQLite session store
35848a1 B4 state_machine_gate (EDIT)    ngv2/state_machine.py       +transition_with_gate
44b4c86 C1 session_api (NEW)            ngv2/session_api.py         pure MCP handler
1898ca9 C2 session_mcp (NEW)            ngv2/session_mcp.py         stdio MCP transport
93bb91b D1 feedback_synth (NEW)         ngv2/feedback_synth.py      telemetry→diagnostic
102f9c3 D2 detonation_semantic_gate(EDIT) ngv2/detonation.py        +semantic_verdict
```
Plus follow-on NGv2 fix commits: `1cf90af` (fix-ast-verifier-restore — see §3.1), `289707d`
(cfix-gate-done), `4a19f88` (cfix-api-dup).

### 2b. NGv2 oracle / doc commits (hand-authored, committed RED-first)
`8d7affb` (Epic A oracles), `c09d779` (Epic B), `07b096f` (Epic C), `8952dbf` (Epic D),
`fa82160` (Epic-C gap-fix oracles), `e4b752b` (README.md — authored by 4 sub-agents),
`cf7149e` (.gitignore add for `agentic_spine_research/`). The oracles live in
`/home/xnihil0zer0/NobleGreedv2/tests/ngv2/test_*_wired.py` plus the pre-existing
`tests/test_ast_verifier.py`.

### 2c. ⚠ JanusMaskJR harness SELF-EDITS (HIGHEST RISK — these change the factory) ⚠
Each was built via the JM pipeline with a RED oracle + decision file. Audit each for correctness AND
for unintended behavior change:
```
ba6bc1a  harness/orchestrator.py        prepare_task_prompt: resolve files_touched against
                                        effective_target_root(working_dir) not PROJECT_DIR.
                                        Oracle: tests/test_prepare_task_prompt_external_partial_edit_wired.py
81fcda2  harness/orchestrator.py        PARTIAL-EDIT prompt now documents the R-anchor additive pattern.
                                        Oracle: tests/test_partial_edit_prompt_r_anchor_wired.py
0fdad2b  harness/autowork_daemon.py     sequential worker spawn propagates JANUSMASK_WORKING_DIR via a
                                        new shared _build_worker_env(); BOTH spawn paths call it.
                                        Oracle: tests/test_sequential_worker_env_propagation_wired.py
                                        NOTE: required a DAEMON RESTART to take effect (see §5e).
52feaed  harness/planner/plan_normalizer.py  _canonicalize_oracle_paths: repairs reversed external
                                        oracle paths (ngv2/tests/… → tests/ngv2/…) when the swapped
                                        path exists. Oracle: tests/test_planner_verification_path_normalization_wired.py
20bc82c  harness/git_integration.py     _ast_merge/_node_key: module `if __name__=="__main__":` guard is
                                        now a mergeable keyed unit (candidate-wins / preserve-when-omitted).
                                        Oracle: tests/test_ast_merge_main_guard_wired.py ; test commit
                                        1aa3ef6 reconciled a stale anti-balloon bound in
                                        tests/integration/test_auto_commit_merge.py. POST-LANDING CHECK:
                                        36/36 (new oracle + ast_merge_regression_adversarial + auto_commit_merge)
                                        green, _ast_merge intact at 460 lines (no truncation). RE-VERIFY THIS —
                                        it is the most central function in the harness.
```
`git_integration._ast_merge` is the single most central function (every accepted .py commit flows
through it). The in-flight fix reproduces the whole 460-line function as a symbol patch → **truncation
risk**. Verify byte-for-byte that no merge behavior regressed.

### 2d. State-artifact hand-edits made to steer the blind worker (verify none are corrupt/latent)
The prior agent repeatedly injected guidance into NGv2 plan-state to make blind workers comply:
- Injected `implementation_notes` / `spec.<key>` directives into tasks inside
  `/home/xnihil0zer0/JanusMaskJR/plan_hooks_spine_*.json` (A4 constant-anchor; B2 method-surface +
  data_model + determinism; B4 transition logic; C1 persistence + transition/gate/audit; C2 module
  structure; D2 verbatim DetonationChamber anchor).
- Hand-corrected `verification_command` paths (`ngv2/tests/` → `tests/ngv2/`) and the `oracle_*`→`test_*`
  filename mangling in plan JSON + staged task files (B2/B4, C1/C2, D1/D2) — BEFORE the durable
  `52feaed` fix landed.
- Changed staged `meta_task_type` (B2 io_adapter→data_model; C2 io_adapter→mcp_plumbing).
- Brief edits at JM root: added bare `# Title` headings + the "≥2 edge_cases mirrored" plan-shape
  invariant to all 5 spine briefs; embedded pinned contracts.
- 11 slugs were added to `state/control/autowork/auto_promote.allowlist` (all now spent). Decision
  files for harness_self_fix tasks under `state/control/decisions/`.
- Edited NGv2 test files: the 4 README-authoring sub-agents and oracle authors committed test files;
  `1aa3ef6` (JM side) changed an integration test's ratio bound.

---

## 3. Issues ALREADY found this session (re-verify they're truly resolved, and look for siblings)

### 3.1 ⚠ CRITICAL regression (found by adversarial sweep, claimed fixed)
A5 (`e55ac66`) was meant to ADD `PocMarkerStubChecker` additively but **REPLACED** `ASTVerifier` with a
gutted reflection-based version: `ASTResult.valid` always None, dropped syntax/`os.system`/`subprocess`/
`/dev/null` checks (`os.system("rm -rf /")` → 0 violations), removed `verify_file()`. The pre-existing
`tests/test_ast_verifier.py` went 8/11 RED but the A5 `*_marker_wired` oracle stayed GREEN because it
only checked the new marker + symbol IMPORTABILITY, not existing BEHAVIOR. Claimed fixed by `1cf90af`
(restore original + keep marker; gate = both oracles, 15/15). **VERIFY the fix is real AND hunt every
other EDIT leaf for the same class of silent clobber (§5b).**

### 3.2 Moderate gaps found by the 4-agent sweep
- Epic C: `done` unreachable (FIXED `289707d`); session_mcp `__main__` crash (NOT fixed — blocked,
  pending the in-flight `_ast_merge` fix; see §4); submit_artifacts dup crash (FIXED `4a19f88`).
- Epic A: marker checker FALSE-POSITIVE on `ngv2/confidence.py:36` (`return 'CONFIRMED'`, a legit enum).
  NOT fixed — confirm impact and whether it fires elsewhere.
- Minor (NOT fixed): `feedback_synth` truncation is line-based (a giant single-line stream bypasses the
  250/750 bound); `semantic_verdict` empty-marker/empty-signature degenerate-confirm; `transition_with_gate`
  raises `ValueError('None')` on the disallowed-but-passing path (cosmetic message).

---

## 4. Open / in-flight items at handoff time
- **`fix_ast_merge_main_guard`**: LANDED `20bc82c` (verified 36/36, no truncation). Re-verify per §5a.
- **`cfix-mcp-main`**: LANDED `d47ef507` after the merge fix — `ngv2/session_mcp.py:52` now
  `SessionApi(SessionDB(resolve_db_path()))`; mcp oracles 14/14, full NGv2 spine suite 102/102 green.
  ⇒ ALL 3 Epic-C gaps are now fixed. Re-verify the merge actually applied the __main__ change (§5b).
- **Epic E `spine_distill_landing`**: intentionally NOT built (optional; no divergence observed → no-op).
- **Live runner `ngv2/poc_runner_live.py`**: intentionally ABSENT (quarantined owner infra). Confirm it
  was NEVER created/dispatched (grep the repo).
- **Allowlist**: 11 spent slugs still present (deny-all boundary not restored). Daemon `flag=resume`,
  running (pid was 1258348).

---

## 5. ADVERSARIAL CHECK DIRECTIVES — what to hunt (the core of your job)

### 5a. Damage to the JanusMaskJR harness itself (regressions in the factory)
The 5 self-edits (§2c) touch `orchestrator.py`, `autowork_daemon.py`, `plan_normalizer.py`,
`git_integration.py`. For EACH:
- Run the FULL relevant JM test suites and confirm green, not just the fix's own oracle:
  `cd /home/xnihil0zer0/JanusMaskJR && python -m pytest tests/ -q` (note: a few pre-existing
  `test_*_export.py` collection errors are unrelated to this session — confirm they predate it via git).
  Pay special attention to: `tests/adversarial/test_ast_merge_regression_adversarial.py`,
  `tests/integration/test_auto_commit_merge.py`, `tests/test_autowork_daemon.py`,
  `tests/test_daemon_agy_pool.py`, and anything touching `prepare_task_prompt` / `plan_normalizer`.
- `_ast_merge` (git_integration.py): diff against the pre-session version
  (`git show <pre-session-sha>:harness/git_integration.py`) and confirm the ONLY behavioral change is
  the __main__-guard keying. Adversarially craft merges (duplicate symbols, forward refs, imports,
  JANUSMASK_DELETE, nested classes, a `__main__` inside a class body) and confirm no corruption.
  A silent merge bug here would mis-commit future leaves.
- `prepare_task_prompt`: confirm SELF tasks and NEW-file external tasks still get the whole-file prompt
  (the NEW-FILE GUARD) and only existing external EDIT targets get partial-edit. A wrong flip would
  make every NEW-file build emit patches (which can't create files).
- `_build_worker_env` / autowork_daemon: confirm BOTH spawn paths set JANUSMASK_WORKING_DIR for external
  and POP it for self/invalid; confirm the agy-pool slot logic on the parallel path is intact; confirm
  no env leakage into self builds.
- `plan_normalizer._canonicalize_oracle_paths`: confirm it is idempotent on correct input, never
  invents a path that doesn't exist, and is safe for self/JM `tests/test_*.py`.
- Confirm the running daemon is actually executing the POST-restart code (the env fix needed a restart;
  has anything since required another restart?).

### 5b. Reproduce-anchor CLOBBERS in EDIT leaves (the §3.1 class — likely more exist)
The R-anchor / whole-file mechanism forces the blind worker to REPRODUCE an existing symbol; it can
silently rewrite it. The wired oracles often only assert the NEW behavior + symbol importability. For
EACH EDIT leaf, run the module's PRE-EXISTING test file(s) (NOT just the `*_wired` oracle) and read the
diff of the edited symbol against its prior commit:
- `ngv2/debate_router.py` (A4): did `route_finding`/`DebateFinding`/`_coerce_score`/`_extract_confidence`
  survive behaviorally? Run any pre-existing `tests/test_debate_router*.py`. (Earlier in-session A4
  FAILED once for exactly this — the agent rewrote route_finding; it was caught + fixed before commit,
  but re-verify the COMMITTED version.)
- `ngv2/ast_verifier.py` (A5 + fix): run `tests/test_ast_verifier.py` AND
  `tests/ngv2/test_ast_verifier_marker_wired.py` together; confirm `os.system`, bare-subprocess,
  /dev/null, syntax errors all flag and `valid` is computed.
- `ngv2/state_machine.py` (B4): confirm `HuntStateMachine.can_transition`/`transition`, `PHASES`,
  `ALLOWED_TRANSITIONS`, `add_finding`, `to_dict` all unchanged behaviorally (run any pre-existing
  state_machine tests).
- `ngv2/detonation.py` (D2 + earlier clobber): the D2 worker once rewrote `DetonationChamber.__init__`
  (caught + re-run). Confirm the COMMITTED `DetonationChamber` is byte-equivalent to its pre-D2 form
  (`git show 102f9c3^:ngv2/detonation.py` vs HEAD) except for the appended `semantic_verdict`.
- `ngv2/session_gate.py` (cfix-gate-done) and `ngv2/session_api.py` (cfix-api-dup): confirm the symbol
  patches changed ONLY the intended lines and preserved all other gate rules / handler behavior.
GENERAL METHOD: for every EDIT commit, `git show <sha> -- <file>` and eyeball that existing symbols are
untouched except the declared change.

### 5c. Vacuous / weak oracles (the gate that lets clobbers through)
The A5 marker oracle proved a weak oracle can pass a broken impl. Audit the hand-authored oracles for
non-vacuity — would each FAIL against a deliberately wrong implementation?
- Mutation-test the load-bearing ones: temporarily break the impl (e.g. make `semantic_verdict` always
  return 'confirmed'; make `gate_transition` always ok; make `payload_selection` return arm 0) and
  confirm the oracle goes RED. Any oracle that stays green on a broken impl is a gap.
- Specifically scrutinize: `test_payload_selection_wired.py` (the prior agent's own note: it may NOT
  distinguish PUCT from UCB1 — verify), `test_ast_verifier_marker_wired.py` (was weak — now paired with
  the strong original, confirm the PAIR is the gate everywhere it matters), and any oracle that only
  asserts "symbol is importable / callable" without exercising behavior.
- Confirm each oracle is actually RUN by the right verification_command and that the committed
  verification_command points at the REAL file (the planner mangled paths/filenames several times).

### 5d. NGv2 spine functional correctness end-to-end (does the assembled system actually work?)
The leaves were verified individually; verify they COMPOSE:
- Drive a full session through `SessionApi` over a real `SessionDB`: create_session → submit findings →
  transition hunt→triage → submit pocs → … → report → done. Confirm gates fire, audit rows are written
  on every attempt, and a session can actually reach `done` now.
- Confirm `session_mcp` imports with the `mcp` SDK absent (no `mcp` in sys.modules) and `build_tools(api)`
  exposes exactly the 3 tools delegating correctly.
- Drive the PoC loop described in README §"The PoC detonation system": variant → DetonationChamber.detonate
  over make_mock_runner/make_scripted_runner → semantic_verdict → build_diagnostic_prompt on non-confirm.
  Confirm the documented steps match the real APIs (the README was written by sub-agents — verify it
  against the code; flag any invented API or wrong signature).
- Run the WHOLE NGv2 suite: `cd /home/xnihil0zer0/NobleGreedv2 && python -m pytest tests/ngv2/ -q`
  (expect ~all green) AND `python -m pytest tests/ -q` (note/triage any failures: some pre-existing
  `test_*_export.py` collection errors predate this session — confirm via git that this session didn't
  introduce or worsen any failure).

### 5e. State / git / daemon hygiene (collateral damage)
- NGv2 git: confirm working tree is clean; README.md + .gitignore are the only doc/config additions;
  no stray files; `agentic_spine_research/` is gitignored not committed (200MB corpus). Confirm no
  spine commit accidentally included unrelated files (`git show --stat` each leaf).
- JM git: confirm only intended harness/test/decision files changed; no production hand-edit slipped in
  outside the pipeline (the owner rule: never hand-edit harness production outside the pipeline — verify
  every `harness/**` change rode a pipeline commit, not a manual edit). Check `git status` is clean.
- Stale state: check `state/tasks/blocked/` (cfix-mcp-main expected), `state/tasks/*.processing`,
  `state/output/*.{patches,files}.json` sidecars, `state/control/autowork/git_commit.lock`,
  external_staging worktrees under `/home/xnihil0zer0/JanusMaskJR_agentwork/external_staging/` and
  `git -C /home/xnihil0zer0/NobleGreedv2 worktree list` — any orphans from the many re-dispatches?
- Allowlist: 11 spent slugs remain. Decide whether to restore the deny-all boundary (owner call).
- Daemon: confirm exactly one daemon running, healthy, executing current code; supervisor
  `scripts/run-autowork.sh` intact. The prior agent did `kill -TERM` + supervisor respawn once.
- plan_hooks_*.json: the prior agent hand-injected directives into these. Confirm they're internally
  consistent (no broken JSON, no contradictory specs) and that spent briefs/plans are correctly
  archived or inert.
- Autocompiler layer is ON (`config/autocompiler.yaml`: population/determinism/decode/js all true).
  Confirm none of the session's changes destabilized it (run `tests/autocompiler/`).

---

## 6. Suggested execution
1. Read SPINE_HANDOFF.md, the memory file, and this doc fully.
2. Fan out (parallel reviewers ok): (a) JM-harness regression auditor [§5a], (b) NGv2 clobber+oracle
   auditor [§5b/§5c], (c) NGv2 end-to-end+README auditor [§5d], (d) hygiene auditor [§5e].
3. For every claimed-fixed item (§3), independently reproduce the BUG on the parent commit and confirm
   the fix commit resolves it — don't trust the green suite alone.
4. Mutation-test the load-bearing oracles (§5c).
5. Produce a findings report: each finding with file:line, severity, repro, and whether it's a GAP
   (missing work) or DAMAGE (regression introduced this session). Root-cause-fix anything real via the
   pipeline (RED oracle + leaf), NOT by hand-editing production — per owner directive.

## 7. Definition of done for THIS audit
- Every §2c harness self-edit proven correct AND non-regressive (full JM suite green + targeted diffs).
- Every EDIT leaf (§5b) proven to preserve existing-symbol BEHAVIOR (pre-existing tests green + diffs).
- Load-bearing oracles proven non-vacuous (mutation tests).
- NGv2 end-to-end session + PoC loop demonstrably works; README matches reality.
- State/git/daemon clean or discrepancies reported.
- A written findings list (GAP vs DAMAGE, with severity + repro). Note explicitly if NOTHING was found
  for a category (so coverage is auditable). Update memory with any new gotcha.
