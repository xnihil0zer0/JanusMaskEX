"""Hygiene: CI guard against missing, empty, or corrupt taxonomy files.

tests/test_track_record_init.py copies taxonomy files from
harness.state._default_state_dir() during init. If state/ were ever
gitignored, those init tests would degrade silently (copy zero-byte
files). This test fails loudly if state/meta_task_taxonomy.json or
state/synthesis_target_taxonomy.json is missing, empty, or malformed.
"""

from __future__ import annotations

import pytest

from harness.state import _default_state_dir
from harness.taxonomy import (
    TaxonomyError,
    load_meta_task_taxonomy,
    load_synthesis_target_taxonomy,
)


def test_meta_task_taxonomy_file_present_and_nonempty():
    state_dir = _default_state_dir()
    path = state_dir / "meta_task_taxonomy.json"
    assert path.exists(), (
        f"meta_task_taxonomy.json missing at {path}. "
        "If state/ is gitignored, restore from a canonical source."
    )
    assert path.stat().st_size > 0, f"meta_task_taxonomy.json is empty at {path}"


def test_synthesis_target_taxonomy_file_present_and_nonempty():
    state_dir = _default_state_dir()
    path = state_dir / "synthesis_target_taxonomy.json"
    assert path.exists(), (
        f"synthesis_target_taxonomy.json missing at {path}. "
        "If state/ is gitignored, restore from a canonical source."
    )
    assert path.stat().st_size > 0, (
        f"synthesis_target_taxonomy.json is empty at {path}"
    )


def test_meta_task_taxonomy_parses_and_has_keys():
    try:
        data = load_meta_task_taxonomy()
    except TaxonomyError as e:
        pytest.fail(f"meta_task_taxonomy.json failed to load: {e}")
    assert isinstance(data.get("keys"), dict)
    assert len(data["keys"]) > 0


def test_synthesis_target_taxonomy_parses_and_has_keys():
    try:
        data = load_synthesis_target_taxonomy()
    except TaxonomyError as e:
        pytest.fail(f"synthesis_target_taxonomy.json failed to load: {e}")
    assert isinstance(data.get("keys"), dict)
    assert len(data["keys"]) > 0
