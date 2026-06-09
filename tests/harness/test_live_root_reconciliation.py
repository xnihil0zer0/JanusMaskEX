"""RED oracle for wire-up-sweep leaf 1: live-root reconciliation.

`harness/wire_up.py` ships a STALE `LIVE_ROOTS` constant: the real per-event
hook entrypoints are registered by name in `config/**` (e.g. the command
``python3 -m harness.hooks.claude.pre_tool``), `harness/hook_pre_tool.py`, and
``-m harness.mcp_server``. Because those entrypoints are absent from the seed
set, the entire hooks subsystem reports ORPHAN even though, for example,
``harness/hooks/_paths.py`` has 15 inbound importers.

This oracle asserts the new ``discover_live_roots(repo_root) -> list[str]``
reconciles the root set from ground truth so the false positive is cured, while
remaining selective (it adds entrypoints, not internals) and still flagging a
genuine orphan. It is RED until ``discover_live_roots`` exists.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# RED until leaf 1 adds discover_live_roots to harness/wire_up.py.
from harness.wire_up import LIVE_ROOTS, check_wired, discover_live_roots

REPO_ROOT = Path(__file__).resolve().parents[2]

# Real hook/entrypoint modules registered by NAME in config/** that the shipped
# LIVE_ROOTS omits. These MUST be reconciled in as live roots.
EXPECTED_ENTRYPOINTS = [
    "harness/hooks/claude/pre_tool.py",
    "harness/mcp_server.py",
    "harness/hook_pre_tool.py",
]

# Internal modules that are NOT entrypoints and must NOT be promoted to roots
# (reconciliation adds entrypoints, it does not flag everything as a root).
NON_ROOT_INTERNALS = [
    "harness/wire_up.py",
    "harness/hooks/_paths.py",
]


def test_discover_live_roots_returns_str_list_superset_of_shipped():
    roots = discover_live_roots(REPO_ROOT)
    assert isinstance(roots, list)
    assert all(isinstance(r, str) for r in roots)
    # Reconciliation UNIONS with the shipped roots; it never drops them.
    shipped_present = {r for r in LIVE_ROOTS if (REPO_ROOT / r).is_file()}
    assert shipped_present <= set(roots)


@pytest.mark.parametrize("entry", EXPECTED_ENTRYPOINTS)
def test_config_hook_entrypoints_are_reconciled_as_roots(entry):
    roots = set(discover_live_roots(REPO_ROOT))
    assert entry in roots, f"{entry} (a config-registered entrypoint) must be a reconciled live root"


@pytest.mark.parametrize("internal", NON_ROOT_INTERNALS)
def test_internal_modules_are_not_promoted_to_roots(internal):
    roots = set(discover_live_roots(REPO_ROOT))
    assert internal not in roots, f"{internal} is an internal module, not an entrypoint; must not be a root"


def test_paths_helper_classifies_wired_under_reconciled_roots():
    # The proven false positive: harness/hooks/_paths.py has 15 inbound
    # importers yet reports ORPHAN under the stale shipped roots. Under the
    # reconciled roots it MUST classify WIRED.
    roots = discover_live_roots(REPO_ROOT)
    result = check_wired(REPO_ROOT, "harness/hooks/_paths.py", roots=roots)
    assert result.wired is True, result.reason
    assert result.importers, "expected at least one reachable live importer"


def test_reconciliation_still_flags_a_genuine_orphan(tmp_path):
    # Seeding more roots must not launder real orphans: a module no root reaches
    # is still ORPHAN.
    (tmp_path / "root.py").write_text("import wired_mod\n")
    (tmp_path / "wired_mod.py").write_text("x = 1\n")
    (tmp_path / "orphan.py").write_text("y = 2\n")
    result = check_wired(tmp_path, "orphan.py", roots=["root.py"])
    assert result.wired is False
    assert "orphan" in result.reason.lower()
