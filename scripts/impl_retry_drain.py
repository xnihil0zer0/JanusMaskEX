"""Resilient retry driver for B3 drain-baseline regen.

Wraps ``scripts/impl_drain_capture.py`` with graceful-resume semantics so
operators can leave the regen cycle running through intermittent failures
— Gemini server 429s, Claude hook regressions, orchestrator idle-timeouts.
Per-brief retry cap + inter-attempt backoff keeps the loop from burning
subscription quota when the underlying failure mode is persistent.

Core invariants:

1. Resume-safe: scans ``state/hooks/drain_baseline_*.json`` at launch and
   skips briefs whose baseline is already real (no ``__baseline_note``).
   Caller can CTRL-C and relaunch with the same args; progress persists
   because the drain wrapper commits auto-commits on success.
2. Empty-capture aware: honours the ``_is_empty_capture`` tripwire
   (rc=2 from ``impl_drain_capture.py``) — restores the synthetic
   placeholder from HEAD so ``grep -L __baseline_note`` stays truthful
   between attempts.
3. Ledger-visible: every attempt appends one row to
   ``state/impl_progress.jsonl`` describing the outcome (start, success,
   empty_capture, timeout, retry, cap_reached).
4. Remote-failure tolerant: Gemini 429 RetryableQuotaError and
   "Claude hooks not firing" both surface as empty-capture → retry.
   The driver does not try to diagnose or fix remote issues; it just
   keeps trying with backoff. See
   ``docs/runbooks/claude_hook_regression_repair.md`` for the local fix
   plan for hooks.

Usage:
    python3 scripts/impl_retry_drain.py                # all pending briefs
    python3 scripts/impl_retry_drain.py --briefs stab_003
    python3 scripts/impl_retry_drain.py --max-attempts 3 --backoff 900

See ledger rows at 2026-04-19T20:55:45Z (blocker #10), 2026-04-20T05:48:54Z
(blocker #12), and 2026-04-20T05:50:44Z (addendum) for context.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_LEDGER = _REPO_ROOT / "state" / "impl_progress.jsonl"
_BASELINE_DIR = _REPO_ROOT / "state" / "hooks"
_DRAIN_WRAPPER = _REPO_ROOT / "scripts" / "impl_drain_capture.py"
_ALL_BRIEFS = ("stab_001", "stab_003", "stab_005")
_DEFAULT_MAX_ATTEMPTS = 5
_DEFAULT_BACKOFF_SECONDS = 1200  # 20 minutes — past the 5-min cache window
_DEFAULT_DRAIN_TIMEOUT = 1800    # match handoff's per-drain ceiling


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _ledger_append(row: dict) -> None:
    """Append one event row to state/impl_progress.jsonl.

    M4-3: ``approved_by`` defaults to ``"automated:retry_drain"`` when
    the caller does not set it. These rows are automated breadcrumbs
    and must not carry a fake operator-approval signature. Callers
    with genuine operator authorisation should set ``approved_by``
    explicitly before calling.

    M4-2: ``paths`` defaults to ``[]`` so every blocker/blocker_resolved
    row carries the canonical optional-paths field (readers treat missing
    ``paths`` as drift; see brief_hooks_schema_drift_03.md §4.3).
    """
    row.setdefault("ts", _now_iso())
    row.setdefault("phase", "META")
    row.setdefault("task_id", "")
    row.setdefault("files", [])
    row.setdefault("paths", [])
    row.setdefault("exit", 0)
    row.setdefault("approved_by", "automated:retry_drain")
    with _LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _baseline_path(brief: str) -> pathlib.Path:
    return _BASELINE_DIR / f"drain_baseline_{brief}.json"


def _baseline_is_real(brief: str) -> bool:
    """True iff the on-disk baseline lacks __baseline_note (= real capture)."""
    path = _baseline_path(brief)
    if not path.exists():
        return False
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    if not isinstance(obj, dict):
        return False
    if "__baseline_note" in obj:
        return False
    # Extra conservativity: patch_stat must be non-empty to count as real.
    # The 2026-04-20T05:18Z stab_003 attempt wrote a 136B file with no
    # __baseline_note but patch_stat="" — tripwire-worthy, not "real".
    patch_stat = (obj.get("artefacts") or {}).get("patch_stat", "")
    return bool((patch_stat or "").strip())


def _restore_synthetic_from_head(brief: str) -> bool:
    """Run ``git checkout HEAD -- <baseline>`` to reset to synthetic."""
    path = _baseline_path(brief).relative_to(_REPO_ROOT)
    try:
        rc = subprocess.run(
            ["git", "checkout", "HEAD", "--", str(path)],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        return rc.returncode == 0
    except OSError:
        return False


def _pending_briefs(all_briefs: tuple[str, ...]) -> list[str]:
    return [b for b in all_briefs if not _baseline_is_real(b)]


def _run_drain(brief: str, drain_timeout: int) -> tuple[int, str]:
    """Run impl_drain_capture.py --brief <brief> --skip-planner.

    Returns (returncode, tail-of-stderr). Uses the system ``timeout``
    command so a hung orchestrator gets SIGTERM'd at drain_timeout s.
    """
    log_stem = f"retry-drain-{brief}-{_now_iso().replace(':', '')}"
    out_path = pathlib.Path(f"/tmp/{log_stem}.stdout")
    err_path = pathlib.Path(f"/tmp/{log_stem}.stderr")
    cmd = [
        "timeout", str(drain_timeout),
        "python3", str(_DRAIN_WRAPPER),
        "--brief", brief,
        "--skip-planner",
    ]
    with out_path.open("wb") as out, err_path.open("wb") as err:
        proc = subprocess.run(
            cmd, cwd=str(_REPO_ROOT),
            stdout=out, stderr=err, check=False,
        )
    try:
        tail = err_path.read_text(encoding="utf-8", errors="replace")
        tail_lines = tail.splitlines()[-10:]
        tail_str = "\n".join(tail_lines)
    except OSError:
        tail_str = ""
    return proc.returncode, tail_str


def _classify(rc: int, stderr_tail: str, brief: str) -> str:
    """Categorize a drain outcome to a single-token label."""
    if rc == 0 and _baseline_is_real(brief):
        return "success"
    if rc == 2:
        return "empty_capture"
    if rc == 124:
        return "timeout"
    if rc == 0 and not _baseline_is_real(brief):
        # Tripwire somehow let an empty cycle through (shouldn't happen
        # post-fix) — still treat as empty_capture for recovery purposes.
        return "empty_capture_unguarded"
    return f"unknown_rc_{rc}"


def _sleep_with_watchdog(seconds: int, reason: str) -> None:
    """Sleep N seconds, printing a heartbeat every 60s so the operator
    tailing the log can tell the driver is alive (not wedged)."""
    if seconds <= 0:
        return
    sys.stderr.write(
        f"[retry-drain] backoff {seconds}s ({reason}); heartbeat every 60s\n"
    )
    sys.stderr.flush()
    start = time.monotonic()
    while True:
        remaining = seconds - (time.monotonic() - start)
        if remaining <= 0:
            break
        step = min(60.0, remaining)
        time.sleep(step)
        sys.stderr.write(
            f"[retry-drain] ...still waiting, {int(remaining - step)}s left\n"
        )
        sys.stderr.flush()


def _backoff_seconds(attempt: int, base: int) -> int:
    """Exponential-ish: base, base*1.5, base*2.25, base*3, base*3 (cap)."""
    multiplier = min(3.0, 1.0 * (1.5 ** max(0, attempt - 1)))
    return int(base * multiplier)


def run_brief(
    brief: str,
    *,
    max_attempts: int,
    backoff: int,
    drain_timeout: int,
) -> str:
    """Drive retries for one brief until success or cap. Returns final label."""
    if _baseline_is_real(brief):
        _ledger_append({
            "event": "observation",
            "detail": (
                f"retry-drain: skipping {brief} — baseline already real "
                f"(no __baseline_note, patch_stat non-empty)."
            ),
            "files": [str(_baseline_path(brief).relative_to(_REPO_ROOT))],
        })
        return "already_real"

    for attempt in range(1, max_attempts + 1):
        _ledger_append({
            "event": "start",
            "detail": (
                f"retry-drain attempt {attempt}/{max_attempts} for {brief}. "
                f"Cmd: python3 scripts/impl_drain_capture.py --brief {brief} "
                f"--skip-planner. Drain timeout: {drain_timeout}s."
            ),
            "files": [],
        })
        sys.stderr.write(
            f"[retry-drain] ==== {brief} attempt {attempt}/{max_attempts} ====\n"
        )
        sys.stderr.flush()

        rc, stderr_tail = _run_drain(brief, drain_timeout)
        label = _classify(rc, stderr_tail, brief)

        _ledger_append({
            "event": "observation",
            "detail": (
                f"retry-drain {brief} attempt {attempt}/{max_attempts} "
                f"→ rc={rc} label={label}. "
                f"stderr tail: {stderr_tail[-800:] if stderr_tail else '<empty>'}"
            ),
            "files": [str(_baseline_path(brief).relative_to(_REPO_ROOT))],
            "exit": rc,
        })

        if label == "success":
            _ledger_append({
                "event": "blocker_resolved",
                "detail": (
                    f"retry-drain {brief} SUCCESS on attempt {attempt}. "
                    f"Baseline is real (patch_stat non-empty, no __baseline_note)."
                ),
                "files": [str(_baseline_path(brief).relative_to(_REPO_ROOT))],
            })
            return "success"

        # All failure cases: restore synthetic placeholder so the file on
        # disk is either real or __baseline_note — never a hollow in-between.
        restored = _restore_synthetic_from_head(brief)
        sys.stderr.write(
            f"[retry-drain] {brief} attempt {attempt} failed "
            f"({label}); synthetic placeholder restored={restored}\n"
        )
        sys.stderr.flush()

        if attempt >= max_attempts:
            _ledger_append({
                "event": "blocker",
                "detail": (
                    f"retry-drain {brief} CAP REACHED after {max_attempts} "
                    f"attempts. Final label: {label}. Likely persistent "
                    "failure (Gemini 429 or Claude hook regression — see "
                    "docs/runbooks/claude_hook_regression_repair.md). Operator "
                    "action required."
                ),
                "files": [str(_baseline_path(brief).relative_to(_REPO_ROOT))],
                "exit": rc,
            })
            return label

        wait = _backoff_seconds(attempt, backoff)
        _sleep_with_watchdog(
            wait, reason=f"{brief} {label}, next attempt {attempt + 1}"
        )

    return "cap_reached"  # unreachable — loop exits via success or cap branch


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--briefs",
        nargs="*",
        default=None,
        help="Zero or more briefs (subset filter; nargs='*'). "
             f"Empty or omitted means every brief in {_ALL_BRIEFS} "
             "whose baseline is still synthetic.",
    )
    p.add_argument(
        "--max-attempts", type=int, default=_DEFAULT_MAX_ATTEMPTS,
        help="Per-brief retry cap (default: %(default)s).",
    )
    p.add_argument(
        "--backoff", type=int, default=_DEFAULT_BACKOFF_SECONDS,
        help="Base backoff seconds between attempts; scales 1.5^(n-1) up "
             "to 3x (default: %(default)s).",
    )
    p.add_argument(
        "--drain-timeout", type=int, default=_DEFAULT_DRAIN_TIMEOUT,
        help="Per-drain wall-clock ceiling (default: %(default)s).",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print what would run and exit.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.briefs:
        briefs = [b for b in args.briefs if b in _ALL_BRIEFS]
        if not briefs:
            sys.stderr.write(
                f"error: --briefs must be subset of {_ALL_BRIEFS}\n"
            )
            return 2
    else:
        briefs = _pending_briefs(_ALL_BRIEFS)

    if not briefs:
        sys.stderr.write(
            "[retry-drain] no pending briefs — all baselines already real\n"
        )
        return 0

    sys.stderr.write(
        f"[retry-drain] plan: {briefs} (max_attempts={args.max_attempts}, "
        f"backoff={args.backoff}s, drain_timeout={args.drain_timeout}s)\n"
    )
    if args.dry_run:
        return 0

    _ledger_append({
        "event": "start",
        "detail": (
            f"retry-drain driver launched. Pending briefs: {briefs}. "
            f"max_attempts={args.max_attempts} base_backoff={args.backoff}s "
            f"drain_timeout={args.drain_timeout}s. See "
            "docs/runbooks/claude_hook_regression_repair.md for context on "
            "expected failure modes."
        ),
        "files": [],
    })

    labels: dict[str, str] = {}
    for brief in briefs:
        labels[brief] = run_brief(
            brief,
            max_attempts=args.max_attempts,
            backoff=args.backoff,
            drain_timeout=args.drain_timeout,
        )

    any_failed = any(lbl != "success" and lbl != "already_real"
                     for lbl in labels.values())

    _ledger_append({
        "event": "observation",
        "detail": (
            f"retry-drain driver FINISHED. Labels: {labels}. "
            + ("Some briefs hit retry cap — see blocker rows above." if any_failed
               else "All briefs succeeded.")
        ),
        "files": [],
    })

    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
