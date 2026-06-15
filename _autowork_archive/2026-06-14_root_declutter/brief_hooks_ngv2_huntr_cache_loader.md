---
interfaces: "ngv2/huntr_cache_loader.py (NEW single-file stdlib module): load_cache(data_dir=None) reads the on-disk data/ngv2/huntr_eligible_cache.json and returns the {'repos':[...], 'fetched_at':str} dict (or None) — directly usable as the zero-arg load_cache seam of huntr_eligible_cache.check_eligible; plus load_repo_bounties()/load_existing_submissions() feeding huntr_data.parse_bounties/parse_existing_submissions"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
meta_task_type: data_model
---

# Title

ngv2/huntr_cache_loader.py

# ⚠️ NEW FILE — WHOLE-FILE SUBMISSION REQUIRED

`ngv2/huntr_cache_loader.py` DOES NOT EXIST YET. Submit the COMPLETE file as a single self-contained Python module: module docstring, then ALL imports at the TOP (`json`, `from pathlib import Path`, `from typing import Any, Dict, Optional`), then the module-level constants and the function defs. Do NOT emit a `__JANUSMASK_PATCHES__` block, and do NOT bury imports inside function bodies — a symbol patch is ONLY for editing an existing file, and this file does not exist, so write the WHOLE module. Single file, this file ONLY.

# Scope

CREATE the NEW stdlib-only module `ngv2/huntr_cache_loader.py` in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). This is the missing file-reading edge: the pure decision libraries `ngv2/huntr_eligible_cache.py` (`check_eligible(owner_repo, load_cache=...)`) and `ngv2/huntr_data.py` (`parse_bounties`, `parse_existing_submissions`) take already-loaded data through INJECTED seams; nothing currently opens the on-disk snapshots. This module is the real `load_cache()`.

VERIFIED FACTS (do not deviate):
- The on-disk data lives at `<repo_root>/data/ngv2/` (NOT bare `data/`). The `ngv2/` package dir is at `<repo_root>/ngv2/`, so from THIS module the data dir is `Path(__file__).resolve().parent.parent / 'data' / 'ngv2'`.
- Files: `huntr_eligible_cache.json` (shape `{"repos":[...], "fetched_at":str}`), `huntr_repo_bounties.json` (shape `{"repos":{...}, ...}`), `huntr_existing_submissions.json`.
- `check_eligible`'s `load_cache` seam expects a callable returning either `{"repos":[...], "fetched_at":str}` or `None`. So `load_cache` (with its default `data_dir`) MUST itself be a valid zero-argument seam: `check_eligible(repo, load_cache=load_cache)` must work.

# Non-Goals

INTEGRATION is out of scope — this leaf is a pure stdlib file reader verified by its committed unit oracle alone; do NOT wire it into any pipeline/gate/scanner, do NOT modify `huntr_eligible_cache.py` or `huntr_data.py`, and author NO test (the oracle is pre-committed). No network. No global mutable state. No module-level side effects beyond defining the constants/functions. Touch no file other than `ngv2/huntr_cache_loader.py`.

# Inputs

The authoritative contract is the PRE-COMMITTED RED WIRING oracle `tests/test_huntr_cache_loader_wired.py` (committed on NGv2 master at `c2b1889`). It is a `*_wired` oracle: it proves the new module is reachable from a LIVE importer — `check_eligible(repo, load_cache=load_cache)` and `parse_bounties(load_repo_bounties())` both consume this loader through their injected seams. It asserts: `load_cache()` reproduces the on-disk eligible set; `check_eligible(repo, load_cache=load_cache)` returns the full known-eligible set; an explicit `data_dir=tmp_path` override is honored; missing-file and malformed-JSON both return `None`; `load_repo_bounties()` feeds `parse_bounties` to the on-disk repo count; `load_existing_submissions()` returns a dict. READ it as the source of truth and make it GREEN.

The EXACT validated module source (proven 9/9 GREEN against this oracle — emit VERBATIM as the whole file):

```python
"""Real on-disk loader for the huntr eligibility/bounty/submission snapshots.

The pure decision libraries (``huntr_eligible_cache.check_eligible``,
``huntr_data.parse_bounties`` / ``parse_existing_submissions``) consume
already-loaded JSON through injected seams; this module is the file-reading edge
that opens the static snapshots shipped under ``data/ngv2/``. ``load_cache`` (with
its default ``data_dir``) is itself a valid zero-argument seam usable directly as
``check_eligible(repo, load_cache=load_cache)``. Stdlib-only, deterministic; the
only I/O is reading the named JSON files. Missing / unreadable / malformed files
yield ``None`` (never raise).
"""
import json
from pathlib import Path
from typing import Any, Dict, Optional

_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / 'data' / 'ngv2'
ELIGIBLE_CACHE_FILE = 'huntr_eligible_cache.json'
REPO_BOUNTIES_FILE = 'huntr_repo_bounties.json'
EXISTING_SUBMISSIONS_FILE = 'huntr_existing_submissions.json'


def _resolve_data_dir(data_dir: Optional[Any] = None) -> Path:
    """Return the directory to read snapshots from (default: in-tree data/ngv2)."""
    if data_dir is not None:
        return Path(data_dir)
    return _DEFAULT_DATA_DIR


def _read_json(path: Path) -> Optional[Any]:
    """Read+parse a JSON file, returning ``None`` on any OS or decode error."""
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def load_cache(data_dir: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """Read the on-disk huntr eligible cache as the zero-arg seam check_eligible expects.

    Returns the dict ``{"repos": [...], "fetched_at": str}`` or ``None`` when the
    file is missing / unreadable / malformed / not a dict.
    """
    data = _read_json(_resolve_data_dir(data_dir) / ELIGIBLE_CACHE_FILE)
    if not isinstance(data, dict):
        return None
    return data


def load_repo_bounties(data_dir: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """Read huntr_repo_bounties.json (the ``{repos:{...}}`` shape parse_bounties consumes)."""
    data = _read_json(_resolve_data_dir(data_dir) / REPO_BOUNTIES_FILE)
    if not isinstance(data, dict):
        return None
    return data


def load_existing_submissions(data_dir: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """Read huntr_existing_submissions.json (consumed by parse_existing_submissions)."""
    data = _read_json(_resolve_data_dir(data_dir) / EXISTING_SUBMISSIONS_FILE)
    if not isinstance(data, dict):
        return None
    return data
```

# Required plan shape

Emit EXACTLY ONE impl task (do NOT decompose):
- meta_task_type: data_model
- files_touched: ["ngv2/huntr_cache_loader.py"] (this NEW file ONLY)
- WHOLE-FILE submission (new module) — NOT a `__JANUSMASK_PATCHES__` symbol patch.
- verification_command: `python -m pytest tests/test_huntr_cache_loader_wired.py -q`
  (this is the `*_wired` oracle that satisfies the new-module wiring requirement)
- spec_author: null — the oracle is pre-committed at NGv2 `c2b1889`; author NO test.
- non_goals MUST contain the literal word `integration`.
- test_spec MUST carry >=2 regression_tests reflecting the edge cases below.

# Deliverables

`ngv2/huntr_cache_loader.py` (new whole file), GREEN under `python -m pytest tests/test_huntr_cache_loader_wired.py -q`. Edge cases the oracle pins: `load_cache()` reproduces the on-disk eligible set and drives `check_eligible(repo, load_cache=load_cache)` to the full known-eligible set; explicit `data_dir=` override honored; missing-file → `None`; malformed JSON → `None`; `load_repo_bounties()` feeds `parse_bounties` to the on-disk repo count.
