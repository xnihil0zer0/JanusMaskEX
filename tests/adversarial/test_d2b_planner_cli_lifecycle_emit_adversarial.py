"""META-D2b-MANUAL pin: harness.planner.cli emit-point closure.

Verifies the additive _emit_planner_lifecycle calls at every _tracker.record
boundary per brief D2 Deliverables.
"""
import inspect
import json
from pathlib import Path

import pytest

from harness.planner import cli as planner_cli


_STAGES = [
    "load_brief",
    "blind_drafts",
    "diff",
    "reconciliation",
    "attribution_stamp",
    "adversarial_review",
    "auto_amend_gate",
    "persist_plan",
]


def test_emit_planner_lifecycle_helper_exists():
    assert hasattr(planner_cli, "_emit_planner_lifecycle")
    src = inspect.getsource(planner_cli._emit_planner_lifecycle)
    assert "write_jsonl_row" in src
    assert "planner_progress.jsonl" in src
    assert "except OSError" in src
    assert "tracker_record" in src


def test_emit_writes_row_to_planner_progress(tmp_path):
    planner_cli._emit_planner_lifecycle("load_brief", state_dir=tmp_path)
    target = tmp_path / "planning" / "planner_progress.jsonl"
    assert target.exists(), "planner_progress.jsonl should be created"
    row = json.loads(target.read_text().strip())
    assert row["stage"] == "load_brief"
    assert row["kind"] == "tracker_record"
    assert "ts" in row
    assert isinstance(row["ts"], float)


def test_emit_falls_back_to_default_state_dir(tmp_path, monkeypatch):
    """When state_dir is None, helper falls back to Path('state')."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    planner_cli._emit_planner_lifecycle("diff")
    target = tmp_path / "state" / "planning" / "planner_progress.jsonl"
    assert target.exists()
    row = json.loads(target.read_text().strip())
    assert row["stage"] == "diff"


def test_emit_swallows_oserror(tmp_path, monkeypatch):
    """OSError on write_jsonl_row swallowed; planner exit unchanged."""
    import harness._journal as journal

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(journal, "write_jsonl_row", boom)
    # Re-import the helper so its `from harness._journal import write_jsonl_row` picks up the patch
    planner_cli._emit_planner_lifecycle("blind_drafts", state_dir=tmp_path)


@pytest.mark.parametrize("stage", _STAGES)
def test_static_source_pin_each_stage_has_emit(stage):
    """Pin: every _tracker.record('STAGE') in cli.py is followed by an
    _emit_planner_lifecycle('STAGE', ...) call.
    """
    src = Path(planner_cli.__file__).read_text()
    # Accept either quote style: AST unparse may normalize "..." to '...' on
    # any pass-through merge of cli.py (e.g. P4.1 PLANNER_LOUD_FAIL_EMPTY_DRAFT
    # dispatch normalized the entire file to single quotes).
    record_tokens = [
        '_tracker.record("' + stage + '")',
        "_tracker.record('" + stage + "')",
    ]
    emit_tokens = [
        '_emit_planner_lifecycle("' + stage + '"',
        "_emit_planner_lifecycle('" + stage + "'",
    ]
    record_token = next((t for t in record_tokens if t in src), None)
    emit_token = next((t for t in emit_tokens if t in src), None)
    assert record_token is not None, "missing _tracker.record(" + stage + ") in either quote style"
    assert emit_token is not None, "missing _emit_planner_lifecycle(" + stage + ") in either quote style"
    record_idx = src.index(record_token)
    emit_idx = src.index(emit_token)
    assert emit_idx > record_idx, stage + ": emit must come AFTER _tracker.record"
    between = src[record_idx + len(record_token):emit_idx]
    assert between.strip() == "", stage + ": emit should immediately follow record (got: " + repr(between) + ")"


def test_emit_count_matches_pipeline_stages():
    """Count helper invocations across the module — must equal 8 stages."""
    src = Path(planner_cli.__file__).read_text()
    n = src.count("_emit_planner_lifecycle(")
    # 8 call sites + 1 def line = 9
    assert n == 9, "expected 9 occurrences (8 calls + 1 def), got " + str(n)


def test_load_brief_actually_emits_when_called(tmp_path, monkeypatch):
    """Functional smoke: calling load_brief writes the planner_progress row."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    brief_text = """# Brief

This is a minimal brief.

## Section A
Some content.
"""
    brief_path = tmp_path / "brief.md"
    brief_path.write_text(brief_text)
    try:
        planner_cli.load_brief(brief_path)
    except Exception:
        # Brief loader may reject minimal content; emit should still have happened.
        pass
    target = tmp_path / "state" / "planning" / "planner_progress.jsonl"
    assert target.exists(), "load_brief should emit even on subsequent loader failure"
    row = json.loads(target.read_text().splitlines()[0])
    assert row["stage"] == "load_brief"
