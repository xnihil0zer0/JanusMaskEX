"""Tests for scripts/impl_normalize_priority.py — priority canonicalization.

Covers the full input→canonical mapping, idempotency, dry-run isolation,
unmapped-value detection, indent preservation, and nested-task walking.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "impl_normalize_priority.py"

# Import the module for direct-call tests too
sys.path.insert(0, str(REPO_ROOT))
from scripts import impl_normalize_priority as mod  # noqa: E402


def _write_plan(path: Path, tasks: list[dict]) -> None:
    path.write_text(json.dumps({"tasks": tasks}, indent=2) + "\n", encoding="utf-8")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestMapping:
    @pytest.mark.parametrize(
        "raw,canonical",
        [
            (1, "critical"),
            (2, "high"),
            (3, "medium"),
            ("P0", "critical"),
            ("P1", "high"),
            ("P2", "medium"),
            ("P3", "low"),
            ("Critical", "critical"),
            ("High", "high"),
            ("Medium", "medium"),
            ("Low", "low"),
            ("critical", "critical"),
            ("high", "high"),
            ("medium", "medium"),
            ("low", "low"),
        ],
    )
    def test_mapping_covers_all_encodings(self, raw, canonical):
        assert mod.PRIORITY_MAP[raw] == canonical


class TestNormalizeFile:
    def test_integer_to_lowercase(self, tmp_path):
        p = tmp_path / "plan.json"
        _write_plan(p, [{"task_id": "T1", "priority": 1}, {"task_id": "T2", "priority": 2}])
        result = mod.normalize_file(p)
        assert result["status"] == "ok"
        assert result["mapped"] == 2
        data = _load(p)
        assert [t["priority"] for t in data["tasks"]] == ["critical", "high"]

    def test_p_prefix_to_lowercase(self, tmp_path):
        p = tmp_path / "plan.json"
        _write_plan(p, [{"task_id": "T1", "priority": "P0"}, {"task_id": "T2", "priority": "P3"}])
        result = mod.normalize_file(p)
        assert result["status"] == "ok"
        assert [t["priority"] for t in _load(p)["tasks"]] == ["critical", "low"]

    def test_titlecase_to_lowercase(self, tmp_path):
        p = tmp_path / "plan.json"
        _write_plan(p, [{"task_id": "T1", "priority": "High"}, {"task_id": "T2", "priority": "Medium"}])
        result = mod.normalize_file(p)
        assert result["status"] == "ok"
        assert [t["priority"] for t in _load(p)["tasks"]] == ["high", "medium"]

    def test_idempotent(self, tmp_path):
        p = tmp_path / "plan.json"
        _write_plan(p, [{"task_id": "T1", "priority": 1}])
        mod.normalize_file(p)
        first = p.read_text(encoding="utf-8")
        result = mod.normalize_file(p)
        assert result["changed"] is False
        assert p.read_text(encoding="utf-8") == first

    def test_unmapped_value_reported(self, tmp_path):
        p = tmp_path / "plan.json"
        _write_plan(p, [{"task_id": "T1", "priority": "urgent"}])
        result = mod.normalize_file(p)
        assert result["status"] == "unmapped_values"
        assert len(result["unmapped"]) == 1
        assert result["unmapped"][0]["priority"] == "urgent"
        # Ensure file not modified
        assert _load(p)["tasks"][0]["priority"] == "urgent"

    def test_dry_run_no_write(self, tmp_path):
        p = tmp_path / "plan.json"
        _write_plan(p, [{"task_id": "T1", "priority": 1}])
        before = p.read_text(encoding="utf-8")
        result = mod.normalize_file(p, dry_run=True)
        assert result["status"] == "ok"
        assert result["mapped"] == 1
        assert result["changed"] is True
        assert p.read_text(encoding="utf-8") == before

    def test_preserves_4space_indent(self, tmp_path):
        p = tmp_path / "plan.json"
        p.write_text(json.dumps({"tasks": [{"task_id": "T", "priority": 1}]}, indent=4) + "\n", encoding="utf-8")
        mod.normalize_file(p)
        lines = p.read_text(encoding="utf-8").split("\n")
        # First nested-object line should have 4 spaces
        for line in lines:
            if line.strip().startswith('"tasks"'):
                continue
            if line.startswith("    ") and not line.startswith("        "):
                break
        else:
            pytest.fail("no 4-space indented line found")

    def test_preserves_trailing_newline(self, tmp_path):
        p = tmp_path / "plan.json"
        _write_plan(p, [{"task_id": "T1", "priority": 1}])
        assert p.read_text(encoding="utf-8").endswith("\n")
        mod.normalize_file(p)
        assert p.read_text(encoding="utf-8").endswith("\n")

    def test_walks_nested_wrapper(self, tmp_path):
        p = tmp_path / "plan.json"
        # Schema-v2.1 wrapper style: wrapper keys + tasks array
        data = {
            "source_brief_path": "brief.md",
            "tasks": [
                {"task_id": "T1", "priority": 1},
                {"task_id": "T2", "priority": "P0"},
            ],
        }
        p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        result = mod.normalize_file(p)
        assert result["status"] == "ok"
        assert result["mapped"] == 2
        priorities = [t["priority"] for t in _load(p)["tasks"]]
        assert priorities == ["critical", "critical"]

    def test_no_priority_field_noop(self, tmp_path):
        p = tmp_path / "plan.json"
        _write_plan(p, [{"task_id": "T1"}])
        result = mod.normalize_file(p)
        assert result["status"] == "ok"
        assert result["mapped"] == 0
        assert result["changed"] is False


class TestCLI:
    def test_cli_dry_run(self, tmp_path):
        p = tmp_path / "plan.json"
        _write_plan(p, [{"task_id": "T1", "priority": 1}])
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--check", str(p)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0
        assert "mapped=1" in proc.stdout
        assert _load(p)["tasks"][0]["priority"] == 1

    def test_cli_writes(self, tmp_path):
        p = tmp_path / "plan.json"
        _write_plan(p, [{"task_id": "T1", "priority": 2}])
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), str(p)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0
        assert _load(p)["tasks"][0]["priority"] == "high"

    def test_cli_unmapped_exits_2(self, tmp_path):
        p = tmp_path / "plan.json"
        _write_plan(p, [{"task_id": "T1", "priority": "urgent"}])
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), str(p)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 2
        assert "unmapped" in proc.stdout
        # File unchanged
        assert _load(p)["tasks"][0]["priority"] == "urgent"

    def test_cli_multiple_files(self, tmp_path):
        p1 = tmp_path / "a.json"
        p2 = tmp_path / "b.json"
        _write_plan(p1, [{"task_id": "T1", "priority": 1}])
        _write_plan(p2, [{"task_id": "T2", "priority": 3}])
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), str(p1), str(p2)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0
        assert _load(p1)["tasks"][0]["priority"] == "critical"
        assert _load(p2)["tasks"][0]["priority"] == "medium"
