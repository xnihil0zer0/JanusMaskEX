"""Shared text emitter for SessionStart / UserPromptSubmit meta-hooks.

Invoked via impl_session_start.sh and impl_prompt_context.sh. Reads the
ledger, derives state, prints a context summary to stdout (becomes
additionalContext in the Claude Code session).

See hooks-augmented-hooks-implementation-plan.md §3.1.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from impl_common import (
    EXPECTED_BASE_SHA,
    LEDGER_PATH,
    PROJECT_DIR,
    compute_dod_gaps,
    derive_state,
    load_ledger,
    phase_allow_globs,
    scope_exception_paths,
)

# HH5 / W72: age threshold separating (active) from (stale) SE rows.
_SE_STALE_AFTER_DAYS = 14


def _ts_to_epoch(ts: str) -> float | None:
    """Parse an ISO-8601 ledger timestamp to a POSIX epoch (UTC)."""
    if not isinstance(ts, str):
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            dt = datetime.datetime.strptime(ts, fmt)
            return dt.replace(tzinfo=datetime.timezone.utc).timestamp()
        except (ValueError, TypeError):
            continue
    return None


def _scope_exception_status_map(ledger: list[dict]) -> dict[str, str]:
    """Compute per-path status tags for the Active scope_exception banner.

    Returns a mapping ``{path: tag}`` where tag is one of ``active``,
    ``consumed``, ``missing``, or ``stale`` (see HH5 design / W72 / W72b):

    - ``consumed`` — some test_pass row for the authoring task_id exists
      with a timestamp AT OR AFTER the SE row's ts.
    - ``missing``  — the SE-listed path does not exist on disk relative to
      ``PROJECT_DIR``. Overrides ``active`` and ``stale``; ``consumed`` and
      ``revoked`` (applied by caller) still win — work was completed even
      if the file was later moved/renamed.
    - ``stale``    — SE row is older than ``_SE_STALE_AFTER_DAYS`` days AND
      no matching test_pass row has been seen AND the path exists.
    - ``active``   — none of the above.

    When a path appears in multiple SE rows, the "best" status wins in the
    order: consumed > missing > active > stale. This keeps the banner
    honest (once a path is consumed under any task, we should not flag it
    as stale or missing under another). The ``(revoked)`` overlay is
    applied by the caller separately.
    """
    now = datetime.datetime.now(datetime.timezone.utc).timestamp()
    stale_cutoff = _SE_STALE_AFTER_DAYS * 86400

    # task_id -> list of test_pass epoch timestamps
    passes_by_task: dict[str, list[float]] = {}
    for row in ledger:
        if not isinstance(row, dict):
            continue
        if row.get("event") != "test_pass":
            continue
        task_id = row.get("task_id") or ""
        ts = _ts_to_epoch(row.get("ts", ""))
        if ts is None:
            continue
        passes_by_task.setdefault(task_id, []).append(ts)

    # Rank ordering used to resolve dup paths: higher rank replaces lower.
    # consumed > missing > active > stale.
    rank = {"stale": 0, "active": 1, "missing": 2, "consumed": 3}
    status: dict[str, str] = {}

    for row in ledger[-150:]:
        if not isinstance(row, dict) or row.get("event") != "scope_exception":
            continue
        paths = row.get("paths")
        if not isinstance(paths, list):
            continue
        task_id = row.get("task_id") or ""
        se_ts = _ts_to_epoch(row.get("ts", ""))

        consumed = False
        if se_ts is not None:
            for pass_ts in passes_by_task.get(task_id, []):
                if pass_ts >= se_ts:
                    consumed = True
                    break

        is_stale = (
            se_ts is not None and (now - se_ts) > stale_cutoff
        )

        for p in paths:
            if not isinstance(p, str):
                continue
            # Per-path tag (path-existence is path-specific, not row-specific).
            if consumed:
                tag = "consumed"
            elif not (PROJECT_DIR / p).exists():
                tag = "missing"
            elif is_stale:
                tag = "stale"
            else:
                tag = "active"

            prev = status.get(p)
            if prev is None or rank[tag] > rank[prev]:
                status[p] = tag

    return status


def _git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(PROJECT_DIR), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def _format_rows(rows: list[dict]) -> str:
    if not rows:
        return "  (empty)"
    lines = []
    for r in rows:
        line = f"  [{r.get('ts','')}] {r.get('phase','').ljust(4)} {r.get('event','').ljust(18)} task={r.get('task_id','')}"
        detail = (r.get("detail") or "").strip()
        if detail:
            line += f" — {detail[:80]}"
        lines.append(line)
    return "\n".join(lines)


def emit(mode: str) -> None:
    ledger = load_ledger()
    state = derive_state(ledger)
    phase = state["current_phase"] or "META"
    task = state["current_task_id"] or "<none>"
    head = _git_head()
    head_ok = head.startswith(EXPECTED_BASE_SHA)

    lines = ["=== JanusMask meta-hook context ==="]
    lines.append(f"Ledger: {LEDGER_PATH}")
    lines.append(f"Git HEAD: {head} (expected base {EXPECTED_BASE_SHA}{'' if head_ok else ' — DRIFT; acknowledge via scope_exception row'})")
    lines.append(f"Current phase: {phase}")
    lines.append(f"Current task : {task}")
    if state["rollback_signal"]:
        lines.append("ROLLBACK SIGNAL PRESENT in last 50 rows — investigate before new writes.")

    if task != "<none>":
        gaps = compute_dod_gaps(task, ledger)
        if gaps:
            lines.append("Outstanding DoD gaps for current task:")
            for g in gaps:
                lines.append(f"  - {g}")
        else:
            lines.append("Current task DoD satisfied; Stop will be allowed.")

    allowed = phase_allow_globs(phase)
    lines.append(f"Phase {phase} write allow-list:")
    for g in allowed:
        lines.append(f"  - {g}")

    sx = scope_exception_paths(ledger)
    if sx:
        revoked_paths: set[str] = set()
        for row in ledger[-150:]:
            if not isinstance(row, dict) or row.get("event") != "scope_revoke":
                continue
            paths = row.get("paths") or []
            if isinstance(paths, str):
                paths = [paths]
            for p in paths:
                if isinstance(p, str):
                    revoked_paths.add(p)
        # HH5 / W72: per-path status tagging.
        status_map = _scope_exception_status_map(ledger)
        annotated: list[str] = []
        seen: set[str] = set()
        for p in sx:
            if p in seen:
                continue
            seen.add(p)
            if p in revoked_paths:
                tag = "revoked"
            else:
                tag = status_map.get(p, "active")
            annotated.append(f"{p} ({tag})")
        lines.append(f"Active scope_exception paths: {annotated}")

    if mode == "session_start":
        lines.append("")
        lines.append("Reminder: writes outside the allow-list are denied; Stop is blocked until")
        lines.append("test_pass + adv_pass + acceptance_files are satisfied. Escape hatches in")
        lines.append("hooks-augmented-hooks-implementation-plan.md §7.2.")
        lines.append("Last 5 ledger rows:")
        lines.append(_format_rows(state["last_rows"]))

    sys.stdout.write("\n".join(lines) + "\n")


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "prompt"
    try:
        emit(mode)
    except Exception as e:  # noqa: BLE001
        # Never wedge the session: emit a short warning and exit 0.
        sys.stdout.write(f"[meta-hook context emit failed: {e}]\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
