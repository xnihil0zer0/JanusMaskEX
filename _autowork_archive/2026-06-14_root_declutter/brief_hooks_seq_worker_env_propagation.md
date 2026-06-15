---
interfaces: "in-place EDIT of harness/autowork_daemon.py — factor the worker-env build (os.environ.copy + JANUSMASK_WORKING_DIR set/pop from the staged task's working_dir) into a NEW shared module-level helper _build_worker_env(state_dir, task_id) and call it from BOTH the parallel spawn (_spawn_worker) and the sequential spawn (the requires_claude branch inside _iteration); the sequential subprocess.Popen now passes env=_worker_env. Behavior-only; no signatures change; _spawn_worker's JANUSMASK_AGY_SLOT logic preserved."
---

# Title

Propagate JANUSMASK_WORKING_DIR on the SEQUENTIAL worker spawn via a shared _build_worker_env helper (harness/autowork_daemon.py EDIT — harness_self_fix)

# Scope

EDIT `harness/autowork_daemon.py` (SENSITIVE path — meta_task_type MUST be `harness_self_fix`; an operator decision file authorizes the commit).

THE BUG: The PARALLEL worker spawn `_spawn_worker` (harness/autowork_daemon.py ~1105-1114) builds `_worker_env = os.environ.copy()`, reads the staged task's `working_dir` from `state_dir/'tasks'/f'{task_id}.json'`, sets `_worker_env['JANUSMASK_WORKING_DIR'] = working_dir` for an EXTERNAL task (pops it for self/missing/invalid as a fail-safe), and passes `env=_worker_env` to `subprocess.Popen`. The SEQUENTIAL worker spawn — the `if requires_claude:` branch inside `_iteration` (~1860-1869) — launches the IDENTICAL worker command but with NO `env=` kwarg, so it inherits the daemon's raw environment and `JANUSMASK_WORKING_DIR` is never set for an EXTERNAL task. The smoke gate `harness/sandbox_smoke.py:smoke_import` adds the external root to PYTHONPATH/ro-binds ONLY via `os.environ.get('JANUSMASK_WORKING_DIR')` (line 101), so a NEW external module that does `from ngv2.contracts import ...` fails the smoke gate with `ModuleNotFoundError: No module named 'ngv2'` when dispatched through the sequential path. (Earlier external tasks passed only because they were stdlib-only.)

THE FIX (shared-helper refactor — the cleaner design):

1. ADD a NEW module-level function `_build_worker_env(state_dir, task_id)` that returns the worker env dict. Its body is EXACTLY the env-building logic currently inlined in `_spawn_worker` (the `os.environ.copy()` + try/except JANUSMASK_WORKING_DIR set/pop), WITHOUT the agy-pool slot logic (that stays in `_spawn_worker`). Signature: `def _build_worker_env(state_dir: pathlib.Path, task_id: str) -> dict:`. Body VERBATIM:

```python
def _build_worker_env(state_dir: pathlib.Path, task_id: str) -> dict:
    # EXTERNAL_WORKING_DIR_PROPAGATION (NGv2 gap #3): the worker's jail retarget
    # (orchestrator.py:391) and the smoke gate (sandbox_smoke.py:smoke_import)
    # read JANUSMASK_WORKING_DIR from the env, but the worker never sets it (only
    # serial run_pipeline does). Propagate the staged task's trusted working_dir
    # so an EXTERNAL target's synthesis jail/smoke retarget onto the external tree.
    # Fail-safe: any read/parse error or a self build leaves the var unset
    # (popped), so it is never inherited from the parent. Shared by BOTH the
    # parallel (_spawn_worker) and sequential (_iteration requires_claude) spawns.
    _worker_env = os.environ.copy()
    try:
        _task_obj = json.loads((state_dir / 'tasks' / f'{task_id}.json').read_text(encoding='utf-8'))
        _wd = _task_obj.get('working_dir') if isinstance(_task_obj, dict) else None
        if isinstance(_wd, str) and _wd:
            _worker_env['JANUSMASK_WORKING_DIR'] = _wd
        else:
            _worker_env.pop('JANUSMASK_WORKING_DIR', None)
    except (OSError, ValueError, TypeError):
        _worker_env.pop('JANUSMASK_WORKING_DIR', None)
    return _worker_env
```

2. MODIFY `_spawn_worker` to call the helper instead of inlining the env build. The CURRENT function is (reproduce it byte-for-byte EXCEPT the indicated env block):

```python
def _spawn_worker(state_dir: pathlib.Path, task_id: str) -> int | None:
    # CONTAIN C7 (trusted-worker boundary): this spawns the TRUSTED harness worker
    # (`python -m harness.orchestrator_worker`), NOT an agent CLI -- so it needs no
    # bwrap jail. The worker itself routes any agent spawn through
    # orchestrator.spawn_agent (jailed). Asserted by test_TC1_1; if a future change
    # ever routes an agent CLI through here it MUST go through _contain_selfheal.
    cmd = [sys.executable, '-m', 'harness.orchestrator_worker', '--state-dir', str(state_dir), '--task-id', task_id]
    # EXTERNAL_WORKING_DIR_PROPAGATION (NGv2 gap #3): the worker's jail retarget
    # (orchestrator.py:391) reads JANUSMASK_WORKING_DIR from the env, but the worker
    # never sets it (only serial run_pipeline does). Propagate the staged task's
    # trusted working_dir so an EXTERNAL target's synthesis jail retargets onto the
    # external tree. Fail-safe: any read/parse error or a self build leaves the var
    # unset (popped), so it is never inherited from the parent.
    _worker_env = os.environ.copy()
    try:
        _task_obj = json.loads((state_dir / 'tasks' / f'{task_id}.json').read_text(encoding='utf-8'))
        _wd = _task_obj.get('working_dir') if isinstance(_task_obj, dict) else None
        if isinstance(_wd, str) and _wd:
            _worker_env['JANUSMASK_WORKING_DIR'] = _wd
        else:
            _worker_env.pop('JANUSMASK_WORKING_DIR', None)
    except (OSError, ValueError, TypeError):
        _worker_env.pop('JANUSMASK_WORKING_DIR', None)
    # Pillar B: reserve a distinct agy-pool slot for this worker (when the pool is
    # enabled) so orchestrator._apply_agy_pool_env can pool its $HOME. A None slot
    # (pool disabled/full) leaves the env unchanged.
    _slot = _agy_pool_assign(state_dir, task_id)
    if _slot is not None:
        _worker_env['JANUSMASK_AGY_SLOT'] = str(_slot)
    try:
        proc = subprocess.Popen(cmd, start_new_session=True, env=_worker_env)
        return proc.pid
    except (OSError, ValueError) as exc:
        _emit_telemetry(state_dir, task_id, 'spawn_failed', repr(exc))
        return None
```

REPLACE WITH EXACTLY (the only change: replace the inline env-build block — from `# EXTERNAL_WORKING_DIR_PROPAGATION` through the closing `_worker_env.pop(...)` except line — with a single call to the new helper; keep the agy-slot block and the Popen byte-identical):

```python
def _spawn_worker(state_dir: pathlib.Path, task_id: str) -> int | None:
    # CONTAIN C7 (trusted-worker boundary): this spawns the TRUSTED harness worker
    # (`python -m harness.orchestrator_worker`), NOT an agent CLI -- so it needs no
    # bwrap jail. The worker itself routes any agent spawn through
    # orchestrator.spawn_agent (jailed). Asserted by test_TC1_1; if a future change
    # ever routes an agent CLI through here it MUST go through _contain_selfheal.
    cmd = [sys.executable, '-m', 'harness.orchestrator_worker', '--state-dir', str(state_dir), '--task-id', task_id]
    # EXTERNAL_WORKING_DIR_PROPAGATION (NGv2 gap #3): build the worker env (copies
    # os.environ and sets/pops JANUSMASK_WORKING_DIR from the staged task) via the
    # shared helper so the parallel and sequential spawns stay in lockstep.
    _worker_env = _build_worker_env(state_dir, task_id)
    # Pillar B: reserve a distinct agy-pool slot for this worker (when the pool is
    # enabled) so orchestrator._apply_agy_pool_env can pool its $HOME. A None slot
    # (pool disabled/full) leaves the env unchanged.
    _slot = _agy_pool_assign(state_dir, task_id)
    if _slot is not None:
        _worker_env['JANUSMASK_AGY_SLOT'] = str(_slot)
    try:
        proc = subprocess.Popen(cmd, start_new_session=True, env=_worker_env)
        return proc.pid
    except (OSError, ValueError) as exc:
        _emit_telemetry(state_dir, task_id, 'spawn_failed', repr(exc))
        return None
```

3. MODIFY the SEQUENTIAL spawn inside `_iteration`. The CURRENT sequential branch lines (inside `if requires_claude:`) are:

```python
            if requires_claude:
                _emit_telemetry(state_dir, tid, 'launch_sequential', 'running sequential/claude worker')
                # CONTAIN C7 (trusted-worker boundary): TRUSTED harness worker, not
                # an agent CLI -- no jail here; the worker jails its own agent spawns
                # via orchestrator.spawn_agent. A future agent-CLI reroute MUST go
                # through _contain_selfheal.
                cmd = [sys.executable, '-m', 'harness.orchestrator_worker', '--state-dir', str(state_dir), '--task-id', tid]
                pid = None
                try:
                    proc = subprocess.Popen(cmd, start_new_session=True)
```

REPLACE those lines WITH EXACTLY (insert the helper call after `cmd = [...]` and add `env=_worker_env` to the Popen; everything else in this branch — pidfile write, suspend_parallel_workers, telemetry, seq_start, watchdog, finally — unchanged):

```python
            if requires_claude:
                _emit_telemetry(state_dir, tid, 'launch_sequential', 'running sequential/claude worker')
                # CONTAIN C7 (trusted-worker boundary): TRUSTED harness worker, not
                # an agent CLI -- no jail here; the worker jails its own agent spawns
                # via orchestrator.spawn_agent. A future agent-CLI reroute MUST go
                # through _contain_selfheal.
                cmd = [sys.executable, '-m', 'harness.orchestrator_worker', '--state-dir', str(state_dir), '--task-id', tid]
                # EXTERNAL_WORKING_DIR_PROPAGATION (NGv2 gap #3): mirror the parallel
                # spawn -- propagate the staged task's trusted working_dir so an
                # EXTERNAL target's worker (jail retarget + smoke gate) resolves the
                # external package. Without this the sequential path inherited the
                # daemon env unchanged and external modules failed the smoke gate.
                _worker_env = _build_worker_env(state_dir, tid)
                pid = None
                try:
                    proc = subprocess.Popen(cmd, start_new_session=True, env=_worker_env)
```

meta_task_type=`harness_self_fix`. verification_command: `pytest tests/test_sequential_worker_env_propagation_wired.py tests/test_autowork_daemon.py tests/test_daemon_agy_pool.py`.

LOUD DISPATCH DIRECTIVE — PATCH FORMAT (`harness/autowork_daemon.py` is a LARGE file, this MUST be a partial edit): emit a single top-level `__JANUSMASK_PATCHES__` list. The AST-merge applies node-by-node keyed by top-level symbol name (matched names REPLACE, new names APPEND), so emit:
  - ONE entry kind `'symbol'`, name `'_spawn_worker'`, whose `code` is the FULL corrected `def _spawn_worker(...)` shown above (every line byte-identical except the env block collapsed to the `_build_worker_env(state_dir, task_id)` call).
  - ONE entry kind `'symbol'`, name `'_iteration'`, whose `code` is the FULL corrected `def _iteration(...)` — reproduce the ENTIRE current function byte-for-byte from the read-only staged target, changing ONLY the two lines in the sequential branch shown above (the inserted `_worker_env = _build_worker_env(state_dir, tid)` line + the `env=_worker_env` kwarg on the sequential `subprocess.Popen`). Do NOT alter any other statement, comment, the parallel-else branch, the watchdog loop, the quarantine logic, or the docstring.
  - ONE entry that ADDS the NEW `def _build_worker_env(...)` (shown above). Because it is a NEW top-level symbol it APPENDS via the AST merge; emit it as a kind `'symbol'` entry, name `'_build_worker_env'`, with the full function `code`. (If your patch schema requires a R-ANCHOR for a new symbol, anchor it on the SHORT existing module-level CONSTANT `MAX_REBUILD_ATTEMPTS = 5` at line 1127 — reproduce that constant byte-for-byte and append `_build_worker_env` after it; agents reproduce a one-line constant anchor reliably, a function unreliably.)
Read each modified function's CURRENT on-disk content from the read-only staged target at `{WORK_DIR}/inbox/targets/harness/autowork_daemon.py`. Do NOT emit a `__JANUSMASK_MANIFEST__`, do NOT emit a whole-file rewrite, do NOT touch `_agy_pool_assign`, `_emit_telemetry`, or any other symbol. Do NOT add agy-pool slot logic to the sequential branch (scope minimal — only JANUSMASK_WORKING_DIR propagation there).

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the operator decision file is keyed to it): `task_id`: `seq-worker-env-propagation`. meta_task_type=`harness_self_fix`. priority: high. dependencies: []. SELF task (no `working_dir` — this edits JM itself). files_touched: `["harness/autowork_daemon.py"]` ONLY (no other file). partial_edit semantics (single `__JANUSMASK_PATCHES__` list: `'symbol'` entries for `_spawn_worker` and `_iteration`, plus the new `_build_worker_env`). verification_command: `pytest tests/test_sequential_worker_env_propagation_wired.py tests/test_autowork_daemon.py tests/test_daemon_agy_pool.py`. The leaf's `non_goals` MUST carry the literal word `integration` (out of scope is integration testing). The pre-committed RED oracle `tests/test_sequential_worker_env_propagation_wired.py` (committed at b168ad0 on JM master) is the authoritative contract — make it 5/5 green; do NOT author new tests.

REQUIRED: at least TWO `edge_cases` in `test_spec`, mirrored into `regression_tests` (and/or `property_tests`) — name exactly these two:
  1. external-task → JANUSMASK_WORKING_DIR-set: `_build_worker_env(state_dir, tid)` for a staged task whose json has `working_dir` = an external path returns an env whose `JANUSMASK_WORKING_DIR` equals that path.
  2. self-task → JANUSMASK_WORKING_DIR-popped: `_build_worker_env(state_dir, tid)` for a staged task with no/empty `working_dir` returns an env that does NOT contain `JANUSMASK_WORKING_DIR`, even when the parent process env had it set (fail-safe, never inherit).
A third (missing-task-json → fail-safe pop) MAY be included. `minimum_test_count` must be >= 1.5 × functional_requirements.

# Non-Goals

- Does NOT add agy-pool (JANUSMASK_AGY_SLOT) logic to the sequential branch — that stays exclusive to `_spawn_worker`.
- Does NOT change `_spawn_worker`'s observable behavior (it produces the identical env via the shared helper plus its existing agy-slot logic).
- Does NOT alter the sequential branch's pidfile write, suspend_parallel_workers, telemetry, seq_start, watchdog loop, or finally block.
- Does NOT touch any file other than `harness/autowork_daemon.py`.
- Does NOT change the signature of `_spawn_worker`, `_iteration`, or any other symbol.
- Out of scope: integration testing of the end-to-end external sequential build/smoke flow; this leaf is a behavior-only unit fix verified by the pre-committed oracle.

# Inputs

- Authoritative contract: the pre-committed RED oracle `tests/test_sequential_worker_env_propagation_wired.py` (JM master commit b168ad0). All 5 cases are RED today because `_build_worker_env` does not yet exist.
- The proven reference logic to factor out: the inline env block in `_spawn_worker` (autowork_daemon.py ~1105-1114) — copy os.environ, read `working_dir` from `state_dir/'tasks'/f'{task_id}.json'`, isinstance-guarded set, pop on self/empty/error. Embedded verbatim in `# Scope`.
- The sequential-branch anchor (the `if requires_claude:` block ~1860-1869) and the constant anchor `MAX_REBUILD_ATTEMPTS = 5` (line 1127) are embedded in `# Scope`.

# Deliverables

`harness/autowork_daemon.py` with: (a) a NEW module-level `_build_worker_env(state_dir, task_id)` helper holding the env-copy + JANUSMASK_WORKING_DIR set/pop logic; (b) `_spawn_worker` calling that helper (agy-slot logic + Popen preserved); (c) the sequential `requires_claude` spawn inside `_iteration` calling that helper and passing `env=_worker_env` to its `subprocess.Popen` (every other line of `_iteration` preserved byte-for-byte). Turns `tests/test_sequential_worker_env_propagation_wired.py` 5/5 GREEN. EXTERNAL tasks dispatched through the SEQUENTIAL path now carry `JANUSMASK_WORKING_DIR`, so a new external module resolves under the smoke gate instead of failing with `ModuleNotFoundError`; self tasks and the parallel path behave exactly as before.
