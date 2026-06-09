# WIRE-UP PHASE RESEARCH #3 — Oracle / Embedded-Test Gate Enforcement

Goal: understand how the oracle gate runs so we can REQUIRE a *wiring-assertion*
oracle (one that proves the new module is reachable on the live code path), and
have the gate REJECT a leaf whose only test is an isolated unit test.

All citations are absolute `file:line`.

---

## 1. How the embedded-test / smoke / narrow gate works

There are TWO distinct "test runs" in the pipeline, and they are easy to confuse.
Only ONE of them is the real wiring lever.

### 1a. The bypass-path embedded gate (runs the candidate's OWN inline tests)

`harness/embedded_test_runner.py:52` `should_run_embedded_tests(module_src)`:
- Parses the candidate **module source string** with `ast.parse`.
- Returns `True` iff the source declares a top-level `def test_*` that is a
  *runnable* pytest target (every required param is `self` or a known pytest
  builtin fixture — `embedded_test_runner.py:103` `_is_runnable_test_function`)
  OR a top-level `class Test*`. Names opted out with `<name>.__test__ = False`
  are ignored (`:119-131`). This carve-out exists because NGv2 leaves expose API
  helpers literally named `test_tool` / `test_file_against_parser`
  (`:64-72`) that must NOT trip the gate.
- `run_embedded_tests` (`:159`) writes the source to a tempdir and runs
  `pytest --collect-only` then `pytest -x` under a scrubbed/jailed subprocess
  (`:237-336`); returns `None` on pass, an error string on fail.

Call site — the **bypass branch** of the worker loop in
`harness/orchestrator.py:3625-3675`:
```
if _should_bypass_or_route_task(task, config) == 'bypass':
    if mtt not in SKIP_SMOKE_GATE_TYPES and not _skip_ifz:
        smoke_err    = smoke_import('_smoke_candidate', claude_code)        # :3627
        embedded_err = run_embedded_tests('_embedded_candidate', claude_code) # :3649
        narrow_err   = run_narrow_fuzz(mtt, '_narrow_fuzz_candidate', ...)    # :3667
```
- `_should_bypass_or_route_task` (`orchestrator.py:3395`) returns `'bypass'` when
  the `meta_task_type` is fuzzer-bypass-eligible (e.g. `data_model`,
  `test_authoring`). `SKIP_SMOKE_GATE_TYPES` / `META_TASK_POLICY` are imported
  from `harness/planner/taxonomies.py` (`orchestrator.py:3832-3833`).
- **KEY LIMITATION**: this gate only runs the test code that the candidate
  module *itself contains* as a string. It NEVER imports the rest of the repo.
  It cannot observe whether the new module is wired into a live entrypoint — it
  is a self-contained, isolated assertion. This is precisely the orphan blind
  spot. (Memory: W64 silent-canary motivation, `embedded_test_runner.py:1-29`.)

### 1b. The committed-oracle gate (runs a SEPARATE oracle test file) — the real lever

This is the path that already CAN assert wiring, because the oracle is a real
repo test file that may import anything.

- Flow: a `test_authoring` task commits an oracle file FIRST; the sibling impl
  task's `verification_command` names that oracle file; when the impl lands, the
  oracle is run against a fresh checkout of parent-HEAD + the staged module.
- Execution site: `harness/git_integration.py:1657`:
  ```
  proc = subprocess.run([sys.executable, '-m', 'pytest', '-p','no:cacheprovider',
                         '-q', *gate_rel], cwd=tmp_dir, env=env, timeout=timeout_sec)
  return proc.returncode == 0
  ```
  - `gate_rel` is the list of pytest paths derived from the impl task's
    `verification_command` (`git_integration.py:1648`).
  - The run happens inside a `git archive` extraction of `parent_head_sha`
    (`:1639-1644`) with the **staging worktree on `PYTHONPATH`** (`:1654-1655`),
    so the oracle imports the REAL repo plus the staged change.
  - **Fail-closed**: returns `True` only on `rc==0`; on the failure path the
    auto-commit is rolled back (`git reset --hard HEAD~1`, see the rollback
    blocks in `_auto_commit_accepted`).

This 1b path is where a wiring-assertion oracle becomes enforceable: the oracle
can `from <live_entrypoint> import ...`, invoke it, and assert the new module is
actually reached.

---

## 2. `_stage_targets` — how the blind worker sees the oracle contract

`harness/orchestrator.py:4338` `_stage_targets(inbox, state_path, task_json)`
(note: memory said ~:4275 — actual location is 4338; line numbers drifted):
- Resolves `files_touched` (walking the parent chain) and `shutil.copy2`'s each
  existing repo file into `inbox/targets/<rel>` as read context (`:4371-4388`).
- For `test_authoring` tasks with a non-empty `mutation_target`, it ALSO stages
  the module-under-test so the oracle author sees the real interface
  (`:4365-4368`):
  ```
  if meta_task_type == 'test_authoring' and isinstance(mt, str) and mt:
      rel = mt.replace('.', '/') + '.py'
      if rel not in rels: rels.append(rel)
  ```
- It copies the **working-tree** file, not HEAD (memory note confirmed).

### Oracle SOURCE injected into spec.implementation_notes (blind worker can't read it)

`harness/planner/plan_normalizer.py:279` `_inject_oracle_sources(plan, repo_root)`:
- For every non-`test_authoring` task with a dict `spec` and a non-empty
  `verification_command`, it resolves each `.py` token in the vcmd under
  `repo_root`, reads the file, and APPENDS it verbatim to
  `spec['implementation_notes']` under the literal marker
  `COMMITTED ORACLE CONTRACT` (`:312-339`):
  ```
  block = '\n\n# COMMITTED ORACLE CONTRACT (authoritative; you cannot read these
           files at synthesis time so they are reproduced verbatim -- your code
           MUST make them pass):\n'
  ```
- Idempotent (skips if marker already present, `:313`); pure no-op when
  `repo_root is None`.
- This is how the jailed blind worker — which only mounts `inbox/brief.json` —
  receives the exact assertions it must satisfy. **A wiring-assertion oracle is
  injected here verbatim, so the worker is told to make the live wiring real.**

---

## 3. How oracle test files are discovered (`tests/**/test_<leaf>.py`)

`harness/planner/plan_normalizer.py:179`
`_sanitize_impl_verification_commands(plan, repo_root)`:
- Builds `oracle_files` = union of `files_touched` over all `test_authoring`
  tasks (`:219-224`).
- For each impl task whose `verification_command` references an oracle file,
  it computes the impl's importable target leaf module names, then globs
  (`:256-257`):
  ```
  for match in root.glob('tests/**/test_' + leaf + '.py'):
  ```
  Matches recorded as repo-relative posix paths, excluding `oracle_files`,
  deduped + sorted. If found, the impl's vcmd becomes
  `python -m pytest <existing_tests> -q` (`:268`); else falls back to a
  smoke-import of the modules (`:271`) or token-strip (`:273-277`).

So a leaf's oracle is conventionally `tests/**/test_<leaf>.py` and the impl's
gate is rewired to run exactly that file.

### Sanitize: impls vs real test files
The "sanitize" memory note refers to `_sanitize_impl_verification_commands`
above (it rewrites a bare/oracle-referencing vcmd to run *real existing test
files* `tests/**/test_<leaf>.py`, never a bare `pytest`, `:197-198`).
Plan-time schema enforcement lives in `harness/planner/plan_validator.py`:
- `test_authoring` tasks must declare `mutation_target` / `mutations[]` so the
  non-vacuity gate can fail-detect (`plan_validator.py:114-122`).
- `verification_command` must be a non-empty string (`:39-41`,
  `validate_plan_wrapper` hard-raises at `:374-377`).

---

## 4. What a WIRING-ASSERTION test looks like — existing examples (the P6 hook)

The P6 PreToolUse hook is the proven precedent. Its oracles do NOT test the hook
module in isolation — they import the **live entrypoint** (`turn_runner.make_seams`,
which is the function the chat loop actually calls) and assert it WIRES the new
module (`procedure_hook`) into the spawn.

### Example A — registration wiring: `tests/overseer/test_make_seams_hook_registration.py`

The live entrypoint is `overseer/turn_runner.py:99` `make_seams(...)`, which at
`turn_runner.py:137-139` writes `procedure_hook.SETTINGS_FRAGMENT` to
`work_dir/.claude/settings.json`, and at `:218-222` (`env_builder`) exports the
live phase. The oracle imports `make_seams` (the live producer) and asserts the
artifact:

```python
# tests/overseer/test_make_seams_hook_registration.py:64-69
def test_make_seams_writes_settings_with_hook_fragment(tmp_path, monkeypatch):
    """make_seams writes procedure_hook.SETTINGS_FRAGMENT to work_dir settings."""
    _seams, work = _make(tmp_path, monkeypatch)              # calls make_seams()
    settings = work / ".claude" / "settings.json"
    assert settings.exists(), "make_seams must register the hook via settings.json"
    assert json.loads(settings.read_text()) == procedure_hook.SETTINGS_FRAGMENT
```
and the phase-export wiring (`:47-61`):
```python
def test_env_builder_exports_live_procedure_phase(tmp_path, monkeypatch):
    (_, env_builder, _, _), _work = _make(tmp_path, monkeypatch)  # from make_seams
    env = env_builder({"procedure_phase": "ORACLE"})
    assert env["JANUSMASK_PROCEDURE_PHASE"] == "ORACLE"
```

**The wiring pattern**: import the LIVE producer (`make_seams`) → call it the way
the runtime does → assert the side effect that connects the new module
(`SETTINGS_FRAGMENT` written, `JANUSMASK_PROCEDURE_PHASE` exported). An orphaned
`procedure_hook.py` (present on disk but not registered by `make_seams`) FAILS
`test_make_seams_writes_settings_with_hook_fragment`. A pure unit test of
`procedure_hook.decide` alone could NOT catch that.

### Example B — behavior-change wiring: `tests/overseer/test_procedure_hook_env_phase.py`

Asserts the consumer's behavior changes because of the live env contract
(`decide` reads `JANUSMASK_PROCEDURE_PHASE`):
```python
# tests/overseer/test_procedure_hook_env_phase.py:17-24
def test_env_phase_blocks_out_of_phase_brief_write(monkeypatch):
    monkeypatch.setenv("JANUSMASK_PROCEDURE_PHASE", "SCOPE")
    decision = decide({"tool_name": "Write",
                       "tool_input": {"file_path": "brief_hooks_x.md"}})
    assert decision["decision"] == "block"
```
This is the "live function's behavior changes" flavor: the only reason `decide`
blocks is that the live env contract (set by `make_seams`) feeds it the phase.

Both examples are explicitly described in their docstrings as proving the module
is "inert unless ... REGISTERED into the spawn"
(`test_make_seams_hook_registration.py:1-19`).

---

## RECOMMENDED WIRING-ASSERTION CONTRACT

### Definition
A leaf's oracle set MUST contain at least one **wiring-assertion test**: a test
that (a) imports a LIVE entrypoint module (NOT the new leaf module by itself),
and (b) asserts that calling/inspecting that entrypoint reaches the new module —
via one of three shapes:

1. **Registration / dispatch-table assertion** — the live registry, hook
   fragment, settings, route table, or dispatch dict contains the new module's
   symbol after the live setup function runs.
   (e.g. `make_seams` writes `SETTINGS_FRAGMENT` → `settings.json`.)
2. **Call-edge assertion** — the live function, when invoked, calls the new
   module (assert via real side effect, or a `monkeypatch`/spy on the new
   module's entry function showing it was invoked on the live path).
3. **Behavior-change assertion** — the live function's output changes *because*
   the new module participates (the orphan baseline produces a different,
   wrong result).

### Concrete example oracle (shape 1 + 2, the strongest)

```python
# tests/<area>/test_<leaf>_wired.py
"""WIRING ORACLE for <leaf>: prove <leaf> is reachable from the LIVE entrypoint.

A pure unit test of <leaf> passing in isolation is NOT sufficient: this module
is inert until <live_entrypoint> dispatches to it. This oracle imports the live
entrypoint and asserts the live dispatch path actually reaches <leaf>.
"""
from <live_entrypoint_pkg> import live_entrypoint          # the function the runtime calls
from <area> import <leaf>                                   # the new module

def test_live_entrypoint_registers_leaf():
    # shape 1: the live setup populates a dispatch/registry with the new symbol
    table = live_entrypoint.build_dispatch_table()          # the REAL builder
    assert "<leaf_handler_key>" in table
    assert table["<leaf_handler_key>"] is <leaf>.handler

def test_live_entrypoint_invokes_leaf(monkeypatch):
    # shape 2: drive the live entrypoint the way the runtime does; assert the
    # new module's entry function is actually called (spy on the LEAF, not a mock
    # of the entrypoint).
    calls = []
    monkeypatch.setattr(<leaf>, "handler", lambda *a, **k: calls.append((a, k)) or "OK")
    out = live_entrypoint.run(<representative_live_input>)   # NO mock of the seam
    assert calls, "live entrypoint never dispatched to <leaf> -- module is ORPHANED"
    assert out == "OK"
```

Rationale tied to the gate:
- This oracle file is committed by a `test_authoring` task; its source is
  injected verbatim into the impl's `spec.implementation_notes` under
  `COMMITTED ORACLE CONTRACT` (`plan_normalizer.py:333`), so the blind worker is
  told it must ALSO edit `<live_entrypoint>` to register/dispatch the leaf.
- It runs at `git_integration.py:1657` against the staged tree with the real
  repo on `PYTHONPATH`, so the `from <live_entrypoint_pkg> import ...` resolves
  the LIVE code; an orphaned leaf fails → auto-commit rolls back.
- It must NOT mock `<live_entrypoint>` (mocking the seam re-introduces the
  orphan blind spot). The spy goes on the LEAF, the call goes through the real
  entrypoint.

---

## 5. How the wire-up phase REQUIRES a wiring oracle and rejects unit-only leaves

### 5a. Plan-validation gate (cheapest, earliest) — `plan_validator.py`
Add a check in the per-task loop next to the A2 `test_authoring` block
(`harness/planner/plan_validator.py:114-122`):
- For every IMPL leaf task (non-`test_authoring`, building a NEW module), require
  that at least one of its gate oracle files (the `.py` tokens in its
  `verification_command`, or its sibling `test_authoring` oracle) is classified
  as a wiring oracle.
- Classification heuristic (cheap, AST/text based, runs on the committed oracle
  source which is already readable at normalize time via the same path
  `_inject_oracle_sources` uses, `plan_normalizer.py:323-327`):
  - REQUIRE the oracle source to `import`/`from` at least one module that is NOT
    the leaf-under-test and NOT under `tests/` (i.e. a live entrypoint), AND
  - REQUIRE a marker — e.g. a mandatory module docstring token
    `WIRING ORACLE` or a function named `test_*_wired` / `test_*_registers_*` /
    `test_*_invokes_*`.
  - If the only oracle imports solely the leaf module → emit
    `PlanViolation('missing_wiring_oracle', ..., 'leaf builds a new module but
    ships no wiring-assertion oracle: an oracle must import a live entrypoint and
    assert it reaches <leaf> (registration/call-edge/behavior-change)')`.
- This fails the plan at `validate_plan` time, before any worker is spawned —
  symmetric to how `missing_mutation_target` is caught early (`:122`).

### 5b. Accept-path gate (defense-in-depth, catches drift) — orchestrator bypass branch
Mirror the existing smoke/embedded/narrow rejection ladder
(`orchestrator.py:3626-3675`). After the impl lands and its oracle is run via
`git_integration.py:1657`, add a pre-accept assertion that the leaf's gate
oracle set includes a wiring oracle (reuse the 5a classifier on the committed
oracle file). On failure: `set_phase(rejected)` exactly like the
`embedded_err is not None` branch (`:3650-3657`). This catches a leaf that
passed plan-validation but whose oracle was later weakened to unit-only.

### 5c. Brief-authoring requirement (process / FSM) — the P6 procedure gates
The overseer gated-procedure FSM (`overseer/procedure_state.py`,
`brief_hooks_overseer_procedure_gates.md`) already enforces an
ORACLE phase before DISPATCH. Add to the ORACLE-phase exit condition: the
authored oracle for a NEW-module leaf must be a wiring oracle (same 5a
classifier). The phase cannot advance to COMPLETE / DISPATCH until a wiring
oracle exists — so every dispatched leaf brief is guaranteed to ship one.

### Why this closes the orphan gap
- The embedded gate (1a) runs only the candidate's inline tests and can't see
  the repo — it is structurally blind to wiring. The committed-oracle gate (1b)
  CAN import the live entrypoint and is fail-closed (`git_integration.py:1660`).
- Today nothing REQUIRES the 1b oracle to assert wiring — an isolated unit test
  passes the gate and lands an orphan ("unit-green isolated oracle, zero live
  importers", memory `implementation-is-not-wired-defect`).
- 5a makes the wiring oracle a HARD plan-schema requirement; 5b enforces it at
  accept time; 5c enforces it at brief-authoring. A leaf whose only test imports
  just the leaf module is rejected at the earliest of the three.

### Files to touch for the wire-up phase
- `harness/planner/plan_validator.py` (~:114) — new `missing_wiring_oracle` check
  + a `_is_wiring_oracle(oracle_src, leaf_module)` classifier helper.
- `harness/planner/plan_normalizer.py` — optionally surface the classifier so
  `_inject_oracle_sources` can flag a non-wiring oracle in the injected notes.
- `harness/orchestrator.py` (~:3650) — accept-path rejection branch.
- `overseer/procedure_state.py` — ORACLE→DISPATCH phase exit condition.
- Brief template / `brief_hooks_*` recipe — mandate a `test_<leaf>_wired.py`
  oracle in the deliverables for every NEW-module leaf.
