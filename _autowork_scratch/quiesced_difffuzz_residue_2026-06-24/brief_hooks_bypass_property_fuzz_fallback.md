---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
required_task_ids:
  - bypass-property-fuzz-oracle
  - bypass-property-fuzz-module
  - bypass-property-fuzz-wireup
interfaces: >
  THREE tasks that add a DEFAULT-OFF single-candidate property/metamorphic runtime
  FALLBACK for the fuzzer-bypass path, so "bypass_fuzzer" no longer means "zero
  runtime check beyond the gameable pytest oracle". When differential A/B fuzzing is
  bypassed (mtt in BYPASS_FUZZER_TYPES) the lone accepted candidate (agent_a_code) is
  run OUT-OF-PROCESS in the existing credential-free bwrap jail against conservative
  property invariants (no uncaught exception on adversarial inputs + determinism +
  optional intrinsic metamorphic relations). A real violation BLOCKS the task; a
  clean candidate passes; a ledger event records that the fallback ran so bypass is
  observable. Default-OFF behind autowork.bypass_property_fuzz (OFF == byte-identical
  to HEAD). This is WEAKER than A/B differential divergence and does NOT replace it.

  Task A (bypass-property-fuzz-oracle, test_authoring) -> a RED-first behavioral
  oracle in tests/harness/test_bypass_property_fuzz.py.

  Task B (bypass-property-fuzz-module, harness_self_fix) -> a NEW module
  harness/bypass_property_fuzz.py exposing one public function
  run_bypass_property_fuzz(...) that reuses the OUT-OF-PROCESS jailed sandbox
  executor (sandbox_from_config(...).execute, which after g7-fuzz-jail-credfree is
  the bwrap credential-free seam) and the diff_fuzzer Hypothesis input generator;
  default-OFF reader autowork.bypass_property_fuzz. A NEW module MUST be WIRED, so:

  Task C (bypass-property-fuzz-wireup, harness_self_fix) -> a SYMBOL patch on
  harness/orchestrator_worker.py:main adding a single minimal call to
  run_bypass_property_fuzz inside the existing bypass branch (mirroring the
  run_narrow_fuzz block), so the module is reachable on the live worker path and
  emits a bypass_property_fuzz ledger event. The oracle asserts reachability.
---

# Title
bypass_property_fuzz_fallback — when differential A/B fuzzing is bypassed, run a
DEFAULT-OFF single-candidate property/metamorphic runtime check on the lone accepted
candidate in the existing credential-free jail, block on a real invariant violation,
and emit a ledger event so bypass is no longer a silent zero-runtime-check waiver.

# Scope
THREE tasks. A `test_authoring` oracle (Task A), a NEW-module implementation (Task B),
and a wire-up patch into the live worker path (Task C). READ every file named in
`# Inputs` FIRST.

The behavior added: today the fuzzer-bypass branch in
`harness/orchestrator_worker.py:641` (`if mtt in BYPASS_FUZZER_TYPES or _skip_ifz:`)
runs at most a smoke/embedded/narrow gate (and for the entire `SKIP_SMOKE_GATE_TYPES`
family — `config_schema`, `docs_writing`, `epic_planning`, `harness_plumbing`,
`harness_self_fix`, `hooks_integration`, `mcp_server_change`, `test_*` — it runs NONE
of those three because of the `if mtt not in SKIP_SMOKE_GATE_TYPES` guard at line 642),
then jumps straight to `_save_final_output` + `_auto_commit_accepted`. For those types
the ONLY verification is the per-task pytest oracle, which is gameable (see memory
`p11-already-landed-real-x1-blocker-wiring-gap`: the build_evidence leaf GAMED its
oracle). "bypass_fuzzer" therefore means "trust the oracle, zero runtime check".

This brief makes bypass mean "run a SINGLE-candidate property/metamorphic runtime
check instead" — strictly WEAKER than A/B divergence, but non-zero and observable.
The check executes the lone candidate OUT-OF-PROCESS through the SAME jailed sandbox
executor the differential path uses, so candidate code never runs in-process on the
host and (after `g7-fuzz-jail-credfree`) cannot read host credentials.

# Background — what already exists (REUSE, do not reinvent)
- The factory already uses Hypothesis end-to-end (`harness/diff_fuzzer.py` imports
  `hypothesis`; `config/autocompiler.yaml` and `harness/config.yaml:106` `engine:
  hypothesis`). REUSE `harness.diff_fuzzer.build_input_strategy(code, func_name)` +
  `harness.diff_fuzzer._generate_inputs(strategy, count, seed)` for seeded,
  type-aware `(args, kwargs)` generation — the EXACT generator the differential path
  trusts. Do NOT write a parallel strategy builder.
- The OUT-OF-PROCESS executor is `harness.sandbox.sandbox_from_config(config,
  session_id=...).execute(code, func_name, args=..., kwargs=...) -> ExecutionResult`
  (with `.success`, `.timed_out`, `.exception_type`, `.return_value`,
  `.return_repr`). REUSE it; this is the seam that, after `g7-fuzz-jail-credfree`
  landed, routes candidate spawns through `agent_jail.build_jail_argv(...,
  bind_credentials=False)` — i.e. the credential-free bwrap jail with `--unshare-net`.
  Do NOT add any new subprocess/Popen of your own and NEVER `exec`/`eval`/`compile`
  the candidate in-process (AST-banned anyway).
- `harness.diff_fuzzer.outputs_match(result_a, result_b, float_tol)` compares two
  `ExecutionResult`s. REUSE it for the determinism / metamorphic comparisons.
- There is PROVEN PRIOR ART for an out-of-process single-candidate verdict inside
  `harness/diff_fuzzer.py`: `_one_sided_execute_verdict(side_code, func_name, config,
  session_id, *, count, seed)` (determinism via `sandbox.execute` twice +
  `outputs_match`) and `_one_sided_metamorphic_verdict(...)` (idempotence +
  order/permutation invariance via additional jailed executions). These return
  `'verified'` / `'rejected'` / `'unverified'` and are exactly the shape Task B
  reuses. Task B does NOT edit `diff_fuzzer.py`; it CALLS these existing helpers
  (and `build_input_strategy` / `_generate_inputs` / `outputs_match`) from the new
  module. (The in-process `_metamorphic_oracle` / `_golden_oracle` family in
  `diff_fuzzer.py` calls `fn(*args)` on a LIVE in-process callable — DO NOT reuse
  those for bypassed candidate code; they are not jail-safe. Use ONLY the
  `_one_sided_*_verdict` out-of-process family.)
- The narrow-fuzz path (`harness/narrow_fuzz/`) is the established per-type
  single-candidate hook, but its registry only has `validation`, it only runs for the
  non-`SKIP_SMOKE_GATE_TYPES` slice, and it is per-type opt-in. This brief is the
  type-agnostic complement: it runs for the WHOLE bypass branch (incl. the
  zero-gate `SKIP_SMOKE_GATE_TYPES` family) behind one global flag. It does NOT edit
  or replace `narrow_fuzz`.
- The ledger is `state/impl_progress.jsonl` (per memory
  `p11-already-landed-real-x1-blocker-wiring-gap`); the differential path records fuzz
  outcomes via `orch._persist_fuzz_results(state_dir, task_id, round_label, result)`
  (writes `logs/fuzz_results/<task_id>_<round>.json`) and lifecycle rows via
  `orch._emit_lifecycle(state_dir, event=..., task_id=..., ...)`. The wire-up (Task C)
  emits an analogous `bypass_property_fuzz` lifecycle row so the fallback is
  observable in the same channel as `gate_failed` / `phase_transition`.

# The fallback design (Task B module)
`harness/bypass_property_fuzz.py` exposes ONE public function:

    def run_bypass_property_fuzz(
        mtt: str,
        candidate_code: str,
        task: dict,
        config: dict,
        session_id: str = "bypass_prop",
    ) -> str | None

Contract (the GENERAL behavior, NOT fixture-matching):
1. FLAG GATE (default-OFF): read `autowork.bypass_property_fuzz` via a fail-safe
   reader that imports `load_config` INSIDE the function and returns False on ANY
   error (mirror `diff_fuzzer._onesided_metamorphic_enabled`). When the flag is
   absent/False, return `None` IMMEDIATELY (no execution at all) — OFF is
   byte-identical to HEAD.
2. TARGET RESOLUTION: derive the function name to exercise the SAME way the
   differential path does — from `task['constraints']['function_signature']`
   (`re.match(r'def\s+(\w+)\s*\(', sig)`) if present, else
   `diff_fuzzer._get_primary_function(candidate_code)`. If no callable function can
   be resolved, or `build_input_strategy` cannot be built, or zero inputs are
   generated, return `None` (NOT-APPLICABLE skip — non-functional / structural-only
   bypass output genuinely has no callable interface to property-check; this is a
   documented skip, not a pass). Use the existing
   `diff_fuzzer.build_input_strategy` + `diff_fuzzer._generate_inputs` with
   `count` / `seed` read from `config['fuzzing']` (`function_level_inputs`, `seed`)
   — bound `count` modestly (e.g. `min(count, 200)`) so the fallback stays cheap.
3. PROPERTY CHECKS (all OUT-OF-PROCESS via the existing jailed sandbox executor):
   delegate to `diff_fuzzer._one_sided_execute_verdict(candidate_code, func_name,
   config, session_id, count=count, seed=seed)` (determinism: same seeded input run
   twice via `sandbox.execute` must `outputs_match`). If that verdict is
   `'verified'` AND `autowork.bypass_property_metamorphic` (a SECOND default-OFF
   sub-flag, same fail-safe reader pattern) is ON, ALSO delegate to
   `diff_fuzzer._one_sided_metamorphic_verdict(...)` (idempotence + order-invariance,
   each self-guarded so a faithful body is never falsely flagged).
   - `'rejected'` (a determinism or metamorphic violation) -> return a descriptive
     NON-EMPTY error string (e.g. `"bypass_property_fuzz: candidate <func> violated
     the out-of-process determinism relation"`). This is the BLOCK signal.
   - `'unverified'` -> return `None` (fail-OPEN to today's behavior for the
     not-applicable case; the candidate could not be exercised, so the fallback adds
     nothing and must NOT regress a previously-green bypass task into a hard block on
     an unbuildable strategy). NOTE: this differs from the differential path's
     fail-CLOSED stance because this is an ADDITIVE single-candidate overlay on a
     path that has NO runtime check today — turning an unverifiable candidate into a
     REJECT would be a throughput regression with no trust gain. State this tradeoff
     explicitly. (A future flag could flip `unverified` to fail-closed; out of scope.)
   - `'verified'` -> return `None` (pass).
4. FAIL-SOFT: wrap the whole body so ANY unexpected exception returns `None` (the
   fallback must NEVER crash the worker or convert an infra hiccup into a spurious
   block). The ONLY way it returns a non-None string is a real `'rejected'` verdict.
5. NO in-process candidate execution: the module imports NOTHING that runs the
   candidate in-process; all execution is the existing `sandbox.execute` seam.
   Do NOT add `subprocess`/`Popen`/`exec`/`eval`/`compile`/`__import__` of candidate
   code in this module.

# The wire-up (Task C — orchestrator_worker.py:main)
A NEW module that nothing calls is an ORPHAN and is NOT done (memory
`implementation-is-not-wired-defect`). Task C wires `run_bypass_property_fuzz` into
the live worker bypass branch via a `__JANUSMASK_PATCHES__` SYMBOL patch keyed on the
top-level `main` (AST-merge replaces the FunctionDef `main` by name; every other
top-level node in `orchestrator_worker.py` stays byte-identical). The patch makes
EXACTLY these additive changes inside `main`, and NOTHING else:

1. Add `from harness.bypass_property_fuzz import run_bypass_property_fuzz` to the
   in-body lazy-import block that already imports `run_narrow_fuzz` (the block at
   ~line 252-256, inside the `with contextlib.redirect_stderr(...)` try). Keep it a
   LAZY in-body import (no new module-top import), matching the existing imports.
2. Inside the `if mtt in BYPASS_FUZZER_TYPES or _skip_ifz:` block (line 641), AFTER
   the existing smoke/embedded/narrow gate sub-block (i.e. AFTER line 694's
   `narrow_err` handling, OUTSIDE and below the `if mtt not in SKIP_SMOKE_GATE_TYPES
   and not _skip_ifz:` guard so it runs for the WHOLE bypass branch incl. the
   zero-gate `SKIP_SMOKE_GATE_TYPES` family), BEFORE the
   `_detect_and_append_untracked_tests` / `_save_final_output` lines (695-696), add a
   minimal block that MIRRORS the `run_narrow_fuzz` block:

       prop_err = run_bypass_property_fuzz(mtt, agent_a_code, task, config, session_id=f'{task_id}_bypassprop')
       orch._emit_lifecycle(state_dir, event='bypass_property_fuzz', task_id=task_id, mtt=mtt, blocked=bool(prop_err), detail=(str(prop_err)[:2000] if prop_err else 'pass_or_skip'))
       if prop_err is not None:
           set_phase(state_dir, phase='rejected')
           orch._emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
           _emit_gate_failure(state_dir, task_id, 'bypass_property_fuzz', prop_err)
           orch._mark_blocked(state_dir, task_id, 'bypass_property_fuzz_failed')
           orch._emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
           _print_json_line({'task_id': task_id, 'outcome': 'rejected', 'reason': 'bypass_property_fuzz_failed'})
           exit_code = 1
           return exit_code

   (Use `_emit_gate_failure`, `set_phase`, `orch._mark_blocked`, `_print_json_line`,
   `exit_code`, and the `f'{task_id}_...'` session naming EXACTLY as the surrounding
   gate blocks already do — they are all in scope inside `main`.) The unconditional
   `bypass_property_fuzz` lifecycle emit (always, even on pass/skip) is the
   observability requirement: it makes "the fallback ran" visible in the ledger.
3. Change NOTHING else in `main`. The OFF flag makes `run_bypass_property_fuzz`
   return `None` immediately, so the only added behavior on the default path is the
   single `bypass_property_fuzz` lifecycle row with `blocked=False detail='pass_or_skip'`
   — byte-equivalent OUTCOME to HEAD (still falls through to `_save_final_output` /
   `_auto_commit_accepted`).

# Inputs (READ FIRST in /home/xnihil0zer0/JanusMaskJR)
- `harness/orchestrator_worker.py` — the bypass branch (lines 641-726). The hook
  goes between line 694 (end of `narrow_err` handling) and line 695
  (`_detect_and_append_untracked_tests`), at the bypass-branch top indent. `main` is
  a ~682-line top-level FunctionDef (line 220); the patch replaces it by AST name
  merge. `_emit_gate_failure` (line 216) and the in-body lazy-import block (252-256)
  are the seams. `orchestrator_worker.py` is NOT in `_NEVER_AUTO_APPROVE` ->
  auto-approve-eligible, no decision file needed.
- `harness/diff_fuzzer.py` — REUSE (do NOT edit): `build_input_strategy` (~445),
  `_generate_inputs` (~665), `_get_primary_function` (~725), `outputs_match` (~469),
  `_one_sided_execute_verdict` (~972), `_one_sided_metamorphic_verdict` (~1059),
  `_onesided_metamorphic_enabled` (~1043, the fail-safe-reader pattern to COPY for
  the new flag readers). `FuzzResult` shape at ~56.
- `harness/sandbox.py` — REUSE (do NOT edit): `sandbox_from_config(config,
  session_id=...).execute(...)`. This is the jailed cred-free executor after
  `g7-fuzz-jail-credfree`. Task B reaches it ONLY indirectly via the
  `_one_sided_*_verdict` helpers.
- `harness/agent_jail.py` — READ for context only (DO NOT edit; it is in
  `_NEVER_AUTO_APPROVE`). `build_jail_argv(..., bind_credentials=False)` is the
  credential-free seam the sandbox executor already routes through.
- `harness/planner/taxonomies.py` — READ for context only (DO NOT edit).
  `BYPASS_FUZZER_TYPES` / `SKIP_SMOKE_GATE_TYPES` define which types reach the hook.
- `harness/config.yaml` — READ for context only (DO NOT edit). The new flags
  `autowork.bypass_property_fuzz` and `autowork.bypass_property_metamorphic` are NOT
  added to config.yaml by this brief — they ship ABSENT, which the fail-safe readers
  treat as OFF (default-OFF without touching prod config; flipping them on is a later
  operator decision after empirical proof). The oracle asserts the readers return
  False when the key is absent.
- `harness/narrow_fuzz/__init__.py` / `validation.py` — READ for context only (DO
  NOT edit). Shows the established jailed single-candidate gate shape and the
  `run_narrow_fuzz` block this hook mirrors.

# Non-Goals (HONEST — integration is OUT OF SCOPE; the literal word `integration` is
required in this section and in EACH task's `non_goals`)
- This does NOT replace differential A/B fuzzing where two genuinely independent
  candidates exist. Differential divergence is STRICTLY STRONGER; this single-
  candidate check is a FALLBACK that runs ONLY when A/B is bypassed by policy.
- WHAT IT CATCHES: non-determinism / impurity (same input -> different output across
  runs), candidate crashes / uncaught exceptions that differ across runs, and (with
  the metamorphic sub-flag) violations of intrinsic relations the candidate's own
  output must satisfy (idempotence `f(f(x))==f(x)` where the result is feedable,
  order/permutation invariance `f(xs)==f(reversed(xs))` where the first arg is a
  list). It also exercises the function on adversarial Hypothesis-generated inputs.
- WHAT IT CANNOT CATCH (be honest): a candidate that is DETERMINISTICALLY WRONG vs
  the spec (computes a consistent wrong answer) passes every property here — there is
  no spec/reference oracle, so a wrong-but-consistent implementation is NOT flagged.
  It cannot catch the two-distinct-but-both-wrong class (the p11 build_evidence
  exploit) — that needs a held-out SPEC reference, which is a separate design. It
  cannot property-check structural-only / non-functional bypass output (docs,
  config-schema declarations, hook glue) — those resolve to no callable interface and
  are a documented SKIP (return None), not a false pass. It cannot catch crashes that
  occur ONLY for inputs Hypothesis did not draw within the bounded budget.
- This does NOT flip the new flags ON in production config; default-OFF ships, the
  cutover is a later operator decision after empirical proof (BUILT != WORKS, per
  memory `dont-conflate-built-with-works`). The integration/activation in production
  is explicitly OUT OF SCOPE; only the BUILT+WIRED+default-OFF capability is in scope.
- This does NOT edit `harness/diff_fuzzer.py`, `harness/sandbox.py`,
  `harness/agent_jail.py`, `harness/planner/taxonomies.py`, `harness/config.yaml`,
  `harness/narrow_fuzz/**`, or any `_NEVER_AUTO_APPROVE` file. It does NOT change
  `BYPASS_FUZZER_TYPES` / `SKIP_SMOKE_GATE_TYPES` / `META_TASK_POLICY`. It does NOT
  add a new subprocess/Popen/exec/eval of candidate code anywhere.
- This does NOT alter the `run_narrow_fuzz` / smoke / embedded gates, the
  `FuzzResult` dataclass, the input-strategy builder, or `_generate_inputs`.

# Deliverables

## TASK A — bypass-property-fuzz-oracle (tests/harness/test_bypass_property_fuzz.py)
The RED-first behavioral oracle. `meta_task_type: test_authoring`. Submit the test
source DIRECTLY as ordinary Python (NO `__JANUSMASK_PATCHES__` / `__JANUSMASK_MANIFEST__`
marker). `mutation_target: harness.bypass_property_fuzz` (dotted MODULE, not a function).

ANTI-GAMING ORACLE REQUIREMENTS (derive expectations from BEHAVIOR/semantics; NEVER
assert against a frozen literal; NEVER pass by special-casing a known input string;
NO answer-key leakage — the oracle MUST drive the REAL module/sandbox, not a mock of
the unit under test):

1. DEFAULT-OFF: with NO `autowork.bypass_property_fuzz` key set (absent config),
   assert the module's flag reader returns `False` AND
   `run_bypass_property_fuzz('orchestration', <any candidate code>, task, config)`
   returns `None` WITHOUT executing the candidate (i.e. OFF is a no-op). This must be
   true on a config dict that omits the key entirely.
2. FLAG ON -> BUGGY CANDIDATE FLAGGED: with the flag turned ON (pass a config whose
   `autowork.bypass_property_fuzz` is True, via the same mechanism the fail-safe
   reader consults — e.g. a temporary config the reader loads, OR monkeypatch the
   reader to True so the test exercises the EXECUTING path, not the gate), submit a
   single candidate whose target function is NON-DETERMINISTIC (e.g. returns
   `random.random()` or reads a mutable module global that changes between calls) and
   assert `run_bypass_property_fuzz(...)` returns a NON-EMPTY error string (the
   determinism violation is FLAGGED). This must FAIL on HEAD (the module does not
   exist / the wire-up is absent) and pass after.
3. FLAG ON -> CLEAN CANDIDATE PASSES (non-vacuity, MANDATORY): with the flag ON,
   submit a clean deterministic pure candidate (e.g. `def f(x: int) -> int: return x
   + 1`) and assert `run_bypass_property_fuzz(...)` returns `None` (passes). A
   purely-negative (only-flags-the-buggy-one) oracle is vacuous and will be rejected
   — this clean-pass case is the load-bearing non-vacuity catch (it also proves the
   sandbox round-trip actually executed, not that everything errored to None).
4. RUNS IN THE CREDENTIAL-FREE JAIL: assert the candidate is executed OUT-OF-PROCESS
   via the real sandbox executor and CANNOT read host credentials. Submit a candidate
   whose target function body does
   `open(os.path.expanduser("~/.gemini/oauth_creds.json")).read()` (and/or
   `~/.claude/.credentials.json`) and returns the bytes; with the flag ON, assert the
   value the property check obtained does NOT equal the real host credential bytes
   (read the real file on the host first and assert those exact bytes are NOT what the
   sandboxed candidate returned), OR that the candidate execution failed
   (FileNotFoundError / SandboxError) inside the jail. SKIP-GUARD this assertion:
   `import shutil; if shutil.which('bwrap') is None: pytest.skip('bwrap unavailable')`
   so it is a clean SKIP on a no-bwrap host and a real RUN where bwrap exists. This
   proves the fallback inherits the jail (it reuses `sandbox.execute`, the cred-free
   seam) and does NOT run candidate code in-process.
5. WIRE-UP REACHABILITY (proves the module is NOT an orphan): assert that
   `harness.orchestrator_worker` imports/calls `run_bypass_property_fuzz` on the
   bypass path. Prove this BEHAVIORALLY, not by grepping source: drive the real
   worker bypass branch with the flag ON for a bypassed mtt (e.g. via
   `orchestrator_worker.main` against a real staged task whose `meta_task_type` is in
   `BYPASS_FUZZER_TYPES`, OR by monkeypatching `harness.bypass_property_fuzz.
   run_bypass_property_fuzz` to a spy and asserting the spy was CALLED with the
   candidate code + mtt when the worker takes the bypass branch). Assert a
   `bypass_property_fuzz` lifecycle event is written to the ledger for that task. The
   reachability assertion MUST fail before Task C lands and pass after — it is the
   anti-orphan teeth.
6. LEDGER EVENT: assert that when the fallback BLOCKS, a `bypass_property_fuzz`
   row with `blocked=True` (and a `gate_failed` row with `gate='bypass_property_fuzz'`)
   is emitted, and the task outcome is `rejected` with reason
   `bypass_property_fuzz_failed`; and when it passes/skips, a `bypass_property_fuzz`
   row with `blocked=False` is still emitted (observability on the happy path).

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: bypass-property-fuzz-oracle`
- `priority: critical`
- `meta_task_type: test_authoring`
- `mutation_target: harness.bypass_property_fuzz`
- `files_touched: ["tests/harness/test_bypass_property_fuzz.py"]`
- `dependencies: []`
- `verification_command:` SCOPED to the new oracle only (the impl modules do not
  exist yet, so this is RED-first):
  `python -m pytest tests/harness/test_bypass_property_fuzz.py -q`
  (do NOT use a broad `pytest tests/adversarial/ -q` vcmd — it is non-hermetic and
  flaky-blocks). The oracle is RED on HEAD.

## TASK B — bypass-property-fuzz-module (harness/bypass_property_fuzz.py)
The NEW module. `meta_task_type: harness_self_fix`. Emit ordinary new-module Python
(this is a brand-new file; submit it as a whole new module — there is no existing
symbol to patch). Implement EXACTLY the contract in "The fallback design" above:
`run_bypass_property_fuzz(mtt, candidate_code, task, config, session_id='bypass_prop')`,
two fail-safe flag readers (`_bypass_property_fuzz_enabled` and
`_bypass_property_metamorphic_enabled`, each COPYING the
`diff_fuzzer._onesided_metamorphic_enabled` pattern: import `load_config` in-body,
return False on ANY exception), target resolution reusing
`diff_fuzzer.build_input_strategy` / `_get_primary_function`, and delegation to
`diff_fuzzer._one_sided_execute_verdict` (+ optionally
`_one_sided_metamorphic_verdict`). Fail-soft top-level try/except returns None. NO
in-process candidate execution; NO new subprocess/Popen/exec/eval; all imports of
`diff_fuzzer` helpers are lazy in-body (keeps the module-load surface clean and avoids
any import cycle).

GENERALITY: the module must work for ANY resolvable callable, not a fixture. It must
return None (skip) when no callable interface exists, return a non-empty string ONLY
on a real `'rejected'` verdict, and never raise.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: bypass-property-fuzz-module`
- `priority: critical`
- `meta_task_type: harness_self_fix`
- `files_touched: ["harness/bypass_property_fuzz.py"]`
- `dependencies: ["bypass-property-fuzz-oracle"]` (impl runs after its oracle)
- OMIT `mutation_target`. `spec_author: null`.
- `verification_command:`
  `python -m pytest tests/harness/test_bypass_property_fuzz.py -q`
  Run the EXACT vcmd before dispatch; confirm `N passed` with N>=2 for the unit-level
  and module-level subtests (the wire-up reachability subtest may still be RED until
  Task C lands — see "Required plan shape" for the dependency ordering note).

## TASK C — bypass-property-fuzz-wireup (harness/orchestrator_worker.py)
The wire-up. `meta_task_type: harness_self_fix`. Emit a `__JANUSMASK_PATCHES__` SYMBOL
patch keyed on the top-level `main` (AST-merge replaces `main` by name; every other
top-level node stays byte-identical). Make ONLY the three additive changes in "The
wire-up" above: (1) add the lazy in-body import of `run_bypass_property_fuzz`
alongside `run_narrow_fuzz`, (2) add the minimal `prop_err` call block + ledger emits
inside the bypass branch after the narrow-fuzz sub-block and outside the
`SKIP_SMOKE_GATE_TYPES` guard, (3) change nothing else. Do NOT emit
`__JANUSMASK_MANIFEST__` (single existing symbol -> patches). Keep `main`'s signature
`def main() -> int:` byte-identical and every other line of `main` byte-identical
except the additive import + the inserted block.

GENERALITY: the inserted block must call `run_bypass_property_fuzz` for EVERY mtt that
reaches the bypass branch (it is type-agnostic; the per-type applicability is decided
INSIDE the module by target resolution), and must use the existing in-scope helpers
(`_emit_gate_failure`, `set_phase`, `orch._mark_blocked`, `_print_json_line`,
`exit_code`). Do NOT key the block on a specific mtt or task_id.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: bypass-property-fuzz-wireup`
- `priority: critical`
- `meta_task_type: harness_self_fix`
- `files_touched: ["harness/orchestrator_worker.py"]`
- `dependencies: ["bypass-property-fuzz-module"]` (wire-up runs after the module exists)
- OMIT `mutation_target`. `spec_author: null`.
- Emit a `__JANUSMASK_PATCHES__` SYMBOL patch keyed on `main`.
- `verification_command:` SCOPED to the oracle (now fully GREEN incl. reachability)
  AND a slice of the existing worker suite that must stay green, e.g.
  `python -m pytest tests/harness/test_bypass_property_fuzz.py tests/test_orchestrator_worker_bypass.py -q`
  (if no such existing worker-bypass test file exists, substitute the actual existing
  scoped test that exercises the bypass branch — discover it before dispatch; do NOT
  use a broad `pytest tests/adversarial/ -q` vcmd). Run the EXACT vcmd before
  dispatch; confirm `N passed` with N>=2 and that the worker-bypass regression slice
  is NOT regressed.

# Required plan shape
Emit EXACTLY THREE tasks (pin via `required_task_ids:
[bypass-property-fuzz-oracle, bypass-property-fuzz-module, bypass-property-fuzz-wireup]`).
PRIORITY MUST be canonical lowercase `critical` (NEVER P0/P1/ints/Capitalized).
Dependency chain: oracle <- module <- wireup (the daemon runs them in that order; the
oracle is RED-first, the module makes the unit subtests green, the wireup makes the
reachability subtest green). Each task edits exactly ONE file as declared in its
`files_touched`; do NOT add a task touching any other file (NO edit to
`diff_fuzzer.py`, `sandbox.py`, `agent_jail.py`, `taxonomies.py`, `config.yaml`,
`narrow_fuzz/**`). Each task's `non_goals` MUST contain the literal word
`integration`; each `regression_tests >= 2`.

`harness/bypass_property_fuzz.py` and `harness/orchestrator_worker.py` are both
`harness/**` and NEITHER is in the irreducible `_NEVER_AUTO_APPROVE` set
(`agent_jail.py`, `dbus_proxy.py`, `paths.py`, `git_integration.py`, `orchestrator.py`,
`interceptors.py`, `selfheal.py`, `autowork_daemon.py`, `services/**`), so both tasks
are auto-approve-eligible `harness_self_fix` edits and need no
`state/control/decisions/<task_id>.json` file.
