# PHV: config-schema root-cause adversarial verification (2026-06-13)

## 1. Oracle RED baseline — CONFIRMED
`python -m pytest tests/webui/test_config_schema.py -q` => **2 failed, 9 passed**.
Failing tests:
- `test_role_assigned_keyed_api_provider_is_accepted`
- `test_atomic_save_roundtrips_without_clobbering` (assert 1 == 5)
(1 SyntaxWarning, benign — invalid escape `\ ` in wiring test docstring.)

## 2. 2-bug diagnosis — BOTH CONFIRMED
(a) ROLE-VALUE PROPAGATION: `validate_config` per-role loop (L177-200) only writes
    `field_errors` on failure; the accept path NEVER does `values[role.config_key]=...`.
    `values` is populated only from CONFIG_FIELDS (L176). So
    `out.values["overseer.default_backend"]` KeyErrors. CONFIRMED.
(b) SAVE-KEY NESTING: `atomic_save_config` (L233-234) iterates `validated.values.items()`
    and `_set_nested(existing, key, value)` with SHORT keys. `parallel_cap` has no dot →
    written top-level; `existing["autowork"]["parallel_cap"]` stays stale (1). No
    short→dotted map exists. CONFIRMED (test got 1, wanted 5).

## 3. Clean baseline — CONFIRMED
No `plan_hooks_webui-config-schema.json`; no config-schema task in `state/tasks/`;
nothing in `state/blocked/`. Clean.

## 4. Brief — CONFIRMED
`brief_hooks_webui-config-schema.md` contains BOTH the TEST-SPEC BALANCE block
(L52, `len(unit_tests) >= len(functional_requirements)`, ≤6 FRs, 6 unit tests, ≥2 edge)
and the AST-CREDENTIAL GATE / verbatim-oracle instruction (L12). Both present.

## 5. DEP-GATE LEAK — CONFIRMED (do NOT edit; _NEVER_AUTO_APPROVE)
`_brief_dep_gate_ok` (autowork_daemon.py L1685-1698): per dep slug —
- `rec is None` (absent/never-planned) -> `continue` (RELEASE)
- `state in ('blocked','zombie')` -> `continue` (RELEASE)
- only HOLDS (`return False`) when dep `task_ids and (not remaining)` is False, i.e. dep
  still has remaining non-terminal work.
Key condition (L1692): `if state in ('blocked', 'zombie'): continue`.
So YES: a dependent IS released when its dependency is blocked/zombie/unplanned/absent.
This is the documented "DEADLOCK-SAFE" degrade-to-dispatch behavior — by design, but it
DOES leak: a dependent of a blocked dep will dispatch (may smoke_fail). config-schema
brief declares `dependencies: []` so it is unaffected.

## VERDICT
Root-cause analysis **CONFIRMED**. Both bugs real & exactly as described; RED baseline
matches; brief carries the dcf697a balance + AST-verbatim blocks; baseline clean.
A FRESH rebuild (Option 1) WOULD converge: brief is plan-shaped (2-task DAG, balance gate
satisfied, harness_self_fix + integration excuse + control_gate wiring anchor), oracle is
committed & non-vacuous, and the 2 fixes are local/self-contained (add role propagation
write + short→dotted save map). No dep-gate dependency to leak on (deps: []).
