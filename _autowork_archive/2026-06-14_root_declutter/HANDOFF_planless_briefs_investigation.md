# HANDOFF — Investigate, update, and (where useful) build the 3 plan-less briefs

**Date authored:** 2026-06-08 · **Repo:** `/home/xnihil0zer0/JanusMaskJR` · **HEAD at authoring:** `6e97b69`
**Author context:** written right after the `overseer_procedure_gates` epic was fully built (252-test overseer suite green). The repo advanced *concurrently* while that ran — read the coordination warning FIRST.

---

## 0. Your mission

Three root-level briefs have no `plan_hooks_<stem>.json`:

1. `brief_hooks_agent_exec_substrate.md`
2. `brief_hooks_overseer_chat.md`
3. `brief_hooks_overseer_procedure_gates.md`

For EACH: (a) investigate what it is, (b) determine its **true build status** against the *current* tree (a missing `plan_hooks_*.json` does NOT mean "unbuilt" — two of these are epics whose work already landed), (c) update the brief to reflect reality, and (d) push any genuinely un-built, still-useful feature it contains through the pipeline — oracle-first, owner-gated. **Do not assume; verify every claim against the code and git log**, because the tree is moving.

---

## 1. ⚠️ COORDINATION WARNING — READ BEFORE TOUCHING ANYTHING

A **second session (or a running daemon) is actively building `agent_exec_substrate` right now.** Evidence at authoring:
- `git log 6c6c3dd..HEAD` shows ~28 commits I did not make: a `brief_reaper`/`brief_status`/archive-on-integrate subsystem, an `mcp-wire` overseer-MCP-spawn epic (`35054e5`), and **Pillar A `claude-tmux`** (`tmux_session.py` `9aef1ef`/`7cddeed`, `tmux_transcript.py` `3a09d3e`/`8319051`, `tmux_driver.py` `1a0e146`/`80b49a7`, seam oracle `6e97b69`).
- `state/impl_progress.jsonl` last event = **`task_claim overseer-tmux-seams`** — a leaf was claimed and is in flight.
- `tests/overseer/test_tmux_chat.py` and `test_tmux_seams.py` **error on collection** (import not-yet-built symbols) — those are the next leaves' RED oracles, impl pending.
- A **`webui_server` is running** (PID seen at authoring `4009529`, `127.0.0.1:8765`).

**Therefore:**
- **Do NOT dispatch builds against `agent_exec_substrate` leaves** (`overseer-tmux-*`, `agy_pool`, the driver/turn_runner `claude-tmux` wiring) without first confirming no other worker/daemon is active. Check: `pgrep -fa "orchestrator_worker|autowork_daemon"`, and `tail state/impl_progress.jsonl` for activity newer than a few minutes.
- **Re-read `git log` at the START of your session** — HEAD will have moved past `6e97b69`. Recompute build status from the *current* HEAD, not from this document's snapshot.
- If the daemon is running and dispatching, your job for `agent_exec_substrate` is likely **observe + analyze only** (update the brief, file a status note) — let the active owner finish. Focus your build energy on the other two briefs and on anything the active session is NOT touching.
- Don't kill the `webui_server` — the operator may be live-testing.

---

## 2. Current-state snapshot (verify, then trust your own re-check)

```
HEAD (authoring):        6e97b69  (will have moved — re-run `git log --oneline -15`)
Posture:                 full_stop PRESENT · orchestrator.flag=pause · allowlist deny-all   (LOCKED)
Live JM procs:           webui_server only (no worker/daemon at the instant of authoring — but a leaf was mid-claim)
overseer/ modules:       actions driver gates mode_gate model_select mode_prompts modes
                         procedure procedure_hook procedure_state service session_store
                         transcript turn_runner web_api  +  tmux_driver tmux_session tmux_transcript
Unpushed commits:        many (origin/master far behind — confirm with `git rev-list --count origin/master..master`)
```

**KNOWN FAILURE to investigate (do this early):**
`tests/overseer/test_config_overseer.py::test_overseer_block_exists_and_is_default_off` **FAILS** at authoring (suite was 293 passed / 1 failed, ignoring the two mid-build tmux oracles). This asserts the `overseer:` block in `harness/config.yaml` is present and **default-OFF**. A failure means someone turned the overseer ON (plausibly for live webui testing) or a concurrent edit broke the invariant. **Determine which:** `git log -p -- harness/config.yaml | head -80` and read the test. If it was an intentional live-test toggle, note it; if it's a regression, it must be fixed (config change → pipeline, `meta_task_type: config_schema`/`data_model`) and the default-OFF posture restored. Do not silently leave a default-ON overseer.

---

## 3. Per-brief dossier

### 3a. `brief_hooks_overseer_procedure_gates.md` — ✅ BUILT (verify, then likely just push)
- **What:** the gated-procedure state machine (deterministic per-mode phase FSM with hard blocks). `epic: true`.
- **Status:** **fully built in the prior session.** Substrate `overseer/gates.py`/`procedure.py`/`procedure_state.py`, enforcement edits to `can_switch`/`dispatch_action`/`render_mode_context`, runtime `turn_runner` per-turn loop + `procedure_hook.py`, plus follow-ups (daemon-supervisor procedure + RED-first oracle-author). Epic record: `plan_overseer_procedure_gates_epic.json`. Memory: `[[overseer-procedure-gates-epic]]`.
- **Action:** Verify green (`python -m pytest tests/overseer/test_gates.py test_procedure.py test_procedure_state.py test_procedure_hook.py test_mode_gate_sequence.py -q`). **Update the brief** to mark it BUILT (add a `# STATUS: BUILT (<commits>)` block) so it stops reading as pending. No new build expected. The decomposed child briefs were already cleaned/archived — fine.
- **Gap to consider (optional, useful):** the per-turn `gate_runner` seam is injected but there is **no default production gate-runner** that resolves a phase's gate-label → a real `gates.py` function and gathers its inputs. If you want the procedure machine to actually self-advance in the live overseer (not just when a caller injects a runner), that resolver is the one genuinely-useful un-built piece. It would be a single new leaf (`overseer/gate_runner.py` + oracle) — but confirm with the owner before building, and confirm `agent_exec_substrate` isn't about to rewrite `turn_runner` under you.

### 3b. `brief_hooks_overseer_chat.md` — ✅ LARGELY BUILT (investigate the recent edit)
- **What:** the interactive multi-turn overseer chat panel + mode system. `epic: true, child_epics: true`. The original large epic.
- **Status:** the foundation + all listed leaves are built (`transcript`, `driver`, `actions`, `web_api`, `webui_control`, `webui_server` tailer, `config` block, `chat_ui` frontend), plus the later fixes (`driver_stream_fold` no-output fix, mode-on-send, clear/session-history). **But the brief was MODIFIED recently** (git shows ` M brief_hooks_overseer_chat.md`, grew to ~35KB). Someone changed its scope.
- **Action:** **`git diff -- brief_hooks_overseer_chat.md`** (and `git log -p`) to see what was added — that delta is the only candidate for new work. Map each leaf's `→ test_<x>.py` to whether that oracle exists and passes. Anything in the modified brief with NO corresponding committed module/oracle is a real candidate; everything else is done. Update the brief's "ALREADY BUILT" section to match reality, then build only the genuine remainder via the pipeline.

### 3c. `brief_hooks_agent_exec_substrate.md` — 🚧 ACTIVELY BUILDING (Pillar A in flight; Pillar B not started)
- **What:** subscription-billed interactive backends + isolated parallelism. `epic: true, child_epics: true`. **Two pillars:**
  - **Pillar A — `claude-tmux` backend** (in `overseer/`): drive a persistent *interactive* claude in a tmux pane (Max-subscription billing, not metered `-p` API), read replies from the structured session-transcript JSONL (no TUI scraping), idle-detect via `capture-pane` (`esc to interrupt` present⇒busy), isolate per-agent via `CLAUDE_CONFIG_DIR`.
  - **Pillar B — agy worker pool** (`harness/agy_pool.py` + gated `orchestrator.py`/`autowork_daemon.py`/`config.yaml` wiring): a project-local pool of N isolated agy `HOME`s so up to 4 build/research workers run concurrently without corrupting `~/.gemini`/`~/.codeium`/`~/.antigravitycli`. Overseer is **exempt** (keeps the main system agy).
- **Status (authoring):** Pillar A substrate **built** — `tmux_session.py`, `tmux_transcript.py`, `tmux_driver.py` (with passing oracles). The **next leaves are in flight** by the concurrent owner: `overseer-tmux-seams` (claimed) and the `claude-tmux` wiring into `driver.run_turn` + `turn_runner.make_tmux_seams` + per-cid `CLAUDE_CONFIG_DIR` seeding (`driver.py`/`turn_runner.py` show NO `tmux`/`claude-tmux` yet). **Pillar B (agy pool) not started.**
- **Action:** **Coordinate first (§1).** If the owner is active, limit yourself to: (i) re-read the brief's "Verified facts" + "Edge Cases" + Deliverables, (ii) produce an accurate status note of which leaves are done/in-flight/todo, (iii) update the brief's grouping if the real tree diverged. **Only if the owner is idle** and the owner-operator approves: digest the remainder (it's `child_epics: true`, so `planner.cli` decomposes into child epics) and build Pillar B and any unbuilt Pillar A wiring, oracle-first. **Pillar B touches deny-listed files** (`harness/orchestrator.py`, `harness/autowork_daemon.py`) → those leaves are `meta_task_type: harness_self_fix` and require an **operator decision file** (`state/control/decisions/<task_id>.json`), not plain auto-commit.

---

## 4. Investigation methodology (apply per brief)

1. **Re-baseline:** `git log --oneline -20`; `git status`; `pgrep -fa "orchestrator_worker|autowork_daemon"`; `tail -5 state/impl_progress.jsonl`.
2. **Frontmatter tells the type:** `epic: true` ⇒ it was meant to be *digested* (decomposed) — its "plan" is a `plan_*_epic.json` record + child briefs, NOT a `plan_hooks_<stem>.json`. A leaf brief's plan IS `plan_hooks_<stem>.json`. So "no plan_hooks" is expected and harmless for an epic.
3. **Map brief → contract → module:** each leaf names a `→ tests/overseer/test_<x>.py` and a target module. Build status = "does that module exist at HEAD AND does its oracle pass?" Run the named oracle. Cross-check `git log --oneline -- <module>`.
4. **Decide per-feature:** BUILT (module+oracle exist, green) / IN-FLIGHT (oracle committed RED, no impl, recent `task_claim`) / TODO (no oracle, no module). Only TODO (and genuinely useful) items get built.
5. **Update the brief in place** with a `# STATUS` block enumerating BUILT/IN-FLIGHT/TODO with commit SHAs, so the next reader doesn't re-investigate from zero. (Briefs are operator artifacts — hand-editing them is fine; only *production code* must go through the pipeline.)

---

## 5. The pipeline recipe (proven this project — follow exactly)

**Driving philosophy:** oracle-first, deterministic, owner-gated. NEVER hand-edit production outside the pipeline ([[never-hand-edit-production-outside-pipeline]]); only oracles/tests/briefs/plans may be hand-authored.

**Per leaf:**
1. **Hand-author the RED oracle(s)** under `tests/overseer/` (or the relevant dir). Pin the EXACT public surface; use injected seams (no real spawn/network/model). Run them — **confirm RED for the right reason** (ImportError or contract mismatch, not a typo).
2. **`git commit` the oracle BEFORE dispatch.** The gate's post-commit verification runs from HEAD in a staging worktree — *uncommitted oracles are invisible and the build rolls back.* (Lesson #1.)
3. **Generate the plan:** `python -m harness.planner.cli brief_hooks_<stem>.md --output-plan plan_hooks_<stem>.json` (LLM, ~5 min; for a `child_epics`/`epic` brief it instead writes child briefs + a `plan_*_epic.json`).
4. **SALVAGE the impl tasks** (the planner emits *separate* `test_authoring` + impl tasks with weak `python -c "import ..."` verification and NO injected oracle). For each impl task: discard the oracle-authoring tasks (you already committed the oracles); set `verification_command` to your committed oracle (add the existing oracle too, for regression coverage on edits); set `meta_task_type: data_model` (bypass_fuzzer + skip_structural_decomp — the proven path for pure/edit leaves); fix `dependencies`; then call `harness.planner.plan_normalizer._inject_oracle_sources(plan, repo_root='.')` to embed the committed oracle as the blind worker's contract. Validate: `harness.planner.plan_validator.validate_plan(path)` must return NONE.
   - *Hand-building a one-task plan?* Clone a previously-validated task as the schema template (the validator requires `title`/`acceptance_criteria`/`spec.interfaces`/`test_spec.{unit_tests,integration_tests,minimum_test_count,...}`/`token_budget_ratio.*`/`attribution_metadata.*`/integer `priority`), then override `task_id`/`files_touched`/`verification_command`/`spec`, and `_inject_oracle_sources`.
5. **Stage + build (controlled, no daemon):** `staging.stage_task(Path(plan), task_id, Path('state'), canonical=True, working_dir='<repo>')` then `python -m harness.orchestrator_worker --state-dir state --task-id <id> --config harness/config.yaml`. The single-task worker **does NOT consult `full_stop`/allowlist** (those gate the daemon) — so the safe posture stays locked throughout. Build in dependency order; each auto-commits to HEAD so the next leaf sees it.
6. **Watch** `state/impl_progress.jsonl` for the task's `accepted`/`auto_commit` (success) or `rejected`/`verification_failed`/`task_blocked` (failure).
7. **On a non-deterministic miss** (worker made a reasonable-but-wrong choice, e.g. kept an old signature): (a) **clean ALL stale state** for the id — `find state -name '*<task_id>*' -exec rm -f {} \;` (sidecars `state/output/<id>.patches.json`/`.py` take precedence over a re-stage and will replay the bad submission — the stale-sidecar gotcha [[stale-sidecar-precedence-gotcha]]); (b) **harden the plan's `implementation_notes`** with the exact signature/contract; (c) re-stage + re-dispatch.
8. **Verify:** named oracle green + full suite 0 new regressions.

**Build-shape rules:** NEW module ⇒ single-file whole-file. EXISTING symbol ⇒ symbol patch (worker reads the staged source). NEW top-level symbol ⇒ R-anchor via implementation_notes (ride as a trailing node of an existing symbol's patch). New class method ⇒ force whole-file emission (can't symbol-patch a new 2-part qualname). Editing a module-level constant ⇒ prefer whole-file. ONE file per leaf — multi-file emission is fragile. Unique descriptive `task_id` (NEVER `T1` — it collides with `state/tasks/processed/T1.json`).

**Deny-listed paths** (`harness/**`, daemon, etc.) ⇒ `meta_task_type: harness_self_fix` + an operator decision file `state/control/decisions/<task_id>.json` (approve) — plain auto-commit is refused. Pillar B of `agent_exec_substrate` is in this class.

---

## 6. Safety posture — keep it, restore it

- **Confirm before building** that posture is locked: `full_stop` present, `state/control/orchestrator.flag` = `pause`, allowlist deny-all. The single-task-worker path I recommend ignores these anyway, but they stop the daemon from racing you.
- **Never flip an enable flag** (overseer `enabled`, daemon allowlist, concurrency) without explicit owner sign-off. The `test_config_overseer` default-OFF invariant (§2) is part of this — leave the overseer default-OFF when you're done.
- **After building:** `full_stop` present, `flag=pause`, allowlist deny-all, no daemon/worker left running; full overseer suite 0-reg; report unpushed commit SHAs (push only on owner sign-off).
- **Don't disturb the running `webui_server`** or any concurrent worker.

---

## 7. Recommended order of attack

1. Re-baseline (§4.1) + resolve the **`test_config_overseer` default-OFF failure** (§2) — it's a posture/regression issue and quick.
2. **`overseer_procedure_gates`**: verify built, stamp a `# STATUS: BUILT` block on the brief. (~10 min, no build.)
3. **`overseer_chat`**: `git diff` the brief, map leaves, stamp status, build only the genuine remainder (likely little/none). 
4. **`agent_exec_substrate`**: **coordinate first.** If the owner is active → observe, status-note, update grouping. If idle + owner-approved → digest the remainder and build Pillar B (agy pool, harness_self_fix + decision files) and any unbuilt Pillar A wiring, oracle-first.
5. Restore posture; report SHAs; propose push.

**Memory to read first:** `[[overseer-procedure-gates-epic]]` (the exact salvage/inject/harden recipe, proven), `[[overseer-chat-fix-features-session]]` (autonomous-loop gotchas), `[[never-hand-edit-production-outside-pipeline]]`, `[[stale-sidecar-precedence-gotcha]]`.
