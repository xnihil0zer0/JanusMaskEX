"""META-D2c-MANUAL pin: harness.planner.attribution emit replacement.

Verifies the print() at attribution.py:57 was replaced by a structured
write_jsonl_row to state/planning/planner_progress.jsonl.
"""
import inspect
import json
from pathlib import Path

from harness.planner import attribution


def test_emit_attribution_lifecycle_helper_exists():
    assert hasattr(attribution, "_emit_attribution_lifecycle")
    src = inspect.getsource(attribution._emit_attribution_lifecycle)
    assert "write_jsonl_row" in src
    assert "planner_progress.jsonl" in src
    assert "except OSError" in src
    assert '"kind": "attribution"' in src


def test_emit_writes_attribution_row(tmp_path):
    attribution._emit_attribution_lifecycle("T1", "convergent", state_dir=tmp_path)
    target = tmp_path / "planning" / "planner_progress.jsonl"
    assert target.exists()
    row = json.loads(target.read_text().strip())
    assert row["kind"] == "attribution"
    assert row["payload"]["task_id"] == "T1"
    assert "convergent" in row["payload"]["diff_kind"]
    assert "ts" in row


def test_emit_swallows_oserror(tmp_path, monkeypatch):
    """OSError on write_jsonl_row swallowed; stamp_attribution exit unchanged."""
    import harness._journal as journal

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(journal, "write_jsonl_row", boom)
    attribution._emit_attribution_lifecycle("T1", "convergent", state_dir=tmp_path)


def test_print_debug_removed_from_attribution():
    """Pin: the old print('DEBUG: task_id=...') call is gone.

    Use AST inspection rather than substring search to avoid false matches
    against docstring text (the helper's docstring legitimately mentions
    the old print).
    """
    import ast as _ast
    src = Path(attribution.__file__).read_text()
    tree = _ast.parse(src)
    print_calls = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Name) and node.func.id == "print":
            print_calls.append(node.lineno)
    assert print_calls == [], "no print() calls should remain, found at lines " + str(print_calls)


def test_stamp_attribution_loop_calls_emit():
    """Static-source pin: stamp_attribution body calls _emit_attribution_lifecycle."""
    src = inspect.getsource(attribution.stamp_attribution)
    assert "_emit_attribution_lifecycle(task_id" in src, (
        "stamp_attribution loop must call the helper per task"
    )


def test_state_dir_fallback_to_default(tmp_path, monkeypatch):
    """When state_dir is None, helper falls back to Path('state')."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    attribution._emit_attribution_lifecycle("Tx", "claude_only")
    target = tmp_path / "state" / "planning" / "planner_progress.jsonl"
    assert target.exists()
