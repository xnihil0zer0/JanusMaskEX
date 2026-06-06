# NobleGreedv2 — Epic-3 handoff (fix 2 discovered bugs, then author+run a FAT multi-level Epic-3)

Compiled 2026-06-06, right after **Epic-2 COMPLETE** (4 orchestration modules landed into
NobleGreedv2 via JM's external-build pipeline). Epic-2 surfaced TWO daemon/harness gaps that
block *fully hands-off* runs. This handoff: **(A)** fix both via the pipeline, then **(B)**
author and execute a deliberately **FAT, MULTI-LEVEL Epic-3** to stress-test (i) multiple
levels of plan decomposition (epic → sub-epics → leaves) and (ii) very long autonomous
pipeline execution. Read memory `ngv2-epic2-run-result`, `ngv2-epic1-run-result`,
`ngv2-cleanroom-rebuild-plan`, `never-hand-edit-production-outside-pipeline` FIRST.

---

## §0 PROMPT (paste this)

Resume the NobleGreedv2 clean-room rebuild (JanusMaskJR builds it — "JM as factory").
**Read FIRST (memory):** `ngv2-epic2-run-result`, `ngv2-epic1-run-result`,
`ngv2-phase0-external-build-proven`, `ngv2-cleanroom-rebuild-plan`,
`never-hand-edit-production-outside-pipeline`, then this file. JM repo
`/home/xnihil0zer0/JanusMaskJR` (HEAD `951ac22`, PUSHED). External target
`/home/xnihil0zer0/NobleGreedv2` (own git+venv, JM-owned marker, `master`==`janusmask/work`
==`24f31f7` = Epic-1 substrate + Epic-2 orchestration, **40/40 oracles pass**, NO git remote).
**Do PART A then PART B.**
**(A) Fix the two discovered bugs via the pipeline** so a long, multi-level, auto-decomposed
run is fully hands-off: **gap #1** = the daemon caps `smoke_failed` (and other "deterministic")
blocked-retry budgets at 1, so a flaky synthesis draft on a smoke-gated child is never
re-dispatched (deny-listed `autowork_daemon.py` → `harness_self_fix` + decision + RED oracle);
**gap #2b** = the diff-fuzzer (`io_adapter` & other non-bypass-fuzzer meta-types) runs the
candidate in a plain subprocess whose PYTHONPATH lacks the external `working_dir`, so a leaf
importing `ngv2.*` fails the fuzz gate (`harness/sandbox.py::sandbox_child_env`, NOT
deny-listed → auto-commits + RED oracle). After A, external leaves of ANY meta-type build
hands-off and draft flakes self-absorb.
**(B) Author and execute a FAT, MULTI-LEVEL Epic-3** (the hunt-to-submission deterministic
tooling) — root epic → ~4 sub-epics → ~12–16 leaves — to test multi-level decomposition +
long autonomous execution. VET the decomposition OFFLINE (does the decomposer emit sub-epic
children? if not, hand-author the level-1 sub-epic briefs and let the daemon auto-decompose
level-2), commit the leaf oracles into NGv2 first, run hands-off via the daemon, MONITOR
multi-level admission + agy concurrency + TOKEN SPEND (no cost budget stop), then close out.
Confirm JM sweep green (baseline **7013** passed at HEAD), gate stays `paused`/allowlist
deny-all between phases, push JM with sign-off.

HEAD at handoff: JM `951ac22` (PUSHED). Gate `paused`, allowlist deny-all, `parallel_cap: 5`,
no daemon, ngv2 NOT in JM venv.

---

## §1 STATE (verified)

- **JM** `951ac22` PUSHED. Sweep baseline = **7013 passed, 8 skipped, 5 xfailed, 0 failed**
  (run at `a5201ee`; `951ac22` adds only docs/artifacts on top). Gate `paused`, allowlist
  deny-all (`state/control/autowork/auto_promote.allowlist`), `parallel_cap: 5`, no daemon.
  Epic-2 PART-A fixes already landed+pushed: BUG#1 jail-PROJECT_ROOT `5c5f2e7`
  (orchestrator.py, `_external_jail_extra_ro`), BUG#2 smoke-extra_paths `a5201ee`
  (sandbox_smoke.py), oracles `ec592ea`.
- **NGv2** `master`==`janusmask/work`==`24f31f7`. Tree clean. venv py3.13+pytest. **40 oracles
  pass** = Epic-1 (contracts/state_machine/detonation) + Epic-2 (grounding/poc_runner/report/
  pipeline). `ngv2/__init__.py` + pyproject (packages=["ngv2"]).
- `hierarchical_planning.enabled: true`, `max_planner_depth: 4` in `harness/config.yaml`.
- The `/tmp/ngv2_dispatch_retry.sh` operator retry helper from Epic-2 is gone (in /tmp);
  re-create from §4 if you keep the manual fallback.

---

## §2 PART A — FIX THE TWO BUGS (do first; both are self-builds, so agents work)

After A, a fat multi-level run is fully hands-off: every leaf (any meta-type) that imports
`ngv2.*` builds, and a flaky first draft is re-dispatched instead of dead-ending.

### gap #1 — `smoke_failed` (and friends) capped at retry budget 1
**Cause:** `harness/autowork_daemon.py::_retry_blocked_tasks` (~line 926):
```
_DETERMINISTIC_OUTCOMES = ('synthesis_or_ast_failed', 'smoke_failed', 'embedded_tests_failed', 'narrow_fuzz_failed')
effective_max = 1 if last_outcome in _DETERMINISTIC_OUTCOMES else max_attempts   # max_attempts=3
```
The daemon RE-DISPATCHES (re-synthesizes a NEW candidate) on retry, so `smoke_failed` is
NON-deterministic at the draft level — a re-draft passes (PROVEN in Epic-2: `report` failed the
daemon's 1 smoke try, then accepted first-try on a plain manual re-dispatch with no spec
change). Budget-1 dead-ends the task into self-heal. For a ~16-leaf run, draft flakes are
near-certain, so this must be fixed for hands-off.
**Fix (recommended, minimal):** remove `'smoke_failed'` from `_DETERMINISTIC_OUTCOMES` so it
gets `max_attempts` (3) with the existing escalating backoff (300s→3600s→86400s) before
self-heal. Judgement call: `'synthesis_or_ast_failed'` is ALSO a pure re-synthesis flake and a
strong candidate to drop too; `'embedded_tests_failed'`/`'narrow_fuzz_failed'` more often
indicate a genuine logic bug the same spec reproduces — leave those as deterministic (budget 1)
unless you want maximal flake-absorption at the cost of 3× wasted cycles on a truly-broken
spec. Keep the `.exhausted`-marker guard (line ~911) intact (it must still permanently park a
task past budget).
**Where:** `harness/autowork_daemon.py` — **DENY-LISTED** (`_NEVER_AUTO_APPROVE`,
orchestrator.py:2174) → `meta_task_type=harness_self_fix` + `state/control/decisions/<tid>.json`
approve + hand-authored RED oracle. Single-symbol partial-edit of `_retry_blocked_tasks`
(reproduce the function, change only the tuple).
**Oracle:** drive `_retry_blocked_tasks` against a `blocked/<tid>.json` + `<tid>.retry.json`
with `{"attempts":1,"last_outcome":"smoke_failed"}`; assert the task is RE-STAGED to
`tasks/<tid>.json` (not `.exhausted`-marked) — i.e. effective budget > 1 for smoke_failed.
Also a negative: `attempts:3` → exhausted (budget still bounded).

### gap #2b — diff-fuzzer can't resolve EXTERNAL imports
**Cause:** non-`bypass_fuzzer` meta-types (`io_adapter`, `algorithm`, …) run the differential
fuzzer (`harness/diff_fuzzer.py`), which executes the candidate via
`harness/sandbox.py` (`Sandbox`/`BatchRunner`) in a **plain `subprocess.Popen([sys.executable,
runner_path, …])`** (sandbox.py:1358/1543/1747 — no bwrap wrapper). The subprocess env comes
from `sandbox_child_env(extra)` (sandbox.py ~line 114) = `os.environ.copy()` + thread guards.
`os.environ['PYTHONPATH']` is the JM root only; `ngv2.*` is NOT importable there (ngv2 not in
JM venv), so a leaf doing `from ngv2.contracts import Finding` fails the fuzz gate. (Epic-2
hit this — the planner assigned `io_adapter` to grounding+poc_runner; WORKAROUND was overriding
their plan `meta_task_type` to a smoke-gated type. That workaround does NOT scale to a
~16-leaf auto-decomposed run, hence fix it here.)
**Fix:** in `sandbox_child_env`, when `os.environ.get('JANUSMASK_WORKING_DIR')` is set and
`not _target_is_self(<wd>)` (lazy `from harness.paths import _target_is_self`), PREPEND that
external root to the returned env's `PYTHONPATH` (mirror BUG#2's approach in sandbox_smoke.py).
Self builds (env unset/self) are inert → byte-identical. The fuzz subprocess is unjailed so no
ro-bind is needed (if you later jail it, also thread the path into the jail's `extra_ro`).
**Where:** `harness/sandbox.py` — **NOT deny-listed** → AUTO-COMMITS (no decision file). Small
single-symbol partial-edit of `sandbox_child_env`. Hand-author the RED oracle.
**Oracle:** hermetic — a tmp `ext/pkg/mod.py` with `X=1`; with `JANUSMASK_WORKING_DIR=<ext>`
set, run a candidate `from pkg.mod import X` through `Sandbox`/`BatchRunner` (or assert
`sandbox_child_env()['PYTHONPATH']` contains `<ext>`); without the env it does not. Confirm a
self build's PYTHONPATH is unchanged.

**Verify A:** JM serial sweep green (0 new regressions vs 7013). Then sanity-check both:
(i) re-dispatch an external `io_adapter` leaf that imports `ngv2.contracts` → fuzz gate now
passes; (ii) inspect that a smoke_failed blocked task re-stages a 2nd time. (Epic-2's
`ngv2-grounding-adapter` brief/plan is a ready `io_adapter`-shaped test case — revert its plan
`meta_task_type` to `io_adapter` and re-run as a smoke test of gap#2b, then discard.)

---

## §3 PART B — AUTHOR + EXECUTE THE FAT MULTI-LEVEL Epic-3

**Goal: a deliberately FAT epic that decomposes TWO levels deep and runs LONG & hands-off.**
Content = the remaining hunt→submission deterministic tooling (per the rebuild plan: JM builds
the deterministic, mock-testable tooling; the live exploit execution stays at NGv2 runtime).
All leaves are pure, deterministic, stdlib-only `ngv2/` modules, IMPL-only (committed oracle),
single-file whole-file, depending ONLY on ALREADY-COMMITTED code (Epic-1 substrate + Epic-2
modules). **Design with NO intra-Epic-3 leaf deps** so the long run isolates the two axes under
test (decomposition DEPTH + long execution), not dep-gating (BUG #3 brief-level dep-gating is
still OPEN; adding leaf deps would need it or operator dep-injection).

### Suggested structure (refine after re-reading legacy NG `/mnt/ai-data/NobleGreed-legacy`)
Root epic `ngv2_epic3` "hunt-to-submission deterministic tooling" → 4 SUB-EPICS → ~12–16 leaves:
- **Sub-epic A `ngv2-intake`** (target intake & prioritization): `ngv2/huntr_data.py`
  (load eligibility/bounty/existing-submission JSON → typed records), `ngv2/prioritize.py`
  (`rank_targets` by expected-payout/ROI + saturation, deterministic ordering),
  `ngv2/dedup.py` (`filter_new(findings, existing_titles)`).
- **Sub-epic B `ngv2-grounding-full`** (grounding & confidence): `ngv2/semgrep_adapter.py`
  (`run_semgrep(target, *, runner)` injected-runner subprocess-adapter contract; mock the tool
  — pairs with Epic-2 `grounding.parse_semgrep`), `ngv2/fp_filter.py` (drop by-design/
  protocol-mandated FPs from `fp_patterns`), `ngv2/confidence.py` (4-tier
  CONFIRMED/HIGH/MEDIUM/LOW from multi-tool agreement).
- **Sub-epic C `ngv2-triage`** (triage & verdict): `ngv2/verdict.py` (`@dataclass Verdict`
  TP/FP+confidence, to_dict/from_dict/validate), `ngv2/triage_parser.py` (parse ng-triage
  debate JSON → Verdict; mock agent output), `ngv2/triage_aggregate.py`
  (`aggregate(verdicts)` counts + keep-TP filter).
- **Sub-epic D `ngv2-submission`** (submission packaging): `ngv2/cvss.py` (deterministic
  CVSS v3.1 base-score from a vector string), `ngv2/huntr_form.py`
  (`build_form(finding, poc, report)` → the 12 huntr form fields), `ngv2/submission.py`
  (`render_submission(form)->str` markdown + `assemble_package(finding, poc, live_test)->dict`).

This is 2 decomposition levels (epic→sub-epic→leaf, depth ≤ 3 ≤ `max_planner_depth:4`) and a
long serial run (~12–16 leaf builds + sub-epic decompositions). Each leaf is mock-testable and
depends only on committed contracts/Epic-2 modules.

### Multi-level decomposition: VET the decomposer first (KEY UNKNOWN)
Multi-level recursive epic decomposition is SUPPORTED + depth-gated + e2e-tested in code but
only PROVEN hands-off at depth-1 (Epics 1 & 2). The make-or-break: **does the epic decomposer
emit CHILD briefs marked as sub-epics (`plan_kind: epic` / `epic: true` frontmatter), or only
leaf children?** VET OFFLINE (`planner.cli` on the root brief, gate paused, nothing else
running) and INSPECT the produced `plan_hooks_ngv2_epic3.json` `child_briefs` /
`brief_hooks_ngv2-<subepic>.md`:
- **If the decomposer produces clean sub-epic children** (each a `plan_kind:epic` brief with
  its own child prose) → run FULLY hands-off (the real multi-level test). The transitive
  admission path is CONFIRMED to support this: `harness.brief_status._resolve_allowlisted_child_slugs`
  does a BFS DOWN each epic plan's `child_slugs`, so once a sub-epic's
  `plan_hooks_<subepic>.json` exists (created when the daemon plan-kickoffs it), its leaves are
  admitted too — allowlisting ONLY `ngv2_epic3` transitively admits the whole tree.
- **If it flattens to leaves / muddles the structure** (likely on a novel fat domain) → FALL
  BACK to the rebuild-plan rule "hand-author each level on novel domains": HAND-AUTHOR the 4
  sub-epic briefs (`brief_hooks_ngv2-{intake,grounding-full,triage,submission}.md`, each
  `epic:true` + prose enumerating its 3–4 leaves) AND a root `brief_hooks_ngv2_epic3.md` whose
  prose decomposes into exactly those 4 sub-epic slugs; pre-write the 4 sub-epic plans
  (`plan_hooks_<subepic>.json`, `plan_kind:epic`, `child_slugs=[leaves]`) so transitive
  admission sees them on tick 1, then let the daemon auto-decompose level-2 (sub-epic→leaves)
  + build hands-off. This still exercises multi-level ADMISSION + long execution while keeping
  the tree structurally correct.

### Run recipe
1. Author the brief(s) (root + maybe 4 sub-epics per the vet outcome). Pack EXACT signatures/
   dict-keys/imports into Scope/Deliverables/interfaces (the decomposition is interface-faithful
   when the prose is precise — proven in Epic-2). `working_dir: /home/xnihil0zer0/NobleGreedv2`
   in every brief's frontmatter. Each leaf: NEW module, SINGLE-FILE WHOLE-FILE, IMPL-only,
   explicit external vcmd `python -m pytest tests/test_<x>.py -q`.
2. Hand-author ALL leaf oracles (tests/test_<leaf>.py), ff NGv2 master→janusmask/work, and
   **commit them into NGv2 master** (the external dirty-gate needs a clean tree). ~12–16 oracle
   files; keep them tight (they ARE the contract the blind-draft must match).
3. VET OFFLINE: decompose the root, inspect sub-epic structure (above). With PART A landed you
   need NOT override leaf `meta_task_type`s (gap#2b makes `io_adapter` etc. resolve external
   imports). You MAY still pre-leaf-plan offline if you want determinism, but for the TRUE
   multi-level test let the daemon auto-decompose every level live.
4. RUN HANDS-OFF: `printf '%s\n' ngv2_epic3 >> state/control/autowork/auto_promote.allowlist`
   (transitive fast-path admits the whole tree); `printf run > state/control/orchestrator.flag`;
   set `parallel_cap: 1` in `harness/config.yaml` (serialize workers; revert to 5 after); start
   the daemon by EXPLICIT PID (`nohup python3 -m harness.autowork_daemon --state-dir state >
   /tmp/ngv2e3_daemon.log 2>&1 & echo $! > /tmp/ngv2e3_daemon.pid`). NEVER `pkill` (self-kills,
   exit 144) — kill by the saved PID.
5. MONITOR (this is a LONG run — budget for it):
   - **Token/wall spend** — `budget.total` is null here; there is NO cost stop. A ~16-leaf,
     2-level run + per-level decompositions is a LOT of agy calls; watch spend manually and be
     ready to pause (`printf paused > state/control/orchestrator.flag`).
   - **Multi-level admission** — `grep -E 'plan_kickoff|extract|auto_commit|retry_exhausted'
     state/impl_progress.jsonl`; confirm sub-epic plans appear, then their leaves get admitted/
     dispatched. `git -C /home/xnihil0zer0/NobleGreedv2 log --oneline master` (gap#2 ff-advances
     master per accept).
   - **agy concurrency** — for a multi-level run the daemon MUST plan-kickoff (decompose
     sub-epics, leaf-plan grandchildren) DURING the run, so a plan-kickoff (blocking planner
     agy in `_auto_promote`) can overlap a still-running worker agy even at `parallel_cap:1`.
     Epic-1's daemon auto-decompose tolerated this (designed path), but watch for gemini/registry
     "code 2" stalls; if they appear, pause, let the in-flight worker finish, resume. (Can't
     fully pre-plan a multi-level tree offline because grandchildren are unknown until sub-epics
     decompose.)
   - **Draft flakes** — with PART A gap#1, `smoke_failed` now re-dispatches (budget 3); a leaf
     that still exhausts after 3 + self-heal is a genuine spec/oracle mismatch — fix-brief it
     (clean sidecars `state/output/<tid>.*`, `tasks/processed|blocked/<tid>*`,
     `tasks/<tid>.json.processing`; re-dispatch).
6. CLOSE OUT: full NGv2 suite green (`/home/xnihil0zer0/NobleGreedv2/.venv/bin/python -m pytest
   -q` = 40 + new); JM sweep green (0 new regressions vs 7013); gate `paused`, allowlist
   deny-all, `parallel_cap` back to 5, kill daemon by PID; verify ngv2 NOT in JM venv; commit
   Epic-3 run artifacts; push JM with sign-off; update memory (new `ngv2-epic3-run-result`,
   note whether the decomposer emits sub-epic children, the agy-concurrency behavior under a
   long run, and the multi-level admission proof).

---

## §4 GOTCHAS / recipes (carried forward + Epic-2 lessons)

- **DENY-LISTED** (`_NEVER_AUTO_APPROVE`, orchestrator.py:2174 — decision file + RED oracle):
  `agent_jail.py, dbus_proxy.py, paths.py, git_integration.py, orchestrator.py,
  interceptors.py, selfheal.py, autowork_daemon.py, services/**`. **NOT deny-listed
  (auto-commit):** `sandbox.py, sandbox_smoke.py, diff_fuzzer.py, orchestrator_worker.py,
  planner/*.py, tests/**`.
- **Driving a self-fix:** hand-author RED oracle → commit it → write `plan_<slug>.json` (single
  task; `meta_task_type=harness_self_fix` ONLY for deny-listed) → `stage_task(...)` →
  `printf run > state/control/orchestrator.flag` → `scripts/impl_dispatch_once.sh <tid>` →
  check ledger `auto_commit`. Deny-listed also needs `state/control/decisions/<tid>.json`
  `{"task_id":..,"decision":"approve","scope":"harness/<file>.py"}`.
- **Until gap#2b lands**, an external leaf that imports `ngv2.*` MUST use a SMOKE-gated
  meta-type (smoke is fixed by Epic-2 BUG#2): `data_model, orchestration, sandbox_infra,
  planner_tooling, validation, mcp_plumbing` (or `stateful_fuzz`). After gap#2b, ANY meta-type
  works (fuzz resolves external imports too). Smoke-gated check:
  `META_TASK_POLICY[m]['bypass_fuzzer'] and not skip_smoke_gates`.
- **Epic-2 run mechanics (verified):** daemon REUSES a pre-existing `plan_hooks_<slug>.json`
  (no re-plan); epic-child dispatch needs `hierarchical_planning.enabled:true` (config) + the
  epic slug in the allowlist; the dry-run `_auto_promote` summary is hard-zeroed and its
  enumeration is NOT eligibility-gated (misleadingly broad) — the REAL path gates plan-kickoff
  AND extract on `_auto_promote_brief_eligible`. gap#2 ff-advances NGv2 `master` per accept so
  children see prior output.
- NEW module = SINGLE-FILE WHOLE-FILE; NEW top-level symbol on an EXISTING file = R-ANCHOR
  (PHASE_R_ANCHORED_PATCH: a 1-part-qualname symbol patch may carry extra top-level defs,
  inserted before the primary — git_integration.py:1095). Single-symbol partial-edits up to
  ~130–160 lines land clean; larger → split/whole-file. Self-builds let the agent READ the real
  source (faithful reproduce); whole-symbol reproduce may strip inline comments (behavior
  preserved; recover from git if the rationale matters).
- The blind-draft decomposition is INTERFACE-FAITHFUL when the brief prose carries exact
  signatures/dict-keys/imports (Epic-2 proof). L1 leaf-planning is FLAKY (validator needs
  `spec_author` + ≥2 edge_case regression/property tests; BOTH agent drafts must validate) —
  the daemon's escalating backoff + (post-gap#1) retry budget absorb it.
- Kill daemon/workers by EXPLICIT PID; `pkill -f <pattern>` self-kills the issuing shell block
  (exit 144). Never run `planner.cli` or a big pytest sweep concurrently with the daemon/a
  dispatch (agy/registry conflict).
- **Operator manual retry helper** (fallback if you don't run the daemon, or to land a stubborn
  leaf): clean sidecars → `stage_task(plan, tid, state, working_dir='/home/xnihil0zer0/NobleGreedv2')`
  → `JANUSMASK_WORKING_DIR=/home/xnihil0zer0/NobleGreedv2 python -m harness.orchestrator_worker
  --task-id <tid> --state-dir state`; retry on `smoke_failed`/`reject`. Proven first-try for
  grounding/poc_runner/pipeline in Epic-2.
- **STILL-OPEN gaps NOT addressed here:** BUG #3 (daemon has no brief-level dep gating — only
  task-level `dependencies`; design Epic-3 leaves dep-free to avoid it) and the diff-fuzzer
  ro-bind if it ever becomes jailed. The deeper "JM-vs-runtime line" (worker registry / GPU
  scheduling / phase-ROI loop) is intentionally NOT in Epic-3 — NGv2 will harvest JM's daemon.
