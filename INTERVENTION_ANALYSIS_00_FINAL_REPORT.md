# JanusMask Factory - Intervention Analysis and Corrected Automation Plan

**Date:** 2026-06-15
**Purpose:** Convert the four intervention-analysis lanes into a buildable
automation plan that reduces external-supervisor intervention while preserving
compatibility with `/home/xnihil0zer0/NobleGreedv2`.

**Inputs:**

- `INTERVENTION_ANALYSIS_01_transcripts.md`
- `INTERVENTION_ANALYSIS_02_git_selfheal.md`
- `INTERVENTION_ANALYSIS_03_archive_forensics.md`
- `INTERVENTION_ANALYSIS_04_seam_map.md`

**Operating constraint:** the report must not merely identify flaws. Where a
lane exposes a blocker, the recommendation must explain the permanent harness
change that would make the original automation goal work.

---

## 1. Executive Conclusion

The original reports had the right intent: identify where the external Claude
Code supervisor repeatedly steps into the automatic factory, then fold the
repeatable parts back into JanusMask. That intent is valid and urgent.

The corrected reading is:

1. **The factory has high intervention pressure.** Lane 1 classifies 10,088 of
   24,998 external-supervisor tool calls as intervention-shaped (40.4%). Lane 2
   classifies 301 of 1,206 commits as likely manual intervention (25.0%), with
   the caveat that commit-message classification is heuristic.
2. **Intervention pressure is not declining.** Lane 1 rises from 23.3% in May to
   52.7% in June. Lane 2 shows the initial build near 0-2%, then persistent high
   oscillation once harder harness/NGv2 work begins.
3. **Most intervention is operational and repeatable.** The supervisor is often
   acting as a missing daemon control plane: re-dispatching tasks, clearing stale
   state, driving stages, running tests, scoping allowlists, pausing workers, and
   pushing clean integrations.
4. **The riskiest intervention is direct production editing.** Lane 1 counts
   1,259 direct production edits to `harness/**`, `ngv2/**`, `config/**`, and
   related files. These bypass the intended pipeline guarantees: oracle,
   validation, isolated apply, gate, commit provenance, archival, and rollback.
5. **NGv2 is not a runtime import dependency, but it is a build-output target.**
   Lane 4 verifies no live JanusMask runtime import of `ngv2.*`; NGv2 is edited
   and built as an external target. Therefore the compatibility risk is not
   runtime import coupling. The risk is emitting or committing NGv2-breaking code
   through planner, staging, self-heal, external-root, or verification paths.

**Corrected strategy:** do not start by declaring a universal "edit anything"
path solved. Build the deterministic pieces first, then expose them through one
operator-facing command. The intended end state is still a sanctioned pipeline
edit/drive path for any file, including harness and NGv2 files, but it must be
assembled from tested control-plane, planner, apply, verification, and NGv2-gate
components.

---

## 2. Evidence Model

The lanes are useful because they observe the same failure from different angles,
but they do not all measure the same thing.

| Lane | Strong Signal | Limit |
|---|---|---|
| 1 transcripts | Volume and type of supervisor actions | Tool calls are not task counts |
| 2 git/self-heal | Durable landed/rejected residue | Manual-vs-auto commit classification is heuristic |
| 3 archives | Root causes and manual recipes | Keyword corpus counts are noisy; decision files are cleaner |
| 4 seam map | Where to implement fixes | A seam is not proof a flag is ready to enable |

Use cross-lane agreement as the decision rule. A fix is high-confidence when:

- it appears in transcript volume,
- it appears in git/self-heal or decision artifacts,
- and Lane 4 identifies an existing harness seam.

---

## 3. What The Supervisor Is Actually Doing

Lane 1's top intervention buckets are the best guide to what should become
daemon behavior.

| Intervention Class | Count | Correct Automation Target |
|---|---:|---|
| Ad-hoc inline state surgery | 2,150 | First-class daemon reset/requeue/repair verbs |
| Manual pipeline driving | 1,518 | `drive-task` / `drive-stage` command |
| Manual test runs and polling | 1,312 | Daemon-owned gate execution and status |
| Direct production edits | 1,259 | Manifest-backed pipeline edit path plus guard |
| Plan/brief shepherding | 686 | Lifecycle archival and spent-artifact reaping |
| Other filesystem operations | 582 | Controlled cleanup commands |
| Oracle test authoring | 449 | Keep human RED-oracle option; automate injection/enforcement |
| Git recovery | 396 | Undo/revert-last-integration command |
| Allowlist/config edits | 370 | Scope/snapshot allowlist command and guarded config flips |
| Daemon control | 364 | Unified pause/resume/run/stop semantics |
| State sidecar cleanup | 352 | Re-dispatch cleanup policy |
| Git push | 153 | Guarded auto-push after clean green integrate |

The intended automation is not "remove humans." It is to move humans from
state-surgery and raw production edits into policy decisions, oracle design, and
explicit approvals.

---

## 4. Root Causes That Must Be Fixed Permanently

Lane 3's decision-file column is the cleanest root-cause signal. The all-corpus
column is useful for context but should not be treated as a direct intervention
count.

| Root Cause | Decision Files | Permanent Fix |
|---|---:|---|
| Jail/sandbox/fail-closed stand-up | 57 | Preserve as substrate; do not regress jail gates |
| External-root target resolution | 18 | Thread `working_dir` through planner, staging, worker, smoke, and commit |
| AST/class-method/R-anchor edit fragility | 9 | Add deterministic block/whole-file manifest apply path |
| Dep-gate leak/wedge | 5 | Default-on dependency stripping plus bounded deadlock breaker |
| Non-Python/multi-file apply routing | 4 | Manifest apply supports non-Python and multi-file envelopes |
| External-build smoke/retry | 3 | External-root smoke gates resolve imports against target repo |
| Implementation not wired | 3 | Acceptance wire-up gate for JanusMask roots; preserve NGv2 rootless no-op |
| Planner ignores verification command | 3 | Normalize weak commands to paired pytest gates |
| Blind-worker clobber | 3 | Plan-time clobber-bomb rejection and fail-closed apply |
| Stale sidecar precedence | 2 | Purge stale sidecars/session/task state on re-dispatch |

Some fixes are already partly present in the current tree. For example,
`harness/planner/plan_normalizer.py` already includes
`_strip_stray_mutation_targets()` and `_inject_oracle_sources()`. Treat those as
the pattern: recurring planner failures should become pure, idempotent
normalizer passes with tests.

---

## 5. Corrected Architecture

The original final report's "Universal Edit Path" is directionally right but too
large as a first implementation step. The corrected architecture is:

```
operator intent / exact patch
        |
        v
daemon command: edit-task / drive-stage / reset-task
        |
        v
planner normalization and validation
        |
        v
isolated apply slot with manifest-backed changes
        |
        v
verification gate: JanusMask tests and, when needed, NGv2 contract tests
        |
        v
accept commit + archive + optional push
        |
        v
rollback / undo metadata retained
```

This accomplishes the original intent without pretending all parts already
exist. The universal command should be the last wrapper over proven pieces, not
the first place those pieces are invented.

---

## 6. Implementation Plan

### Phase 0 - Stabilize Control Plane

These changes reduce risk immediately and make later automation safe.

| ID | Change | Evidence | Seam |
|---|---|---:|---|
| P0.1 | Unify pause/resume into one authoritative primitive | Lane 3 pause hazards; Lane 4 notes two pause channels | `autowork_daemon._decide`, `control_gate.check_pause` |
| P0.2 | Add `daemon reset-task <id>` | Lane 1 state surgery + sidecar cleanup; Lane 3 R1 pre-clean | `stage_task`, daemon command layer |
| P0.3 | Auto-clear stale commit locks only when owner PID is dead and idle threshold is met | Lane 2 `daemon_inactivity_stuck` x30 | inactivity watchdog |
| P0.4 | Make daemon own test-gate execution and status polling | Lane 1 manual test run x1,312 | worker/orchestrator gate status |
| P0.5 | Add direct-production-edit guard in report-only mode first | Lane 1 production edits x1,259 | interceptor or git hook |

**Acceptance tests:**

- pausing through the chosen primitive prevents new dispatch while preserving
  running-worker accounting;
- reset-task removes stale `state/output/<id>.*`, stale sessions, task markers,
  and retry poison without deleting unrelated task state;
- stale lock cleanup refuses to remove a live owner's lock;
- daemon gate status records the command, PID, exit code, log path, and duration.

### Phase 1 - Fix Planner Shape and Verification

Planner failures should be corrected before staging, not after a human sees a
blocked task.

| ID | Change | Evidence | Seam |
|---|---|---:|---|
| P1.1 | Keep/finish oracle-source injection into implementation notes | Lane 3 oracle-first x209; R1 recipe | `normalize_plan`, `stage_task` |
| P1.2 | Upgrade weak `python -c import` verification to paired pytest when oracle can be resolved | Lane 3 vcmd blockers | `normalize_plan` |
| P1.3 | Keep/finish stripping stray `mutation_target` from non-test-authoring tasks | Lane 3 live blocker; current tree has pass | `normalize_plan` |
| P1.4 | Strip unresolvable deps and add bounded deadlock breaker | Lane 2 retry caps; Lane 3 dep-gate | `normalize_plan`, `_retry_blocked_tasks` |
| P1.5 | Reject clobber-bombs at plan validation | Lane 1 clobber neutralize; Lane 3 clobber blockers | `plan_validator` |
| P1.6 | Make multi-file/new-module shape deterministic | Lane 3 non-Python/multi-file/new-module blockers | `normalize_plan` |

**Acceptance tests:**

- normalizer is pure and idempotent;
- whole planner suite passes;
- weak vcmd becomes a real pytest command only when a paired oracle is found;
- test-authoring mutation targets are preserved;
- non-test-authoring mutation targets are removed;
- unresolvable dependencies are stripped only when they cannot refer to admitted
  plan tasks;
- clobber-bomb signature is rejected before dispatch.

### Phase 2 - Close Lifecycle Loops

These remove recurrent supervisor housekeeping.

| ID | Change | Evidence | Seam |
|---|---|---:|---|
| P2.1 | Archive spent brief, plan, handoff, and scratch artifacts on integrate | Lane 1 shepherding x686; Lane 2 declutter x56 | `_reap_spent_briefs_safe`, integrate hook |
| P2.2 | Add `daemon drive-stage <task> <stage>` | Lane 1 manual driving x1,518; Lane 3 R1/R2 | daemon over `stage_task` and worker spawn |
| P2.3 | Add `scope-allowlist <epic>` with snapshot/restore | Lane 2 90 admitted slugs and `.bak.epic_*` | allowlist gate |
| P2.4 | Add guarded auto-push after clean green integrate | Lane 1 git push x153 | accept-commit hook |
| P2.5 | Add `undo-last-integrate` | Lane 1/2 git recovery/revert evidence | git integration |

**Acceptance tests:**

- archive is a rename/move with provenance, not deletion;
- drive-stage produces the same staged task shape as the manual recipe;
- allowlist scoping writes a diffable snapshot and restore file;
- auto-push requires enabled config, clean tree, expected branch, passing gates,
  and known remote;
- undo-last-integrate refuses if HEAD moved unexpectedly.

### Phase 3 - Deterministic Apply Primitive

This is the core fix for direct hand-edits and fragile AST edits.

Implement a manifest-backed apply mode:

- A manifest contains ordered file operations.
- Each operation is either:
  - exact old-block to new-block replacement, or
  - whole-file creation/replacement with explicit mode.
- Exact old-block replacement must match exactly once.
- Zero matches fail closed.
- Multiple matches fail closed.
- Paths are resolved before apply.
- External paths carry explicit `working_dir`.
- The apply result records changed files, hashes before/after, verification
  command, gate result, commit, and rollback metadata.

This directly fixes:

- AST partial-edit truncation;
- class-method patch fragility;
- new-symbol/new-module patch limitations;
- non-Python and multi-file routing;
- duplicate/missing block ambiguity;
- silent clobber risk.

**Acceptance tests:**

- Python block replacement;
- non-Python block replacement;
- new file;
- whole-file replacement;
- multi-file manifest;
- duplicate old-block rejection;
- missing old-block rejection;
- external-root path resolution;
- no commit on failed apply;
- rollback metadata written on success.

### Phase 4 - Sanctioned Pipeline Edit Command

Only after Phases 0-3 pass should the factory expose the operator-facing command
that accomplishes the original "Universal Edit Path" intent.

Recommended command surface:

```
daemon edit --file <path> --intent <text> --oracle <pytest-or-smoke>
daemon edit --file <path> --manifest <manifest.json>
daemon drive-stage --task <id> --stage <stage>
daemon reset-task <id>
```

Rules:

- `daemon edit` always routes through manifest apply, gate, commit, archive, and
  rollback metadata.
- For `harness/**` and `config/**`, require JanusMask regression gates.
- For `/home/xnihil0zer0/NobleGreedv2/**`, require NGv2 contract gates.
- For exact-manifest mode, no blind worker is needed.
- For intent mode, the worker may synthesize the manifest, but the same
  fail-closed apply and verification rules apply.

This makes direct production editing unnecessary without pretending humans will
never provide exact changes.

### Phase 5 - NGv2 Boundary Automation

NGv2 compatibility is preserved by contract tests, not by optimism.

| ID | Change | Guard |
|---|---|---|
| N5.1 | Thread `working_dir` end-to-end | External-root plan, stage, worker, smoke, commit tests |
| N5.2 | External smoke gate resolves imports against NGv2 root | `python -m ngv2.workers.<phase>` smoke |
| N5.3 | Preserve `_ISOLATED_EXTERNAL_DIRS` serialization | Parallelism tests |
| N5.4 | Preserve wire-up rootless no-op for external roots | `wire_up.check_wired` tests |
| N5.5 | Gate NGv2 self-heal promotion on NGv2 suite | NGv2 contracts and worker oracles |

Required NGv2 contract checklist:

- `ngv2/workers/<phase>.py::run_stage(context, seams)`
- `ngv2/workers/_runner.py` argv and seam keys
- `ngv2/stage_command_map.py::command_for_phase`
- `ngv2/run_hunt.py`
- `ngv2/conductor_seams.py::build_default_seams`
- `ngv2/session_db.py` and `ngv2/session_api.py`
- `ngv2/contracts.py`
- `ngv2/poc_writer.py::write_poc`
- `ngv2/poc_repair_loop.py::repair_poc`

### Phase 6 - Self-Heal Promotion

Do not simply flip `autowork.selfheal_auto_promote` on globally. Enable it by
failure class.

Eligible first:

- stale sidecar / retry poison;
- known AST/apply failure remediated by manifest mode;
- weak vcmd normalized to paired pytest;
- deadlock breaker with bounded one-time retry.

Not eligible until NGv2 gates exist:

- any heal touching `ngv2/workers/**`;
- any heal touching `ngv2/session_db.py`, `ngv2/session_api.py`, or conductor
  seams;
- any heal changing command-line entrypoints.

**Acceptance tests:**

- provenance HMAC required;
- one retry budget per failure class;
- no auto-promotion without passing configured gates;
- NGv2-touching heals run NGv2 contract gates;
- skipped tasks can be retried once after a root-fix touches their failing
  subsystem.

---

## 7. Fixed Interpretation of Key Original Recommendations

The original report's intent should be preserved but tightened as follows.

| Original Direction | Corrected Implementation |
|---|---|
| "Universal Edit Path" | Build manifest apply + daemon edit after control, planner, and gate pieces are proven |
| "Turn on half-built flags" | Review each flag with readiness tests; enable only behind gates |
| "Oracle authoring is manual load" | Keep human RED-oracle design allowed; automate oracle injection and non-bypass |
| "Tiers 1/2/4 are NGv2-safe" | Treat them as low runtime-import risk, not zero build-output risk |
| "Auto-push after green integrate" | Make it guarded and config-enabled, never unconditional |
| "Pre-commit guard blocks raw edits" | Start report-only, then route to `daemon edit`; allow explicit break-glass |
| "Self-heal auto-promote" | Enable per deterministic failure class, with NGv2 gates for NGv2 files |

---

## 8. Success Metrics For The Next Run

The next intervention analysis should measure whether the specific rituals
disappear.

| Ritual | Success Signal |
|---|---|
| Manual state cleanup | `reset-task` events replace raw `rm/mv state/...` |
| Manual pipeline driving | `drive-stage` events replace inline `python - <<PY` staging |
| Manual pytest polling | daemon gate-status events replace shell polling |
| Direct production edits | manifest-backed pipeline edits replace raw file edits |
| Allowlist hand-edits | scope/snapshot command records replace direct edits |
| Stale daemon re-kicks | no repeated `daemon_inactivity_stuck` bursts |
| External-root approvals | decline after `working_dir` tests and NGv2 gates land |
| Git push | guarded auto-push records replace manual push commands |

The goal is not to make every count zero. The goal is to make the remaining human
actions explicit approvals, oracle design, and policy choices rather than hidden
state surgery.

---

## 9. Build Order

1. Implement Phase 0 control-plane stabilization.
2. Finish and test Phase 1 planner normalization.
3. Implement Phase 2 lifecycle commands.
4. Implement Phase 3 deterministic manifest apply.
5. Expose Phase 4 `daemon edit` / `drive-stage` / `reset-task` commands.
6. Land Phase 5 NGv2 external-root contract gates.
7. Enable Phase 6 self-heal promotion by failure class.
8. Re-run `scripts/intervention_analysis/*` and compare the ritual metrics in
   Section 8 against the current baseline.

This sequence accomplishes the original reports' intent: it turns repeated
manual interventions into permanent, reusable harness capabilities while keeping
NGv2 compatibility as a first-class acceptance condition.

---

## 10. Reproducibility

The source counts come from:

```
python3 scripts/intervention_analysis/lane1_parse_transcripts.py
python3 scripts/intervention_analysis/lane2_git_selfheal.py
python3 scripts/intervention_analysis/lane3_archive_forensics.py
PYTHONPATH=. python3 scripts/intervention_analysis/lane4_seam_map.py --out scripts/intervention_analysis/lane4_seam_map.json
```

When this plan is implemented, add a fifth script that reports ritual-level
replacement metrics: raw cleanup commands vs `reset-task`, raw stage-driving vs
`drive-stage`, raw production edits vs manifest edits, and manual pushes vs
guarded auto-push events.
