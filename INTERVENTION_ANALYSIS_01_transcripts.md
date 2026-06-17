# Intervention Analysis — Lane 1: External Supervisor Transcripts

**Goal:** Quantify how often the EXTERNAL Claude Code supervisor sessions manually
INTERVENE in the JanusMask factory's automatic pipeline, by TYPE and COUNT, so
those interventions can later be folded into the daemon.

**Method:** Streamed every `*.jsonl` in the two external operator-driven session
dirs, extracted every assistant `tool_use`, and classified each into automatable
intervention categories. The ~3000 internal jailed-agent dirs
(`*.cache-jm-cleanroom-*`, `*-out-*`, `*-replicant`, `TA-*`) were excluded — they
are factory-spawned agents, not operator interventions.

- Parser: `scripts/intervention_analysis/lane1_parse_transcripts.py` (re-runnable)
- Machine summary: `scripts/intervention_analysis/lane1_summary.json`

## Totals

| Metric | Value |
|---|---|
| Session files analyzed | **2,730** |
| Total assistant tool calls | **24,998** |
| Malformed lines skipped | 0 |
| **Interventions** | **10,088 (40.4%)** |
| Read-only exploration + doc notetaking | 12,025 (48.1%) |
| Framework/MCP overhead (TaskUpdate, AskUserQuestion, ToolSearch, submit_code…) | 2,885 (11.5%) |
| Date range | 2026-05-21 → 2026-06-15 |
| Interventions touching NGv2 (`/home/xnihil0zer0/NobleGreedv2` or `ngv2`) | **1,710** |

So roughly **2 of every 5 supervisor actions is a manual intervention** the
pipeline could in principle absorb.

## Counts by category (sorted desc)

Non-intervention rows are marked. Sub-categories were mined out of the original
"OTHER_BASH" bucket using a read-only-verb detector + a mutating-op signal scan.

| Category | Count | Intervention? |
|---|---:|:--:|
| EXPLORATION_READONLY (ls/cat/grep/find/git status/pgrep…) | 10,865 | no |
| OTHER (TaskUpdate, AskUserQuestion, ToolSearch, MCP submit_code, ScheduleWakeup) | 2,885 | no (framework) |
| **OTHER_BASH** (ad-hoc inline `python - <<PY` state surgery, one-off scripts) | 2,150 | **yes** |
| **MANUAL_PIPELINE_DRIVING** (planner.cli / stage_task / orchestrator_worker / `-m ngv2` / drive.py by hand) | 1,518 | **yes** |
| **MANUAL_TEST_RUN** (hand-invoked pytest, sweep-log polling) | 1,312 | **yes** |
| **MANUAL_PRODUCTION_EDIT** (hand-edits to harness/ngv2/config `.py/.yaml/.sh`) | 1,259 | **yes** |
| DOC_NOTETAKING (plan/handoff/memory `.md` edits) | 1,160 | no (operator notes) |
| **PLAN_BRIEF_SHEPHERDING** (brief_hooks_*.md, EPIC_/PROVENANCE_, plan moves) | 686 | **yes** |
| **OTHER_FS_OP** (rm/mv/cp/mkdir, `>` redirects, env setup) | 582 | **yes** |
| **ORACLE_TEST_AUTHORING** (hand-writing `test_*.py`) | 449 | **yes** (sanctioned) |
| **GIT_RECOVERY** (revert/reset/checkout/cherry-pick/amend/manual add+commit) | 396 | **yes** |
| **AGY_SPAWN** (manual `agy --dangerously-skip-permissions …`) | 373 | **yes** |
| **ALLOWLIST_CONFIG_EDIT** (auto_promote.allowlist, config/*.yaml, flip flags) | 370 | **yes** |
| **DAEMON_CONTROL** (pkill/kill, nohup run-autowork, orchestrator.flag, pause file) | 364 | **yes** |
| **STATE_SIDECAR_CLEANUP** (rm/mv state/output/*.patches.json/.files.json, sessions, plans, locks) | 352 | **yes** |
| **GIT_PUSH** (manual `git push origin master`) | 153 | **yes** |
| **CLOBBER_NEUTRALIZE** (guards/edits explicitly stopping a blind clobber) | 94 | **yes** |
| OTHER_EDIT (uncategorised edits) | 30 | yes |

**Total interventions = 10,088.** All categories sum exactly to 24,998 (full
accounting, no double counting).

## Top recurring intervention commands (verbatim, with frequency)

The single largest concrete intervention is **hand-editing production harness
files** — the daemon is supposed to route these through planner→stage→worker, but
the supervisor repeatedly edits them directly:

| n | category | command / file |
|---:|---|---|
| 57 | MANUAL_PRODUCTION_EDIT | `Edit harness/orchestrator.py` |
| 46 | MANUAL_PRODUCTION_EDIT | `Edit harness/config.yaml` |
| 34 | MANUAL_PRODUCTION_EDIT | `Edit harness/autowork_daemon.py` |
| 31 | MANUAL_PRODUCTION_EDIT | `Edit harness/orchestrator_worker.py` |
| 29 | ALLOWLIST_CONFIG_EDIT | `Edit state/control/autowork/auto_promote.allowlist` |
| 25 | MANUAL_PRODUCTION_EDIT | `Edit harness/git_integration.py` |
| 19 | MANUAL_TEST_RUN | `pgrep -f "pytest -q -p no:cacheprovider" … && …` (poll test sweep) |
| 17 | PLAN_BRIEF_SHEPHERDING | `Edit brief_hooks_overseer_chat.md` |
| 16 | MANUAL_PRODUCTION_EDIT | `Edit harness/agent_jail.py` |
| 15 | MANUAL_PRODUCTION_EDIT | `Edit _autowork_scratch/ngv2_fsm/poc_writer.py` |
| 14 | MANUAL_PRODUCTION_EDIT | `Edit _autowork_scratch/pty_jail_proof.py` |
| 12 | ORACLE_TEST_AUTHORING | `Edit tests/test_orchestrator.py` |
| 10 | MANUAL_PRODUCTION_EDIT | `Edit harness/planner/blind_draft.py` |
|  9 | MANUAL_PRODUCTION_EDIT | `Edit /home/xnihil0zer0/NobleGreedv2/ngv2/poc_writer.py` (NGv2!) |
|  8 | MANUAL_TEST_RUN | `python -m pytest tests/test_autowork_daemon.py -q` |
|  7 | MANUAL_PIPELINE_DRIVING | `source venv/bin/activate; python - <<PY … (manual stage drive)` |
|  6 | GIT_PUSH | `git push origin master 2>&1 \| tail -2` |

Representative per-category exemplars:

- **DAEMON_CONTROL:** `printf run > state/control/orchestrator.flag; nohup … run-autowork`;
  `DPID=$(cat /tmp/ngv2e4_daemon.pid); kill …`; `TID=…; rm -f state/output/$TID.* state/tasks/…` (pause-then-reset combo)
- **STATE_SIDECAR_CLEANUP:** `rm -f state/output/<id>.patches.json state/output/<id>.files.json`;
  `pkill -9 -x agy; mv state/tasks/processed/<id> …`; `rm -f state/tasks/blocked/<id>.json`
- **GIT_RECOVERY:** `git add <plan>.md; git commit -q -m …`; `cp /tmp/.../oracle … && git …` (hand-land); reverts of bad auto-commits
- **ALLOWLIST_CONFIG_EDIT:** `Edit auto_promote.allowlist` (29×), `Edit config/autocompiler.yaml`, `scripts/flip_autowork_flags.sh`
- **AGY_SPAWN:** `agy --dangerously-skip-permissions --model "Gemini 3.5 Flash (Medium)" --print-timeout 20m --add-dir …`
- **MANUAL_PIPELINE_DRIVING:** `python - <<PY … from harness.planner.stage … PY` (hand-pushing a task through a pipeline stage)

## Timeline — are interventions decreasing?

**No — they are clearly INCREASING as a share of activity.**

| Period | Interventions | Tool calls | Intervention rate |
|---|---:|---:|---:|
| May (21–31) | 2,447 | 10,500 | **23.3%** |
| June (01–15) | 7,641 | 14,498 | **52.7%** |

Daily rate climbs steadily: ~15–23% in the first week (late May), crossing 40% by
~Jun 2, and sitting at 50–63% for almost all of June. This is the opposite of the
hoped-for trend: as the factory took on harder work (NGv2 bounty FSM, overseer,
autocompiler, source-driving), the supervisor had to drive *more* by hand, not
less. The automation candidates below are where that growing manual load
concentrates.

## NGv2 compatibility note

**1,710 interventions (17% of all interventions) touch NGv2 interfaces** (mention
`ngv2`/`NobleGreedv2`). Concentrations: OTHER_BASH inline state surgery (430),
MANUAL_PIPELINE_DRIVING (286, e.g. `python -m ngv2.*` and `drive.py`),
MANUAL_TEST_RUN (158), DAEMON_CONTROL (107), MANUAL_PRODUCTION_EDIT (107 —
including **direct hand-edits to `/home/xnihil0zer0/NobleGreedv2/ngv2/poc_writer.py`**,
9×). Any automation of these patterns **must preserve the NGv2 interface contract**
(the `python -m ngv2.workers.<phase>` / `python -m ngv2.run_hunt` entrypoints and
the SessionDB/gate-graph seams). Folding pipeline-driving into the daemon should
re-use the existing NGv2 module entrypoints rather than reaching into NGv2
internals, so the cleanroom rebuild stays decoupled.

## Automation candidates (highest-value, deterministic)

Ranked by frequency × determinism — the patterns most worth folding into the
daemon:

1. **Auto state/sidecar reset before re-dispatch (DAEMON_CONTROL+STATE_SIDECAR ≈
   700+ calls).** The recurring `TID=…; rm -f state/output/$TID.* state/tasks/…`
   then re-run idiom is fully deterministic. Add a daemon `--reset-task <id>`
   action that purges `state/output/<id>.{patches,files}.json`, the session, the
   `processed`/`blocked` marker, and stale `git_commit.lock`, then re-queues —
   eliminating the manual rm+mv+pause dance (and the known stale-sidecar
   precedence gotcha).

2. **Auto `git push` after a green integrate (GIT_PUSH, 153).** The command is
   almost always the literal `git push origin master`. Gate it behind the
   existing green-integrate hook so the daemon pushes automatically once the
   working tree is clean and tests pass.

3. **Daemon-managed test sweep + poll (MANUAL_TEST_RUN, 1,312).** The dominant
   pattern is launch-pytest-then-poll-a-logfile (`pgrep -f pytest … && …`,
   `tail sweep.log`). Have the daemon run the gating suite itself and expose
   status, removing both the manual launch and the 19×-repeated poll loop.

4. **Brief/plan lifecycle automation (PLAN_BRIEF_SHEPHERDING, 686).** Moving
   spent briefs to `_autowork_archive/`, re-dispatching, and `brief_hooks_*.md`
   churn is mechanical. The `archive_spent_briefs` flag covers part of this;
   extend it to also move spent plans out of `state/plans/` and auto-archive
   EPIC_/PROVENANCE_/handoff scratch on integrate.

5. **Allowlist auto-population on brief admission (ALLOWLIST_CONFIG_EDIT, 370 —
   29× the same allowlist file).** The supervisor repeatedly hand-edits
   `auto_promote.allowlist`. When the planner admits a brief, it can derive and
   append the allowlist entries automatically (with the EX_fix phantom-task
   exception already in memory), removing nearly all manual allowlist edits.

6. **Daemon-driven pipeline staging (MANUAL_PIPELINE_DRIVING, 1,518).** The
   `python - <<PY … harness.planner.stage …` hand-drives exist precisely because
   the daemon couldn't push a specific task through one stage on demand. A
   `daemon drive --task <id> --to-stage <stage>` command (re-using existing
   planner/worker entrypoints, and the NGv2 `-m ngv2.*` entrypoints unchanged)
   would absorb most of this — the single biggest concrete intervention bucket.

7. **Route harness hand-edits through the pipeline / detect them (MANUAL_PRODUCTION_EDIT,
   1,259).** Direct edits to `harness/orchestrator.py` (57), `config.yaml` (46),
   `autowork_daemon.py` (34), etc. violate the "never hand-edit production outside
   the pipeline" rule. These are harder to fully automate, but a pre-commit guard
   that flags un-pipelined edits to `harness/**`/`ngv2/**` and offers to wrap them
   in a `harness_self_fix` brief would convert the highest-risk manual action into
   a sanctioned flow.

8. **Manual `agy` spawn → daemon-managed oracle authoring (AGY_SPAWN, 373).** The
   `agy --dangerously-skip-permissions --model "Gemini …" --add-dir …` invocation
   is templated and repetitive. Wrap it as a daemon sub-action for the
   oracle-authoring / Gemini-solo recipes (the webui large-file leaves already use
   a scoped config override), with the post-run tree verification baked in (agy is
   not isolated from the main tree).

### Lower-priority but deterministic
- **DAEMON_CONTROL pause/resume (364):** `printf run/pause > orchestrator.flag` and
  pause-file touch/rm are trivial to expose as first-class daemon verbs (note the
  documented pause semantics: dispatch loop pauses on existence of
  `state/control/autowork/pause`; orchestrator.flag needs the literal `paused`).
- **GIT_RECOVERY (396):** reverting bad auto-commits is the inverse of an
  auto-commit; a daemon "undo last integrate" that reverts the commit and restores
  sidecars would cover the common case.
