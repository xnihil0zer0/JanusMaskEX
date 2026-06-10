"""RED oracle — authoritative contract for autocompiler/js/node_version.py (leaf ac-js-node-version).

Contract: pure resolution of the EXACT pinned Node binary under an nvm tree —
the only path Phase D will ever bind into the agent jail (never the global
``~/.nvm``). Stdlib-only, no filesystem access required (existence checks are
the caller's concern), no spawn. Exposes:

- ``validate_node_version(version) -> bool`` — True ONLY for a full match of
  ``^v\\d+\\.\\d+\\.\\d+$`` on a str. Aliases (``lts/*``), partials, prefixes,
  whitespace, or any path-ish content => False. Never raises.
- ``parse_nvmrc(content) -> str | None`` — strips surrounding whitespace from
  an ``.nvmrc`` body and returns the version iff it validates, else None
  (an escaping/alias/garbage ``.nvmrc`` must NEVER come back as a path
  component). Never raises.
- ``resolve_node_bin(nvm_dir, version) -> str | None`` — exactly
  ``<nvm_dir>/versions/node/<version>/bin/node`` when ``version`` validates
  AND the joined result still normalizes to a path UNDER ``nvm_dir``
  (safe_subpath-style); else None. Never raises.
"""
import os

import pytest

from autocompiler.js.node_version import (
    parse_nvmrc,
    resolve_node_bin,
    validate_node_version,
)


def test_exact_semver_validates():
    assert validate_node_version('v22.17.0') is True
    assert validate_node_version('v0.0.0') is True


def test_non_conforming_versions_rejected():
    for bad in ('22.17.0', 'v22.17', 'v22.17.0-rc1', 'lts/iron', 'v22.17.0 ',
                ' v22.17.0', 'v22.17.0\n', '', 'vv22.17.0', 'v22.17.0.1'):
        assert validate_node_version(bad) is False, bad


def test_path_escaping_versions_rejected():
    # Regression: a version string must never smuggle path components.
    for bad in ('../v22.17.0', 'v22.17.0/../..', 'v22.17.0/..', '..', '/etc',
                'v22.17.0/bin', 'v1.2.3\\..\\..'):
        assert validate_node_version(bad) is False, bad


def test_garbage_inputs_never_raise():
    for bad in (None, 42, b'v22.17.0', ['v22.17.0'], object()):
        assert validate_node_version(bad) is False
    assert parse_nvmrc(None) is None
    assert parse_nvmrc(123) is None


def test_parse_nvmrc_strips_and_validates():
    assert parse_nvmrc('v22.17.0\n') == 'v22.17.0'
    assert parse_nvmrc('  v22.17.0  ') == 'v22.17.0'
    assert parse_nvmrc('lts/iron\n') is None
    assert parse_nvmrc('../../../etc/passwd') is None
    assert parse_nvmrc('') is None


def test_resolve_exact_subpath():
    out = resolve_node_bin('/home/u/.nvm', 'v22.17.0')
    assert out == os.path.join('/home/u/.nvm', 'versions', 'node', 'v22.17.0', 'bin', 'node')


def test_resolve_rejects_invalid_version():
    assert resolve_node_bin('/home/u/.nvm', 'lts/iron') is None
    assert resolve_node_bin('/home/u/.nvm', 'v22.17.0/../../..') is None
    assert resolve_node_bin('/home/u/.nvm', '') is None


def test_resolve_result_always_under_nvm_dir():
    # Property: any accepted resolution normalizes to a strict subpath of nvm_dir.
    for version in ('v1.0.0', 'v22.17.0', 'v999.999.999'):
        out = resolve_node_bin('/opt/nvm', version)
        assert out is not None
        norm = os.path.normpath(out)
        assert norm.startswith(os.path.normpath('/opt/nvm') + os.sep)
        assert '..' not in norm.split(os.sep)
