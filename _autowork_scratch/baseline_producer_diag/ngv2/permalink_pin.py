"""SHA-pinning of GitHub blob permalinks (ngv2/permalink_pin.py, P6.2).

Pure, stdlib-only, hermetic port of the legacy ``prepare_submissions.sh``
permalink logic: rewrite GitHub blob permalinks from a moving branch ref
(``/blob/main/`` or ``/blob/master/``) to an immutable commit SHA
(``/blob/{sha}/``), verify each pinned permalink resolves (HTTP 200) via an
INJECTED fetcher seam, and DROP any citation whose pinned URL no longer
resolves. SHA resolution is likewise an INJECTED sha_resolver seam
(``owner/repo`` -> commit SHA).

The module performs NO real network/subprocess/gh/curl/LLM/wall-clock/
randomness; all external access flows through the injected callables.
"""
from __future__ import annotations
import re
from typing import Callable, Dict, List, Optional
Fetcher = Callable[[str], int]
ShaResolver = Callable[[str], Optional[str]]
_BRANCH_BLOB_RE = re.compile('(github\\.com/[^/]+/[^/]+)/blob/(?:main|master)/')
_REPO_RE = re.compile('github\\.com/([^/]+/[^/]+)/blob/')
__all__ = ['pin_permalink', 'pin_and_verify', 'extract_repo', 'Fetcher', 'ShaResolver']

def extract_repo(url: str) -> Optional[str]:
    """Return 'owner/repo' parsed from a GitHub blob URL, or None."""
    match = _REPO_RE.search(url or '')
    return match.group(1) if match else None

def pin_permalink(url: str, sha: str) -> str:
    """Rewrite /blob/main|master/ to /blob/{sha}/.

    Returns the URL unchanged when ``sha`` is falsy or the URL does not match
    a moving branch ref (e.g. it is already pinned to a SHA).
    """
    if not sha:
        return url
    return _BRANCH_BLOB_RE.sub('\\1/blob/' + sha + '/', url)

def pin_and_verify(urls: Optional[List[str]], sha_resolver: ShaResolver, fetcher: Fetcher) -> Dict[str, List[str]]:
    """Pin each URL to its repo's SHA and verify the pinned URL.

    Returns ``{'pinned': [...], 'dropped': [...]}``: HTTP 200 results go to
    ``pinned`` (the SHA-pinned URL); all other statuses (including a fetcher
    exception, treated as status 0) drop the original URL.
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