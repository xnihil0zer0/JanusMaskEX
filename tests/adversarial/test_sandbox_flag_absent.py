"""RED oracle for plan item §1a: the agy-backed fallback agents must NOT carry
the `--sandbox` flag.

agy's own `--sandbox` cannot nest inside the harness bwrap jail -> the agent
exits `code 2` without submitting. This was LIVE-CONFIRMED on 2026-06-03: in a
real `rev26_p5b_config_keys` dispatch, `claude_fallback` died `code 2` on every
retry. The primary `gemini` agent (no `--sandbox`) runs fine under the same jail.

- RED on HEAD: `antigravity` and `claude_fallback` args contain `--sandbox`.
- GREEN after fix: the flag is removed from both.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from harness.paths import PROJECT_ROOT

CONFIG = PROJECT_ROOT / "harness" / "config.yaml"

# Agents whose `command` is agy (basename 'agy') route through the in-process
# stdin/fenced-block submission path and never need agy's own sandbox; carrying
# `--sandbox` only makes them die `code 2` inside bwrap.
_AGY_BACKED = ("antigravity", "claude_fallback")


def test_no_sandbox_flag_on_agy_backed_agents():
    cfg = yaml.safe_load(CONFIG.read_text())
    agents = cfg["agents"]
    offenders = []
    for name in _AGY_BACKED:
        args = agents.get(name, {}).get("args") or []
        if "--sandbox" in args:
            offenders.append(name)
    assert not offenders, (
        f"agy-backed agents still carry --sandbox (cannot nest in bwrap -> code 2): "
        f"{offenders}"
    )


def test_agy_backed_agents_keep_skip_permissions():
    """Guard: removing --sandbox must NOT strip --dangerously-skip-permissions,
    which agy requires in the non-interactive jail (else it prompts and dies)."""
    cfg = yaml.safe_load(CONFIG.read_text())
    agents = cfg["agents"]
    for name in _AGY_BACKED:
        args = agents.get(name, {}).get("args") or []
        assert "--dangerously-skip-permissions" in args, (
            f"{name} must retain --dangerously-skip-permissions"
        )
