"""Self-heal Link #3b oracle: a NEW operator flag ``autowork.selfheal_auto_promote``
(default false) gates whether self-heal-originated briefs auto-promote, WITHOUT
mutating the operator ``auto_promote.allowlist`` (the allowlist-guard invariant in
test_allowlist_promotion_guard.py must stay green — that test runs alongside this one).

RED on HEAD: the helper ``_selfheal_auto_promote_enabled`` does not exist and
harness/config.yaml does not declare the flag.
"""
from __future__ import annotations

import pathlib

from harness import autowork_daemon as d

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_selfheal_flag_helper_reads_config() -> None:
    assert hasattr(d, "_selfheal_auto_promote_enabled"), (
        "autowork_daemon._selfheal_auto_promote_enabled missing"
    )
    assert d._selfheal_auto_promote_enabled({"autowork": {"selfheal_auto_promote": True}}) is True
    assert d._selfheal_auto_promote_enabled({"autowork": {"selfheal_auto_promote": False}}) is False
    # default-deny when the key/section is absent
    assert d._selfheal_auto_promote_enabled({}) is False
    assert d._selfheal_auto_promote_enabled({"autowork": {}}) is False


def test_config_declares_selfheal_flag() -> None:
    cfg = (REPO / "harness" / "config.yaml").read_text(encoding="utf-8")
    assert "selfheal_auto_promote" in cfg, (
        "harness/config.yaml must declare autowork.selfheal_auto_promote (default false)"
    )
