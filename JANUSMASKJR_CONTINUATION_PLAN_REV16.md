# JanusMaskJR — Continuation Plan (2026-06-01, rev 16)

> **rev 16 — written after the rev-15 Phase-1 pipelineable scope was fully executed (16 dual-agent landings,
> 0 hand-edits, pushed to `origin/master` @ `bc338b3`) and then adversarially re-reviewed by a 4-agent
> Antigravity/Gemini panel (reports in `~/janusmask_briefs/review_rev16/R{1..4}_*.md`).**
> Supersedes `JANUSMASKJR_CONTINUATION_PLAN_REV15.md`. **Governing rule (owner directive, carried):** use the
> PIPELINE for every change wherever possible; HAND-EDIT only after a pipeline attempt fails with a PERMANENT
> blocker (never a timeout, never a re-groundable verification failure).
>
> **Verification discipline:** every file:line anchor below comes from the rev-16 Gemini panel at HEAD
> `bc338b3` and MUST be re-verified against live code before action (Gemini anchors drift). This plan will be
> adversarially re-reviewed by Claude agents next session; trust the verdicts only after that re-verification,
> exactly as rev-15 did with its panel.
>
> **Read this first (state):** master HEAD `bc338b3`, synced to `origin/master`. All of rev-15 Phase-1's
> *pipelineable* scope is CLOSED via the pipeline (16 landings). Full suite **6315 passed / 5 failed** (the 5
> are PRE-EXISTING and == the two deferred cleanup items below; **zero new regressions** — panel R1/R2
> confirmed). Hard invariants intact (R4): `synthesis_success = True` ×1 each, `skip_interface_fuzz` on
> `test_authoring` only, `BYPASS_FUZZER_TYPES` underived/unnarrowed, `_SENSITIVE_APPLY_GLOBS =
> ('harness/**','config/**','scripts/**')`, `state/control/**` jail-ro, **`full_stop` PRESENT**. Phase A (lift
> `full_stop`) remains **OWNER-ONLY** and was not done.

---

## 0. Landed via PIPELINE this session — VERIFIED by panel R1 (do not re-do)

All dual-agent, oracle committed RED-first, §1b per-task where harness/**, tree byte-checked. R1 confirmed **no
dropped changes** across the SEVEN `_auto_commit_accepted` whole-symbol replaces and **no vacuous oracles / no
weakened boundaries**.

| Commit | Item | Closes | Note |
|--------|------|--------|------|
| `a625ef2` | PARITY-1 | interceptor⊆enforcer | `except_exception_pass` ERROR→WARNING (services/+tests/, no §1b) |
| `e676894` | SEC-2 | jail bind fragility | `_auto_commit_accepted` extra_ro=[base_prefix, **sys.prefix**] |
| `3ce3d9e` | C2/ROLLB-A | concurrent staging collision | `{name}_{task_id}_staging` |
| `ce79bba` | C6/H3 | retry budget | ast_retry HARD = `synthesis_timeout*2+300` |
| `74793e0` | AGY2A | zombie (spawn_agent) | guarded `proc.kill()`+`proc.wait(5)` |
| `1321fe5` | AGY2D | watchdog kills retriers | `max(1800, 2*timeout+600)` + 2 test updates |
| `fa7fe35` | ATEST-STDERR | A-TEST non-vacuity | +EROFS/EACCES stderr asserts (still 7/7) |
| `f8dce2b` | SEC-4 | fuzz stdout spoof | `_exec_module` driver `redirect_stdout(sys.stderr)` |
| `70afe30` | MUT-MASK | vacuous-test accept | baseline-in-copy guard (infra-fail ≠ "caught") |
| `34c32d7` | ESCMOCK_B | §3 (2 of 5) | escalate missing/corrupt task_json (fuzz-log) |
| `265fa84` | SEC-5a | jail rw allowlist | `build_jail_argv(extra_rw=())`; `run_embedded_tests` reads cfg |
| `fb73017` | SEC-5c | (cont.) | `_auto_commit_accepted` reads cfg `verify_extra_ro/rw` |
| `5dfe936`/`74bab10`/`800645b`/`bc338b3` | SEC-3 SMOKE/FUZZ/ORCH/EMBEDDED | fail-closed (4 sites) | sandbox-enabled+bwrap-absent → reject cleanly, never unjailed/crash |

**REFUTED (do NOT touch — panel R2 re-confirmed):** REV15 §2 rows **G-METADATA / G-UNTRACKED / C4-ROLLB-C** are
already-landed, deliberate, **test-locked** behavior (prune-order @3d553e2; stash-drop M2/M3 w/
`test_phase_m_dropped_stash_is_logged_for_audit`; ROLLB-C checkout = defense-in-depth w/
`test_rollback_worktree_checkout.py`). Dispatching would REVERT safety features. **Struck from this plan.**

---

## 1. Panel findings — NEW items the rev-16 review surfaced (verify-first, then fix)

| # | Finding (panel) | Sev | Route |
|---|-----------------|-----|-------|
| **VALIDATOR-SIG** (R4) | Partial-edit validator applies a task's `declared_signature` to **every** patch block (`orchestrator.py:~1097` → `validate_code(blk, declared_signature=...)`), so any patch whose symbol ≠ the signature's function fails `return_type_mismatch: function 'F' not found`. Real bug; blocks 2+-symbol partial edits that declare a signature (cost a re-dispatch this session). | HIGH | **PIPELINE** — only pass `declared_signature` to the patch entry whose `name` matches the signature's function (parse func name via `_extract_func_name_from_signature`). |
| **KILL-REAP** (R4) | `kill_agent` (`orchestrator.py:~446`) calls a final `proc.wait(timeout=3)` **not** wrapped in try/except, inside `run_agent_phase`'s `finally` → a stuck child raises `TimeoutExpired` that bubbles up and crashes the run loop. (Distinct from AGY2A's spawn_agent fix.) | MED | **PIPELINE** — wrap in `except (TimeoutExpired, ProcessLookupError, PermissionError, OSError)`. |
| **MUT-HARNESS-ISO** (R1) | `tests/adversarial/test_P2_mutation_kill.py` mutates LIVE hook files in place (e.g. `harness/hooks/claude/post_tool.py`); concurrent/ interrupted runs race and can leave the tree dirty (this is the source of the transient `config.yaml`/hook stat-cache noise seen all session). | MED | **PIPELINE** — copy hook files into a task-scoped tmp/worktree and mutate the copies (mirror the mutation-gate pattern). |
| **BWRAP-PATH-MOCK** (R1) | Several oracles mock `shutil.which` → hardcoded `/usr/bin/bwrap` (e.g. `test_sec5_verify_extra_binds.py`, `test_sec2_jail_extra_ro_prefix.py`); brittle/vacuous on hosts where bwrap lives elsewhere. | LOW | **PIPELINE** — resolve the real `shutil.which('bwrap')` in the mock. |
| **SEC-1 (confirmed PoC)** (R3) | Jailed agent reaches `<XDG>/bus` (bound rw for OAuth) → `org.freedesktop.systemd1.Manager.StartTransientUnit` starts an **un-jailed host process**. R3 gave a working `dbus.SessionBus()` PoC. bwrap doesn't unshare IPC/PID. | HIGH | **HAND-EDIT** after a pipeline-attempt demo — needs an `xdg-dbus-proxy` sidecar (new subprocess + socket lifecycle). |

**Panel verdicts on already-known items:** R1 — 16/16 landings correct, oracles non-vacuous, boundaries intact.
R3 — bwrap write-boundary **sound**; SEC-3 all four sites **verified fail-closed**; SEC-4/SEC-5 verified. R4 —
all five cross-cutting invariants **intact**; the function-local-class applier limit (FAKEPOPEN file-2) is a
**real permanent blocker**.

---

## 2. Phase-A / daemon-enable gating (panel R3 verdict)

- **Minimal set that MUST land before `rm full_stop` for AUTONOMOUS daemon operation:** SEC-3 ✅, MUT-MASK ✅,
  C2/ROLLB-A ✅, C5/AGY2D ✅ (all landed) **+ C13/H-WORKER-DAEMON (NOT landed — hand-edit; the one remaining
  gating item)**.
- **SEC-1** is **non-gating for the OWNER-SUPERVISED single foreground Phase-A run** (operator monitors the bus
  vector) but is **REQUIRED before UN-monitored autonomous runs**. KILL-REAP and MUT-HARNESS-ISO are
  daemon-stability hygiene (strongly recommended before un-attended operation).
- **Phase A itself (OWNER-ONLY, unchanged):** `pytest tests/adversarial/test_phase_a_selfheal_jail_writedenial.py
  -v` on the owner host; confirm the bwrap-flip mutant → **failures, not skips** (now also asserts EROFS/EACCES
  stderr); owner go/no-go; `rm state/control/autowork/full_stop`. **Do NOT automate.**

---

## 3. Ordered next steps — PIPELINE-FIRST

Each pipeline item: Gemini drafts brief (`agy` — abs paths + `--add-dir`; no `--model`) → Opus sub-agent
adversarially reviews/corrects vs live code, verifies oracle RED-on-HEAD, confirms repo CLEAN → overseer
ingests, commits oracle RED-first, self-approves §1b (harness/**), runs
`.venv/bin/python -m harness.orchestrator_worker --state-dir state --task-id <ID>`, verifies
(`{"skipped":"not_found"}` + integrate commit + both submissions + invariants + targeted suite). Apply the
**carried pipeline lessons** in `~/janusmask_briefs/PATCH_CONVENTIONS.md` (#1-#8): harness_self_fix commits
claude (both must AST-validate); nested-method patch code at **col-0**; gemini **truncates long multi-patch
sums** (≤3 patches / isolate big functions); **2+-symbol taskspecs must OMIT `function_signature`/`interfaces`**
until VALIDATOR-SIG lands.

**Phase 1 — pipeline-viable (do first; ordered):**
1. **VALIDATOR-SIG** — fix `_validate_submission` so `declared_signature` is applied only to the matching patch.
   Do FIRST: it removes the omit-the-signature workaround and unblocks all future multi-symbol partial edits.
   (`services`? no — `harness/orchestrator.py`, §1b.)
2. **KILL-REAP** — guard `kill_agent`'s final `proc.wait(timeout=3)` (single-symbol `harness/orchestrator.py`, §1b).
3. **ESCMOCK GROUP-A** (3 tests) — scoped `builtins.open` side_effect (route only `config.yaml` to the mock,
   delegate the rest to real `open`) so the degenerate-escalation guard isn't tripped; for the dotted
   class-method `TestAutoworkEscalation.test_escalate_to_autobrief_safe_loads_config` the patch `code` MUST
   include its `@patch` decorators at col-0 (or replace the whole class) — last attempt dropped them. tests/**,
   no §1b. PIPELINE.
4. **FAKEPOPEN file-1** — add `communicate(self, input=None, timeout=None)->('','')` to module-level `_FakePopen`
   in `tests/adversarial/test_agent_isolation.py` (fixes that test via inheritance). tests/**, no §1b. PIPELINE.
5. **MUT-HARNESS-ISO** — isolate `test_P2_mutation_kill.py` mutations into a tmp copy (tests/**, no §1b). PIPELINE.
6. **BWRAP-PATH-MOCK** — de-hardcode `/usr/bin/bwrap` in the affected oracles (tests/**, no §1b). PIPELINE.

**Phase 2 — hand-edit ONLY after a pipeline attempt fails with a permanent blocker:**
7. **FAKEPOPEN file-2** — `_P` is a **function-local class** in `test_spawn_cwd_and_prompt_isolation.py:~45`;
   `_apply_symbol_patch` cannot resolve it (PERMANENT BLOCKER, R2+R4 confirmed). Demonstrate via a pipeline
   attempt, then hand-edit: add `communicate` to `_P` (or hoist `_P` to module level). tests/**, no §1b.
   *(Alternative pipeline route to try first: a whole-file `partial_edit:false` submission of that test file.)*
8. **C13/H-WORKER-DAEMON** — suspended (SIGSTOP) workers count wall-time vs the monotonic budget
   (`orchestrator_worker.py:~244`). **The one remaining MINIMAL daemon-gating item.** Attempt pipeline → expect
   permanent blocker (cross-process signal/budget restructure) → hand-edit. §1b.
9. **SEC-1** — `xdg-dbus-proxy` sidecar filtering the session bus to `org.freedesktop.secrets`, blocking
   `org.freedesktop.systemd1` (`agent_jail.py:~239-245`). Attempt pipeline → permanent blocker (new subprocess +
   socket lifecycle) → hand-edit. **MUST re-run the agy-auth smoke (`~/janusmask_briefs/agy_jail_smoke.py`) after
   and revert if agy auth breaks.** §1b.
10. **C3/ROLLB-D** (try/finally over the whole `_auto_commit_accepted` body — ~360-line reindent),
    **C1/ROLLB-E** (13 non-contiguous `_mark_processed` sites in `run_pipeline`),
    **R-anchored-patch** (new splicer in `git_integration._apply_symbol_patch:~939` to add module-level
    imports/sub-symbols — bootstrap-sensitive). Each: attempt pipeline first to demonstrate the permanent blocker.
    **R-anchored-patch, if landed, would convert several Phase-2 hand-edits into pipeline-viable work** — high
    leverage but self-referential/risky.

**Phase A (OWNER-ONLY):** see §2.

> **Sequencing note:** Items 1-2 + 8 + 10 all edit `harness/orchestrator.py` (different functions) — run serially
> and re-ground each against the prior HEAD; workers run SERIALLY regardless (global staging path is now
> task-scoped per C2, but only one foreground worker is run at a time). ESCMOCK-A is the only one likely to need
> a re-ground (decorator handling).

---

## 4. Invariants carried through EVERY phase (do-NOT)

- Never single-agent / lone-candidate acceptance: `grep -c "synthesis_success = True"` == 1 per file. HALT on
  mismatch. (Bypass route: claude is sole *author*, gate syntax intact, §1b is the human backstop.)
- Never narrow `BYPASS_FUZZER_TYPES`; `test_authoring` stays `bypass_fuzzer:False`; `skip_interface_fuzz` only on
  `test_authoring` (`grep -c` == 1). `_SENSITIVE_APPLY_GLOBS` unchanged.
- Keep submit-time AST interceptor ⊆ commit-time enforcer (the PARITY-1/H-INT class).
- agy-backed agents route submission via STDIN; never argv `-p`+file-write in the jail. agy is NOT tree-isolated
  → after ANY agy run: `repo_snapshot.sh` + verify byte-identical + revert drift. **Known benign nuisance:** an
  external process re-emits `harness/config.yaml` with comments stripped (values identical) — restore with
  `git checkout HEAD -- harness/config.yaml` (root cause = MUT-HARNESS-ISO item 5; fixing it removes the noise).
- Never add `*_fix`/any `<task>_fix` to the allowlist. `full_stop` stays present until owner-gated Phase A. §1b
  (`_apply_approval_granted`) is the autonomous-commit boundary; `meta_task_type`/`mutations`/`mutation_target`
  read ONLY from the jail-ro task spec. Mutation-gate fail-closed semantics unchanged. Agents tree-isolated ONLY
  via the bwrap jail.

---

## Appendix — anchors (panel-reported @ `bc338b3`; RE-VERIFY before use)

- `harness/orchestrator.py`: `_validate_submission` per-patch declared_signature **:~1097** [VALIDATOR-SIG];
  `kill_agent` final wait **:~446** [KILL-REAP]; `_auto_commit_accepted` staging **:~1688**, jailed binds
  **:~1812/1937/1961/1975**, SEC-3 verify catch **:~1832-1852**, MUT-MASK baseline-in-copy **:~1922-1941**,
  body span for ROLLB-D **:~1694-2062**, ROLLB-E `_mark_processed` sites in `run_pipeline` **:~2304-2454** + **:2023**;
  four-gate `synthesis_success = True` **:2298** (×1).
- `harness/orchestrator_worker.py`: `synthesis_success = True` **:309** (×1); monotonic budget **:244** [H-WORKER-DAEMON].
- `harness/agent_jail.py`: repo ro-bind **:247**; XDG tmpfs + bus/keyring `--bind` **:239-245** [SEC-1]; `extra_rw`
  `--bind` **:125-133** [SEC-5a].
- `harness/narrow_fuzz/validation.py`: `_exec_module` SEC-4 redirect **:199-203/231-233**; SEC-3 gate/catch **:255-260**.
- `harness/sandbox_smoke.py`: `smoke_import` SEC-3 catch **:134-143**.
- `harness/embedded_test_runner.py`: SEC-5a cfg read **:120-127**; SEC-3 catches **:154-171/202-216**.
- `harness/git_integration.py`: `_SENSITIVE_APPLY_GLOBS` **:16**; `_apply_symbol_patch` **:939** [R-anchored-patch].
- `tests/adversarial/test_spawn_cwd_and_prompt_isolation.py`: function-local `_P` **:~45** [FAKEPOPEN file-2 blocker].
- `tests/adversarial/test_P2_mutation_kill.py`: live-file mutation [MUT-HARNESS-ISO].
