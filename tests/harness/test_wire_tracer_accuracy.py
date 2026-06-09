"""RED oracle for wire-up Wave-2 leaf A: import-tracer accuracy fix.

The Wave-1 sweep over-reported orphans because the underlying import graph could
not resolve three real wiring forms:
  1. ``from PACKAGE import SUBMODULE``  (e.g. orchestrator does ``from harness
     import agy_pool``; mcp_server does ``from harness.hooks.rpc import submit_code``;
     overseer/service does ``from overseer import turn_runner``).
  2. ``import a.b.c`` dotted-module imports.
  3. imports performed by a package ``__init__`` (a seed, excluded from the graph)
     — e.g. ``harness/narrow_fuzz/__init__`` does ``from harness.narrow_fuzz._registry
     import REGISTRY``.

Once ``check_wired`` / ``sweep_modules`` resolve these, the affected modules are
GENUINELY reachable from a live root (no new import is added — the edges already
exist in the source, the tracer just now sees them). This oracle asserts a
representative sample flips to WIRED while a genuinely-unwired residual and a
synthetic orphan stay ORPHAN (the fix is accurate, not over-broad). RED until the
augmentation lands.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from harness.wire_up import check_wired, discover_live_roots

REPO_ROOT = Path(__file__).resolve().parents[2]

# Formerly-false-positive modules that the resolved tracer must classify WIRED
# (each is reached from a live root via a real from-package-import / __init__ edge).
NOW_WIRED = [
    "harness/agy_pool.py",            # orchestrator/daemon: `from harness import agy_pool`
    "harness/control_gate.py",        # orchestrator: `from harness import control_gate`
    "harness/hooks/rpc/submit_code.py",  # mcp_server: `from harness.hooks.rpc import submit_code`
    "harness/hooks/rpc/clarification.py",
    "harness/rebuild/harvest.py",     # rebuild loop/job/task: `from harness.rebuild import harvest`
    "harness/rebuild/venv.py",
    "harness/narrow_fuzz/_registry.py",  # narrow_fuzz/__init__: `from harness.narrow_fuzz._registry import REGISTRY`
    "harness/narrow_fuzz/validation.py", # _registry: `from harness.narrow_fuzz import validation`
    "overseer/service.py",            # tools/webui_control (via tools/webui_server root)
    "overseer/turn_runner.py",        # overseer/service: `from overseer import turn_runner`
    "overseer/driver.py",
    "overseer/gate_runner.py",
    "overseer/mode_gate.py",
]

# Genuinely-unwired residual: imported only by tests (config_loader, oracle_attach)
# or a dead duplicate (tools/brief_status) — MUST stay ORPHAN after the fix.
STILL_ORPHAN = [
    "harness/config_loader.py",
    "harness/planner/oracle_attach.py",
    "tools/brief_status.py",
]


@pytest.fixture(scope="module")
def roots():
    return discover_live_roots(REPO_ROOT)


@pytest.mark.parametrize("module_rel", NOW_WIRED)
def test_resolved_tracer_classifies_real_wiring_as_wired(module_rel, roots):
    result = check_wired(REPO_ROOT, module_rel, roots=roots)
    assert result.wired is True, f"{module_rel} should be WIRED via its real import edge: {result.reason}"


@pytest.mark.parametrize("module_rel", STILL_ORPHAN)
def test_genuinely_unwired_stays_orphan(module_rel, roots):
    result = check_wired(REPO_ROOT, module_rel, roots=roots)
    assert result.wired is False, f"{module_rel} has no live importer and must stay ORPHAN: {result.reason}"


def test_synthetic_orphan_still_orphan(tmp_path):
    (tmp_path / "root.py").write_text("import wired_mod\n")
    (tmp_path / "wired_mod.py").write_text("x = 1\n")
    (tmp_path / "orphan.py").write_text("y = 2\n")
    assert check_wired(tmp_path, "orphan.py", roots=["root.py"]).wired is False


def test_from_package_import_submodule_edge_resolves(tmp_path):
    # The core new capability, hermetically: a package submodule imported via
    # `from pkg import sub` from a reachable root is WIRED.
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "sub.py").write_text("z = 1\n")
    (tmp_path / "root.py").write_text("from pkg import sub\n")
    assert check_wired(tmp_path, "pkg/sub.py", roots=["root.py"]).wired is True
