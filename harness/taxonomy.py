"""Taxonomy loader and validator for JanusMask."""

import json
from pathlib import Path

from harness.state import _default_state_dir


class TaxonomyError(Exception):
    """Raised when a taxonomy file is missing, malformed, or invalid."""
    pass


class UnknownTaxonomyKeyError(TaxonomyError):
    """Raised when an unknown taxonomy key is encountered."""
    pass


def _load_taxonomy_file(file_name: str, path: Path | None = None) -> dict:
    state_dir = path or _default_state_dir()
    file_path = state_dir / file_name

    if not file_path.exists():
        raise TaxonomyError(f"Taxonomy file missing at {file_path}")

    try:
        with open(file_path, "r") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise TaxonomyError(f"Invalid JSON in taxonomy file {file_path}: {e}") from e

    if not isinstance(data, dict):
        raise TaxonomyError(f"Taxonomy file {file_path} must contain a top-level JSON object")

    if "version" not in data or "keys" not in data:
        raise TaxonomyError(f"Taxonomy file {file_path} is missing 'version' or 'keys'")

    version = data["version"]
    if not isinstance(version, int) or isinstance(version, bool):
        raise TaxonomyError(f"Taxonomy file {file_path} 'version' must be an int")
    
    if version < 1:
        raise TaxonomyError(f"Taxonomy file {file_path} 'version' must be >= 1")

    keys = data["keys"]
    if not isinstance(keys, dict) or not keys:
        raise TaxonomyError(f"Taxonomy file {file_path} 'keys' must be a non-empty dict")

    for v in keys.values():
        if not isinstance(v, str) or not v:
            raise TaxonomyError(f"Taxonomy file {file_path} 'keys' values must be non-empty strings")

    return data


def load_meta_task_taxonomy(path: Path | None = None) -> dict:
    """Load and validate the meta-task taxonomy JSON file."""
    return _load_taxonomy_file("meta_task_taxonomy.json", path)


def load_synthesis_target_taxonomy(path: Path | None = None) -> dict:
    """Load and validate the synthesis-target taxonomy JSON file."""
    return _load_taxonomy_file("synthesis_target_taxonomy.json", path)


def meta_task_keys() -> frozenset[str]:
    """Return a frozenset of valid meta-task keys."""
    data = load_meta_task_taxonomy()
    return frozenset(data["keys"].keys())


def synthesis_target_keys() -> frozenset[str]:
    """Return a frozenset of valid synthesis-target keys."""
    data = load_synthesis_target_taxonomy()
    return frozenset(data["keys"].keys())


def validate_meta_task_type(value: str) -> None:
    """Validate that the given string is a known meta-task type."""
    valid_keys = meta_task_keys()
    if value not in valid_keys:
        raise UnknownTaxonomyKeyError(
            f"Unknown meta-task type '{value}'. Valid keys: {', '.join(sorted(valid_keys))}"
        )


def validate_synthesis_target_type(value: str) -> None:
    """Validate that the given string is a known synthesis-target type."""
    valid_keys = synthesis_target_keys()
    if value not in valid_keys:
        raise UnknownTaxonomyKeyError(
            f"Unknown synthesis-target type '{value}'. Valid keys: {', '.join(sorted(valid_keys))}"
        )
