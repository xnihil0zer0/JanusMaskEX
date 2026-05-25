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

def _load_taxonomy_file(file_name: str, path: Path | None=None) -> dict:
    raise NotImplementedError

def load_meta_task_taxonomy(path: Path | None=None) -> dict:
    """Load and validate the meta-task taxonomy JSON file."""
    return _load_taxonomy_file('meta_task_taxonomy.json', path)

def load_synthesis_target_taxonomy(path: Path | None=None) -> dict:
    """Load and validate the synthesis-target taxonomy JSON file."""
    return _load_taxonomy_file('synthesis_target_taxonomy.json', path)

def meta_task_keys() -> frozenset[str]:
    """Return a frozenset of valid meta-task keys."""
    raise NotImplementedError

def synthesis_target_keys() -> frozenset[str]:
    """Return a frozenset of valid synthesis-target keys."""
    data = load_synthesis_target_taxonomy()
    return frozenset(data['keys'].keys())

def validate_meta_task_type(value: str) -> None:
    """Validate that the given string is a known meta-task type."""
    raise NotImplementedError

def validate_synthesis_target_type(value: str) -> None:
    """Validate that the given string is a known synthesis-target type."""
    valid_keys = synthesis_target_keys()
    if value not in valid_keys:
        raise UnknownTaxonomyKeyError(f"Unknown synthesis-target type '{value}'. Valid keys: {', '.join(sorted(valid_keys))}")
from harness.taxonomy import _load_taxonomy_file
from harness.taxonomy import load_synthesis_target_taxonomy
from harness.taxonomy import UnknownTaxonomyKeyError