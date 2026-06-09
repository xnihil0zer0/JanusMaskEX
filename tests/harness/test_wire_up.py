"""RED oracle for the wire-up reachability primitive (harness/wire_up.py).

Contract under test (epic: wire_up_phase, leaf: wire-up-primitive):

    check_wired(repo_root, new_module_rel, *, roots=LIVE_ROOTS, exclude=())
        -> WireResult(wired: bool, importers: list[str], reason: str, fix_hint: str)

A module is WIRED iff it is reachable, via the intra-project import graph, from at
least one of the LIVE entrypoint roots -- NOT merely if *something* imports it. A
module imported only by another orphan is itself unwired (BFS-from-roots, not inbound
degree). The check reuses harness.rebuild.discover.module_import_graph, which already
excludes test/seed files from the module set, and seeds the BFS from `roots`.

These tests build a synthetic source tree so the primitive is driven hermetically
over an injected root set, with no real repo, process, or network dependency.
"""
import textwrap

import pytest

from harness.wire_up import check_wired, WireResult, LIVE_ROOTS


def _write(root, rel, body=""):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def _tree(root):
    # root.py is a live entrypoint that imports wired_mod.
    _write(root, "root.py", "import wired_mod\n")
    _write(root, "wired_mod.py", "X = 1\n")
    # orphan_mod is imported by nobody.
    _write(root, "orphan_mod.py", "Y = 2\n")
    # chain_mod is imported ONLY by orphan_mod -> not reachable from root.
    _write(root, "orphan_mod.py", "import chain_mod\nY = 2\n")
    _write(root, "chain_mod.py", "Z = 3\n")


def test_wireresult_shape():
    r = WireResult(wired=True, importers=["root.py"], reason="", fix_hint="")
    assert r.wired is True
    assert r.importers == ["root.py"]
    assert hasattr(r, "reason") and hasattr(r, "fix_hint")


def test_module_reachable_from_root_is_wired(tmp_path):
    _tree(tmp_path)
    r = check_wired(tmp_path, "wired_mod.py", roots=["root.py"])
    assert r.wired is True
    # The live importer is reported.
    assert any("root" in imp for imp in r.importers)


def test_module_nobody_imports_is_orphan(tmp_path):
    _tree(tmp_path)
    r = check_wired(tmp_path, "orphan_mod.py", roots=["root.py"])
    assert r.wired is False
    assert r.fix_hint  # actionable hint on how to wire it


def test_imported_only_by_orphan_is_still_unwired(tmp_path):
    # chain_mod has an inbound import edge (from orphan_mod) but is NOT reachable
    # from any live root. Inbound-degree > 0 must NOT launder it as wired.
    _tree(tmp_path)
    r = check_wired(tmp_path, "chain_mod.py", roots=["root.py"])
    assert r.wired is False


def test_own_oracle_excluded_from_importers(tmp_path):
    # A module imported ONLY by its own oracle is not wired. discover already drops
    # test files from the module set, but the exclude= contract is explicit so a
    # caller scanning tests cannot launder the module via its own oracle.
    _tree(tmp_path)
    _write(tmp_path, "selftest_mod.py", "W = 4\n")
    _write(tmp_path, "tests/test_selftest_mod.py", "import selftest_mod\n")
    r = check_wired(tmp_path, "selftest_mod.py", roots=["root.py"],
                    exclude=["tests/test_selftest_mod.py"])
    assert r.wired is False


def test_live_roots_constant_declared():
    # The real entrypoint set is declared so the accept-path gate seeds from it.
    assert isinstance(LIVE_ROOTS, (list, tuple)) and LIVE_ROOTS
    joined = " ".join(LIVE_ROOTS)
    assert "orchestrator" in joined
    assert "autowork_daemon" in joined


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
