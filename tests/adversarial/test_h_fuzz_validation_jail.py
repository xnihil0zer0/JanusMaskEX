"""Adversarial oracle for H-FUZZ: ensure narrow-fuzz validation executes candidate code
in a separate jailed subprocess rather than in-process on the host.
"""
from __future__ import annotations

import os
import re
import shutil
import pytest
from harness.narrow_fuzz import validation

_SENTINEL_VAR = "JANUSMASK_H_FUZZ_SENTINEL"


def test_narrow_fuzz_executes_in_separate_process():
    """Verify that candidate module import/exec cannot modify host process state (in-process side effects)."""
    if _SENTINEL_VAR in os.environ:
        del os.environ[_SENTINEL_VAR]

    candidate_src = f"""
import os
os.environ[{_SENTINEL_VAR!r}] = "compromised"

def validate_dummy(x: int) -> bool:
    return True
"""
    validation.fuzz("_canary", candidate_src)
    assert _SENTINEL_VAR not in os.environ, "Candidate module was executed in-process on the host!"


def test_narrow_fuzz_executes_in_different_pid():
    """Verify that candidate code executes under a different PID than the host (structural fact)."""
    host_pid = os.getpid()

    candidate_src = """
import os
def validate_pid(x: int) -> bool:
    raise RuntimeError(f"PID: {os.getpid()}")
"""
    err = validation.fuzz("_canary", candidate_src)
    assert err is not None
    match = re.search(r"PID:\s*(\d+)", err)
    assert match is not None, f"Could not find PID in error: {err}"
    child_pid = int(match.group(1))
    assert child_pid != host_pid, f"Candidate code ran in host process (PID {host_pid})!"


def test_narrow_fuzz_uses_bwrap_jail_when_available():
    """Verify that if bwrap is available, writing to a path outside the allowed workspace is denied."""
    if shutil.which("bwrap") is None:
        pytest.skip("bwrap not installed, skipping jail write denial check")

    from harness.paths import PROJECT_ROOT_STR

    test_file_path = os.path.join(PROJECT_ROOT_STR, "h_fuzz_jail_write_test_sentinel.txt")
    if os.path.exists(test_file_path):
        try:
            os.remove(test_file_path)
        except OSError:
            pass

    candidate_src = f"""
def validate_write(x: int) -> bool:
    with open({test_file_path!r}, "w") as f:
        f.write("jail_breached")
    return True
"""
    err = validation.fuzz("_canary", candidate_src)
    # Load-bearing structural assertion: under the bwrap jail the repo root is
    # ro-bound, so the candidate's open(...,'w') is denied by the KERNEL and the
    # file must NOT exist on the host. This proves the candidate ran in the jail,
    # not in-process (in-process exec would succeed in writing the file).
    assert not os.path.exists(test_file_path), (
        "Jail write barrier was bypassed! File written to repository root -- "
        "candidate executed without the bwrap ro-bind."
    )
    # The blocked write must surface as a validator crash carrying a filesystem
    # write-denial signal (NOT the catch-all 'Error', which would also match an
    # unrelated driver failure and make this vacuous).
    assert err is not None, "Validator should have crashed due to blocked write under the jail"
    assert any(
        x in err
        for x in ("OSError", "PermissionError", "ReadOnlyFileSystem", "Read-only file system", "EROFS", "Errno 30")
    ), f"expected a filesystem write-denial signal in the error, got: {err!r}"
