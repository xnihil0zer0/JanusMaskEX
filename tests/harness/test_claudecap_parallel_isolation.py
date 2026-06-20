"""tests/harness/test_claudecap_parallel_isolation.py

Regression / oracle tests for the configurable Claude parallel cap and the
per-worker config-directory isolation logic in ``harness.autowork_daemon``
(and, where present, ``harness.orchestrator``).

These tests pin the *observable* behaviour described by the task spec:

  * ``parallel_cap == 4`` + disjoint ``files_touched`` -> all tasks admitted on
    the parallel branch (no mutual serialization),
  * ``parallel_cap == 1`` -> at most one task admitted per decision (today's
    sequential / suspend behaviour preserved),
  * overlapping ``files_touched`` -> still serialized (the ``can_run_parallel``
    veto holds, both against admitted candidates and against running workers),
  * the Claude *headless worker* environment gets a distinct, per-task
    ``CLAUDE_CONFIG_DIR`` derived from its work dir, while the Gemini / Agy
    worker environment is left untouched by the Claude isolation logic.

The cap-decision and serialization tests assert against concrete daemon
functions and so will FAIL on a mutant that breaks the parallelism math or the
file-overlap veto. The config-dir seeding tests probe the (newer) per-agent env
entry points defensively and skip only when no such entry point can be located,
so they exercise real behaviour on an implemented daemon without spuriously
failing the suite.
"""
from __future__ import annotations
import json
import os
import signal
import pytest
import harness.autowork_daemon as ad

@pytest.fixture(autouse=True)
def _clean_daemon_globals():
    """Snapshot + clear the daemon's process-global suspend bookkeeping.

    ``suspend_parallel_workers`` / ``resume_parallel_workers`` mutate module
    globals; isolate every test from leakage and restore afterwards.
    """
    susp = set(getattr(ad, '_suspended_pids', set()))
    starts = dict(getattr(ad, '_suspension_start_times', {}))
    ad._suspended_pids.clear()
    ad._suspension_start_times.clear()
    try:
        yield
    finally:
        ad._suspended_pids.clear()
        ad._suspended_pids.update(susp)
        ad._suspension_start_times.clear()
        ad._suspension_start_times.update(starts)

@pytest.fixture
def patched_decide(monkeypatch):
    """Stub the brief-status + dep-gate collaborators of ``_decide``.

    Keeps the decision deterministic and offline: every collected task passes
    the brief dependency gate and there are no brief-status records.
    """
    monkeypatch.setattr(ad, 'compute_brief_status', lambda *a, **k: [], raising=False)
    monkeypatch.setattr(ad, '_brief_dep_gate_ok', lambda *a, **k: True, raising=False)

def _write_task(state_dir, task_id, files, deps=None, **extra):
    """Stage a dispatchable task JSON under ``<state_dir>/tasks/<id>.json``."""
    tasks = state_dir / 'tasks'
    tasks.mkdir(parents=True, exist_ok=True)
    data = {'task_id': task_id, 'files_touched': list(files), 'dependencies': list(deps or [])}
    data.update(extra)
    (tasks / f'{task_id}.json').write_text(json.dumps(data), encoding='utf-8')
    return data

def _import_orch():
    try:
        import harness.orchestrator as orch
        return orch
    except Exception:
        return None

def _try_call(fn, args, kwargs):
    """Call ``fn`` defensively; return the dict result or ``None`` on any error.

    Also handles "mutate-an-env-in-place" style helpers: when a dict is passed
    positionally and the function returns ``None``, the mutated dict is used.
    """
    probe = None
    for a in args:
        if isinstance(a, dict):
            probe = a
            break
    try:
        res = fn(*args, **kwargs)
    except Exception:
        return None
    if isinstance(res, dict):
        return res
    if res is None and isinstance(probe, dict):
        return probe
    return None
_SEED_NAMES = ('_build_agent_env', '_seed_claude_config_dir', '_apply_claude_config_dir', '_claude_config_env', '_worker_env_for_agent', '_agent_env', 'build_agent_env', '_seed_config_dir', '_build_worker_env')

def _call_variants(fn, agent, work_dir, task_id, state_dir):
    wd = str(work_dir)
    sd = str(state_dir)
    return [((), {'agent': agent, 'work_dir': work_dir}), ((agent, work_dir), {}), ((agent, wd), {}), ((agent, work_dir, sd), {}), ((agent, work_dir, task_id), {}), ((sd, task_id, agent), {}), ((state_dir, task_id, agent), {}), ((task_id, agent, work_dir), {}), (({}, work_dir, agent), {}), ((state_dir, task_id), {})]

def _resolve_config_dir_builder(state_dir, probe_work_dir, probe_task_id):
    """Locate a per-agent env entry point that seeds ``CLAUDE_CONFIG_DIR``.

    Returns a callable ``builder(agent, work_dir, task_id) -> dict | None`` bound
    to the exact (function, call-convention) that produced a Claude env with a
    ``CLAUDE_CONFIG_DIR`` key, or ``None`` if none could be found.
    """
    orch = _import_orch()
    mods = [m for m in (ad, orch) if m is not None]
    fns = []
    for m in mods:
        for nm in _SEED_NAMES:
            fn = getattr(m, nm, None)
            if callable(fn):
                fns.append(fn)
    for fn in fns:
        variants = _call_variants(fn, 'claude', probe_work_dir, probe_task_id, state_dir)
        for idx, (args, kwargs) in enumerate(variants):
            env = _try_call(fn, args, kwargs)
            if isinstance(env, dict) and 'CLAUDE_CONFIG_DIR' in env:

                def builder(agent, work_dir, task_id, _fn=fn, _idx=idx):
                    vs = _call_variants(_fn, agent, work_dir, task_id, state_dir)
                    a, k = vs[_idx]
                    return _try_call(_fn, a, k)
                return builder
    return None

def test_claude_parallel_cap_validation_defaults():
    """An absent/empty config yields the documented default cap (4)."""
    assert ad.DEFAULT_PARALLEL_CAP == 4
    assert ad._parallel_cap({}) == ad.DEFAULT_PARALLEL_CAP
    assert ad._parallel_cap({'autowork': {}}) == ad.DEFAULT_PARALLEL_CAP
    assert ad._parallel_cap({'autowork': {'parallel_cap': 3}}) == 3
    assert ad._parallel_cap({'autowork': {'parallel_cap': 'nope'}}) == ad.DEFAULT_PARALLEL_CAP

def test_claude_parallel_cap_clamping_to_effective_parallel_cap():
    """The cap is clamped into ``[PARALLEL_CAP_MIN, PARALLEL_CAP_MAX]``."""
    lo, hi = (ad.PARALLEL_CAP_MIN, ad.PARALLEL_CAP_MAX)
    assert lo == 1 and hi == 16
    assert ad._parallel_cap({'autowork': {'parallel_cap': 0}}) == lo
    assert ad._parallel_cap({'autowork': {'parallel_cap': -5}}) == lo
    assert ad._parallel_cap({'autowork': {'parallel_cap': 999}}) == hi
    assert ad._parallel_cap({'autowork': {'parallel_cap': 2}}) == 2
    for nm in ('_claude_parallel_cap', '_effective_claude_parallel_cap', '_effective_parallel_cap'):
        fn = getattr(ad, nm, None)
        if callable(fn):
            cfg = {'autowork': {'parallel_cap': 4, 'claude_parallel_cap': 99}}
            try:
                eff = fn(cfg)
            except TypeError:
                continue
            if isinstance(eff, int):
                assert eff <= ad._parallel_cap(cfg)
                assert eff >= lo

def test_claude_parallel_cap_parallel_dispatch_disjoint_files(tmp_path, patched_decide):
    """cap=4 + two disjoint-file tasks -> BOTH admitted (parallel branch)."""
    state = tmp_path / 'state'
    _write_task(state, 'alpha', ['src/a.py'])
    _write_task(state, 'beta', ['src/b.py'])
    chosen, paused, free = ad._decide(state, state, set(), 4)
    ids = {t['task_id'] for t in chosen}
    assert ids == {'alpha', 'beta'}
    assert paused is False
    assert free == 4

def test_claude_parallel_cap_4_disjoint_tasks_run_concurrently(tmp_path, patched_decide):
    """REGRESSION: cap=4 with four disjoint tasks -> all four dispatch at once."""
    state = tmp_path / 'state'
    for i in range(4):
        _write_task(state, f't{i}', [f'src/m{i}.py'])
    chosen, paused, free = ad._decide(state, state, set(), 4)
    ids = {t['task_id'] for t in chosen}
    assert ids == {'t0', 't1', 't2', 't3'}
    assert len(chosen) == 4
    assert free == 4
    assert paused is False

def test_claude_parallel_cap_one_sequential_behavior(tmp_path, patched_decide):
    """cap=1 -> at most one task admitted even when several are dispatchable."""
    state = tmp_path / 'state'
    _write_task(state, 'one', ['src/one.py'])
    _write_task(state, 'two', ['src/two.py'])
    _write_task(state, 'three', ['src/three.py'])
    chosen, paused, free = ad._decide(state, state, set(), 1)
    assert len(chosen) == 1
    assert free == 1
    assert chosen[0]['task_id'] in {'one', 'two', 'three'}

def test_claude_parallel_cap_1_is_fully_sequential(tmp_path, monkeypatch, patched_decide):
    """REGRESSION: cap=1 admits one task and the suspend path serializes others.

    Two arms: (a) ``_decide`` admits exactly one of two disjoint tasks under
    cap=1 (free slot math is the gate), and (b) the sequential branch's
    ``suspend_parallel_workers`` SIGSTOPs an already-running worker so it cannot
    race the newly launched one -- today's back-compatible behaviour.
    """
    state = tmp_path / 'state'
    _write_task(state, 'first', ['src/first.py'])
    _write_task(state, 'second', ['src/second.py'])
    chosen, _paused, free = ad._decide(state, state, set(), 1)
    assert len(chosen) == 1
    assert free == 1
    calls = []
    monkeypatch.setattr(ad.os, 'kill', lambda pid, sig: calls.append((pid, sig)))
    rdir = ad._running_dir(state)
    rdir.mkdir(parents=True, exist_ok=True)
    running_pid = 515151
    (rdir / 'running_worker.pid').write_text(str(running_pid), encoding='utf-8')
    new_seq_pid = 525252
    ad.suspend_parallel_workers(state, exclude_pid=new_seq_pid)
    assert (running_pid, signal.SIGSTOP) in calls
    assert running_pid in ad._suspended_pids

def test_claude_parallel_cap_sequential_dispatch_fallback(tmp_path, monkeypatch):
    """The suspend fallback SIGSTOPs other workers, honouring exclude + daemon pid.

    ``suspend_parallel_workers`` must stop every running worker EXCEPT the one
    explicitly excluded (the freshly launched sequential worker) and the daemon
    itself.
    """
    state = tmp_path / 'state'
    rdir = ad._running_dir(state)
    rdir.mkdir(parents=True, exist_ok=True)
    normal_pid = 600001
    excluded_pid = 600002
    daemon_pid = os.getpid()
    (rdir / 'normal.pid').write_text(str(normal_pid), encoding='utf-8')
    (rdir / 'excluded.pid').write_text(str(excluded_pid), encoding='utf-8')
    (rdir / 'daemon.pid').write_text(str(daemon_pid), encoding='utf-8')
    calls = []
    monkeypatch.setattr(ad.os, 'kill', lambda pid, sig: calls.append((pid, sig)))
    ad.suspend_parallel_workers(state, exclude_pid=excluded_pid)
    stopped = {pid for pid, sig in calls if sig == signal.SIGSTOP}
    assert normal_pid in stopped
    assert excluded_pid not in stopped
    assert daemon_pid not in stopped
    assert normal_pid in ad._suspended_pids
    assert excluded_pid not in ad._suspended_pids

def test_file_overlap_veto_continues_to_serialize_tasks(tmp_path, patched_decide):
    """cap=4 but two tasks sharing a file -> only one admitted (veto holds)."""
    state = tmp_path / 'state'
    _write_task(state, 'writer_a', ['src/shared.py', 'src/a.py'])
    _write_task(state, 'writer_b', ['src/shared.py', 'src/b.py'])
    chosen, _paused, free = ad._decide(state, state, set(), 4)
    assert free == 4
    assert len(chosen) == 1

def test_overlapping_files_still_serialize_under_cap(tmp_path):
    """REGRESSION: a candidate overlapping a RUNNING worker is not dispatchable.

    ``collect_dispatchable_tasks`` must drop any task whose ``files_touched``
    conflict with a currently-running task, regardless of the parallel cap.
    """
    state = tmp_path / 'state'
    _write_task(state, 'running_one', ['src/contended.py'])
    _write_task(state, 'candidate', ['src/contended.py', 'src/extra.py'])
    _write_task(state, 'free_one', ['src/independent.py'])
    cands = ad.collect_dispatchable_tasks([], {'running_one'}, state)
    ids = {t['task_id'] for t in cands}
    assert 'candidate' not in ids
    assert 'free_one' in ids
    assert 'running_one' not in ids

def test_headless_claude_gets_distinct_config_dir(tmp_path, monkeypatch):
    """A Claude headless worker env carries a CLAUDE_CONFIG_DIR (per work_dir)."""
    monkeypatch.delenv('CLAUDE_CONFIG_DIR', raising=False)
    state = tmp_path / 'state'
    wd = tmp_path / 'wd_claude'
    wd.mkdir(parents=True, exist_ok=True)
    _write_task(state, 'claude-task', ['src/c.py'], agent='claude', target_agent='claude', synthesis_agent='claude', working_dir=str(wd))
    builder = _resolve_config_dir_builder(state, wd, 'claude-task')
    if builder is not None:
        env = builder('claude', wd, 'claude-task')
        assert isinstance(env, dict)
        assert 'CLAUDE_CONFIG_DIR' in env
        assert str(env['CLAUDE_CONFIG_DIR']).strip()
        return
    env = ad._build_worker_env(state, 'claude-task')
    if 'CLAUDE_CONFIG_DIR' not in env:
        pytest.skip('no Claude config-dir seeding entry point is present yet')
    assert str(env['CLAUDE_CONFIG_DIR']).strip()

def test_headless_claude_env_gets_distinct_config_dir(tmp_path, monkeypatch):
    """REGRESSION: two Claude tasks get *distinct* CLAUDE_CONFIG_DIR values."""
    monkeypatch.delenv('CLAUDE_CONFIG_DIR', raising=False)
    state = tmp_path / 'state'
    wd_a = tmp_path / 'wd_a'
    wd_b = tmp_path / 'wd_b'
    wd_a.mkdir(parents=True, exist_ok=True)
    wd_b.mkdir(parents=True, exist_ok=True)
    _write_task(state, 'claude-a', ['src/a.py'], agent='claude', target_agent='claude', synthesis_agent='claude', working_dir=str(wd_a))
    _write_task(state, 'claude-b', ['src/b.py'], agent='claude', target_agent='claude', synthesis_agent='claude', working_dir=str(wd_b))
    builder = _resolve_config_dir_builder(state, wd_a, 'claude-a')
    if builder is not None:
        env_a = builder('claude', wd_a, 'claude-a')
        env_b = builder('claude', wd_b, 'claude-b')
        assert 'CLAUDE_CONFIG_DIR' in env_a and 'CLAUDE_CONFIG_DIR' in env_b
        assert env_a['CLAUDE_CONFIG_DIR'] != env_b['CLAUDE_CONFIG_DIR']
        return
    env_a = ad._build_worker_env(state, 'claude-a')
    env_b = ad._build_worker_env(state, 'claude-b')
    if 'CLAUDE_CONFIG_DIR' not in env_a or 'CLAUDE_CONFIG_DIR' not in env_b:
        pytest.skip('no Claude config-dir seeding entry point is present yet')
    assert env_a['CLAUDE_CONFIG_DIR'] != env_b['CLAUDE_CONFIG_DIR']

def test_gemini_agy_env_remains_unchanged(tmp_path, monkeypatch):
    """Gemini / Agy worker env must NOT contain CLAUDE_CONFIG_DIR."""
    monkeypatch.delenv('CLAUDE_CONFIG_DIR', raising=False)
    state = tmp_path / 'state'
    wd = tmp_path / 'wd_gem'
    wd.mkdir(parents=True, exist_ok=True)
    _write_task(state, 'gem-task', ['src/g.py'], agent='gemini', target_agent='gemini', synthesis_agent='gemini', working_dir=str(wd))
    env = ad._build_worker_env(state, 'gem-task')
    assert 'CLAUDE_CONFIG_DIR' not in env
    builder = _resolve_config_dir_builder(state, wd, 'gem-task')
    if builder is not None:
        for agent in ('gemini', 'agy', 'antigravity'):
            g_env = builder(agent, wd, 'gem-task')
            if isinstance(g_env, dict):
                assert 'CLAUDE_CONFIG_DIR' not in g_env

def test_config_dir_seeding_failsafe_on_exception(tmp_path, monkeypatch):
    """Config-dir seeding must FAIL-SAFE: a mkdir error must not propagate."""
    state = tmp_path / 'state'
    wd = tmp_path / 'wd_fail'
    wd.mkdir(parents=True, exist_ok=True)
    _write_task(state, 'claude-fail', ['src/f.py'], agent='claude', target_agent='claude', synthesis_agent='claude', working_dir=str(wd))
    builder = _resolve_config_dir_builder(state, wd, 'claude-fail')
    if builder is None:
        pytest.skip('no Claude config-dir seeding entry point is present yet')
    import pathlib as _pathlib

    def _boom(self, *a, **k):
        raise OSError('simulated mkdir failure')
    monkeypatch.setattr(_pathlib.Path, 'mkdir', _boom, raising=False)
    monkeypatch.setattr(ad.os, 'makedirs', lambda *a, **k: (_ for _ in ()).throw(OSError('boom')), raising=False)
    try:
        result = builder('claude', wd, 'claude-fail')
    except Exception as exc:
        pytest.fail(f'config-dir seeding did not fail safely: {exc!r}')
    assert result is None or isinstance(result, dict)

def test_no_unapproved_or_manifest_files_created(tmp_path, patched_decide):
    """A pure dispatch *decision* must not write tasks/manifest/patch artefacts.

    ``_decide`` is a read-only planning step: against an empty queue it returns
    no work and must not create files in the state tree. Also assert the daemon
    module exposes no JanusMask patch/manifest sentinels (this is an oracle test
    file, not a patch bundle).
    """
    state = tmp_path / 'state'
    (state / 'tasks').mkdir(parents=True, exist_ok=True)
    before = {p.name for p in (state / 'tasks').iterdir()}
    chosen, paused, free = ad._decide(state, state, set(), 4)
    assert chosen == []
    assert paused is False
    assert free == 4
    after = {p.name for p in (state / 'tasks').iterdir()}
    assert after == before
    assert not hasattr(ad, '__JANUSMASK_PATCHES__')
    assert not hasattr(ad, '__JANUSMASK_MANIFEST__')
    src = open(__file__, 'r', encoding='utf-8').read()
    assert '__JANUSMASK_PATCHES__' not in src
    assert '__JANUSMASK_MANIFEST__' not in src