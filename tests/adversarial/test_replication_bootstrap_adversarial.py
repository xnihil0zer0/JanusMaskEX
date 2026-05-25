"""W116 adversarial — bootstrap.sh state tree materialization.

Pre-fix: scripts/bootstrap.sh only copied the .claude / .gemini settings
templates. A fresh clone had no state/ tree, so the harness's pre-write
gate (scripts/impl_pre_write.py reading state/impl_preserve.md) would
degrade to either fail-open or fail-closed depending on missing-file
handling, and the orchestrator had no state/STATE.json to read.

Post-fix: bootstrap.sh additionally creates state/{tasks/{queued,processed,
blocked},sessions,workdirs,hooks}/, copies config/impl_preserve.template.md
→ state/impl_preserve.md (if absent), touches state/impl_progress.jsonl
(if absent), and writes a minimal idle state/STATE.json (if absent).
Idempotent: re-running does not clobber existing files.

These tests run bootstrap.sh against a tmpdir that contains a copy of the
repo's tracked templates, then assert the state tree lands and is
idempotent on re-invocation.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _stage_repo(tmp_path: Path) -> Path:
    """Stage a minimal repo skeleton in tmp_path containing the files
    bootstrap.sh needs: scripts/bootstrap.sh + the three .template files.
    """
    proj = tmp_path / "proj"
    (proj / "scripts").mkdir(parents=True)
    (proj / ".claude").mkdir(parents=True)
    (proj / ".gemini").mkdir(parents=True)
    (proj / "config").mkdir(parents=True)

    shutil.copy(
        _REPO_ROOT / "scripts" / "bootstrap.sh", proj / "scripts" / "bootstrap.sh"
    )
    (proj / "scripts" / "bootstrap.sh").chmod(0o755)

    # Stage the tracked templates that bootstrap copies.
    for rel in (
        ".claude/settings.local.json.template",
        ".gemini/settings.json.template",
        "config/impl_preserve.template.md",
    ):
        src = _REPO_ROOT / rel
        if src.exists():
            shutil.copy(src, proj / rel)
    return proj


def _run_bootstrap(proj: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(proj / "scripts" / "bootstrap.sh")],
        env={"CLAUDE_PROJECT_DIR": str(proj), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


# -- Smoke: bootstrap creates the expected tree -------------------------


class TestBootstrapStateMaterialization:
    def test_bootstrap_creates_state_tree(self, tmp_path) -> None:
        proj = _stage_repo(tmp_path)
        result = _run_bootstrap(proj)
        assert result.returncode == 0, result.stderr

        for sub in (
            "state/tasks/queued",
            "state/tasks/processed",
            "state/tasks/blocked",
            "state/sessions",
            "state/workdirs",
            "state/hooks",
        ):
            assert (proj / sub).is_dir(), f"missing {sub}"

    def test_bootstrap_copies_impl_preserve_from_template(
        self, tmp_path
    ) -> None:
        proj = _stage_repo(tmp_path)
        _run_bootstrap(proj)
        live = proj / "state" / "impl_preserve.md"
        assert live.is_file()
        content = live.read_text()
        # The canonical phase-write allow-list must be present.
        assert "Phase META write allow-list" in content
        for entry in (
            "state/impl_progress.jsonl",
            "state/impl_preserve.md",
            "tests/adversarial/**",
            ".claude/settings.local.json",
            "scripts/impl_*.py",
        ):
            assert entry in content

    def test_bootstrap_touches_impl_progress_jsonl(self, tmp_path) -> None:
        proj = _stage_repo(tmp_path)
        _run_bootstrap(proj)
        ledger = proj / "state" / "impl_progress.jsonl"
        assert ledger.is_file()
        # Must be empty at bootstrap time (any content would be stale state
        # from another host accidentally checked in).
        assert ledger.read_text() == ""

    def test_bootstrap_writes_idle_state_json(self, tmp_path) -> None:
        proj = _stage_repo(tmp_path)
        _run_bootstrap(proj)
        state_json = proj / "state" / "STATE.json"
        assert state_json.is_file()
        data = json.loads(state_json.read_text())
        assert data == {"task_id": None, "round": 0, "phase": "idle"}


# -- Idempotence: re-running does not clobber live files ---------------


class TestBootstrapIdempotence:
    def test_rerun_does_not_overwrite_existing_state_files(
        self, tmp_path
    ) -> None:
        proj = _stage_repo(tmp_path)
        _run_bootstrap(proj)

        # Mutate live files.
        (proj / "state" / "impl_preserve.md").write_text("CUSTOM_OPERATOR_EDIT")
        (proj / "state" / "impl_progress.jsonl").write_text(
            '{"event": "test"}\n'
        )
        (proj / "state" / "STATE.json").write_text(
            '{"task_id": "T1", "round": 5, "phase": "synthesis"}'
        )

        result = _run_bootstrap(proj)
        assert result.returncode == 0

        # All three live files preserved verbatim.
        assert (
            proj / "state" / "impl_preserve.md"
        ).read_text() == "CUSTOM_OPERATOR_EDIT"
        assert (
            proj / "state" / "impl_progress.jsonl"
        ).read_text() == '{"event": "test"}\n'
        assert json.loads(
            (proj / "state" / "STATE.json").read_text()
        ) == {"task_id": "T1", "round": 5, "phase": "synthesis"}

    def test_rerun_idempotent_on_first_run_messages(self, tmp_path) -> None:
        proj = _stage_repo(tmp_path)
        first = _run_bootstrap(proj)
        second = _run_bootstrap(proj)
        assert first.returncode == 0 and second.returncode == 0
        # Second run must say "already exists" for at least the state files
        # so operators can see it was a no-op.
        assert "already exists, skipping" in second.stdout


# -- Template content pin ----------------------------------------------


class TestTemplateContent:
    def test_template_contains_canonical_allow_list(self) -> None:
        tpl = _REPO_ROOT / "config" / "impl_preserve.template.md"
        assert tpl.is_file()
        content = tpl.read_text()
        assert "Phase: `META`" in content
        # The exact entries the harness pre-write gate cares about.
        for entry in (
            "state/impl_progress.jsonl",
            "state/impl_preserve.md",
            "brief_hooks_*.md",
            "plan_hooks_*.json",
            "scripts/impl_*.py",
            "scripts/impl_*.sh",
            "scripts/run_adv.py",
            "tests/adversarial/**",
            ".claude/settings.local.json",
        ):
            assert entry in content, f"template missing allow-list entry: {entry}"

    def test_template_does_not_carry_audit_body(self) -> None:
        tpl = _REPO_ROOT / "config" / "impl_preserve.template.md"
        content = tpl.read_text()
        # Ensure the live host-specific audit body never bled into the template.
        for forbidden in (
            "Dead-code audit",
            "REMOVED",
            "trace_call_path",
            "20121 nodes",
        ):
            assert (
                forbidden not in content
            ), f"template should not contain audit body fragment: {forbidden}"
