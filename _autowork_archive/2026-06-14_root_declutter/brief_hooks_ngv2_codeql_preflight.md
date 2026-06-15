---
interfaces: "creates NEW ngv2/codeql_preflight.py exposing preflight(target, fetcher)->PreflightResult, parse_github_repo, is_osi_approved, make_pass_token, verify_pass_token, require_authorization, PreflightResult, OSI_APPROVED_LICENSES, TOKEN_PREFIX — the FAIL-CLOSED license/host gate that every CodeQL-running path must pass before a DB build"
dependencies: []
meta_task_type: data_model
spec_author: "Phase-III BUILD-PREP agent (JanusMask)"
spec_reviewed_by: "owner (CodeQL CLI use APPROVED 2026-06-12)"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/codeql_preflight.py — NEW FAIL-CLOSED CodeQL license/host preflight gate (OWNER CONDITION): authorize CodeQL only for GitHub-hosted repos carrying an OSI-approved license, via an injected GitHub-license fetcher seam, issuing a verifiable pass token; refuse everything else.

# Scope

CREATE the NEW single-file module `ngv2/codeql_preflight.py` (NGv2 external-target task — `working_dir` = /home/xnihil0zer0/NobleGreedv2). This is the owner-mandated gate that sequences FIRST in the Phase-III cascade: the CodeQL CLI is free for OSS-on-GitHub analysis, so before any database is built we must prove the target is GitHub-hosted AND OSI-licensed. The module is PURE and stdlib-only (`re`, `dataclasses`, `typing`): no network, clock, randomness, subprocess, or third-party import. The single external effect — the GitHub `GET /repos/{owner}/{repo}/license` lookup — is abstracted behind an injected `fetcher(owner, repo)->dict` seam (live path wraps `gh api`; oracle injects a double). It FAILS CLOSED: a non-GitHub host, a fetch error, a missing/NOASSERTION/other license, or any SPDX id outside the OSI allowlist all yield an unauthorized result with `token=None`. A clean pass returns a deterministic, self-describing pass token that `verify_pass_token` accepts only for that exact owner/repo and re-checks against the OSI allowlist.

DISPATCH DIRECTIVE — PATCH FORMAT (MANDATORY — WHOLE-FILE): this is a NEW single-file module, so emit the COMPLETE file for `ngv2/codeql_preflight.py` (whole-file emission — NEVER a `__JANUSMASK_PATCHES__` symbol patch, never a manifest, never a dotted qualname). Reproduce it BYTE-FOR-BYTE exactly as follows:

```python
"""ngv2.codeql_preflight -- FAIL-CLOSED CodeQL license/host preflight gate.

The owner condition for running CodeQL: every CodeQL-executing code path must
first prove that the target repository is **GitHub-hosted** AND carries an
**OSI-approved open-source license**. CodeQL CLI is licensed free for analysis
of "any Open Source Codebase hosted and maintained on GitHub.com"; a target that
is not GitHub-hosted, or whose license is unknown / source-available / NOASSERTION
/ BUSL / SSPL / Elastic, is **refused** -- the gate fails CLOSED.

This module is PURE and stdlib-only. The single external effect -- the GitHub
license API lookup -- is abstracted behind an injected ``fetcher`` seam::

    fetcher(owner, repo) -> dict | None

returning the GitHub ``GET /repos/{owner}/{repo}/license`` JSON shape
(``{"license": {"spdx_id": "MIT", ...}}``); the live path wraps a ``gh api`` /
HTTPS call, the oracle injects a scripted double. The module never spawns a
process, opens a socket, consults a clock, or imports a third-party package.

A successful preflight returns a deterministic, self-describing *pass token*.
Downstream CodeQL entry points (``codeql_orchestrate.analyze_repo``) require a
token that ``verify_pass_token`` accepts for that exact owner/repo, so an
unlicensed target can never reach a CodeQL DB build.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any, Optional, Tuple

__all__ = [
    'OSI_APPROVED_LICENSES', 'REFUSED_LICENSES', 'GITHUB_HOSTS', 'TOKEN_PREFIX',
    'PreflightResult', 'parse_github_repo', 'is_osi_approved',
    'make_pass_token', 'verify_pass_token', 'preflight', 'require_authorization',
]

# OSI-approved SPDX identifiers we accept (lowercased for case-insensitive
# matching). Conservative, common-in-corpus set; extend deliberately.
OSI_APPROVED_LICENSES = frozenset({
    'mit', 'apache-2.0', 'bsd-2-clause', 'bsd-3-clause', 'isc', 'mpl-2.0',
    'gpl-2.0', 'gpl-2.0-only', 'gpl-2.0-or-later', 'gpl-3.0', 'gpl-3.0-only',
    'gpl-3.0-or-later', 'lgpl-2.1', 'lgpl-2.1-only', 'lgpl-2.1-or-later',
    'lgpl-3.0', 'lgpl-3.0-only', 'lgpl-3.0-or-later', 'agpl-3.0',
    'agpl-3.0-only', 'agpl-3.0-or-later', 'epl-2.0', 'unlicense', 'bsl-1.0',
    'zlib', 'ncsa', 'python-2.0', 'psf-2.0', 'artistic-2.0',
})
# Known source-available / non-OSI identifiers, surfaced for a precise refusal
# reason. NB: refusal does not depend on this list -- anything not in
# OSI_APPROVED_LICENSES is refused (fail closed); this only sharpens the message.
REFUSED_LICENSES = frozenset({
    'busl-1.1', 'sspl-1.0', 'elastic-2.0', 'elastic-license-2.0', 'commons-clause',
    'noassociation', 'noassertion', 'other', 'proprietary', 'unknown',
})
GITHUB_HOSTS = frozenset({'github.com', 'www.github.com'})
TOKEN_PREFIX = 'CODEQL-PREFLIGHT-OK'

# owner/repo from a github URL or a bare "owner/repo" full_name.
_URL_RE = re.compile(
    r'(?:https?://|git@)?(?:www\.)?github\.com[/:]+'
    r'(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$'
)
_FULLNAME_RE = re.compile(r'^(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)$')
_REPO_FIELDS = ('html_url', 'repo_url', 'clone_url', 'url', 'full_name',
                'github', 'repo', 'repository')


@dataclass(frozen=True)
class PreflightResult:
    """Outcome of a license/host preflight. ``authorized`` gates CodeQL."""
    authorized: bool
    token: Optional[str] = None
    reason: str = ''
    owner: Optional[str] = None
    repo: Optional[str] = None
    spdx: Optional[str] = None


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def parse_github_repo(target: Any) -> Optional[Tuple[str, str]]:
    """Extract ``(owner, repo)`` from a GitHub-hosted target, else ``None``.

    Accepts a bare URL string, a ``owner/repo`` full-name string, or a Target
    dict/object carrying one of those in a recognised field. A non-GitHub host
    (gitlab, bitbucket, a local path) returns ``None`` -> the gate refuses.
    """
    candidates = []
    if isinstance(target, str):
        candidates.append(target)
    else:
        for field_name in _REPO_FIELDS:
            value = _get(target, field_name)
            if isinstance(value, str) and value:
                candidates.append(value)
    for raw in candidates:
        text = raw.strip()
        match = _URL_RE.search(text)
        if match:
            return (match.group('owner'), match.group('repo'))
        # only treat a bare "owner/repo" as github when no other host is present
        if '://' not in text and '@' not in text and 'github.com' not in text:
            fn = _FULLNAME_RE.match(text)
            if fn:
                return (fn.group('owner'), fn.group('repo'))
    return None


def is_osi_approved(spdx_id: Any) -> bool:
    """True iff ``spdx_id`` names an OSI-approved license (fail closed).

    ``None``, empty, ``NOASSERTION``/``other``, and any id outside
    :data:`OSI_APPROVED_LICENSES` all return ``False``.
    """
    if not isinstance(spdx_id, str) or not spdx_id.strip():
        return False
    return spdx_id.strip().lower() in OSI_APPROVED_LICENSES


def make_pass_token(owner: str, repo: str, spdx: str) -> str:
    """Build the deterministic, self-describing CodeQL pass token."""
    return '%s|%s/%s|%s' % (TOKEN_PREFIX, owner, repo, str(spdx).strip().lower())


def verify_pass_token(token: Any, owner: str, repo: str) -> bool:
    """True iff ``token`` authorises CodeQL for exactly ``owner/repo``.

    Fail closed: a non-string, wrong-prefix, or owner/repo-mismatched token is
    rejected. The SPDX trailer is re-checked against the OSI allowlist so a
    hand-forged token naming a refused license cannot pass.
    """
    if not isinstance(token, str) or not token:
        return False
    parts = token.split('|')
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        return False
    if parts[1] != '%s/%s' % (owner, repo):
        return False
    return is_osi_approved(parts[2])


def _extract_spdx(license_response: Any) -> Optional[str]:
    """Pull the SPDX id from a GitHub license-API response, tolerantly."""
    lic = _get(license_response, 'license', None)
    if lic is None and isinstance(license_response, dict):
        lic = license_response  # caller may pass the inner license object
    spdx = _get(lic, 'spdx_id', None)
    if spdx is None:
        spdx = _get(license_response, 'spdx_id', None)
    return spdx if isinstance(spdx, str) else None


def preflight(target: Any, fetcher) -> PreflightResult:
    """Authorise (or refuse) CodeQL for ``target`` -- FAIL CLOSED.

    Steps: (1) the target must be GitHub-hosted (``parse_github_repo``);
    (2) ``fetcher(owner, repo)`` must return the license response without error;
    (3) the resolved SPDX id must be OSI-approved. Any failure yields an
    unauthorised result with ``token=None`` and a human reason. Only a clean
    pass returns a verifiable token.
    """
    parsed = parse_github_repo(target)
    if parsed is None:
        return PreflightResult(False, None, 'target is not GitHub-hosted')
    owner, repo = parsed
    try:
        response = fetcher(owner, repo)
    except Exception as exc:  # fail closed on any fetch error
        return PreflightResult(False, None, 'license fetch failed: %s' % exc,
                               owner=owner, repo=repo)
    if response is None:
        return PreflightResult(False, None, 'license fetch returned no data',
                               owner=owner, repo=repo)
    spdx = _extract_spdx(response)
    if spdx is None:
        return PreflightResult(False, None, 'no SPDX license id in response',
                               owner=owner, repo=repo)
    if not is_osi_approved(spdx):
        norm = spdx.strip().lower()
        kind = 'source-available/non-OSI' if norm in REFUSED_LICENSES else 'not OSI-approved'
        return PreflightResult(False, None,
                               'license %r is %s' % (spdx, kind),
                               owner=owner, repo=repo, spdx=spdx)
    token = make_pass_token(owner, repo, spdx)
    return PreflightResult(True, token, 'authorized', owner=owner, repo=repo, spdx=spdx)


def require_authorization(target: Any, fetcher) -> str:
    """Return a verified pass token for ``target`` or raise ``PermissionError``.

    Convenience for CodeQL entry points that want to hard-stop on refusal
    rather than branch on a result object.
    """
    result = preflight(target, fetcher)
    if not result.authorized or result.token is None:
        raise PermissionError('CodeQL preflight refused: ' + result.reason)
    return result.token
```

POST-EMIT SELF-CHECK (mandatory): the emitted module imports only `re`/`dataclasses`/`typing`; `preflight` returns `authorized=False, token=None` for every refusal branch; `verify_pass_token` re-checks the SPDX trailer against the OSI allowlist; no network/clock/subprocess import is present.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle is keyed to it): `task_id`: `ngv2_codeql_preflight`. meta_task_type=`data_model` (NEW pure module — single-file whole-file emission, no production-harness edit). priority: high. dependencies: []. working_dir: "/home/xnihil0zer0/NobleGreedv2". files_touched: `["ngv2/codeql_preflight.py"]` ONLY. partial_edit semantics: WHOLE-FILE single-file emission per the DISPATCH DIRECTIVE — the DISPATCH DIRECTIVE block above (including the full pinned file content) MUST be copied VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python3 -m pytest -q tests/ngv2/test_codeql_preflight_wired.py` (CWD-relative — NO `cd`). The committed RED oracle tests/ngv2/test_codeql_preflight_wired.py is the authoritative acceptance contract — make it GREEN (10 tests); do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries naming committed oracle cases: `test_preflight_authorizes_osi_github_repo_and_issues_token`, `test_preflight_refuses_source_available_license`. `test_spec.edge_cases` (≥2, reflected in those test names): `test_preflight_fails_closed_on_fetch_error`, `test_preflight_fails_closed_on_missing_or_noassertion_license`, `test_require_authorization_raises_for_refused_target` — including the integration-style case `test_require_authorization_raises_for_refused_target`.

# Non-Goals

Do NOT perform the real `gh api` / network call — the fetcher is injected. Do NOT touch any other module. Do NOT add a crypto-signed token (the structural CODEQL-PREFLIGHT-OK token is sufficient and must stay offline-deterministic). Do NOT widen the OSI allowlist beyond the pinned set. Do NOT add logging, clock, randomness, or subprocess. The downstream wiring that makes CodeQL entry points REQUIRE this token (codeql_orchestrate.analyze_repo) is a separate leaf — this brief ships only the gate.

# Inputs

The committed authoritative oracle tests/ngv2/test_codeql_preflight_wired.py (currently RED — module absent). It pins: host parsing of github URLs / git@ / owner-repo / dict targets and rejection of gitlab/bitbucket/local paths; the OSI allowlist (MIT/Apache-2.0/AGPL-3.0 accepted; NOASSERTION/other/BUSL-1.1/SSPL-1.0/None/'' refused); authorize+token round-trip; token forgery rejection (a token naming a refused license must not verify); fail-closed refusals (non-GitHub, source-available, fetch error, missing license); and the integration-style enforcement seam require_authorization raising PermissionError for a refused target while returning a verifiable token for an OSI repo.

# Deliverables

The NEW file `ngv2/codeql_preflight.py` exactly as pinned in the DISPATCH DIRECTIVE, verified GREEN by `python3 -m pytest -q tests/ngv2/test_codeql_preflight_wired.py` (10 passed).
