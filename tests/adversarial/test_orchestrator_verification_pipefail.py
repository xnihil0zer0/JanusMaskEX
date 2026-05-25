"""Adversarial regression: pin pipefail behavior for verification_command (G25).

The orchestrator runs each task's ``verification_command`` via
``subprocess.run(..., shell=True, executable='/bin/bash')`` after wrapping
the vcmd in ``set -o pipefail; <vcmd>``. Without that wrapping, a vcmd of
the form ``... | tail -5`` returns the exit code of ``tail`` (always 0)
and a real test failure inside the pipe is silently swallowed. The two
tests below pin both halves of the invariant.

The harness wraps every vcmd via the same prefix + executable kwargs, so
these tests double as a contract test for the shape of that invocation.
"""
from __future__ import annotations

import subprocess


def test_pipefail_propagates_failure_through_tail() -> None:
    proc = subprocess.run(
        "set -o pipefail; python -c 'import sys; sys.exit(7)' | tail -5",
        shell=True,
        executable="/bin/bash",
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 7, (
        f"pipefail did not propagate left-hand failure through tail: rc={proc.returncode!r}"
    )


def test_pipefail_zero_when_pipeline_succeeds() -> None:
    proc = subprocess.run(
        "set -o pipefail; python -c 'print(42)' | tail -5",
        shell=True,
        executable="/bin/bash",
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"clean pipeline returned non-zero under pipefail: rc={proc.returncode!r}, stderr={proc.stderr!r}"
    )
