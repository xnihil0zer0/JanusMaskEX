import os
import subprocess
import pytest

# Try to import the primitive - this MUST fail on HEAD (RED check: symbol absent).
try:
    from harness.git_integration import _verify_from_ro_parent
except ImportError as e:
    # Explicitly re-raise so pytest registers a collection-time import failure
    # (RED on HEAD until part-1 lands the primitive).
    raise ImportError(
        "RED check: _verify_from_ro_parent is absent on master/HEAD"
    ) from e


# ----------------------------------------------------------------------------
# MECHANISM / TREE LAYOUT (the crux: "trusted test code x candidate harness")
#
#   PARENT repo (committed, materialised read-only via `git archive`):
#       src/roprobe.py            -> LIMIT = 10   (parent value, never run)
#       tests/test_probe_invariant.py
#                                 -> imports `roprobe`, asserts LIMIT <= 10
#                                    (the TRUSTED gatekeeper test)
#
#   The primitive extracts the parent tree into a tmp dir and runs pytest with
#   cwd=<tmp>. With pytest's default "prepend" import mode (and no __init__.py),
#   the only sys.path entry pytest adds for the test file is <tmp>/tests/ --
#   which does NOT contain roprobe.py (it lives in <tmp>/src/, off-path). So
#   `import roprobe` inside the trusted test CANNOT resolve from the parent
#   (tmp) tree. The ONLY place roprobe.py is importable is <staging_path>,
#   which the primitive PREPENDS onto PYTHONPATH. Hence the trusted test code
#   runs against the CANDIDATE's roprobe -- exactly the intended pairing.
#
#   STAGING (adversarial):  roprobe.py -> LIMIT = 999  (violates invariant)
#                           tests/test_probe_invariant.py -> weakened (assert True)
#       => running staging's OWN test would pass, but the primitive runs the
#          TRUSTED parent test, which imports the staging roprobe (LIMIT=999)
#          and FAILS the assert -> pytest nonzero -> primitive returns False.
#
#   STAGING (benign):       roprobe.py -> LIMIT = 5   (satisfies invariant)
#       => trusted parent test passes against staging roprobe -> returns True.
# ----------------------------------------------------------------------------


def test_sec_ro_checkout_primitive(tmp_path):
    # 1. Initialize parent git repository (trusted, read-only via git archive).
    parent_repo = tmp_path / "parent_repo"
    parent_repo.mkdir()

    subprocess.run(['git', 'init'], cwd=str(parent_repo), check=True,
                   capture_output=True, text=True)
    subprocess.run(['git', 'config', 'user.name', 'Oracle Test'],
                   cwd=str(parent_repo), check=True, capture_output=True, text=True)
    subprocess.run(['git', 'config', 'user.email', 'oracle@test.com'],
                   cwd=str(parent_repo), check=True, capture_output=True, text=True)

    # Parent: roprobe.py lives in src/ (OFF the pytest test-dir path) so the
    # trusted test can only resolve `roprobe` from the PYTHONPATH-prepended
    # staging path, never from the parent tmp tree itself.
    src_dir = parent_repo / "src"
    src_dir.mkdir()
    (src_dir / "roprobe.py").write_text("LIMIT = 10\n")

    # Trusted gate test: imports the probe and asserts the invariant.
    tests_dir = parent_repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_probe_invariant.py").write_text(
        "import roprobe\n"
        "def test_invariant():\n"
        "    assert roprobe.LIMIT <= 10\n"
    )

    subprocess.run(['git', 'add', 'src/roprobe.py', 'tests/test_probe_invariant.py'],
                   cwd=str(parent_repo), check=True, capture_output=True, text=True)
    subprocess.run(['git', 'commit', '-m', 'Initial commit'],
                   cwd=str(parent_repo), check=True, capture_output=True, text=True)

    res = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=str(parent_repo),
                         capture_output=True, text=True, check=True)
    parent_head_sha = res.stdout.strip()

    # 2. Adversarial staging: probe VIOLATES the invariant AND the staging's
    #    own copy of the gate test is WEAKENED (would pass if it were run).
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    (staging_dir / "roprobe.py").write_text("LIMIT = 999\n")
    staging_tests = staging_dir / "tests"
    staging_tests.mkdir()
    (staging_tests / "test_probe_invariant.py").write_text(
        "def test_invariant():\n"
        "    assert True\n"
    )

    # 3. Benign staging: probe satisfies the invariant.
    benign_dir = tmp_path / "benign"
    benign_dir.mkdir()
    (benign_dir / "roprobe.py").write_text("LIMIT = 5\n")
    benign_tests = benign_dir / "tests"
    benign_tests.mkdir()
    (benign_tests / "test_probe_invariant.py").write_text(
        "def test_invariant():\n"
        "    assert True\n"
    )

    # Assert: adversarial staging FAILS validation (trusted test catches the
    # LIMIT=999 violation against the candidate probe) -> False.
    assert not _verify_from_ro_parent(
        repo_root=parent_repo,
        parent_head_sha=parent_head_sha,
        staging_path=staging_dir,
        gate_test_paths=['tests/test_probe_invariant.py'],
    )

    # Assert: benign staging PASSES validation -> True.
    assert _verify_from_ro_parent(
        repo_root=parent_repo,
        parent_head_sha=parent_head_sha,
        staging_path=benign_dir,
        gate_test_paths=['tests/test_probe_invariant.py'],
    )

    # Assert FAIL-CLOSED: bogus parent_head_sha (git archive fails) -> False.
    assert not _verify_from_ro_parent(
        repo_root=parent_repo,
        parent_head_sha="0000000000000000000000000000000000000000",
        staging_path=benign_dir,
        gate_test_paths=['tests/test_probe_invariant.py'],
    )

    # Assert FAIL-CLOSED: missing gate test in the trusted snapshot -> False.
    assert not _verify_from_ro_parent(
        repo_root=parent_repo,
        parent_head_sha=parent_head_sha,
        staging_path=benign_dir,
        gate_test_paths=['tests/test_missing.py'],
    )
