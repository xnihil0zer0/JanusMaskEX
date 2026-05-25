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
    raise NotImplementedError

def meta_task_keys() -> frozenset[str]:
    """Return a frozenset of valid meta-task keys."""
    raise NotImplementedError

def synthesis_target_keys() -> frozenset[str]:
    """Return a frozenset of valid synthesis-target keys."""
    raise NotImplementedError

def validate_meta_task_type(value: str) -> None:
    """Validate that the given string is a known meta-task type."""
    raise NotImplementedError

def validate_synthesis_target_type(value: str) -> None:
    """Validate that the given string is a known synthesis-target type."""
    raise NotImplementedError
from harness.taxonomy import _load_taxonomy_file