---
dependencies: []
interfaces: "exposes `pin_permalink(url, sha) -> str` (rewrite /blob/main|master/ -> /blob/{sha}/), `extract_repo(url) -> str|None` (parse owner/repo from a GitHub blob URL), and `pin_and_verify(urls, sha_resolver, fetcher) -> dict` returning {\"pinned\": [...], \"dropped\": [...]} — pins each URL to its commit SHA via the injected sha_resolver, verifies with the injected fetcher (HTTP 200), and drops any citation whose pinned URL fails to resolve."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
verification_command: ".venv/bin/python -m pytest tests/ngv2/test_permalink_pin_wired.py -q"
---

# Title

P6.2 Permalink SHA-pinning — pin /blob/main|master/ -> /blob/{sha}/, verify 200, drop-on-404 (hermetic, injected fetcher)

# Scope

Build a new pure, stdlib-only module `ngv2/permalink_pin.py` porting the legacy `prepare_submissions.sh` permalink logic as a hermetic, injectable module: rewrite GitHub blob permalinks from a moving branch ref (`/blob/main/` or `/blob/master/`) to an immutable commit SHA (`/blob/{sha}/`), verify each pinned permalink resolves (HTTP 200) via an INJECTED `fetcher` seam, and DROP any citation whose pinned URL no longer resolves (cited code moved/removed). The SHA resolution is also an INJECTED `sha_resolver` seam (maps "owner/repo" -> commit SHA). All network access goes through the injected seams so oracles stay hermetic. The implementation below is VALIDATED (oracle proven green against it) — ship it VERBATIM as the whole file `ngv2/permalink_pin.py`.

# Non-Goals

Do NOT make real network/`gh`/`curl` calls in this module — fetch and sha-resolution are injected callables (keeps the oracle hermetic). No subprocess, LLM, wall-clock, or randomness. Do NOT render the submission document (that is P6.1). Do NOT perform eligibility/dedup (that is P6.3).

# Inputs

Two injected callables: `sha_resolver(owner_repo: str) -> Optional[str]` and `fetcher(url: str) -> int` (returns an HTTP status code). The committed RED oracle is `tests/ngv2/test_permalink_pin_wired.py`.

# Deliverables

New file `ngv2/permalink_pin.py` — ship this VALIDATED implementation verbatim:

```python
"""Permalink SHA-pinning for huntr submission packages (P6.2).

Ports the legacy ``prepare_submissions.sh`` logic as a hermetic, injectable
module: rewrite GitHub blob permalinks from a moving branch ref
(``/blob/main/`` or ``/blob/master/``) to an immutable commit SHA
(``/blob/{sha}/``), verify each pinned permalink resolves (HTTP 200), and
DROP any citation whose pinned URL no longer resolves (the cited code moved
or was removed).

All network access goes through an injected ``fetcher`` seam so oracles stay
hermetic. Standard library only.
"""
from __future__ import annotations
import re
from typing import Callable, List, Optional

# A fetcher takes a URL and returns an HTTP status code (int).
Fetcher = Callable[[str], int]

# A sha-resolver takes "owner/repo" and returns the pinned commit SHA (str).
ShaResolver = Callable[[str], Optional[str]]

_BRANCH_BLOB_RE = re.compile(
    r'(https://github\.com/[^/\s]+/[^/\s]+)/blob/(?:main|master)/')
_REPO_RE = re.compile(r'https://github\.com/([^/\s]+/[^/\s#)]+)/blob/')

__all__ = ['pin_permalink', 'pin_and_verify', 'extract_repo', 'Fetcher',
           'ShaResolver']


def extract_repo(url: str) -> Optional[str]:
    """Return ``owner/repo`` parsed from a GitHub blob URL, or None."""
    m = _REPO_RE.search(url or '')
    return m.group(1) if m else None


def pin_permalink(url: str, sha: str) -> str:
    """Rewrite a ``/blob/main|master/`` URL to ``/blob/{sha}/``.

    URLs already pinned to a SHA (or non-matching) are returned unchanged.
    """
    if not sha:
        return url
    return _BRANCH_BLOB_RE.sub(lambda m: f'{m.group(1)}/blob/{sha}/', url)


def pin_and_verify(urls: List[str], sha_resolver: ShaResolver,
                   fetcher: Fetcher) -> dict:
    """Pin each URL to a commit SHA and verify it resolves.

    Returns ``{"pinned": [...], "dropped": [...]}`` where ``pinned`` lists the
    SHA-pinned URLs that returned HTTP 200 and ``dropped`` lists the original
    URLs whose pinned form failed to resolve (non-200 / the cited code
    changed). Deterministic given deterministic ``sha_resolver``/``fetcher``.
    """
    pinned: List[str] = []
    dropped: List[str] = []
    for url in urls or []:
        repo = extract_repo(url)
        sha = sha_resolver(repo) if repo else None
        pinned_url = pin_permalink(url, sha) if sha else url
        try:
            status = fetcher(pinned_url)
        except Exception:
            status = 0
        if status == 200:
            pinned.append(pinned_url)
        else:
            dropped.append(url)
    return {'pinned': pinned, 'dropped': dropped}
```

Plus the already-committed RED oracle `tests/ngv2/test_permalink_pin_wired.py` (do not modify it).
