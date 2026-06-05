"""Oracle for Brief 1: declare the hierarchical_planning config block (default-off).

RED on HEAD: harness/config.yaml does not declare the block. Mirrors the
auto_approve_sensitive_harness / selfheal_auto_promote default-off convention —
every hierarchical-planner capability is fail-closed until an operator flips it.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


def _load_cfg() -> dict:
    cfg_text = (REPO / "harness" / "config.yaml").read_text(encoding="utf-8")
    assert "hierarchical_planning" in cfg_text, (
        "harness/config.yaml must declare a hierarchical_planning block"
    )
    return yaml.safe_load(cfg_text)


def test_hierarchical_planning_block_present() -> None:
    cfg = _load_cfg()
    assert isinstance(cfg.get("hierarchical_planning"), dict), (
        "hierarchical_planning must be a mapping"
    )


def test_hierarchical_planning_enabled_activated() -> None:
    # Shipped default-off (fail-closed) through Phase-1 build; the operator
    # activated the loop on 2026-06-05 once all 17 briefs + the webui surface
    # landed. The Level-2 subflags below remain off, and the allowlist is still
    # deny-all by default, so activation alone dispatches nothing.
    cfg = _load_cfg()
    assert cfg["hierarchical_planning"].get("enabled") is True, (
        "hierarchical_planning.enabled was activated by the operator post-Phase-1"
    )


def test_hierarchical_planning_level2_subflags_default_false() -> None:
    cfg = _load_cfg()
    hp = cfg["hierarchical_planning"]
    assert hp.get("symbol_ledger") is False, (
        "hierarchical_planning.symbol_ledger must be False by default (Level-2 deferred)"
    )
    assert hp.get("failure_propagation") is False, (
        "hierarchical_planning.failure_propagation must be False by default (Level-2 deferred)"
    )


def test_hierarchical_planning_max_depth_default_four() -> None:
    cfg = _load_cfg()
    depth = cfg["hierarchical_planning"].get("max_planner_depth")
    assert depth == 4, (
        "hierarchical_planning.max_planner_depth must default to 4 (bounds runaway recursion)"
    )


def test_reader_pattern_is_safe_when_block_absent() -> None:
    """The documented read pattern config.get('hierarchical_planning',{}).get(...)
    must degrade to a safe default (False / None) — never raise — so all five
    validate_plan callers and the daemon stay byte-identical when the block is
    missing or partial. Guards against a future reader assuming the key exists.
    """
    empty: dict = {}
    assert empty.get("hierarchical_planning", {}).get("enabled", False) is False
    assert empty.get("hierarchical_planning", {}).get("symbol_ledger", False) is False
    assert empty.get("hierarchical_planning", {}).get("max_planner_depth", 4) == 4
