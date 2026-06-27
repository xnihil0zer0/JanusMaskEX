---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
priority: high
required_task_ids: [wireup-detonation-prompt-oracle, wireup-detonation-prompt-impl]
interfaces: |
  Touches one function: harness/orchestrator.py::prepare_task_prompt(task: dict) -> str
  (top-level def at line 1425). Inside the existing `if mtt == 'test_authoring':`
  block (line 1475-1476), AFTER the base 'TEST-AUTHORING DISPATCH' string is
  appended, append a NEW contract-gated detonation clause when (and only when) the
  task carries a VALID integration_contract. The contract is already in scope via
  `(task.get('constraints') or {}).get('integration_contract')` -- a dict of shape
  {entrypoints:[...], symbols:[...], runtime_oracle:"..."}. Valid iff isinstance
  dict AND entrypoints is a non-empty list with every entry in
  harness.wire_up.LIVE_ROOTS AND symbols non-empty AND runtime_oracle a non-empty
  string. No new helper, no new gate (the stub_target mutation gate at
  orchestrator.py:3050-3167 already enforces non-vacuity), no threading -- the
  contract is already accessible. Nothing else in prepare_task_prompt changes.
---

# Title

wire-up-detonation-oracle-authoring-prompt: contract-gated LIVE-ROOT detonation clause in the test-authoring dispatch prompt

# Scope

Brief #6 of the wire-up detonation program. When a `test_authoring` task carries a
valid `integration_contract`, the factory's test-authoring worker prompt (built by
`harness/orchestrator.py::prepare_task_prompt`) must instruct the agent to author a
LIVE-ROOT DETONATION ORACLE -- drive a declared LIVE_ROOT entrypoint for one
bounded iteration with the target symbol UNMOCKED, observe via
`observe_symbol_execution`, and assert `executed_with_live_root_ancestor` -- rather
than a hermetic unit test, with a prominent `pure_helper` wire_exempt fallback for
symbols that genuinely cannot detonate.

Fix-forward RED-PAIR, single production file: `harness/orchestrator.py`.

# Inputs

- `harness/orchestrator.py::prepare_task_prompt(task)` -- top-level def at line 1425.
  The existing test-authoring clause is the `prompt += '\nTEST-AUTHORING DISPATCH:\n...'`
  string-concat inside `if mtt == 'test_authoring':` (lines 1475-1476). `mtt` is
  resolved at line 1462. The new clause is appended right after that base string,
  still inside the same `if` block, before the `if spec_summary:` tail.
- Contract access (already in scope, no threading):
  `contract = (task.get('constraints') or {}).get('integration_contract')`.
  Shape: `{entrypoints:[...], symbols:[...], runtime_oracle:"..."}`.
- `harness.wire_up.LIVE_ROOTS` (wire_up.py:37) =
  `['harness/orchestrator.py','harness/orchestrator_worker.py','harness/autowork_daemon.py','harness/planner/cli.py']`.
  Import LIVE_ROOTS inside prepare_task_prompt (local import, matching the file's
  existing pattern of in-function imports such as `from harness.paths import ...`).
- Canonical driver scaffold to reference by NAME: `_drive_run_pipeline` in
  `tests/harness/test_wire_up_runtime_observe.py` (lines 84-118) -- patches every
  spawn collaborator at its SOURCE module, returns the task once then None, bounds
  the loop with a `_StopLoop` sentinel raised from `time.sleep`, and leaves the
  watched PASS symbol UNMOCKED so its real body runs via a production call edge.
- Model oracle for the import/call convention:
  `tests/adversarial/test_prepare_task_prompt_test_authoring.py` -- imports
  `from harness.orchestrator import prepare_task_prompt`, calls it directly with a
  literal task dict, asserts substrings on the returned prompt; it declares NO
  mutation_target (it is a model only -- our oracle DOES declare one, see below).
- Non-vacuity gate: the existing stub_target mutation gate (orchestrator.py:3050-3167)
  stubs the `mutation_target` module via `harness.test_author.stub_for` (every
  function body -> `raise NotImplementedError`) and re-runs the vcmd, requiring it to
  FAIL on the mutant. No new gate code.

# Non-Goals

- NO new gate code: the stub_target mutation gate (orchestrator.py:3050-3167)
  already enforces detonation non-vacuity. Do not add a gate.
- NO integration test and NO live-environment stand-up in THIS change: we modify a
  pure prompt-builder string. The "integration" wiring this clause describes is the
  CONTENT of the prompt text, exercised here only by substring assertions on the
  returned string; the leaf is NOT required to stand up a LIVE_ROOT or run a real
  detonation. The integration excuse applies.
- NO change to any other branch of prepare_task_prompt (base prompt, partial-edit,
  multi-file manifest, spec_summary tail, repair_feedback). Touch ONLY the new
  contract-gated append inside the `if mtt == 'test_authoring':` block.
- NO contract threading: the contract is already in scope. NO new helper function.
- NO allowlist edit, NO decision file, NO dispatch from this brief.

# Deliverables

Two tasks, a fix-forward RED-PAIR over a single production file.

- Task 1 -- `wireup-detonation-prompt-oracle` (meta_task_type: test_authoring, dependencies: [])
  Authors `tests/adversarial/test_prepare_task_prompt_detonation_clause.py`
  (tests/** is NOT sensitive -> no decision file). files_touched:
  ["tests/adversarial/test_prepare_task_prompt_detonation_clause.py"].
  mutation_target: `harness.orchestrator` (bare dotted module name).
- Task 2 -- `wireup-detonation-prompt-impl` (meta_task_type: harness_self_fix,
  dependencies: [wireup-detonation-prompt-oracle])
  A `__JANUSMASK_PATCHES__` SYMBOL patch (kind symbol, name `prepare_task_prompt`)
  replacing the existing top-level def in harness/orchestrator.py (1-part top-level
  def -> NO R-anchor). files_touched: ["harness/orchestrator.py"]. regression_tests
  >= 2. harness/orchestrator.py is TRUST-CORE, so this task_id is pinned in
  required_task_ids above so a decision file can be pre-authored out-of-band.

Both tasks' verification_command (bare -- no `cd`, no broad adversarial suite):
`python -m pytest tests/adversarial/test_prepare_task_prompt_detonation_clause.py -q`

# Required plan shape

Two tasks, in this order, both touching the artifacts above.

Task `wireup-detonation-prompt-oracle` (test_authoring, deps []) authors
`tests/adversarial/test_prepare_task_prompt_detonation_clause.py`. It imports
`from harness.orchestrator import prepare_task_prompt` (and `from harness.wire_up
import LIVE_ROOTS`), calls `prepare_task_prompt(task)` DIRECTLY with literal task
dicts (no LLM, no subprocess), and asserts:
  (A) a `test_authoring` task carrying a VALID `constraints.integration_contract`
      (entrypoints a non-empty list all in LIVE_ROOTS, e.g. ["harness/orchestrator.py"];
      symbols non-empty, e.g. ["_save_final_output"]; runtime_oracle a non-empty
      string) -> the returned prompt CONTAINS every detonation marker:
      "LIVE-ROOT DETONATION ORACLE", "executed_with_live_root_ancestor",
      "_drive_run_pipeline", "UNMOCKED", "pure_helper".
  (B) CONTROL: a `test_authoring` task with NO integration_contract -> NONE of the
      detonation markers present, but the base "TEST-AUTHORING DISPATCH" framing
      still PRESENT (no regression to the base clause).
  (C) CONTROL: a non-`test_authoring` task (e.g. meta_task_type harness_self_fix)
      -> none of the detonation markers present.
  (D) TEETH (validity, not just presence): a `test_authoring` task carrying an
      INVALID integration_contract -> NONE of the detonation markers present, base
      "TEST-AUTHORING DISPATCH" framing still PRESENT. Cover, as SEPARATE cases:
      (d1) an entrypoint NOT in LIVE_ROOTS (e.g. ["harness/not_a_live_root.py"]),
      (d2) empty `symbols`, (d3) missing/empty `runtime_oracle`, (d4) empty
      `entrypoints`, (d5) a mixed one-good-one-bad entrypoint list (still invalid).
      This PINS the entrypoints-subset-of-LIVE_ROOTS + non-empty-symbols +
      non-empty-runtime_oracle validity logic; WITHOUT it a presence-only impl
      (`if contract:`) lands as "done" with the validity check absent/wrong.
Name test functions `test_<unit>_<behaviour>`. Import the module under test by
normal import / importlib only -- exec/eval/__import__ are AST-banned in generated
.py. Declare mutation_target `harness.orchestrator`.

# NESTED-QUOTE HAZARD: the impl appends prompt strings that themselves embed code
guidance. In BOTH the oracle and the impl, emit `"""` (triple-double-quote)
docstrings only -- never `'''`, and never backslash-escape quotes. The impl's
appended clause is a Python string literal interpolating contract values; keep its
inner quoting simple (no triple-quote-inside-triple-quote, no `\"`).

mutation_target rationale: the symbol under test (`prepare_task_prompt`) lives in
`harness.orchestrator`; that is the tightest bare dotted module that contains it.
The stub_target gate replaces every function body in `harness/orchestrator.py` with
`raise NotImplementedError` (via `harness.test_author.stub_for`), so the stubbed
`prepare_task_prompt(task)` raises on every call -- assertions (A), (B), and (C)
all error -> vcmd FAILS on the mutant -> non-vacuity satisfied. There is no
finer-grained module to stub (the function is not in a submodule), so
`harness.orchestrator` is both correct and the tightest target.

Task `wireup-detonation-prompt-impl` (harness_self_fix, deps
[wireup-detonation-prompt-oracle]) emits a `__JANUSMASK_PATCHES__` SYMBOL patch
(kind symbol, name `prepare_task_prompt`) reproducing the function VERBATIM except
for ONE addition: inside the existing `if mtt == 'test_authoring':` block, AFTER the
base `prompt += '\nTEST-AUTHORING DISPATCH:...'` line, compute
`contract = (task.get('constraints') or {}).get('integration_contract')`, validate
it (isinstance dict; `contract.get('entrypoints')` a non-empty list with EVERY entry
in LIVE_ROOTS [local import from harness.wire_up]; `contract.get('symbols')`
non-empty; `contract.get('runtime_oracle')` a non-empty string), and when VALID
append a detonation clause as a Python string interpolating the contract's
entrypoints and symbols; when invalid, leave the prompt unchanged. Touch NOTHING
else in prepare_task_prompt. The base "TEST-AUTHORING DISPATCH" framing and all
other branches stay byte-identical. REGRESSION CAVEAT: the scoped vcmd exercises
ONLY the test_authoring branch; the other branches (base prompt, partial_edit,
multi-file `__JANUSMASK_MANIFEST__`, spec_summary tail, repair_feedback) are NOT
covered by this oracle, so a transcription slip in them would pass this vcmd and
surface only in the broad suite -- reproduce the WHOLE function VERBATIM.

The clause text the impl must append (with the contract's entrypoints/symbols
interpolated where natural; embed this guidance verbatim as the prompt content):

  "LIVE-ROOT DETONATION ORACLE (this task carries an integration_contract):
  instead of a hermetic unit test, author a pytest module that, for EACH contract
  symbol, drives the declared LIVE_ROOT entrypoint for ONE bounded iteration with
  the symbol left UNMOCKED, under `with observe_symbol_execution([symbol]) as obs:`
  (from harness.wire_up), and asserts
  `obs.executed_with_live_root_ancestor(symbol, LIVE_ROOTS) is True`. Use the
  canonical driver scaffold `_drive_run_pipeline` from
  tests/harness/test_wire_up_runtime_observe.py VERBATIM (patch every spawn
  collaborator at its source module, return the task once then None, bound the loop
  with a _StopLoop sentinel, and LEAVE THE TARGET SYMBOL UNMOCKED so its real body
  runs via a production call edge). DO NOT call the symbol directly. DETONATION
  NON-VACUITY: declare the symbol's module as mutation_target so the harness
  re-runs this oracle against a stubbed mutant -- the assertion MUST fail when the
  symbol body is replaced by raise NotImplementedError; assert observed execution,
  never a bare True. For any symbol that genuinely cannot detonate from a LIVE_ROOT
  in one bounded iteration, do NOT fabricate a driver -- declare a `pure_helper`
  wire_exempt claim (validated by harness.wire_up.validate_exemption against the
  static floor)."

Integration excuse (restated): this leaf modifies a pure prompt-builder string;
the integration described in the clause is the prompt CONTENT, asserted only via
substring checks on the returned string. No live-env stand-up, no real detonation,
no integration test is required of this leaf.

Both tasks' verification_command is the bare:
`python -m pytest tests/adversarial/test_prepare_task_prompt_detonation_clause.py -q`
The impl's verification_command substring-contains the authored oracle file (it is
the same vcmd), satisfying the red-pair rule. regression_tests on the impl >= 2.
