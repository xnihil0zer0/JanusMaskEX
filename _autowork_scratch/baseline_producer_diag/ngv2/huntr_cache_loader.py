"""Real on-disk loader seam for huntr snapshots.

The pure decision libraries (``huntr_eligible_cache.check_eligible`` and
``huntr_data.parse_bounties`` / ``parse_existing_submissions``) consume
already-loaded data through injected seams; nothing in them opens files. This
module is the missing file-reading edge: it reads the static snapshots under
``data/ngv2/`` and feeds them to those pure libraries.

In particular ``load_cache`` is itself a valid zero-argument seam, so
``check_eligible(repo, load_cache=load_cache)`` works with no extra wiring.
"""
import json
from pathlib import Path
from typing import Any, Dict, Optional
_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / 'data' / 'ngv2'
ELIGIBLE_CACHE_FILE = 'huntr_eligible_cache.json'
REPO_BOUNTIES_FILE = 'huntr_repo_bounties.json'
EXISTING_SUBMISSIONS_FILE = 'huntr_existing_submissions.json'

def _resolve_data_dir(data_dir: Optional[Any]=None) -> Path:
    """Return ``Path(data_dir)`` when given, else the module default dir."""
    if data_dir is None:
        return _DEFAULT_DATA_DIR
    return Path(data_dir)

def _read_json(path: Path) -> Optional[Any]:
    """Open and parse ``path`` as JSON, returning None on any I/O or parse error."""
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None

def load_cache(data_dir: Optional[Any]=None) -> Optional[Dict[str, Any]]:
    """Read the eligible-cache snapshot.

    Returns the ``{'repos': [...], 'fetched_at': str}`` dict, or None when the
    file is missing/unreadable/malformed or its top-level value is not a dict.
    Usable directly as the zero-arg ``load_cache`` seam of ``check_eligible``.
    """
    data = _read_json(_resolve_data_dir(data_dir) / ELIGIBLE_CACHE_FILE)
    if isinstance(data, dict):
        return data
    return None

def load_repo_bounties(data_dir: Optional[Any]=None) -> Optional[Dict[str, Any]]:
    """Read the repo-bounties snapshot consumed by ``parse_bounties``.

    Returns the ``{'repos': {...}}`` dict, or None when missing/unreadable/
    malformed or its top-level value is not a dict.
    """
    data = _read_json(_resolve_data_dir(data_dir) / REPO_BOUNTIES_FILE)
    if isinstance(data, dict):
        return data
    return None

def load_existing_submissions(data_dir: Optional[Any]=None) -> Optional[Dict[str, Any]]:
    """Read the existing-submissions snapshot consumed by ``parse_existing_submissions``.

    Returns the dict, or None when missing/unreadable/malformed or its
    top-level value is not a dict.
    """
    data = _read_json(_resolve_data_dir(data_dir) / EXISTING_SUBMISSIONS_FILE)
    if isinstance(data, dict):
        return data
    return None