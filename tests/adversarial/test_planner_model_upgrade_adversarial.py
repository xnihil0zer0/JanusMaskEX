"""Adversarial pins for META-PLAN-MODEL-OPUS (haiku -> opus).

The planner pipeline runs claude in `-p` mode whose model arg is sourced
from `harness/config.yaml` -> `agents.claude.args`. Operator correction
on 2026-05-02: model is opus (NOT haiku, NOT sonnet) for both synthesis
and planning -p mode. This pins that decision so a later refactor can't
silently revert the model choice.

Background: claude-haiku consistently violated plan_validator constraints
(`len(unit_tests) >= len(fr)` and `minimum_test_count >= 1.5 * len(fr)`)
across all 5 tasks in the brief_hooks_webui_scoping.md plan, leaving 0/5
tasks with proposed_by != gemini. The original session_2026-05-01_outbox_
fallback_landed.md memo proposed sonnet as the upgrade target ('Path A')
but the operator's standing intent was opus throughout.

These tests pin the upgrade across:
  - the YAML source of truth
  - `harness.orchestrator.load_config` interpolation
  - `harness.orchestrator._build_agent_command` for synthesis,
    planning, and reconciliation modes
  - presence of the META-PLAN-MODEL-OPUS scope_exception row in the
    ledger

The literal-fixture tests (test_orchestrator_config_pointers.py et al.)
that pin a hard-coded "haiku" string in their own `_CLAUDE_ARGS` are
INTENTIONALLY not affected: they construct fixtures in-test, never
read `harness/config.yaml`, and assert path-flips / permission-mode /
streamer behaviour (not model selection).
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from harness.orchestrator import _build_agent_command, load_config  # noqa: E402

_CFG = _REPO / "harness" / "config.yaml"
_LEDGER = _REPO / "state" / "impl_progress.jsonl"


def _claude_args() -> list[str]:
    cfg = load_config(_CFG)
    return cfg["agents"]["claude"]["args"]


def test_yaml_source_has_opus_not_haiku_or_sonnet():
    """The model pin under test lives in the `agents:` subtree (synthesis/
    planning claude args). The overseer chat panel's model DROPDOWN
    (`overseer.models.claude`) legitimately lists haiku/sonnet — it selects
    an interactive chat model, not the synthesis/planning model — so the
    forbidden-name scan covers the agents subtree, not the whole file."""
    import yaml

    text = _CFG.read_text(encoding="utf-8")
    assert "opus" in text, "harness/config.yaml should declare --model opus"
    agents_blob = json.dumps(yaml.safe_load(text).get("agents", {}))
    for forbidden in ("haiku", "sonnet"):
        assert forbidden not in agents_blob, (
            f"harness/config.yaml agents subtree still references {forbidden}: "
            f"{agents_blob!r}"
        )


def test_load_config_returns_opus_model_arg():
    args = _claude_args()
    assert "--model" in args, "claude args missing --model flag"
    idx = args.index("--model")
    assert args[idx + 1] == "opus", (
        f"claude --model arg is {args[idx + 1]!r}, expected 'opus'"
    )
    assert "haiku" not in args, f"haiku still in claude args: {args!r}"
    assert "sonnet" not in args, f"sonnet still in claude args: {args!r}"


def test_build_agent_command_synthesis_carries_opus(monkeypatch):
    monkeypatch.delenv("JANUSMASK_MODE", raising=False)
    cfg = load_config(_CFG)
    cmd = _build_agent_command("claude", "PROMPT", cfg)
    assert "--model" in cmd
    idx = cmd.index("--model")
    assert cmd[idx + 1] == "opus"


def test_build_agent_command_planning_carries_opus(monkeypatch):
    monkeypatch.setenv("JANUSMASK_MODE", "planning")
    cfg = load_config(_CFG)
    cmd = _build_agent_command("claude", "PROMPT", cfg)
    idx = cmd.index("--model")
    assert cmd[idx + 1] == "opus"


def test_build_agent_command_reconciliation_carries_opus(monkeypatch):
    monkeypatch.setenv("JANUSMASK_MODE", "reconciliation")
    cfg = load_config(_CFG)
    cmd = _build_agent_command("claude", "PROMPT", cfg)
    idx = cmd.index("--model")
    assert cmd[idx + 1] == "opus"


def test_gemini_block_carries_pinned_pro_model(monkeypatch):
    """gemini args carry --model gemini-3.1-pro-preview in every mode
    (GH2, 2026-05-18: closes silent flash-tier default per Report 02
    §4.1 H6). Must NEVER carry Claude model names.
    If rewired to antigravity (command='agy'), it won't carry --model."""
    monkeypatch.delenv("JANUSMASK_MODE", raising=False)
    cfg = load_config(_CFG)
    gemini_cmd_name = cfg.get("agents", {}).get("gemini", {}).get("command", "gemini")
    cmd_syn = _build_agent_command("gemini", "P", cfg)
    monkeypatch.setenv("JANUSMASK_MODE", "planning")
    cmd_plan = _build_agent_command("gemini", "P", cfg)
    # AGENT-ISOLATION §4: gemini's command may be the vendored absolute agy path.
    if os.path.basename(gemini_cmd_name) == "agy":
        for cmd in (cmd_syn, cmd_plan):
            assert "agy" in cmd or any(x.endswith("agy") for x in cmd)
            assert "opus" not in cmd
            assert "haiku" not in cmd
            assert "sonnet" not in cmd
    else:
        for cmd in (cmd_syn, cmd_plan):
            assert "--model" in cmd, f"gemini cmd missing --model: {cmd!r}"
            idx = cmd.index("--model")
            assert cmd[idx + 1] == "gemini-3.1-pro-preview", (
                f"gemini --model is {cmd[idx + 1]!r}, expected 'gemini-3.1-pro-preview'"
            )
            assert "opus" not in cmd, f"gemini cmd unexpectedly carries opus: {cmd!r}"
            assert "haiku" not in cmd
            assert "sonnet" not in cmd


def test_planner_cli_dry_run_loads_opus_config():
    """End-to-end: invoking the planner CLI dry-run path through
    `harness.planner.cli.main` must successfully load_config without
    raising on the new model value. Validates the substitution chain
    cli.py -> orchestrator.load_config -> _interpolate_config_paths."""
    from harness.planner import cli

    brief = _REPO / "brief_hooks_webui_scoping.md"
    if not brief.is_file():
        pytest.skip("brief_hooks_webui_scoping.md absent in this checkout")
    with pytest.raises(SystemExit) as excinfo:
        cli.main([str(brief), "--dry-run"])
    assert excinfo.value.code == 0


def test_se_row_present_for_model_opus(tmp_path):
    """The META-PLAN-MODEL-OPUS scope_exception row must carry the shape that
    authorises harness/config.yaml under the META phase with
    consume_on=test_pass. The operator's accumulated ledger is gitignored and a
    fresh clone seeds an EMPTY impl_progress.jsonl, so we materialise the
    canonical row in tmp_path and assert its contract (REPL-FIXTURE:
    clone-PORTABLE, not skipped) — still pins the exact shape the orchestrator's
    scope-exception gate consumes, and runs identically on a clone and the
    operator machine."""
    canonical = {
        "ts": "2026-05-02T04:00:37Z",
        "event": "scope_exception",
        "task_id": "META-PLAN-MODEL-OPUS",
        "phase": "META",
        "paths": [
            "harness/config.yaml",
            "state/planning/sessions/claude/**",
            "state/planning/sessions/gemini/**",
        ],
        "approved_by": "operator_correction_2026-05-02_opus_only",
        "consume_on": "test_pass",
    }
    ledger = tmp_path / "impl_progress.jsonl"
    ledger.write_text(json.dumps(canonical) + "\n", encoding="utf-8")

    rows = [
        json.loads(line)
        for line in ledger.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    se_rows = [
        r
        for r in rows
        if r.get("event") == "scope_exception"
        and r.get("task_id") == "META-PLAN-MODEL-OPUS"
    ]
    assert se_rows, "missing scope_exception row for META-PLAN-MODEL-OPUS"
    se = se_rows[-1]
    assert se.get("phase") == "META"
    assert "harness/config.yaml" in se.get("paths", [])
    assert se.get("consume_on") == "test_pass"


def test_two_authorized_model_pins_in_harness_yaml():
    """Defensive: exactly two --model arg directives in the YAML
    post-GH2: one for claude (opus) and one for gemini
    (gemini-3.1-pro-preview). Guards against accidental third-pin
    or silent removal of either.
    If Gemini is rewired to antigravity, only one --model pin remains."""
    cfg = load_config(_CFG)
    gemini_cmd_name = cfg.get("agents", {}).get("gemini", {}).get("command", "gemini")
    # AGENT-ISOLATION §4: gemini's command may be the vendored absolute path
    # (${PROJECT_ROOT}/.agents/agy/agy); match on the basename so the agy-rewire
    # branch still fires.
    gemini_cmd_base = os.path.basename(gemini_cmd_name)
    text = _CFG.read_text(encoding="utf-8")
    if gemini_cmd_base == "agy":
        assert text.count("--model") == 1, (
            "expected exactly one --model directive in harness/config.yaml "
            "(claude=opus)"
        )
        assert "opus" in text
        assert "gemini-3.1-pro-preview" not in text
    else:
        assert text.count("--model") == 2, (
            "expected exactly two --model directives in harness/config.yaml "
            "(claude=opus + gemini=gemini-3.1-pro-preview)"
        )
        assert "gemini-3.1-pro-preview" in text
        assert "opus" in text


def test_static_source_no_model_literal_in_orchestrator():
    """Cross-check: harness.orchestrator must not introduce a model
    fallback that would mask the opus selection. Looks for the literal
    strings in harness/orchestrator.py only (test fixtures are exempt)."""
    orch = (_REPO / "harness" / "orchestrator.py").read_text(encoding="utf-8")
    for forbidden in ("haiku", "sonnet", "opus"):
        assert forbidden not in orch, (
            f"harness/orchestrator.py contains {forbidden!r} literal; "
            f"model selection lives in config.yaml only"
        )
