# Overseer-Chat WebUI Build — Continuation Handoff

Compiled 2026-06-08. Mission: finish building the **overseer-chat WebUI epic**
(`brief_hooks_overseer_chat.md`) through JanusMaskJR's gated pipeline, **one leaf
at a time**, token-efficiently, until the interactive chat panel works. The hard
exploration is done and the build recipe is **validated** — do NOT re-derive it.

---

## §0 PASTE PROMPT

Resume building the overseer-chat epic. Read FIRST (in order): THIS file, then the
4 adversarial verification reports in `_autowork_archive/overseer_session_verification/`
(`agent_1_oracle_quality.md`, `agent_2_built_code.md`, `agent_3_repo_state_safety.md`,
`agent_4_decisions_remaining.md`). State: 13 RED oracles committed (`72e8c8c`); 2 of
13 leaves BUILT + oracle-green (`overseer/model_select.py`, `overseer/session_store.py`);
HEAD `b416b36`. The build uses **PINNED LEAF SETS** — never let the daemon freely
decompose (it over-decomposes/duplicates/mis-types every epic). Build ONE leaf at a
time via §3. Before any daemon run do the §3 PRE-FLIGHT (remove `full_stop`, kill ALL
daemons + verify zero, keep `state/tasks/` clean — the daemon dispatches ANY staged
task regardless of the allowlist). Per-leaf contract = the committed oracle. Don't push.

---

## §1 EXACT STATE NOW

- **JM** `/home/xnihil0zer0/JanusMaskJR`, branch master, HEAD **`b416b36`**.
- Two overseer commits on top of the oracle/brief commit `72e8c8c`:
  - `14e1a33` → `overseer/model_select.py` (task `ov-model-select-impl`)
  - `b416b36` → `overseer/session_store.py` (commit msg says "T1" — **benign mislabel**,
    verified: `T1.json` *is* the session_store leaf; the NGv2 `T1_rlcf_export_module`
    is a distinct id that never touched `overseer/`). Both modules verified CORRECT
    (not oracle-gamed) and pass 16/16 oracle tests.
- **13 committed oracles** in `tests/overseer/test_*.py` (the dispatch precondition).
- **Daemon DEAD. `state/control/autowork/full_stop` PRESENT** = durable kill switch.
  **Remove it to allow a run.** Allowlist = `overseer_chat`. (`orchestrator.flag=pause`
  is IGNORED by the daemon — it only honors `autowork/full_stop` + `autowork/pause`.)
- Root plan `plan_hooks_overseer_chat.json`: `child_slugs` = the 6 `ov-` foundation
  leaves (2 built, 4 pending); `_deferred_child_slugs` = the 4 daemon-generated epic
  slugs (their briefs were archived — see §4 reference note).
- **Root decluttered** by `scripts/cleanup_stale_artifacts.py` (re-runnable): 8 briefs
  + 7 plans remain (active overseer + `smoke`/`symbol_ledger`). 52 stale files archived
  to `_autowork_archive/stale_briefs_2026-06-08/` (`MANIFEST.tsv`); 3 confirmed-landed
  fix-plans deleted. NGv2 parked work + overseer reference briefs are in that archive
  (reusable).
- `harness/config.yaml` has **uncommitted** working-tree edits (auto-approve flags OFF
  + `synthesis.accept_single_agent_leaf_plans: true`) — intentional safety posture, do
  NOT revert.
- Nothing pushed. The 2 overseer commits + the oracle commit `72e8c8c` are local-only.

---

## §2 THE VALIDATED BUILD RECIPE — "pinned leaf sets" (do NOT re-derive)

**Why:** the daemon's free epic→leaf decomposition over-decomposes, **duplicates**
(two leaves targeting the same file), and **mis-types** (assigns `io_adapter`, which
runs the Python fuzzer, to a JS edit → `fuzz_error_r1`). Observed on 3/3 epics. It also
structurally decomposes complex tasks into `-loop_0/-conditional_1/...` subtasks. **Pin
every leaf instead.**

For each leaf, author `brief_hooks_ov-<leaf>.md` with a **"Required plan shape"** block
that FORCES, explicitly:
1. **`meta_task_type`** (in frontmatter AND the body) — by location:
   - `overseer/*.py` modules → **`data_model`**
   - `tools/*.py` edits + the frontend (`app.js`/`index.html`/`styles.css`) → **`harness_plumbing`**
   - `harness/config.yaml` → **`harness_self_fix`** (+ operator decision file, see §4)
   These three types **`bypass_fuzzer` + `skip_structural_decomp`** (and `harness_plumbing`/
   `harness_self_fix` also `skip_smoke_gates`) — so no fuzz_error, no structural mangling.
   There is **no `frontend` meta_task_type**; `harness_plumbing` is correct for JS/HTML/CSS.
2. **`files_touched`: exactly one file.**
3. **`verification_command`: an EXPLICIT `python -m pytest tests/overseer/test_<oracle>.py -q`.**
   MANDATORY for EVERY leaf. Oracle-injection (`plan_normalizer._inject_oracle_sources`)
   reads the `.py` token straight out of the `verification_command` and embeds the oracle
   source into the worker's notes. **No explicit vcmd ⇒ the worker builds BLIND.** (This
   especially bites the EDIT leaves + config, whose target basename does NOT match the
   oracle filename, but set it on every leaf.)

Template = §5. Working example = `brief_hooks_ov-modes.md` (already in root).

---

## §3 RESUME PROCEDURE — token-efficient, ONE leaf at a time

**PRE-FLIGHT (every run — these are the landmines that ate this session):**
1. `rm -f state/control/autowork/full_stop`
2. Kill ALL daemons + verify zero: `for p in $(pgrep -f harness.autowork_daemon); do kill -9 $p; done; sleep 2; pgrep -af harness.autowork_daemon || echo zero`
   (Daemon multiplicity bit repeatedly — `scripts/run-autowork.sh` is a respawn supervisor;
   do NOT invoke it. Always confirm ZERO before starting one.)
3. `state/tasks/` must contain ONLY your target leaf's task — **the daemon dispatches any
   staged task file regardless of the allowlist.** `ls state/tasks/*.json` and remove strays.
4. `rm -f state/control/autowork/git_commit.lock`

**BUILD (per leaf):**
5. Set `plan_hooks_overseer_chat.json` `child_slugs` to JUST the target leaf slug.
6. Start ONE daemon: `nohup python3 -m harness.autowork_daemon --state-dir state > /tmp/ov_daemon.log 2>&1 & echo $! > /tmp/ov_pid`
7. Wait for the `overseer/<file>` commit (`git log --oneline`) OR a block/`fuzz_error`/
   `auto_commit_failed` in the log; then **stop the daemon by PID**.
8. Verify: `python -m pytest tests/overseer/test_<leaf>.py -q` (must be green).
9. Recreate `full_stop` if pausing, else go to the next leaf.

**Max-control alternative (no daemon scheduling):** manual-drive a single leaf —
`python3 -m harness.planner.cli brief_hooks_ov-<leaf>.md --output-plan plan_hooks_ov-<leaf>.json`,
then `stage_task`, then `python -m harness.orchestrator_worker --state-dir state --task-id <tid>`.

---

## §4 REMAINING WORK — 11 of 13 leaves (build in this order; deps respected)

**Phase 1 — foundations (4 leaves; briefs + plans ALREADY pinned in root → just build):**
| leaf slug | target | meta_task_type | oracle |
|---|---|---|---|
| `ov-modes` | `overseer/modes.py` | data_model | `test_modes.py` |
| `ov-mode-gate` | `overseer/mode_gate.py` | data_model | `test_mode_gate.py` |
| `ov-mode-prompts` | `overseer/mode_prompts.py` | data_model | `test_mode_prompts.py` |
| `ov-transcript` | `overseer/transcript.py` | data_model | `test_transcript.py` |

**Phase 2 — driver/actions/web_api (author pinned briefs, `data_model`):**
| `ov-driver` | `overseer/driver.py` | data_model | `test_driver.py` — HARDEST (11 tests, injected seams, session_id extraction independent of ClaudeStreamParser) |
| `ov-actions` | `overseer/actions.py` | data_model | `test_actions.py` |
| `ov-web-api` | `overseer/web_api.py` | data_model | `test_web_api.py` — imports `session_store`+`driver`+`actions`, build after them |

**Phase 3 — tools edits (author pinned briefs, `harness_plumbing`, explicit vcmd):**
| `ov-webui-control` | `tools/webui_control.py` EDIT | harness_plumbing | `test_webui_control_overseer.py` |
| `ov-webui-server` | `tools/webui_server.py` EDIT | harness_plumbing | `test_webui_server_tailer.py` |

**Phase 4 — config (`harness_self_fix` + operator decision file):**
| `ov-config` | `harness/config.yaml` EDIT | harness_self_fix | `test_config_overseer.py` |
Owner has **pre-authorized a default-OFF `overseer:` block ONLY**: when the task id exists,
stage `state/control/decisions/<task_id>.json` = approve, then report it.

**Phase 5 — frontend (ONE leaf, NOT three):**
| `ov-frontend` | `app.js`+`index.html`+`styles.css` | harness_plumbing | `test_chat_ui.py` |
Keep it as a SINGLE `harness_plumbing` leaf with explicit vcmd `test_chat_ui.py`. A
multi-leaf split shares one oracle → **deadlock** (no single leaf turns it green). The
test is structural (greps the static files), so one whole-leaf edit satisfies it.

**Phase 6 — Phase-H Playwright UI-fidelity sweep (LAST, live, manual — not a determ. leaf).**

**Reference specs for the unbuilt-leaf briefs** (the daemon already wrote detailed,
correct-surface child briefs before I deferred them — mine them, don't re-invent):
`_autowork_archive/stale_briefs_2026-06-08/` →
`brief_hooks_interactive-driver-and-actions.md` (driver+actions),
`brief_hooks_webui-backend-integration.md` + `overseer-web-api`/`web-api-handlers`/
`webui-control-*`/`webui-server-sse-tailer` (web_api/control/server),
`brief_hooks_overseer-config-block.md` (config). Frontend reference:
`_autowork_archive/overseer_decompose_prune/frontend_deferred/`.

---

## §5 PINNED LEAF-BRIEF TEMPLATE (proven — produced correct `data_model` tasks)

```markdown
---
interfaces: "<one-line public surface, copied from the committed oracle>"
meta_task_type: <data_model | harness_plumbing | harness_self_fix>
---

# Title
overseer/<module>.py   (or: EDIT tools/<file>.py)

# Scope
Build the NEW single-file, whole-file, stdlib-only module overseer/<module>.py
IMPL-only against its pre-committed RED oracle tests/overseer/test_<oracle>.py.
The committed oracle is AUTHORITATIVE — reproduce the exact public surface it
imports. <2-4 sentences of behavior from the oracle/brief.>

# Required plan shape
Emit EXACTLY ONE task (do NOT decompose / split into subtasks):
- meta_task_type: <type>
- files_touched: ["<the one file>"]
- verification_command: "python -m pytest tests/overseer/test_<oracle>.py -q"
- spec_author: null
- IMPL-only: the oracle is a pre-committed precondition — author/edit NO test;
  touch no other file. (EDIT leaves: ADD new methods, do NOT modify existing
  method bodies — never-patch-class-methods.)

# Non-Goals
No agent spawn / subprocess / model call / SSE / network. Stdlib only. No other files.

# Inputs
The committed oracle tests/overseer/test_<oracle>.py is the contract.

# Deliverables
<file>, GREEN under `python -m pytest tests/overseer/test_<oracle>.py -q`.
```

---

## §6 LANDMINES (from the 4 verification agents — read before running)

1. **Stale-task auto-dispatch** — the daemon builds ANY task file in `state/tasks/`
   regardless of the deny-all allowlist (allowlist only gates *brief* promotion). Keep
   `state/tasks/` empty of non-target tasks. (Caused stray NGv2 `T1`/`T1_rlcf` builds.)
2. **Daemon multiplicity** — never leave stragglers; kill by `pgrep` + verify ZERO.
   `scripts/run-autowork.sh` respawns the daemon (auto-clears `supervisor.stop`, honors
   `full_stop`). Don't invoke it; keep `full_stop` until you deliberately build.
3. **Every brief needs an EXPLICIT pytest vcmd** (oracle-injection reads it). No vcmd ⇒ blind build.
4. **Frontend = ONE `harness_plumbing` leaf**, not split (shared `test_chat_ui.py` deadlock).
5. **config.yaml leaf** needs an operator decision file (owner pre-authorized default-off only).
6. **`test_chat_ui.py` has no brief route yet** (intentional defer) — author the Phase-5 brief.

---

## §7 OPTIONAL HARDENING (agent findings — non-blocking, do NOT rebuild for these)

- **Oracles (agent 1, 5 minor):** P1 `test_driver` `--tools` check is a whole-argv
  substring (`all(tool in joined)`) — tighten to assert the value *after* `--tools`.
  P2 `test_driver` doesn't pin the driver→`_build_agent_env`/`build_jail_argv` production
  wiring (permissive fakes). P3 weak 1-char tier substring in `test_mode_prompts`; add
  `overseer/__init__.py`; `test_actions` only asserts "some seam fired."
- **Built code (agent 2):** `session_store` `_save` is a non-atomic full-file rewrite
  with no flock (corruption risk only under the dual-daemon condition, now prevented);
  `_load` raises on malformed JSON. Harden in a later pass.
- **Fact correction:** the mode registry is **14 modes** (3R/6W/5S), not 13. The oracle
  is internally consistent at 14; the older MEMORY note saying "13" is stale.

---

## §8 ARTIFACT INDEX

- Committed oracles: `tests/overseer/test_*.py` (13).
- Built modules: `overseer/model_select.py`, `overseer/session_store.py`.
- Active pinned briefs/plans: `brief_hooks_ov-*.md` (6), `plan_hooks_ov-{modes,mode-gate,mode-prompts,transcript}.json`, `plan_hooks_overseer_chat.json`.
- Verification reports: `_autowork_archive/overseer_session_verification/agent_{1,2,3,4}_*.md`.
- Cleanup script (re-runnable, dry-run by default): `scripts/cleanup_stale_artifacts.py`.
- Archived reusable material: `_autowork_archive/stale_briefs_2026-06-08/` (+ `MANIFEST.tsv`),
  `_autowork_archive/overseer_decompose_prune/` (pruned epics + deferred frontend).
- Root epic brief (the full spec, 14 modes, all leaves): `brief_hooks_overseer_chat.md`.
