"""Hygiene: every taxonomy key must be referenced by at least one test.

state/meta_task_taxonomy.json and state/synthesis_target_taxonomy.json
define keys the planner synthesises against. A key that no test file
mentions has no coverage — this test fails loudly listing such keys so
the operator can add coverage or retire the key.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from harness.taxonomy import load_meta_task_taxonomy, load_synthesis_target_taxonomy

TESTS_ROOT = Path(__file__).resolve().parents[1]
SELF_FILE = Path(__file__).resolve()


def _count_references(key: str) -> int:
    proc = subprocess.run(
        ["grep", "-rl", "--include=*.py", key, str(TESTS_ROOT)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    matches = [
        line.strip() for line in proc.stdout.splitlines() if line.strip()
    ]
    return sum(1 for m in matches if Path(m).resolve() != SELF_FILE)


def test_meta_task_keys_each_referenced_by_one_test():
    keys = sorted(load_meta_task_taxonomy()["keys"].keys())
    unreferenced = [k for k in keys if _count_references(k) == 0]
    assert not unreferenced, (
        f"Meta-task taxonomy keys with zero test references: {unreferenced}. "
        "Add a test or remove the key from meta_task_taxonomy.json."
    )


def test_synthesis_target_keys_each_referenced_by_one_test():
    keys = sorted(load_synthesis_target_taxonomy()["keys"].keys())
    unreferenced = [k for k in keys if _count_references(k) == 0]
    assert not unreferenced, (
        f"Synthesis-target taxonomy keys with zero test references: {unreferenced}. "
        "Add a test or remove the key from synthesis_target_taxonomy.json."
    )
