# Self-heal loop closure (REV25 §2) — landing manifest

Architecture: NEW module `harness/selfheal.py` + 1-line daemon re-export import + small additive
edits to EXISTING daemon/worker functions. ALL §2 tasks touch `harness/**` → every commit is
SENSITIVE and fails closed without an operator approve-decision at
`state/control/decisions/<task_id>.json` (`{"decision":"approve"}` keyed on the task_id below).

Oracles are committed (P1) and RED on HEAD. Land in dependency order:

---

## S1 — selfheal_01_capture_ast_reason
- **File(s):** `harness/orchestrator_worker.py` (inline edit to `main()` reject terminal, ~:312-319).
- **Oracle:** `tests/adversarial/test_selfheal_ast_reason_capture.py`
- **vcmd:** `python -m pytest tests/adversarial/test_selfheal_ast_reason_capture.py -q`
- **Dependencies:** none.
- **Viability:** **VIABLE (partial_edit).** Additive inline emission inside an EXISTING function; no
  new top-level symbol. The companion round-trip test in the oracle is already GREEN (pins the ledger
  shape). Low risk.
- **Approve-decision:** `state/control/decisions/selfheal_01_capture_ast_reason.json`

## S2 — selfheal_02_module_and_flag
- **File(s):** `harness/selfheal.py` (NEW), `harness/config.yaml` (1 line), `harness/autowork_daemon.py` (1 import line).
- **Oracle:** `tests/adversarial/test_selfheal_flag_eligibility.py` + `tests/adversarial/test_selfheal_harvest_brief.py` (helper presence/behavior, satisfied by the module + re-export).
- **vcmd:** `python -m pytest tests/adversarial/test_selfheal_flag_eligibility.py tests/adversarial/test_selfheal_harvest_brief.py tests/adversarial/test_allowlist_promotion_guard.py -q`
- **Dependencies:** none.
- **Viability:** **VIABLE but MULTI-FILE (watch this).** New single-file module = the most viable
  pattern. The two satellite edits (config line + daemon import line) make this NOT `single_file_edit`
  (`constraints.single_file_edit:false`, `no_new_module_level_imports:false` for the one re-export).
  Multi-file manifests are nondeterministic in this pipeline (REV23 lesson). **If the multi-file apply
  flakes, hand-land the config line + daemon import line** (both are 1-liners; the module body is the
  real work and is viable). CRITICAL: the daemon import MUST re-export all three helpers into the
  `autowork_daemon` namespace or S1/S3/S4 oracles + downstream callers fail to resolve.
- **Approve-decision:** `state/control/decisions/selfheal_02_module_and_flag.json`

## S3 — selfheal_03_wire_harvest_and_eligibility
- **File(s):** `harness/autowork_daemon.py` (two existing-fn edits: `_auto_promote` ~:1170, `_auto_promote_brief_eligible` ~:2155 + its two call sites ~:1219/:1332).
- **Oracle:** `tests/adversarial/test_selfheal_integration_loop.py` (the wiring/harvest-is-called check) — NOT `test_selfheal_harvest_brief.py` (that only proves the helper, already green after S2).
- **vcmd:** `python -m pytest tests/adversarial/test_selfheal_integration_loop.py tests/adversarial/test_allowlist_promotion_guard.py -q`
- **Dependencies:** S2 (accepted).
- **Viability:** **VIABLE (partial_edit), but the eligibility signature change is the risk.** Adding a
  `config` param to `_auto_promote_brief_eligible` plus updating two call sites is a 3-site
  coordinated edit in a 2,400-line file. The `_auto_promote` harvest call is a clean additive insert.
  **Likely-viable; if the multi-site signature thread flakes, hand-land the two call-site edits.**
- **Approve-decision:** `state/control/decisions/selfheal_03_wire_harvest_and_eligibility.json`

## S4 — selfheal_04_restage_same_task_corrective
- **File(s):** `harness/autowork_daemon.py` (single inline edit: the `prompt` f-string in `_escalate_to_autobrief` ~:827).
- **Oracle:** `tests/adversarial/test_selfheal_restage_same_id.py`
- **vcmd:** `python -m pytest tests/adversarial/test_selfheal_restage_same_id.py tests/adversarial/test_allowlist_promotion_guard.py -q`
- **Dependencies:** S2, S3 (accepted).
- **Viability:** **VIABLE (partial_edit).** Single inline string edit in an EXISTING function. The
  oracle is a substring/AST-segment check, satisfiable by editing the f-string. Must keep both `eval`
  and `exec` (forbidding) + an original-task-id marker.
- **Approve-decision:** `state/control/decisions/selfheal_04_restage_same_task_corrective.json`

## S5 — selfheal_05_integration_loop_closure
- **File(s):** `tests/adversarial/test_selfheal_integration_loop.py` (the oracle is PRE-AUTHORED + committed; this task is primarily a DAG node).
- **Oracle:** `tests/adversarial/test_selfheal_integration_loop.py`
- **vcmd:** `python -m pytest tests/adversarial/test_selfheal_integration_loop.py -q`
- **Dependencies:** S1, S2, S3, S4 (accepted).
- **Viability:** **VIABLE (seam/test_integration).** `meta_task_type: test_integration` is cosmetic;
  the load-bearing parts are the deps (gate on accepted → runs against the integrated tree) + the
  behavioral vcmd. `partial_edit:false`. The oracle already exists; the value is that it is PLANNED
  into the DAG so the seam is actually verified (P-I).
- **Approve-decision:** `state/control/decisions/selfheal_05_integration_loop_closure.json`

---

## Landing order
1. **S1** (no deps) — capture AST reason.
2. **S2** (no deps) — new module + flag + re-export.
3. **S3** (deps: S2) — wire harvest + eligibility.
4. **S4** (deps: S2, S3) — corrective re-stage prompt.
5. **S5** (deps: S1–S4) — integration/behavioral acceptance.

S1 and S2 are independent and may land in either order. S3→S4→S5 are strictly serial.

## All required operator approve-decisions (sensitive harness/** edits)
- `state/control/decisions/selfheal_01_capture_ast_reason.json`
- `state/control/decisions/selfheal_02_module_and_flag.json`
- `state/control/decisions/selfheal_03_wire_harvest_and_eligibility.json`
- `state/control/decisions/selfheal_04_restage_same_task_corrective.json`
- `state/control/decisions/selfheal_05_integration_loop_closure.json`

(Each: `{"decision":"approve"}` keyed on the task_id; sensitive-glob fail-close is at
`orchestrator.py:1818`, decision read at `orchestrator.py:1906`.)

## Likely hand-lands (pre-declared, not pipeline failures)
- **S2 satellite edits** (`harness/config.yaml` 1 line + `harness/autowork_daemon.py` import line):
  multi-file manifest nondeterminism — if the apply drops a file, hand-land the two 1-liners. The
  module body itself is viable.
- **S3 eligibility signature thread** (add `config` param + update two call sites): 3-site coordinated
  edit in a 2,400-line file — hand-land the call-site edits if the multi-site partial_edit flakes.

## Slug/id mapping note
`compute_brief_status` derives `slug = stem.removeprefix('brief_hooks_')`, so the harvested
`brief_hooks_selfheal_<task_id>.md` → slug `selfheal_<task_id>`, which `_is_selfheal_brief` recognizes
(prefix `selfheal_`). The re-staged plan must key the corrective task on the ORIGINAL `<task_id>` so
dependents resolve (S4 keeps `brief_hooks_<task_id>_fix.md` → S2 maps it to `selfheal_<task_id>`).
