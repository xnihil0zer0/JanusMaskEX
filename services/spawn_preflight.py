#!/usr/bin/env python3
"""Spawn Preflight Checker — prevents cascade failures, duplicates, and resource exhaustion."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "worker_registry.db"
SPAWN_CONTROLS = ROOT / "data" / "spawn_controls.json"
COOLDOWN_STATE = ROOT / "data" / "spawn_cooldown_state.json"

CASCADE_WINDOW_SECONDS = 600
CASCADE_FAILURE_THRESHOLD = 0.50
CASCADE_MIN_SAMPLE = 4
CASCADE_COOLDOWN_BASE_S = 30
CASCADE_COOLDOWN_MAX_S = 300

MEMORY_MIN_AVAILABLE_MB = 2048

MAX_CONCURRENT_WORKERS = 8

DEDUP_RUNNING_BLOCK = True
DEDUP_COMPLETED_WINDOW_S = 300

COOLDOWN_BASE_S = 15
COOLDOWN_MAX_S = 180
COOLDOWN_DECAY_S = 600

LOG = logging.getLogger("spawn_preflight")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [spawn_preflight] %(levelname)s %(message)s",
    stream=sys.stderr,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS workers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_type TEXT    NOT NULL,
    pid         INTEGER NOT NULL,
    start_time  TEXT    NOT NULL,
    last_seen   TEXT    NOT NULL,
    worktree_path TEXT  DEFAULT NULL,
    status      TEXT    NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running','completed','failed','crashed','suspended','resumed','expired')),
    exit_code   INTEGER DEFAULT NULL,
    prompt_hash TEXT    DEFAULT NULL,
    model       TEXT    DEFAULT NULL,
    session_id  TEXT    DEFAULT NULL,
    token_usage INTEGER DEFAULT 0,
    prompt_text TEXT    DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS worker_intents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id   INTEGER NOT NULL REFERENCES workers(id),
    intent_type TEXT    NOT NULL,
    target      TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workers_status ON workers(status);
CREATE INDEX IF NOT EXISTS idx_wi_worker ON worker_intents(worker_id);
CREATE INDEX IF NOT EXISTS idx_wi_target ON worker_intents(intent_type, target);
"""

@dataclass
class CheckResult:
    check: str
    passed: bool
    reason: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

@dataclass
class PreflightResult:
    verdict: str
    checks: List[CheckResult] = field(default_factory=list)
    blocked_by: str = ""
    reason: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "blocked_by": self.blocked_by,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "checks": [asdict(c) for c in self.checks],
        }

def _get_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH))
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn

def _recent_workers(conn: sqlite3.Connection, window_s: int) -> List[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=window_s)).isoformat()
    rows = conn.execute(
        """SELECT id, worker_type, status, exit_code, start_time, last_seen
           FROM workers
           WHERE last_seen >= ? OR start_time >= ?
           ORDER BY id DESC""",
        (cutoff, cutoff),
    ).fetchall()
    return [dict(r) for r in rows]

def _active_workers(conn: sqlite3.Connection) -> List[dict]:
    rows = conn.execute(
        "SELECT id, worker_type, pid, start_time FROM workers WHERE status = 'running'"
    ).fetchall()
    return [dict(r) for r in rows]

def _worker_intents(conn: sqlite3.Connection, target: str) -> List[dict]:
    rows = conn.execute(
        """SELECT wi.id, wi.worker_id, wi.intent_type, wi.target, wi.created_at,
                  w.status as worker_status
           FROM worker_intents wi
           JOIN workers w ON wi.worker_id = w.id
           WHERE wi.target = ?
           ORDER BY wi.created_at DESC""",
        (target,),
    ).fetchall()
    return [dict(r) for r in rows]

def _load_cooldown_state() -> dict:
    if COOLDOWN_STATE.exists():
        try:
            with open(COOLDOWN_STATE) as f:
                return json.load(f)
        except Exception as exc:
            LOG.warning("Failed to load cooldown state: %s", exc)
    return {}

def _save_cooldown_state(state: dict) -> None:
    COOLDOWN_STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = COOLDOWN_STATE.with_suffix(".tmp")
    try:
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        tmp.rename(COOLDOWN_STATE)
    except Exception as exc:
        LOG.error("Failed to save cooldown state: %s", exc)

def record_failure(worker_type: str) -> None:
    state = _load_cooldown_state()
    entry = state.get(worker_type, {"streak": 0, "last_failure": 0})
    entry["streak"] = entry.get("streak", 0) + 1
    entry["last_failure"] = time.time()
    state[worker_type] = entry
    _save_cooldown_state(state)
    LOG.info("Recorded failure for %s: streak=%d", worker_type, entry["streak"])

def record_success(worker_type: str) -> None:
    state = _load_cooldown_state()
    if worker_type in state:
        state[worker_type] = {"streak": 0, "last_failure": state[worker_type].get("last_failure", 0)}
        _save_cooldown_state(state)

def _get_cooldown_seconds(worker_type: str) -> float:
    state = _load_cooldown_state()
    entry = state.get(worker_type, {})
    if isinstance(entry, int):
        entry = {"streak": entry, "last_failure": 0}
    streak = entry.get("streak", 0)
    last_failure = entry.get("last_failure", 0)

    if streak == 0:
        return 0.0

    elapsed = time.time() - last_failure
    if elapsed > COOLDOWN_DECAY_S:
        state[worker_type] = {"streak": 0, "last_failure": last_failure}
        _save_cooldown_state(state)
        return 0.0

    cooldown = min(COOLDOWN_BASE_S * (2 ** (streak - 1)), COOLDOWN_MAX_S)
    remaining = cooldown - elapsed
    return max(0.0, remaining)

def check_cascade(conn: sqlite3.Connection) -> CheckResult:
    recent = _recent_workers(conn, CASCADE_WINDOW_SECONDS)
    if len(recent) < CASCADE_MIN_SAMPLE:
        return CheckResult(
            check="cascade",
            passed=True,
            reason=f"Too few recent workers ({len(recent)}) to assess cascade",
            data={"recent_count": len(recent), "min_sample": CASCADE_MIN_SAMPLE},
        )

    terminal = [w for w in recent if w["status"] in ("completed", "failed", "crashed")]
    terminal = [w for w in terminal if not (w["status"] == "completed" and w.get("exit_code") == 3)]
    if not terminal:
        return CheckResult(
            check="cascade",
            passed=True,
            reason="No terminal workers in window — cannot assess",
            data={"running_count": len(recent)},
        )

    failed = [w for w in terminal if w["status"] in ("failed", "crashed")]
    failure_rate = len(failed) / len(terminal)

    if failure_rate > CASCADE_FAILURE_THRESHOLD:
        cascade_level = min(int((failure_rate - CASCADE_FAILURE_THRESHOLD) * 10) + 1, 5)
        cooldown = min(CASCADE_COOLDOWN_BASE_S * cascade_level, CASCADE_COOLDOWN_MAX_S)
        return CheckResult(
            check="cascade",
            passed=False,
            reason=f"Cascade detected: {len(failed)}/{len(terminal)} failed ({failure_rate:.0%}). Cooldown: {cooldown}s",
            data={
                "failure_rate": round(failure_rate, 3),
                "failed_count": len(failed),
                "terminal_count": len(terminal),
                "cascade_level": cascade_level,
                "cooldown_seconds": cooldown,
            },
        )

    return CheckResult(
        check="cascade",
        passed=True,
        reason=f"Failure rate {failure_rate:.0%} ({len(failed)}/{len(terminal)}) — below threshold",
        data={"failure_rate": round(failure_rate, 3), "failed_count": len(failed), "terminal_count": len(terminal)},
    )

def check_memory() -> CheckResult:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    available_kb = int(line.split()[1])
                    available_mb = available_kb // 1024
                    if available_mb < MEMORY_MIN_AVAILABLE_MB:
                        return CheckResult(
                            check="memory",
                            passed=False,
                            reason=f"Low memory: {available_mb} MB available (need >= {MEMORY_MIN_AVAILABLE_MB} MB)",
                            data={"available_mb": available_mb, "threshold_mb": MEMORY_MIN_AVAILABLE_MB},
                        )
                    return CheckResult(
                        check="memory",
                        passed=True,
                        reason=f"{available_mb} MB available",
                        data={"available_mb": available_mb},
                    )
        return CheckResult(check="memory", passed=True, reason="Could not parse /proc/meminfo — allowing")
    except Exception as exc:
        LOG.warning("Memory check failed: %s", exc)
        return CheckResult(check="memory", passed=True, reason=f"Memory check unavailable: {exc}")

def check_capacity(conn: sqlite3.Connection) -> CheckResult:
    active = _active_workers(conn)
    active = [w for w in active if w.get("worker_type") != "overseer"]
    active_count = len(active)

    self_id = os.environ.get("NOBLEJANUS_WORKER_ID") or os.environ.get("NOBLEGREED_WORKER_ID")
    if self_id:
        try:
            self_id_int = int(self_id)
            if any(w.get("id") == self_id_int for w in active):
                active_count -= 1
        except Exception as exc:
            LOG.warning("capacity: could not parse worker ID=%r: %s", self_id, exc)

    max_workers = MAX_CONCURRENT_WORKERS
    try:
        if SPAWN_CONTROLS.exists():
            with open(SPAWN_CONTROLS) as f:
                controls = json.load(f)
                max_workers = controls.get("max_workers", MAX_CONCURRENT_WORKERS)
    except Exception as exc:
        LOG.warning("Could not read spawn_controls.json: %s", exc)

    if active_count >= max_workers:
        types = {}
        for w in active:
            t = w.get("worker_type", "unknown")
            types[t] = types.get(t, 0) + 1
        return CheckResult(
            check="capacity",
            passed=False,
            reason=f"At capacity: {active_count}/{max_workers} workers running ({types})",
            data={"active": active_count, "max": max_workers, "by_type": types},
        )

    return CheckResult(
        check="capacity",
        passed=True,
        reason=f"{active_count}/{max_workers} workers — capacity available",
        data={"active": active_count, "max": max_workers, "available": max_workers - active_count},
    )

def check_dedup(conn: sqlite3.Connection, task_target: Optional[str]) -> CheckResult:
    if not task_target:
        return CheckResult(check="dedup", passed=True, reason="No task target specified — skipping dedup")

    intents = _worker_intents(conn, task_target)
    if not intents:
        return CheckResult(check="dedup", passed=True, reason=f"No existing intents for target '{task_target}'")

    running = [i for i in intents if i.get("worker_status") == "running"]
    if running and DEDUP_RUNNING_BLOCK:
        return CheckResult(
            check="dedup",
            passed=False,
            reason=f"Duplicate: target '{task_target}' already worked on by {[i['worker_id'] for i in running]}",
            data={"running_workers": [i["worker_id"] for i in running], "target": task_target},
        )

    now = time.time()
    for intent in intents:
        if intent.get("worker_status") == "completed":
            try:
                created = datetime.fromisoformat(intent["created_at"].replace("Z", "+00:00"))
                age_s = (datetime.now(timezone.utc) - created).total_seconds()
                if age_s < DEDUP_COMPLETED_WINDOW_S:
                    return CheckResult(
                        check="dedup",
                        passed=False,
                        reason=f"Recently completed: target '{task_target}' done by worker {intent['worker_id']} ({age_s:.0f}s ago)",
                        data={"completed_worker": intent["worker_id"], "completed_seconds_ago": round(age_s), "target": task_target},
                    )
            except Exception:
                continue

    return CheckResult(
        check="dedup",
        passed=True,
        reason=f"No active/recent duplicates for '{task_target}'",
        data={"target": task_target, "historical_intents": len(intents)},
    )

def check_cooldown(worker_type: str) -> CheckResult:
    if not worker_type:
        return CheckResult(check="cooldown", passed=True, reason="No worker type — skipping cooldown")

    remaining = _get_cooldown_seconds(worker_type)
    if remaining > 0:
        state = _load_cooldown_state()
        streak = state.get(worker_type, {}).get("streak", 0)
        return CheckResult(
            check="cooldown",
            passed=False,
            reason=f"Cooldown active for '{worker_type}': {remaining:.0f}s remaining (streak={streak})",
            data={"worker_type": worker_type, "remaining_seconds": round(remaining, 1), "streak": streak},
        )

    return CheckResult(
        check="cooldown",
        passed=True,
        reason=f"No cooldown for '{worker_type}'",
        data={"worker_type": worker_type},
    )

def run_preflight(worker_type: str = "", task_target: str = "", force: bool = False) -> dict:
    result = PreflightResult(
        verdict="GO",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    if force:
        result.reason = "Force flag — all checks bypassed"
        LOG.info("Preflight FORCED GO for %s/%s", worker_type, task_target)
        return result.to_dict()

    try:
        conn = _get_db()
    except Exception as exc:
        LOG.error("Cannot open worker registry: %s", exc)
        result.reason = f"Registry unavailable ({exc}) — allowing spawn"
        return result.to_dict()

    try:
        checks = [
            ("cascade", lambda: check_cascade(conn)),
            ("memory", lambda: check_memory()),
            ("capacity", lambda: check_capacity(conn)),
            ("dedup", lambda: check_dedup(conn, task_target if task_target else None)),
            ("cooldown", lambda: check_cooldown(worker_type)),
        ]

        for name, check_fn in checks:
            try:
                check = check_fn()
                result.checks.append(check)
                if not check.passed:
                    result.verdict = "BLOCKED"
                    result.blocked_by = check.check
                    result.reason = check.reason
                    break
            except Exception as exc:
                LOG.error("Check '%s' raised exception: %s", name, exc)
                result.checks.append(CheckResult(
                    check=name,
                    passed=True,
                    reason=f"Check failed with exception (allowing): {exc}",
                ))
    finally:
        conn.close()

    return result.to_dict()

def show_status() -> None:
    print("=" * 72)
    print("  SPAWN PREFLIGHT STATUS")
    print("=" * 72)
    try:
        mem = check_memory()
        print(f"  {'✅' if mem.passed else '🔴'} Memory: {mem.reason}")
        
        conn = _get_db()
        cap = check_capacity(conn)
        print(f"  {'✅' if cap.passed else '🔴'} Capacity: {cap.reason}")
        
        cas = check_cascade(conn)
        print(f"  {'✅' if cas.passed else '🔴'} Cascade: {cas.reason}")
        conn.close()
    except Exception as exc:
        print(f"  ⚠️ Registry unavailable: {exc}")

    state = _load_cooldown_state()
    if state:
        print("\n  Cooldown streaks:")
        for wtype, entry in sorted(state.items()):
            if isinstance(entry, int):
                entry = {"streak": entry, "last_failure": 0}
            streak = entry.get("streak", 0)
            remaining = _get_cooldown_seconds(wtype)
            if streak > 0:
                print(f"    🔸 {wtype}: streak={streak}, remaining={remaining:.0f}s")
            else:
                print(f"    ✅ {wtype}: no active cooldown")
    else:
        print("\n  ✅ Cooldowns: none active")
    print()

def main() -> None:
    parser = argparse.ArgumentParser(description="Spawn Preflight Checker")
    parser.add_argument("--worker-type", default="", help="Worker type")
    parser.add_argument("--task-target", default="", help="Task target")
    parser.add_argument("--force", action="store_true", help="Bypass all checks")
    parser.add_argument("--status", action="store_true", help="Show preflight dashboard")
    args = parser.parse_args()

    if args.status:
        show_status()
        sys.exit(0)

    result = run_preflight(
        worker_type=args.worker_type,
        task_target=args.task_target,
        force=args.force,
    )

    print(json.dumps(result, indent=2))
    sys.exit(0 if result["verdict"] == "GO" else 1)

if __name__ == "__main__":
    main()
