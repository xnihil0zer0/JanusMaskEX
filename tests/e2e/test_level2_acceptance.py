"""Hermetic Level-2 end-to-end acceptance test (epic e2e_acceptance_test child).

Proves the four assembled Level-2 capabilities compose, exercising the REAL
components built by the sibling children (no production code added, no network,
no pip, no rebuild, no tests/planner glob -- fixtures/temp dirs only):

  (a) epic routing: an ``epic: true`` brief is routed to epic decomposition (not
      the leaf pipeline) when hierarchical planning is enabled;
  (b) nested epic recursion: a child brief that is itself ``epic: true`` is also
      routed to decomposition rather than treated as a leaf;
  (c) depth budget: a brief whose epic lineage exceeds ``max_planner_depth`` is
      refused by ``cli.main`` with a non-zero exit;
  (d) failure propagation: ``compute_epic_status`` surfaces an epic as ``blocked``
      for a transitive failed descendant when ``failure_propagation`` is enabled;
  (e) interface resolution: the lazy ledger (``record_symbols``) +
      ``resolve_interfaces`` rewrite ``spec.interfaces`` at the staging seam
      (``stage_task``) when ``symbol_ledger`` is enabled -- a genuine
      ledger -> resolve -> staging round-trip.
"""
from pathlib import Path
import json
import types

import pytest
import yaml

import harness.planner.cli as cli
import harness.brief_status as bs
import harness.planner.staging as staging
from harness.symbol_ledger import record_symbols, resolve_interfaces

_REPO_CONFIG = Path(cli.__file__).resolve().parent.parent / "config.yaml"


# --------------------------------------------------------------------------- #
# (a) + (b)  epic routing / nested recursion
# --------------------------------------------------------------------------- #

def _brief(epic):
    b = types.SimpleNamespace()
    b.epic = epic
    b.slug = "x"
    b.source_path = "brief_hooks_x.md"
    return b


def test_a_epic_brief_routes_to_decomposition_when_enabled():
    cfg = {"hierarchical_planning": {"enabled": True}}
    assert cli._should_run_epic(_brief(True), cfg) is True
    # A leaf brief is NOT routed to epic decomposition.
    assert cli._should_run_epic(_brief(False), cfg) is False
    # With hierarchical planning disabled, even an epic brief falls to the leaf path.
    assert cli._should_run_epic(_brief(True), {"hierarchical_planning": {"enabled": False}}) is False


def test_b_nested_epic_child_is_also_decomposed_not_leaf():
    # A child brief that is itself epic:true must route to decomposition (recursion),
    # bounded by the depth gate (exercised in (c)). Same routing predicate applies
    # at every level -> a nested epic is re-decomposed, never treated as a leaf.
    cfg = {"hierarchical_planning": {"enabled": True}}
    nested_epic_child = _brief(True)
    assert cli._should_run_epic(nested_epic_child, cfg) is True


# --------------------------------------------------------------------------- #
# (c)  depth budget refusal via cli.main (real argparse only)
# --------------------------------------------------------------------------- #

class _PastGate(Exception):
    pass


def _write_epic_rec(repo, epic_slug, child_slugs):
    rec = {"plan_kind": "epic", "epic_slug": epic_slug, "child_slugs": list(child_slugs)}
    (repo / f"plan_hooks_{epic_slug}.json").write_text(json.dumps(rec), encoding="utf-8")


def _config_with_depth(tmp_path, max_depth):
    base = yaml.safe_load(_REPO_CONFIG.read_text(encoding="utf-8")) or {}
    base.setdefault("hierarchical_planning", {})
    base["hierarchical_planning"]["max_planner_depth"] = max_depth
    base["hierarchical_planning"]["enabled"] = True
    conf = tmp_path / "config.yaml"
    conf.write_text(yaml.safe_dump(base), encoding="utf-8")
    return conf


def test_c_over_budget_lineage_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_epic_rec(tmp_path, "gp", ["parent"])
    _write_epic_rec(tmp_path, "parent", ["child"])
    (tmp_path / "state").mkdir(exist_ok=True)

    childbrief = types.SimpleNamespace(epic=False, slug="child", source_path="brief_hooks_child.md")
    monkeypatch.setattr(cli, "load_brief", lambda p: childbrief)
    monkeypatch.setattr(cli, "_should_run_epic", lambda b, c: (_ for _ in ()).throw(_PastGate()))

    conf = _config_with_depth(tmp_path, max_depth=1)  # 'child' is depth 2 > 1
    brief = tmp_path / "brief.md"
    brief.write_text("# t\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cli.main([str(brief), "--config", str(conf)])
    assert exc.value.code != 0

    # And within budget the same lineage passes the gate (reaches _should_run_epic).
    conf4 = _config_with_depth(tmp_path, max_depth=4)
    with pytest.raises(_PastGate):
        cli.main([str(brief), "--config", str(conf4)])


# --------------------------------------------------------------------------- #
# (d)  failure propagation via compute_epic_status
# --------------------------------------------------------------------------- #

def test_d_transitive_failure_blocks_epic_when_enabled(tmp_path, monkeypatch):
    _write_epic_rec(tmp_path, "root", ["mid"])
    _write_epic_rec(tmp_path, "mid", ["leaf"])
    records = [
        {"slug": "root", "state": "planned"},
        {"slug": "mid", "state": "in_flight"},
        {"slug": "leaf", "state": "blocked"},
    ]
    monkeypatch.setattr(bs, "compute_brief_status", lambda repo_root, state_dir: records)

    def _root(result):
        return next(r for r in result if r["epic_slug"] == "root")

    on = _root(bs.compute_epic_status(tmp_path, tmp_path / "state",
                                      {"hierarchical_planning": {"failure_propagation": True}}))
    off = _root(bs.compute_epic_status(tmp_path, tmp_path / "state",
                                       {"hierarchical_planning": {"failure_propagation": False}}))
    assert on["state"] == "blocked"      # transitive failed descendant surfaces blocked
    assert off["state"] == "in_flight"   # flag off -> Phase-1 (direct children only)


# --------------------------------------------------------------------------- #
# (e)  ledger -> resolve_interfaces -> staging seam round-trip
# --------------------------------------------------------------------------- #

def _make_ledger(state_dir):
    """Write an accepted auto_commit row + its committed .py file under state_dir."""
    committed = state_dir / "harness" / "widget.py"
    committed.parent.mkdir(parents=True, exist_ok=True)
    committed.write_text("def make_widget(size: int) -> str:\n    return 'w'\n", encoding="utf-8")
    ledger = state_dir / "state"
    ledger.mkdir(parents=True, exist_ok=True)
    row = {"phase": "accepted", "event": "auto_commit", "files": ["harness/widget.py"]}
    (ledger / "impl_progress.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")


def test_e_ledger_resolve_round_trip(tmp_path):
    state_dir = tmp_path
    _make_ledger(state_dir)
    # record_symbols lazily derives the committed signature.
    mapping = record_symbols(state_dir)
    assert "make_widget" in mapping
    assert "make_widget(size: int) -> str" in mapping["make_widget"]
    # resolve_interfaces rewrites bare-name prose to the committed signature.
    resolved = resolve_interfaces("calls make_widget to build", state_dir)
    assert "make_widget(size: int) -> str" in resolved
    # A miss is returned unchanged.
    assert resolve_interfaces("no symbols here", state_dir) == "no symbols here"


def test_e_staging_seam_rewrites_interfaces_when_flag_on(tmp_path, monkeypatch):
    state_dir = tmp_path / "sd"
    _make_ledger(state_dir)
    # Flag ON via the canonical loader the staging seam uses.
    import harness.orchestrator as orch
    monkeypatch.setattr(orch, "load_config",
                        lambda *a, **k: {"hierarchical_planning": {"symbol_ledger": True}}, raising=False)
    plan = {"tasks": [{"task_id": "t1", "spec": {"interfaces": "uses make_widget here"}}]}
    plan_path = tmp_path / "plan_hooks_e.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    out = staging.stage_task(plan_path, "t1", state_dir)
    staged = json.loads(out.read_text(encoding="utf-8"))
    # The staging seam ran resolve_interfaces against the real ledger.
    assert "make_widget(size: int) -> str" in staged["spec"]["interfaces"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
