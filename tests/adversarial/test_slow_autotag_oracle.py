"""Oracle for tests/adversarial/conftest.py -- the adversarial slow-autotagger.

The deliverable (synthesized by the pipeline) is a NEW file
``tests/adversarial/conftest.py`` whose ``pytest_collection_modifyitems`` hook
adds the ``slow`` marker to every collected test item located under
``tests/adversarial/``. That lets the fast inner-loop tier exclude the heavy
integration tier via ``-m "not slow"`` while the serial gate still runs
everything.

RED on HEAD: ``tests/adversarial/conftest.py`` does not exist, so adversarial
items carry no ``slow`` marker; ``pytest --collect-only -m "not slow"`` on an
adversarial file COLLECTS them (exit code 0).

GREEN after the fix: the hook marks them ``slow``; the same command collects
ZERO items (pytest exit code 5 == "no tests collected").

All checks use ``--collect-only`` (no test execution -> no recursion when this
oracle probes its own file).
"""
import pathlib
import subprocess
import sys

THIS = pathlib.Path(__file__).resolve()
REPO = THIS.parents[2]
NO_TESTS_COLLECTED = 5  # pytest exit code when 0 items remain after marker filter


def _collect_only_not_slow(target: str) -> int:
    """Return the pytest exit code of a `--collect-only -m "not slow"` run."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
         "--collect-only", "-q", "-m", "not slow", target],
        capture_output=True, text=True, cwd=str(REPO),
    )
    return proc.returncode


def test_adversarial_conftest_exists():
    """Structural: the autotagger conftest must exist after the fix."""
    assert (REPO / "tests" / "adversarial" / "conftest.py").is_file(), (
        "tests/adversarial/conftest.py must exist (it auto-tags adversarial "
        "tests `slow`)"
    )


def test_adversarial_items_are_slow_marked():
    """PRIMARY (RED on HEAD): an adversarial test file collects ZERO items under
    `-m "not slow"` once the conftest marks it slow (pytest exit 5)."""
    rc = _collect_only_not_slow(str(THIS.relative_to(REPO)))
    assert rc == NO_TESTS_COLLECTED, (
        f"adversarial items not slow-marked: `--collect-only -m 'not slow'` on "
        f"this file returned exit {rc}, expected {NO_TESTS_COLLECTED} "
        f"(all items deselected because marked slow)"
    )


def test_unit_items_not_slow_marked():
    """NARROWNESS GUARD: non-adversarial (unit) tests must NOT be slow-marked --
    they still collect under `-m "not slow"` (exit 0)."""
    rc = _collect_only_not_slow("tests/unit")
    assert rc == 0, (
        f"unit tests were wrongly slow-marked: `--collect-only -m 'not slow'` on "
        f"tests/unit returned exit {rc}, expected 0 (items still selected)"
    )
