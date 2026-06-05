"""Oracle for P10-A1: declare the auto_approve_sensitive_harness config flag.

RED on HEAD: harness/config.yaml does not declare the flag.
"""
from __future__ import annotations

import pathlib
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_config_declares_auto_approve_sensitive_harness() -> None:
    cfg_text = (REPO / "harness" / "config.yaml").read_text(encoding="utf-8")
    assert "auto_approve_sensitive_harness" in cfg_text, (
        "harness/config.yaml must declare autowork.auto_approve_sensitive_harness"
    )
    
    cfg = yaml.safe_load(cfg_text)
    # OWNER POSTURE (2026-06-05): autowork.enabled is the security switch; with
    # it ON, auto_approve_sensitive_harness is intentionally True so Phase-2
    # builds fully unattended. The irreducible _NEVER_AUTO_APPROVE deny-list
    # (verified elsewhere) is the floor that stays regardless of this flag.
    assert cfg.get("autowork", {}).get("auto_approve_sensitive_harness") is True, (
        "autowork.auto_approve_sensitive_harness must be True under the active "
        "fully-unattended autonomy posture"
    )
