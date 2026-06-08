# NobleGreedv2 Rebuild — Epic #1 RUN handoff (paste §0)

Compiled 2026-06-06. Phase 0 (de-risk) DONE+PROVEN; gaps #2/#3 FIXED via pipeline
and PUSHED; Epic-1 children designed. **Owner decision: run Epic-1 FULLY HANDS-OFF
via the daemon's epic AUTO-DECOMPOSE path** (real epic brief → planner generates
child plans → daemon dep-gated dispatch). So the work order is: **(1) fix gap #4
via pipeline → (2) the 2 caveats → (3) author the epic brief → (4) run hands-off →
(5) close out.** A PROVEN fallback (hand-authored-plan daemon path, no gap #4
needed) is in §8 if the auto-decompose path stalls.

---

## §0 PROMPT (paste this)

Resume the NobleGreedv2 clean-room rebuild (JanusMaskJR builds it — "JM as factory").
**Read FIRST (in order):** memory `ngv2-cleanroom-rebuild-plan.md`,
`ngv2-phase0-external-build-proven.md`, `never-hand-edit-production-outside-pipeline.md`,
then this file `NGV2_EPIC1_RUN_HANDOFF.md` and `NGV2_EPIC1_BRIEF.md`. JM repo
`/home/xnihil0zer0/JanusMaskJR` (HEAD pushed); external target
`/home/xnihil0zer0/NobleGreedv2` (own git+venv, JM-owned via marker).

Run Epic-1 fully hands-off via the daemon's epic auto-decompose path, in this order:
**(1) FIX GAP #4 via the pipeline** — `normalize_plan` self-roots its vcmd glob at
JM's cwd, so planner-generated external child plans get their `verification_command`
mis-mapped to a JM-rooted smoke import. Fix `harness/planner/plan_normalizer.py`
(NOT deny-listed → auto-commits) to root vcmd resolution at the plan's external
`working_dir`; hand-author the RED oracle; keep JM sweep green (baseline 7002
passed). **(2) THE 2 CAVEATS:** (a) external oracles must be COMMITTED into NGv2
before dispatch (the EXTERNAL_DIRTY_GATE refuses a dirty tree) — decide oracle
ownership (commit hand-authored, OR let the daemon author them via test_authoring
children — see §4 risk); (b) gap #3 (worker reads external source) is AUTO-handled
on the daemon path. **(3) AUTHOR the epic brief** `brief_hooks_ngv2_epic1.md`
(`plan_kind:'epic'`, top-level external `working_dir`, precise `child_briefs` whose
specs MATCH the committed oracles). **(4) RUN hands-off:** allowlist the epic slug,
set gate `run`, start the daemon by EXPLICIT PID; monitor `impl_progress.jsonl`,
NGv2 git (master advances per child via gap #2; output also on janusmask/work), and
TOKEN/WALL spend. Fix-brief any failure before continuing. **(5) CLOSE OUT:** JM
sweep green, gate `paused`, push JM changes w/ owner sign-off; NGv2 pushes separately.

HEAD at handoff: JM `b042a9b` (PUSHED to origin/master), gate paused, no daemon.
NGv2 master `aac9970`, janusmask/work `cccae37`, 3 epic oracles untracked.

---

## §1 EXACT STATE

**JM** `/home/xnihil0zer0/JanusMaskJR`, master, HEAD `b042a9b`, **PUSHED** (origin/master
up to date). Commits since `92bafb5`: `332a7a2`+`a73f294` (gap #3), `8cd037a`+`b042a9b`
(gap #2). Gate `paused`. No daemon. Sweep CONFIRMED GREEN after both fixes =
**7002 passed, 8 skipped, 5 xfailed, 0 failed** (baseline; 0 regressions).

**NGv2** `/home/xnihil0zer0/NobleGreedv2` (JM-owned, marker present, py3.13+pytest9 venv):
master `aac9970` (BEHIND janusmask/work by the smoke commit — ff master to
janusmask/work first), janusmask/work `cccae37` (+`ngv2/_smoke.py`). UNTRACKED:
`tests/test_contracts.py`, `tests/test_state_machine.py`, `tests/test_detonation.py`.

**Authored (JM root, untracked):** `NGV2_EPIC1_BRIEF.md` (design), `plan_ngv2_epic1.json`
(the precise 3-task flat plan — REUSE its task specs verbatim as the epic brief's
child_briefs, and as the §8 fallback), and the already-executed plans
(`plan_ngv2_smoke.json`, `plan_fix_*.json`). `state/control/autowork/external_roots.allow`
= NGv2.

---

## §2 THE 4 GAPS (status)

1. **EXTERNAL_DIRTY_GATE** (orchestrator.py:2661) — external tree must be CLEAN;
   commit oracles first. (Caveat 2a.) By design.
2. **Accumulation** — FIXED `b042a9b`: `merge_staging_to_parent` ff-advances the
   checked-out branch on a JM-owned external accept (marker-gated). master accumulates.
3. **Jail-retarget env** — FIXED `a73f294`: daemon `_spawn_worker` sets
   `JANUSMASK_WORKING_DIR`. AUTO-handled on the daemon path (caveat 2b satisfied).
4. **vcmd normalize self-roots** — OPEN; **fix it FIRST (§3)** for the auto-decompose path.

---

## §3 STEP 1 — FIX GAP #4 via the pipeline (do first)

**Root cause:** `harness/planner/plan_normalizer.py::_sanitize_impl_verification_commands`
(:179) rewrites an impl task's `verification_command` to its sibling test_authoring
oracle by globbing `Path(repo_root).glob('tests/**/test_<leaf>.py')` (:257), and
`normalize_plan` (:279) is called from `harness/planner/cli.py:296` with
`repo_root=Path.cwd()` (JM). For an EXTERNAL child plan this globs JM's tests (miss)
→ falls back to a JM-rooted smoke import, so NGv2's real oracle never runs as the
gate. NOTE: the rewrite ONLY triggers when the plan contains test_authoring tasks
(oracle_files non-empty, :225) — i.e. the planner-generated impl+oracle child plans,
NOT a hand plan with explicit vcmds and no test_authoring task.

**Fix (recommended):** in `normalize_plan`, if `plan.get('working_dir')` is a
non-empty str that is NOT `_target_is_self`, pass that working_dir as the effective
glob root to `_sanitize_impl_verification_commands` (instead of JM's cwd) so impl
vcmds map to NGv2's own `tests/**`. `plan_normalizer.py` is NOT on
`_NEVER_AUTO_APPROVE` → the pipeline AUTO-COMMITS (no decision file). Hand-author a
RED oracle: a plan dict with external `working_dir`, a `test_authoring` task whose
`files_touched` is `tests/test_x.py`, and an impl task touching `pkg/x.py` whose
vcmd names that oracle → after `normalize_plan`, the impl vcmd is
`python -m pytest tests/test_x.py -q` resolved against the external root (create the
matching `tests/test_x.py` under a tmp external dir), NOT a smoke import. Add a
self/no-working_dir control asserting byte-identical legacy behavior.

**VERIFY (critical for this path):** does the epic flow PROPAGATE the top-level
`working_dir` into each generated CHILD plan (so normalize sees it at child-plan
time)? Trace the epic→child-brief→child-plan generation (harness/planner/cli.py epic
branch + harness/planner/* ); if child plans/briefs don't carry working_dir, the gap
#4 fix won't fire per-child — then ALSO propagate working_dir into child briefs/plans
(another small non-deny-listed pipeline fix), or fall back to §8.

---

## §4 STEP 2 — THE 2 CAVEATS + ORACLE OWNERSHIP DECISION

- **2a (committed oracles):** before the daemon dispatches, NGv2's tree must be clean.
  ff NGv2 master→janusmask/work, then EITHER:
  - **(i) commit the 3 hand-authored oracles** (`tests/test_contracts.py`,
    `tests/test_state_machine.py`, `tests/test_detonation.py`) into NGv2 master — then
    the epic's child_briefs must be IMPL-only (no test_authoring children) and their
    specs must MATCH the committed oracles (RISK: planner blind-draft may diverge from
    the oracle interface → verify fails; mitigate with very precise child_briefs). OR
  - **(ii) let the daemon AUTHOR oracles** via test_authoring children (gap #4 fix
    makes their vcmds resolve). RISK: external test_authoring is UNPROVEN — FIX #1
    (`_stage_targets` mounting the module-under-test) is self-rooted at JM's repo_root
    and may not stage an EXTERNAL module-under-test; verify or fall back to (i).
  Recommend (i) for reliability on the FIRST epic.
- **2b (gap #3 env):** AUTO-handled — the daemon's `_spawn_worker` sets
  `JANUSMASK_WORKING_DIR`, so L1 children's agents read `ngv2/contracts.py` from the
  retargeted jail. Nothing to do.

---

## §5 STEP 3 — AUTHOR the epic brief

Write `brief_hooks_ngv2_epic1.md` with `plan_kind:'epic'`, a top-level external
`working_dir: /home/xnihil0zer0/NobleGreedv2`, and explicit `child_briefs` (slug/
title/scope/spec/`# Required plan shape`/dependencies) — REUSE the three task specs
in `plan_ngv2_epic1.json` VERBATIM as the child_briefs (they precisely pin field
names/methods/dict-keys/validation so blind-draft matches the oracles): children
`ngv2-artifact-contract` (L0), `ngv2-state-machine` (L1), `ngv2-detonation-chamber`
(L1, both dep on contract). Ensure `harness/config.yaml` `hierarchical_planning`
is enabled for epic decomposition (it is ACTIVE per memory — confirm). Each child:
NEW module → SINGLE-FILE WHOLE-FILE; exact target path; explicit external vcmd
(`python -m pytest tests/test_<x>.py -q`). Keep the DAG ONE level deep.

VET before running: plan the epic once OFFLINE (never while the daemon runs) and
inspect the generated child plans — confirm each carries `working_dir`, a correct
NGv2-rooted vcmd (gap #4 fix worked), and an interface matching its committed oracle.

---

## §6 STEP 4 — RUN hands-off via the daemon

1. `printf '%s\n' ngv2_epic1 >> state/control/autowork/auto_promote.allowlist`
   (the daemon transitively admits children of an allowlisted epic slug).
2. `printf run > state/control/orchestrator.flag`.
3. Start the daemon by EXPLICIT PID; never `pkill` (self-kill → exit 144):
   `nohup python3 -m harness.autowork_daemon --state-dir state > /tmp/ngv2_daemon.log 2>&1 & echo $!`
4. The daemon: bootstrap NGv2 (idempotent) → decompose epic → plan + dep-gate stage
   L0 → build → accept → **gap #2 advances NGv2 master** → dep-gate releases L1 ×2 →
   build (gap #3 lets agents read contracts) → accept.
5. MONITOR: `grep -E 'auto_commit|reject_rollback|blocked' state/impl_progress.jsonl`
   (the `auto_commit` row is GROUND TRUTH — worker stdout shows a spurious
   `{"skipped":"not_found"}`); `git -C /home/xnihil0zer0/NobleGreedv2 log --oneline master`
   (each child lands + master advances); and TOKEN/WALL spend (the depth budget is
   NOT cost-aware — a wide epic burns unbounded; watch manually).
6. On ANY child failure: read the worker stderr (`worker_exit` ledger row
   `stderr_tail` + `/tmp/ngv2_daemon.log`); PAUSE the gate; clean stale sidecars
   (`rm -f state/output/<tid>.* state/tasks/processed/<tid>.json state/tasks/blocked/<tid>* state/tasks/<tid>.json.processing`);
   author a corrective brief (NGv2 child fix, or JM harness_self_fix + decision +
   RED oracle); re-run BEFORE continuing.
7. STOP the daemon by EXPLICIT PID when the 3 children are accepted.

---

## §7 STEP 5 — CLOSE OUT

JM serial sweep green (baseline 7002 passed; 0 new regressions for the gap #4 fix —
re-run `python -m pytest -q -p no:cacheprovider`). Empty the allowlist; gate
`paused`; kill the daemon by PID. Push JM-side changes (gap #4 fix + its oracle) with
owner sign-off. NGv2 commits live in NGv2's own git (master + janusmask/work) — push
NGv2 separately. Update memory `ngv2-phase0-external-build-proven` with the epic result.

---

## §8 PROVEN FALLBACK — hand-authored-plan daemon path (no gap #4 needed)

If the epic auto-decompose path hits a wall (working_dir not propagated to child
plans, external test_authoring fails, or blind-draft interfaces don't match the
oracles), use this VERIFIED-VIABLE path — the daemon REUSES an existing
`plan_hooks_<slug>.json` WITHOUT re-planning or re-normalizing (so gap #4 never
fires), and dep-gates a FLAT multi-task `implementation` plan via each task's
`dependencies`:
1. ff NGv2 master→janusmask/work; COMMIT the 3 oracles into NGv2 master.
2. `cp plan_ngv2_epic1.json plan_hooks_ngv2_epic1.json`; create a stub
   `brief_hooks_ngv2_epic1.md` (any content — needed only so `compute_brief_status`
   DISCOVERS the slug as state `has_plan`; the existing plan is NOT re-planned).
3. Allowlist `ngv2_epic1`; gate `run`; start daemon by PID.
4. Daemon stages dep-gated (L0 then L1×2 once L0 accepted), dispatches via
   `_spawn_worker` (gap #3 env), gap #2 advances master. Precise hand-authored
   interfaces match the committed oracles. Monitor + close out as §6/§7.
This path needs NO gap #4 fix and NO blind-draft — it's the lowest-risk way to get a
hands-off daemon run of Epic-1 if the auto-decompose route is troublesome.

---

## §9 GOTCHAS

- Ledger `auto_commit` = ground truth (ignore spurious `{"skipped":"not_found"}` stdout).
- External oracles MUST be committed (dirty gate). Manual dispatch (not daemon) must
  `export JANUSMASK_WORKING_DIR=<NGv2>` (gap #3 only auto-fires on the daemon path).
- Stale-sidecar precedence: clean `state/output/<tid>.*` + `processed/<tid>.json`
  before re-dispatch. Kill daemon/workers by EXPLICIT PID (pkill self-kills → 144).
- Never run `planner.cli` concurrently with the daemon; never run a big pytest sweep
  concurrently with a dispatch.
- Deny-listed (need decision file + RED oracle): orchestrator.py, autowork_daemon.py,
  git_integration.py, planner/staging.py, agent_jail.py, paths.py, dbus_proxy.py,
  interceptors.py, selfheal.py, services/**. NOT deny-listed (auto-commit):
  planner/plan_normalizer.py, planner/cli.py, orchestrator_worker.py, tests/**.
- Single-symbol partial-edit patches up to ~130 lines land clean; larger → split/whole-file.
