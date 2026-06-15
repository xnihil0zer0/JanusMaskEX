# HANDOFF — Verify last session, harden one-time workarounds, run a live 4-way / 5-PoC NobleGreed E2E

You are the **overseer**. Three missions, in order:
**(A)** verify the work landed in the previous session (concurrency isolation + NGv2 z3/tree-sitter capability epic);
**(B)** fix the loose ends and bake recently-discovered one-time workarounds into JM/NGv2 so they stop being manual;
**(C)** drive a **live NobleGreed end-to-end hunt with 4-way parallelization that produces FIVE confirmed Proof-of-Concept exploits, each with a live test demonstration.**

Every production change to the harness (`harness/**`) routes as `harness_self_fix` (RED oracle committed FIRST → brief → planner → stage → worker → operator decision at `state/control/decisions/<task_id>.json`). Every NGv2 (`/home/xnihil0zer0/NobleGreedv2`) production change routes as `data_model` / `config_schema` (bypass-fuzzer external types), oracle committed to NGv2 master FIRST. Rule: [[never-hand-edit-production-outside-pipeline]]. Tests/oracles are hand-authorable.

★ **The recipe that one-shot all four leaves last session** (reuse it): a prep subagent PROVES each RED oracle is satisfiable BEFORE committing it — build a throwaway reference implementation in `/tmp`, inject it via `sys.modules` (or run it live), confirm the oracle goes green, delete the scratch — then embed the *exact validated artifact* (query strings, encodings, file content) verbatim in the brief so the blind jailed worker cannot mis-implement. Memory: [[concurrency-isolation-and-ngv2-solver-ast-epic]].

---

## Orientation (verified 2026-06-12)

* **JM** `/home/xnihil0zer0/JanusMaskJR` HEAD `4a80a0d` (pushed). **NGv2** `/home/xnihil0zer0/NobleGreedv2` HEAD `4f917fe` (pushed). Both trees were clean at handoff time — re-check before dispatch; `EXTERNAL_DIRTY_GATE` (`harness/orchestrator.py:2833-2847`) refuses a dirty external repo.
* **Daemon RUNNING** under a supervisor: `scripts/run-autowork.sh` (the parent) launches `harness.autowork_daemon` and **respawns it on death with backoff**. Live pid is written to `state/control/autowork.pid`. Last session's pid was 2034399 (supervisor pid 197936). Do not disturb `state/` by hand.
  * ★ **Correct restart procedure** (memory [[daemon-supervisor-respawn]]): `kill -TERM "$(cat state/control/autowork.pid)"`, wait ~5s for the supervisor to respawn, then confirm exactly one daemon via `pgrep -af harness.autowork_daemon`. **NEVER** `nohup` a second daemon — last session that produced a duplicate (double-dispatch hazard) which had to be killed. The previous handoff's "stop pid X, restart manually" recipe was WRONG; this supersedes it.
* **Posture flags** (`harness/config.yaml`): `parallel_cap: 5`, `wire_up_gate: true`, `archive_spent_briefs: false`, `selfheal_auto_promote: false`. `agy_pool.POOL_SIZE = 4` (isolated worker HOMEs).
* **Allowlist** `state/control/autowork/auto_promote.allowlist` is append-only opt-in (empty = deny-all). Dispatch flow for every task: commit RED oracle → drop `brief_hooks_<slug>.md` → (harness only) write decision file → append slug → running daemon dispatches.
* **NGv2 venv**: `/home/xnihil0zer0/NobleGreedv2/.venv` — has `z3-solver 4.16.0.0`, `tree-sitter 0.25.2`, `tree-sitter-c 0.24.2`, `tree-sitter-java 0.23.5`, `tree-sitter-javascript 0.25.0`.
* **Memory references**: [[concurrency-isolation-and-ngv2-solver-ast-epic]], [[ngv2-e2e-huntr-poc-driven]], [[ngv2-autonomous-bounty-fsm-epic]], [[daemon-supervisor-respawn]], [[ngv2-phase0-external-build-proven]].

---

## PART A — Verify last session's work (no pipeline; read + run gates)

Confirm, don't assume. Run each and record the result:

1. **T1 — concurrency_isolation** (JM `4a80a0d`):
   * `git -C /home/xnihil0zer0/JanusMaskJR show 4a80a0d --stat` → only `harness/autowork_parallelism.py` (20 insertions).
   * Confirm the landed contract is the *decided* (inverted) one, NOT the stale working-tree draft: file must contain `_ISOLATED_EXTERNAL_DIRS = frozenset({'/home/xnihil0zer0/NobleGreedv2'})`, an exact-path check `if proj_a == proj_b and proj_a in _ISOLATED_EXTERNAL_DIRS:`, and **no** substring test `"NobleGreedv2" not in`. `parallel_cap` must still be `5` (the 5→4 hand-edit was reverted in P1).
   * `python3 -m pytest -q tests/test_autowork_parallelism.py` → 9 passed (incl. `test_project_isolation`, `test_project_isolation_exact_path`).
   * **Live-behavior proof to re-confirm**: in `state/impl_progress.jsonl`, `ngv2-treesitter-verifier` `auto_commit` (00:40:32Z) precedes `ngv2-z3-solver-adapter` dispatch (00:41:15Z) — two same-external-root tasks ran *strictly sequentially* after the restart, which is the isolation working. Grep both task_ids and confirm non-overlapping phase windows.
   * Confirm the live daemon actually loaded the new code (it restarted post-landing): the daemon importing `can_run_parallel` must be the one started AFTER `4a80a0d`. Check `state/control/autowork.pid` start time vs the commit time.
2. **NGv2 leaves** (master `4f917fe`):
   * `git -C /home/xnihil0zer0/NobleGreedv2 log --oneline -6` → `4f917fe` z3 adapter, `c91c64b` tree-sitter, `6a8d326` requirements pins on top of `ae2675a`.
   * `/home/xnihil0zer0/NobleGreedv2/.venv/bin/python -m pytest tests -q` (run from NGv2 root — **`tests`, not bare `pytest`**; see Issue B-2) → expect ~1239 passed.
   * Targeted: `… -m pytest tests/ngv2/test_z3_solver_adapter_wired.py tests/ngv2/test_treesitter_verifier_wired.py tests/ngv2/test_requirements_pins_wired.py -q` → all green.
   * Spot-check the modules exist and are honest: `ngv2/z3_solver_adapter.py` (guarded in-body `import z3`, `make_z3_solver`), `ngv2/treesitter_verifier.py` (module-level S-expression query dict, `matches()` not `captures()`), `requirements.txt` is the exact six lines.
3. **JM full suite** (serial gate, NOT xdist — [[test-tiering-bootstrap]]): `python3 -m pytest -q` → expect 7744 passed / 8 skipped / 5 xfailed (~14 min). If anything regressed, that's the first thing to fix.

If any verification fails, STOP mission C and root-cause via the pipeline first ([[issue-fix-via-pipeline-then-rerun]]).

---

## PART B — Issues encountered this round (fix or consciously dismiss)

### B-1 — `decode_check ok:false` after every successful commit — INVESTIGATE (likely benign)
Every `auto_commit` is immediately followed by `{"event":"decode_check","ok":false,"repaired":false,"dropped_edits":0}`. Measured: **92/92** decode_check rows across all history have `ok:false`, **zero** `ok:true`, always `dropped_edits:0`. So it is NOT session-specific and is NOT gating anything (all four leaves committed and verified green). But a check that is *universally false* is either dead or mis-named. Find the producer (grep `decode_check` in `harness/`), determine whether `ok` is inverted-sense or measuring something never satisfied, and either fix the sense or downgrade it to debug-level. If it's load-bearing telemetry, an always-false signal is a latent blind spot. Low priority; do NOT let it block C. If you change harness code → `harness_self_fix` with a RED oracle pinning the corrected sense.

### B-2 — NGv2 bare `pytest` yields ~190 collection errors — BAKE A FIX (see C-1)
Running `pytest -q` from the NGv2 *root* collects non-suite corpus/target trees and unbuilt `*_wired.py` oracles → ~190 ModuleNotFoundError collection errors (`yaml`, `openai`, `torch`, `autoharness`, `tests.ngv2`). This is NOT a regression — the real suite is `pytest tests`. Root cause: NGv2 `pyproject.toml` has **no `[tool.pytest.ini_options] testpaths`**. Fixed permanently by C-1. Until then, always gate NGv2 with `pytest tests`.

### B-3 — Spent briefs did not auto-archive; JM root is cluttered — DECIDE
`archive_spent_briefs: false` (it was ON per memory [[brief-staleness-reconciler]], now off — someone flipped it). Consequence: last session's four briefs (`brief_hooks_concurrency_isolation.md`, `brief_hooks_ngv2_requirements_pins.md`, `brief_hooks_ngv2_z3_solver_adapter.md`, `brief_hooks_ngv2_treesitter_verifier.md`) plus **86 untracked `HANDOFF_*`/`*REPORT*`/`*.md`** files and many `_autowork_archive/` dirs sit uncommitted in JM root. Decide one: (a) re-enable `archive_spent_briefs` (config change — but verify WHY it was disabled first; it may have caused a problem — check git log / transcripts before flipping), or (b) leave the flag and do a one-time manual sweep of spent briefs into `_autowork_archive/<dated>/`. Either way, the 86 untracked root docs are real clutter — propose an archival sweep to the owner; do not delete anything you didn't create without confirming.

### B-4 — Daemon restart fragility — DOCUMENTED, consider baking (see C-4)
Covered in Orientation. The respawn-on-kill behavior is correct but the manual-restart trap is easy to hit. Optional: bake `scripts/restart-autowork.sh` (C-4).

---

## PART C — Bake one-time workarounds into the codebase (pipeline leaves; RED oracle first)

Each is independent. NGv2 edits need NGv2 clean at dispatch and serialize against each other under T1's new isolation (that's fine — let the daemon sequence them; do not hand-drive parallel external workers). Use the prove-satisfiable recipe for every oracle.

### C-1 — NGv2: pin `testpaths` so the suite scope is unambiguous *(config_schema)*
* **Why**: kills B-2 permanently; makes `pytest` == `pytest tests`; protects future full-suite gates from unbuilt-oracle collection interruptions.
* **Oracle** (`tests/ngv2/test_pytest_testpaths_wired.py`, commit to NGv2 first): parse `pyproject.toml` (stdlib `tomllib`), assert `tool.pytest.ini_options.testpaths == ["tests"]`; as a wiring anchor, assert `tests/` is the only configured collection root. RED today (key absent).
* **Edit**: add `[tool.pytest.ini_options]\ntestpaths = ["tests"]` to NGv2 `pyproject.toml`. Non-Python target ⇒ `__JANUSMASK_MANIFEST__` verbatim whole-file manifest path (the idiom proven in `brief_hooks_ngv2_requirements_pins.md` last session — reuse it). `files_touched: ["pyproject.toml"]`. ⚠️ pyproject is whole-file: embed the COMPLETE current pyproject + the added stanza verbatim in the brief.
* **Verify**: after landing, bare `pytest tests` unchanged-green AND bare `pytest` from root no longer mass-errors (it will now honor testpaths).

### C-2 — NGv2: fix `SessionApi._classify` ordering so reports self-classify *(data_model)*
* **Defect** (`ngv2/session_api.py:232-239`): `_classify` resolves `explicit → phase → structural`. Phase-string before structure means an artifact's *kind* is decided by which phase it's submitted at, not its shape — so a PoC submitted at `detonate` mis-tags as `report`, and the only reason it works today is the e2e driver manually injecting `artifact_type:'report'` (`_e2e_run/drive.py:133`). Memory: [[ngv2-e2e-huntr-poc-driven]].
* **Fix**: reorder to `explicit → structural → phase` (structural is authoritative: `_structural_kind` at `:649` already detects `{'poc_finding_id','verdict'}→report` and `{'language','entrypoint','code'}→poc`; phase becomes the last-resort fallback). This eliminates the manual `artifact_type` workaround in the drivers.
* **Oracle** (`tests/ngv2/test_classify_structural_precedence_wired.py`): assert a LiveTestReport dict (no `artifact_type`) submitted at phase `'detonate'` classifies `report`; a PoC dict submitted at phase `'detonate'` classifies `poc` (the bug case — RED today, returns `report`); an explicit `artifact_type` still wins; a bare dict at `'hunt'` still falls through to `finding` via phase fallback. Exhaustively pin the precedence with one case per branch.
* **Edit**: single whole-symbol patch on `_classify` (1-part method on `SessionApi`? — NO: it's a method, so emit the WHOLE FILE or use the class-method discipline. `session_api.py` is large; prefer the committed-safe shape: whole-file emission is heavy. Decide in the brief — if it's a clean single-method body change with no new symbol, a `__JANUSMASK_PATCHES__` symbol patch on the method qualname per the gateresult-brief pattern is fine; if any doubt, whole-file). `files_touched: ["ngv2/session_api.py"]`. Non-Goal: do not touch any gate handler or the drivers.
* **Follow-up** (separate, optional): once C-2 lands, the `artifact_type:'report'` line in the e2e drivers is redundant — leave it (harmless) or remove it in the C-5 driver rework.

### C-3 — NGv2: make the detonation semantic oracle the default; refuse weak `confirmed` *(data_model)* — HIGH VALUE for mission C
* **Defect** (`ngv2/detonation.py:36-62`): when `expected_fs_signature is None`, `detonate()` returns `verdict='confirmed'` on **exit_code==0 + success_marker in stdout alone** — no filesystem-effect check. A PoC that merely *prints* the marker without actually exploiting anything is accepted. The strong `semantic_verdict` (`detonation.py:3-22`, requires exit 0 AND marker AND `expected_fs_signature in fs_diff`) only runs when callers remember to pass the signature. For a *trustworthy* 5-PoC live demonstration this matters enormously: the weak gate admits vacuous PoCs.
* **Fix (decide the exact contract in the brief; recommend)**: when `expected_fs_signature is None`, the weak path may return `inconclusive`/`refuted` but **must NOT return `confirmed`** — a confirmed verdict requires the semantic oracle (marker + filesystem signature). This forces every confirmation through real-effect evidence. Alternatively (softer): keep the weak path but emit a `weak_gate: True` provenance flag on the report so downstream readiness gates can reject it. Pick the stricter one unless an existing committed oracle pins the weak `confirmed` behavior (CHECK `tests/test_detonation*.py` first — if a committed test asserts weak `confirmed`, that's an ANTI-SEESAW hazard: you must update the union of all oracles touching `detonate`, memory [[ngv2-autonomous-bounty-fsm-epic]]).
* **Oracle** (`tests/ngv2/test_detonation_requires_semantic_oracle_wired.py`): marker-only, no fs_signature, exit 0 ⇒ verdict is NOT `confirmed`; marker + matching fs_signature ⇒ `confirmed`; marker + non-matching fs_signature ⇒ `refuted`; exit≠0 ⇒ `error`/`refuted`. Differential against the existing `semantic_verdict` as reference.
* **Edit**: whole-symbol/whole-file on `ngv2/detonation.py` `detonate`. `files_touched: ["ngv2/detonation.py"]`.
* ★ Mission C MUST use the strong oracle on every hunt regardless of whether C-3 lands — but landing C-3 makes "5 confirmed PoCs" mean "5 real exploits," not "5 marker prints." Treat C-3 as a prerequisite for a *credible* demonstration.

### C-4 — JM: `scripts/restart-autowork.sh` supervisor-aware restart helper *(harness_self_fix or scripts/)*
* **Why**: encode the correct restart so the next operator can't spawn a duplicate. TERM the pidfile, wait for the supervisor's respawn, assert exactly one daemon, fail loudly if zero or two.
* **Check the sensitive-path gate first**: is `scripts/**` in `_NEVER_AUTO_APPROVE` or the `harness/**` path-scope gate (`harness/git_integration.py:82`)? If `scripts/` is outside the protected glob, this may be a normal task type; if inside, it's `harness_self_fix` + decision file. Determine before authoring.
* **Oracle**: a test that imports/execs the script logic against a faked pidfile + fake `pgrep` and asserts single-survivor invariant. Keep it hermetic (no real daemon).
* Lower priority than C-1/C-2/C-3; do it if time permits.

---

## PART D — Live NobleGreed E2E: 4-way parallel, FIVE confirmed PoCs with live test demonstrations

This is the headline deliverable. The owner will act as the single human-checkpoint approver. **Build the missing pieces through the pipeline (RED oracle first), then drive the live run.**

### D-0 — What exists vs what's missing (verified 2026-06-12)
* **Lifecycle FSM** (`ngv2/state_machine.py:69` `LIFECYCLE_PHASES`): `source→hunt→triage→verify→poc→detonate→novelty→report→awaiting_submission→submitted→done`. Confirmation gate `_gate_poc_to_detonate` (`ngv2/session_gate.py:118`) calls `semantic_verdict`; `confirmed` requires the strong oracle (see C-3).
* **Live detonation jail** (`ngv2/poc_runner_live.py:258` `detonate_live`): bubblewrap, `--unshare-net/ipc/pid`, target `--ro-bind` read-only, per-detonation `--tmpfs` workspace, wall-clock timeout, FS snapshot diff → this IS the "live test demonstration."
* **Drivers** (`_e2e_run/drive_full_lifecycle.py`, `_e2e_run/drive.py`): **single-target, hardcoded** — `TARGET = HERE/"target"`, `DB_PATH = HERE/"lifecycle.db"`. Prints `FULL_LIFECYCLE_CONFIRMED: true`. **No target/DB parameterization, no parallelism.**
* **Pattern scanner** (`ngv2/pattern_scanner.py` `VULN_PATTERNS`): exactly five — `sql_injection, command_injection, eval_usage, weak_crypto, hardcoded_secret`. ★ **This is the clean 5-PoC plan: one target fixture per pattern.**
* **No corpus**: only one CWE-78 target (`_e2e_run/target/vuln_service.py`). **Five targets must be authored.**
* **No parallel runner**: pipeline detonates via a serial list-comprehension (`pipeline.py:36`). 4-way fan-out must be built.

### D-1 — Build: five vulnerable target fixtures (one per VULN_PATTERN) *(hand-authorable test fixtures, or a data leaf)*
Author five minimal, self-contained vulnerable targets under `_e2e_run/targets/<pattern>/`, each a real instance the scanner detects AND that the live jail can demonstrate exploiting (i.e. the PoC must produce a real filesystem effect matching an `expected_fs_signature`, so C-3's strong oracle confirms it):
* `command_injection/` — e.g. `os.system("getent hosts " + host)`; PoC injects `; touch $WORK/pwned` → fs_signature `pwned`.
* `sql_injection/` — string-built query; PoC demonstrates injection effect observable in the jail (e.g. a sqlite file the query writes/leaks).
* `eval_usage/` — `eval(user_input)`; PoC evaluates a payload that writes a marker file.
* `weak_crypto/` — e.g. MD5/DES usage; demonstration is a collision/predictability proof writing evidence (this one is the hardest to give a *filesystem* effect — design the demonstration carefully; if a real fs-effect PoC isn't sound for a crypto weakness, decide with the owner whether `weak_crypto` is demonstrated by a deterministic proof artifact rather than a jail detonation, and pick a different 5th pattern if needed).
* `hardcoded_secret/` — secret in source; PoC extracts it and writes proof.
* Each target gets a fixture oracle (scanner finds the expected finding id; the PoC, when run in the jail, yields `confirmed` under the strong oracle). ★ Author these as committed NGv2 tests/fixtures (hand-authorable). Prove each PoC actually detonates `confirmed` in the jail locally before declaring the fixture done — same prove-satisfiable discipline.

### D-2 — Build: parameterize the driver + a 4-way parallel orchestrator *(data_model / new module)*
* **Parameterize** `drive_full_lifecycle.py` (or a new `_e2e_run/drive_one.py`) to accept `--target <dir>` and `--db <path>` so each hunt is fully isolated (own SessionDB file, own target). ★ **Isolation is mandatory for safe parallelism**: each concurrent hunt MUST write a distinct SessionDB (`sqlite` files don't share safely) and rely on the jail's per-detonation tmpfs (already isolated). The read-only target bind-mount is safe to share but give each its own dir anyway.
* **Orchestrator** `_e2e_run/run_parallel.py`: `concurrent.futures.ProcessPoolExecutor(max_workers=4)` (processes, not threads — the hunts are CPU/subprocess-bound and sqlite-per-process is cleaner) fanning the five `(target, db, session_id)` jobs across **4 workers**. Collect per-session `(session_id, verdict, db_path, submission_package_path)`. Print a final table and a single `FIVE_POC_RUN: <n>/5 confirmed`.
* **Oracle** (`tests/ngv2/test_run_parallel_orchestrator_wired.py`): with 5 trivial stub jobs and `max_workers=4`, assert all 5 complete, results are collected, and at most 4 run concurrently (instrument via a shared counter/semaphore probe). Keep the oracle hermetic (stub the hunt fn) so it doesn't need the jail. The real jailed run is the live demonstration, gated separately.
* **NOTE on T1 interplay**: T1's `can_run_parallel` isolation governs the **JM build pipeline** (which build/commit tasks may run together), NOT the NGv2 **runtime** e2e. The 4-way parallel *hunt run* is a separate runtime path (the orchestrator process pool) and is NOT throttled by `parallel_cap` or external-root isolation. They are orthogonal — say this clearly so no one expects the daemon to parallelize the hunts.

### D-3 — Drive the live run (operator-in-the-loop)
1. Land C-3 (strong-oracle confirmation), C-2 (clean classification), D-1 (five targets), D-2 (driver + orchestrator) through the pipeline — NGv2 clean between dispatches, daemon sequences them.
2. Pre-flight: NGv2 `pytest tests` green; each of the five PoCs proven to detonate `confirmed` in the jail in a solo run (`drive_one.py --target … --db …`).
3. Launch: `cd /home/xnihil0zer0/NobleGreedv2 && PYTHONPATH=. .venv/bin/python _e2e_run/run_parallel.py` → 4 workers, 5 hunts.
4. **Human checkpoint**: each session parks at `awaiting_submission` (fail-closed, `ngv2/human_checkpoint_gate.py` reads an operator decision file). The owner approves each (or you write the approve decision files on the owner's instruction). Then sessions advance `submitted→done`.
5. **Success criteria** (all must hold): five SessionDBs each with a `reports` row `verdict='confirmed'` produced through the **strong** semantic oracle (marker + filesystem signature, NOT weak-gate); five submission packages rendered (9-section markdown via `ngv2/submission_package.py`) each with a populated "Live-Test Evidence: confirmed" section; the run reported `FIVE_POC_RUN: 5/5 confirmed`; observed concurrency ≤4. Capture the five package paths + the five DB paths in the run report.
6. If any hunt yields `refuted`/`inconclusive`, that's a real signal — do not paper over it. Root-cause (weak PoC? scanner miss? jail timeout?) and fix the *fixture or the harness* via the pipeline, then re-run. Vacuous green is failure.

### D-4 — Out-of-scope guards
* Do NOT submit to any real external bounty platform — this is a self-contained demonstration against authored fixtures in the jail. The `submitted` phase writes a local ledger row only; confirm no driver path performs a real network submission (the FSM is `--unshare-net` in the jail; the submission package is a local artifact).
* Do NOT weaken any gate to force confirmations. The whole point is that five PoCs pass the *strong* oracle.

---

## Execution sequence

1. **PART A** — verify last session (read + 3 gate runs). If clean, proceed; if not, pipeline-fix the regression first.
2. **PART C-1, C-2, C-3** — bake the three NGv2 hardening leaves (RED oracle → brief → allowlist → daemon; NGv2 clean between each; let T1 isolation sequence them). C-3 before D. (B-1, B-3, C-4 are lower priority — do as time permits, or hand to a later session.)
3. **PART D-1, D-2** — author five target fixtures + parameterized driver + 4-way orchestrator (oracles first; prove each PoC detonates `confirmed` solo).
4. **PART D-3** — drive the live 4-way / 5-PoC run with the owner approving the human checkpoints. Capture artifacts and report `5/5 confirmed`.
5. Gating runs are SERIAL (no xdist — [[test-tiering-bootstrap]]). NGv2 gate = `pytest tests` (post C-1, bare `pytest` also works). JM gate = `python3 -m pytest -q`.
6. **Daemon restart** only via `kill -TERM "$(cat state/control/autowork.pid)"` + supervisor respawn + single-survivor check ([[daemon-supervisor-respawn]]). Needed if any landed harness change must load live (none of C-1/2/3 are harness — they're NGv2 — so no JM restart required for mission C unless B-1/C-4 land).

---

## Appendix — verified file anchors

* T1 landed: `harness/autowork_parallelism.py` (`_ISOLATED_EXTERNAL_DIRS`, `_get_project_dir`, exact-path check). Oracle `tests/test_autowork_parallelism.py` (JM `d574679`).
* NGv2 confirmation path: `ngv2/state_machine.py:69` (LIFECYCLE_PHASES), `ngv2/session_gate.py:118` (`_gate_poc_to_detonate`), `ngv2/detonation.py:3-22` (`semantic_verdict`, strong) vs `:36-62` (weak default), `ngv2/poc_runner_live.py:258` (`detonate_live` bwrap jail).
* Classification defect: `ngv2/session_api.py:232-239` (`_classify` order), `:649` (`_structural_kind`, authoritative), `:644` (`_phase_to_kind`).
* Drivers: `_e2e_run/drive_full_lifecycle.py` (hardcoded `TARGET`/`DB_PATH` at `:45/:50`), `_e2e_run/drive.py:133` (manual `artifact_type:'report'` workaround → removable post-C-2).
* Patterns→PoCs: `ngv2/pattern_scanner.py` `VULN_PATTERNS` = `['sql_injection','command_injection','eval_usage','weak_crypto','hardcoded_secret']`.
* Submission package: `ngv2/submission_package.py:194-243` (9-section markdown). Readiness: `ngv2/submission_readiness_gate.py:64-78` (needs `verdict=='confirmed'` AND `live_tested`). Checkpoint: `ngv2/human_checkpoint_gate.py` (operator decision file).
* Supervisor: `scripts/run-autowork.sh`; pidfile `state/control/autowork.pid`.
* Telemetry oddity: `decode_check` producer in `harness/` (92/92 `ok:false`).
