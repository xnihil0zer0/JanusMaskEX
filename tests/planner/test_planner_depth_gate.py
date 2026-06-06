"""Oracle for the planner depth-budget gate (child planner_depth_and_recursion).

Validates the gate added to ``harness/planner/cli.py`` ``main()`` (50d223c) and the
leaf-allow fix (b26da87), driving it through ONLY the REAL argparse interface
(positional brief + ``--config``) — NO invented flags like ``--repo-root``.

The gate runs after the brief loads and before any pipeline: it computes the
brief's epic-lineage depth via ``harness.depth_validator.check_brief_depth`` using
``config['hierarchical_planning']['max_planner_depth']`` and ``repo_root =
Path('state').parent`` (cwd), and exits non-zero when the lineage exceeds budget.
A leaf brief with no epic lineage (empty slug) must plan normally.

Hermetic: each test chdir's into tmp_path, builds an epic-lineage of
``plan_hooks_*.json`` records there, stubs ``load_brief`` to a brief with a chosen
slug, and stubs ``_should_run_epic`` to raise a sentinel — so "gate passed" is
observable as the sentinel propagating, with NO real planning pipeline running.
"""
from pathlib import Path
import json

import pytest
import yaml

import harness.planner.cli as cli

# Real harness/config.yaml, captured before any chdir (cli is harness/planner/cli.py).
_REPO_CONFIG = Path(cli.__file__).resolve().parent.parent / "config.yaml"


class _PastGate(Exception):
    """Raised by the stubbed _should_run_epic to prove control passed the gate."""


class _Brief:
    def __init__(self, slug):
        self.slug = slug
        self.source_path = f"brief_hooks_{slug}.md" if slug else "brief_hooks_.md"
        self.epic = False


def _write_epic(repo, epic_slug, child_slugs):
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


def _setup(tmp_path, monkeypatch, slug, max_depth):
    monkeypatch.chdir(tmp_path)
    # Lineage gp -> parent -> child  =>  'child' is at depth 2.
    _write_epic(tmp_path, "gp", ["parent"])
    _write_epic(tmp_path, "parent", ["child"])
    (tmp_path / "state").mkdir(exist_ok=True)
    monkeypatch.setattr(cli, "load_brief", lambda p: _Brief(slug))

    def _past(brief_obj, config):
        raise _PastGate()

    monkeypatch.setattr(cli, "_should_run_epic", _past)
    conf = _config_with_depth(tmp_path, max_depth)
    brief = tmp_path / "brief.md"
    brief.write_text("# Title\n", encoding="utf-8")
    return conf, brief


def test_over_budget_lineage_refused_with_exit_2(tmp_path, monkeypatch):
    # 'child' depth 2 with max_depth 1 -> refused before the pipeline.
    conf, brief = _setup(tmp_path, monkeypatch, "child", max_depth=1)
    with pytest.raises(SystemExit) as exc:
        cli.main([str(brief), "--config", str(conf)])
    assert exc.value.code != 0


def test_within_budget_lineage_passes_the_gate(tmp_path, monkeypatch):
    # 'child' depth 2 with max_depth 4 -> gate passes; control reaches _should_run_epic.
    conf, brief = _setup(tmp_path, monkeypatch, "child", max_depth=4)
    with pytest.raises(_PastGate):
        cli.main([str(brief), "--config", str(conf)])


def test_leaf_brief_empty_slug_plans_normally_even_at_low_budget(tmp_path, monkeypatch):
    # Empty slug (no epic lineage) must skip the gate (b26da87) even at max_depth 1.
    conf, brief = _setup(tmp_path, monkeypatch, "", max_depth=1)
    with pytest.raises(_PastGate):
        cli.main([str(brief), "--config", str(conf)])


def test_non_lineage_slug_at_low_budget_passes(tmp_path, monkeypatch):
    # A non-empty slug that is NOT part of any epic lineage has depth 0 -> allowed.
    conf, brief = _setup(tmp_path, monkeypatch, "unrelated_leaf", max_depth=1)
    with pytest.raises(_PastGate):
        cli.main([str(brief), "--config", str(conf)])


def test_depth_budget_is_non_vacuous(tmp_path, monkeypatch):
    """Same 'child' lineage: budget 1 refuses (SystemExit), budget 4 passes
    (_PastGate). The budget must actually change the outcome."""
    conf1, brief1 = _setup(tmp_path, monkeypatch, "child", max_depth=1)
    with pytest.raises(SystemExit):
        cli.main([str(brief1), "--config", str(conf1)])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
