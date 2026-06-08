# NobleGreedv2 — Epic-3 RESUME handoff (fix daemon epic-kickoff hallucination bug + slug collision, then finish the live multi-level run)

Compiled 2026-06-06 mid-Epic-3. PART A (both discovered bugs) is DONE+verified, the
two decomposer defects are FIXED+VET-proven, and the fully-live multi-level Epic-3 run
was launched — but the daemon got stuck: its planner-hallucination guard discards EVERY
epic plan-kickoff because epic plans carry `child_slugs`/`child_briefs` and no `tasks`.
This handoff: fix that daemon guard (deny-listed → harness_self_fix), fix a slug
collision in the Epic-3 briefs, clean the half-written artifacts, then resume the
hands-off run to completion. **Read memory FIRST:** `ngv2-epic2-run-result`,
`ngv2-epic1-run-result`, `ngv2-phase0-external-build-proven`, `ngv2-cleanroom-rebuild-plan`,
`never-hand-edit-production-outside-pipeline`, then `NGV2_EPIC3_HANDOFF.md` (the original
Epic-3 brief) and this file.

---

## §0 PROMPT (paste this)

Resume the NobleGreedv2 clean-room rebuild (JanusMaskJR builds it — "JM as factory").
Read memory `ngv2-epic2-run-result`, `ngv2-epic1-run-result`,
`ngv2-phase0-external-build-proven`, `ngv2-cleanroom-rebuild-plan`,
`never-hand-edit-production-outside-pipeline`, then `NGV2_EPIC3_HANDOFF.md` and
`NGV2_EPIC3_RESUME_HANDOFF.md`. JM repo `/home/xnihil0zer0/JanusMaskJR` (HEAD `6d3624d`,
NOT pushed — 9 commits ahead of origin/master `951ac22`). External target
`/home/xnihil0zer0/NobleGreedv2` (own git+venv, JM-owned marker, `master`==`24f31f7`
substrate+orchestration PLUS oracle commit `d54f091` = the 12 Epic-3 leaf oracles; NO git
remote). PART A + the decomposer fixes are DONE and landed. **Finish Epic-3:** (1) fix the
daemon epic-kickoff hallucination bug (`_check_hallucination` flags epic plans as
`empty_plan` because they have no `tasks` → every sub-epic plan-kickoff is discarded;
deny-listed `autowork_daemon.py` → `harness_self_fix` + decision + RED oracle); (2) fix the
`ngv2-submission` sub-epic↔leaf slug collision in the Epic-3 briefs; (3) clean the
half-written artifacts + the `.failed` backoff marker; (4) re-launch the daemon hands-off
for the fully-live multi-level run (root → 4 epic-marked sub-epics → 12 leaves → 12 NGv2
builds); (5) monitor multi-level admission + agy concurrency + token spend (no cost stop);
(6) close out (NGv2 suite green, JM full sweep 0-regression, gate paused, allowlist
deny-all, parallel_cap back to 5, push JM, update memory). Gate is `paused`, daemon dead.

---

## §1 STATE (verified at handoff)

- **JM** HEAD `6d3624d`, **NOT pushed** (9 commits ahead of origin/master `951ac22`).
  Gate `paused` (`state/control/orchestrator.flag`). Daemon DEAD (killed by PID). Allowlist
  = `ngv2_epic3` (one slug; `state/control/autowork/auto_promote.allowlist`).
  `harness/config.yaml` `autowork.parallel_cap: 1` (set for the run; revert to 5 at
  close-out), `hierarchical_planning.enabled: true`, `max_planner_depth: 4`.
- **NGv2** `master`==`janusmask/work`==`d54f091` (= `24f31f7` substrate+Epic-2 + the Epic-3
  oracle commit). Tree CLEAN. 12 leaf oracles committed: `tests/test_{huntr_data,prioritize,
  dedup,semgrep_adapter,fp_filter,confidence,verdict,triage_parser,triage_aggregate,cvss,
  huntr_form,submission}.py` (all RED — modules don't exist yet). 40 prior oracles still pass.
- ngv2 NOT installed in the JM venv (gap#2b makes that unnecessary).

### Commits landed THIS session (all via the pipeline unless noted)
PART A: `72972d9` gap#2b sandbox_child_env external PYTHONPATH (auto-commit), `7d1925e`
gap#1 smoke_failed retry budget (harness_self_fix+decision), oracles `fc98481`, escalation
test realign `f8abab7` (hand-authored test).
Decomposer fixes: `e0de030` serialize `epic: true` for sub-epic children, `17dfce2`
`_finalize_epic_children` (canonicalize+dedupe slugs, mark children epic when parent
declares `child_epics`), oracles `4c7f123`, slug-posture test realigns `f55f213`+`6d3624d`
(hand-authored tests).
**JM full serial sweep was GREEN (0 failures) after the PART-A test realigns**; the
decomposer-fix commits added only planner tests (+ the realigns) — re-run the full sweep at
close-out to confirm 0-regression on the final HEAD.

### Epic-3 artifacts present in the JM repo
- `brief_hooks_ngv2_epic3.md` — ROOT epic brief (`epic: true`, `child_epics: true`,
  `working_dir: /home/xnihil0zer0/NobleGreedv2`). Decomposes into 4 sub-epics.
- `plan_hooks_ngv2_epic3.json` — ROOT epic plan (`plan_kind: epic`, `epic_slug: ngv2_epic3`,
  `child_slugs: [ngv2-grounding-full, ngv2-intake, ngv2-submission, ngv2-triage]`, every
  embedded child_brief `epic: true`). VET-produced + verified.
- `brief_hooks_ngv2-{intake,grounding-full,triage,submission}.md` — 4 SUB-EPIC briefs,
  each `epic: true` in frontmatter (level-1 decomposition, VET-proven interface-faithful).
- **STRAY (delete — see §4):** `brief_hooks_ngv2-{verdict,triage-parser,triage-aggregate}.md`
  (leaf briefs the discarded `ngv2-triage` kickoff wrote before its plan was discarded).
- **STALE backoff marker (delete — see §4):** `state/control/autowork/plan_attempts/ngv2-triage.json`
  (`attempts:1` → 300s backoff). (`e2e_acceptance_test.json` and `planner_depth_and_recursion.json`
  in that dir are UNRELATED pre-existing markers — leave them.)
- No sub-epic plans exist (all kickoffs were discarded). Leftover Epic-1/2 briefs/plans
  (`ngv2-artifact-contract`, `ngv2-grounding-adapter`, `ngv2-state-machine`, etc.) are inert
  (not allowlisted/admitted) — ignore.

---

## §2 THE DAEMON BUG (fix FIRST — it blocks the whole run)

**Symptom:** the daemon launched, plan-kickoffed sub-epic `ngv2-triage`, `_run_epic_pipeline`
wrote its 3 leaf briefs (verdict/triage-parser/triage-aggregate) AND the epic plan, but the
daemon then emitted `planner_hallucination_discarded ... reason=empty_plan`, UNLINKED the
epic plan, and wrote a `.failed` backoff marker. It loops doing this for every admitted
sub-epic → no sub-epic plan ever persists → leaves never get admitted → 0 builds. (Epic-1/2
never hit this: the operator decomposed the ROOT epic OFFLINE via `planner.cli` and the
daemon only EXTRACTED+dispatched leaf tasks — daemon-driven *epic* plan-kickoff was never
exercised.)

**Root cause:** `harness/autowork_daemon.py::_check_hallucination` (def at line ~1259) does
`tasks = plan_dict.get('tasks'); if not isinstance(tasks, list) or not tasks: return (True,
'empty_plan')`. An EPIC plan legitimately has NO `tasks` — it carries `child_slugs` +
`child_briefs`. So every epic plan is mis-flagged as a hallucinated empty plan and discarded
at `_auto_promote` lines ~1542-1571 (`if hallucinated: output_plan.unlink(); write .failed
marker; emit planner_hallucination_discarded`).

**Fix (recommended, minimal):** in `_check_hallucination`, BEFORE the `tasks` check, special-
case epic plans:
```python
    if isinstance(plan_dict, dict) and plan_dict.get('plan_kind') == 'epic':
        child_slugs = plan_dict.get('child_slugs')
        if isinstance(child_slugs, list) and child_slugs:
            return (False, '')          # a non-empty epic decomposition is valid
        return (True, 'empty_epic')     # genuinely empty epic decomposition is still a halluc
```
Keep the `wall < min_wall` guard ABOVE this (a sub-min-wall epic kickoff is still suspicious),
and leave the existing `tasks`/`all_gemini_no_reconciled` logic UNCHANGED for leaf plans.
**Where:** `harness/autowork_daemon.py` — **DENY-LISTED** (`_NEVER_AUTO_APPROVE`) →
`meta_task_type=harness_self_fix` + `state/control/decisions/<tid>.json` approve + hand-authored
RED oracle. Single-symbol partial-edit of `_check_hallucination` (it's small — reproduce the
whole function, add the epic branch). **Dispatch via the WORKER path** (`harness_self_fix` is
`bypass_fuzzer+skip_smoke_gates+skip_structural_decomp` → single-agent straight to
`_auto_commit_accepted`; the full orchestrator differential-fuzzes and decomposes — DON'T use
`impl_dispatch_once.sh` for harness self-fixes that read os state, see §5 LESSON 1).
**Oracle:** drive `_check_hallucination` directly: an epic plan dict `{'plan_kind':'epic',
'child_slugs':['a','b'], 'child_briefs':[...]}` with `wall>=min_wall` → `(False, '')`; an
epic plan with empty/missing `child_slugs` → `(True, 'empty_epic')`; a normal leaf plan with
tasks → unchanged `(False,'')`; a leaf plan with no tasks → still `(True,'empty_plan')`; a
sub-min-wall epic → `(True,'wall<min')`.

---

## §3 THE SLUG COLLISION (fix in the briefs BEFORE re-run — no pipeline needed)

Sub-epic D's slug is `ngv2-submission` AND its 3rd leaf (ngv2/submission.py, test_submission.py)
is ALSO `ngv2-submission`. When the daemon decomposes the `ngv2-submission` SUB-EPIC,
`_run_epic_pipeline` will write `brief_hooks_ngv2-submission.md` for the LEAF — OVERWRITING the
sub-epic brief — and the slugs collide in admission/plans. **Fix:** rename the SUB-EPIC (not
the leaf — the leaf must stay `ngv2-submission` to match `test_submission.py`). Recommended:
sub-epic slug `ngv2-submission` → `ngv2-submission-pkg`. Edits (all are brief/plan files, no
pipeline):
1. `git mv brief_hooks_ngv2-submission.md brief_hooks_ngv2-submission-pkg.md` (or rewrite).
2. In `brief_hooks_ngv2_epic3.md` (root): change the sub-epic D slug reference
   `ngv2-submission` → `ngv2-submission-pkg` in the Scope/Deliverables prose (leave the LEAF
   `ngv2-submission` reference intact).
3. In `plan_hooks_ngv2_epic3.json` (root plan): change `child_slugs` entry `ngv2-submission`
   → `ngv2-submission-pkg`, and the matching embedded `child_briefs[].slug`.
4. Verify no OTHER sub-epic↔leaf slug collisions (none found: triage vs triage-parser/aggregate
   differ; intake/grounding-full distinct from their leaves).
ALTERNATIVE if you prefer regenerating cleanly: delete `plan_hooks_ngv2_epic3.json` + the 4
sub-epic briefs, rename sub-epic D in the root brief prose, then re-VET the root offline
(`planner.cli brief_hooks_ngv2_epic3.md --output-plan plan_hooks_ngv2_epic3.json`) and confirm
the 4 sub-epic briefs are `epic: true` with deduped slugs (the decomposer fixes make this
deterministic) — but the simple rename above is lower-risk.

---

## §4 CLEANUP (before re-launch)

```
cd /home/xnihil0zer0/JanusMaskJR
# stray leaf briefs from the discarded ngv2-triage kickoff
rm -f brief_hooks_ngv2-verdict.md brief_hooks_ngv2-triage-parser.md brief_hooks_ngv2-triage-aggregate.md
# stale backoff marker so ngv2-triage re-kickoffs immediately (leave the 2 unrelated markers)
rm -f state/control/autowork/plan_attempts/ngv2-triage.json
# any half-written sub-epic plans (should be none, but be safe)
rm -f plan_hooks_ngv2-intake.json plan_hooks_ngv2-grounding-full.json plan_hooks_ngv2-triage.json plan_hooks_ngv2-submission-pkg.json
# the dead daemon's pid/log
rm -f /tmp/ngv2e3_daemon.pid /tmp/ngv2e3_daemon.log
```
Confirm NGv2 clean (`git -C /home/xnihil0zer0/NobleGreedv2 status --porcelain` empty) and at
`d54f091`. Confirm no daemon/worker/planner procs: `ps -eo pid,args | grep -E
"harness.autowork_daemon|orchestrator_worker|harness.planner.cli" | grep -v grep`.

---

## §5 RE-RUN (fully-live multi-level, hands-off)

After §2 lands + §3 + §4: re-launch the daemon. It will: plan-kickoff each admitted SUB-EPIC
(now NOT discarded) → write its epic plan (`child_slugs`=3 leaves) + 3 leaf briefs → leaves
become transitively admitted → plan-kickoff each LEAF brief → leaf impl plan (has tasks) →
extract+dispatch worker → build into NGv2. ~16 plan-kickoffs + 12 builds over many ticks.

```
cd /home/xnihil0zer0/JanusMaskJR
printf run > state/control/orchestrator.flag
nohup /home/xnihil0zer0/miniconda3/bin/python -m harness.autowork_daemon --state-dir state \
  > /tmp/ngv2e3_daemon.log 2>&1 & echo $! > /tmp/ngv2e3_daemon.pid
# (use the miniconda python explicitly; `make`/bare `python` is not executable here — LESSON 4)
```
**MONITOR (LONG run — budget for it; NO cost stop):**
- `git -C /home/xnihil0zer0/NobleGreedv2 log --oneline master` — NGv2 master ff-advances per
  accept (gap#2). Expect 12 `Integrate validated code for ngv2-<leaf>` commits over time.
- `grep -E 'plan_kickoff|extract|auto_commit|retry_exhausted|hallucination' state/impl_progress.jsonl | tail`
  — confirm sub-epic plans now plan_kickoff (NOT discarded), then leaves admit/dispatch.
- Sub-epic plans appear: `ls plan_hooks_ngv2-{intake,grounding-full,triage,submission-pkg}.json`.
- `transitive admission`: `python -c "from pathlib import Path; from harness.brief_status import
  _resolve_allowlisted_child_slugs as r; print(sorted(r(Path('.'), {'ngv2_epic3'})))"` should
  grow from 4 sub-epics to 4+12 as sub-epic plans land.
- **agy concurrency**: at `parallel_cap:1` workers serialize, but a plan-kickoff (blocking
  planner agy in `_auto_promote`) can overlap a running worker agy. Watch for gemini/registry
  "code 2" stalls; if they appear, `printf paused`, let the in-flight worker finish, resume.
- **token spend**: `budget.total` is null; watch manually, be ready to `printf paused`.
- **draft flakes**: gap#1 makes `smoke_failed` retry (budget 3); a leaf that still exhausts
  after 3 + self-heal is a genuine spec/oracle mismatch → fix-brief it (clean sidecars
  `state/output/<tid>.*`, `state/tasks/processed|blocked/<tid>*`, `state/tasks/<tid>.json.processing`).
- The leaf `meta_task_type` is planner-assigned; gap#2b makes `io_adapter`/etc. resolve
  `ngv2.*` external imports in the diff-fuzzer subprocess (empirically confirmed), and BUG#2
  makes smoke-gated types resolve them too — so ANY meta-type builds.

### LESSONS from this session (read before dispatching)
1. **Self-fixes that read os state / take `extra` dicts MUST go through the WORKER path**
   (`orchestrator_worker --task-id`), NOT `impl_dispatch_once.sh`. The full `orchestrator.py`
   ALWAYS runs dual-agent differential fuzzing (Phase 6 decomposition at orchestrator.py:3739);
   an `os.environ`-reading or env-dependent function makes the two agent drafts diverge →
   endless `-general`/`-boundary`/`-reviewed` decomposition cascade. `harness_self_fix` (and
   `sandbox_infra`, `planner_tooling`, etc. = `bypass_fuzzer`) on the worker path goes
   single-agent → smoke/none → `_auto_commit_accepted` (the committed oracle is the gate).
2. **Driving a worker self-fix:** hand-author RED oracle → commit → write `plan_<slug>.json`
   (1 task, `meta_task_type=harness_self_fix` for deny-listed) → `stage_task(Path(plan),tid,
   Path('state'))` → `printf run > state/control/orchestrator.flag` → `timeout 600
   <miniconda-python> -m harness.orchestrator_worker --task-id <tid> --state-dir state`.
   Deny-listed also needs `state/control/decisions/<tid>.json`
   `{"task_id":..,"decision":"approve","approved_by":"operator","reason":"..","scope":"harness/autowork_daemon.py"}`.
3. **STALE/MALFORMED `.py` sidecar gremlin:** a pure-DELETION self-fix
   (`fix-finalize-preserve-slug`, abandoned) rejected twice with `auto_commit_failed` even
   though the candidate `.patches.json` was correct — its `.py` sidecar held a patch-repr
   (`{'file':...}`, "invalid syntax line 1") that took precedence at git_integration and the
   verify ran old code. If a self-fix rejects with `auto_commit_failed` but the candidate looks
   right, suspect this; the abandoned fix was unnecessary (we embraced slug canonicalization
   instead — see `tests/planner/test_epic_pipeline_dedup_childepics.py`).
4. `make`/bare `python` resolves to a non-executable in this env (`make: python: Permission
   denied`); always invoke `/home/xnihil0zer0/miniconda3/bin/python` explicitly. Full serial
   sweep = `/home/xnihil0zer0/miniconda3/bin/python -m pytest -p no:cacheprovider -q` (~920s).
5. **Kill daemon/workers by EXPLICIT PID** (`kill -TERM $(cat /tmp/ngv2e3_daemon.pid)`), NEVER
   `pkill -f` (self-kills the issuing shell block, exit 144). A `pgrep -f harness.autowork_daemon`
   from inside a bash script matches the script's OWN cmdline — false positive; filter `grep -v
   bash` / check `ps -eo pid,args`.
6. **Decomposition is now interface-faithful + deterministic** (the two fixes): root → 4
   `epic:true` sub-epics (deduped kebab slugs); each sub-epic → 3 `epic:false` leaves (deduped).
   The decomposer canonicalizes child slugs `_`→`-` (kebab) to dedupe the two agents' naming
   variants — that's the intended posture (tests aligned in `6d3624d`).

---

## §6 CLOSE-OUT (when all 12 leaves land)

1. NGv2 full suite green: `/home/xnihil0zer0/NobleGreedv2/.venv/bin/python -m pytest -q`
   (= 40 prior + 12 new = 52 oracles pass). NGv2 `master` has 12 new `Integrate validated code`
   commits; tree clean.
2. JM full serial sweep 0-regression vs baseline (`/home/xnihil0zer0/miniconda3/bin/python -m
   pytest -p no:cacheprovider -q`).
3. Kill daemon by PID; gate `paused`; allowlist back to deny-all (remove `ngv2_epic3`);
   `parallel_cap` back to `5` in `harness/config.yaml`; verify ngv2 NOT in JM venv.
4. Commit Epic-3 run artifacts (briefs/plans/oracles/decision files) + the daemon fix.
   **Push JM with sign-off** (HEAD is 9+ commits ahead of origin — owner approval to push).
5. Update memory: new `ngv2-epic3-run-result` — record (a) PART A fixes, (b) the TWO decomposer
   fixes that made live multi-level decomposition work, (c) the daemon epic-kickoff
   hallucination fix (this handoff), (d) the slug-collision lesson, (e) whether the fully-live
   multi-level run completed hands-off + the agy-concurrency behavior under a long run + the
   multi-level admission proof. Link `[[ngv2-epic2-run-result]]`, `[[ngv2-cleanroom-rebuild-plan]]`.

---

## §7 STILL-OPEN / NOT addressed here
- BUG #3: daemon has no brief-level dep gating (only task-level `dependencies`). Epic-3 leaves
  are dep-free by design, so not needed.
- The diff-fuzzer ro-bind if it ever becomes jailed (currently unjailed; gap#2b handles it).
- The deeper JM-vs-runtime line (worker registry / GPU scheduling / phase-ROI loop) is
  intentionally NOT in Epic-3 — NGv2 will harvest JM's daemon later.
