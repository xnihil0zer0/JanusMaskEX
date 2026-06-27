# Adversarial Review — "archive-on-integrate" shipped code

Reviewer: adversarial agent 1. Repo: `/home/xnihil0zer0/JanusMaskJR`. HEAD at review:
`e33eb44` (flag-activation `11930d2`, reaper `a060fdc`, wiring `4b64e84`).

Scope: correctness & runtime behavior of `tools/brief_reaper.py`,
`harness/orchestrator_worker.py` (`_reap_spent_briefs_safe` + `_print_json_line`),
`harness/config.yaml` flag, and the author's "proven end-to-end / no regressions"
claims. Every claim below is backed by a reproduction.

Verdict up front: the code does not crash and the two oracles pass (16/16), but the
**oracles are weak**, the **semantics of "integrated" are wrong** (it archives on
verification-command exit codes, not on whether the brief's work was actually
integrated), the **git-tree mutation is silent and inconsistent**, and the
**"proven end-to-end" claim is false** — it was only hand-called, never fired
through a real worker dispatch. Several HIGH-severity correctness defects.

---

## FINDING 1 — "Integrated" is decided by re-running vcmds, so a brief is archived while sibling tasks are still pending. [HIGH]

`reap_for_task` (brief_reaper.py:104-108) collects the DISTINCT
`verification_command` strings across the *whole plan* and archives iff every one
exits 0 — it never checks whether the sibling tasks were actually integrated /
processed. A multi-task plan where only ONE task has landed but the other task's
vcmd is independently green (very common: shared command, trivially-passing
module, or a test file that already exists) is archived prematurely.

Reproduction (all four cases ran clean, no exceptions):

```
CASE1 (archive on integrating only A, B pending but vcmd green): ['x'] -> brief gone: True
```

A 2-task plan, integrate only task `A`, task `B` never built but its vcmd exits 0
→ the brief+plan are reaped out from under task `B`. The oracle even *blesses*
this as intended (`test_multi_task_plan_archived_only_when_all_green`), but it is a
real hazard: the moment the daemon re-dispatches `B`, its `plan_hooks_<slug>.json`
is gone from root, so the planner/daemon can no longer find the brief. This
directly answers the prompt's task 6: **yes, it archives a brief while sibling
tasks are still pending** whenever the pending sibling's vcmd happens to pass.

Note the design assumption "all distinct vcmds green ⇒ everything integrated" is
only valid if vcmds are 1:1 with their task's deliverable AND fail before the
deliverable exists. Neither is guaranteed — a vcmd that runs a broad suite, or a
test file pre-staged by a prior leaf, passes for the wrong reason.

## FINDING 2 — Two plans sharing a `task_id` → the WRONG brief is archived. [HIGH]

brief_reaper.py:84 iterates `sorted(root.glob('plan_hooks_*.json'))` and `break`s
on the FIRST plan whose tasks contain `task_id`. Task ids are not globally unique
(daemon-generated ids, hand-authored plans, re-decompositions all collide), so the
reaper silently picks the lexicographically-first plan.

```
CASE2 (two plans share task_id 'shared'): ['aaa'] aaa gone: True zzz gone: False
```

Integrating `shared` archived `brief_hooks_aaa.md` while the actually-relevant
`zzz` brief was left untouched. If `aaa`'s vcmd is green but `aaa` itself is still
in flight, this is data loss against the wrong brief.

## FINDING 3 — Archives a plan with NO brief, and archives "epics with no brief". [MEDIUM]

The epic guard (brief_reaper.py:102) is `if brief_path.exists() and _is_epic(...)`.
If the brief file is absent, the guard is skipped and the plan is still archived:

```
CASE3 (no brief file, only plan): ['q'] plan gone: True
```

So a plan whose brief was an epic but whose `.md` is momentarily missing (or named
off-slug) bypasses the never-reap-epics rule. More generally the reaper happily
moves a `plan_hooks_*.json` with no paired brief — orphaning paperwork the daemon
may still need.

## FINDING 4 — Verification commands run with `shell=True` on the hot accept path: side effects + injection + latency. [HIGH]

`_all_green` (brief_reaper.py:50-59) does
`subprocess.run(cmd, shell=True, cwd=repo_root)` for every distinct vcmd in the
plan, **on the worker's hot accept path, on every accepted build**.

- Side effects execute: a vcmd is arbitrary shell, re-run at archive time.
  ```
  CASE4 (vcmd side effect ran): True archived: ['p']   # "touch PWNED; true" created the file
  ```
  Any vcmd with a side effect (mutating fixtures, writing files, hitting network,
  re-dispatching) runs a SECOND time at commit, after the build already passed it.
- Injection: vcmd content originates from plan JSON (agent/planner-authored). With
  `shell=True` a malicious or malformed vcmd runs verbatim under the worker's
  privileges at commit time. There is no allowlist, no `shlex`, no sandbox.
- Latency: real plans use `python -m pytest tests/...`. Measured a single real
  oracle at **1.12s**; real plans carry multiple DISTINCT pytest commands run
  serially. `plan_hooks_enforcement-integration.json` has **3 distinct pytest
  vcmds** → ~3-5s+ added to *every* accept. Each vcmd has a **600s** timeout, so
  worst case the reaper can block the worker for `600 * N` seconds.
- This is full-oracle-at-commit-time and **races the just-completed commit**: it
  runs against the post-commit working tree (`cwd=repo_root`), which is fine for a
  pure read, but any vcmd that depends on uncommitted state, or any concurrent
  worker mutating the tree, makes the green/red verdict nondeterministic.

## FINDING 5 — The reaper blocks worker EXIT, which blocks the daemon. [MEDIUM/HIGH]

`_reap_spent_briefs_safe` is called from inside `_print_json_line`
(orchestrator_worker.py:74-75) which runs BEFORE the accept path's `return 0`
(e.g. line 494-495). The daemon spawns the worker and waits on
`proc.communicate(timeout=timeout_sec)` (autowork_daemon.py:1232) — it waits for
the *process to exit*, not for the JSON line. So the worker process stays alive
running the reaper's pytest commands after emitting `accepted`. Consequences:

- The daemon's per-worker timeout can fire mid-reap. If `timeout_sec` elapses
  while the reaper is mid-`_move` (git mv done, shutil pending, or vice versa) the
  daemon kills the worker → **half-archived brief/plan** (one file moved, one not).
- It serializes accept throughput on a synchronous full-oracle re-run that has
  nothing to do with the build's own validation (which already happened upstream).

The flush-before-reap ordering (line 72-73) only guarantees the *line* is emitted;
it does nothing for process exit, which is what the daemon actually awaits.

## FINDING 6 — Silent, git-inconsistent working-tree mutation; collisions overwrite. [HIGH]

`_move` (brief_reaper.py:61-71) tries `git mv` then falls back to `shutil.move`.
For UNTRACKED briefs/plans (the normal case — freshly authored paperwork at root
is usually untracked) `git mv` fails and `shutil.move` runs, leaving the
destination **untracked** and **no staged source deletion**:

```
git status after reap (untracked brief):
 ?? _autowork_archive/
dest exists: True
```

This is exactly the live state of the real archive: `_autowork_archive/2026-06-08/
reconciled/` holds **44 files, all `??` untracked** (verified via `git status
--short`). The reaper mutates the working tree invisibly to git and to the
daemon's commit flow; those moves can be lost, double-applied, or confuse a later
`git add -A`.

Destination collisions silently overwrite (two slugs reaped to the same stamp, or
a re-dispatch):

```
archive on dest-collision returned: ['c']
dest content now: NEW CONTENT (OLD overwritten silently)
```

`shutil.move` onto an existing file replaces it — prior archived content is lost
with no error and no warning.

## FINDING 7 — "Proven end-to-end" is FALSE; it was only hand-called. [HIGH — process/claim defect]

The author claims it was proven by manually calling
`_reap_spent_briefs_safe({'outcome':'accepted','task_id':'brief_reaper_module'})`.
That is a hand call of the bridge, not a real dispatch. Evidence it never fired
through a genuine worker integrate:

- I ran the heavy e2e batch (`test_orchestrator_hitl_pipeline`,
  `test_external_capability_e2e`, `test_orchestrator_worker_timeout_budgets`, 34
  tests) with the flag ON and the real config — **root briefs unchanged** (`NO
  CHANGE`). None of the real accept paths reached the reaper with a matching plan.
- The accept emit sites are NOT all `outcome:'accepted'`. The `no_diff` accept
  paths (orchestrator_worker.py:499, 576, 673) emit `outcome:'no_diff'`, which the
  bridge ignores (line 53) — yet `no_diff` means the brief is genuinely DONE (per
  the worker's own comment at line 84). So **the reaper MISSES the entire no_diff
  class of completed briefs.** The "all 4 accept emit sites" framing is wrong:
  there are ~5 `'accepted'` sites and ~3 `'no_diff'` sites; only the former fire.
- The committed reconciled archive (44 files) did NOT come from the worker reaper —
  it came from the separate `scripts/brief_status.py` "ground-truth sweep" added in
  the SAME commit `11930d2`. So the visible archive evidence is the *manual*
  reconciler, not the wired-in reaper firing on accept. The end-to-end worker path
  has zero observed real-world firing.

## FINDING 8 — External (non-self) builds reap against the JM root regardless. [MEDIUM]

`repo_root = pathlib.Path(__file__).resolve().parents[1]` (orchestrator_worker.py:65)
correctly resolves to the JM root for the worker's location (verified:
`/home/xnihil0zer0/JanusMaskJR`). But it is **hard-pinned to JM** and ignores
`JANUSMASK_WORKING_DIR`. For an EXTERNAL target build (e.g. NGv2), an `accepted`
outcome still drives the reaper to glob `plan_hooks_*` at the **JM root** and run
JM-rooted pytest vcmds. If the external task_id collides with a JM plan task
(Finding 2 mechanism), an unrelated external build can archive a JM brief.

---

## What IS correct / what I could NOT break

- Fail-safe wrapping is genuinely robust: `reap_for_task` wraps its whole body in
  `except Exception` (brief_reaper.py:119), the bridge wraps its body
  (orchestrator_worker.py:69), AND `_print_json_line` wraps the bridge call (line
  76). I could not construct an input that escapes an exception to the caller; the
  JSON line is always emitted first (line 72 flush precedes the reaper). The two
  "swallows exception" oracle tests are legitimate.
- Repo-root computation is correct for the worker file's actual location.
- The flag read (`cfg.get('autowork', {}).get('archive_spent_briefs')`, line 57)
  and default-OFF semantics are correct; flag is committed ON in config.yaml:41.
- Both oracles pass: `16 passed in 0.27s`. Worker/timeout regression set: `13
  passed`. No crash regressions observed in the suites I ran.

## Oracle weakness assessment (prompt task 1)

`tests/tools/test_brief_reaper.py` tests only hermetic happy paths with
`python -c sys.exit(N)` vcmds. It MISSES: shared/colliding task_ids across plans
(Finding 2), premature archive on a pending sibling whose vcmd is green (Finding 1
— it actively asserts this AS desired behavior), plan-without-brief reaping
(Finding 3), shell side effects / injection (Finding 4), git-tracked vs untracked
move divergence and dest-collision overwrite (Finding 6), and symlinked
brief/plan paths. The wiring oracle monkeypatches `reap_for_task` away, so it
never exercises the real subprocess/move behavior end-to-end and cannot catch any
of the above.

## Severity roll-up

| # | Finding | Severity |
|---|---------|----------|
| 1 | Premature archive while sibling task pending (vcmd-green ≠ integrated) | HIGH |
| 2 | Shared task_id → wrong brief archived | HIGH |
| 4 | shell=True vcmd re-run on hot path: side effects + injection + latency | HIGH |
| 6 | Silent git-inconsistent move; collisions overwrite | HIGH |
| 7 | "Proven end-to-end" false; no_diff class missed; archive came from manual sweep | HIGH |
| 3 | Plan with no/epic-missing brief still archived | MEDIUM |
| 5 | Reaper blocks worker exit → blocks daemon; kill mid-move | MEDIUM/HIGH |
| 8 | External builds reap against hard-pinned JM root | MEDIUM |

## Reproduction notes

All cases above were run from repo root with the project venv. The four CASE
reproductions, the untracked-move git-status demo, the dest-collision overwrite
demo, the 1.12s real-pytest latency measurement, and the 34-test e2e "NO CHANGE"
side-effect check are all reproducible by re-running the inline `python3 -` /
`pytest` snippets in this report. `git status --short _autowork_archive/2026-06-08/
reconciled/` shows the 44 untracked files corroborating Finding 6.
