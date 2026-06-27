#!/usr/bin/env python3
"""Read-only autonomous-oversight monitor.

Wakes the operator (by EXITING) only when something actionable happens:
  exit 0  SUCCESS       all WATCHED briefs reached `complete`
  exit 2  STALL         no pipeline progress for STALL_SECS while watched work pending + workers idle
  exit 3  THRASH        a task is failure-looping (repeated reject/verify-fail/replan, or respawn w/o commit)
  exit 4  DEADLOCK      a LIVE running-pidfile with empty files_touched + non-selfheal slug blocks ALL dispatch
  exit 5  HEARTBEAT     MAX_SECS elapsed with nothing actionable (calm check-in)
  exit 6  DAEMON_DEAD   supervised daemon pid gone past respawn window

It NEVER mutates state.  Each iteration writes _autowork_scratch/oversight_snapshot.json
so the operator can inspect current state out-of-band.  Captures the first moment
true concurrency (>=2 live workers) occurs, with the task_ids/pids/output-sidecars
present then — the evidence that parallelism runs AND saves output without clobber.
"""
import json, os, sys, time, pathlib, collections

REPO = pathlib.Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
STATE = REPO / "state"
LEDGER = STATE / "impl_progress.jsonl"
RUNNING = STATE / "control" / "autowork" / "running"
DAEMON_PID = STATE / "control" / "autowork.pid"
TASKS = STATE / "tasks"
OUTPUT = STATE / "output"
SNAP = REPO / "_autowork_scratch" / "oversight_snapshot.json"

# env-overridable so one monitor can watch different phases (planner-outbox fix, then build_evidence).
# MON_SLUGS / MON_TASKS = comma-separated; defaults preserve the P1.1 build_evidence watch.
WATCHED_SLUGS = {s for s in os.environ.get(
    "MON_SLUGS", "p11_build_evidence_perphase").split(",") if s}
WATCHED_TASKS = {s for s in os.environ.get(
    "MON_TASKS",
    "p11-build-evidence-oracle-perphase,p11-build-evidence-perphase-impl").split(",") if s}

MAX_SECS     = int(os.environ.get("MON_MAX_SECS", "1500"))
POLL         = int(os.environ.get("MON_POLL", "15"))
STALL_SECS   = int(os.environ.get("MON_STALL_SECS", "480"))
THRASH_N     = int(os.environ.get("MON_THRASH_N", "4"))
DEADLOCK_SECS= int(os.environ.get("MON_DEADLOCK_SECS", "420"))

FAIL_EVENTS = {
    "verification_failed", "reject_rollback", "ast_validation_failed",
    "task_blocked", "retry_exhausted", "retry_budget_exhausted",
    "brief_dep_unresolvable", "dependency_failed", "mutation_gate_error",
    "multi_file_missing_sidecar", "runaway_ceiling_tripped",
    "auto_commit_patch_failed", "watchdog_kill", "orphan_unwired",
    "planner_validation_rejected", "auto_commit_failed",
}
ACCEPT_EVENTS = {"auto_commit"}            # accepted/committed
PROGRESS_INACTIVITY_OK = {"inactivity_watchdog_triggered"}  # a watchdog firing is NOT progress

def classify_success(st, watched_slugs, watched_tasks, observed_accept_tids, watched_terminal):
    """Decide whether the watched work has GENUINELY completed (verdict, code).

    Returns ("SUCCESS", 0) only when ALL of:
      (a) watched_slugs is NON-EMPTY (an empty watch set must NEVER vacuously
          succeed — `set() <= anything` is True and `all(... for s in set())`
          is vacuously True, the original false-positive root cause);
      (b) every watched slug is present in `st` AND == "complete";
      (c) POSITIVE terminal evidence exists: at least one watched task was
          observed reaching auto_commit (acceptance). Absence-of-failure or a
          bare brief-status roll-up is NOT success — a parked/never-built slug
          (state=unplanned/blocked/queued) or a "complete" roll-up with zero
          observed accepts does not qualify.

    Otherwise returns (None, None) and the caller keeps polling (eventually
    STALL/HEARTBEAT fire instead — never a spurious 0).

    `watched_terminal` is True when at least one watched task has been seen
    accepted (auto_commit) in the ledger this run; `observed_accept_tids` is the
    set of task_ids observed accepted (used when watched_tasks is unset so we can
    still demand >=1 real acceptance among the watched slugs' tasks). Either
    signal counts as positive terminal evidence.
    """
    if not watched_slugs:
        return (None, None)            # (a) no vacuous success on an empty watch
    if not (watched_slugs <= set(st) and all(st.get(s) == "complete" for s in watched_slugs)):
        return (None, None)            # (b) not all watched slugs complete
    # (c) require positive terminal evidence, not merely a roll-up.
    if watched_terminal:
        return ("SUCCESS", 0)
    if watched_tasks and (set(watched_tasks) & set(observed_accept_tids)):
        return ("SUCCESS", 0)
    return (None, None)


def _alive(pid:int)->bool:
    if pid <= 0: return False          # os.kill(0/-1,..) signals a GROUP — never a liveness probe
    try: os.kill(pid, 0); return True
    except (ProcessLookupError, ValueError): return False
    except PermissionError: return True

def _daemon_alive():
    try: return _alive(int(DAEMON_PID.read_text().strip()))
    except Exception: return False

def _brief_states():
    try:
        from harness.brief_status import compute_brief_status
        rows = compute_brief_status(REPO, STATE)
        return {r["slug"]: r["state"] for r in rows if r["slug"] in WATCHED_SLUGS}
    except Exception as e:
        return {"_error": str(e)}

def _accepted_watched_tasks():
    """Durable positive terminal evidence: WATCHED task_ids that reached
    auto_commit (acceptance) in the ledger and were NOT later rejected/blocked.

    Mirrors compute_brief_status's accept/reject bookkeeping so a brief that
    truly completed BEFORE the monitor attached (commit_count==0 this run) still
    qualifies as a real success — without trusting a bare roll-up that has no
    acceptance behind it. Scans the whole ledger (small, append-only)."""
    if not WATCHED_TASKS:
        return set()
    accepted = set()
    try:
        with LEDGER.open() as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try: row = json.loads(line)
                except Exception: continue
                tid = row.get("task_id")
                if tid not in WATCHED_TASKS: continue
                if row.get("phase") == "accepted" and row.get("event") == "auto_commit":
                    accepted.add(tid)
                elif row.get("event") in ("reject_rollback", "task_blocked"):
                    accepted.discard(tid)
    except FileNotFoundError:
        pass
    return accepted

def _running_live():
    """Return list of (task_id, pid, age_secs, files_touched, is_selfheal) for LIVE running pidfiles."""
    out = []
    if not RUNNING.is_dir(): return out
    now = time.time()
    for pf in RUNNING.iterdir():
        if not pf.is_file() or pf.suffix != ".pid": continue   # ONLY worker pidfiles; skip .slot sidecars
        try: pid = int(pf.read_text().strip().split()[0])
        except Exception: continue
        if not _alive(pid): continue
        tid = pf.stem
        ft = None
        try:
            tj = json.loads((TASKS / f"{tid}.json").read_text())
            ft = tj.get("files_touched")
        except Exception: pass
        out.append({
            "task_id": tid, "pid": pid,
            "age": round(now - pf.stat().st_mtime, 1),
            "files_touched": ft,
            "selfheal": tid.startswith("selfheal_"),
        })
    return out

def _sidecars():
    if not OUTPUT.is_dir(): return []
    return sorted(p.name for p in OUTPUT.iterdir()
                  if p.suffix in (".json",) and (".patches." in p.name or ".files." in p.name))

def _planner_live(watched_slugs):
    """Return [{pid, slug}] for live planner.cli processes drafting a WATCHED brief.

    BLIND SPOT FIX: a planner run is NEITHER a worker pidfile (state/control/.../running)
    NOR a ledger-row emitter during the blind-draft phase — it just blocks ~minutes waiting
    on its claude/gemini draft children. Without detecting it, a long-but-live planner reads
    as `total_silent` STALL (false positive, observed 2026-06-21: 21-min live draft → false
    STALL@480s). The planner cmdline embeds the brief path `brief_hooks_<slug>.md`, so a
    substring match on the slug identifies an in-flight plan for watched work."""
    out = []
    proc = pathlib.Path("/proc")
    try:
        for p in proc.iterdir():
            if not p.name.isdigit(): continue
            try:
                cmd = (p / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace")
            except Exception:
                continue
            if "planner.cli" not in cmd: continue
            for s in watched_slugs:
                if s and s in cmd:
                    out.append({"pid": int(p.name), "slug": s}); break
    except Exception:
        pass
    return out

def main():
    start = time.monotonic()
    last_progress = start
    last_watched_progress = start   # starvation guard: last time WATCHED work advanced
    prev_states = {}
    fail_counts = collections.Counter()    # task_blocked per task == one per REAL failed attempt
    exhausted   = collections.Counter()    # retry_exhausted per task (terminal give-up)
    start_count = collections.Counter()   # worker_start per task
    commit_count = collections.Counter()
    max_conc = 0
    parallel_evidence = None
    offset = LEDGER.stat().st_size if LEDGER.exists() else 0  # only NEW rows

    def emit(verdict, code, extra=None, final=True):
        snap = {
            "verdict": verdict, "exit": code,
            "elapsed": round(time.monotonic() - start, 1),
            "watched_states": _brief_states(),
            "running_live": _running_live(),
            "planner_live": _planner_live(WATCHED_SLUGS),
            "max_concurrency": max_conc,
            "parallel_evidence": parallel_evidence,
            "fail_counts": dict(fail_counts.most_common(12)),
            "worker_starts": dict(start_count),
            "commits": dict(commit_count),
            "daemon_alive": _daemon_alive(),
            "sidecars_now": _sidecars(),
        }
        if extra: snap.update(extra)
        try: SNAP.write_text(json.dumps(snap, indent=2))
        except Exception: pass
        if final:
            print(json.dumps(snap)); sys.stdout.flush()

    daemon_dead_since = None
    while True:
        now = time.monotonic()
        # --- ingest new ledger rows ---
        new_rows = 0
        try:
            with LEDGER.open() as f:
                f.seek(offset); chunk = f.read(); offset = f.tell()
            for line in chunk.splitlines():
                line = line.strip()
                if not line: continue
                new_rows += 1
                try: row = json.loads(line)
                except Exception: continue
                ev = row.get("event"); tid = row.get("task_id")
                if ev in PROGRESS_INACTIVITY_OK:
                    new_rows -= 1  # watchdog firing is not real progress
                if ev == "task_blocked" and tid: fail_counts[tid] += 1   # one per REAL failed attempt
                if ev == "retry_exhausted" and tid: exhausted[tid] += 1  # terminal give-up
                if ev == "worker_start" and tid: start_count[tid] += 1
                if ev in ACCEPT_EVENTS and tid: commit_count[tid] += 1
                if tid in WATCHED_TASKS and ev not in PROGRESS_INACTIVITY_OK:
                    last_watched_progress = now
        except FileNotFoundError:
            pass
        # --- concurrency ---
        live = _running_live()
        if len(live) > max_conc: max_conc = len(live)
        if len(live) >= 2 and parallel_evidence is None:
            parallel_evidence = {
                "at_elapsed": round(now - start, 1),
                "tasks": [l["task_id"] for l in live],
                "pids": [l["pid"] for l in live],
                "sidecars_present": _sidecars(),
                "distinct_sidecars": len(set(_sidecars())),
            }
        if any(l["task_id"] in WATCHED_TASKS for l in live):
            last_watched_progress = now
        # --- in-flight planner for a watched slug counts as progress (see _planner_live) ---
        planner_live = _planner_live(WATCHED_SLUGS)
        if planner_live:
            last_progress = now
            last_watched_progress = now
        if new_rows > 0 or len(live) > 0:
            last_progress = now
        # --- daemon liveness ---
        dalive = _daemon_alive()
        if not dalive:
            daemon_dead_since = daemon_dead_since or now
            if now - daemon_dead_since > 90:
                emit("DAEMON_DEAD", 6); return 6
        else:
            daemon_dead_since = None
        # --- DEADLOCK: a live non-selfheal pidfile with a GENUINELY EMPTY files_touched ([])
        #     blocks all dispatch (autowork_parallelism conservative veto). NOTE: a RUNNING task's
        #     json is moved out of state/tasks/, so files_touched reads None (unknown) for healthy
        #     in-flight workers — None must NOT trip this (that was a false-positive on slow workers).
        #     Only an explicit [] is the real signature. Genuinely-stuck workers are otherwise
        #     killed by the daemon's own inactivity_watchdog; functional blockage of WATCHED work
        #     is caught by STALL below. ---
        for l in live:
            if (not l["selfheal"]) and l["age"] > DEADLOCK_SECS and l["files_touched"] == []:
                emit("DEADLOCK", 4, {"deadlock_task": l["task_id"], "deadlock_pid": l["pid"], "age": l["age"]}); return 4
        # --- THRASH: a WATCHED task exhausted its retry budget (terminal), OR any task was
        #     task_blocked >= THRASH_N times (one count per REAL attempt, not per fail-row), OR a
        #     watched task started >=3x with no commit. ---
        thrash_tid = None
        for tid in WATCHED_TASKS:
            if exhausted[tid] >= 1: thrash_tid = f"{tid}:retry_exhausted"; break
        if not thrash_tid:
            for tid, n in fail_counts.items():
                if n >= THRASH_N: thrash_tid = f"{tid}:{n}_blocked_attempts"; break
        if not thrash_tid:
            for tid in WATCHED_TASKS:
                if start_count[tid] >= 3 and commit_count[tid] == 0:
                    thrash_tid = f"{tid}:{start_count[tid]}_starts_0_commits"; break
        if thrash_tid:
            emit("THRASH", 3, {"thrash": thrash_tid}); return 3
        # --- SUCCESS ---
        st = _brief_states()
        for s in WATCHED_SLUGS:                          # state change == watched progress
            if st.get(s) and prev_states.get(s) != st.get(s):
                last_watched_progress = now
        prev_states = dict(st)
        # Positive terminal evidence: a WATCHED task reached auto_commit either
        # this run (commit_count, live) OR durably in the ledger (a brief that
        # completed before the monitor attached). Absence of either => no SUCCESS.
        accepted_tids = {t for t, n in commit_count.items() if n > 0} | _accepted_watched_tasks()
        watched_terminal = bool(set(WATCHED_TASKS) & accepted_tids)
        sverdict, scode = classify_success(
            st, WATCHED_SLUGS, WATCHED_TASKS, accepted_tids, watched_terminal)
        if sverdict is not None:
            emit(sverdict, scode); return scode
        # --- STALL: either the WHOLE system went silent (no ledger rows AND no live workers)
        #     for STALL_SECS, OR watched work specifically starved for 1.5*STALL_SECS while other
        #     work monopolizes. Planning a watched brief emits plan_kickoff/extract rows -> last_progress
        #     stays fresh -> a long but live planner run does NOT trip a false STALL. ---
        pending = any(st.get(s) != "complete" for s in WATCHED_SLUGS) or "_error" in st
        total_silent    = (now - last_progress) > STALL_SECS
        watched_starved = (now - last_watched_progress) > STALL_SECS * 1.5
        if pending and dalive and (total_silent or watched_starved):
            emit("STALL", 2, {"reason": "total_silent" if total_silent else "watched_starved",
                              "silent_secs": round(now - last_progress, 1),
                              "watched_stall_secs": round(now - last_watched_progress, 1),
                              "running_now": [l["task_id"] for l in live]}); return 2
        # --- HEARTBEAT ---
        if now - start > MAX_SECS:
            emit("HEARTBEAT", 5); return 5
        emit("tick", -1, final=False)  # rolling snapshot only; loop continues
        time.sleep(POLL)

if __name__ == "__main__":
    sys.exit(main())
