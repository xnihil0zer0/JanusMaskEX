"""Tests for the taxonomy loader and validator."""

import json
from pathlib import Path

import pytest
from hypothesis import given, strategies as st

from harness.taxonomy import (
    TaxonomyError,
    UnknownTaxonomyKeyError,
    load_meta_task_taxonomy,
    load_synthesis_target_taxonomy,
    meta_task_keys,
    synthesis_target_keys,
    validate_meta_task_type,
    validate_synthesis_target_type,
)


EXPECTED_META_KEYS = {
    "sandbox_infra", "mcp_server_change",
    "config_schema", "data_model", "cli_tooling", "test_unit",
    "test_integration", "test_e2e", "docs_writing", "refactor",
    "logging_observability",
    "orchestration", "harness_plumbing", "planner_tooling",
    "hooks_integration", "validation",
    "mcp_plumbing", "state_machine", "io_adapter",
}


@pytest.fixture(autouse=True)
def set_default_state_dir(monkeypatch):
    """Ensure that by default, tests read the seed files from the worktree."""
    worktree_state_dir = Path(__file__).parent.parent / "state"
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(worktree_state_dir))


def test_meta_task_taxonomy_seed_present():
    """The seeded meta-task taxonomy file exists and contains the full canonical key set."""
    data = load_meta_task_taxonomy()
    assert data["version"] == 1
    assert set(data["keys"].keys()) == EXPECTED_META_KEYS


def test_synthesis_target_taxonomy_seed_present():
    """The seeded synthesis-target taxonomy file exists and contains exactly the fourteen preamble keys."""
    data = load_synthesis_target_taxonomy()
    assert data["version"] == 1

    expected_keys = {
        "array_transform", "numerical_computation", "string_parsing",
        "string_formatting", "graph_traversal", "tree_recursion",
        "dynamic_programming", "bitwise_logic", "hash_set_logic",
        "greedy_interval", "constraint_satisfaction", "stateful_simulation",
        "geometry", "io_transform"
    }
    assert set(data["keys"].keys()) == expected_keys


def test_loader_validates_version_type(monkeypatch, tmp_path):
    """Loader rejects taxonomy files whose version is not an int."""
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
    file_path = tmp_path / "meta_task_taxonomy.json"

    with open(file_path, "w") as f:
        json.dump({"version": "1", "keys": {"a": "b"}}, f)

    with pytest.raises(TaxonomyError, match="'version' must be an int"):
        load_meta_task_taxonomy()


def test_loader_rejects_empty_keys(monkeypatch, tmp_path):
    """Loader rejects taxonomy files with empty keys object."""
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
    file_path = tmp_path / "meta_task_taxonomy.json"

    with open(file_path, "w") as f:
        json.dump({"version": 1, "keys": {}}, f)

    with pytest.raises(TaxonomyError, match="'keys' must be a non-empty dict"):
        load_meta_task_taxonomy()


def test_meta_task_keys_returns_frozenset():
    """meta_task_keys() returns a frozenset so callers cannot mutate the loaded set."""
    keys = meta_task_keys()
    assert isinstance(keys, frozenset)
    assert keys == EXPECTED_META_KEYS


def test_validate_meta_task_type_accepts_known_keys():
    """validate_meta_task_type returns None for every seeded key."""
    assert validate_meta_task_type("data_model") is None
    assert validate_meta_task_type("orchestration") is None
    assert validate_meta_task_type("planner_tooling") is None
    assert validate_meta_task_type("hooks_integration") is None


def test_validate_meta_task_type_rejects_unknown():
    """validate_meta_task_type raises UnknownTaxonomyKeyError on unknown keys."""
    with pytest.raises(UnknownTaxonomyKeyError) as exc_info:
        validate_meta_task_type("not_a_real_type")

    err_msg = str(exc_info.value)
    assert "not_a_real_type" in err_msg
    assert "data_model" in err_msg


def test_taxonomy_round_trip_with_tmp_state_dir(monkeypatch, tmp_path):
    """Loader honors an overridden state dir via the JANUSMASK_STATE_DIR env var and reads freshly-written taxonomy files."""
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))

    meta_path = tmp_path / "meta_task_taxonomy.json"
    with open(meta_path, "w") as f:
        json.dump({"version": 1, "keys": {"subset_meta": "A subset meta task"}}, f)

    synth_path = tmp_path / "synthesis_target_taxonomy.json"
    with open(synth_path, "w") as f:
        json.dump({"version": 1, "keys": {"subset_synth": "A subset synth target"}}, f)

    meta_data = load_meta_task_taxonomy()
    assert meta_data["keys"] == {"subset_meta": "A subset meta task"}

    synth_data = load_synthesis_target_taxonomy()
    assert synth_data["keys"] == {"subset_synth": "A subset synth target"}

    assert validate_meta_task_type("subset_meta") is None
    assert validate_synthesis_target_type("subset_synth") is None


@given(st.text().filter(lambda x: x not in EXPECTED_META_KEYS))
def test_validate_random_unknown_keys_always_reject(key):
    """Any random string not in the taxonomy is rejected."""
    with pytest.raises(UnknownTaxonomyKeyError):
        validate_meta_task_type(key)


def test_taxonomy_file_missing_message(monkeypatch, tmp_path):
    """Pointing the loader at a non-existent path surfaces the path in the error message to aid debugging."""
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))

    with pytest.raises(TaxonomyError) as exc_info:
        load_meta_task_taxonomy()

    expected_path = tmp_path / "meta_task_taxonomy.json"
    assert str(expected_path) in str(exc_info.value)


def test_taxonomy_invalid_json_wrapped(monkeypatch, tmp_path):
    """Malformed JSON in a taxonomy file is wrapped in TaxonomyError (not raw json.JSONDecodeError)."""
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
    file_path = tmp_path / "meta_task_taxonomy.json"

    with open(file_path, "w") as f:
        f.write("{ invalid json")

    with pytest.raises(TaxonomyError) as exc_info:
        load_meta_task_taxonomy()

    assert "Invalid JSON in taxonomy file" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)
