"""RED oracle for wire-up-sweep leaf 2: the tree-wide sweep classifier.

``sweep_modules(repo_root, *, roots) -> SweepReport`` builds the intra-project
import graph ONCE (via discover.module_import_graph), applies the source-set
filter (excluding _archive/**, _autowork_archive/**, samples/**, scripts/**,
tests/**, venv/**), and partitions every remaining source module into exactly
one of four classes over the BFS-reachable set from ``roots``:

  * WIRED          - reachable from a live root (own-oracle/test importers never count)
  * CONFIG_WIRED   - no static reachability but referenced by stem in config/**
  * ORPHAN_CLUSTER - inbound importers exist but none is reachable from a root
  * ORPHAN         - zero inbound importers and no config reference

This oracle drives a hermetic fixture tree and asserts each class lands on the
right module, exclusions hold, test importers do not launder, and output is
deterministic. RED until ``sweep_modules`` / ``SweepReport`` exist.
"""
from __future__ import annotations

from pathlib import Path

# RED until leaf 2 adds sweep_modules + SweepReport to harness/wire_up.py.
from harness.wire_up import SweepReport, sweep_modules


def _build_fixture(tmp: Path) -> None:
    def w(rel: str, txt: str) -> None:
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")

    w("root.py", "import wired_mod\n")          # the live root (passed via roots=)
    w("wired_mod.py", "x = 1\n")                # WIRED: imported by the root
    w("orphan.py", "y = 1\n")                   # ORPHAN: zero importers
    w("cluster_a.py", "import cluster_b\n")     # ORPHAN_CLUSTER: mutual, unreachable
    w("cluster_b.py", "import cluster_a\n")     # ORPHAN_CLUSTER
    w("config_only.py", "z = 1\n")              # CONFIG_WIRED: referenced in config/**
    w("tested_mod.py", "t = 1\n")               # ORPHAN: imported ONLY by a test
    w("config/hooks.json", '{"command": "python3 -m config_only"}\n')
    w("_archive/junk.py", "import wired_mod\n")  # excluded by source-set filter
    w("samples/s.py", "a = 1\n")                # excluded
    w("scripts/sc.py", "b = 1\n")               # excluded
    w("tests/test_tested.py", "import tested_mod\n")  # test importer must not wire tested_mod


def _report(tmp: Path) -> SweepReport:
    _build_fixture(tmp)
    return sweep_modules(tmp, roots=["root.py"])


def test_wired_class(tmp_path):
    r = _report(tmp_path)
    assert "wired_mod.py" in r.wired
    assert "root.py" in r.wired  # a live root is itself wired


def test_orphan_class(tmp_path):
    r = _report(tmp_path)
    assert "orphan.py" in r.orphan


def test_orphan_cluster_class(tmp_path):
    r = _report(tmp_path)
    assert "cluster_a.py" in r.orphan_cluster
    assert "cluster_b.py" in r.orphan_cluster
    # a cluster member is NOT a plain orphan (it has inbound importers)
    assert "cluster_a.py" not in r.orphan


def test_config_wired_class(tmp_path):
    r = _report(tmp_path)
    assert "config_only.py" in r.config_wired
    assert "config_only.py" not in r.orphan


def test_test_importer_does_not_launder(tmp_path):
    # tested_mod is imported only by tests/test_tested.py -> still ORPHAN.
    r = _report(tmp_path)
    assert "tested_mod.py" in r.orphan
    assert "tested_mod.py" not in r.wired


def test_excluded_dirs_are_not_classified(tmp_path):
    r = _report(tmp_path)
    everything = set(r.wired) | set(r.config_wired) | set(r.orphan_cluster) | set(r.orphan)
    for excluded in ("_archive/junk.py", "samples/s.py", "scripts/sc.py"):
        assert excluded not in everything, f"{excluded} must be excluded by the source-set filter"


def test_each_class_list_is_sorted(tmp_path):
    r = _report(tmp_path)
    for lst in (r.wired, r.config_wired, r.orphan_cluster, r.orphan):
        assert lst == sorted(lst)


def test_classification_is_deterministic(tmp_path):
    _build_fixture(tmp_path)
    a = sweep_modules(tmp_path, roots=["root.py"])
    b = sweep_modules(tmp_path, roots=["root.py"])
    assert a.to_dict() == b.to_dict()


def test_report_serializes_to_markdown(tmp_path):
    r = _report(tmp_path)
    md = r.to_markdown()
    assert isinstance(md, str)
    assert "ORPHAN" in md
    assert "orphan.py" in md
    # deterministic rendering
    assert md == r.to_markdown()
