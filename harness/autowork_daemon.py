"""harness/autowork_daemon.py -- polling daemon for orchestrator_worker subprocesses (AW4a).

Scans state/tasks/ for dispatchable task JSONs, decides which can run in
parallel via harness.autowork_parallelism.can_run_parallel, and spawns
harness.orchestrator_worker subprocesses up to a configurable parallel
cap. Supports --once (single iteration) and --dry-run (print decision
without spawning) modes for testing.
"""
from __future__ import annotations
import argparse
import json
import os
import pathlib
import signal
import subprocess
import sys
import time
from pathlib import Path
from harness.brief_status import compute_brief_status
from harness.planner.staging import stage_task
from harness.autowork_parallelism import can_run_parallel
from harness.autowork_parallelism import transitive_deps
try:
    import yaml
except ImportError:
    yaml = None
DEFAULT_POLL_INTERVAL_SEC = 5
DEFAULT_PARALLEL_CAP = 4
PARALLEL_CAP_MIN = 1
PARALLEL_CAP_MAX = 16
DEFAULT_HEARTBEAT_SEC = 1800
DEFAULT_PLANNER_TIMEOUT_SEC = 300
DEFAULT_BRIEF_MAX_SIZE_BYTES = 50000
_PRIORITY_RANK = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
_UNSET_RANK = 4
_shutdown_requested = False
_suspended_pids: set[int] = set()
_suspension_start_times: dict[int, float] = {}

def _install_sigterm_handler() -> None:

    def _handler(signum, frame):
        global _shutdown_requested
        _shutdown_requested = True
    try:
        signal.signal(signal.SIGTERM, _handler)
    except (ValueError, OSError):
        pass

def _load_config(config_path: pathlib.Path) -> dict:
    if yaml is None:
        return {}
    try:
        if not config_path.exists():
            return {}
        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, Exception):
        return {}

def _autowork_section(config: dict) -> dict:
    if not isinstance(config, dict):
        return {}
    aw = config.get('autowork')
    return aw if isinstance(aw, dict) else {}

def _parallel_cap(config: dict) -> int:
    aw = _autowork_section(config)
    raw = aw.get('parallel_cap', DEFAULT_PARALLEL_CAP)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = DEFAULT_PARALLEL_CAP
    if n < PARALLEL_CAP_MIN:
        return PARALLEL_CAP_MIN
    if n > PARALLEL_CAP_MAX:
        return PARALLEL_CAP_MAX
    return n

def _poll_interval(config: dict) -> float:
    aw = _autowork_section(config)
    raw = aw.get('poll_interval_sec', DEFAULT_POLL_INTERVAL_SEC)
    try:
        v = float(raw)
    except (TypeError, ValueError):
        v = float(DEFAULT_POLL_INTERVAL_SEC)
    return v if v > 0 else float(DEFAULT_POLL_INTERVAL_SEC)

def _heartbeat_interval(config: dict) -> float:
    aw = _autowork_section(config)
    raw = aw.get('heartbeat_sec', DEFAULT_HEARTBEAT_SEC)
    try:
        v = float(raw)
    except (TypeError, ValueError):
        v = float(DEFAULT_HEARTBEAT_SEC)
    return v if v > 0 else float(DEFAULT_HEARTBEAT_SEC)

def _planner_timeout(config: dict) -> float:
    aw = _autowork_section(config)
    raw = aw.get('planner_timeout_sec', DEFAULT_PLANNER_TIMEOUT_SEC)
    try:
        v = float(raw)
    except (TypeError, ValueError):
        v = float(DEFAULT_PLANNER_TIMEOUT_SEC)
    return v if v > 0 else float(DEFAULT_PLANNER_TIMEOUT_SEC)

def _planner_min_wall(config: dict) -> float:
    """G-MINWALL: the planner-hallucination wall threshold (seconds).

    Reads autowork.planner_min_wall_sec, defaulting to the canonical named
    constant harness.PLANNER_MIN_WALL_SECONDS (AW18) — this is the deferred
    consumer-side rewire of that constant.
    """
    from harness import PLANNER_MIN_WALL_SECONDS
    aw = _autowork_section(config)
    raw = aw.get('planner_min_wall_sec', PLANNER_MIN_WALL_SECONDS)
    try:
        v = float(raw)
    except (TypeError, ValueError):
        v = float(PLANNER_MIN_WALL_SECONDS)
    return v if v > 0 else float(PLANNER_MIN_WALL_SECONDS)

def _brief_max_size(config: dict) -> int:
    aw = _autowork_section(config)
    raw = aw.get('brief_max_size_bytes', DEFAULT_BRIEF_MAX_SIZE_BYTES)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = DEFAULT_BRIEF_MAX_SIZE_BYTES
    return n if n > 0 else DEFAULT_BRIEF_MAX_SIZE_BYTES

def _brief_max_age(config: dict) -> int:
    aw = _autowork_section(config)
    raw = aw.get('brief_max_age_seconds', DEFAULT_BRIEF_MAX_AGE_SEC)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = DEFAULT_BRIEF_MAX_AGE_SEC
    return n if n > 0 else DEFAULT_BRIEF_MAX_AGE_SEC

def _emit_telemetry(state_dir: pathlib.Path, task_id: str, event: str, detail: str='') -> None:
    row = {'ts': time.time(), 'pid': os.getpid(), 'phase': 'autowork', 'task_id': task_id, 'event': event, 'detail': detail}
    try:
        ledger = state_dir / 'impl_progress.jsonl'
        line = json.dumps(row) + '\n'
        with open(ledger, 'a', encoding='utf-8') as f:
            f.write(line)
    except OSError:
        pass

def _accepted_task_ids(status_records: list[dict]) -> set[str]:
    accepted: set[str] = set()
    for rec in status_records or []:
        if not isinstance(rec, dict):
            continue
        for a in rec.get('accepted') or []:
            if isinstance(a, dict):
                tid = a.get('task_id')
                if isinstance(tid, str):
                    accepted.add(tid)
            elif isinstance(a, str):
                accepted.add(a)
    return accepted

def collect_dispatchable_tasks(status_records: list[dict], running_task_ids: set[str], repo_root: pathlib.Path) -> list[dict]:
    """Return task dicts that are ready to dispatch right now.

    The third argument is named ``repo_root`` per spec, but the function
    resolves task files at ``<repo_root>/tasks/<id>.json``. ``run_daemon``
    passes ``state_dir`` here so the path becomes ``state_dir/tasks/``.

    Spec files are skipped when their stem does not match the declared
    ``task_id``, or when the filename starts with ``current_task`` (no
    underscore, so ``current_task.json`` and ``current_task_*.json`` are both
    excluded) or ends with ``.retry.json``.
    """
    base = pathlib.Path(repo_root)
    tasks_dir = base / 'tasks'
    if not tasks_dir.exists() or not tasks_dir.is_dir():
        return []
    accepted_ids = _accepted_task_ids(status_records)
    ledger_path = base / 'impl_progress.jsonl'
    if ledger_path.exists():
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        row = json.loads(line)
                        if isinstance(row, dict) and row.get('phase') == 'accepted' and (row.get('event') == 'auto_commit'):
                            tid = row.get('task_id')
                            if tid:
                                accepted_ids.add(tid)
                    except Exception as err:
                        _ = err
        except OSError:
            pass
    running_ids = set(running_task_ids or set())
    all_tasks: list[dict] = []
    for p in sorted(tasks_dir.iterdir()):
        if p.is_dir():
            continue
        if p.suffix != '.json':
            continue
        if p.name.endswith('.processing') or p.name.endswith('.json.processing'):
            continue
        if p.name.startswith('current_task') or p.name.endswith('.retry.json'):
            continue
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if not isinstance(data.get('task_id'), str):
            continue
        if p.stem != data['task_id']:
            continue
        try:
            data['_mtime'] = p.stat().st_mtime
        except OSError:
            data['_mtime'] = 0.0
        data['_path'] = str(p)
        all_tasks.append(data)
    by_id: dict[str, dict] = {t['task_id']: t for t in all_tasks}
    running_dicts: list[dict] = []
    for rid in running_ids:
        if rid in by_id:
            running_dicts.append(by_id[rid])
        else:
            running_dicts.append({'task_id': rid, 'files_touched': []})
    candidates: list[dict] = []
    for task in all_tasks:
        tid = task['task_id']
        if tid in running_ids:
            continue
        deps = task.get('dependencies') or []
        deps_ok = True
        for d in deps:
            if not isinstance(d, str):
                continue
            if d not in accepted_ids:
                deps_ok = False
                break
        if not deps_ok:
            continue
        conflict = False
        for r in running_dicts:
            if not can_run_parallel(task, r, all_tasks):
                conflict = True
                break
        if conflict:
            continue
        candidates.append(task)
    return candidates

def prioritize(candidates: list[dict]) -> list[dict]:
    """Pure sort by priority bucket then brief mtime ascending.

    Priority order: critical(0) > high(1) > medium(2) > low(3) > unset(4).
    Ties broken by the ``_mtime`` field attached by
    :func:`collect_dispatchable_tasks` (ascending).
    """

    def _key(t: dict) -> tuple[int, float]:
        prio = t.get('priority') if isinstance(t, dict) else None
        if isinstance(prio, str):
            rank = _PRIORITY_RANK.get(prio.lower(), _UNSET_RANK)
        else:
            rank = _UNSET_RANK
        m = t.get('_mtime', 0.0) if isinstance(t, dict) else 0.0
        try:
            mf = float(m)
        except (TypeError, ValueError):
            mf = 0.0
        return (rank, mf)
    return sorted(candidates, key=_key)

def _pause_flag_path(state_dir: pathlib.Path) -> pathlib.Path:
    return state_dir / 'control' / 'autowork' / 'pause'

def _full_stop_path(state_dir: pathlib.Path) -> pathlib.Path:
    """G-FULLSTOP: a single operator-persistent 'full stop' sentinel.

    When present it halts BOTH dispatch (_decide) and promotion (_auto_promote)
    AND stops the daemon loop (run_daemon breaks -> daemon_stop) AND the
    run-autowork.sh supervisor's respawn. Unlike pause it is never auto-cleared
    — the operator removes it to resume.
    """
    return state_dir / 'control' / 'autowork' / 'full_stop'

def _running_dir(state_dir: pathlib.Path) -> pathlib.Path:
    return state_dir / 'control' / 'autowork' / 'running'

def _reap_running(state_dir: pathlib.Path) -> set[str]:
    """Scan running pidfiles; remove stale ones; return live task_ids."""
    rdir = _running_dir(state_dir)
    if not rdir.exists():
        return set()
    live: set[str] = set()
    try:
        entries = list(rdir.glob('*.pid'))
    except OSError:
        return set()
    for p in entries:
        try:
            txt = p.read_text(encoding='utf-8').strip()
            pid = int(txt)
        except (OSError, ValueError):
            try:
                p.unlink()
            except OSError:
                pass
            continue
        try:
            reaped_pid, _status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                try:
                    p.unlink()
                except OSError:
                    pass
                continue
            except PermissionError:
                live.add(p.stem)
                continue
            except OSError:
                try:
                    p.unlink()
                except OSError:
                    pass
                continue
            live.add(p.stem)
            continue
        except OSError:
            try:
                p.unlink()
            except OSError:
                pass
            continue
        if reaped_pid != 0:
            try:
                p.unlink()
            except OSError:
                pass
            continue
        live.add(p.stem)
    return live

def _drain_running(state_dir: pathlib.Path, grace: float=30.0) -> int:
    """Wait for spawned worker pids in running/ to exit, SIGKILL stragglers (G-DRAINEXIT).

    On SIGTERM the loop breaks but spawned orchestrator_worker subprocesses keep
    running -> orphans (reclaimed only next run). This os.waitpid()'s each live
    pid up to ``grace`` seconds total, then SIGKILLs any that remain. Emits
    drain_start / drain_complete telemetry. Best-effort; never raises. Returns
    the count of pids SIGKILLed past grace."""
    rdir = _running_dir(state_dir)
    if not rdir.exists():
        return 0
    try:
        entries = list(rdir.glob('*.pid'))
    except OSError:
        return 0
    pids: list[tuple[int, pathlib.Path]] = []
    for p in entries:
        try:
            pid = int(p.read_text(encoding='utf-8').strip())
        except (OSError, ValueError):
            continue
        pids.append((pid, p))
    if not pids:
        return 0
    _emit_telemetry(state_dir, '', 'drain_start', f'{len(pids)} worker(s) grace={grace:.0f}s')
    deadline = time.time() + float(grace)
    remaining = list(pids)
    while remaining and time.time() < deadline:
        still: list[tuple[int, pathlib.Path]] = []
        for pid, p in remaining:
            try:
                reaped, _status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                try:
                    os.kill(pid, 0)
                except OSError:
                    reaped = pid
                else:
                    reaped = 0
            except OSError:
                reaped = pid
            if reaped != 0:
                try:
                    p.unlink()
                except OSError:
                    pass
            else:
                still.append((pid, p))
        remaining = still
        if remaining:
            time.sleep(0.5)
    killed = 0
    for pid, p in remaining:
        try:
            os.kill(pid, signal.SIGKILL)
            killed += 1
        except OSError:
            pass
        try:
            os.waitpid(pid, 0)
        except (ChildProcessError, OSError):
            pass
        try:
            p.unlink()
        except OSError:
            pass
    _emit_telemetry(state_dir, '', 'drain_complete', f'killed={killed} drained={len(pids) - killed}')
    return killed

def _bump_blocked_sidecar(state_dir: pathlib.Path, task_id: str, outcome: str) -> int:
    """Bump the {attempts,last_outcome,ts} retry sidecar for a blocked task.

    Mirrors orchestrator._write_retry_sidecar; kept local so the daemon need not
    import the 127KB orchestrator module. Read-modify-write keeps ``attempts``
    monotonic across re-blocks. Returns the new attempt count.
    """
    blocked_dir = pathlib.Path(state_dir) / 'tasks' / 'blocked'
    sidecar = blocked_dir / f'{task_id}.retry.json'
    attempts = 0
    if sidecar.exists():
        try:
            prev = json.loads(sidecar.read_text(encoding='utf-8'))
            if isinstance(prev, dict) and isinstance(prev.get('attempts'), int) and (not isinstance(prev.get('attempts'), bool)):
                attempts = prev['attempts']
        except (OSError, ValueError):
            attempts = 0
    attempts += 1
    try:
        blocked_dir.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(json.dumps({'attempts': attempts, 'last_outcome': outcome, 'ts': time.time()}, sort_keys=True), encoding='utf-8')
    except OSError:
        pass
    return attempts

def _reclaim_orphan_processing(state_dir: pathlib.Path, live_ids: set[str]) -> int:
    """Route orphaned ``<id>.json.processing`` files (no live worker) to blocked/.

    G-ORPHAN: a SIGKILL/OOM/crash can leave a claimed task parked as
    ``<id>.json.processing`` forever -- no worker holds it, yet
    ``collect_dispatchable_tasks`` skips ``.processing`` files, so it never
    re-dispatches. Any ``.processing`` whose task_id is NOT in the post-reap
    live set is a genuine orphan; route it to blocked/ with a retry sidecar so
    ``_retry_blocked_tasks`` re-stages it under budget. Returns the count
    reclaimed.
    """
    state_dir = pathlib.Path(state_dir)
    tasks_dir = state_dir / 'tasks'
    if not tasks_dir.is_dir():
        return 0
    live = set(live_ids or set())
    reclaimed = 0
    try:
        entries = list(tasks_dir.glob('*.json.processing'))
    except OSError:
        return 0
    blocked_dir = tasks_dir / 'blocked'
    for p in entries:
        name = p.name
        if not name.endswith('.json.processing'):
            continue
        tid = name[:-len('.json.processing')]
        if not tid or tid in live:
            continue
        try:
            blocked_dir.mkdir(parents=True, exist_ok=True)
            dest = blocked_dir / f'{tid}.json'
            if dest.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
                continue
            p.rename(dest)
        except OSError:
            continue
        current_task_path = tasks_dir / f'current_task_{tid}.json'
        if current_task_path.exists():
            try:
                current_task_path.unlink()
            except OSError:
                pass
        _bump_blocked_sidecar(state_dir, tid, 'orphaned')
        _emit_telemetry(state_dir, tid, 'task_blocked', 'orphaned (no live worker) routed to blocked/')
        reclaimed += 1
    return reclaimed

def _get_errors_for_task(state_dir: pathlib.Path, task_id: str) -> str:
    import json
    import pathlib
    errors = []
    logs_dir = state_dir.parent / 'logs'
    fuzz_dir = logs_dir / 'fuzz_results'
    if fuzz_dir.exists() and fuzz_dir.is_dir():
        try:
            for p in fuzz_dir.glob(f'*{task_id}*.json'):
                try:
                    fuzz_data = json.loads(p.read_text(encoding='utf-8'))
                    if isinstance(fuzz_data, dict):
                        failures = fuzz_data.get('failures', [])
                        if failures:
                            errors.append(f'Fuzzing failures from {p.name}:\n' + json.dumps(failures[:5], indent=2))
                        elif fuzz_data.get('error'):
                            errors.append(f'Fuzzing error from {p.name}: {fuzz_data['error']}')
                except Exception:
                    pass
        except Exception:
            pass
    ledger = state_dir / 'impl_progress.jsonl'
    if ledger.exists():
        ledger_errors = []
        try:
            with open(ledger, 'r', encoding='utf-8') as f:
                for line in f:
                    if task_id in line:
                        try:
                            row = json.loads(line)
                            if not isinstance(row, dict):
                                continue
                            if row.get('stderr_tail'):
                                ledger_errors.append(f'stderr tail:\n{row['stderr_tail']}')
                            elif row.get('detail') and ('error' in line or 'fail' in line):
                                ledger_errors.append(f'Detail: {row['detail']}')
                        except Exception:
                            pass
        except Exception:
            pass
        errors.extend(ledger_errors[-10:])
    # AGENT-ISOLATION §3.7: agent workdirs relocated outside the repo; read
    # error reports from the shared workroot, not state_dir/workdirs (dead).
    from harness.paths import agent_workroot
    workdirs_dir = agent_workroot()
    if workdirs_dir.exists():
        try:
            for agent in ['claude', 'gemini', 'antigravity']:
                agent_dir = workdirs_dir / agent
                if agent_dir.exists():
                    for p in agent_dir.glob(f'*-{task_id}-*/outbox/error.md'):
                        try:
                            errors.append(f'Agent error report ({p.parent.parent.name}):\n{p.read_text(encoding='utf-8')}')
                        except Exception:
                            pass
        except Exception:
            pass
    if errors:
        combined = '\n\n'.join(errors)
        if len(combined) > 100000:
            combined = combined[-100000:] + '\n\n[Traceback truncated due to length limits]'
        return combined
    return 'No traceback or fuzz error logs found.'

def _contain_selfheal(cmd: list, env: dict, work_dir, state_dir, config: dict | None, agent: str = '') -> list:
    """CONTAIN C7: apply the C1 env-decouple + C2 bwrap jail to a daemon
    self-heal agent spawn, mirroring ``orchestrator.spawn_agent``.

    The daemon deliberately does NOT import ``orchestrator`` (it keeps spawn
    helpers local so it need not load the 127KB module -- see _bump_blocked_sidecar
    et al.), so the C1/C2 logic is inlined here against ``harness.paths`` +
    ``harness.agent_jail`` ONLY. Before C7 the two self-heal ``Popen`` sites
    (retry-budget + inactivity) called ``subprocess.Popen`` directly, bypassing the
    jail / env-decouple / --tools that CONTAIN closed on the ``spawn_agent`` path
    (plan rev3.1 §1a; the same uncontained-absolute-path-write class as GAP_H4).

    Mutates ``env`` in place (C1) and returns the possibly jail-wrapped ``cmd`` (C2).
    """
    from harness.paths import PROJECT_ROOT_STR
    work_dir_s = str(work_dir)
    # C1: point CLAUDE_PROJECT_DIR at the per-spawn OUTSIDE-repo work_dir (not the
    # live repo claude would otherwise resolve its project root / hook discovery /
    # ${CLAUDE_PROJECT_DIR} interpolation from). JANUSMASK_PROJECT_DIR stays the repo
    # (trusted hook read-roots); explicit PYTHONPATH keeps `import harness.*` working.
    env['CLAUDE_PROJECT_DIR'] = work_dir_s
    env['JANUSMASK_PROJECT_DIR'] = PROJECT_ROOT_STR
    _pp = env.get('PYTHONPATH', '')
    env['PYTHONPATH'] = PROJECT_ROOT_STR if not _pp else PROJECT_ROOT_STR + os.pathsep + _pp
    # C2: wrap in the bwrap jail (repo read-only) when enabled. Fail-closed:
    # build_jail_argv raises if bwrap is missing while the gate is on, so a
    # misconfigured host aborts the self-heal rather than spawning un-jailed.
    from harness import agent_jail
    # J3 (C7-R): fail-closed hook-config parity with orchestrator.spawn_agent
    # (orchestrator.py:339-340). For a claude self-heal, assert the effective
    # --settings file declares a PreToolUse hook BEFORE wrapping in the jail (the
    # assertion reads --settings out of the RAW agent argv; the bwrap wrap buries it
    # after the '--' separator). Lazy import keeps the 127KB orchestrator module off
    # the daemon's hot path (the no-import-orchestrator rule in this fn's docstring);
    # it only loads when a claude self-heal actually fires. Raises RuntimeError on a
    # missing/hookless settings file -- the caller's spawn-exception handling (or the
    # bwrap-missing FileNotFoundError already raised below) turns it into a no-spawn.
    if agent == 'claude':
        from harness.orchestrator import _assert_claude_hook_config
        _assert_claude_hook_config(cmd)
    if agent_jail.sandbox_enabled(config):
        # SEC-1c-DAEMON: thread the daemon-lifetime filtered D-Bus proxy socket
        # opened once by run_daemon at startup. Read defensively via globals() so a
        # never-started daemon (the unit-test default) sees None and adds no
        # per-escalation proxy Popen.
        # SEC-1 FAIL-CLOSED: if the daemon's proxy init genuinely FAILED
        # (_SELFHEAL_DBUS_PROXY_FAILED is True) and the xdg-dbus-proxy binary resolves
        # on PATH, refuse to spawn rather than thread None and bind the unfiltered host
        # session bus into the jail (which re-exposes systemd1 StartTransientUnit -- a
        # sandbox escape). A never-started daemon leaves the flag absent/None, so the
        # graceful path (thread None) is preserved for backward compatibility.
        import shutil
        if globals().get('_SELFHEAL_DBUS_PROXY_FAILED') and shutil.which('xdg-dbus-proxy') is not None:
            raise RuntimeError('agent_sandbox is enabled and xdg-dbus-proxy is present but the filtered D-Bus proxy failed to start; refusing to spawn an agent on the unfiltered host bus (fail-closed).')
        _dbus_sock = globals().get('_SELFHEAL_DBUS_SOCKET')
        cmd = agent_jail.build_jail_argv(cmd, repo_root=PROJECT_ROOT_STR, work_dir=work_dir_s, state_dir=str(state_dir), dbus_proxy_socket=_dbus_sock)
    return cmd


def _runaway_counter_bump(state_dir, ceiling):
    """Persisted read-modify-write of the self-heal runaway-ceiling counter.

    The daemon-global cascade budget for self-heal escalations is PERSISTED to
    state/control/autowork/runaway_ceiling.json ({"count": int}) so it survives
    daemon restarts and repeated --once invocations (the in-memory
    _SELFHEAL_ESCALATION_COUNT global resets to 0 each fresh process, which
    would otherwise let a crash-loop / repeated --once re-arm the budget
    indefinitely). Shared by both _escalate_to_autobrief (normal fix-cascades)
    and _escalate_inactivity.

    Returns ``(tripped, count)`` where ``count`` is the PRE-bump persisted count
    (mirroring the old ``globals().get('_SELFHEAL_ESCALATION_COUNT', 0)`` read so
    the callers' ``_SELFHEAL_ESCALATION_COUNT = count + 1`` update stays
    correct). If the persisted count is already >= ``ceiling`` it returns
    ``(True, count)`` WITHOUT incrementing; otherwise it writes ``count + 1``
    back to the file and returns ``(False, count)``.

    RESET POLICY: operator-cleared only -- delete runaway_ceiling.json to reset
    the counter; there is no automatic reset.

    Edge cases: a missing / empty / corrupt / non-dict / non-int-count JSON file
    defaults to count=0. An advisory fcntl LOCK_EX is held across the
    read-modify-write when available, falling back gracefully to an unlocked
    read-modify-write where flock is unsupported. A filesystem error
    creating/opening the persistence file FAILS OPEN (returns (False, 0)) so a
    transient FS fault never permanently wedges self-heal.
    """
    import json
    import os
    import pathlib
    state_dir = pathlib.Path(state_dir)
    path = state_dir / 'control' / 'autowork' / 'runaway_ceiling.json'
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return (False, 0)
    try:
        import fcntl
    except Exception:
        fcntl = None
    try:
        with open(path, 'a+', encoding='utf-8') as f:
            if fcntl is not None:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX)
                except OSError:
                    fcntl = None
            try:
                count = 0
                try:
                    f.seek(0)
                    raw = f.read()
                    data = json.loads(raw) if raw.strip() else {}
                    if isinstance(data, dict):
                        c = data.get('count')
                        if isinstance(c, int) and (not isinstance(c, bool)):
                            count = c
                except (ValueError, OSError):
                    count = 0
                if count >= ceiling:
                    return (True, count)
                try:
                    f.seek(0)
                    f.truncate()
                    f.write(json.dumps({'count': count + 1}))
                    f.flush()
                except OSError:
                    return (False, 0)
                return (False, count)
            finally:
                if fcntl is not None:
                    try:
                        fcntl.flock(f, fcntl.LOCK_UN)
                    except OSError:
                        pass
    except OSError:
        return (False, 0)
def _escalate_to_autobrief(state_dir: pathlib.Path, task_id: str, last_outcome: str) -> None:
    import json
    import os
    import pathlib
    import subprocess
    import sys
    import time
    import uuid
    state_dir = pathlib.Path(state_dir)
    task_json_path = state_dir / 'tasks' / 'blocked' / f'{task_id}.json'
    files_touched = []
    objective = ''
    if task_json_path.exists():
        try:
            with open(task_json_path, 'r', encoding='utf-8') as f:
                task_data = json.load(f)
                if isinstance(task_data, dict):
                    files_touched = task_data.get('files_touched', [])
                    objective = task_data.get('objective', '')
        except Exception:
            pass
    _errs = _get_errors_for_task(state_dir, task_id)
    _no_errors = (not _errs) or _errs.strip() == 'No traceback or fuzz error logs found.'
    if (not task_json_path.exists()) or (not str(objective or '').strip() and not files_touched and _no_errors):
        _reason = 'missing_task_json' if not task_json_path.exists() else 'empty_objective_files_no_errors'
        _emit_telemetry(state_dir, task_id, 'skip_degenerate_escalation', _reason)
        return
    config_path = pathlib.Path('harness/config.yaml')
    if not config_path.is_file():
        config_path = state_dir.parent / 'harness' / 'config.yaml'
    config = {}
    if yaml is not None and config_path.is_file():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
        except Exception:
            pass
    if not isinstance(config, dict):
        config = {}
    # RUNAWAY_CEILING (PERSISTED): daemon-level GLOBAL cascade ceiling for
    # self-heal escalations, now PERSISTED to disk in
    # state/control/autowork/runaway_ceiling.json ({"count": int}) so the budget
    # survives daemon restarts and repeated --once invocations (the in-memory
    # _SELFHEAL_ESCALATION_COUNT resets to 0 each fresh process, which would
    # otherwise let a crash-loop re-arm the budget indefinitely). Degenerate
    # skips above already returned and so never reach this budget. The check sits
    # AFTER the degenerate-skip return and AFTER config is available.
    # RESET POLICY: operator-cleared only -- delete runaway_ceiling.json to reset
    # the counter; there is no automatic reset.
    ceiling = _autowork_section(config).get('max_total_selfheal_escalations', 50)
    if not isinstance(ceiling, int):
        ceiling = 50
    tripped, count = _runaway_counter_bump(state_dir, ceiling)
    global _SELFHEAL_ESCALATION_COUNT
    if tripped:
        # Keep the backward-compatible in-memory global in sync with the
        # persisted count when the ceiling trips.
        _SELFHEAL_ESCALATION_COUNT = count
        _emit_telemetry(state_dir, task_id, 'runaway_ceiling_tripped', f'dropped escalation, count={count}/{ceiling}')
        return
    # count is the PRE-bump count; the persisted file now holds count + 1.
    _SELFHEAL_ESCALATION_COUNT = count + 1
    control = config.get('control', {})
    agent = control.get('autobrief_default_agent', 'claude') if isinstance(control, dict) else 'claude'
    if not agent:
        agent = 'claude'
    history_dir = state_dir / 'control' / 'autowork'
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / 'self_healing_history.jsonl'
    record = {'ts': time.time(), 'task_id': task_id, 'files_touched': files_touched, 'outcome': last_outcome, 'spec_objective': objective}
    line = json.dumps(record, sort_keys=True) + '\n'
    try:
        import fcntl
        with open(history_path, 'a', encoding='utf-8') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(line)
                f.flush()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        try:
            with open(history_path, 'a', encoding='utf-8') as f:
                f.write(line)
        except Exception:
            pass
    agents = config.get('agents', {})
    agent_cfg = agents.get(agent, {}) if isinstance(agents, dict) else {}
    if not agent_cfg:
        # M9 (folded into CONTAIN C7): the bare 'agy'/'claude' fallback is an
        # uncontrolled binary off PATH (possibly un-sandboxed / not the vendored
        # build). Use the VENDORED agents under ${PROJECT_ROOT}/.agents/... (resolved
        # by subst()), mirroring config.yaml's agents.* incl. the C4 --tools allowlist
        # for claude. M9 alone is necessary but NOT sufficient -- the C7 jail below
        # is what closes the containment gap.
        if agent == 'gemini':
            agent_cfg = {'command': '${PROJECT_ROOT}/.agents/agy/agy', 'args': ['-p', '--sandbox']}
        else:
            # J2: --verbose is REQUIRED for `--output-format stream-json` under -p in the
            # vendored claude-code (else it aborts "stream-json requires --verbose" before
            # submitting -- the same claude-jail-fix failure-class). The config-derived
            # path (config.yaml agents.claude.args) already carries it; this M9 vendored
            # fallback (used when config['agents']['claude'] is absent) must carry it too.
            agent_cfg = {'command': '${PROJECT_ROOT}/.agents/claude-code/node_modules/.bin/claude', 'args': ['-p', '--model', 'opus', '--output-format', 'stream-json', '--include-partial-messages', '--verbose', '--settings', '${CONFIG_DIR}/claude_worker.json', '--mcp-config', '${CONFIG_DIR}/claude_mcp.json', '--strict-mcp-config', '--setting-sources', '', '--tools', 'Read,Glob,Grep,Write', '--disallowedTools', 'Bash,Edit,Task,NotebookEdit,WebFetch,WebSearch,Skill,ToolSearch']}
    command_tmpl = agent_cfg.get('command', 'claude')
    args_tmpl = agent_cfg.get('args', [])
    from harness.paths import PROJECT_ROOT_STR, CONFIG_DIR_STR, HARNESS_DIR_STR, agent_work_dir

    def subst(s: str) -> str:
        if not isinstance(s, str):
            return s
        s = s.replace('${PROJECT_ROOT}', PROJECT_ROOT_STR)
        s = s.replace('${STATE_DIR}', str(state_dir))
        s = s.replace('${CONFIG_DIR}', CONFIG_DIR_STR)
        s = s.replace('${HARNESS_DIR}', HARNESS_DIR_STR)
        return s
    command = subst(command_tmpl)
    args = [subst(arg) for arg in args_tmpl]
    rewire = {str(pathlib.Path(CONFIG_DIR_STR) / 'claude_worker.json'): str(pathlib.Path(CONFIG_DIR_STR) / 'claude_worker_planning_hooks.json'), str(pathlib.Path(CONFIG_DIR_STR) / 'gemini_worker_policy.toml'): str(pathlib.Path(CONFIG_DIR_STR) / 'gemini_worker_policy_planning.toml')}
    args = [rewire.get(a, a) for a in args]
    if agent == 'claude' and '--permission-mode' not in args:
        args = args + ['--permission-mode', 'acceptEdits']
    errors_str = _get_errors_for_task(state_dir, task_id)
    # AGENT-ISOLATION §3.8.3: the self-heal agent must write ONLY into its
    # outbox and must NOT touch the live repo, run git, or edit the auto-promote
    # allowlist. Promotion is an operator decision (see memory:
    # ex-phantom-task-no-promote — never auto-append <task>_fix).
    prompt = f"The task '{task_id}' has exhausted its retry budget. Investigate and propose a self-healing plan.\nObjective: {objective}\nFiles touched: {files_touched}\n\n--- Traceback/Fuzz Error Logs ---\n{errors_str}\n\nInstructions:\n1. Write your diagnosis and a proposed brief to your OUTBOX at {{OUTBOX_PATH}}/brief_hooks_{task_id}_fix.md. Do NOT write anywhere outside your outbox, and do NOT run git.\n2. Do NOT edit the auto-promote allowlist or any file in the live repository; promotion is an operator decision. If you believe '{task_id}_fix' should be promoted, recommend it in your outbox brief for operator review."
    # SEC_ENV_ALLOWLIST: copy ONLY allowlisted host env into the jailed self-heal
    # agent (IDENTICAL allowlist to orchestrator._build_agent_env), scrubbing
    # operator secrets (GITHUB_TOKEN, AWS_*, etc). JANUSMASK_* overlays follow.
    _ENV_ALLOW_EXACT = frozenset(('PATH', 'HOME', 'LANG', 'LANGUAGE', 'LC_ALL', 'TERM', 'SHELL', 'USER', 'LOGNAME', 'TZ', 'TMPDIR', 'PWD', 'DBUS_SESSION_BUS_ADDRESS', 'GOOGLE_GENAI_USE_GCA', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'NODE_EXTRA_CA_CERTS', 'CURL_CA_BUNDLE', 'NO_PROXY', 'no_proxy', 'HTTP_PROXY', 'http_proxy', 'HTTPS_PROXY', 'https_proxy'))
    _ENV_ALLOW_PREFIXES = ('JANUSMASK_', 'XDG_', 'NVM_', 'NODE_', 'GEMINI_', 'GOOGLE_', 'ANTHROPIC_', 'CLAUDE_', 'LC_')
    env = {k: v for k, v in os.environ.items() if k in _ENV_ALLOW_EXACT or any((k.startswith(p) for p in _ENV_ALLOW_PREFIXES))}
    env['JANUSMASK_MODE'] = 'planning'
    env['JANUSMASK_TASK_ID'] = task_id
    env['JANUSMASK_STATE_DIR'] = str(state_dir)
    session_slug = f'{agent}-r1-{task_id}-{uuid.uuid4().hex[:8]}'
    # AGENT-ISOLATION §3.8: relocate the daemon self-heal workdir OUTSIDE the
    # repo via the shared helper (agree with the orchestrator + _env fallback).
    work_dir = agent_work_dir(agent, session_slug)
    env['JANUSMASK_WORK_DIR'] = str(work_dir)
    outbox_path = work_dir / 'outbox'
    outbox_path.mkdir(parents=True, exist_ok=True)
    inbox_dir = work_dir / 'inbox'
    inbox_dir.mkdir(parents=True, exist_ok=True)
    brief_data = {'task_id': task_id, 'objective': objective, 'files_touched': files_touched}
    try:
        with open(inbox_dir / 'brief.json', 'w', encoding='utf-8') as f:
            json.dump(brief_data, f)
    except OSError:
        pass
    resolved_prompt = prompt.replace('{STATE_DIR}', str(state_dir)).replace('{OUTBOX_PATH}', str(outbox_path))
    try:
        p_index = args.index('-p')
        cmd = [command] + args[:p_index + 1] + [resolved_prompt] + args[p_index + 1:]
    except ValueError:
        cmd = [command] + args + ['-p', resolved_prompt]
    # CONTAIN C7: decouple CLAUDE_PROJECT_DIR + jail this self-heal spawn (was a
    # direct Popen that bypassed all of CONTAIN -- plan rev3.1 §1a).
    cmd = _contain_selfheal(cmd, env, work_dir, state_dir, config, agent)
    try:
        proc = subprocess.Popen(cmd, env=env, cwd=str(work_dir))  # AGENT-ISOLATION §3.8: cwd = isolated outside-repo workdir
        _write_pidfile(state_dir, f'selfheal_{agent}_{task_id}_{proc.pid}', proc.pid)
    except Exception as exc:
        _emit_telemetry(state_dir, task_id, 'spawn_failed', repr(exc))

def _retry_blocked_tasks(state_dir: pathlib.Path, summary: dict, max_attempts: int=3) -> int:
    """Re-stage blocked task JSONs back to tasks/ under a retry budget + backoff.

    G-BLOCKED: a non-accept terminal now lands in blocked/ with a
    {attempts,last_outcome,ts} sidecar (see orchestrator._mark_blocked). This
    re-stages each blocked task back to the live queue once its backoff window
    elapses, mirroring ``_recently_failed_to_plan``'s escalating tiers (300s ->
    3600s -> 86400s). Past ``max_attempts`` the task stays parked and a single
    ``retry_exhausted`` row is emitted. Returns the count re-staged.
    """
    state_dir = pathlib.Path(state_dir)
    tasks_dir = state_dir / 'tasks'
    blocked_dir = tasks_dir / 'blocked'
    if not blocked_dir.is_dir():
        return 0
    try:
        entries = sorted(blocked_dir.glob('*.json'))
    except OSError:
        return 0
    restaged = 0
    for p in entries:
        if p.name.endswith('.retry.json'):
            continue
        tid = p.name[:-len('.json')] if p.name.endswith('.json') else p.stem
        sidecar = blocked_dir / f'{tid}.retry.json'
        attempts, last_ts, last_outcome = (0, 0.0, '')
        if sidecar.exists():
            try:
                d = json.loads(sidecar.read_text(encoding='utf-8'))
                if isinstance(d, dict):
                    a = d.get('attempts')
                    attempts = a if isinstance(a, int) and (not isinstance(a, bool)) else 0
                    last_ts = float(d.get('ts', 0) or 0)
                    lo = d.get('last_outcome')
                    last_outcome = lo if isinstance(lo, str) else ''
            except (OSError, ValueError):
                attempts, last_ts, last_outcome = (0, 0.0, '')
        _DETERMINISTIC_OUTCOMES = ('synthesis_or_ast_failed', 'smoke_failed', 'embedded_tests_failed', 'narrow_fuzz_failed')
        effective_max = 1 if last_outcome in _DETERMINISTIC_OUTCOMES else max_attempts
        if attempts >= effective_max:
            exhausted = blocked_dir / f'{tid}.exhausted'
            if not exhausted.exists():
                try:
                    exhausted.write_text('1', encoding='utf-8')
                except OSError:
                    pass
                _emit_telemetry(state_dir, tid, 'retry_exhausted', f'blocked retry budget {effective_max} exhausted (outcome={last_outcome or 'unknown'})')
                try:
                    _escalate_to_autobrief(state_dir, tid, last_outcome)
                except Exception as exc:
                    _emit_telemetry(state_dir, tid, 'escalation_failed', repr(exc))
            continue
        if attempts <= 1:
            threshold = 300.0
        elif attempts == 2:
            threshold = 3600.0
        else:
            threshold = 86400.0
        if time.time() - last_ts < threshold:
            continue
        dest = tasks_dir / f'{tid}.json'
        if dest.exists():
            continue
        try:
            p.rename(dest)
        except OSError:
            continue
        _emit_telemetry(state_dir, tid, 'extract', f'retry_blocked attempts={attempts}')
        if isinstance(summary, dict):
            summary['extracts'] = summary.get('extracts', 0) + 1
        restaged += 1
    return restaged

def _write_pidfile(state_dir: pathlib.Path, task_id: str, pid: int) -> None:
    rdir = _running_dir(state_dir)
    try:
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / f'{task_id}.pid').write_text(str(pid), encoding='utf-8')
    except OSError:
        pass

def _spawn_worker(state_dir: pathlib.Path, task_id: str) -> int | None:
    # CONTAIN C7 (trusted-worker boundary): this spawns the TRUSTED harness worker
    # (`python -m harness.orchestrator_worker`), NOT an agent CLI -- so it needs no
    # bwrap jail. The worker itself routes any agent spawn through
    # orchestrator.spawn_agent (jailed). Asserted by test_TC1_1; if a future change
    # ever routes an agent CLI through here it MUST go through _contain_selfheal.
    cmd = [sys.executable, '-m', 'harness.orchestrator_worker', '--state-dir', str(state_dir), '--task-id', task_id]
    try:
        proc = subprocess.Popen(cmd, start_new_session=True)
        return proc.pid
    except (OSError, ValueError) as exc:
        _emit_telemetry(state_dir, task_id, 'spawn_failed', repr(exc))
        return None
MAX_REBUILD_ATTEMPTS = 5

def _rebuild_pid_name(slug: str) -> str:
    """Pidfile stem for a rebuild loop subprocess (distinct from task pidfiles)."""
    return f'rebuild__{slug}'

def _spawn_rebuild_worker(state_dir: pathlib.Path, job: dict) -> int | None:
    from harness.rebuild import job as _job
    # CONTAIN C7 (trusted-worker boundary): build_loop_command returns the TRUSTED
    # rebuild loop (`python -m harness.rebuild.loop ...`), NOT an agent CLI; agent
    # spawns inside the loop route through orchestrator.spawn_agent (jailed). No
    # bwrap wrap here. A future agent-CLI reroute MUST go through _contain_selfheal.
    cmd = _job.build_loop_command(job)
    try:
        proc = subprocess.Popen(cmd, cwd=_job.parent_root())
        return proc.pid
    except (OSError, ValueError) as exc:
        _emit_telemetry(state_dir, _rebuild_pid_name(job.get('job_id', '')), 'rebuild_spawn_failed', repr(exc))
        return None

def _has_active_rebuild_job(state_dir: pathlib.Path) -> bool:
    """B9: True when a rebuild job is pending or running (not complete/blocked).

    run_daemon's ``is_idle`` must stay False while such a job exists so the
    daemon keeps the short poll cadence and detects rebuild completion promptly
    instead of idle-sleeping the long heartbeat after a ``rebuild_launch``.
    A ``complete`` job (or one parked ``blocked`` past MAX_REBUILD_ATTEMPTS) does
    not keep the daemon busy.
    """
    try:
        from harness.rebuild import job as _job
        for j in _job.list_jobs(state_dir):
            st = _job.job_status(state_dir, j.get('job_id', ''), persist=False)
            if st.get('complete'):
                continue
            if j.get('status') == 'blocked':
                continue
            return True
    except Exception:
        return False
    return False

def _watch_rebuild_jobs(repo_root: pathlib.Path, state_dir: pathlib.Path, running: set[str], *, config: dict | None=None, dry_run: bool=False) -> None:
    """Model A rebuild-watcher: supervise a resumable loop per allowlisted job.

    Orthogonal to task dispatch -- it does NOT consume worker slots. Each call:
    skip jobs already running (pidfile live this iteration), skip complete jobs,
    park jobs that exhausted MAX_REBUILD_ATTEMPTS, else spawn ``loop.py --resume``
    and pidfile it so the existing _reap_running / _drain_running machinery
    supervises it exactly like a worker. The subprocess itself spawns
    orchestrator_worker per unit (the proven retarget dogfood) into the OUTPUT
    repo, committing every accepted body there.
    """
    try:
        from harness.rebuild import job as _job
        jobs = _job.list_jobs(state_dir)
    except Exception as exc:
        _emit_telemetry(state_dir, '', 'rebuild_skip', f'list_jobs error: {exc!r}')
        return
    if not jobs:
        return
    allow = _auto_promote_allowlist(state_dir) or set()
    for job in jobs:
        slug = job.get('job_id')
        if not slug or slug not in allow:
            continue
        pidname = _rebuild_pid_name(slug)
        if pidname in running:
            continue
        try:
            st = _job.job_status(state_dir, slug, persist=False)
        except Exception as exc:
            _emit_telemetry(state_dir, pidname, 'rebuild_skip', f'status error: {exc!r}')
            continue
        if st.get('complete'):
            if job.get('status') != 'complete':
                _emit_telemetry(state_dir, pidname, 'rebuild_complete', f'head={st.get('head_sha')}')
                _mark_rebuild_job(state_dir, slug, status='complete')
            continue
        attempts = int(job.get('attempts', 0) or 0)
        if attempts >= MAX_REBUILD_ATTEMPTS:
            if job.get('status') != 'blocked':
                _mark_rebuild_job(state_dir, slug, status='blocked')
                _emit_telemetry(state_dir, pidname, 'rebuild_blocked', f'exhausted {attempts} attempts; remaining={len(st.get('remaining', []))}')
            continue
        if dry_run:
            _emit_telemetry(state_dir, pidname, 'rebuild_dry_run', f'would resume; remaining={len(st.get('remaining', []))}')
            continue
        pid = _spawn_rebuild_worker(state_dir, job)
        if pid is None:
            continue
        _write_pidfile(state_dir, pidname, pid)
        _mark_rebuild_job(state_dir, slug, status='running', attempts=attempts + 1)
        _emit_telemetry(state_dir, pidname, 'rebuild_launch', f'pid={pid} attempt={attempts + 1} remaining={len(st.get('remaining', []))}')

def _mark_rebuild_job(state_dir: pathlib.Path, slug: str, *, status: str | None=None, attempts: int | None=None) -> None:
    path = pathlib.Path(state_dir) / 'control' / 'rebuild' / 'jobs' / f'{slug}.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return
    if status is not None:
        data['status'] = status
    if attempts is not None:
        data['attempts'] = attempts
    data['updated_ts'] = time.time()
    try:
        path.write_text(json.dumps(data, indent=2), encoding='utf-8')
    except OSError:
        pass

def _plan_attempt_marker_path(state_dir: pathlib.Path, slug: str) -> pathlib.Path:
    return pathlib.Path(state_dir) / 'control' / 'autowork' / 'plan_attempts' / f'{slug}.json'

def _recently_failed_to_plan(state_dir: pathlib.Path, slug: str) -> bool:
    marker = _plan_attempt_marker_path(state_dir, slug)
    try:
        raw = marker.read_text(encoding='utf-8')
    except (OSError, FileNotFoundError):
        return False
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    if 'last_ts' not in data:
        return False
    last_ts_raw = data.get('last_ts')
    if isinstance(last_ts_raw, bool) or not isinstance(last_ts_raw, (int, float)):
        return False
    last_ts = float(last_ts_raw)
    attempts_raw = data.get('attempts', 0)
    if isinstance(attempts_raw, bool) or not isinstance(attempts_raw, int):
        return False
    attempts = attempts_raw
    if attempts <= 1:
        threshold = 300.0
    elif attempts == 2:
        threshold = 3600.0
    else:
        threshold = 86400.0
    return time.time() - last_ts < threshold

def _run_planner_subprocess(brief_path: pathlib.Path, output_plan: pathlib.Path, state_dir: pathlib.Path, timeout_sec: float=300.0) -> tuple[int, float, str]:
    cmd = [sys.executable, '-m', 'harness.planner.cli', str(brief_path), '--output-plan', str(output_plan)]
    started = time.time()
    try:
        proc = subprocess.run(cmd, timeout=timeout_sec, capture_output=True)
    except subprocess.TimeoutExpired as e:
        stderr_tail = ''
        err_bytes = getattr(e, 'stderr', None)
        if err_bytes is not None:
            try:
                stderr_tail = err_bytes[-512:].decode('utf-8', errors='replace')
            except (AttributeError, TypeError, UnicodeDecodeError):
                stderr_tail = ''
        return (124, float(timeout_sec), stderr_tail)
    except OSError:
        return (127, 0.0, '')
    wall = time.time() - started
    try:
        rc = int(proc.returncode)
    except (TypeError, ValueError):
        rc = 1
    stderr_tail = ''
    if proc.stderr is not None:
        try:
            stderr_tail = proc.stderr[-512:].decode('utf-8', errors='replace')
        except (AttributeError, TypeError, UnicodeDecodeError):
            stderr_tail = ''
    return (rc, float(wall), stderr_tail)

def _check_hallucination(plan_dict: dict, wall_seconds: float, min_wall: float=10.0) -> tuple[bool, str]:
    try:
        wall = float(wall_seconds)
    except (TypeError, ValueError):
        wall = 0.0
    if wall < float(min_wall):
        return (True, 'wall<min')
    tasks = plan_dict.get('tasks') if isinstance(plan_dict, dict) else None
    if not isinstance(tasks, list) or not tasks:
        return (True, 'empty_plan')
    all_gemini = True
    any_reconciled = False
    for t in tasks:
        if not isinstance(t, dict):
            all_gemini = False
            break
        meta = t.get('attribution_metadata')
        if not isinstance(meta, dict):
            all_gemini = False
            break
        if meta.get('proposed_by') != 'gemini':
            all_gemini = False
        if meta.get('reconciled') is True:
            any_reconciled = True
    if all_gemini and (not any_reconciled):
        return (True, 'all_gemini_no_reconciled')
    return (False, '')

def _auto_promote(repo_root: pathlib.Path, state_dir: pathlib.Path, config: dict | None=None, dry_run: bool=False) -> dict:
    """Stage unstaged plan tasks and kick off at most one unplanned brief.

    Returns a small telemetry dict ``{'extracts': int, 'plan_kickoffs':
    int, 'discarded': int}`` so unit tests can introspect the pass.

    When ``dry_run`` is True all MUTATIONS (retry re-stage, stage_task,
    planner kickoff) are skipped; the pass only enumerates and emits
    ``dry_run`` telemetry so ``--dry-run`` is genuinely side-effect-free
    (G-DRYRUN).
    """
    from harness._journal import write_jsonl_row
    repo_root = pathlib.Path(repo_root)
    state_dir = pathlib.Path(state_dir)
    if _auto_promote_disabled(state_dir) or _full_stop_path(state_dir).exists():
        return {'extracts': 0, 'plan_kickoffs': 0, 'discarded': 0}
    if dry_run:
        summary = {'extracts': 0, 'plan_kickoffs': 0, 'discarded': 0}
        try:
            records = compute_brief_status(repo_root, state_dir)
        except Exception:
            records = []
        for rec in records or []:
            if not isinstance(rec, dict):
                continue
            slug = rec.get('slug') or ''
            if rec.get('has_plan') and rec.get('unstaged_task_ids'):
                _emit_telemetry(state_dir, '', 'dry_run', f'would extract {slug}: {rec.get('unstaged_task_ids')}')
            elif rec.get('state') == 'unplanned':
                _emit_telemetry(state_dir, '', 'dry_run', f'would plan_kickoff {slug}')
        return summary
    summary = {'extracts': 0, 'plan_kickoffs': 0, 'discarded': 0}
    try:
        _retry_blocked_tasks(state_dir, summary)
    except Exception as exc:
        try:
            write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.time(), 'phase': 'autowork', 'task_id': '', 'event': 'silent_skip', 'detail': f'retry_blocked: {type(exc).__name__}: {exc!r}', 'phase_tag': 'auto_promote_step_0_retry_blocked', 'exit': 0})
        except OSError:
            pass
    try:
        records = compute_brief_status(repo_root, state_dir)
    except Exception:
        records = []
    try:
        for rec in records or []:
            if not isinstance(rec, dict):
                continue
            if not rec.get('has_plan'):
                continue
            if not _auto_promote_brief_eligible(state_dir, rec.get('slug') or '', rec.get('brief_mtime', 0), max_age_sec=_brief_max_age(config or {})):
                continue
            unstaged = rec.get('unstaged_task_ids') or []
            plan_filename = rec.get('plan_filename')
            if not isinstance(plan_filename, str) or not plan_filename:
                continue
            plan_path = repo_root / plan_filename
            slug = rec.get('slug') or ''
            stamped_working_dir: str | None = None
            try:
                _plan_obj = json.loads(plan_path.read_text(encoding='utf-8'))
                if isinstance(_plan_obj, dict):
                    _wd = _plan_obj.get('working_dir')
                    if isinstance(_wd, str) and _wd:
                        stamped_working_dir = _wd
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                stamped_working_dir = None
            # BOOTSTRAP (REV22 §4-7): when a plan targets an EXTERNAL repo
            # (working_dir present AND classified not-self), idempotently
            # bootstrap it BEFORE staging its tasks. SELF-builds (working_dir
            # absent or self) are untouched. Bootstrap is best-effort: a
            # failure emits telemetry but does NOT skip staging (staging is
            # the pre-existing behavior and must be preserved), and never
            # raises into the iteration loop. Reachable from BOTH run_daemon
            # and main(--once) via _iteration -> _auto_promote.
            if stamped_working_dir:
                try:
                    from harness.paths import _target_is_self as _bs_is_self
                    if not _bs_is_self(stamped_working_dir):
                        from harness.target_bootstrap import bootstrap_target as _bs_bootstrap
                        _bs_bootstrap(stamped_working_dir)
                except Exception as _bs_exc:
                    try:
                        write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.time(), 'phase': 'autowork', 'task_id': '', 'event': 'silent_skip', 'detail': f'bootstrap {slug}: {type(_bs_exc).__name__}: {_bs_exc!r}', 'phase_tag': 'auto_promote_step_0b_bootstrap', 'exit': 0})
                    except OSError:
                        pass
            for tid in unstaged:
                if not isinstance(tid, str) or not tid:
                    continue
                try:
                    stage_task(plan_path, tid, state_dir, canonical=True, working_dir=stamped_working_dir)
                except FileExistsError:
                    continue
                except (FileNotFoundError, KeyError, ValueError, OSError, json.JSONDecodeError) as exc:
                    try:
                        write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.time(), 'phase': 'autowork', 'task_id': tid, 'event': 'silent_skip', 'detail': f'stage_task {slug} {tid}: {type(exc).__name__}: {exc!r}', 'phase_tag': 'auto_promote_step_1_stage_task', 'exit': 0})
                    except OSError:
                        pass
                    continue
                _emit_telemetry(state_dir, tid, 'extract', slug)
                summary['extracts'] += 1
    except OSError as exc:
        try:
            write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.time(), 'phase': 'autowork', 'task_id': '', 'event': 'silent_skip', 'detail': f'extract_loop: {type(exc).__name__}: {exc!r}', 'phase_tag': 'auto_promote_step_2_extract_loop', 'exit': 0})
        except OSError:
            pass
    try:
        target_slug: str | None = None
        target_brief_path: pathlib.Path | None = None
        for rec in records or []:
            if not isinstance(rec, dict):
                continue
            if rec.get('state') != 'unplanned':
                continue
            slug = rec.get('slug') or ''
            if not slug:
                continue
            if not _auto_promote_brief_eligible(state_dir, slug, rec.get('brief_mtime', 0), max_age_sec=_brief_max_age(config or {})):
                continue
            brief_filename = rec.get('brief_filename')
            if not isinstance(brief_filename, str) or not brief_filename:
                continue
            brief_path = repo_root / brief_filename
            try:
                size = brief_path.stat().st_size
            except OSError:
                continue
            max_size = _brief_max_size(config or {})
            if size >= max_size:
                _emit_telemetry(state_dir, '', 'brief_too_large', f'{slug} size={size} max={max_size}')
                continue
            if _recently_failed_to_plan(state_dir, slug):
                continue
            target_slug = slug
            target_brief_path = brief_path
            break
        if target_slug is not None and target_brief_path is not None:
            output_plan = repo_root / f'plan_hooks_{target_slug}.json'
            timeout_sec = _planner_timeout(config or {})
            try:
                rc, wall, stderr_tail = _run_planner_subprocess(target_brief_path, output_plan, state_dir, timeout_sec=timeout_sec)
            except Exception:
                rc, wall, stderr_tail = (1, 0.0, '')
            if not isinstance(stderr_tail, str):
                stderr_tail = ''
            if rc == 124:
                try:
                    if output_plan.exists():
                        output_plan.unlink()
                except OSError:
                    pass
                marker = _plan_attempt_marker_path(state_dir, target_slug)
                try:
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    prev_attempts = 0
                    try:
                        existing = json.loads(marker.read_text(encoding='utf-8'))
                        if isinstance(existing, dict):
                            cand = existing.get('attempts', 0)
                            if isinstance(cand, int) and (not isinstance(cand, bool)):
                                prev_attempts = cand
                    except (OSError, FileNotFoundError, json.JSONDecodeError, ValueError):
                        prev_attempts = 0
                    marker.write_text(json.dumps({'attempts': prev_attempts + 1, 'last_ts': time.time()}, sort_keys=True), encoding='utf-8')
                except OSError:
                    pass
                _emit_telemetry(state_dir, '', 'plan_timeout', f'{target_slug} timeout={timeout_sec:.0f}s')
                summary['discarded'] += 1
                return summary
            plan_dict: dict = {}
            if output_plan.exists():
                try:
                    raw = output_plan.read_text(encoding='utf-8')
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        plan_dict = parsed
                except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                    plan_dict = {}
            hallucinated, why = _check_hallucination(plan_dict, wall, min_wall=_planner_min_wall(config or {}))
            if hallucinated:
                try:
                    if output_plan.exists():
                        output_plan.unlink()
                except OSError:
                    pass
                marker = _plan_attempt_marker_path(state_dir, target_slug)
                try:
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    prev_attempts = 0
                    try:
                        existing_raw = marker.read_text(encoding='utf-8')
                        existing = json.loads(existing_raw)
                        if isinstance(existing, dict):
                            cand = existing.get('attempts', 0)
                            if isinstance(cand, int) and (not isinstance(cand, bool)):
                                prev_attempts = cand
                    except (OSError, FileNotFoundError, json.JSONDecodeError, ValueError):
                        prev_attempts = 0
                    payload = {'attempts': prev_attempts + 1, 'last_ts': time.time()}
                    marker.write_text(json.dumps(payload, sort_keys=True), encoding='utf-8')
                except OSError:
                    pass
                detail = f'{target_slug} wall={wall:.1f} reason={why}'
                if stderr_tail:
                    escaped = stderr_tail[:256].replace('\n', '\\n').replace('\r', '\\r')
                    detail = f'{detail} stderr_tail={escaped}'
                _emit_telemetry(state_dir, '', 'planner_hallucination_discarded', detail)
                summary['discarded'] += 1
            else:
                _emit_telemetry(state_dir, '', 'plan_kickoff', f'{target_slug} wall={wall:.1f}')
                summary['plan_kickoffs'] += 1
    except OSError as exc:
        try:
            write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.time(), 'phase': 'autowork', 'task_id': '', 'event': 'silent_skip', 'detail': f'plan_kickoff: {type(exc).__name__}: {exc!r}', 'phase_tag': 'auto_promote_step_3_plan_kickoff', 'exit': 0})
        except OSError:
            pass
    return summary

def _decide(repo_root: pathlib.Path, state_dir: pathlib.Path, running_task_ids: set[str], cap: int) -> tuple[list[dict], bool, int]:
    try:
        status_records = compute_brief_status(repo_root, state_dir)
    except Exception:
        status_records = []
    candidates = collect_dispatchable_tasks(status_records, running_task_ids, state_dir)
    ordered = prioritize(candidates)
    free = max(0, cap - len(running_task_ids))
    paused = _pause_flag_path(state_dir).exists() or _full_stop_path(state_dir).exists()
    if paused or free <= 0:
        return ([], paused, free)
    running_dicts = _load_running_task_dicts(state_dir, running_task_ids)
    all_tasks: list[dict] = list(ordered) + running_dicts
    admitted: list[dict] = []
    for cand in ordered:
        conflict_with: str | None = None
        for a in admitted:
            if not can_run_parallel(cand, a, all_tasks):
                conflict_with = a.get('task_id', '') if isinstance(a, dict) else ''
                break
        if conflict_with is None:
            for r in running_dicts:
                if not can_run_parallel(cand, r, all_tasks):
                    conflict_with = r.get('task_id', '') if isinstance(r, dict) else ''
                    break
        if conflict_with is not None:
            tid = cand.get('task_id', '') if isinstance(cand, dict) else ''
            _emit_telemetry(state_dir, tid, 'skip', f'in-iteration conflict with {conflict_with}')
            continue
        admitted.append(cand)
        if len(admitted) >= free:
            break
    chosen = admitted[:free]
    return (chosen, paused, free)

def suspend_parallel_workers(state_dir: pathlib.Path, exclude_pid: int) -> None:
    global _suspended_pids, _suspension_start_times
    rdir = _running_dir(state_dir)
    if not rdir.exists():
        return
    daemon_pid = os.getpid()
    for p in rdir.glob('*.pid'):
        try:
            pid = int(p.read_text(encoding='utf-8').strip())
            if pid == exclude_pid or pid == daemon_pid:
                continue
            os.kill(pid, signal.SIGSTOP)
            _suspended_pids.add(pid)
            _suspension_start_times[pid] = time.time()
            _emit_telemetry(state_dir, p.stem, 'suspend', f'pid={pid}')
        except Exception:
            pass

def resume_parallel_workers(state_dir: pathlib.Path) -> None:
    global _suspended_pids, _suspension_start_times
    for pid in list(_suspended_pids):
        try:
            os.kill(pid, signal.SIGCONT)
            _emit_telemetry(state_dir, '', 'resume', f'pid={pid}')
        except Exception:
            pass
    _suspended_pids.clear()
    _suspension_start_times.clear()

def _iteration(repo_root: pathlib.Path, state_dir: pathlib.Path, cap: int, *, dry_run: bool, config: dict | None=None) -> dict:
    running = _reap_running(state_dir)
    # PARALLEL-WORKER-WATCHDOG: the parallel _spawn_worker branch is fire-and-forget
    # (no watchdog, unlike the sequential branch), so a hung/suspended parallel worker
    # would leak its slot forever. Sweep running/ pidfiles whose mtime (~spawn time;
    # written once, never rewritten) is older than the 1800s hang threshold AND whose
    # pid is still alive (os.kill(pid, 0) -- NOT waitpid, the worker may be an inherited
    # orphan), SIGKILL them and unlink the pidfile. Sequential pidfiles live and die
    # inside one blocking _iteration call so they are never aged out here. Wrapped so a
    # sweep failure never breaks the iteration.
    try:
        rdir = _running_dir(state_dir)
        if rdir.exists():
            now = time.time()
            for pidfile in rdir.glob('*.pid'):
                try:
                    if now - pidfile.stat().st_mtime <= 1800:
                        continue
                    pid = int(pidfile.read_text(encoding='utf-8').strip())
                    try:
                        os.kill(pid, 0)
                    except OSError:
                        continue
                    os.kill(pid, signal.SIGKILL)
                    try:
                        pidfile.unlink()
                    except OSError:
                        pass
                    _emit_telemetry(state_dir, pidfile.stem, 'watchdog_kill', f'hung parallel worker pid={pid} (>1800s)')
                except (OSError, ValueError):
                    continue
    except Exception as exc:
        _emit_telemetry(state_dir, '', 'skip', f'parallel watchdog error: {exc!r}')
    try:
        _reclaim_orphan_processing(state_dir, running)
    except Exception as exc:
        _emit_telemetry(state_dir, '', 'skip', f'reclaim_orphan error: {exc!r}')
    promote_summary: dict = {'extracts': 0, 'plan_kickoffs': 0, 'discarded': 0}
    try:
        res = _auto_promote(repo_root, state_dir, config=config or {}, dry_run=dry_run)
        if isinstance(res, dict):
            promote_summary = res
    except Exception as exc:
        _emit_telemetry(state_dir, '', 'skip', f'auto_promote error: {exc!r}')
    chosen, paused, free = _decide(repo_root, state_dir, running, cap)
    try:
        _watch_rebuild_jobs(repo_root, state_dir, running, config=config, dry_run=dry_run)
    except Exception as exc:
        _emit_telemetry(state_dir, '', 'rebuild_skip', f'watch error: {exc!r}')
    would_launch = [t['task_id'] for t in chosen]
    try:
        extracts_count = int(promote_summary.get('extracts', 0) or 0)
    except (TypeError, ValueError):
        extracts_count = 0
    try:
        plan_kickoffs_count = int(promote_summary.get('plan_kickoffs', 0) or 0)
    except (TypeError, ValueError):
        plan_kickoffs_count = 0
    if dry_run:
        for tid in would_launch:
            _emit_telemetry(state_dir, tid, 'dry_run', 'would launch')
        return {'would_launch': would_launch, 'free_slots': free, 'cap': cap, 'paused': paused, 'extracts': extracts_count, 'plan_kickoffs': plan_kickoffs_count}
    launched: list[str] = []
    cfg = config or {}
    active_agents = cfg.get('synthesis', {}).get('active_agents', ['claude', 'gemini'])
    requires_claude = cfg.get('synthesis', {}).get('antigravity_mode', True) or 'claude' in active_agents or 'antigravity' in active_agents
    if not paused:
        for task in chosen:
            tid = task['task_id']
            now_ts = time.time()
            if tid not in _dispatch_timestamps:
                _dispatch_timestamps[tid] = []
            _dispatch_timestamps[tid].append(now_ts)
            _dispatch_timestamps[tid] = [ts for ts in _dispatch_timestamps[tid] if now_ts - ts <= 300.0]
            if len(_dispatch_timestamps[tid]) >= 10:
                tasks_dir = state_dir / 'tasks'
                quarantine_dir = tasks_dir / 'quarantine'
                quarantine_dir.mkdir(parents=True, exist_ok=True)
                src_path = tasks_dir / f'{tid}.json'
                dest_path = quarantine_dir / f'{tid}.json'
                if src_path.exists():
                    try:
                        src_path.replace(dest_path)
                    except OSError:
                        try:
                            import shutil
                            shutil.move(str(src_path), str(dest_path))
                        except Exception as err:
                            _ = err
                _emit_telemetry(state_dir, tid, 'quarantine', 'loop spinning detected: 10 dispatches in last 5m')
                continue
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
                    pid = proc.pid
                    _write_pidfile(state_dir, tid, pid)
                    suspend_parallel_workers(state_dir, exclude_pid=pid)
                    _emit_telemetry(state_dir, tid, 'launch', f'pid={pid}')
                    launched.append(tid)
                    seq_start = time.time()
                    synthesis_cfg = cfg.get('synthesis', {}) if isinstance(cfg, dict) else {}
                    timeout_val = synthesis_cfg.get('timeout_seconds', 900) if isinstance(synthesis_cfg, dict) else 900
                    try:
                        watchdog_timeout = max(1800.0, 2.0 * float(timeout_val) + 600.0)
                    except (TypeError, ValueError):
                        watchdog_timeout = 1800.0
                    try:
                        while proc.poll() is None:
                            now = time.time()
                            if now - seq_start > watchdog_timeout:
                                _emit_telemetry(state_dir, tid, 'timeout', f'sequential worker timed out ({watchdog_timeout / 60:.0f} min)')
                                _kill_process_group(state_dir, tid, proc)
                                proc.wait()
                                break
                            to_remove = set()
                            for spid in _suspended_pids:
                                if now - _suspension_start_times.get(spid, now) > 300:
                                    try:
                                        os.kill(spid, signal.SIGKILL)
                                        _emit_telemetry(state_dir, str(spid), 'watchdog_kill', f'pid={spid}')
                                    except Exception as err:
                                        _ = err
                                    to_remove.add(spid)
                            for spid in to_remove:
                                _suspended_pids.discard(spid)
                                _suspension_start_times.pop(spid, None)
                            time.sleep(1.0)
                    except Exception as exc:
                        _ = exc
                except Exception as exc:
                    _emit_telemetry(state_dir, tid, 'spawn_failed', repr(exc))
                finally:
                    rdir = _running_dir(state_dir)
                    pid_file = rdir / f'{tid}.pid'
                    if pid_file.exists():
                        try:
                            pid_file.unlink()
                        except OSError:
                            pass
                    resume_parallel_workers(state_dir)
            else:
                pid = _spawn_worker(state_dir, tid)
                if pid is None:
                    _emit_telemetry(state_dir, tid, 'skip', 'popen failed')
                    continue
                _write_pidfile(state_dir, tid, pid)
                _emit_telemetry(state_dir, tid, 'launch', f'pid={pid}')
                launched.append(tid)
    return {'would_launch': launched, 'free_slots': free, 'cap': cap, 'paused': paused, 'extracts': extracts_count, 'plan_kickoffs': plan_kickoffs_count}

def _autowork_watch_mtime(repo_root: pathlib.Path, state_dir: pathlib.Path) -> float:
    """Max mtime across the allowlist file + ``brief_hooks_*.md`` (G-IDLE wake signal).

    The idle daemon sleeps a long heartbeat; without a wake signal an operator's
    allowlist edit or new brief is unseen for up to ``heartbeat`` seconds. The
    idle sleep loop breaks early when this value changes.
    """
    latest = 0.0
    try:
        allow = pathlib.Path(state_dir) / 'control' / 'autowork' / 'auto_promote.allowlist'
        if allow.exists():
            latest = max(latest, allow.stat().st_mtime)
    except OSError:
        pass
    try:
        for b in pathlib.Path(repo_root).glob('brief_hooks_*.md'):
            try:
                latest = max(latest, b.stat().st_mtime)
            except OSError:
                continue
    except OSError:
        pass
    return latest

def _push_enabled(state_dir: pathlib.Path) -> bool:
    return (pathlib.Path(state_dir) / 'control' / 'autowork' / 'push.enabled').exists()

def _maybe_push_and_rebase_pin(repo_root: pathlib.Path, state_dir: pathlib.Path) -> dict:
    """Opt-in post-commit durability (G-PUSH/G-DRIFT). Default-OFF, never raises.

    Gated by the presence of ``state/control/autowork/push.enabled`` so a daemon
    is local-only unless an operator opts in. When enabled and HEAD is ahead of
    ``origin/main``, pushes under the AW3 ``git_commit.lock``, then rebases the
    ``EXPECTED_BASE_SHA`` drift pin via ``scripts/impl_rebase_drift_pin.py`` and
    commits+pushes the pin if it moved. All git steps are best-effort with
    telemetry; a failure emits a row and returns without raising.
    """
    if not _push_enabled(state_dir):
        return {'pushed': False, 'reason': 'disabled'}
    repo_root = pathlib.Path(repo_root)
    out: dict = {'pushed': False, 'rebased': False}
    lock_path = pathlib.Path(state_dir) / 'control' / 'autowork' / 'git_commit.lock'
    try:
        import fcntl
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, 'a') as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                ahead = subprocess.run(['git', 'rev-list', '--count', 'origin/main..HEAD'], cwd=str(repo_root), capture_output=True, text=True, timeout=30)
                try:
                    n_ahead = int((ahead.stdout or '0').strip() or '0')
                except ValueError:
                    n_ahead = 0
                if ahead.returncode != 0 or n_ahead <= 0:
                    out['reason'] = 'up_to_date'
                    return out
                push = subprocess.run(['git', 'push', 'origin', 'main'], cwd=str(repo_root), capture_output=True, text=True, timeout=180)
                if push.returncode != 0:
                    _emit_telemetry(state_dir, '', 'push_failed', (push.stderr or '')[-256:])
                    return out
                out['pushed'] = True
                _emit_telemetry(state_dir, '', 'pushed', f'origin/main +{n_ahead}')
                reb = subprocess.run([sys.executable, 'scripts/impl_rebase_drift_pin.py'], cwd=str(repo_root), capture_output=True, text=True, timeout=60)
                if reb.returncode == 0:
                    dirty = subprocess.run(['git', 'diff', '--quiet', '--', 'scripts/impl_common.py'], cwd=str(repo_root), timeout=30)
                    if dirty.returncode != 0:
                        subprocess.run(['git', 'commit', '-m', 'META: rebase EXPECTED_BASE_SHA drift pin (autowork post-push)', '--', 'scripts/impl_common.py'], cwd=str(repo_root), capture_output=True, text=True, timeout=30)
                        subprocess.run(['git', 'push', 'origin', 'main'], cwd=str(repo_root), capture_output=True, text=True, timeout=180)
                        out['rebased'] = True
                        _emit_telemetry(state_dir, '', 'drift_pin_rebased', '')
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        _emit_telemetry(state_dir, '', 'push_error', repr(exc))
    return out

def _resume_or_kill_orphaned_workers(state_dir: pathlib.Path, config: dict) -> None:
    """DAEMON-STARTUP-ORPHAN: sweep running/ pidfiles once at daemon startup.

    A crash/restart between SIGSTOP and SIGCONT strands a parallel worker in T
    (stopped) state with its pidfile still under _running_dir(state_dir). The
    in-memory _suspended_pids does not survive a restart, and _reap_running's
    os.kill(pid, 0) liveness probe SUCCEEDS for a live-but-stopped pid, so the
    orphan is treated as live, never reaped, and its parallel slot leaks
    forever while the T-state worker never makes progress.

    This best-effort sweep probes each pidfile with os.kill(pid, 0) -- NOT
    os.waitpid, because an inherited orphan is NOT a child of the restarted
    daemon. A dead pid (ProcessLookupError / non-Permission OSError) has its
    pidfile unlinked; a PermissionError pidfile is left alone (someone else
    owns it); a live pid is resumed with SIGCONT so the stranded worker runs to
    completion and frees its slot. Per-pidfile work is wrapped so the sweep
    never raises.
    """
    rdir = _running_dir(state_dir)
    if not rdir.exists():
        return
    try:
        entries = list(rdir.glob('*.pid'))
    except OSError:
        return
    for p in entries:
        try:
            try:
                pid = int(p.read_text(encoding='utf-8').strip())
            except (OSError, ValueError):
                try:
                    p.unlink()
                except OSError:
                    pass
                continue
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                try:
                    p.unlink()
                except OSError:
                    pass
                continue
            except PermissionError:
                continue
            except OSError:
                try:
                    p.unlink()
                except OSError:
                    pass
                continue
            try:
                os.kill(pid, signal.SIGCONT)
            except OSError:
                pass
            _emit_telemetry(state_dir, p.stem, 'resume_orphan', f'pid={pid}')
        except Exception:
            continue
def run_daemon(repo_root: pathlib.Path, state_dir: pathlib.Path, config: dict) -> int:
    """Run the polling loop. Returns 0 on clean shutdown."""
    global _shutdown_requested
    _shutdown_requested = False
    _install_sigterm_handler()
    cap = _parallel_cap(config)
    poll = _poll_interval(config)
    heartbeat = _heartbeat_interval(config)
    global _daemon_start_time
    _daemon_start_time = time.time()
    _emit_telemetry(state_dir, '', 'daemon_start', f'cap={cap} poll={poll} heartbeat={heartbeat}')
    # PHASE_ABSTRACT_SOCKET_WARN: detect-and-warn ONLY. The jail does not unshare
    # net/ipc on synthesis spawn, so a non-cooperative jailed process could dial
    # the host abstract-namespace session bus directly. If the host
    # DBUS_SESSION_BUS_ADDRESS points to an abstract socket (unix:abstract=...),
    # emit a WARNING telemetry row. A path socket (unix:path=...) or a
    # missing/empty value is a NO-OP. This never raises, blocks, or exits.
    _dbus_addr = os.environ.get('DBUS_SESSION_BUS_ADDRESS', '')
    if 'unix:abstract=' in _dbus_addr:
        _emit_telemetry(state_dir, '', 'abstract_bus_residual_warning', f'host DBUS_SESSION_BUS_ADDRESS points to an abstract-namespace socket ({_dbus_addr}); the jail does not unshare net/ipc on synthesis spawn so a non-cooperative jailed process could dial the host session bus directly')
    # BINARY_ABSENT_REFUSE (REV22 §2b / CR-8): when the host session bus is ACTIVE
    # but xdg-dbus-proxy is ABSENT, the jail degrades to dbus_proxy_socket=None and
    # mounts the REAL host session bus unjailed (agent_jail.py:287 region) -- a
    # systemd1/D-Bus escape that survives even when sandbox_enabled() is True. With
    # full_stop gone, refuse to run unattended in that configuration. Escape hatch:
    # set JANUSMASK_ALLOW_HOSTBUS=1 to opt into the unjailed host bus explicitly.
    import shutil as _bar_shutil
    if os.environ.get('DBUS_SESSION_BUS_ADDRESS', '') and _bar_shutil.which('xdg-dbus-proxy') is None and (not os.environ.get('JANUSMASK_ALLOW_HOSTBUS')):
        raise RuntimeError('refusing unattended daemon start: host D-Bus session bus is active but xdg-dbus-proxy is absent; the jail would mount the real host session bus unjailed (systemd1/D-Bus escape). Install xdg-dbus-proxy or set JANUSMASK_ALLOW_HOSTBUS=1 to override.')
    try:
        _resume_or_kill_orphaned_workers(state_dir, config)
    except Exception as exc:
        _emit_telemetry(state_dir, '', 'skip', f'orphan sweep error: {exc!r}')
    try:
        marker_path = pathlib.Path(state_dir) / 'control' / 'autowork' / 'inactivity_escalated.json'
        if marker_path.exists():
            marker_path.unlink()
    except OSError:
        pass
    # SEC-1c-DAEMON: open ONE daemon-lifetime filtered D-Bus proxy at startup (only
    # when the sandbox is enabled) and stash its socket in a module global so the
    # single self-heal funnel _contain_selfheal can thread it into every detached
    # build_jail_argv spawn. SEC-1 FAIL-CLOSED: track whether a genuine proxy spawn
    # attempt FAILED via the runtime global _SELFHEAL_DBUS_PROXY_FAILED so the
    # self-heal funnel can refuse to spawn on the unfiltered host bus when the proxy
    # binary is present but the proxy could not start. The globals are created here
    # at runtime (no module-level assignment); all imports are lazy in-body.
    global _SELFHEAL_DBUS_SOCKET, _SELFHEAL_DBUS_STACK, _SELFHEAL_DBUS_PROXY_FAILED
    _SELFHEAL_DBUS_SOCKET = None
    _SELFHEAL_DBUS_STACK = None
    _SELFHEAL_DBUS_PROXY_FAILED = False
    try:
        from harness import agent_jail as _agent_jail
        if _agent_jail.sandbox_enabled(config):
            import contextlib
            from harness.dbus_proxy import proxied_session_bus
            stack = contextlib.ExitStack()
            try:
                _SELFHEAL_DBUS_SOCKET = stack.enter_context(proxied_session_bus())
                _SELFHEAL_DBUS_STACK = stack
            except Exception as exc:
                _SELFHEAL_DBUS_SOCKET = None
                _SELFHEAL_DBUS_STACK = None
                _SELFHEAL_DBUS_PROXY_FAILED = True
                try:
                    stack.close()
                except Exception:
                    pass
                _emit_telemetry(state_dir, '', 'skip', f'dbus proxy init error: {exc!r}')
    except Exception as exc:
        _SELFHEAL_DBUS_SOCKET = None
        _SELFHEAL_DBUS_STACK = None
        _SELFHEAL_DBUS_PROXY_FAILED = True
        _emit_telemetry(state_dir, '', 'skip', f'dbus proxy init error: {exc!r}')
    prev_paused: bool | None = None
    prev_is_idle: bool = False
    try:
        while not _shutdown_requested:
            if _full_stop_path(state_dir).exists():
                _emit_telemetry(state_dir, '', 'full_stop', 'full_stop sentinel present; shutting down')
                break
            paused_now = _pause_flag_path(state_dir).exists()
            if prev_paused is None or paused_now != prev_paused:
                if paused_now:
                    _emit_telemetry(state_dir, '', 'pause', 'pause flag set')
                elif prev_paused is True:
                    _emit_telemetry(state_dir, '', 'resume', 'pause flag cleared')
            prev_paused = paused_now
            result: dict = {'would_launch': [], 'free_slots': 0, 'cap': cap, 'paused': paused_now, 'extracts': 0, 'plan_kickoffs': 0}
            try:
                result = _iteration(repo_root, state_dir, cap, dry_run=False, config=config)
            except Exception as exc:
                _emit_telemetry(state_dir, '', 'skip', f'iteration error: {exc!r}')
            try:
                _maybe_push_and_rebase_pin(repo_root, state_dir)
            except Exception as exc:
                _emit_telemetry(state_dir, '', 'push_error', f'{exc!r}')
            is_idle = not paused_now and result.get('free_slots', 0) == result.get('cap', 0) and (not result.get('would_launch'))
            is_idle = is_idle and (not result.get('plan_kickoffs', 0))
            is_idle = is_idle and (not _has_active_rebuild_job(state_dir))
            if is_idle and (not prev_is_idle):
                _emit_telemetry(state_dir, '', 'idle', f'heartbeat={heartbeat}')
            elif not is_idle and prev_is_idle:
                _emit_telemetry(state_dir, '', 'active', '')
            prev_is_idle = is_idle
            try:
                _check_inactivity_watchdog(repo_root, state_dir, config)
            except Exception as exc:
                _emit_telemetry(state_dir, '', 'skip', f'watchdog error: {exc!r}')
            sleep_target = heartbeat if is_idle else poll
            slept = 0.0
            step = 0.5 if sleep_target > 0.5 else sleep_target
            watch_baseline = _autowork_watch_mtime(repo_root, state_dir) if is_idle else None
            while slept < sleep_target and (not _shutdown_requested):
                time.sleep(step)
                slept += step
                if is_idle and _autowork_watch_mtime(repo_root, state_dir) != watch_baseline:
                    _emit_telemetry(state_dir, '', 'idle_wake', 'allowlist/brief change detected')
                    break
    finally:
        try:
            _drain_running(state_dir, grace=30.0)
        except Exception as exc:
            _emit_telemetry(state_dir, '', 'skip', f'drain error: {exc!r}')
        try:
            if _SELFHEAL_DBUS_STACK is not None:
                _SELFHEAL_DBUS_STACK.close()
        except Exception:
            pass
        _SELFHEAL_DBUS_SOCKET = None
        _SELFHEAL_DBUS_STACK = None
        _SELFHEAL_DBUS_PROXY_FAILED = False
        _emit_telemetry(state_dir, '', 'daemon_stop', 'shutdown')
    return 0

def main(argv: list[str] | None=None) -> int:
    parser = argparse.ArgumentParser(prog='harness.autowork_daemon', description='JanusMask autowork polling daemon (AW4a).')
    parser.add_argument('--state-dir', type=pathlib.Path, required=True, help='Path to the shared state directory.')
    parser.add_argument('--once', action='store_true', help='Run a single decision iteration and exit.')
    parser.add_argument('--dry-run', action='store_true', help='Print would-launch JSON without spawning workers.')
    parser.add_argument('--config', type=pathlib.Path, default=pathlib.Path('harness/config.yaml'), help='Path to harness/config.yaml.')
    args = parser.parse_args(argv)
    state_dir: pathlib.Path = args.state_dir.resolve()
    repo_root: pathlib.Path = pathlib.Path.cwd()
    config = _load_config(args.config)
    cap = _parallel_cap(config)
    if args.dry_run:
        result = _iteration(repo_root, state_dir, cap, dry_run=True, config=config)
        sys.stdout.write(json.dumps(result) + '\n')
        sys.stdout.flush()
        return 0
    if args.once:
        _install_sigterm_handler()
        _emit_telemetry(state_dir, '', 'daemon_start', f'cap={cap} mode=once')
        # PHASE_ABSTRACT_SOCKET_WARN (--once parity): detect-and-warn ONLY, identical
        # to run_daemon. The jail does not unshare net/ipc on synthesis spawn, so a
        # non-cooperative jailed process could dial the host abstract-namespace
        # session bus directly. If the host DBUS_SESSION_BUS_ADDRESS points to an
        # abstract socket (unix:abstract=...), emit a WARNING telemetry row. A path
        # socket (unix:path=...) or a missing/empty value is a NO-OP. This never
        # raises, blocks, or exits.
        _dbus_addr = os.environ.get('DBUS_SESSION_BUS_ADDRESS', '')
        if 'unix:abstract=' in _dbus_addr:
            _emit_telemetry(state_dir, '', 'abstract_bus_residual_warning', f'host DBUS_SESSION_BUS_ADDRESS points to an abstract-namespace socket ({_dbus_addr}); the jail does not unshare net/ipc on synthesis spawn so a non-cooperative jailed process could dial the host session bus directly')
        # BINARY_ABSENT_REFUSE (REV22 §2b / CR-8, --once parity): identical to
        # run_daemon. When the host session bus is ACTIVE but xdg-dbus-proxy is
        # ABSENT, the jail degrades to dbus_proxy_socket=None and mounts the REAL
        # host session bus unjailed -- a systemd1/D-Bus escape that survives even
        # when sandbox_enabled() is True. Refuse to run unattended unless the
        # operator opts in via JANUSMASK_ALLOW_HOSTBUS=1.
        import shutil as _bar_shutil
        if os.environ.get('DBUS_SESSION_BUS_ADDRESS', '') and _bar_shutil.which('xdg-dbus-proxy') is None and (not os.environ.get('JANUSMASK_ALLOW_HOSTBUS')):
            raise RuntimeError('refusing unattended daemon start: host D-Bus session bus is active but xdg-dbus-proxy is absent; the jail would mount the real host session bus unjailed (systemd1/D-Bus escape). Install xdg-dbus-proxy or set JANUSMASK_ALLOW_HOSTBUS=1 to override.')
        # SEC-1c-DAEMON (--once parity): mirror run_daemon's startup block so the
        # supervised single-iteration path also opens ONE daemon-lifetime filtered
        # D-Bus proxy (only when the sandbox is enabled) and stashes its socket in
        # the module global that _contain_selfheal threads into every detached
        # build_jail_argv spawn. SEC-1 FAIL-CLOSED: track whether a genuine proxy
        # spawn attempt FAILED via the runtime global _SELFHEAL_DBUS_PROXY_FAILED so
        # the self-heal funnel can refuse to spawn on the unfiltered host bus when
        # the proxy binary is present but the proxy could not start -- identical to
        # run_daemon. The globals are created here at runtime (no module-level
        # assignment); all imports are lazy in-body.
        global _SELFHEAL_DBUS_SOCKET, _SELFHEAL_DBUS_STACK, _SELFHEAL_DBUS_PROXY_FAILED
        _SELFHEAL_DBUS_SOCKET = None
        _SELFHEAL_DBUS_STACK = None
        _SELFHEAL_DBUS_PROXY_FAILED = False
        try:
            from harness import agent_jail as _agent_jail
            if _agent_jail.sandbox_enabled(config):
                import contextlib
                from harness.dbus_proxy import proxied_session_bus
                stack = contextlib.ExitStack()
                try:
                    _SELFHEAL_DBUS_SOCKET = stack.enter_context(proxied_session_bus())
                    _SELFHEAL_DBUS_STACK = stack
                except Exception as exc:
                    _SELFHEAL_DBUS_SOCKET = None
                    _SELFHEAL_DBUS_STACK = None
                    _SELFHEAL_DBUS_PROXY_FAILED = True
                    try:
                        stack.close()
                    except Exception:
                        pass
                    _emit_telemetry(state_dir, '', 'skip', f'dbus proxy init error: {exc!r}')
        except Exception as exc:
            _SELFHEAL_DBUS_SOCKET = None
            _SELFHEAL_DBUS_STACK = None
            _SELFHEAL_DBUS_PROXY_FAILED = True
            _emit_telemetry(state_dir, '', 'skip', f'dbus proxy init error: {exc!r}')
        try:
            _iteration(repo_root, state_dir, cap, dry_run=False, config=config)
        finally:
            # SEC-1c-DAEMON (--once parity): reap the daemon-lifetime singleton
            # proxy stack so the supervised once path never leaks an
            # xdg-dbus-proxy process; reset both globals back to None.
            try:
                if _SELFHEAL_DBUS_STACK is not None:
                    _SELFHEAL_DBUS_STACK.close()
            except Exception:
                pass
            _SELFHEAL_DBUS_SOCKET = None
            _SELFHEAL_DBUS_STACK = None
            _emit_telemetry(state_dir, '', 'daemon_stop', 'once complete')
        return 0
    return run_daemon(repo_root, state_dir, config)

def _load_running_task_dicts(state_dir: pathlib.Path, running_task_ids: set[str]) -> list[dict]:
    """Look up running task ids in ``state_dir/tasks/`` so parallelism checks
    see real ``files_touched``/``dependencies``. Missing files fall back to
    a minimal placeholder, mirroring :func:`collect_dispatchable_tasks`.
    """
    running_ids = set(running_task_ids or set())
    if not running_ids:
        return []
    tasks_dir = pathlib.Path(state_dir) / 'tasks'
    by_id: dict[str, dict] = {}
    if tasks_dir.exists() and tasks_dir.is_dir():
        try:
            entries = sorted(tasks_dir.iterdir())
        except OSError:
            entries = []
        for p in entries:
            if p.is_dir() or p.suffix != '.json':
                continue
            if p.name.endswith('.processing') or p.name.endswith('.json.processing'):
                continue
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(data, dict) and isinstance(data.get('task_id'), str):
                by_id[data['task_id']] = data
    running_dicts: list[dict] = []
    for rid in running_ids:
        if rid in by_id:
            running_dicts.append(by_id[rid])
        else:
            running_dicts.append({'task_id': rid, 'files_touched': []})
    return running_dicts
'Submission for G27_autowork_zombie_reap.\n\nReplaces the liveness probe in harness/autowork_daemon.py:_reap_running with\nos.waitpid(pid, os.WNOHANG) as the primary check (which both detects and reaps\nzombies), falling back to os.kill(pid, 0) only when waitpid raises\nChildProcessError (i.e. the pid is not a child of this process -- typically a\nstale pidfile from a prior daemon process).\n'
"Submission for AW9c_daemon_promote.\n\nAdds an in-process auto-promote pass to ``harness/autowork_daemon.py`` so\nthe polling daemon closes both Path A (extract tasks from existing plans)\nand Path B (kick off the planner on unplanned briefs) without shelling\nout. ``_iteration`` calls ``_auto_promote`` BEFORE ``_decide``; the call\nis wrapped in try/except so a promote failure can never raise into the\niteration loop -- it emits ``skip`` with the exception repr instead.\n\nModule additions (AST-merged by name into the target):\n\n* ``_plan_attempt_marker_path`` -- maps slug to the ``.failed`` marker\n  under ``state/control/autowork/plan_attempts/``.\n* ``_recently_failed_to_plan`` -- TTL-gated marker check (default 1h).\n* ``_run_planner_subprocess`` -- spawns ``python -m harness.planner.cli``\n  with timeout; returns ``(returncode, wall_seconds)``. The function is\n  the test seam: ``tests/adversarial/test_autowork_auto_promote.py``\n  monkeypatches it by attribute name on the module.\n* ``_check_hallucination`` -- returns ``(True, reason)`` when wall is\n  under ``min_wall`` OR every task is proposed_by=gemini with no\n  reconciled task. Otherwise ``(False, '')``.\n* ``_auto_promote`` -- enumerates briefs via ``compute_brief_status``,\n  stages every unstaged task_id (catching ``FileExistsError`` silently)\n  with an ``extract`` ledger row, then picks at most ONE ``unplanned``\n  brief (size < 50_000 bytes, no recent ``.failed`` marker) and runs the\n  planner. Hallucinated output is discarded -> ``.failed`` marker +\n  ``planner_hallucination_discarded`` row. Clean output emits\n  ``plan_kickoff``. Each phase is wrapped in try/except OSError to keep\n  the iteration loop resilient.\n* ``_iteration`` -- prefixed with the ``_auto_promote`` call inside a\n  try/except so the existing dispatch logic continues to run after a\n  promote failure. The rest of the body is byte-identical with the\n  pre-fix file.\n"
DEFAULT_BRIEF_MAX_AGE_SEC = 604800

def _auto_promote_disabled(state_dir) -> bool:
    try:
        return (pathlib.Path(state_dir) / 'control' / 'autowork' / 'auto_promote.disabled').exists()
    except OSError:
        return False

def _auto_promote_allowlist(state_dir):
    """Return the set of allowlisted slugs, or None if the file is missing/unreadable.

    The allowlist is a SAFETY BOUNDARY: callers must treat both ``None`` (missing
    file) and ``set()`` (present but comment-only) as DENY-ALL. Only an explicit
    non-empty slug set permits auto-promotion. Do NOT re-introduce a
    ``None``-means-allow-all branch (REPL-1/G-EMPTYALLOW: a missing allowlist
    previously dispatched every brief).
    """
    path = pathlib.Path(state_dir) / 'control' / 'autowork' / 'auto_promote.allowlist'
    try:
        if not path.exists():
            return None
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return None
    out: set[str] = set()
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith('#'):
            continue
        out.add(s)
    return out

def _auto_promote_brief_eligible(state_dir, slug, brief_mtime, now=None, max_age_sec=None) -> bool:
    if max_age_sec is None:
        max_age_sec = DEFAULT_BRIEF_MAX_AGE_SEC
    if now is None:
        now = time.time()
    try:
        mtime = float(brief_mtime or 0)
    except (TypeError, ValueError):
        mtime = 0.0
    if mtime <= 0:
        return False
    allow = _auto_promote_allowlist(state_dir)
    if slug not in (allow or set()):
        return False
    if now - mtime > float(max_age_sec):
        _emit_telemetry(pathlib.Path(state_dir), '', 'brief_too_old', f'{slug} age={now - mtime:.0f}s max={max_age_sec}')
        return False
    return True
"harness/autowork_daemon.py -- polling daemon for orchestrator_worker subprocesses (AW4a).\n\nR-PROMOTE-6: _iteration bubbles {extracts, plan_kickoffs} into its result dict\nso run_daemon's is_idle excludes iterations that just kicked off a plan\n(whose tasks need extracting on the next iteration). Without this, a fresh\nplan_kickoff iteration is classified idle and the daemon sleeps for\nheartbeat (1800s), leaving the new plan's tasks unstaged.\n"
"Submission for escalating_backoff_recently_failed_to_plan.\n\nThree coordinated edits to harness/autowork_daemon.py:\n  1. _plan_attempt_marker_path: suffix .failed -> .json\n  2. _recently_failed_to_plan: read JSON marker, apply tiered backoff\n     (300s / 3600s / 86400s based on 'attempts' count); drop ttl_sec param\n  3. _auto_promote: rewrite the hallucination marker-write block to\n     read-modify-write JSON, bumping 'attempts' on each failure\n"
_dispatch_timestamps: dict[str, list[float]] = {}
_daemon_start_time: float = 0.0

def _escalate_inactivity(state_dir: pathlib.Path, config: dict) -> None:
    import json
    import os
    import pathlib
    import subprocess
    import sys
    import time
    import uuid
    state_dir = pathlib.Path(state_dir)
    task_id = 'daemon_inactivity_stuck'
    _allowlist_path = state_dir / 'control' / 'autowork' / 'auto_promote.allowlist'
    _has_allowlisted = False
    try:
        if _allowlist_path.exists():
            for _ln in _allowlist_path.read_text(encoding='utf-8').splitlines():
                _s = _ln.strip()
                if _s and not _s.startswith('#'):
                    _has_allowlisted = True
                    break
    except Exception:
        _has_allowlisted = False
    _has_queued = False
    try:
        _has_queued = any((state_dir / 'tasks').glob('*.json'))
    except Exception:
        _has_queued = False
    _has_live_blocked = False
    try:
        for _bp in (state_dir / 'tasks' / 'blocked').glob('*.json'):
            if not _bp.with_suffix('.exhausted').exists():
                _has_live_blocked = True
                break
    except Exception:
        _has_live_blocked = False
    if not (_has_allowlisted or _has_queued or _has_live_blocked):
        _emit_telemetry(state_dir, task_id, 'skip_degenerate_escalation', 'no_actionable_work')
        return
    config_path = pathlib.Path('harness/config.yaml')
    if not config_path.is_file():
        config_path = state_dir.parent / 'harness' / 'config.yaml'
    if not isinstance(config, dict):
        config = {}
    # RUNAWAY_CEILING (PERSISTED): daemon-level GLOBAL cascade ceiling for
    # self-heal escalations, now PERSISTED to disk in
    # state/control/autowork/runaway_ceiling.json ({"count": int}) so the budget
    # survives daemon restarts and repeated --once invocations (the in-memory
    # _SELFHEAL_ESCALATION_COUNT resets to 0 each fresh process, which would
    # otherwise let a crash-loop re-arm the budget indefinitely). The
    # no_actionable_work degenerate-skip above already returned and so never
    # reaches this budget. The check sits AFTER that return and AFTER config is
    # available.
    # RESET POLICY: operator-cleared only -- delete runaway_ceiling.json to reset
    # the counter; there is no automatic reset.
    ceiling = _autowork_section(config).get('max_total_selfheal_escalations', 50)
    if not isinstance(ceiling, int):
        ceiling = 50
    tripped, count = _runaway_counter_bump(state_dir, ceiling)
    global _SELFHEAL_ESCALATION_COUNT
    if tripped:
        # Keep the backward-compatible in-memory global in sync with the
        # persisted count when the ceiling trips.
        _SELFHEAL_ESCALATION_COUNT = count
        _emit_telemetry(state_dir, task_id, 'runaway_ceiling_tripped', f'dropped escalation, count={count}/{ceiling}')
        return
    # count is the PRE-bump count; the persisted file now holds count + 1.
    _SELFHEAL_ESCALATION_COUNT = count + 1
    control = config.get('control', {})
    agent = control.get('autobrief_default_agent', 'claude') if isinstance(control, dict) else 'claude'
    if not agent:
        agent = 'claude'
    agents = config.get('agents', {})
    agent_cfg = agents.get(agent, {}) if isinstance(agents, dict) else {}
    if not agent_cfg:
        # M9 (folded into CONTAIN C7): the bare 'agy'/'claude' fallback is an
        # uncontrolled binary off PATH (possibly un-sandboxed / not the vendored
        # build). Use the VENDORED agents under ${PROJECT_ROOT}/.agents/... (resolved
        # by subst()), mirroring config.yaml's agents.* incl. the C4 --tools allowlist
        # for claude. M9 alone is necessary but NOT sufficient -- the C7 jail below
        # is what closes the containment gap.
        if agent == 'gemini':
            agent_cfg = {'command': '${PROJECT_ROOT}/.agents/agy/agy', 'args': ['-p', '--sandbox']}
        else:
            # J2: --verbose is REQUIRED for `--output-format stream-json` under -p in the
            # vendored claude-code (else it aborts "stream-json requires --verbose" before
            # submitting -- the same claude-jail-fix failure-class). The config-derived
            # path (config.yaml agents.claude.args) already carries it; this M9 vendored
            # fallback (used when config['agents']['claude'] is absent) must carry it too.
            agent_cfg = {'command': '${PROJECT_ROOT}/.agents/claude-code/node_modules/.bin/claude', 'args': ['-p', '--model', 'opus', '--output-format', 'stream-json', '--include-partial-messages', '--verbose', '--settings', '${CONFIG_DIR}/claude_worker.json', '--mcp-config', '${CONFIG_DIR}/claude_mcp.json', '--strict-mcp-config', '--setting-sources', '', '--tools', 'Read,Glob,Grep,Write', '--disallowedTools', 'Bash,Edit,Task,NotebookEdit,WebFetch,WebSearch,Skill,ToolSearch']}
    command_tmpl = agent_cfg.get('command', 'claude')
    args_tmpl = agent_cfg.get('args', [])
    from harness.paths import PROJECT_ROOT_STR, CONFIG_DIR_STR, HARNESS_DIR_STR, agent_work_dir

    def subst(s: str) -> str:
        if not isinstance(s, str):
            return s
        s = s.replace('${PROJECT_ROOT}', PROJECT_ROOT_STR)
        s = s.replace('${STATE_DIR}', str(state_dir))
        s = s.replace('${CONFIG_DIR}', CONFIG_DIR_STR)
        s = s.replace('${HARNESS_DIR}', HARNESS_DIR_STR)
        return s
    command = subst(command_tmpl)
    args = [subst(arg) for arg in args_tmpl]
    rewire = {str(pathlib.Path(CONFIG_DIR_STR) / 'claude_worker.json'): str(pathlib.Path(CONFIG_DIR_STR) / 'claude_worker_planning_hooks.json'), str(pathlib.Path(CONFIG_DIR_STR) / 'gemini_worker_policy.toml'): str(pathlib.Path(CONFIG_DIR_STR) / 'gemini_worker_policy_planning.toml')}
    args = [rewire.get(a, a) for a in args]
    if agent == 'claude' and '--permission-mode' not in args:
        args = args + ['--permission-mode', 'acceptEdits']
    # AGENT-ISOLATION §3.8.3: outbox-only diagnosis; no live-repo writes, no git.
    prompt = f'The autowork daemon is stuck with unfinished allowlisted work and no agent activity for 20 minutes.\nSynthetic Task: {task_id}\n\nWrite a self-healing diagnosis identifying why the daemon is stuck to your OUTBOX at {{OUTBOX_PATH}}/diagnosis.md. Do NOT write anywhere outside your outbox, do NOT run git, and do NOT edit the auto-promote allowlist or any file in the live repository — surface recommended fixes in your outbox for operator review.'
    # SEC_ENV_ALLOWLIST: copy ONLY allowlisted host env into the jailed self-heal
    # agent (IDENTICAL allowlist to orchestrator._build_agent_env), scrubbing
    # operator secrets (GITHUB_TOKEN, AWS_*, etc). JANUSMASK_* overlays follow.
    _ENV_ALLOW_EXACT = frozenset(('PATH', 'HOME', 'LANG', 'LANGUAGE', 'LC_ALL', 'TERM', 'SHELL', 'USER', 'LOGNAME', 'TZ', 'TMPDIR', 'PWD', 'DBUS_SESSION_BUS_ADDRESS', 'GOOGLE_GENAI_USE_GCA', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'NODE_EXTRA_CA_CERTS', 'CURL_CA_BUNDLE', 'NO_PROXY', 'no_proxy', 'HTTP_PROXY', 'http_proxy', 'HTTPS_PROXY', 'https_proxy'))
    _ENV_ALLOW_PREFIXES = ('JANUSMASK_', 'XDG_', 'NVM_', 'NODE_', 'GEMINI_', 'GOOGLE_', 'ANTHROPIC_', 'CLAUDE_', 'LC_')
    env = {k: v for k, v in os.environ.items() if k in _ENV_ALLOW_EXACT or any((k.startswith(p) for p in _ENV_ALLOW_PREFIXES))}
    env['JANUSMASK_MODE'] = 'planning'
    env['JANUSMASK_TASK_ID'] = task_id
    env['JANUSMASK_STATE_DIR'] = str(state_dir)
    session_slug = f'{agent}-r1-{task_id}-{uuid.uuid4().hex[:8]}'
    # AGENT-ISOLATION §3.8: relocate the daemon self-heal workdir OUTSIDE the
    # repo via the shared helper (agree with the orchestrator + _env fallback).
    work_dir = agent_work_dir(agent, session_slug)
    env['JANUSMASK_WORK_DIR'] = str(work_dir)
    outbox_path = work_dir / 'outbox'
    outbox_path.mkdir(parents=True, exist_ok=True)
    inbox_dir = work_dir / 'inbox'
    inbox_dir.mkdir(parents=True, exist_ok=True)
    brief_data = {'task_id': task_id, 'objective': 'Diagnose and resolve autowork daemon inactivity/stuck state', 'files_touched': []}
    try:
        with open(inbox_dir / 'brief.json', 'w', encoding='utf-8') as f:
            json.dump(brief_data, f)
    except OSError:
        pass
    resolved_prompt = prompt.replace('{STATE_DIR}', str(state_dir)).replace('{OUTBOX_PATH}', str(outbox_path))
    try:
        p_index = args.index('-p')
        cmd = [command] + args[:p_index + 1] + [resolved_prompt] + args[p_index + 1:]
    except ValueError:
        cmd = [command] + args + ['-p', resolved_prompt]
    history_dir = state_dir / 'control' / 'autowork'
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / 'self_healing_history.jsonl'
    record = {'ts': time.time(), 'task_id': task_id, 'files_touched': [], 'outcome': 'inactivity', 'spec_objective': 'Diagnose and resolve autowork daemon inactivity/stuck state'}
    line = json.dumps(record, sort_keys=True) + '\n'
    try:
        import fcntl
        with open(history_path, 'a', encoding='utf-8') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(line)
                f.flush()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception as err1:
        try:
            with open(history_path, 'a', encoding='utf-8') as f:
                f.write(line)
        except Exception as err2:
            _ = err2
    # CONTAIN C7: decouple CLAUDE_PROJECT_DIR + jail this self-heal spawn (was a
    # direct Popen that bypassed all of CONTAIN -- plan rev3.1 §1a).
    cmd = _contain_selfheal(cmd, env, work_dir, state_dir, config, agent)
    try:
        proc = subprocess.Popen(cmd, env=env, cwd=str(work_dir))  # AGENT-ISOLATION §3.8: cwd = isolated outside-repo workdir
        # SELFHEAL PIDFILE: track this inactivity self-heal spawn under a stem
        # distinct from worker-task ids (prefixed 'selfheal_' + agent + task_id)
        # so the existing _reap_running / _drain_running machinery reaps it and
        # it never leaks. Reuses _write_pidfile / _running_dir as-is.
        _write_pidfile(state_dir, f'selfheal_{agent}_{task_id}_{proc.pid}', proc.pid)
    except Exception as exc:
        _emit_telemetry(state_dir, task_id, 'spawn_failed', repr(exc))

def _check_inactivity_watchdog(repo_root: pathlib.Path, state_dir: pathlib.Path, config: dict) -> None:
    repo_root = pathlib.Path(repo_root)
    state_dir = pathlib.Path(state_dir)
    has_unfinished = False
    try:
        from harness.brief_status import compute_autowork_backlog
        backlog = compute_autowork_backlog(repo_root, state_dir)
        has_unfinished = len(backlog.get('eligible_with_work', [])) > 0
    except Exception as err:
        _ = err
    ledger_path = state_dir / 'impl_progress.jsonl'
    last_event_ts = None
    agent_level_events = {'worker_start', 'agent_status', 'phase_transition', 'auto_commit', 'task_blocked'}
    if ledger_path.exists():
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        row = json.loads(line)
                        if isinstance(row, dict):
                            event = row.get('event')
                            ts = row.get('ts')
                            if event in agent_level_events and isinstance(ts, (int, float)):
                                last_event_ts = ts
                    except Exception as err:
                        _ = err
        except OSError:
            pass
    now = time.time()
    if last_event_ts is not None:
        stuck_duration = now - last_event_ts
    else:
        stuck_duration = now - _daemon_start_time
    is_stuck = has_unfinished and stuck_duration > 1200.0
    marker_path = state_dir / 'control' / 'autowork' / 'inactivity_escalated.json'
    if is_stuck:
        if not marker_path.exists():
            try:
                marker_path.parent.mkdir(parents=True, exist_ok=True)
                marker_path.write_text(json.dumps({'ts': now}), encoding='utf-8')
            except OSError:
                pass
            _emit_telemetry(state_dir, 'daemon_inactivity_stuck', 'inactivity_watchdog_triggered', f'stuck_duration={stuck_duration:.1f}s')
            try:
                _escalate_inactivity(state_dir, config)
            except Exception as exc:
                _emit_telemetry(state_dir, 'daemon_inactivity_stuck', 'escalation_failed', repr(exc))
    elif marker_path.exists():
        try:
            marker_path.unlink()
        except OSError:
            pass
'harness/autowork_daemon.py safeguards (AUTOWORK_DAEMON_SAFEGUARDS).\n\nThree loop-spinning / inactivity safeguards for the autowork polling daemon:\n\n  1. ``collect_dispatchable_tasks`` skips spec files whose stem does not match\n     the declared ``task_id``, plus any ``current_task*`` or ``*.retry.json``.\n  2. A per-task dispatch circuit breaker (``_dispatch_timestamps``): 10 dispatches\n     within 300s quarantines the spec file and skips dispatch.\n  3. ``_check_inactivity_watchdog`` triggers a planning self-healing agent when\n     allowlisted briefs still have unfinished work but no agent-level event has\n     been recorded in impl_progress.jsonl for 20 minutes.\n\nThese definitions are AST-merged by name into the live module, so the helpers\nthey call (``_reap_running``, ``_decide``, ``_parallel_cap``, ...) resolve from\nthe target at call time.\n'

def _kill_process_group(state_dir: pathlib.Path, task_id: str, proc: subprocess.Popen) -> None:
    """SIGKILL the worker's entire process group on watchdog timeout (G-PGKILL).

    The sequential worker is spawned with ``start_new_session=True`` so it leads
    its own process group; killing the group reaps the grandchild agent CLIs
    (claude/gemini) that a bare ``proc.kill()`` would orphan. Best-effort: a
    vanished pid (ProcessLookupError) or an unsignalable group (PermissionError)
    falls back to killing just the direct child, and never raises."""
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError) as exc:
        _emit_telemetry(state_dir, task_id, 'killpg_failed', repr(exc))
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            pass
if __name__ == '__main__':
    raise SystemExit(main())
_ = transitive_deps