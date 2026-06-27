"""ngv2/sourcing/browser_fetcher.py -- injected live browser fetcher seam.

This leaf exposes the ``Fetcher`` seam (mirroring
``ngv2.sourcing.huntr_client``) plus three composition helpers:

* ``fetch_hacktivity`` -- a plain HTTP GET carrying the ``RSC: 1`` header for
  the bulk React Server Component hacktivity feed.
* ``fetch_repo_page`` -- the per-repo detail body; the Playwright path is
  reserved *only* for lazy-loaded detail content and is always bypassable via
  the injected fetcher so oracles stay offline. It never performs form-fill,
  click, or any HTTP POST -- findings are parked for a human only.
* ``fetch_bounties_index`` -- the server-rendered ``/bounties`` eligibility
  index, fetched as a plain GET *without* the RSC header.

The ``fetcher`` callable is always injected, so tests run fully hermetically
with no real network I/O.
"""
from __future__ import annotations
from typing import Callable, Mapping, Optional
Fetcher = Callable[[str, dict], 'tuple[int, str, dict]']
HUNTR_BASE = 'https://huntr.com'
HACKTIVITY_PATH = '/bounties/hacktivity'
BOUNTIES_PATH = '/bounties'
_RSC_HEADERS: dict = {'RSC': '1'}

def _request(fetcher: Fetcher, url: str, headers: Optional[Mapping[str, object]]=None) -> str:
    """Drive the injected fetcher and return the body on HTTP 200.

    A non-200 status raises ``RuntimeError`` so the caller's refresh loop can
    handle backoff rather than silently propagating a junk body. An empty or
    missing response-headers dict does not raise.
    """
    status, body, resp_headers = fetcher(url, dict(headers or {}))
    if resp_headers is None:
        resp_headers = {}
    if status != 200:
        raise RuntimeError('browser_fetcher: GET {0} returned HTTP {1}'.format(url, status))
    return body

def fetch_hacktivity(fetcher: Fetcher) -> str:
    """Issue an ``RSC: 1`` HTTP GET for the bulk hacktivity feed.

    Returns the response body string on HTTP 200; raises on any non-200.
    """
    url = HUNTR_BASE + HACKTIVITY_PATH
    return _request(fetcher, url, _RSC_HEADERS)

def fetch_repo_page(fetcher: Fetcher, owner: str, name: str) -> str:
    """Return the per-repo detail body via the injected fetcher.

    Bulk detail bodies are fetched with the same plain ``RSC: 1`` GET. The
    Playwright path is reserved solely for lazy-loaded detail content and is
    bypassed entirely here because the fetcher is injected -- no form-fill, no
    click, no POST.
    """
    url = '{0}/repos/{1}/{2}'.format(HUNTR_BASE, owner, name)
    return _request(fetcher, url, _RSC_HEADERS)

def fetch_bounties_index(fetcher: Fetcher) -> str:
    """Plain GET of the server-rendered ``/bounties`` eligibility index.

    The repo list on this page is NOT in the RSC flight payload, so this fetch
    deliberately omits the ``RSC`` header. Returns the body on HTTP 200; raises
    on any non-200.
    """
    url = HUNTR_BASE + BOUNTIES_PATH
    return _request(fetcher, url, {})