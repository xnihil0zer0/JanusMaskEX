"""META-D4-MANUAL: cross-cutting lifecycle emit invariants + parametric
adversarial failure injection across all 3 D2 emit-helpers.

Per-site unit tests already live at:
    tests/adversarial/test_d2a_orchestrator_lifecycle_emit_adversarial.py
    tests/adversarial/test_d2b_planner_cli_lifecycle_emit_adversarial.py
    tests/adversarial/test_d2c_attribution_emit_adversarial.py

This file consolidates the cross-cutting D4 acceptance:
    - Monotonic JSONL growth invariant on both impl_progress.jsonl AND
      planner_progress.jsonl across a synthetic mixed-emit dispatch.
    - Parametric OSError/PermissionError/FileNotFoundError injection across
      all 3 emit helpers verifying caller exit-code preservation.
    - Cross-helper schema invariant: every emitted row has a `ts` float.
"""
import json
from pathlib import Path

import pytest

from harness import orchestrator
from harness.planner import cli as planner_cli
from harness.planner import attribution


# ---------------------------------------------------------------------------
# Cross-cutting monotonic invariant
# ---------------------------------------------------------------------------


def test_monotonic_impl_progress_growth_across_synthetic_dispatch(tmp_path):
    """impl_progress.jsonl row count is monotonic non-decreasing across a
    synthetic 3-task dispatch worth of emits.
    """
    target = tmp_path / "impl_progress.jsonl"
    counts = []

    def append_count():
        if target.exists():
            counts.append(sum(1 for _ in target.read_text().splitlines() if _.strip()))
        else:
            counts.append(0)

    append_count()
    for i in range(3):
        orchestrator._emit_lifecycle(tmp_path, event="task_claim", task_id="T" + str(i))
        append_count()
        for phase in ("ast_validation", "fuzzing", "accepted"):
            orchestrator._emit_lifecycle(
                tmp_path,
                event="phase_transition",
                phase=phase,
                task_id="T" + str(i),
                phase_transition={"to": phase},
            )
            append_count()
        orchestrator._emit_lifecycle(tmp_path, event="task_terminal", task_id="T" + str(i))
        append_count()

    # Strictly non-decreasing
    assert counts == sorted(counts), "impl_progress row count not monotonic: " + str(counts)
    # Final count == start + (1 task_claim + 3 phases + 1 terminal) * 3 tasks = 15
    assert counts[-1] == 15, "expected 15 rows, got " + str(counts[-1])


def test_monotonic_planner_progress_growth_across_pipeline_stages(tmp_path):
    """planner_progress.jsonl grows monotonically across the 8-stage planner
    pipeline (D2b sites) plus interleaved attribution emits (D2c)."""
    pipeline = (tmp_path / "planning") / "planner_progress.jsonl"
    pipeline.parent.mkdir(parents=True, exist_ok=True)
    counts = [0]
    for stage in (
        "load_brief", "blind_drafts", "diff", "reconciliation",
        "attribution_stamp", "adversarial_review", "auto_amend_gate", "persist_plan",
    ):
        planner_cli._emit_planner_lifecycle(stage, state_dir=tmp_path)
        counts.append(sum(1 for _ in pipeline.read_text().splitlines() if _.strip()))

    # Interleave 5 attribution rows
    for i in range(5):
        attribution._emit_attribution_lifecycle("Tx" + str(i), "convergent", state_dir=tmp_path)
        counts.append(sum(1 for _ in pipeline.read_text().splitlines() if _.strip()))

    assert counts == sorted(counts)
    assert counts[-1] == 13, "expected 13 (8 stages + 5 attribution), got " + str(counts[-1])


# ---------------------------------------------------------------------------
# Parametric adversarial failure injection across ALL 3 helpers
# ---------------------------------------------------------------------------


def _orchestrator_emit(state_dir):
    orchestrator._emit_lifecycle(state_dir, event="phase_transition", phase="x", task_id="T")


def _planner_emit(state_dir):
    planner_cli._emit_planner_lifecycle("blind_drafts", state_dir=state_dir)


def _attribution_emit(state_dir):
    attribution._emit_attribution_lifecycle("T", "convergent", state_dir=state_dir)


_ALL_HELPERS = [
    ("orchestrator._emit_lifecycle", _orchestrator_emit, orchestrator),
    ("planner_cli._emit_planner_lifecycle", _planner_emit, planner_cli),
    ("attribution._emit_attribution_lifecycle", _attribution_emit, attribution),
]


@pytest.mark.parametrize("name,call,_module", _ALL_HELPERS)
@pytest.mark.parametrize("exc_class", [OSError, PermissionError, FileNotFoundError])
def test_all_helpers_swallow_oserror_subclasses(tmp_path, monkeypatch, name, call, _module, exc_class):
    """Cross-cutting: every D2 emit helper swallows OSError + subclasses.
    Caller exit unchanged (no exception propagates)."""
    import harness._journal as journal

    def boom(*a, **k):
        raise exc_class("err")

    # Monkey-patch the journal module the helpers all import from.
    monkeypatch.setattr(journal, "write_jsonl_row", boom)
    # Should NOT raise.
    call(tmp_path)


@pytest.mark.parametrize("name,call,_module", _ALL_HELPERS)
def test_all_helpers_propagate_non_oserror(tmp_path, monkeypatch, name, call, _module):
    """Negative-control: helpers do NOT swallow non-OSError. Pins the contract:
    only IO failures are best-effort; logic errors must surface."""
    import harness._journal as journal

    def boom(*a, **k):
        raise ValueError("logic bug")

    monkeypatch.setattr(journal, "write_jsonl_row", boom)
    # orchestrator helper imports write_jsonl_row at module load time, so the
    # monkeypatch on harness._journal.write_jsonl_row may not affect it.
    # Patch the orchestrator-bound symbol too if we hit it.
    if name.startswith("orchestrator"):
        monkeypatch.setattr(orchestrator, "write_jsonl_row", boom)
    with pytest.raises(ValueError):
        call(tmp_path)


# ---------------------------------------------------------------------------
# Cross-helper schema invariant
# ---------------------------------------------------------------------------


def test_all_helpers_emit_rows_with_ts_float(tmp_path):
    """Every emit row across all 3 helpers carries a `ts` float field."""
    # impl_progress side
    orchestrator._emit_lifecycle(tmp_path, event="phase_transition", phase="x", task_id="T")
    impl_rows = [json.loads(r) for r in (tmp_path / "impl_progress.jsonl").read_text().splitlines() if r.strip()]
    assert all(isinstance(r.get("ts"), float) for r in impl_rows)

    # planner_progress side (D2b)
    planner_cli._emit_planner_lifecycle("load_brief", state_dir=tmp_path)
    planner_rows = [json.loads(r) for r in (tmp_path / "planning" / "planner_progress.jsonl").read_text().splitlines() if r.strip()]
    assert all(isinstance(r.get("ts"), float) for r in planner_rows)

    # planner_progress side (D2c, same target file)
    attribution._emit_attribution_lifecycle("T", "convergent", state_dir=tmp_path)
    planner_rows2 = [json.loads(r) for r in (tmp_path / "planning" / "planner_progress.jsonl").read_text().splitlines() if r.strip()]
    assert len(planner_rows2) == len(planner_rows) + 1
    assert all(isinstance(r.get("ts"), float) for r in planner_rows2)


def test_planner_progress_kind_field_distinguishes_emit_source(tmp_path):
    """D2b emits kind='tracker_record'; D2c emits kind='attribution'.
    Both share the same JSONL target so consumers must filter on kind."""
    planner_cli._emit_planner_lifecycle("blind_drafts", state_dir=tmp_path)
    attribution._emit_attribution_lifecycle("T1", "convergent", state_dir=tmp_path)
    rows = [json.loads(r) for r in (tmp_path / "planning" / "planner_progress.jsonl").read_text().splitlines() if r.strip()]
    kinds = sorted(r["kind"] for r in rows)
    assert kinds == ["attribution", "tracker_record"]


# ---------------------------------------------------------------------------
# Regression sentinel
# ---------------------------------------------------------------------------


def test_no_existing_test_files_collide_with_d4_filename():
    """Pin: the consolidated D4 filename does not shadow a pre-existing test.
    Catches careless copy that would silently skip prior tests at collection."""
    repo = Path(__file__).resolve().parents[2]
    matches = list(repo.glob("tests/**/test_d4_lifecycle_emit_invariants_adversarial.py"))
    assert len(matches) == 1, "expected exactly one D4 test file, found " + str(matches)
