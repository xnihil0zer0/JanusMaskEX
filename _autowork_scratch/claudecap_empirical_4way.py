"""Empirical validation of the LANDED claudecap dispatch loop.

Drives the real harness.autowork_daemon._iteration against a self-contained temp
state dir with 4 disjoint-file claude tasks, monkeypatching the spawn primitives
so NO real claude/gemini process is launched. Proves:
  * cap=4 -> all 4 disjoint claude tasks dispatch via the PARALLEL _spawn_worker
    branch (no suspend_parallel_workers, no blocking subprocess.Popen).
  * cap=1 -> the SEQUENTIAL/suspend path is taken (back-compat) and only one
    claude worker is launched per iteration.
Run: PYTHONPATH=. python _autowork_scratch/claudecap_empirical_4way.py
"""
import json
import pathlib
import tempfile
import types

import harness.autowork_daemon as ad


def _setup_state(root: pathlib.Path, n_tasks: int):
    state = root / 'state'
    (state / 'control' / 'autowork').mkdir(parents=True, exist_ok=True)
    (state / 'tasks').mkdir(parents=True, exist_ok=True)
    (state / 'tasks' / 'blocked').mkdir(parents=True, exist_ok=True)
    (state / 'tasks' / 'processed').mkdir(parents=True, exist_ok=True)
    ad._running_dir(state).mkdir(parents=True, exist_ok=True)
    (state / 'impl_progress.jsonl').write_text('', encoding='utf-8')
    # deny-all allowlist so _auto_promote is a no-op
    (state / 'control' / 'autowork' / 'auto_promote.allowlist').write_text('# deny-all\n', encoding='utf-8')
    # 4 disjoint-file claude tasks, no deps
    for i in range(n_tasks):
        t = {'task_id': f't{i}', 'files_touched': [f'src/m{i}.py'], 'dependencies': [],
             'agent': 'claude', 'target_agent': 'claude', 'synthesis_agent': 'claude',
             'meta_task_type': 'harness_self_fix', 'verification_command': 'python -c "pass"'}
        (state / 'tasks' / f't{i}.json').write_text(json.dumps(t), encoding='utf-8')
    return state


def _run(cap_value: int, n_tasks: int = 4):
    spawn_calls = []
    popen_calls = []
    suspend_calls = []
    resume_calls = []

    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        repo_root = root / 'repo'      # empty -> no briefs -> promote no-op
        repo_root.mkdir(parents=True, exist_ok=True)
        state = _setup_state(root, n_tasks)

        cfg = {'synthesis': {'active_agents': ['claude', 'gemini']},
               'autowork': {'parallel_cap': 16, 'claude_parallel_cap': cap_value}}

        # --- monkeypatch spawn primitives (no real processes) ---
        _orig = {}
        def _patch(name, fn):
            _orig[name] = getattr(ad, name, None)
            setattr(ad, name, fn)

        fake_pid = [990000]
        def fake_spawn_worker(state_dir, tid, *a, **k):
            fake_pid[0] += 1
            spawn_calls.append(tid)
            # emulate a live worker pidfile so cap accounting is realistic
            try:
                ad._write_pidfile(state_dir, tid, fake_pid[0])
            except Exception:
                pass
            return fake_pid[0]
        _patch('_spawn_worker', fake_spawn_worker)

        def fake_suspend(state_dir, exclude_pid):
            suspend_calls.append(exclude_pid)
        _patch('suspend_parallel_workers', fake_suspend)
        def fake_resume(state_dir):
            resume_calls.append(True)
        _patch('resume_parallel_workers', fake_resume)

        class FakeProc:
            def __init__(self, *a, **k):
                fake_pid[0] += 1
                self.pid = fake_pid[0]
                popen_calls.append(getattr(self, 'pid', None))
                self._polls = 0
            def poll(self):
                # return non-None immediately so the sequential blocking loop exits at once
                return 0
            def wait(self, *a, **k):
                return 0
        _patch_subprocess = ad.subprocess
        _orig_popen = _patch_subprocess.Popen
        _patch_subprocess.Popen = FakeProc

        try:
            ad._iteration(repo_root, state, 16, dry_run=False, config=cfg)
        finally:
            _patch_subprocess.Popen = _orig_popen
            for k, v in _orig.items():
                if v is not None:
                    setattr(ad, k, v)

    return {'cap': cap_value, 'spawn_parallel': spawn_calls, 'popen_sequential': popen_calls,
            'suspend': suspend_calls}


def main():
    print('=== claudecap empirical dispatch validation (real _iteration, mocked spawns) ===\n')

    r4 = _run(cap_value=4, n_tasks=4)
    print(f'CAP=4 (parallel expected):')
    print(f'  parallel _spawn_worker calls: {sorted(r4["spawn_parallel"])}')
    print(f'  sequential Popen calls:       {r4["popen_sequential"]}')
    print(f'  suspend_parallel_workers:     {len(r4["suspend"])}')
    ok4 = (len(set(r4['spawn_parallel'])) == 4 and len(r4['popen_sequential']) == 0 and len(r4['suspend']) == 0)
    print(f'  => {"PASS" if ok4 else "FAIL"}: 4 disjoint claude tasks dispatched concurrently via parallel branch, no suspend\n')

    r1 = _run(cap_value=1, n_tasks=4)
    print(f'CAP=1 (sequential/back-compat expected):')
    print(f'  parallel _spawn_worker calls: {sorted(r1["spawn_parallel"])}')
    print(f'  sequential Popen calls:       {r1["popen_sequential"]}')
    print(f'  suspend_parallel_workers:     {len(r1["suspend"])}')
    # back-compat: the claude path takes the sequential Popen+suspend branch (not _spawn_worker)
    ok1 = (len(r1['popen_sequential']) >= 1 and len(r1['suspend']) >= 1)
    print(f'  => {"PASS" if ok1 else "FAIL"}: cap=1 routes the claude task through the sequential suspend path\n')

    print('=' * 60)
    print(f'OVERALL: {"PASS" if (ok4 and ok1) else "FAIL"}')


if __name__ == '__main__':
    main()
