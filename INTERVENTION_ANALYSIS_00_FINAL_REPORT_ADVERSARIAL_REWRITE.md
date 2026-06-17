# JanusMask Intervention Analysis - Adversarial Final Report

**Date:** 2026-06-15
**Scope:** Adversarial review and replacement synthesis for:

- `INTERVENTION_ANALYSIS_00_FINAL_REPORT.md`
- `INTERVENTION_ANALYSIS_01_transcripts.md`
- `INTERVENTION_ANALYSIS_02_git_selfheal.md`
- `INTERVENTION_ANALYSIS_03_archive_forensics.md`
- `INTERVENTION_ANALYSIS_04_seam_map.md`

**Question:** How much manual external-supervisor intervention is present in the
JanusMask factory, what actually causes it, and which interventions are safe and
deterministic enough to absorb into the factory without breaking
`/home/xnihil0zer0/NobleGreedv2`?

**Adversarial posture:** Treat counts as evidence with different strengths, not
as equal ground truth. Separate measured behavior from interpretation and separate
engineering recommendations from proven facts.

---

## 1. Executive Judgment

The evidence supports the central conclusion: the factory is not yet autonomous
in the operational sense. A large share of external-supervisor activity is
manual intervention, and the interventions cluster around repeatable failure
modes: state cleanup, manual task driving, weak verification, direct production
edits, external-root handling, and lifecycle hygiene.

The evidence does **not** support the strongest version of the original final
report: that the factory's intervention burden can be summarized as "one in
three of everything," that all proposed Universal Edit Path behavior is already
justified by the data, or that broad classes of automation are categorically
NGv2-safe "by construction." Those are useful hypotheses, but they are stronger
than the evidence.

The right conclusion is narrower and more actionable:

1. **The manual load is real and high.** Transcript classification finds 10,088
   intervention-like supervisor tool calls out of 24,998 total tool calls
   (40.4%). Git-message classification finds 301 likely manual-intervention
   commits out of 1,206 commits (25.0%), but that number is explicitly
   heuristic.
2. **The direction of travel is bad.** Both transcript and git views show no
   sustained decline after the initial build. The transcript rate rises sharply
   in June; the git rate oscillates high after May 28.
3. **The top recurring interventions are not mysterious.** They are mostly
   mechanical operations that the daemon can own: re-dispatch cleanup, stage/task
   driving, test-gate execution and polling, spent-artifact archival, allowlist
   scoping, stale-lock handling, and pause semantics.
4. **The highest-risk intervention is direct production editing.** The transcript
   lane counts 1,259 direct hand-edits to `harness/**`, `ngv2/**`, `config/**`,
   and related production files. These edits bypass the pipeline's intended
   provenance, oracle, gate, and rollback story.
5. **NGv2 risk is concentrated at the emission boundary, not runtime import.**
   Lane 4's most important finding is that JanusMask does not have a live runtime
   dependency on `ngv2.*`; it builds NGv2 as an external target. Therefore
   planner/self-heal/control changes inside JanusMask do not break NGv2 by import
   coupling, but they can absolutely break NGv2 by emitting bad code or by
   mishandling external-root staging, validation, or commit routing.

Recommended first move: do **not** start with a broad "edit any file" super-verb.
First land the smaller deterministic closures that make such a verb safe:
authoritative pause, re-dispatch cleanup, oracle-source injection, verification
command hardening, spent-artifact archival, daemon-owned test execution, and
external-root regression gates. Then wrap them in a single operator-facing edit
or drive command.

---

## 2. Evidence Strength

The four lanes are useful, but they are not equally precise.

| Lane | Strongest Use | Main Weakness |
|---|---|---|
| Lane 1 transcripts | Best volume view of what the external supervisor actually did | Tool-call counts are not task counts; one intervention can require many tool calls, and classification is signature-based |
| Lane 2 git/self-heal | Best durable residue of what landed or failed | Commit-message classification is heuristic; manual and automatic authorship share identity/signature |
| Lane 3 archives | Best root-cause narrative and decision-file evidence | All-corpus keyword counts are noisy; artifacts can mention a blocker without being blocked by it |
| Lane 4 code seams | Best map of where automation can be inserted | Seam existence is not proof that enabling it is safe or enough |

The most defensible claims are the ones corroborated by at least two lanes:

- Manual intervention volume is high: Lane 1 and Lane 2 agree directionally.
- Intervention rate is not decreasing: Lane 1 and Lane 2 both show worsening or
  high oscillation after initial build.
- Manual task driving and state cleanup recur: Lane 1 command classes, Lane 2
  self-heal ledgers, and Lane 3 manual-drive recipes all point at the same
  operational gap.
- External-root / NGv2 handling is a real boundary risk: Lane 1 has 1,710
  NGv2-touching intervention calls, Lane 3 has 16 NGv2/external decision files
  and 18 decision-file hits for external-root target resolution, Lane 4 identifies
  the external-target architecture and the contracts to preserve.

Weak or overstated claims in the original final report:

- **"One in three of everything" is too broad.** The denominators are supervisor
  tool calls and commits, not all factory work. The result is a useful
  intervention-pressure metric, not a literal factory-wide autonomy rate.
- **"Independent denominators agree" is only partially true.** Transcript counts
  and git counts are independent sources, but they measure different things and
  can overlap causally. They should not be averaged into one precise truth.
- **"UEP removes every blocker" is an architecture proposal, not an observed
  result.** A universal edit path may be correct, but the evidence only proves
  the blockers are recurring. It does not prove one new edit primitive can safely
  absorb all of them.
- **"Tiers 1, 2, and 4 are NGv2-safe by construction" is too strong.** Runtime
  import isolation helps, but planner normalization, allowlist automation,
  self-heal promotion, auto-push, and raw-edit guards can change what is built
  into NGv2. That is an emission-path risk.
- **"Oracle authoring should be automated away" is not established.** The reports
  distinguish oracle authoring as a deliberate allowed human artifact. The
  automatable part is oracle **injection and enforcement**, not necessarily
  oracle design.
- **"Half-neutered" is rhetoric, not a complete technical finding.** Some
  disabled flags and clipped call sites are real, but each needs a separate
  readiness review before being turned on.

---

## 3. What Is Solidly Established

### 3.1 Intervention volume is high

Lane 1:

| Metric | Count |
|---|---:|
| Session files analyzed | 2,730 |
| Supervisor tool calls | 24,998 |
| Classified interventions | 10,088 |
| Intervention-call rate | 40.4% |
| NGv2-touching intervention calls | 1,710 |

Lane 2:

| Metric | Count |
|---|---:|
| Commits analyzed | 1,206 |
| Likely automated commits | 905 |
| Likely manual intervention commits | 301 |
| Manual-commit rate | 25.0% |

Use these as a range of intervention pressure, not a single exact autonomy score.
The conservative statement is: **between one quarter of durable landed commits
and two fifths of external-supervisor actions are intervention-shaped.**

### 3.2 The trend is not improving

Lane 1 reports transcript intervention rate increasing from 23.3% in May
(May 21-31) to 52.7% in June (June 1-15). Lane 2 shows the initial cold-start
build near 0-2% intervention, then sustained high oscillation after harder
harness/NGv2 work began, including spikes of 69-82%.

This does not prove the factory got worse. It proves the work got harder faster
than the automation closed the operational gaps.

### 3.3 The biggest intervention buckets are operational, not creative

From Lane 1, the largest intervention classes are:

| Class | Count | Interpretation |
|---|---:|---|
| Ad-hoc inline bash/Python state surgery | 2,150 | Missing daemon verbs and lifecycle cleanup |
| Manual pipeline driving | 1,518 | No first-class "drive this task/stage" control |
| Manual test runs and log polling | 1,312 | Gate execution/status not owned cleanly by daemon |
| Manual production edits | 1,259 | Pipeline bypass for risky files |
| Plan/brief shepherding | 686 | Lifecycle and archival gaps |
| Filesystem operations | 582 | Mostly cleanup, moves, state surgery |
| Oracle test authoring | 449 | Part deliberate policy, part injection gap |
| Git recovery | 396 | Bad integrations and missing rollback/undo flow |
| Allowlist/config edits | 370 | Manual admission/scoping ritual |
| Daemon control | 364 | Pause/run/kill/restart not cleanly unified |
| State sidecar cleanup | 352 | Stale output/session/task state poisoning retries |
| Git push | 153 | Post-green publishing remains manual |

The pattern is clear: the supervisor is often acting as an operations console for
the daemon. That is automatable.

### 3.4 The main blocker classes recur

Lane 3's high-precision decision-file column is the best blocker signal:

| Blocker Class | Decision-File Hits | Notes |
|---|---:|---|
| Jail/sandbox/fail-closed security stand-up | 57 | Large early substrate effort; not all recurring |
| External-root target resolution | 18 | NGv2-critical |
| AST partial-edit / class-method / R-anchor | 9 | Edit/apply path weakness |
| Dep-gate leak/wedge | 5 | Planner/dispatch lifecycle |
| Non-Python / multi-file apply routing | 4 | Apply path weakness |
| External-build smoke / retry budget | 3 | NGv2-critical |
| Implementation not wired | 3 | Acceptance gate gap |
| Planner ignores verification command | 3 | Verification hardening |
| Blind-worker clobber | 3 | Plan/apply safety |
| Stale sidecar precedence | 2 | Re-dispatch cleanup |

All-corpus mentions are useful for attention surfaces but should not be read as
intervention counts. The decision-file counts are smaller and more reliable.

---

## 4. Corrected Structural Diagnosis

The failure is not one thing. It is four interacting gaps.

### Gap A: The daemon lacks an operator-grade control surface

The supervisor repeatedly performs operations that should be daemon verbs:

- reset/requeue task
- drive task to a stage
- pause/resume reliably
- run/poll gate suite
- clear stale locks and sidecars
- archive spent artifacts
- scope allowlist for an epic
- push after clean integration

These are not synthesis problems. They are missing control-plane affordances.

### Gap B: Planner output still needs deterministic sanitation

Several blockers are planner-shape failures: weak verification commands, stray
fields, unresolvable dependencies, multi-file clobber risks, external-root
misrouting, and orphanable implementations. Lane 4 correctly identifies
`normalize_plan` as the right seam.

Important current-tree drift: the live tree already contains
`_strip_stray_mutation_targets()` and `_inject_oracle_sources()` in
`harness/planner/plan_normalizer.py`. Therefore a replacement roadmap should
treat these as examples of the right kind of fix, not necessarily as still-open
work unless tests show they are incomplete.

### Gap C: The apply/integration path is fragile under large, external, or
non-standard edits

AST partial edits, whole-file requirements, non-Python/multi-file routing, and
large-file backend swaps all point at the same weakness: the pipeline needs a
deterministic apply contract that can fail closed before commit. A literal block
manifest or whole-file manifest may be appropriate, but it should be introduced
as a narrow apply primitive with tests before it becomes a universal edit path.

### Gap D: NGv2 is external but not irrelevant

Lane 4's runtime isolation finding is real and valuable: JanusMask does not
import `ngv2.*` at runtime. But the factory edits/builds NGv2 source, and the
reports contain repeated NGv2 intervention evidence. The relevant safety model is:

- JanusMask-internal control-plane changes have low **runtime import** risk to
  NGv2.
- Any change that affects emitted files, external `working_dir`, staging,
  commit-reroot, verification, self-heal promotion, or allowlist admission has
  **build-output** risk to NGv2.

That distinction should govern rollout.

---

## 5. Replacement Roadmap

This roadmap prioritizes small deterministic closures before broad new
architecture. Each item names the evidence and the seam.

### Tier 0: Safety Corrections Before More Automation

| ID | Change | Why First | Seam |
|---|---|---|---|
| T0.1 | Define one authoritative pause primitive | Two pause channels are documented; wrong pause can leave workers live | `autowork_daemon._decide`, `control_gate.check_pause` |
| T0.2 | Add daemon `reset-task` that purges sidecars, sessions, task markers, and stale locks under rules | Replaces a high-volume manual rm/mv/requeue ritual | `stage_task`, daemon control path |
| T0.3 | Add stale lock cleanup with PID/dead-owner and idle-time checks | `daemon_inactivity_stuck` fired 30 times | inactivity watchdog |
| T0.4 | Make test-gate execution and status daemon-owned | Manual pytest launch/poll is 1,312 calls | worker/orchestrator gate status |
| T0.5 | Treat direct production edits as exceptional | 1,259 direct edits bypass pipeline guarantees | interceptor/pre-commit/daemon wrapper |

These changes reduce operational hazard without increasing synthesis authority.

### Tier 1: Planner Normalization and Verification Hardening

| ID | Change | Evidence | Seam |
|---|---|---:|---|
| T1.1 | Keep and test oracle-source injection into worker notes | Lane 3: 209 oracle-first artifacts; live tree already has `_inject_oracle_sources` | `normalize_plan`, `stage_task` |
| T1.2 | Upgrade weak import-only verification to paired pytest gates where an oracle can be resolved | Lane 3: verification-command/vacuous-import blockers | `normalize_plan` |
| T1.3 | Keep and test stripping stray `mutation_target` from non-test-authoring tasks | Lane 3 calls it a live blocker; live tree already has the pass | `normalize_plan` |
| T1.4 | Promote unresolvable-dependency stripping and deadlock breaking cautiously | Lane 2 retry-cap hot spots; Lane 3 dep-gate hits | `normalize_plan`, retry policy |
| T1.5 | Enforce clobber-bomb rejection in validation | Lane 1 clobber neutralization; Lane 3 clobber blockers | `plan_validator` |
| T1.6 | Preserve rootless no-op for external wire-up checks | Lane 4 NGv2 boundary | `wire_up.check_wired` |

Planner passes should remain pure, idempotent, and covered by the whole planner
test suite. The final report should not recommend flag flips without test names.

### Tier 2: Lifecycle Automation

| ID | Change | Evidence | Seam |
|---|---|---:|---|
| T2.1 | Archive spent brief, plan, handoff, and scratch artifacts on integration | Lane 1: 686 shepherding calls; Lane 2: 56 declutter commits | `_reap_spent_briefs_safe`, integrate hook |
| T2.2 | Add `drive-task` / `drive-stage` daemon verb | Lane 1: 1,518 manual pipeline-driving calls; Lane 3 R1/R2 recipes | daemon over `stage_task` and worker spawn |
| T2.3 | Add allowlist scope/snapshot command, not blind auto-admission | Lane 2: 90 distinct slugs and `.bak.epic_*` ritual | allowlist management |
| T2.4 | Add clean-green push policy behind explicit config | Lane 1: 153 manual pushes | accept-commit hook |
| T2.5 | Add revert/undo-last-integration command | Lane 1/Lane 2 git recovery and revert evidence | git integration |

Do not make auto-push unconditional. It should require clean tree, known branch,
passing configured gate, and an enabled config flag.

### Tier 3: Deterministic Apply Primitive

Introduce a deterministic apply contract before introducing a universal edit
entrypoint.

Minimum requirements:

- Ordered file manifests with either exact old/new block replacements or
  whole-file replacement.
- Uniqueness checks: zero or multiple matches must fail closed.
- Path/root resolution before apply, including explicit external-root handling.
- No silent fallback to broad AST surgery.
- Gate before commit.
- Provenance stored with manifest, oracle, command, result, commit, and rollback
  metadata.
- Tests for Python, non-Python, new file, multi-file, large file, duplicate block,
  missing block, NGv2 external-root, and self-edit cases.

Only after this primitive is stable should the project expose a single
`daemon edit` command. The command should be a wrapper over proven pieces, not
the first implementation of those pieces.

### Tier 4: NGv2 Boundary Work

NGv2-facing automation must be gated separately.

| ID | Change | Required Guard |
|---|---|---|
| N1 | End-to-end `working_dir` / external-root threading | Run NGv2 worker smoke and external-root staging/commit tests |
| N2 | External build smoke retry policy | Verify imports resolve against `/home/xnihil0zer0/NobleGreedv2`, not JanusMask |
| N3 | Self-heal auto-promotion for NGv2-touching tasks | Require NGv2 contract suite before commit |
| N4 | Wire-up acceptance changes | Preserve external rootless no-op |
| N5 | Allowlist scoping for NGv2 epics | Snapshot/restore and explicit operator-visible diff |

The NGv2 contract list from Lane 4 should be retained as the regression checklist:

- `ngv2/workers/<phase>.py::run_stage(context, seams)`
- `ngv2/workers/_runner.py` argv and seam keys
- `ngv2/stage_command_map.py::command_for_phase`
- `ngv2/run_hunt.py`
- `ngv2/conductor_seams.py::build_default_seams`
- `ngv2/session_db.py` and `ngv2/session_api.py`
- `ngv2/contracts.py`
- `ngv2/poc_writer.py::write_poc` and `poc_repair_loop.repair_poc`

---

## 6. What Not To Do

Do not turn every OFF flag on because it exists. `archive_spent_briefs`,
`selfheal_auto_promote`, worker pool isolation, antigravity mode, and related
flags each need their own readiness test. A disabled flag is evidence of a
possible seam, not evidence of safe latent capability.

Do not treat all manual oracle work as waste. The allowed manual act appears to
be authoring RED oracles. The automation target is making sure the committed
oracle is injected, enforced, and not bypassed by a weak verification command.

Do not introduce a universal edit path that bypasses the pipeline while claiming
to replace hand-editing. The replacement for raw edits must preserve the things
raw edits currently bypass: oracle, validation, isolated apply, gate, commit,
archive, provenance, and rollback.

Do not use transcript tool-call counts as exact task-level ROI. Use them to rank
automation candidates, then validate against task/commit artifacts.

Do not auto-promote NGv2 self-heals on JanusMask tests alone. The risk is emitted
NGv2 code violating NGv2's own contracts.

---

## 7. Recommended Implementation Order

1. **Lock down observability and safety:** unified pause, daemon-owned test-gate
   status, stale-lock cleanup, reset-task.
2. **Harden planner verification:** oracle injection, weak-vcmd upgrade, stray
   `mutation_target` stripping, dependency cleanup, clobber-bomb rejection.
3. **Close lifecycle loops:** archive spent artifacts, drive-stage command,
   allowlist scope/snapshot command, guarded auto-push.
4. **Build the deterministic apply primitive:** exact block/whole-file manifests
   with fail-closed matching and provenance.
5. **Expose `daemon edit` only after steps 1-4 work:** the command should compose
   already-tested mechanisms.
6. **Then expand into NGv2 external-root automation:** every landing gated by the
   NGv2 contract/smoke suite.
7. **Finally review self-heal auto-promotion:** enable only for failure classes
   with deterministic remediation and adequate regression coverage.

---

## 8. Success Criteria

The next intervention analysis should not just re-count tool calls. It should
measure whether specific manual rituals disappeared:

| Ritual | Target Metric |
|---|---|
| Manual sidecar/session/task cleanup | Near zero direct `rm/mv` of state for known task IDs |
| Manual stage/worker drive | Replaced by daemon `drive-stage` logs |
| Manual pytest polling | Replaced by daemon gate status events |
| Direct `harness/**` / `ngv2/**` edits | Replaced by manifest-backed pipeline edits or explicit exceptions |
| Allowlist file hand-edits | Replaced by scope/snapshot command records |
| Stale daemon lock re-kicks | No repeated `daemon_inactivity_stuck` bursts |
| NGv2 external-root approvals | Decline after external-root regression suite exists |

The success bar is not zero human involvement. The success bar is that human
involvement moves from ad-hoc state surgery and raw production edits to explicit
policy decisions and RED-oracle design.

---

## 9. Bottom Line

The factory's autonomy problem is real, but the fix should be smaller and more
disciplined than the original final report implies. The strongest evidence points
to missing control-plane verbs, fragile planner/apply contracts, and incomplete
lifecycle cleanup. Build those deterministic pieces first. A universal edit or
drive interface can then be a thin wrapper over proven mechanisms instead of a
new all-purpose mechanism with too many untested promises.

