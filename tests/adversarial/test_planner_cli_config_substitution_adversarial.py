"""Pin: harness/planner/cli.py must use harness.orchestrator.load_config so that
${CONFIG_DIR}/${PROJECT_ROOT}/${STATE_DIR} placeholders in harness/config.yaml
are substituted before the spawned agents see them. A regression to raw
yaml.safe_load() leaves literal ${CONFIG_DIR} in claude/gemini --settings
args, claude dies with `Settings file not found: ${CONFIG_DIR}/claude_worker.json`,
the planner exits 2 with `Both agents failed to produce a valid draft`, and no
plan_hooks_*.json is produced.
"""
import inspect
import subprocess
import sys
from pathlib import Path

import harness.planner.cli as cli_mod


PROJECT_DIR = Path(__file__).resolve().parents[2]


def test_main_imports_load_config_not_raw_yaml_safe_load():
    src = inspect.getsource(cli_mod.main)
    assert "from harness.orchestrator import load_config" in src, (
        "cli.main must import load_config from harness.orchestrator"
    )
    assert "config = load_config(parsed.config)" in src, (
        "cli.main must invoke load_config(parsed.config)"
    )
    # Negative pin: the regression-prone raw-yaml-load pattern must be gone
    # from main(). yaml.safe_load may still appear elsewhere in the file but
    # not inside main()'s config-load step.
    assert "yaml.safe_load(f)" not in src, (
        "cli.main must not use raw yaml.safe_load — it bypasses ${CONFIG_DIR} "
        "interpolation and breaks claude/gemini spawn settings paths"
    )


def test_dry_run_against_minimal_brief_exits_zero(tmp_path):
    brief = tmp_path / "brief_hooks_smoke.md"
    brief.write_text(
        "# Title\nSmoke\n\n# Scope\nSmoke\n\n# Non-Goals\nNone\n\n"
        "# Inputs\nNone\n\n# Deliverables\nNone\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.planner.cli",
            str(brief),
            "--dry-run",
        ],
        cwd=str(PROJECT_DIR),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"dry-run failed: stderr={result.stderr!r} stdout={result.stdout!r}"
    )


def test_load_config_interpolates_config_dir(tmp_path):
    """End-to-end: load_config returns config with no ${CONFIG_DIR} literals
    in agents.claude.args / agents.gemini.args.
    """
    from harness.orchestrator import load_config

    config = load_config(PROJECT_DIR / "harness" / "config.yaml")
    for agent in ("claude", "gemini"):
        args = config["agents"][agent]["args"]
        for a in args:
            assert "${CONFIG_DIR}" not in a, (
                f"agent {agent} arg {a!r} still contains ${{CONFIG_DIR}} literal"
            )
            assert "${PROJECT_ROOT}" not in a
            assert "${STATE_DIR}" not in a
