# Intervention Analysis — Lane 2: Git History + Self-Heal / State Ledgers

Forensic quantification of how often the external Claude supervisor had to
**manually intervene** in the JanusMask automatic pipeline, derived from the
durable residue: the git log and the runtime state ledgers under
`state/control/autowork/`.

Reproduce: `python3 scripts/intervention_analysis/lane2_git_selfheal.py`
(emits `scripts/intervention_analysis/lane2_results.json`).

Classification is **heuristic, by commit-message signature** — the git author
("JanusMask Rebuild Engine") does not distinguish manual vs automatic, so the
message body is the only signal. "Integrate validated code …" is the pipeline's
own auto-commit boilerplate and is treated as automated even when its payload
slug is a fix/wire-up (those are counted separately as *auto-integrated
remediation*). Numbers are directional, not exact ground truth.

---

## 1. Commit classification

**Total commits analyzed: 1206**

| Kind | Count | % |
|---|---:|---:|
| Automated (pipeline integrations, oracles, scaffolds) | 905 | 75.0% |
| **Manual intervention** | **301** | **25.0%** |

**1 in 4 commits is a supervisor intervention** — i.e. work the pipeline could
not produce on its own.

### Per-class breakdown (sorted desc)

| Class | Kind | Count | Example |
|---|---|---:|---|
| Integrate validated code | auto | 680 | `Integrate validated code for stamp-working-dir-blind-draft` |
| other/unclassified | auto | 120 | (misc oracle/handoff/epic-artifact commits) |
| **config/flag flip** | intv | **83** | `Flip workers.claude_backend to tmux`; `enable the autocompiler layer` |
| **owner hand-edit** | intv | **59** | `§4a/§4b owner hand-edits`; `Recover ControlHandlers … wiped by leaf` |
| **declutter/archive sweep** | intv | **56** | `Archive stale root scratch (declutter sweep)` |
| **bugfix/defect** | intv | **48** | `fix(blocker1): drop bogus -m flag from claude_fallback` |
| RED oracle | auto | 45 | `Add RED oracle: …` |
| **blocker/deadlock unblock** | intv | **30** | `Phase 3b brief-dep deadlock-breaker` |
| oracle/brief authoring | auto | 25 | `briefN_*: oracle (RED on HEAD)` |
| Test/oracle commit | auto | 19 | `Test: _spy accepts working_dir kwarg` |
| **revert/undo** | intv | **15** | `acc7edb hand-edit reversed → pipeline-re-landed` |
| skeleton/scaffold | auto | 15 | `skeleton: JR_leafC1` |
| **wire-up/orphan** | intv | **7** | `wire-up Wave-2: tracer` |
| **clobber neutralize/guard** | intv | **3** | clobber-bomb neutralizations |
| docs/README | auto | 1 | |

**Intervention-class total = 301** (config-flip 83 + hand-edit 59 + declutter 56
+ bugfix 48 + unblock 30 + revert 15 + wire-up 7 + clobber 3).

Separately, **87 of the 680 auto-integrations carry a remediation payload**
(slug contains fix/clobber/wire/unblock/orphan/guard). The pipeline successfully
self-built ~13% of its own *fixes* — but the 301 manual commits are the ones it
could not.

### Commits-over-time intervention rate (trend)

```
2026-05-20  auto=  4 intv=  0    0%
2026-05-22  auto= 93 intv=  0    0%   <- bulk initial build, fully automated
2026-05-25  auto=146 intv=  3    2%
2026-05-29  auto=  6 intv= 28   82%   <- first big intervention spike (SEC/self-heal)
2026-05-30  auto= 10 intv= 13   57%
2026-06-01  auto= 77 intv= 20   21%
2026-06-02  auto= 69 intv= 24   26%
2026-06-04  auto= 33 intv= 27   45%
2026-06-05  auto= 55 intv= 33   38%
2026-06-08  auto= 72 intv= 28   28%
2026-06-09  auto= 39 intv= 31   44%
2026-06-10  auto= 22 intv= 19   46%
2026-06-12  auto=  5 intv= 11   69%
2026-06-13  auto= 17 intv=  9   35%
2026-06-14  auto= 17 intv=  5   23%
```

**Trend: NOT falling.** The first week (May 20–25, the cold-start build) was
~0–2% intervention. Once the factory began doing real harness/NGv2 work
(May 28+) the rate jumped and has **oscillated in a steady 25–46% band** ever
since, with spikes to 69–82% on hard days (May 29 SEC/self-heal stack; Jun 12
financial-viability pivot). The factory has **not** become more self-sufficient
over time — interventions scale with task difficulty, not down with maturity.

---

## 2. Self-healing history (`self_healing_history.jsonl`)

**109 events across 75 distinct tasks; only 6 tasks retried.**

| Outcome | Count | Meaning |
|---|---:|---|
| `auto_commit_failed` | 37 (+1 r1, +1 r2 = 39) | synth passed but commit/AST-merge rejected |
| `inactivity` | 30 | **daemon wedged / stuck** (all one task: `daemon_inactivity_stuck`) |
| `synthesis_or_ast_failed` | 28 | dual-agent could not produce mergeable AST |
| `smoke_failed` | 6 | external build/smoke gate failed |
| `orphaned` | 4 | module built but never wired to a live root |
| `embedded_tests_failed` | 2 | in-plan oracle failed |

**Most common failure→heal patterns:**
- **`daemon_inactivity_stuck` fired 30×** — the daemon repeatedly wedged
  (stale lock / no progress) and the self-heal watchdog re-kicked it. This is
  the single biggest *recurring* heal signature and is purely mechanical.
- **`auto_commit_failed` (39)** is the dominant *task-level* failure: synthesis
  succeeds but the AST-merge/commit step rejects the patch (class-method edits,
  symbol-add via patch path, large-symbol truncation — all documented gotchas).
- Retried tasks healed at most twice then gave up; e.g.
  `RB_jr_slice_TargetDescriptor___post_init__` → `auto_commit_failed` ×2;
  `stamp-working-dir-blind-draft` → `synthesis_or_ast_failed` ×2.

**Self-heal targets skew NGv2:** top touched files are `ngv2/workers/__init__.py`
(6×), `ngv2/workers/hunt.py` (3×), `ngv2/mff_*`, `ngv2/session_db.py`.
⚠️ **NGv2-compat flag:** the self-heal loop frequently rewrites NGv2 worker and
session-DB modules. Any automation that auto-promotes these heals must preserve
the NGv2 public interfaces (`ngv2.workers.*`, `ngv2.session_db.SessionDB/
SessionApi`, `ngv2.run_hunt`) that the NobleGreedv2 runtime depends on.

---

## 3. Allowlist churn (manual-gating proxy)

The `auto_promote.allowlist` is the human gate: only listed brief slugs may
auto-promote. Every edit is a manual gating decision.

| Metric | Value |
|---|---:|
| Allowlist snapshot files (incl. `.bak.*`) | 4 |
| **Distinct slugs admitted over time** | **90** |
| Currently active entries | 8 |
| Largest snapshot (`*.full.63cdda4.bak`) | 84 |

**90 distinct slugs** have been hand-added to the gate across the project — each
a discrete "owner approves this brief for autonomy" decision. The current list
was deliberately **narrowed from 84 → 8** (focused on the NGv2 automation epic),
with the full backlog preserved in `*.full.*.bak` for restore. The `.bak`
suffixes (`bak.epic_srcdrive`, `bak.1781395200`) show the list is snapshotted
and re-scoped per epic — a recurring manual ritual, not a one-time setup.

---

## 4. Recurring blocker signatures (quarantine / plan_attempts / selfheal_skip)

| Ledger | Count | What it means |
|---|---:|---|
| `selfheal_skip/` markers | **86** | tasks the self-heal loop **permanently gave up on** (1-byte abandon markers) |
| `plan_attempts/` | 38 | per-slug planning-retry counters |
| `selfheal_provenance/` | 33 | provenance of healed leaves |
| `quarantine/` | 2 | co-hallucinated briefs quarantined |

**86 selfheal-skip markers** is the loudest signal: for 86 tasks the automatic
heal loop exhausted its budget and stopped trying — these are the cases that
*forced* a human into the loop.

**`plan_attempts` hot-spots (hit the retry cap = 5):**
`integration-smoke-classifiers`, `conductor-seams`,
`integration-smoke-plan-validation`, `integration-smoke-config-flag` — all at 5
attempts (the budget ceiling). The **integration-smoke epic and conductor-seams
are the chronic planner-deadlock offenders**; they re-plan to the cap and then
need a brief rewrite (non_goals excuse, Required-plan-shape) to proceed.

**Quarantine pattern:** both quarantined items are
`brief_hooks_*` co-hallucinated briefs (normalizer/symbol-ledger) — agents
invented briefs that didn't match real oracle contracts.

---

## 5. Automation candidates (deterministic interventions the daemon could absorb)

Ranked by frequency × determinism:

1. **Auto-recover from `daemon_inactivity_stuck` (30 self-heal events).**
   Already partly watchdog-handled, but 30 fires means the wedge keeps
   recurring. Root-cause the stale `git_commit.lock` / no-progress trigger and
   auto-clear it (delete stale lock if PID dead + N min idle) instead of relying
   on repeated re-kicks. Purely mechanical.

2. **Auto-archive spent briefs/plans/handoffs (56 declutter commits).** The
   `archive_spent_briefs` flag exists but root-scratch still accretes until a
   manual "declutter sweep." Make the integrate hook *always* move spent
   brief+plan+handoff into `_autowork_archive/<date>/` as renames — fully
   deterministic (the slug is known at integrate time).

3. **Auto-clear `auto_commit_failed` for known AST-merge classes (39 events).**
   The dominant task failure. The failure modes are catalogued (class-method
   edit, symbol-add-via-patch, large-symbol truncation). The self-heal loop
   should detect these signatures and **auto-retry with the corrected strategy**
   (whole-file emit, R-anchored trailing node) rather than skipping to a human.

4. **Auto-escalate planner deadlock at attempt cap (4 slugs hit 5/5).**
   When `plan_attempts >= cap`, the daemon currently stalls. Add a deterministic
   "deadlock breaker": inject the standard non_goals integration-test excuse +
   Required-plan-shape into the brief and reset the budget once, automatically
   (this is exactly what the supervisor does by hand for integration-smoke).

5. **Auto-strip stray `mutation_target` on new-file impl tasks.** A documented
   root blocker (planner attaches `mutation_target=module.function` to new-file
   tasks → bogus mutation gate). A `_strip_stray_mutation_targets` normalizer
   pass would absorb a whole class of manual brief-nudges (intervention class:
   blocker/unblock, 30 commits).

6. **Detect + neutralize clobber-bombs at plan time (3 explicit + many time-bombs).**
   Signature is deterministic: `python -c "import X"` vacuous verification_command
   + file already at HEAD. A plan-validator rule should reject/normalize these
   automatically instead of letting a blind worker stub a live symbol.

7. **Auto-prune the selfheal_skip backlog with a re-try-once policy (86 markers).**
   86 permanently-abandoned tasks accumulate with no re-evaluation. Add a periodic
   sweep that re-queues skip-marked tasks once after a harness root-fix that
   touches their failing subsystem (provenance is already tracked).

8. **Auto-snapshot + restore allowlist on epic switch (90 churn entries).**
   The `.bak.epic_*` ritual is manual. A `scope_allowlist_to_epic <slug>`
   command that snapshots the full list and narrows to an epic's transitive
   children would absorb a recurring manual gating step.

9. **Auto-detect orphaned modules at integrate (4 `orphaned` heals + 7 wire-up
   commits).** The `wire_up_gate` exists but is default-OFF; orphans still slip
   through to manual wire-up commits. Default it ON for new-module leaves so the
   orphan is caught before commit, not after.

---

## NGv2 compatibility flags

- **Self-heal frequently rewrites NGv2 modules** (`ngv2/workers/*`,
  `ngv2/session_db.py`, `ngv2/mff_*`). Any auto-promotion of these heals (esp.
  candidates #3, #7) MUST preserve the public NGv2 interfaces consumed by the
  NobleGreedv2 runtime: `ngv2.workers.<phase>` entrypoints, `SessionDB`/
  `SessionApi`, `ngv2.run_hunt`. Validate against NGv2's own oracle suite, not
  just JanusMask's, before auto-committing.
- The active allowlist is entirely NGv2-epic scoped (8/8 entries) — automating
  allowlist scoping (candidate #8) directly affects which NGv2 briefs run.
