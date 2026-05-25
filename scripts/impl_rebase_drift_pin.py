"""Rebase the EXPECTED_BASE_SHA tripwire in scripts/impl_common.py.

The pin in impl_common.py is a hand-edited literal that anchors a saga
session. When the saga closes, the operator rebases the pin to the new
HEAD so subsequent prompts don't fire the DRIFT banner on every fire.
This script makes that a one-command operation and appends a ledger
observation row documenting the rebase.

Usage:
    python scripts/impl_rebase_drift_pin.py             # rebase to current HEAD
    python scripts/impl_rebase_drift_pin.py <sha>       # rebase to a specific commit
    python scripts/impl_rebase_drift_pin.py --dry-run   # report only, no writes

Exit codes:
    0 — rebase applied (or dry-run reported)
    1 — new sha unresolved by git or pin literal not found in impl_common.py
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.impl_common import append_impl_progress_event  # noqa: E402

_IMPL_COMMON = _REPO_ROOT / "scripts" / "impl_common.py"
_PIN_RE = re.compile(r'^EXPECTED_BASE_SHA\s*=\s*"([0-9a-f]{6,40})"\s*$', re.MULTILINE)


def _resolve_short_sha(arg: str | None) -> str | None:
    target = arg or "HEAD"
    try:
        out = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "--short=7", target],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        sys.stderr.write(f"git rev-parse failed: {exc}\n")
        return None
    if out.returncode != 0:
        sys.stderr.write(out.stderr or f"git rev-parse {target!r} returned {out.returncode}\n")
        return None
    sha = out.stdout.strip()
    return sha or None


def main() -> int:
    args = [a for a in sys.argv[1:] if a]
    dry_run = "--dry-run" in args
    positional = [a for a in args if not a.startswith("--")]
    target_arg = positional[0] if positional else None

    new_sha = _resolve_short_sha(target_arg)
    if not new_sha:
        return 1

    src = _IMPL_COMMON.read_text(encoding="utf-8")
    match = _PIN_RE.search(src)
    if not match:
        sys.stderr.write("EXPECTED_BASE_SHA pin not found in scripts/impl_common.py\n")
        return 1
    old_sha = match.group(1)

    if old_sha == new_sha:
        sys.stdout.write(f"EXPECTED_BASE_SHA already at {new_sha}; no change.\n")
        return 0

    if dry_run:
        sys.stdout.write(f"DRY-RUN: would rebase EXPECTED_BASE_SHA {old_sha} -> {new_sha}\n")
        return 0

    new_src = src[:match.start()] + f'EXPECTED_BASE_SHA = "{new_sha}"' + src[match.end():]
    _IMPL_COMMON.write_text(new_src, encoding="utf-8")

    append_impl_progress_event(
        event="observation",
        phase="META",
        detail=(
            f"Rebased EXPECTED_BASE_SHA pin {old_sha} -> {new_sha} via "
            f"scripts/impl_rebase_drift_pin.py. Anchors next saga session; "
            f"prior drift acknowledged by all scope_exception rows since "
            f"the pin was last rebased."
        ),
        files=["scripts/impl_common.py"],
    )

    sys.stdout.write(f"EXPECTED_BASE_SHA rebased {old_sha} -> {new_sha}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
