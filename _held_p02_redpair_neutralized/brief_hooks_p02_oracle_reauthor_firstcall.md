---
slug: p02_oracle_reauthor_firstcall
working_dir: /home/xnihil0zer0/NobleGreedv2
complexity_score: low
required_task_ids:
  - p02-ngv2-oracle-reauthor-firstcall
---

# Title

P0.2-NGv2 — Re-author the jailed-install oracle so its mock subprocess tracks
first-call state in a mutable closure cell, not a class-body NameError

The committed oracle `tests/ngv2/test_poc_runner_jailed_install.py` (authored by a
prior `test_authoring` task, mutation_target `ngv2.poc_runner_live`) is
SELF-CRASHING. Three of its tests build a `class MockCompletedProcess:` whose
class body references the enclosing function's `nonlocal first_call`:

    49  def mock_run(args, **kwargs):
    50      nonlocal first_call
    51      calls.append((args, kwargs))
    52
    53      class MockCompletedProcess:
    54          if 'pip' in str(args):
    55              ...
    58          elif first_call:          # <-- NameError here
    59              ...
    62              first_call = False

Python class-body scope does NOT close over enclosing-function locals, so the
`elif first_call:` evaluates with `first_call` unbound. Running the oracle in the
target venv yields, before the implementation under test is ever exercised:

    tests/ngv2/test_poc_runner_jailed_install.py:58: in mock_run
        class MockCompletedProcess:
    E   NameError: name 'first_call' is not defined

This fires in `test_poc_runner_jailed_install_positive_lockfile` (def line 41,
class line 53, ref line 58) and identically in
`test_poc_runner_jailed_install_lockfile_only_argv` (class 141, ref 146) and
`test_jailed_installation_with_detonation_re_run_pythonpath` (class 212, ref 217).
Because the mock crashes on its own scope bug, the oracle can NEVER pass — it
permanently blocks the implementation task `p02-ngv2-jailed-install-impl` (an impl
cannot satisfy a mock that raises before reaching the code under test). This brief
re-authors the test file so the mock tracks first-call-vs-subsequent-call state in
a MUTABLE CLOSURE CELL read/written inside the mock FUNCTION body, fixing ONLY the
call-tracking scope so the oracle actually runs the production code; every
assertion and the jailed/no-network/lockfile-only + detonation-re-run-PYTHONPATH
intent is preserved verbatim.

# Scope

- Re-author EXACTLY ONE existing file: `tests/ngv2/test_poc_runner_jailed_install.py`.
  Submission is the corrected test file as ordinary Python source (NOT a manifest /
  `__JANUSMASK_PATCHES__` recipe).
- The ONLY behavioral change permitted is fixing the mock's call-tracking scope in
  the three affected tests so the oracle no longer raises NameError before reaching
  the implementation:
  - `test_poc_runner_jailed_install_positive_lockfile`
  - `test_poc_runner_jailed_install_lockfile_only_argv`
  - `test_jailed_installation_with_detonation_re_run_pythonpath`
- In each, replace the class-body `if/elif first_call:` state machine with a mock
  that decides returncode/stdout/stderr from a MUTABLE CLOSURE CELL captured in the
  mock FUNCTION body — e.g. `state = {'first': True}` (or `calls`'s own length, or
  a `list`), read and mutated INSIDE the `def mock_run(...)` body. NEVER reference a
  bare local name inside a `class` body. Construct the return value as a plain
  object (e.g. `types.SimpleNamespace(returncode=..., stdout=..., stderr=...)`, or a
  trivial holder instantiated after the values are computed in the function scope).
  The `nonlocal first_call` / `first_call = True` machinery is removed; the
  equivalent first-vs-subsequent dispatch now lives entirely in the function body.
- PRESERVE every existing assertion in those three tests byte-for-intent: the pip
  call count and `bwrap` / `--unshare-net` argv checks, the `poc_runs` count, the
  `PYTHONPATH` / `JMDEPS_DIRNAME` re-run assertions, the `-r <lockfile>` lockfile-
  only argv checks, the `len(calls) == 3` / `calls[2]` re-run shape, and the
  attacker-name-never-installed intent. Do NOT weaken, delete, or relax any
  assertion to force green.
- Do NOT touch the other (already-correct) tests in the file — negative_control,
  fail_closed_no_lockfile, fail_closed_bwrap_missing, regression tests,
  pip_installer_seam_args, loop_bounded, target_own_package_excluded — beyond what
  re-emitting the whole file requires; their bodies must be reproduced unchanged.

# Non-Goals

- **integration**: this leaf does NOT wire anything into a live `run_hunt` /
  conductor / FSM traversal. Do not touch `transition_planner`, `gate_executor`,
  `conductor_seams`, `run_hunt`, the FSM phase tuples, or `ngv2/workers/**`. The
  oracle proves the installer contract as a unit only; no live-env wiring here.
- Do NOT edit the production module `ngv2/poc_runner_live.py` in this task. This is
  a test-re-authoring leaf only; the implementation that turns the oracle green is
  the separate task `p02-ngv2-jailed-install-impl`.
- No change to `_default_pip_installer`, `detonate_live`, `build_detonation_jail_argv`,
  the success/verdict gate, the FS-snapshot oracle, or the loopback path.
- No new test scenarios, no relaxed assertions, no added skips. The fix is scope-only.

# Inputs

- Target test file (existing, to re-author):
  `tests/ngv2/test_poc_runner_jailed_install.py`.
  - Self-crashing mock pattern at lines 49-67 (positive_lockfile), 137-155
    (lockfile_only_argv), 208-226 (re_run_pythonpath): each defines
    `class MockCompletedProcess:` whose body does `elif first_call:` /
    `first_call = False`, which raises `NameError` because a class body cannot read
    the enclosing function's local `first_call`.
  - Confirmed real failure (target venv):
    `tests/ngv2/test_poc_runner_jailed_install.py:58: NameError: name 'first_call'
    is not defined`, raised inside `test_poc_runner_jailed_install_positive_lockfile`
    at the `class MockCompletedProcess:` statement, BEFORE
    `prl.detonate_live(...)` reaches the production logic.
- Production module under test (UNCHANGED by this task): `ngv2/poc_runner_live.py`
  — exists (~30 KB) and defines all symbols the oracle exercises:
  `detonate_live` (def ~233), `_default_pip_installer` (~434),
  `LiveRunnerError` (~62), `JMDEPS_DIRNAME='_jmdeps'` (~387),
  `MAX_DEP_INSTALL_ROUNDS=3` (~388), `_default_jail_runner` (~447). The mutation
  gate therefore has real mutatable target code — the re-authored oracle stays
  NON-VACUOUS (it must still kill a mutant of `ngv2.poc_runner_live`).
- Correct closure-cell technique (mirror, do not crash on class scope):

      def mock_run(args, **kwargs):
          calls.append((args, kwargs))
          if 'pip' in str(args):
              returncode, stdout, stderr = 0, '', ''
          elif state['first']:
              state['first'] = False
              returncode, stdout, stderr = 1, '', "ModuleNotFoundError: No module named 'regex'"
          else:
              returncode, stdout, stderr = 0, 'VULNERABLE', ''
          return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

  where `state = {'first': True}` is defined in the test body before `mock_run`.
- The oracle imports the generated production code via importlib
  (`spec.loader.exec_module` from `tmp_path`) per the existing `prl` fixture — keep
  that; do NOT use exec/eval/`__import__`.

# Deliverables

1. A re-authored RED-as-appropriate oracle (test_authoring task) at
   `tests/ngv2/test_poc_runner_jailed_install.py`, mutation_target
   `ngv2.poc_runner_live`, in which the three affected tests
   (`test_poc_runner_jailed_install_positive_lockfile`,
   `test_poc_runner_jailed_install_lockfile_only_argv`,
   `test_jailed_installation_with_detonation_re_run_pythonpath`) track
   first-call-vs-subsequent state via a MUTABLE CLOSURE CELL captured in the mock
   FUNCTION body — never a bare name referenced inside a `class` body — so the
   oracle reaches and exercises `prl.detonate_live(...)` instead of self-crashing.
2. Every pre-existing assertion in those three tests is preserved verbatim in
   intent (pip-call count, `bwrap` / `--unshare-net` argv, `poc_runs` count,
   `PYTHONPATH` / `JMDEPS_DIRNAME` re-run, `-r <lockfile>` lockfile-only argv,
   `len(calls) == 3` / `calls[2]` re-run shape). No assertion is weakened, removed,
   or relaxed to force green.
3. The remaining tests in the file (already correct) are reproduced unchanged.
4. The re-authored oracle MUST stay NON-VACUOUS — it must still kill a mutant of
   `ngv2.poc_runner_live` (the mutation gate runs against the real production
   symbols). The corrected oracle stays RED against the current/unfixed production
   path and GREEN once `p02-ngv2-jailed-install-impl` lands, as appropriate; do NOT
   weaken assertions to force a premature green.
5. regression_tests >= 2 — the file already carries `test_regression_*` cases;
   reproduce them unchanged so the regression count is satisfied.

# Required plan shape

Author EXACTLY ONE task. Do NOT decompose; do NOT add a second task.

1. `test_authoring` task — id `p02-ngv2-oracle-reauthor-firstcall`:
   - meta_task_type `test_authoring`, mutation_target `ngv2.poc_runner_live`.
   - `files_touched: ["tests/ngv2/test_poc_runner_jailed_install.py"]`.
   - Submission is the corrected test file as ordinary Python source (NOT a
     `__JANUSMASK_PATCHES__` manifest). The three affected tests must use a mutable
     closure cell in the mock FUNCTION body for first-call dispatch; all other tests
     reproduced unchanged.
   - regression_tests >= 2 (the existing `test_regression_*` cases, unchanged).
   - Imports the generated production module via importlib (`spec.loader.exec_module`
     from `tmp_path`) per the existing `prl` fixture; does NOT use exec/eval/`__import__`.

- **integration** restated: NO live `run_hunt` / FSM / conductor wiring; the oracle
  proves the installer contract as a unit only.
- verification_command (bare, no `cd`):
  `python -m pytest tests/ngv2/test_poc_runner_jailed_install.py -q`
