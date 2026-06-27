# Adversarial Verification Findings — 2026-06-12 session

Scope: commits d29f60c (daemon brief_dep_gate, pipeline re-land), feb13ad (planner
redundant-oracle dedupe), 2561d67 (planner validation external+cd), acc7edb
(hand-edit) / e7b4939 (revert).

Verdict: **SOLID — no BLOCKER, no GAP, no NIT.** All changed code is on the live
execution path, imported + called, with real behavioral oracles. No stubs, no
trivial assertions, no lost functionality across the revert→reland.

---

## 1. Daemon brief-level dependency gating (d29f60c) — WIRED, REAL, GATES

**On live path (confirmed):**
- `_brief_dep_gate_ok` defined at `harness/autowork_daemon.py:1637`.
- Called as a withhold-only filter at `harness/autowork_daemon.py:1708`, inside
  `_decide` (def at :1702), immediately after the byte-identical
  `collect_dispatchable_tasks` (:1707).
- `_decide` is invoked in the iteration loop at `harness/autowork_daemon.py:1876`.
- Live daemon process running (pid 2421475: `python -m harness.autowork_daemon`).

**Actually gates (confirmed behavioral):**
- Gate HOLDS (returns False) when a declared sibling-brief dep EXISTS in
  `status_records` and still has un-accepted, non-terminal work
  (`autowork_daemon.py:1685-1698`, `return False` at :1698).
- Record-shape fidelity verified: gate reads `slug`, `task_ids`, `remaining`,
  `state`, `brief_filename` — all emitted by the real `compute_brief_status`
  (`harness/brief_status.py:73`). State vocabulary `blocked`/`zombie`/`complete`
  is real (`brief_status.py:58-72`). The test's `_record()` is faithful to prod.
- Deadlock-safe fallbacks present: absent dep (:1689-1690), terminal `blocked`/
  `zombie` dep (:1692-1693), any exception (:1700-1701) → DISPATCH.

**Oracle (real, not trivial):** `tests/harness/test_brief_level_dep_gate.py`, 5
cases. The keystone `test_unmet_brief_dep_holds_dispatch` (:60-73) asserts
`is False` (HELD) — a true behavioral constraint, not a smoke check. Two
no-deadlock cases (:89, :102) assert the fallbacks. 5/5 pass at HEAD.

## 2. Revert→reland equivalence (e7b4939 reverted acc7edb; d29f60c re-landed)

`_brief_dep_gate_ok` in the pipeline-blessed HEAD vs the reverted hand-edit is
**semantically identical** — diff (whitespace/comments stripped) shows only:
- `(coerced.get('dependencies') or ())` vs `coerced.get('dependencies') or ()`
  (redundant paren removed; identical evaluation),
- `not remaining` vs `(not remaining)` (identical).

No functionality lost. Daemon parses + imports cleanly. Claim in e7b4939 (file
restored to pipeline-blessed state, hand-edit was operationally inert) holds.

## 3. Planner redundant-oracle dedupe (feb13ad) — WIRED, REAL

**On live path (confirmed):** module pre-existed; feb13ad added the dedupe
helpers (+102 lines). The live entry `normalize_plan`
(`harness/planner/plan_normalizer.py:730`) is imported + called at
`harness/planner/cli.py:356-357`. `normalize_plan` invokes the new helpers:
`_dedupe_oracles` (:749) and `_enforce_module_first` (:752). All referenced
helpers (incl. `_drop_redundant_precommitted_oracles` :629) exist; module
imports cleanly.

**Real logic:** `_dedupe_oracles` (:86-140) groups oracles by `mutation_target`,
keeps one survivor, and rewires dangling deps (:122-139) — non-trivial.

**Oracle:** `tests/planner/test_plan_normalizer.py` —
`test_dedupe_duplicate_oracle_dropped_and_deps_rewired` (:94) asserts survivor
count, removal, and dep-rewiring. `test_module_first_flip_oracle_depends_on_impl`
(:108) asserts ordering flip. Real assertions; pass at HEAD.

## 4. Planner validation external+cd (2561d67) — WIRED, REAL

**On live path (confirmed):** both edits are inside `validate_plan`
(`harness/planner/plan_validator.py`, the live validator entry). `_is_module_creating`
now takes `working_dir` threaded from `plan.get('working_dir')` and uses
`effective_target_root(wd)` (external-target correctness). New
`cd_prefixed_verification_command` violation emitted for leading or embedded
`cd ` re-roots.

**Oracle:** `tests/planner/test_cd_prefixed_verification_command.py` — leading-cd
rejected (:9), embedded-cd rejected (:12), normal vcmd NOT rejected (:15). Real
positive+negative coverage; pass at HEAD.

## Stub / shortcut scan

No `TODO`/`FIXME`/`raise NotImplementedError`/`...` in any of the three changed
production files. The `pass` occurrences in `autowork_daemon.py` are all
`except: pass` defensive handlers (none inside `_brief_dep_gate_ok`, which uses
`return True`). No vacuous oracles found.

## Test run (HEAD)

`tests/planner/test_plan_normalizer.py` +
`tests/planner/test_cd_prefixed_verification_command.py` +
`tests/planner/test_dedupe_precommitted_oracle.py` +
`tests/harness/test_brief_level_dep_gate.py` → **17 passed.**

Backing decision files all present:
`state/control/decisions/{daemon_brief_dep_gate, fix-planner-redundant-oracle-dedupe,
fix-planner-validation-external-and-cd}.json`.
