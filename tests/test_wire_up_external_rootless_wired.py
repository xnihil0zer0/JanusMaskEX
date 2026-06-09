"""RED oracle for the external/rootless repo-aware reconcile in ``check_wired``
(harness_self_fix: wire_up_external_rootless).

Contract: ``harness.wire_up.check_wired`` decides whether a NEW module is WIRED =
reachable, via the intra-project import graph, from a *live entrypoint root*. Its
default ``roots`` are the JM-specific ``LIVE_ROOTS`` (``harness/orchestrator.py`` …).
For a FOREIGN / clean-room target tree (e.g. NobleGreedv2) NONE of those roots
exist, so ``seeded_roots`` is empty and EVERY module -- even one imported by eight
peers -- is reported ``wired=False``. That makes the accept-time wire-up gate
structurally unsatisfiable for any external rootless toolkit.

The fix makes ``check_wired`` repo-aware: when none of the passed roots exist in the
target tree, it reconciles the live-root seed from ground truth via
``discover_live_roots(repo_root)``; and for a genuinely ROOTLESS toolkit (no
entrypoint root at all) the "reachable from a live root" model is INAPPLICABLE, so
the gate no-ops -- the module is reported ``wired=True`` rather than a false-positive
orphan. SELF builds (JM ``LIVE_ROOTS`` present) are byte-identical: real orphans are
still ``wired=False`` and real spine modules still ``wired=True``.

We assert specifically on ``.wired`` so the tests are robust to ``reason`` wording.
"""
import textwrap

from harness.wire_up import check_wired


def _write(root, rel, body=""):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_external_rootless_toolkit_module_is_wired_noop(tmp_path):
    # A foreign tree with NO JM LIVE_ROOTS and NO __main__ entrypoint: a rootless
    # toolkit consumed by external agents. Its isolate module must NOT be flagged
    # a false orphan -- the gate no-ops -> wired=True.
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/contracts.py", "VALUE = 1\n")
    _write(tmp_path, "pkg/toolkit_a.py", "from pkg import contracts\n")
    _write(tmp_path, "pkg/toolkit_b.py", "X = 2\n")
    # An isolate toolkit module: only reachable from external agents, never from an
    # internal root. RED before fix (wired=False), GREEN after (no-op wired=True).
    assert check_wired(tmp_path, "pkg/toolkit_b.py").wired is True
    # A module WITH a peer importer that is itself unreachable (orphan_cluster
    # shape) is likewise accepted on an external rootless tree.
    assert check_wired(tmp_path, "pkg/contracts.py").wired is True


def test_external_module_reachable_via_reconciled_main_root_is_wired(tmp_path):
    # A foreign tree WITH a real __main__ entrypoint that imports a lib module.
    # The reconciled root (discovered from the target tree, not JM LIVE_ROOTS)
    # must make the imported lib reachable -> wired=True via a live importer.
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/lib.py", "def helper():\n    return 1\n")
    _write(
        tmp_path,
        "pkg/app.py",
        """
        from pkg import lib

        def main():
            return lib.helper()

        if __name__ == '__main__':
            main()
        """,
    )
    res = check_wired(tmp_path, "pkg/lib.py")
    assert res.wired is True
    # Reachability (not merely the rootless no-op) is the cause: the reconciled
    # entrypoint app.py is a live importer of lib.
    assert "pkg/app.py" in res.importers


def test_self_tree_real_orphan_still_blocked(tmp_path):
    # SELF tree: a JM LIVE_ROOT (harness/orchestrator.py) IS present, so the
    # external-reconcile branch is NOT taken. A module imported by nobody
    # reachable stays a real orphan -> wired=False (unchanged by the fix).
    _write(tmp_path, "harness/__init__.py", "")
    _write(tmp_path, "harness/orchestrator.py", "VALUE = 1\n")
    _write(tmp_path, "harness/orphan.py", "Y = 3\n")
    assert check_wired(tmp_path, "harness/orphan.py").wired is False


def test_self_tree_wired_module_still_wired(tmp_path):
    # SELF tree positive path: a module imported by a live root stays wired
    # (the fix must not perturb the JM-monolith behavior).
    _write(tmp_path, "harness/__init__.py", "")
    _write(tmp_path, "harness/util.py", "def u():\n    return 0\n")
    _write(tmp_path, "harness/orchestrator.py", "from harness import util\n")
    assert check_wired(tmp_path, "harness/util.py").wired is True
