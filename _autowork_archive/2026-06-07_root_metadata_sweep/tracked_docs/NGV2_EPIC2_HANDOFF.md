# NobleGreedv2 — Epic-2 handoff (fix external-build bugs, then author+run Epic-2)

Compiled 2026-06-06, right after **Epic-1 COMPLETE** (all 3 substrate children landed
into NobleGreedv2 via JM's auto-decompose pipeline). Two pre-existing harness bugs in
the EXTERNAL-build path were diagnosed and *worked around* to land Epic-1; this handoff
is to **(A) fix both properly through the pipeline** so external source-reading builds
work hands-off, then **(B) author and execute Epic-2** (the hunt→triage→PoC→detonate→
report runtime). Read memory `ngv2-epic1-run-result`, `ngv2-cleanroom-rebuild-plan`,
`never-hand-edit-production-outside-pipeline` FIRST.

---

## §0 PROMPT (paste this)

Resume the NobleGreedv2 clean-room rebuild (JanusMaskJR builds it — "JM as factory").
**Read FIRST (memory):** `ngv2-epic1-run-result`, `ngv2-cleanroom-rebuild-plan`,
`ngv2-phase0-external-build-proven`, `never-hand-edit-production-outside-pipeline`,
then this file. JM repo `/home/xnihil0zer0/JanusMaskJR` (HEAD pushed); external target
`/home/xnihil0zer0/NobleGreedv2` (own git+venv, JM-owned via `.janusmask/bootstrap.json`
marker, NGv2 `master`=`7a36a33` = contracts+state_machine+detonation, 22 oracles pass,
NO git remote). **Do PART A then PART B:**
**(A) Fix the two external-build harness bugs via the pipeline** (so external builds that
READ external source work hands-off with `JANUSMASK_WORKING_DIR` set), then optionally the
daemon brief-level dep-gating gap. **(B) Author Epic-2** (the deterministic hunt→triage→
PoC→detonate→report orchestration over the Epic-1 substrate) and **execute it hands-off**
via the daemon auto-decompose path (now unblocked by A). Confirm JM sweep green (baseline
**7013** passed), commit oracles into NGv2 first, VET offline, run, close out, push.

HEAD at handoff: JM `5baf30a` (PUSHED). Gate `paused`, allowlist deny-all, no daemon.

---

## §1 STATE (verified)

- **JM** `5baf30a` PUSHED. Sweep baseline = **7013 passed, 8 skipped, 5 xfailed, 0 failed**.
  Gate `paused`, allowlist deny-all (`state/control/autowork/auto_promote.allowlist`),
  no daemon. Epic-1 fixes already landed+pushed: A2 `5964368` (brief_generator working_dir),
  A1 `0d969a0` (epic pipeline working_dir stamp), A3 `2a49c74` (cli._effective_repo_root /
  gap#4). Epic-1 artifacts committed `5baf30a`.
- **NGv2** `master`=`janusmask/work`=`7a36a33` (contracts `5a10771`, state_machine `e8cf0ff`,
  detonation `7a36a33`). Tree clean. venv py3.13+pytest9. `ngv2/__init__.py` + pyproject.toml
  (packages=["ngv2"]). All 3 oracles (tests/test_{contracts,state_machine,detonation}.py)
  committed + passing (22).
- A dead prior-workstream task `oracle-resolve-interfaces-staging` had its blocked/ retry
  sidecars quarantined to `/tmp/ngv2_stale_aside/` to stop `_retry_blocked_tasks` from
  re-dispatching it; restore only if that workstream resumes.

---

## §2 PART A — FIX THE TWO EXTERNAL-BUILD BUGS (do first; self-builds, so agents work)

Both ONLY bite EXTERNAL tasks. Self-builds (editing JM's own `harness/**`) are unaffected,
so you can build these fixes through the normal pipeline. After A, an external build with
`JANUSMASK_WORKING_DIR=<NGv2>` set works end-to-end (binary found + agent can READ external
source + smoke resolves external imports) — the full hands-off auto-decompose for Epic-2.

### BUG #1 — jail T_RETARGET drops PROJECT_ROOT (claude binary + harness unbound)
**Cause:** `harness/orchestrator.py::spawn_agent` (~:391-400) retargets the jail `repo_root`
to the external tree for external tasks, and `harness/agent_jail.build_jail_argv` ro-binds
only `repo_root` + `_SYSTEM_RO` (/usr,/bin,/sbin,/lib*,/etc,/opt) + HOME subdirs
(~/.nvm,~/.gemini,~/.claude). The claude command is the VENDORED
`${PROJECT_ROOT}/.agents/claude-code/node_modules/.bin/claude` — **under the JM repo**,
which is NOT bound when repo_root=NGv2 → `bwrap: execvp ...claude: No such file or
directory` → agents die silently in ~18s (`both_agents_timed_out`, zero output). The
hooks `python3 -m harness.hooks.claude.*` also need `harness` importable (also under JM).
**CONFIRMED FIX (empirically):** replicating the jail with `extra_ro=['/home/xnihil0zer0/JanusMaskJR']`
makes the external jail run claude rc=0. So: when the jail repo_root is external, ALSO
ro-bind PROJECT_DIR.
**Where:** `harness/orchestrator.py` (DENY-LISTED → `meta_task_type=harness_self_fix` +
`state/control/decisions/<tid>.json` approve file + hand-authored RED oracle).
**Recommended shape:** add a small top-level helper
`_external_jail_extra_ro(jail_repo_root) -> list[str]` returning `[str(PROJECT_DIR)]` when
`Path(jail_repo_root).resolve() != PROJECT_DIR.resolve()` else `[]`; pass
`extra_ro=_external_jail_extra_ro(_jail_repo_root)` into the `build_jail_argv(...)` call at
orchestrator.py:400. R-ANCHOR the new symbol (ride it on an existing small top-level fn's
patch). **Oracle:** unit-test the helper (external path → [PROJECT_DIR]; self/PROJECT_DIR
→ []); optionally assert `build_jail_argv(repo_root=<ext>, extra_ro=[PROJECT_DIR])` argv
contains a `--ro-bind <PROJECT_DIR> <PROJECT_DIR>` pair.

### BUG #2 — smoke_import is hard-rooted at JM (can't resolve external deps)
**Cause:** `harness/sandbox_smoke.smoke_import` runs the candidate under a SCRUBBED env with
`PYTHONPATH = [tempdir, _discover_project_root() (always JM — walks up to .git), site-packages]`
via `python -S -c 'import <candidate>'`. A candidate that does `from ngv2.contracts import …`
is unresolvable → `smoke_failed`. The smoke gate runs for meta-types with `bypass_fuzzer:True`
and not in `SKIP_SMOKE_GATE_TYPES` (orchestrator_worker.py:471-473). Epic-1 detonation
(`orchestration` meta-type) hit this; state_machine dodged it (its policy is
`stateful_fuzz:True`, no smoke); contracts (`data_model`) ran smoke but is stdlib-only.
**Where:** `harness/sandbox_smoke.py` + `harness/orchestrator_worker.py` (BOTH NOT
deny-listed → AUTO-COMMITS, no decision file). Hand-author the RED oracle.
**Recommended shape:** give `smoke_import(module_name, module_src, *, timeout=…, extra_paths=())`
an `extra_paths` param appended to `path_parts` AND ro-bound into the smoke jail (mirror the
existing site-packages handling). In `orchestrator_worker.py` at the smoke call, compute the
task's external working_dir (from the task dict; external iff set and `not _target_is_self`)
and pass `extra_paths=[working_dir]`. **Oracle:** hermetic — a tmp dir with `pkg/mod.py`,
a candidate `from pkg.mod import X`; `smoke_import(..., extra_paths=[tmpdir])` returns None
(resolves) while without it returns an error.

### BUG #3 (OPTIONAL, lower priority) — daemon has NO brief-level dep gating
`_auto_promote`/`collect_dispatchable_tasks` (autowork_daemon.py:246-251) only gate
TASK-level `dependencies` (accepted-set keyed on task_id); the leaf planner can't emit a dep
on a sibling's task_id, so epic children with only BRIEF-level deps would dispatch L1 before
L0 accepts. Epic-1 workaround = operator injects `dependencies:[<L0 task_id>]` into the L1
child plans before running. PROPER FIX (autowork_daemon.py, DENY-LISTED): when staging an
epic child's tasks, resolve the child brief's sibling `dependencies` → those siblings' plan
task_ids → inject as task-level deps (or gate staging on them). If you skip #3, keep using
the operator dep-wiring step in §3.

**Verify A:** JM serial sweep green (0 new regressions vs 7013); then re-confirm an external
build works WITH the retarget by dispatching a trivial external smoke task with
`JANUSMASK_WORKING_DIR=<NGv2>` set (agents should spawn + smoke should pass).

---

## §3 PART B — AUTHOR + EXECUTE EPIC-2 (hunt→triage→PoC→detonate→report)

Epic-2 builds the DETERMINISTIC orchestration of NobleGreedv2's hunting runtime ON TOP of
the Epic-1 substrate (`ngv2.contracts` Finding/PoC/LiveTestReport, `ngv2.state_machine`
HuntStateMachine/PHASES, `ngv2.detonation` DetonationChamber). The dangerous LIVE work
(running real exploit PoCs) stays data-driven at NGv2 runtime; JM only manufactures the
deterministic, mock-testable tooling (the regime JM's gates love).

**HARVEST from legacy NG** (`/mnt/ai-data/NobleGreed-legacy`): the Claude subagent prompts
(`.claude/agents/ng-hunter`, `ng-mff-hunter`, `ng-poc-writer`, `ng-verifier`, `ng-triage`),
huntr eligibility/bounty data (`data/huntr_*.json`), grounding approach (semgrep/joern/codeql
+ taint specs), and the shipped `huntr-submission-packages/*/_poc.js` as a GOLDEN regression
corpus for the detonation harness.

**Suggested child DAG (single level — design carefully, this is a novel domain; do NOT
auto-recurse).** Candidates (refine after reading the legacy artifacts):
- `ngv2-pipeline-orchestrator` → `ngv2/pipeline.py`: drives a `HuntStateMachine` through
  hunt→triage→poc→detonate→report over INJECTED phase handlers (callables), pure +
  deterministic + mock-testable. Depends on contracts + state_machine + detonation.
- `ngv2-grounding-adapter` → `ngv2/grounding.py`: deterministic adapter that turns a
  grounding tool's JSON output (semgrep/joern/codeql) into `Finding`s. Pure parse/normalize
  (mock the tool output); depends on contracts.
- `ngv2-report` → `ngv2/report.py`: deterministic report builder from a `HuntState` +
  `LiveTestReport`s → a serializable report dict/markdown. Depends on contracts + state_machine.
- (optional) `ngv2-poc-runner-contract` → `ngv2/poc_runner.py`: the deterministic
  `runner(poc, target_spec) -> (exit_code,stdout,stderr,duration_ms)` ADAPTER contract the
  DetonationChamber consumes (the real subprocess/bwrap runner lives at NGv2 runtime; here
  build the pure injection seam + a mock).

**Recipe (now unblocked by PART A):**
1. Author `brief_hooks_ngv2_epic2.md` (`plan_kind: epic`, top-level `working_dir:
   /home/xnihil0zer0/NobleGreedv2`, prose Scope/Deliverables enumerating each child with
   EXACT module path, signatures, dict-keys, validation — the epic blind-draft DECOMPOSES
   the prose into child_briefs, so pack full specs into Scope/Deliverables/interfaces).
   Each child: NEW module → SINGLE-FILE WHOLE-FILE; IMPL-ONLY (committed oracle); explicit
   external vcmd `python -m pytest tests/test_<x>.py -q`.
2. Hand-author the child oracles, ff NGv2 master→janusmask/work, and **commit them into
   NGv2 master** (external dirty-gate needs a clean tree).
3. VET OFFLINE (never while the daemon runs): `python -m harness.planner.cli
   brief_hooks_ngv2_epic2.md --output-plan plan_hooks_ngv2_epic2.json` then plan each child
   brief; inspect each child plan for working_dir, NGv2-rooted vcmd, IMPL-only, interface
   matching its oracle. L1 leaf-planning is FLAKY (validator needs `spec_author` + ≥2
   edge_case regression/property tests; BOTH agent drafts must validate) — retry; the daemon
   has escalating backoff for this.
4. **Cross-child ordering:** if you did NOT land BUG #3, inject `dependencies:[<L0 task_id>]`
   into each L1 child plan (the L0 task_id is whatever the L0 child plan emitted, e.g.
   `ngv2_contracts_impl`-style). If you DID land #3, the daemon dep-gates by brief deps.
5. Run hands-off: `printf '%s\n' ngv2_epic2 >> state/control/autowork/auto_promote.allowlist`
   (epic-child fast-path admits children); `printf run > state/control/orchestrator.flag`;
   start the daemon by EXPLICIT PID (`nohup python3 -m harness.autowork_daemon --state-dir
   state > /tmp/ngv2e2_daemon.log 2>&1 & echo $!`); never `pkill` (self-kills → exit 144).
   With PART A landed and `JANUSMASK_WORKING_DIR` flowing (gap#3 `_spawn_worker`), external
   children that READ contracts/state_machine BUILD correctly (binary found + smoke resolves
   + accept-verify in the NGv2 worktree; gap#2 advances master per accept).
6. MONITOR: `grep -E 'auto_commit|reject_rollback|blocked' state/impl_progress.jsonl`
   (`auto_commit` row = ground truth; ignore the spurious `{"skipped":"not_found"}` stdout),
   `git -C /home/xnihil0zer0/NobleGreedv2 log --oneline master`, and TOKEN/WALL spend (depth
   budget is NOT cost-aware). Fix-brief any failing child before continuing; clean stale
   sidecars (`state/output/<tid>.*`, `tasks/processed/<tid>.json`, `tasks/blocked/<tid>*`,
   `tasks/<tid>.json.processing`) before re-dispatch.
7. CLOSE OUT: JM sweep green, gate `paused`, allowlist deny-all, kill daemon by PID, push JM
   with sign-off; NGv2 commits live in NGv2's own git (set up a remote first if you want them
   pushed). Update memory.

---

## §4 GOTCHAS / recipes (carried forward)

- **Driving a self-fix through the pipeline:** hand-author RED oracle → commit it → write
  `plan_<slug>.json` (single task; `meta_task_type=harness_self_fix` ONLY for deny-listed
  files) → `python -c "from harness.planner.staging import stage_task; stage_task(...)"` →
  `printf run > state/control/orchestrator.flag` → `scripts/impl_dispatch_once.sh <task_id>`
  (orchestrator path; honors the gate flag) → check ledger `auto_commit`. Deny-listed also
  needs `state/control/decisions/<tid>.json` approve.
- **DENY-LISTED** (decision file + RED oracle): orchestrator.py, autowork_daemon.py,
  git_integration.py, planner/staging.py, agent_jail.py, paths.py, dbus_proxy.py,
  interceptors.py, selfheal.py, services/**. **NOT deny-listed (auto-commit):**
  orchestrator_worker.py, sandbox_smoke.py, planner/plan_normalizer.py, planner/cli.py,
  planner/brief_generator.py, tests/**.
- Single-symbol partial-edit patches up to ~130 lines land clean; larger → split/whole-file.
  NEW top-level symbol → R-ANCHOR (ride as a trailing def on an existing symbol's patch).
- NEVER hand-commit production/agent output (bypasses the gate / the JM-as-factory thesis).
  Oracles/tests MAY be hand-authored.
- Kill daemon/workers by EXPLICIT PID; `pkill` self-kills the issuing block (exit 144).
- Never run `planner.cli` or a big pytest sweep concurrently with the daemon/a dispatch.
- The Epic-1 smoke workaround (`pip install <NGv2>` into the JM venv) is NO LONGER NEEDED
  once BUG #2 is fixed — and it dirties NGv2 (`build/`,`ngv2.egg-info/`); don't reuse it.
