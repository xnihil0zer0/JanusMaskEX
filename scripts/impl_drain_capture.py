#!/usr/bin/env python3
"""Operator helper: regenerate B3 drain baselines against a real cycle.

Bridges the CLI gap flagged in ``docs/runbooks/operator_followup.md`` §3.
``harness/orchestrator.py``'s ``main()`` only accepts
``--config/--state-dir/--log-dir`` — the B3 runbook needs ``--brief`` and
``--session`` plumbing plus post-cycle artefact capture.

Real-execution flow (two subprocesses, both spawned from this wrapper):

1. **Planner subprocess** — ``python3 -m harness.planner.cli <brief>.md
   --config <config>``. This converts the planning brief into one-or-more
   task JSON files under ``state/tasks/``. Skippable via ``--skip-planner``
   when tasks are already queued (e.g. a prior cycle failed mid-drain and
   re-running the planner would double-bill subscription).

2. **Orchestrator subprocess** — ``python3 -m harness.orchestrator
   --config <config> --state-dir <state_dir> --log-dir <log_dir>`` in its
   own session group. The wrapper polls ``state_dir/tasks/*.json`` for
   emptiness; once the pending-queue has stayed empty for ``--idle-confirm``
   consecutive seconds (default ~3× orchestrator ``POLL_INTERVAL``), the
   wrapper sends ``SIGINT`` (the only graceful-stop signal ``main()``
   catches) then falls back to ``SIGTERM`` if the process does not exit.

After the orchestrator returns, the wrapper
 - ``git diff``s HEAD-before → HEAD-after into
   ``state/drain_patches/<session>.patch``,
 - extracts the track-record events *this cycle* wrote (the canonical
   ``track_record_events.jsonl`` accumulates across cycles; we snapshot
   its line count before the cycle and copy the delta into
   ``state/drain_patches/<session>.tracks.jsonl``),
 - collects a pytest test-count via ``_collect_test_count``,
 - hands the three artefacts to
   ``capture_drain_artefacts`` → ``save_drain_baseline`` to overwrite the
   synthetic placeholder baseline under ``state/hooks/``.

Subscription-cost guardrail: a real invocation burns a real slice of the
operator's 5hr Claude rolling window and daily Gemini quota. The
``--dry-run`` flag prints the full invocation plan without spawning
either subprocess so the operator can sanity-check the shape before
committing a real cycle. Tests exercise only ``--dry-run`` and
subprocess-mocked helper paths; no test ever spawns a real planner or
orchestrator.

Usage::

    python3 scripts/impl_drain_capture.py --brief stab_001 [--session <id>] \\
        [--baseline-dir state/hooks] [--skip-planner] [--dry-run]

See ``docs/runbooks/operator_followup.md`` §3 for the surrounding runbook
and the ``__baseline_note``-absence check operators rely on to confirm a
baseline is real.
"""

from __future__ import annotations

import argparse
import datetime
import errno
import glob as _glob
import json
import os
import pathlib
import signal
import subprocess
import sys
import time
from typing import Optional

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from harness.hooks_equivalence import (  # noqa: E402
    DRAIN_BASELINE_DIR,
    DRAIN_BRIEFS,
    DrainArtefacts,
    capture_drain_artefacts,
    save_drain_baseline,
)
from harness.safe_subpath import is_safe_subpath  # noqa: E402


DEFAULT_PLANNER_TIMEOUT_S = 900
DEFAULT_ORCHESTRATOR_TIMEOUT_S = 1800
DEFAULT_POLL_STEP_S = 3.0
DEFAULT_IDLE_CONFIRM_S = 9.0
DEFAULT_SIGINT_GRACE_S = 30
DEFAULT_SIGTERM_GRACE_S = 10


def _default_session_id(brief: str, now: Optional[datetime.datetime] = None) -> str:
    """Deterministic session-id default: ``drain-<brief>-<UTC timestamp>``."""
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    return "drain-{}-{}".format(brief, now.strftime("%Y%m%dT%H%M%SZ"))


def _brief_file_path(brief: str, repo_root: pathlib.Path = _REPO_ROOT) -> pathlib.Path:
    """Brief markdown convention: ``<repo>/brief_<brief>.md``."""
    return repo_root / f"brief_{brief}.md"


def _tracks_path(state_dir: pathlib.Path) -> pathlib.Path:
    """Canonical tracks at ``<state_dir>/track_record_events.jsonl``.

    Matches ``harness/track_record_events.py::_event_log_file``.
    """
    return state_dir / "track_record_events.jsonl"


def _patch_path(state_dir: pathlib.Path, session: str) -> pathlib.Path:
    """Per-cycle patch at ``<state_dir>/drain_patches/<session>.patch``."""
    return state_dir / "drain_patches" / f"{session}.patch"


def _per_cycle_tracks_path(state_dir: pathlib.Path, session: str) -> pathlib.Path:
    """Per-cycle tracks copy — only new lines appended during this cycle.

    The canonical ``<state_dir>/track_record_events.jsonl`` accumulates
    across cycles and unrelated orchestrator runs. ``capture_drain_artefacts``
    reads the whole file with no offset, so feeding it the canonical file
    would contaminate the baseline with unrelated history. We snapshot the
    line count before the cycle, then copy the delta here.
    """
    return state_dir / "drain_patches" / f"{session}.tracks.jsonl"


def _log_dir(repo_root: pathlib.Path, session: str) -> pathlib.Path:
    """Orchestrator log dir for this cycle — ``<repo>/logs/<session>/``."""
    return repo_root / "logs" / session


def _rollback_interlock_blockers(state_dir: pathlib.Path) -> list[str]:
    """Return human-readable blocker strings; empty list means safe to proceed."""
    blockers: list[str] = []
    signal_path = state_dir / "hooks" / "rollback_signal"
    if signal_path.exists():
        blockers.append(f"rollback_signal present at {signal_path}")
    blocked_dir = state_dir / "tasks" / "blocked"
    if blocked_dir.exists():
        stale = sorted(blocked_dir.glob("ROLLBACK-*.md"))
        if stale:
            blockers.append(
                "stale ROLLBACK-*.md blocked-reports: "
                + ", ".join(str(p) for p in stale)
            )
    return blockers


def _existing_baseline_is_synthetic(
    brief: str, baseline_dir: pathlib.Path
) -> bool:
    """True iff the on-disk baseline still carries ``__baseline_note`` marker."""
    path = baseline_dir / f"drain_baseline_{brief}.json"
    if not path.exists():
        return False
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    return isinstance(obj, dict) and "__baseline_note" in obj


def _is_empty_capture(artefacts) -> bool:
    """True iff this drain cycle produced no observable work.

    A cycle is "empty" when BOTH patch_stat is empty (no files changed by
    any orchestrator auto-commit) AND track_events is empty (no track
    emissions). test_count is a repo-wide measurement that does not vary
    per cycle, so it is not part of the signal. The empty-capture
    tripwire was documented in ledger row 2026-04-19T20:30Z as
    _is_empty_capture at scripts/impl_drain_capture.py:162 but had been
    removed from the wrapper at some point, letting the 2026-04-20T05:18Z
    stab_003 drain write a 136B baseline without __baseline_note.
    Restored 2026-04-20T07:XXZ per blocker #12 addendum.
    """
    patch_empty = not (artefacts.patch_stat or "").strip()
    events_empty = len(artefacts.track_events) == 0
    return patch_empty and events_empty


def _count_lines(path: pathlib.Path) -> int:
    """Count newline-terminated lines in ``path``. 0 if missing."""
    if not path.exists():
        return 0
    try:
        with open(path, "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def _clear_stale_task_state(
    merged_plan_obj,
    state_dir: pathlib.Path,
    stderr,
) -> int:
    """Unlink stale processed entries + session submissions for tasks in the
    merged plan, so a re-replay finds them as fresh work.

    Why: orchestrator's get_next_task() filters out task_ids whose JSON exists
    in state/tasks/processed/, so cached --skip-planner shards would otherwise
    be no-ops on second invocation. Match-glob also drops session submission
    files from prior rounds to give the new orchestrator instance a clean slate.

    SECURITY: task_id values are attacker-controllable (they flow from the
    planner's merged plan JSON). This function hardens the join into
    ``processed_dir`` against path traversal (``..``, ``/``, ``\\``, NUL),
    rejects glob metacharacters (``*``, ``?``, ``[``, ``]``) that would
    otherwise over-match the sessions glob, length-caps to avoid
    ``OSError(ENAMETOOLONG)``, and uses
    ``harness.safe_subpath.is_safe_subpath`` as defence-in-depth on the
    *non-resolved* parent directory (resolving would dereference legitimate
    symlinks inside ``processed/`` — see
    ``test_processed_symlink_unlinks_link_not_target``). On any rejection
    the task is skipped (contract: return ``0`` without raising) and a
    ``SECURITY:`` line is emitted on ``stderr`` for operator observability.
    """
    if isinstance(merged_plan_obj, dict):
        tasks = merged_plan_obj.get("tasks")
    elif isinstance(merged_plan_obj, list):
        tasks = merged_plan_obj
    else:
        tasks = None
    if not isinstance(tasks, list):
        return 0

    processed_dir = state_dir / "tasks" / "processed"
    sessions_dir = state_dir / "sessions"
    # NAME_MAX is 255 on ext4/ext3/btrfs; subtract the longest suffix we
    # build (``_submission.json`` = 16 chars + a short agent prefix like
    # ``gemini_`` = 7 chars) so neither ``processed/<id>.json`` nor
    # ``sessions/<agent>_<id>_submission.json`` can exceed NAME_MAX.
    _NAME_MAX = 255
    _SUFFIX_BUDGET = len("_submission.json") + len("gemini_")
    _MAX_TASK_ID_LEN = _NAME_MAX - _SUFFIX_BUDGET  # 232 bytes/chars
    _norm_processed_root = os.path.normpath(str(processed_dir))
    unlinked = 0
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            continue
        # SECURITY: reject task_ids that would escape processed_dir via
        # path separators, traversal components, or NUL bytes. A safe
        # task_id must be a flat basename (no '/', '\\', '..', '\x00').
        if (
            "/" in task_id
            or "\\" in task_id
            or "\x00" in task_id
            or task_id in (".", "..")
            or ".." in pathlib.PurePosixPath(task_id).parts
        ):
            try:
                stderr.write(
                    "SECURITY: rejected unsafe task_id (path traversal): "
                    f"{task_id!r}\n"
                )
            except Exception:
                pass
            continue
        # SECURITY: reject task_ids that expand to glob metacharacters in
        # the sessions pattern '*_<task_id>_submission.json'. A literal
        # ``*`` / ``?`` / ``[`` / ``]`` would otherwise over-match unrelated
        # submissions. We reject outright rather than just escaping because
        # a pure-metachar task_id cannot correspond to any real
        # ``processed/<id>.json`` file either.
        if any(ch in task_id for ch in ("*", "?", "[", "]")):
            try:
                stderr.write(
                    "SECURITY: rejected unsafe task_id (glob metachar): "
                    f"{task_id!r}\n"
                )
            except Exception:
                pass
            continue
        # Length cap: avoid OSError(ENAMETOOLONG) from downstream
        # ``Path.exists()`` / ``Path.glob()`` calls.
        if len(task_id) > _MAX_TASK_ID_LEN:
            try:
                stderr.write(
                    "SECURITY: rejected unsafe task_id (name too long): "
                    f"{len(task_id)} chars\n"
                )
            except Exception:
                pass
            continue
        processed_path = processed_dir / f"{task_id}.json"
        # Defence-in-depth: verify the LEXICAL (non-symlink-resolved) parent
        # of the constructed path equals processed_dir. This catches any
        # traversal the basename check missed while still allowing symlink
        # entries inside processed/ to be unlinked (Path.unlink removes
        # the link, not the target — pinned by
        # test_processed_symlink_unlinks_link_not_target).
        _norm_parent = os.path.normpath(str(processed_path.parent))
        if _norm_parent != _norm_processed_root or not is_safe_subpath(
            _norm_parent, _norm_processed_root
        ):
            try:
                stderr.write(
                    "SECURITY: rejected unsafe task_id (escapes processed/): "
                    f"{task_id!r}\n"
                )
            except Exception:
                pass
            continue
        try:
            exists = processed_path.exists()
        except OSError as exc:
            if getattr(exc, "errno", None) == errno.ENAMETOOLONG:
                try:
                    stderr.write(
                        "SECURITY: rejected unsafe task_id (ENAMETOOLONG on exists): "
                        f"{task_id!r}\n"
                    )
                except Exception:
                    pass
                continue
            exists = False
        if exists:
            try:
                processed_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                continue
            else:
                unlinked += 1
                stderr.write(
                    f"cleared stale processed entry: {processed_path}\n"
                )
        if sessions_dir.is_dir():
            # Escape the task_id so ``*`` / ``?`` / ``[`` in future inputs
            # are treated as literals; the outer ``*_`` wildcard still
            # matches any agent prefix (claude_, gemini_, ...).
            escaped_id = _glob.escape(task_id)
            # Tolerate races: glob-then-unlink may see files disappear.
            try:
                matches = sorted(
                    sessions_dir.glob(f"*_{escaped_id}_submission.json")
                )
            except OSError:
                matches = []
            for sub_path in matches:
                try:
                    sub_path.unlink()
                except FileNotFoundError:
                    continue
                except OSError:
                    continue
                unlinked += 1
                stderr.write(f"cleared stale submission: {sub_path}\n")
    return unlinked


def _pending_task_count(state_dir: pathlib.Path) -> int:
    """Count unfinished task work — pending + in-flight + current.

    The orchestrator's lifecycle renames ``<task>.json`` → ``<task>.json.processing``
    when a worker picks it up, and drops a ``current_task.json`` marker. A wrapper
    that only counted ``*.json`` (minus current_task.json) would see zero during
    active synthesis and prematurely SIGINT the orchestrator mid-cycle. We count:

    * ``*.json`` (excluding ``current_task.json``) — queued and not yet claimed.
    * ``*.json.processing``                       — claimed, in active synthesis.
    * ``current_task.json`` (if present)          — at least one task in flight.
    """
    tasks_dir = state_dir / "tasks"
    if not tasks_dir.is_dir():
        return 0
    n = 0
    for pth in tasks_dir.glob("*.json"):
        if pth.name == "current_task.json":
            continue
        n += 1
    for pth in tasks_dir.glob("*.json.processing"):
        n += 1
    if (tasks_dir / "current_task.json").exists():
        n += 1
    return n


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="impl_drain_capture.py",
        description=(
            "Regenerate a single B3 drain baseline against a real orchestrator "
            "cycle. Replaces the synthetic placeholder under state/hooks/. "
            "Use --dry-run first to sanity-check the invocation plan — a real "
            "run burns a non-trivial slice of the operator's subscription window."
        ),
    )
    parser.add_argument(
        "--brief",
        required=True,
        help="Single brief id (required). One of {}.".format(", ".join(DRAIN_BRIEFS)),
    )
    parser.add_argument(
        "--session",
        default=None,
        help=(
            "Session id for this drain cycle. Default: "
            "drain-<brief>-<YYYYmmddTHHMMSSZ>."
        ),
    )
    parser.add_argument(
        "--baseline-dir",
        default=DRAIN_BASELINE_DIR,
        help=(
            "Directory for drain_baseline_<brief>.json output. "
            "Default matches DRAIN_BASELINE_DIR ({}).".format(DRAIN_BASELINE_DIR)
        ),
    )
    parser.add_argument(
        "--state-dir",
        default="state",
        help="Orchestrator state dir (default: state).",
    )
    parser.add_argument(
        "--config",
        default="harness/config.yaml",
        help="Harness config path (default: harness/config.yaml).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the full invocation plan (planner + orchestrator subprocess "
            "commands, expected patch/tracks paths, expected capture+save calls) "
            "but do NOT execute. Exit 0."
        ),
    )
    parser.add_argument(
        "--skip-planner",
        action="store_true",
        help=(
            "Skip the planner subprocess. Use if a prior (failed) invocation "
            "already planned tasks into state/tasks/ — avoids re-burning "
            "planner subscription cost."
        ),
    )
    parser.add_argument(
        "--planner-timeout",
        type=int,
        default=DEFAULT_PLANNER_TIMEOUT_S,
        help=(
            "Seconds before terminating the planner subprocess "
            "(default: {}).".format(DEFAULT_PLANNER_TIMEOUT_S)
        ),
    )
    parser.add_argument(
        "--orchestrator-timeout",
        type=int,
        default=DEFAULT_ORCHESTRATOR_TIMEOUT_S,
        help=(
            "Seconds before forcibly terminating the orchestrator even if the "
            "task queue has not drained (default: {}).".format(
                DEFAULT_ORCHESTRATOR_TIMEOUT_S
            )
        ),
    )
    parser.add_argument(
        "--poll-step",
        type=float,
        default=DEFAULT_POLL_STEP_S,
        help=(
            "Seconds between pending-queue polls (default: {}).".format(
                DEFAULT_POLL_STEP_S
            )
        ),
    )
    parser.add_argument(
        "--idle-confirm",
        type=float,
        default=DEFAULT_IDLE_CONFIRM_S,
        help=(
            "Consecutive seconds the pending queue must stay empty before "
            "we signal shutdown. Must be >= orchestrator POLL_INTERVAL × 2 "
            "to avoid stopping mid-decomposition (default: {}).".format(
                DEFAULT_IDLE_CONFIRM_S
            )
        ),
    )
    return parser


def _validate_brief(brief: str) -> None:
    if brief not in DRAIN_BRIEFS:
        raise SystemExit(
            "unknown brief {!r}; must be one of {}".format(brief, list(DRAIN_BRIEFS))
        )


def _emit_plan(
    *,
    brief: str,
    session: str,
    brief_file: pathlib.Path,
    config_path: pathlib.Path,
    state_dir: pathlib.Path,
    baseline_dir: pathlib.Path,
    patch_path: pathlib.Path,
    per_cycle_tracks: pathlib.Path,
    canonical_tracks: pathlib.Path,
    log_dir: pathlib.Path,
    interlocks: list[str],
    synthetic_placeholder: bool,
    skip_planner: bool,
    planner_timeout: int,
    orchestrator_timeout: int,
    idle_confirm: float,
    out=None,
) -> None:
    """Emit the dry-run / pre-execution plan.

    ``out`` defaults to ``None`` and is resolved to ``sys.stdout`` at call
    time so pytest's ``capsys`` capture (which replaces ``sys.stdout``
    per-test) still sees our writes.
    """
    lines: list[str] = []
    lines.append("=== drain-capture plan ===")
    lines.append(f"brief           : {brief}")
    lines.append(f"brief_file      : {brief_file}")
    lines.append(f"session         : {session}")
    lines.append(f"config          : {config_path}")
    lines.append(f"state_dir       : {state_dir}")
    lines.append(f"baseline_dir    : {baseline_dir}")
    lines.append(f"log_dir         : {log_dir}")
    lines.append(f"expected patch  : {patch_path}")
    lines.append(f"canonical tracks: {canonical_tracks}")
    lines.append(f"per-cycle tracks: {per_cycle_tracks}")
    lines.append("")
    step = 1
    if skip_planner:
        lines.append(
            f"{step}. [planner] SKIPPED (--skip-planner); expecting tasks already "
            f"queued under {state_dir}/tasks/*.json"
        )
    else:
        lines.append(
            "{}. [planner] {} -m harness.planner.cli {} --config {}".format(
                step, sys.executable, str(brief_file), str(config_path),
            )
        )
        lines.append(f"     timeout: {planner_timeout}s")
    step += 1
    lines.append(
        "{}. [shard] read {}/planning/merged_plan.json → write per-task "
        "files under {}/tasks/<task_id>.json (renames dependencies → depends_on)".format(
            step, str(state_dir), str(state_dir),
        )
    )
    step += 1
    lines.append(
        "{}. [orchestrator] {} -m harness.orchestrator --config {} "
        "--state-dir {} --log-dir {}".format(
            step, sys.executable, str(config_path), str(state_dir), str(log_dir),
        )
    )
    lines.append(
        f"     graceful shutdown: SIGINT once pending-queue empty for "
        f"{idle_confirm}s (hard timeout: {orchestrator_timeout}s)"
    )
    step += 1
    lines.append(
        "{}. patch = git diff <before>..<after>  →  {}".format(step, str(patch_path))
    )
    step += 1
    lines.append(
        "{}. tracks = tail -n +<lines_before+1> {}  →  {}".format(
            step, str(canonical_tracks), str(per_cycle_tracks),
        )
    )
    step += 1
    lines.append(
        "{}. test_count = pytest --collect-only -q (tests/hooks + P5 core "
        "suites)".format(step)
    )
    step += 1
    lines.append(
        "{}. art = capture_drain_artefacts(patch_path={!r}, "
        "tracks_path={!r}, test_count=<n>)".format(
            step, str(patch_path), str(per_cycle_tracks),
        )
    )
    step += 1
    lines.append(
        "{}. save_drain_baseline(brief_id={!r}, artefacts=art, "
        "baseline_dir={!r})".format(step, brief, str(baseline_dir))
    )
    lines.append("")
    if interlocks:
        lines.append("SAFETY INTERLOCKS WOULD BLOCK:")
        for b in interlocks:
            lines.append(f"  - {b}")
    else:
        lines.append("safety interlocks: clean (rollback_signal absent, no stale ROLLBACK-*.md)")
    if synthetic_placeholder:
        lines.append(
            f"note: existing baseline for {brief} still has __baseline_note "
            "(synthetic placeholder) — real capture would replace it"
        )
    stream = out if out is not None else sys.stdout
    stream.write("\n".join(lines) + "\n")


def _collect_test_count(repo_root: pathlib.Path) -> int:
    """Deterministic test count matching what compare_drain_artefacts expects.

    Uses the same targets as impl_phase_gate.py's P5 row plus the extra
    regression suites called out in the operator brief, via
    ``pytest --collect-only -q``.
    """
    import re

    targets = [
        "tests/hooks",
        "tests/test_orchestrator.py",
        "tests/test_task_decomposer.py",
        "tests/test_cross_examiner.py",
        "tests/test_mcp_server.py",
        "tests/test_depth_validator.py",
        "tests/test_hook_pre_tool.py",
        "tests/integration/",
    ]
    cmd = [sys.executable, "-m", "pytest", *targets, "--collect-only", "-q"]
    proc = subprocess.run(
        cmd, cwd=str(repo_root), capture_output=True, text=True, timeout=600,
    )
    if proc.returncode not in (0, 5):
        raise SystemExit(
            "test-count collection failed (exit {}): {}".format(
                proc.returncode, (proc.stderr or proc.stdout).strip()[-400:]
            )
        )
    tail = (proc.stdout or "").strip().splitlines()
    for line in reversed(tail):
        m = re.search(r"(\d+)\s+tests?\s+collected", line)
        if m:
            return int(m.group(1))
    raise SystemExit(
        "could not parse pytest collection count from output:\n"
        + "\n".join(tail[-10:])
    )


def _run_planner(
    *,
    brief_file: pathlib.Path,
    config_path: pathlib.Path,
    repo_root: pathlib.Path,
    log_dir: pathlib.Path,
    timeout: int,
) -> None:
    """Invoke ``harness.planner.cli`` as a subprocess and wait for it.

    Raises ``SystemExit`` on non-zero exit or timeout. Stdout/stderr are
    mirrored into ``<log_dir>/planner.stdout.log`` and ``planner.stderr.log``
    for operator post-mortem.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = log_dir / "planner.stdout.log"
    stderr_log = log_dir / "planner.stderr.log"
    cmd = [
        sys.executable, "-m", "harness.planner.cli",
        str(brief_file), "--config", str(config_path),
    ]
    try:
        with open(stdout_log, "w") as out_f, open(stderr_log, "w") as err_f:
            proc = subprocess.run(
                cmd, cwd=str(repo_root), stdout=out_f, stderr=err_f,
                timeout=timeout,
            )
    except subprocess.TimeoutExpired:
        raise SystemExit(
            f"planner timed out after {timeout}s; see {stderr_log}"
        )
    if proc.returncode != 0:
        tail = ""
        try:
            tail = stderr_log.read_text(encoding="utf-8")[-400:]
        except OSError:
            pass
        raise SystemExit(
            f"planner exited {proc.returncode}; see {stderr_log}\n{tail}"
        )


def _shard_merged_plan(
    plan_path: pathlib.Path,
    tasks_dir: pathlib.Path,
) -> list[str]:
    """Materialise ``state/planning/merged_plan.json`` into per-task JSON files.

    The planner CLI ends at ``persist_plan(final_plan, merged_plan.json)``; it
    does not split the ``plan["tasks"]`` array into the per-task files the
    orchestrator's ``get_next_task`` polls for. Without this shard step the
    orchestrator starts, finds an empty queue, and drains immediately — the
    baseline then captures a no-op cycle with zero track events.

    Schema translation: the merged plan uses ``"dependencies"`` (array of
    task-id strings) but the orchestrator reads ``"depends_on"``. We rename
    the field on write and preserve everything else; extra fields like
    ``spec``, ``test_spec``, ``acceptance_criteria`` are ignored harmlessly
    by the orchestrator but kept for operator post-mortem.

    Returns the list of task_ids written. Raises ``SystemExit`` if the plan
    is missing, malformed, or empty.
    """
    if not plan_path.exists():
        raise SystemExit(f"planner did not produce a plan at {plan_path}")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"merged plan at {plan_path} is not valid JSON: {e}")

    tasks = plan.get("tasks") if isinstance(plan, dict) else None
    if not isinstance(tasks, list) or not tasks:
        raise SystemExit(
            f"merged plan at {plan_path} has no tasks array to shard"
        )

    tasks_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = task.get("task_id")
        if not task_id or not isinstance(task_id, str):
            continue
        if "dependencies" in task and "depends_on" not in task:
            task = {**task, "depends_on": task["dependencies"]}
        target = tasks_dir / f"{task_id}.json"
        target.write_text(json.dumps(task, indent=2), encoding="utf-8")
        written.append(task_id)
    if not written:
        raise SystemExit(f"no tasks with valid task_id found in {plan_path}")
    return written


def _spawn_orchestrator(
    *,
    config_path: pathlib.Path,
    state_dir: pathlib.Path,
    log_dir: pathlib.Path,
    repo_root: pathlib.Path,
) -> subprocess.Popen:
    """Spawn the orchestrator in its own process group so we can SIGINT cleanly.

    stdout/stderr go to ``<log_dir>/orchestrator.{stdout,stderr}.log`` so the
    wrapper's own output stream stays readable.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = log_dir / "orchestrator.stdout.log"
    stderr_log = log_dir / "orchestrator.stderr.log"
    cmd = [
        sys.executable, "-m", "harness.orchestrator",
        "--config", str(config_path),
        "--state-dir", str(state_dir),
        "--log-dir", str(log_dir),
    ]
    out_f = open(stdout_log, "w")
    err_f = open(stderr_log, "w")
    proc = subprocess.Popen(
        cmd, cwd=str(repo_root), stdout=out_f, stderr=err_f,
        start_new_session=True,
    )
    proc._drain_log_handles = (out_f, err_f)  # type: ignore[attr-defined]
    return proc


def _wait_for_drain(
    *,
    orch_proc: subprocess.Popen,
    state_dir: pathlib.Path,
    poll_step: float,
    idle_confirm: float,
    timeout: int,
) -> str:
    """Poll until pending queue stays empty for ``idle_confirm`` seconds.

    Returns a short status string describing why we stopped waiting
    (``"idle"``, ``"timeout"``, or ``"orchestrator_exit"``). Callers should
    still shut down the orchestrator — this function only waits.
    """
    start = time.monotonic()
    idle_stretch = 0.0
    while True:
        rc = orch_proc.poll()
        if rc is not None:
            return "orchestrator_exit"
        elapsed = time.monotonic() - start
        if elapsed > timeout:
            return "timeout"
        pending = _pending_task_count(state_dir)
        if pending == 0:
            idle_stretch += poll_step
            if idle_stretch >= idle_confirm:
                return "idle"
        else:
            idle_stretch = 0.0
        time.sleep(poll_step)


def _shutdown_orchestrator(
    orch_proc: subprocess.Popen,
    *,
    sigint_grace: int = DEFAULT_SIGINT_GRACE_S,
    sigterm_grace: int = DEFAULT_SIGTERM_GRACE_S,
) -> int:
    """Graceful SIGINT → SIGTERM → SIGKILL escalation; returns final exit code.

    The orchestrator's ``main()`` catches ``KeyboardInterrupt`` (SIGINT)
    and sets phase=idle before exiting cleanly. SIGTERM is not caught, so
    SIGINT must be first.
    """
    handles = getattr(orch_proc, "_drain_log_handles", ())
    try:
        if orch_proc.poll() is None:
            try:
                os.killpg(os.getpgid(orch_proc.pid), signal.SIGINT)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                return orch_proc.wait(timeout=sigint_grace)
            except subprocess.TimeoutExpired:
                pass
        if orch_proc.poll() is None:
            try:
                os.killpg(os.getpgid(orch_proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                return orch_proc.wait(timeout=sigterm_grace)
            except subprocess.TimeoutExpired:
                pass
        if orch_proc.poll() is None:
            try:
                os.killpg(os.getpgid(orch_proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                return orch_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                return -1
        return orch_proc.returncode if orch_proc.returncode is not None else -1
    finally:
        for h in handles:
            try:
                h.close()
            except OSError:
                pass


def _spawn_outbox_watcher(
    *,
    state_dir: pathlib.Path,
    log_dir: pathlib.Path,
    repo_root: pathlib.Path,
) -> subprocess.Popen:
    """Spawn the Path-A outbox-watcher sidecar.

    Works around Claude Code 2.1.114 silently dropping hooks in ``-p`` mode.
    See ``docs/runbooks/claude_hook_regression_repair.md`` §Path A.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = log_dir / "outbox_watcher.stdout.log"
    stderr_log = log_dir / "outbox_watcher.stderr.log"
    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "impl_outbox_watcher.py"),
        "--state-dir", str(state_dir),
    ]
    out_f = open(stdout_log, "w")
    err_f = open(stderr_log, "w")
    proc = subprocess.Popen(
        cmd, cwd=str(repo_root), stdout=out_f, stderr=err_f,
        start_new_session=True,
    )
    proc._drain_log_handles = (out_f, err_f)
    return proc


def _shutdown_outbox_watcher(proc: subprocess.Popen, *, grace: int = 5) -> int:
    """SIGTERM then SIGKILL the sidecar. Mirrors ``_shutdown_orchestrator``."""
    handles = getattr(proc, "_drain_log_handles", ())
    try:
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                return proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                pass
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                return proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                return -1
        return proc.returncode if proc.returncode is not None else -1
    finally:
        for h in handles:
            try:
                h.close()
            except OSError:
                pass


def _capture_tracks_delta(
    *,
    canonical: pathlib.Path,
    lines_before: int,
    dest: pathlib.Path,
) -> None:
    """Copy lines ``[lines_before:]`` of ``canonical`` to ``dest``.

    If ``canonical`` does not exist or has shrunk (unlikely; would mean
    a concurrent truncation), write an empty file at ``dest`` so
    ``capture_drain_artefacts`` reads a real (empty) path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not canonical.exists():
        dest.write_text("", encoding="utf-8")
        return
    try:
        with open(canonical, "r", encoding="utf-8") as src:
            out_lines: list[str] = []
            for idx, line in enumerate(src):
                if idx < lines_before:
                    continue
                out_lines.append(line)
        with open(dest, "w", encoding="utf-8") as out_f:
            out_f.writelines(out_lines)
    except OSError as e:
        raise SystemExit(f"failed to capture tracks delta: {e}")


_IMPL_PROGRESS_LEDGER = _REPO_ROOT / "state" / "impl_progress.jsonl"


def _ledger_append_observation(
    *,
    detail: str,
    files: list[str],
    approved_by: str = "automated:drain_capture",
    ledger_path: pathlib.Path | None = None,
) -> None:
    """Append a single ``observation`` row to ``state/impl_progress.jsonl``.

    Never raises — a best-effort breadcrumb for the auto-commit helper.

    ``approved_by`` defaults to an honest ``"automated:drain_capture"``
    marker (M4-3): these rows are automated breadcrumbs, not
    operator-approved actions, and must not carry a fake operator
    signature. Callers that do have explicit operator approval should
    pass it explicitly.

    ``ledger_path`` defaults to the module-level ``_IMPL_PROGRESS_LEDGER``
    when ``None``; passing an explicit path lets tmp-repo tests redirect
    writes without monkeypatching the module constant.
    """
    target = ledger_path if ledger_path is not None else _IMPL_PROGRESS_LEDGER
    row = {
        "ts": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "phase": "META",
        "task_id": "",
        "event": "observation",
        "detail": detail,
        "files": files,
        "exit": 0,
        "approved_by": approved_by,
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        # Ledger write failures must never crash the drain wrapper. The
        # stderr path below still carries the signal for the operator.
        pass


def _auto_commit_drain_baseline(
    *,
    baseline_path: pathlib.Path,
    brief_id: str,
    session: str,
    state_dir: pathlib.Path,
    repo_root: pathlib.Path = _REPO_ROOT,
    ledger_path: pathlib.Path | None = None,
) -> bool:
    """Stage & commit the freshly-persisted drain baseline + session evidence.

    Closes the race documented in ``state/impl_progress.jsonl`` row
    ``2026-04-20T15:11:00Z``: if the baseline is left uncommitted, the
    NEXT drain's pre-flight ``git checkout --`` treats it as dirty scratch
    and wipes the real capture back to the synthetic placeholder. Template
    borrowed from ``harness/orchestrator._auto_commit_accepted`` — matches
    its subprocess flags (``check=False``, explicit ``cwd``, ``timeout``)
    and its ``Integrate validated code for …`` commit-message style.

    Never raises. Returns True only if a new commit was produced.
    """
    # F1-MED: refuse hostile brief_id values that would split the commit
    # subject or smuggle fake trailers (Co-Authored-By / Signed-off-by)
    # via f-string interpolation below.
    if "\n" in brief_id or "\r" in brief_id:
        _ledger_append_observation(
            detail=(
                "auto-commit drain baseline: refused — brief_id contains "
                "newline/carriage-return control chars (trailer-injection "
                "guard)"
            ),
            files=[],
            ledger_path=ledger_path,
        )
        sys.stderr.write(
            "auto-commit drain baseline: refused (brief_id contains "
            "newline/CR)\n"
        )
        return False
    # F1-MED: refuse detached HEAD — an anonymous-chain commit defeats
    # the pre-flight race-guard this helper exists to close (the commit
    # is unreachable by branch name and eligible for GC).
    try:
        symref_rc = subprocess.run(
            ["git", "symbolic-ref", "-q", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        _ledger_append_observation(
            detail=(
                "auto-commit drain baseline: `git symbolic-ref` failed: "
                f"{exc!r}"
            ),
            files=[],
            ledger_path=ledger_path,
        )
        sys.stderr.write(
            f"auto-commit drain baseline: git symbolic-ref raised {exc!r}\n"
        )
        return False
    if symref_rc.returncode != 0:
        _ledger_append_observation(
            detail=(
                "auto-commit drain baseline: refused — detached HEAD "
                "(anonymous-chain commit would defeat race-guard); "
                f"git symbolic-ref rc={symref_rc.returncode}"
            ),
            files=[],
            ledger_path=ledger_path,
        )
        sys.stderr.write(
            "auto-commit drain baseline: refused (detached HEAD)\n"
        )
        return False
    baseline_rel = str(baseline_path)
    try:
        if baseline_path.is_absolute():
            try:
                baseline_rel = str(baseline_path.relative_to(repo_root))
            except ValueError:
                # Baseline lives outside the repo root — nothing we can
                # commit here; skip cleanly so the drain wrapper continues.
                _ledger_append_observation(
                    detail=(
                        "auto-commit drain baseline: skipped — baseline "
                        f"{baseline_path} escapes repo root {repo_root}"
                    ),
                    files=[],
                    ledger_path=ledger_path,
                )
                sys.stderr.write(
                    "auto-commit drain baseline: skipped (path outside repo)\n"
                )
                return False

        if not baseline_path.exists():
            _ledger_append_observation(
                detail=(
                    f"auto-commit drain baseline: skipped — {baseline_rel} "
                    "not present on disk"
                ),
                files=[baseline_rel],
                ledger_path=ledger_path,
            )
            sys.stderr.write(
                f"auto-commit drain baseline: skipped (missing {baseline_rel})\n"
            )
            return False

        # Operator-visible evidence files: per-round submission JSON + the
        # agent ledger JSONL. Glob patterns match the shapes written by
        # scripts/impl_outbox_watcher.py and harness/orchestrator's session
        # logger. We stage only files that actually exist so ``git add``
        # never errors on a missing path.
        sessions_dir = state_dir / "sessions"
        evidence_globs = (
            "claude_round*_*_submission.json",
            "gemini_round*_*_submission.json",
            "claude_*.ledger.jsonl",
            "gemini_*.ledger.jsonl",
        )
        evidence_paths: list[str] = []
        if sessions_dir.is_dir():
            for pat in evidence_globs:
                for p in sessions_dir.glob(pat):
                    if not p.is_file():
                        continue
                    try:
                        rel = str(p.resolve().relative_to(repo_root))
                    except ValueError:
                        continue
                    evidence_paths.append(rel)

        # F1-HIGH: use ``-f`` so a gitignored ``state/`` (.gitignore:15)
        # does not make git return rc=1; the whole point of this helper is
        # to commit the drain baseline under state/hooks/.
        add_args = ["git", "add", "-f", "--", baseline_rel] + evidence_paths
        try:
            add_rc = subprocess.run(
                add_args,
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            _ledger_append_observation(
                detail=(
                    "auto-commit drain baseline: `git add` failed for "
                    f"{baseline_rel}: {exc!r}"
                ),
                files=[baseline_rel],
                ledger_path=ledger_path,
            )
            sys.stderr.write(
                f"auto-commit drain baseline: git add raised {exc!r}\n"
            )
            return False
        if add_rc.returncode != 0:
            _ledger_append_observation(
                detail=(
                    "auto-commit drain baseline: `git add` rc="
                    f"{add_rc.returncode} stderr={add_rc.stderr.strip()!r}"
                ),
                files=[baseline_rel],
                ledger_path=ledger_path,
            )
            sys.stderr.write(
                "auto-commit drain baseline: git add rc="
                f"{add_rc.returncode}: {add_rc.stderr.strip()}\n"
            )
            return False

        # Skip the commit if there are no cached changes under the baseline —
        # mirrors the ``--cached --quiet`` pattern in _auto_commit_accepted.
        diff_rc = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--", baseline_rel],
            cwd=str(repo_root),
            check=False,
            timeout=30,
        ).returncode
        if diff_rc == 0:
            # No change against HEAD for the baseline itself — nothing to
            # commit. Do not emit a ledger observation for the no-op case
            # to avoid polluting the log on repeat runs.
            return False

        now_iso = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        commit_subject = f"Capture real drain baseline for {brief_id}"
        commit_body = (
            f"Brief: {brief_id}\n"
            f"Session: {session}\n"
            f"Captured-at: {now_iso}\n"
            f"Auto-committed-by: scripts/impl_drain_capture.py (drain wrapper)\n"
            "\n"
            "Closes the pre-flight `git checkout --` race documented in\n"
            "state/impl_progress.jsonl row 2026-04-20T15:11:00Z: without\n"
            "this commit the next drain wipes the freshly-captured\n"
            "baseline back to the synthetic placeholder.\n"
            "\n"
            "Co-Authored-By: Claude Opus 4.7 (1M context) "
            "<noreply@anthropic.com>"
        )
        commit_msg = f"{commit_subject}\n\n{commit_body}"
        # F1-HIGH: pathspec-scope the commit to the exact files we staged
        # (baseline + evidence). Without `-- <pathspec>` `git commit`
        # bundles every other pre-staged index entry into the auto-commit.
        commit_argv = [
            "git", "commit", "-m", commit_msg, "--", baseline_rel,
        ] + evidence_paths
        try:
            commit_rc = subprocess.run(
                commit_argv,
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            _ledger_append_observation(
                detail=(
                    "auto-commit drain baseline: `git commit` failed for "
                    f"{baseline_rel}: {exc!r}"
                ),
                files=[baseline_rel],
                ledger_path=ledger_path,
            )
            sys.stderr.write(
                f"auto-commit drain baseline: git commit raised {exc!r}\n"
            )
            return False
        if commit_rc.returncode != 0:
            _ledger_append_observation(
                detail=(
                    "auto-commit drain baseline: `git commit` rc="
                    f"{commit_rc.returncode} stderr="
                    f"{commit_rc.stderr.strip()!r}"
                ),
                files=[baseline_rel],
                ledger_path=ledger_path,
            )
            sys.stderr.write(
                "auto-commit drain baseline: git commit rc="
                f"{commit_rc.returncode}: {commit_rc.stderr.strip()}\n"
            )
            return False

        sys.stderr.write(
            f"auto-commit drain baseline: SUCCESS {baseline_rel} "
            f"(+{len(evidence_paths)} evidence files)\n"
        )
        return True
    except Exception as exc:  # pragma: no cover - defensive
        # Catch-all — losing the commit is recoverable; crashing the
        # wrapper mid-drain is not.
        try:
            _ledger_append_observation(
                detail=(
                    "auto-commit drain baseline: unexpected exception "
                    f"for {baseline_rel}: {exc!r}"
                ),
                files=[baseline_rel],
                ledger_path=ledger_path,
            )
        except Exception:
            pass
        sys.stderr.write(
            f"auto-commit drain baseline: unexpected {exc!r}\n"
        )
        return False


def _run_real_cycle(
    *,
    config_path: pathlib.Path,
    state_dir: pathlib.Path,
    session: str,
    patch_path: pathlib.Path,
    per_cycle_tracks: pathlib.Path,
    canonical_tracks: pathlib.Path,
    log_dir: pathlib.Path,
    brief_file: pathlib.Path,
    skip_planner: bool,
    planner_timeout: int,
    orchestrator_timeout: int,
    poll_step: float,
    idle_confirm: float,
) -> str:
    """Run a full planner + orchestrator cycle; capture patch and tracks-delta.

    Returns the drain-status string from ``_wait_for_drain``. Mutates
    ``patch_path`` and ``per_cycle_tracks`` on disk. Raises ``SystemExit``
    on planner failure or unexpected orchestrator exit.
    """
    before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(_REPO_ROOT), capture_output=True, text=True, check=True,
    ).stdout.strip()

    lines_before = _count_lines(canonical_tracks)

    if not skip_planner:
        _run_planner(
            brief_file=brief_file,
            config_path=config_path,
            repo_root=_REPO_ROOT,
            log_dir=log_dir,
            timeout=planner_timeout,
        )

    merged_plan_path = state_dir / "planning" / "merged_plan.json"
    tasks_dir = state_dir / "tasks"
    # Why: orchestrator skips task_ids already in tasks/processed/, so cached
    # --skip-planner re-runs would idle forever without this scrub.
    if merged_plan_path.exists():
        try:
            _stale_plan_obj = json.loads(merged_plan_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _stale_plan_obj = None
        # B3 guard: empty-tasks stubs (see 2026-04-20T00:10Z wipe incident,
        # ledger row 2026-04-20T05:18:33Z) must not silently shadow a prior
        # good plan. Abort before _clear_stale_task_state / _shard_merged_plan
        # touch disk — covers both the post-planner path and --skip-planner
        # where the cached plan is expected to carry live tasks.
        if isinstance(_stale_plan_obj, dict):
            _tasks = _stale_plan_obj.get("tasks")
            if not isinstance(_tasks, list) or len(_tasks) == 0:
                raise RuntimeError(
                    "merged_plan.json shows empty tasks after planner "
                    "step — refusing to shard over cached work. See "
                    "docs/runbooks/operator_followup.md §3."
                )
        if _stale_plan_obj is not None:
            _clear_stale_task_state(_stale_plan_obj, state_dir, sys.stderr)
    written_task_ids = _shard_merged_plan(merged_plan_path, tasks_dir)
    sys.stderr.write(
        f"sharded {len(written_task_ids)} task(s) from {merged_plan_path} "
        f"into {tasks_dir}: {', '.join(written_task_ids)}\n"
    )

    # Path-A sidecar: must bracket the orchestrator lifetime so Claude -p-mode
    # submissions persist (see docs/runbooks/claude_hook_regression_repair.md).
    watcher_proc = _spawn_outbox_watcher(
        state_dir=state_dir,
        log_dir=log_dir,
        repo_root=_REPO_ROOT,
    )
    try:
        orch_proc = _spawn_orchestrator(
            config_path=config_path,
            state_dir=state_dir,
            log_dir=log_dir,
            repo_root=_REPO_ROOT,
        )
        try:
            status = _wait_for_drain(
                orch_proc=orch_proc,
                state_dir=state_dir,
                poll_step=poll_step,
                idle_confirm=idle_confirm,
                timeout=orchestrator_timeout,
            )
        finally:
            _shutdown_orchestrator(orch_proc)
    finally:
        _shutdown_outbox_watcher(watcher_proc)

    after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(_REPO_ROOT), capture_output=True, text=True, check=True,
    ).stdout.strip()

    patch_path.parent.mkdir(parents=True, exist_ok=True)
    if before == after:
        patch_path.write_text("", encoding="utf-8")
    else:
        diff = subprocess.run(
            ["git", "diff", f"{before}..{after}"],
            cwd=str(_REPO_ROOT), capture_output=True, text=True, check=True,
        ).stdout
        patch_path.write_text(diff, encoding="utf-8")

    _capture_tracks_delta(
        canonical=canonical_tracks,
        lines_before=lines_before,
        dest=per_cycle_tracks,
    )

    if status == "orchestrator_exit":
        rc = orch_proc.returncode
        if rc not in (0, None):
            raise SystemExit(
                f"orchestrator exited unexpectedly (rc={rc}); see "
                f"{log_dir}/orchestrator.stderr.log — artefacts captured anyway"
            )
    return status


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    _validate_brief(args.brief)

    brief_file = _brief_file_path(args.brief)
    if not brief_file.exists():
        raise SystemExit(f"brief file not found: {brief_file}")

    session = args.session or _default_session_id(args.brief)

    def _resolve(p: str) -> pathlib.Path:
        pp = pathlib.Path(p)
        if not pp.is_absolute():
            pp = _REPO_ROOT / pp
        return pp

    state_dir = _resolve(args.state_dir)
    baseline_dir = _resolve(args.baseline_dir)
    config_path = _resolve(args.config)
    patch_path = _patch_path(state_dir, session)
    canonical_tracks = _tracks_path(state_dir)
    per_cycle_tracks = _per_cycle_tracks_path(state_dir, session)
    log_dir = _log_dir(_REPO_ROOT, session)

    interlocks = _rollback_interlock_blockers(state_dir)
    synthetic_placeholder = _existing_baseline_is_synthetic(args.brief, baseline_dir)

    if args.dry_run:
        _emit_plan(
            brief=args.brief,
            session=session,
            brief_file=brief_file,
            config_path=config_path,
            state_dir=state_dir,
            baseline_dir=baseline_dir,
            patch_path=patch_path,
            per_cycle_tracks=per_cycle_tracks,
            canonical_tracks=canonical_tracks,
            log_dir=log_dir,
            interlocks=interlocks,
            synthetic_placeholder=synthetic_placeholder,
            skip_planner=args.skip_planner,
            planner_timeout=args.planner_timeout,
            orchestrator_timeout=args.orchestrator_timeout,
            idle_confirm=args.idle_confirm,
        )
        return 0

    if interlocks:
        sys.stderr.write(
            "refusing to run: safety interlock(s) active:\n  - "
            + "\n  - ".join(interlocks) + "\n"
        )
        return 1

    if not config_path.exists():
        raise SystemExit(f"config not found: {config_path}")

    if synthetic_placeholder:
        sys.stderr.write(
            f"Replacing synthetic placeholder baseline for {args.brief}\n"
        )

    status = _run_real_cycle(
        config_path=config_path,
        state_dir=state_dir,
        session=session,
        patch_path=patch_path,
        per_cycle_tracks=per_cycle_tracks,
        canonical_tracks=canonical_tracks,
        log_dir=log_dir,
        brief_file=brief_file,
        skip_planner=args.skip_planner,
        planner_timeout=args.planner_timeout,
        orchestrator_timeout=args.orchestrator_timeout,
        poll_step=args.poll_step,
        idle_confirm=args.idle_confirm,
    )

    if status == "timeout":
        sys.stderr.write(
            f"WARN: orchestrator did not drain within {args.orchestrator_timeout}s "
            "— baseline captured from partial cycle\n"
        )

    test_count = _collect_test_count(_REPO_ROOT)

    artefacts: DrainArtefacts = capture_drain_artefacts(
        patch_path=patch_path,
        tracks_path=per_cycle_tracks,
        test_count=test_count,
    )
    # Empty-capture tripwire: refuse to overwrite the on-disk baseline if
    # neither agent produced any work. Restored 2026-04-20 per blocker #12.
    if _is_empty_capture(artefacts):
        sys.stderr.write(
            "EMPTY-CAPTURE TRIPWIRE: patch_stat empty AND track_events "
            f"empty (test_count={artefacts.test_count}, status={status}). "
            f"Refusing to overwrite state/hooks/drain_baseline_{args.brief}"
            ".json — the on-disk file is left untouched so grep -L "
            "__baseline_note stays honest.\n"
        )
        return 2
    out = save_drain_baseline(
        brief_id=args.brief,
        artefacts=artefacts,
        baseline_dir=baseline_dir,
    )
    # Pre-flight race guard (ledger row 2026-04-20T15:11:00Z): the next
    # drain's `git checkout --` treats an uncommitted baseline as dirty
    # scratch and wipes it back to the synthetic placeholder. Auto-commit
    # immediately. Helper never raises — losing the commit is recoverable,
    # crashing the wrapper mid-drain is not.
    _auto_commit_drain_baseline(
        baseline_path=out,
        brief_id=args.brief,
        session=session,
        state_dir=state_dir,
    )
    size = out.stat().st_size if out.exists() else 0
    sys.stdout.write(
        "wrote {} ({} bytes) — test_count={} events={} patch_stat_lines={} "
        "status={}\n".format(
            out, size, artefacts.test_count,
            len(artefacts.track_events),
            len(artefacts.patch_stat.splitlines()),
            status,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
