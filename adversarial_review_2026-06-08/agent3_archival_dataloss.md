# Adversarial Audit — Brief/Plan Archival Data-Loss & Misclassification

**Auditor:** Agent 3 (adversarial, data-loss + classification-correctness)
**Repo:** /home/xnihil0zer0/JanusMaskJR @ HEAD `e33eb44` (archive commit `11930d2`)
**Date:** 2026-06-08
**Verdict:** No real pending work was misclassified as DONE. The classification was, in this run, **substantively correct** — every archived plan's oracle re-ran GREEN under my independent verification. However, there are **two real bugs in the tooling** (one provenance/data-integrity, one latent false-positive vector) and the "40 archived" / commit story is **misleading about what was actually committed**.

---

## Executive summary (ranked by severity)

| # | Severity | Finding |
|---|----------|---------|
| 1 | **DATA-INTEGRITY (medium)** | 37 of the 39 moved files are **UNTRACKED and UNCOMMITTED** in `reconciled/`. They were `shutil.move`'d (git mv rejected untracked sources), so the archive at HEAD `11930d2` contains only 4 reaper-fixture files. The bulk of the "archive" exists only in the working tree — not reversible via git, not in any commit, lost on a `git clean -fdx`. |
| 2 | **LATENT FALSE-POSITIVE (medium)** | The planless-brief `brief_command` regex is fragile. It already misfires on `brief_hooks_brief_status.md`, extracting the command `...` (literal ellipsis from prose). It happened to be harmless **only** because that brief has a plan (plan branch wins). A planless brief whose prose contains `verification_command: "..."` or any stray `python -m pytest ...` example line would be classified by the WRONG command. |
| 3 | **LATENT FALSE-POSITIVE (low/medium)** | The reaper's `_distinct_commands` **dedups** verification commands. A multi-task plan whose tasks share one test file would reap (archive) the whole plan when only ONE task is integrated. Did NOT fire this run (no archived multi-task plan shares a command), but it is an unguarded premature-archival vector. |
| 4 | **MISCLASSIFICATION (cosmetic, benign)** | One ORPHAN-PLAN (`plan_hooks_overseer-webui-frontend.json`) is **not a leaf plan at all — it is an EPIC decomposition record** (`plan_kind:"epic"`, `child_slugs:[...]`). The classifier blindly archives orphan plans with NO green check; this one had no verification_command and was archived purely for lacking a sibling brief. Benign here (its source brief + children are already done/archived elsewhere), but the classifier would have swept it even if its children were unbuilt. |
| 5 | **COUNT CLAIM (minor inaccuracy)** | The "21 briefs = 19 DONE + 2 EPIC + 3 ORPHAN" count does not cleanly reconcile with reality (20 archived briefs + 1 planless + the 2 root epics + brief_status). The headline number is approximately right but the bookkeeping is loose. |

**Bottom line:** The author was NOT too aggressive in *what* it classified — the green checks are real and I reproduced them. The danger is in *durability* (Finding 1) and in *tooling fragility* that would bite a future run (Findings 2–4).

---

## Task 1 — Did anything archived actually fail its own oracle?

I independently re-ran every archived plan's distinct `verification_command(s)` from the repo root. **Result: all green (or no-command).**

```
GREEN  plan_hooks_brief_reaper.json                    OK
GREEN  plan_hooks_enforcement-integration.json         OK; OK; OK
GREEN  plan_hooks_ov-actions.json                      OK
GREEN  plan_hooks_ov-config.json                       OK
GREEN  plan_hooks_ov-driver.json                       OK
GREEN  plan_hooks_ov-frontend.json                     OK
GREEN  plan_hooks_ov-manifest-routing.json             OK
GREEN  plan_hooks_ov-transcript.json                   OK
GREEN  plan_hooks_ov-web-api.json                      OK
GREEN  plan_hooks_ov-webui-control.json                OK
GREEN  plan_hooks_ov-webui-server.json                 OK
GREEN  plan_hooks_overseer_chat_clear_mode.json        OK
GREEN  plan_hooks_overseer_driver_headless.json        OK
GREEN  plan_hooks_overseer_mode_on_send.json           OK
GREEN  plan_hooks_overseer_session_history_store.json  OK
GREEN  plan_hooks_overseer_web_api_history.json        OK
GREEN  plan_hooks_procedure-substrate.json             OK; OK; OK
GREEN  plan_hooks_runtime-wiring.json                  OK; OK
GREEN  plan_hooks_followup-procedures.json             OK
GREEN  plan_hooks_wire_reaper_worker.json              OK
GREEN  plan_hooks_brief_reaper.json / smoke / symbol_ledger  OK (pre-existing fixtures)
NO-CMD plan_hooks_overseer-webui-frontend.json         (epic decomposition record; see Finding 4)
```

I did NOT find a single archived plan whose oracle is RED/vacuous/trivial. Spot-checking the commands: they point at the genuinely-relevant per-leaf oracle test file (e.g. `ov-actions` → `tests/overseer/test_actions.py`, `ov-manifest-routing` → `tests/adversarial/test_nonpy_manifest_routing.py`). These are real contract tests, not trivial/`assert True` shells. The corresponding integrations also appear in the git log (e.g. `6c6c3dd Integrate validated code for extend-procedure-followup-procedures`, `4b64e84`, `a060fdc`). **No false-positive DONE found among the plan-backed leaves.**

## Task 2 — The "no plan, brief's own oracle green => DONE" branch (regex)

Exactly **one** brief was archived via this branch: `brief_hooks_overseer_driver_stream_parse.md` (it has no `plan_hooks_overseer_driver_stream_parse.json`). I traced the regex:

- `brief_command` pattern 1 = `verification_command["\s:]+["\']([^"\']+)["\']`. On this brief it correctly grabbed line 32: `verification_command: "python -m pytest tests/overseer/test_driver_stream_shapes.py tests/overseer/test_driver.py -q"`.
- I ran that command myself: **`20 passed`**. The brief's intended work (the `run_turn` stream-fold fix) is genuinely integrated. **Correct DONE.**

**But the regex is demonstrably unsafe** — I ran `brief_command` over every root brief:

- `brief_hooks_brief_status.md` → regex extracted `cmd = "..."` (a literal ellipsis, matched out of the brief's PROSE: `verification_command: "..."` appears as an *example* in its own spec text). Had this brief been planless, the classifier would have run `...` (which fails) and marked it NEEDS-PLAN — a *false negative* here, but the symmetric failure (grabbing a stray `python -m pytest <unrelated>` example that happens to pass) would produce a **false-positive DONE on unbuilt work**. Pattern 2 (`first python -m pytest line`) is especially dangerous: many briefs cite example/illustrative pytest invocations in their "Required plan shape" sections that are NOT the real contract.

This branch is a real misfire vector; it only escaped harm this run because the single planless brief that hit it happened to have a clean explicit command.

## Task 3 — The 3 ORPHAN-PLANs and the 2 EPICs

**ORPHAN-PLANs archived:**
- `plan_hooks_followup-procedures.json` — single task `extend-procedure-followup-procedures`, vcmd `test_procedure.py -q` → GREEN; integrated per git log. Benign.
- `plan_hooks_symbol_ledger_module.json` — pre-existing fixture (committed `ecf8f36`), green. Benign.
- `plan_hooks_overseer-webui-frontend.json` — **NOT a leaf plan; it is an epic decomposition record** (`plan_kind:"epic"`, `epic:true`, `child_slugs:["chat-panel-spa-bundle","overseer-webui-chat-layout-styles","overseer-webui-chat-logic"]`, `source_brief_path`, `epic_slug`). The classifier archived it with **zero green check** (ORPHAN-PLAN branch does no `run_green`). Its source brief already lives in two prior archives (`overseer_decompose_prune/`, `2026-06-08_overseer_build_declutter/`), and the chat-panel work landed via the `ov-frontend` leaf (`test_chat_ui.py` → `5 passed`). So **no dangling reference resulted**, but this exposes a design hole: an epic-decomposition plan can be mistaken for an orphan leaf and swept regardless of whether its children are built. If those children had been pending, this would have silently discarded the decomposition record.

**EPICs (correctly left at root, never archived):** `brief_hooks_overseer_chat.md` and `brief_hooks_overseer_procedure_gates.md` — I confirmed `brief_is_epic` returns True for both (frontmatter `epic: true`). Their children were all archived as DONE leaves; the epics dangle no unbuilt child. `brief_hooks_brief_status.md` contains `epic: true` in PROSE (line 34) but `brief_is_epic` correctly scopes to frontmatter and returns False — so it was NOT mis-treated as an epic. Good.

## Task 4 — Did the archival LOSE anything / is it reversible/committed?

**This is the most concrete problem.** The author's claim that it "git-mv'd tracked files" is mostly false in practice:

- The 39 moved root briefs/plans were **untracked at HEAD** (verified `git cat-file -e HEAD:brief_hooks_ov-actions.md` etc. → all "UNTRACKED"). `git mv` rejects untracked files, so the script's fallback `shutil.move` ran for nearly all of them.
- Consequently **37 files in `reconciled/` are `??` (untracked) and UNCOMMITTED**. Only 4 files in that dir are tracked at HEAD (`brief_hooks_smoke.md`, `brief_hooks_brief_reaper.md`, `brief_hooks_wire_reaper_worker.md`, and their plans + `plan_hooks_smoke.json`/`symbol_ledger`), and those were committed back in `ecf8f36`/`11930d2` as **reaper test fixtures**, not as part of this sweep.
- The archive commit `11930d2` added only 4 reconciled files (the two reaper leaves' paperwork). **The other ~35 archived artifacts exist only in the working tree.** A `git clean -fdx`, a fresh checkout, or any worktree reset would erase them with no git history. This is a **durability/data-integrity gap**, not yet an actual loss.

Other checks:
- **No `D` (deleted-not-moved) brief/plan from the sweep.** The lone `D brief_hooks_symbol_ledger_module.md` is unrelated (it moved to `state/control/autowork/quarantine/`, a separate prior action).
- **No name collisions / overwrites detected** in `reconciled/` — but note `shutil.move` would silently overwrite a same-named file, and the script writes `dest/<name>` unconditionally. Re-running `--archive 2026-06-08` is **not safely idempotent**: a second run on a re-created root file would overwrite the archived copy without warning.

## Task 5 — Reaper premature-archival scenario

The reaper (`tools/brief_reaper.py::reap_for_task`) IS guarded against the naive "1-of-N tasks integrated" case: `_all_green` re-runs **every distinct** plan command and reaps only if all exit 0. Wiring is fail-safe (`_print_json_line` → `_reap_spent_briefs_safe`, behind `autowork.archive_spent_briefs` which is now **ON** in `harness/config.yaml:41`).

**The hole:** `_distinct_commands` dedups by command string. Construct a plan with tasks A and B that both declare `verification_command: "python -m pytest tests/x/test_shared.py -q"` (a very common pattern — sibling tasks editing the same module verified by one oracle). When task A integrates, the single deduped command can be green (because the oracle tolerates A's change) even though B is unbuilt → the reaper archives the brief+plan, discarding B's still-pending work. There is **no per-task integration check**, only a per-distinct-command check. This did not fire this run (I verified no archived multi-task plan shares a command), but cross-plan sharing already exists (`followup-procedures` and `procedure-substrate` both use `test_procedure.py`), so the pattern is live in the codebase. Additionally, **transient-green** oracles (flaky/time-dependent) would cause irreversible archival on a single lucky run, since there is no re-confirmation.

## Task 6 — Count cross-check

Archived: **20 briefs** (incl. 1 planless `stream_parse`, + the `smoke` fixture) and **23 plans** (incl. 3 orphans + fixtures). The headline "19 DONE + 2 EPIC + 3 ORPHAN = 0 pending" is roughly consistent but the arithmetic is loose (it omits the `smoke`/`symbol_ledger` fixtures and counts the epic-decomposition orphan as a normal orphan). I re-ran the classifier logic over the union of root + archived briefs and found **no brief that should have been NEEDS-PLAN or PENDING but was archived as DONE.** The two genuinely-pending items still at root are the 2 epics (correct) and `brief_status` itself (DONE, plan-green, simply not yet reaped). So the "ZERO genuinely pending" conclusion is **defensible for this run** — the aggression risk is in the tooling, not in this run's outcome.

---

## Recommendations
1. **Commit the reconciled/ moves** (`git add _autowork_archive/2026-06-08/reconciled && git commit`) — 37 archived files are uncommitted and lost on any worktree reset. (Severity 1.)
2. Harden `brief_command`: only accept an explicit `verification_command:` from inside a fenced/structured "Required plan shape" block; never fall back to the first prose `python -m pytest` line. Reject `...`-style placeholders.
3. In the reaper/classifier, key integration on **per-task** evidence, not per-*distinct*-command; or require each task to map to a non-shared command before reaping.
4. Have the ORPHAN-PLAN branch skip `plan_kind:"epic"` decomposition records (they are not spent leaf paperwork), and refuse to archive an orphan plan whose `child_slugs` are not all themselves DONE.
5. Make `--archive` idempotent: refuse to overwrite an existing destination file; log collisions instead of silently `shutil.move`-overwriting.
