"""RED oracle for ngv2.codeql_preflight -- the FAIL-CLOSED CodeQL license/host
preflight gate (owner condition: CodeQL runs only on OSI-licensed, GitHub-hosted
repos).

Pure, stdlib-only, offline: the GitHub license API is an injected ``fetcher``
seam, so nothing here touches the network. Covers host parsing, the OSI
allowlist, fail-closed refusals (non-GitHub host, fetch error, NOASSERTION,
BUSL/SSPL source-available), token issue+verify, and an integration-style case
proving a refused target yields no usable CodeQL token.
"""
import pytest

from ngv2.codeql_preflight import (
    preflight,
    parse_github_repo,
    is_osi_approved,
    make_pass_token,
    verify_pass_token,
    require_authorization,
    PreflightResult,
    OSI_APPROVED_LICENSES,
    TOKEN_PREFIX,
)


def _fetcher(spdx):
    """A scripted GitHub license-API double returning a fixed SPDX id."""
    def fetch(owner, repo):
        return {'license': {'spdx_id': spdx, 'key': str(spdx).lower()}}
    return fetch


def _raising_fetcher(owner=None, repo=None):
    def fetch(owner, repo):
        raise RuntimeError('gh api 404')
    return fetch


# --- host parsing -----------------------------------------------------------
def test_parse_github_repo_from_url_and_fullname():
    assert parse_github_repo('https://github.com/comfyanonymous/ComfyUI') == (
        'comfyanonymous', 'ComfyUI')
    assert parse_github_repo('git@github.com:bentoml/BentoML.git') == (
        'bentoml', 'BentoML')
    assert parse_github_repo('bentoml/BentoML') == ('bentoml', 'BentoML')
    assert parse_github_repo({'clone_url': 'https://github.com/wandb/wandb.git'}) == (
        'wandb', 'wandb')


def test_parse_github_repo_rejects_non_github_hosts():
    assert parse_github_repo('https://gitlab.com/foo/bar') is None
    assert parse_github_repo('https://bitbucket.org/foo/bar') is None
    assert parse_github_repo('/home/user/local/clone') is None
    assert parse_github_repo({'url': 'https://example.com/x/y'}) is None


# --- OSI allowlist ----------------------------------------------------------
def test_is_osi_approved_allowlist_and_fail_closed():
    assert is_osi_approved('MIT') is True
    assert is_osi_approved('Apache-2.0') is True
    assert is_osi_approved('agpl-3.0') is True
    # fail closed
    assert is_osi_approved('NOASSERTION') is False
    assert is_osi_approved('other') is False
    assert is_osi_approved('BUSL-1.1') is False
    assert is_osi_approved('SSPL-1.0') is False
    assert is_osi_approved(None) is False
    assert is_osi_approved('') is False
    assert 'mit' in OSI_APPROVED_LICENSES


# --- happy path: authorize + token round-trip -------------------------------
def test_preflight_authorizes_osi_github_repo_and_issues_token():
    res = preflight('https://github.com/bentoml/BentoML', _fetcher('Apache-2.0'))
    assert isinstance(res, PreflightResult)
    assert res.authorized is True
    assert res.owner == 'bentoml' and res.repo == 'BentoML'
    assert res.spdx == 'Apache-2.0'
    assert isinstance(res.token, str) and res.token.startswith(TOKEN_PREFIX)
    # token verifies for this exact repo only
    assert verify_pass_token(res.token, 'bentoml', 'BentoML') is True
    assert verify_pass_token(res.token, 'someone', 'else') is False


def test_make_and_verify_pass_token():
    tok = make_pass_token('wandb', 'wandb', 'MIT')
    assert verify_pass_token(tok, 'wandb', 'wandb') is True
    # a forged token naming a refused license must not verify
    forged = '%s|%s/%s|%s' % (TOKEN_PREFIX, 'wandb', 'wandb', 'busl-1.1')
    assert verify_pass_token(forged, 'wandb', 'wandb') is False
    assert verify_pass_token('garbage', 'wandb', 'wandb') is False
    assert verify_pass_token(None, 'wandb', 'wandb') is False


# --- fail-closed refusals ---------------------------------------------------
def test_preflight_refuses_non_github_target():
    res = preflight('https://gitlab.com/foo/bar', _fetcher('MIT'))
    assert res.authorized is False
    assert res.token is None
    assert 'github' in res.reason.lower()


def test_preflight_refuses_source_available_license():
    res = preflight('https://github.com/foo/bar', _fetcher('BUSL-1.1'))
    assert res.authorized is False
    assert res.token is None
    assert 'busl' in res.reason.lower() or 'source-available' in res.reason.lower()


def test_preflight_fails_closed_on_fetch_error():
    res = preflight('https://github.com/foo/bar', _raising_fetcher())
    assert res.authorized is False
    assert res.token is None


def test_preflight_fails_closed_on_missing_or_noassertion_license():
    assert preflight('github.com/foo/bar', _fetcher('NOASSERTION')).authorized is False
    assert preflight('foo/bar', lambda o, r: {'license': None}).authorized is False
    assert preflight('foo/bar', lambda o, r: None).authorized is False


# --- integration-style: enforcement seam ------------------------------------
def test_require_authorization_raises_for_refused_target():
    # a CodeQL entry point that demands a token gets a hard stop on refusal
    with pytest.raises(PermissionError):
        require_authorization('https://github.com/foo/bar', _fetcher('SSPL-1.0'))
    # and a clean token for an OSI repo
    tok = require_authorization('foo/bar', _fetcher('MIT'))
    assert verify_pass_token(tok, 'foo', 'bar') is True
