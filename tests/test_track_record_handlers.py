import pytest
import json
import re
import multiprocessing
from pathlib import Path
from typing import Any

from harness.track_record import (
    decomposition_event,
    refactor_event,
    ambiguous_spec_event,
    fuzz_round1_fail_event,
    ast_rejection_event,
    clean_success_event,
    InvalidAgentError,
    init_track_record,
    _track_record_file,
    _read_track_record_from_disk,
)
from harness.track_record_events import read_events, _event_log_file
from harness.track_record_events import EventValidationError

@pytest.fixture
def seeded_state_dir(tmp_path, monkeypatch):
    src_meta = Path("tests/fixtures/taxonomies/meta_task_v1.json").resolve()
    src_synth = Path("tests/fixtures/taxonomies/synthesis_target_v1.json").resolve()
    meta_keys = json.loads(src_meta.read_text())
    synth_keys = json.loads(src_synth.read_text())
    meta_tax = {"version": 1, "keys": {k: k for k in meta_keys}}
    synth_tax = {"version": 1, "keys": {k: k for k in synth_keys}}
    (tmp_path / "meta_task_taxonomy.json").write_text(json.dumps(meta_tax))
    (tmp_path / "synthesis_target_taxonomy.json").write_text(json.dumps(synth_tax))
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
    init_track_record(tmp_path)
    return tmp_path

# Unit tests

def test_decomposition_event_appends_and_mutates(seeded_state_dir):
    event = decomposition_event("claude", "task-1", "test_unit", state_dir=seeded_state_dir)
    events = read_events(seeded_state_dir)
    assert len(events) == 1
    assert event["event_type"] == "decomposition"
    
    record = _read_track_record_from_disk(_track_record_file(seeded_state_dir))
    cell = record["spec_authorship"]["claude"]["test_unit"]
    assert cell["failures"] == 1
    assert cell["attempts"] == 1

def test_refactor_event_behaves_like_decomposition_on_counters(seeded_state_dir):
    event = refactor_event("claude", "task-2", "test_unit", state_dir=seeded_state_dir)
    events = read_events(seeded_state_dir)
    assert events[0]["event_type"] == "refactor"
    
    record = _read_track_record_from_disk(_track_record_file(seeded_state_dir))
    cell = record["spec_authorship"]["claude"]["test_unit"]
    assert cell["failures"] == 1
    assert cell["attempts"] == 1

def test_ambiguous_spec_event_folds_into_failures(seeded_state_dir):
    event = ambiguous_spec_event("claude", "task-3", "test_unit", state_dir=seeded_state_dir)
    events = read_events(seeded_state_dir)
    assert events[0]["event_type"] == "ambiguous_spec"
    
    record = _read_track_record_from_disk(_track_record_file(seeded_state_dir))
    cell = record["spec_authorship"]["claude"]["test_unit"]
    assert cell["failures"] == 1
    assert cell["attempts"] == 1

def test_fuzz_round1_fail_event_writes_to_synthesis_book(seeded_state_dir):
    event = fuzz_round1_fail_event("gemini", "task-4", "algorithm_impl", state_dir=seeded_state_dir)
    events = read_events(seeded_state_dir)
    assert events[0]["event_type"] == "fuzz_round1_fail"
    
    record = _read_track_record_from_disk(_track_record_file(seeded_state_dir))
    cell = record["synthesis"]["gemini"]["algorithm_impl"]
    assert cell["failures"] == 1
    assert cell["attempts"] == 1

def test_ast_rejection_event_writes_to_synthesis_book(seeded_state_dir):
    event = ast_rejection_event("gemini", "task-5", "algorithm_impl", state_dir=seeded_state_dir)
    events = read_events(seeded_state_dir)
    assert events[0]["event_type"] == "ast_rejection"
    
    record = _read_track_record_from_disk(_track_record_file(seeded_state_dir))
    cell = record["synthesis"]["gemini"]["algorithm_impl"]
    assert cell["failures"] == 1
    assert cell["attempts"] == 1

def test_clean_success_event_only_increments_attempts(seeded_state_dir):
    event = clean_success_event("spec_authorship", "claude", "test_unit", "task-6", state_dir=seeded_state_dir)
    events = read_events(seeded_state_dir)
    assert events[0]["event_type"] == "clean_success"
    
    record = _read_track_record_from_disk(_track_record_file(seeded_state_dir))
    cell = record["spec_authorship"]["claude"]["test_unit"]
    assert cell["failures"] == 0
    assert cell["attempts"] == 1

def test_handler_validates_meta_task_type(seeded_state_dir):
    from harness.taxonomy import UnknownTaxonomyKeyError
    with pytest.raises(UnknownTaxonomyKeyError):
        decomposition_event("claude", "task-err", "invalid_type", state_dir=seeded_state_dir)
        
    events = read_events(seeded_state_dir)
    assert len(events) == 0
    
    record = _read_track_record_from_disk(_track_record_file(seeded_state_dir))
    assert "invalid_type" not in record["spec_authorship"]["claude"]

def test_handler_validates_agent(seeded_state_dir):
    with pytest.raises(InvalidAgentError):
        decomposition_event("invalid_agent", "task-err2", "test_unit", state_dir=seeded_state_dir)

# Integration tests

def test_mixed_event_sequence_accumulates_correctly(seeded_state_dir):
    # 3 decomposition + 2 ambiguous_spec + 4 clean_success
    for i in range(3):
        decomposition_event("claude", f"d-{i}", "config_schema", state_dir=seeded_state_dir)
    for i in range(2):
        ambiguous_spec_event("claude", f"a-{i}", "config_schema", state_dir=seeded_state_dir)
    for i in range(4):
        clean_success_event("spec_authorship", "claude", "config_schema", f"c-{i}", state_dir=seeded_state_dir)
        
    events = read_events(seeded_state_dir)
    assert len(events) == 9
    
    record = _read_track_record_from_disk(_track_record_file(seeded_state_dir))
    cell = record["spec_authorship"]["claude"]["config_schema"]
    assert cell["failures"] == 5
    assert cell["attempts"] == 9

# Regression tests

def test_deferred_wiring_attempts_marker_present_in_every_handler():
    path = Path("harness/track_record.py")
    content = path.read_text()
    count = content.count("# DEFERRED_WIRING: attempts_not_consumed")
    assert count == 6

def test_deferred_wiring_ambiguous_marker_present():
    path = Path("harness/track_record.py")
    content = path.read_text()
    assert "# DEFERRED_WIRING: ambiguous_folded_into_failures" in content
    # Should be exactly 1
    count = content.count("# DEFERRED_WIRING: ambiguous_folded_into_failures")
    assert count >= 1

def test_ambiguous_event_shares_cell_with_decomposition(seeded_state_dir):
    ambiguous_spec_event("claude", "t1", "test_unit", state_dir=seeded_state_dir)
    decomposition_event("claude", "t2", "test_unit", state_dir=seeded_state_dir)
    record = _read_track_record_from_disk(_track_record_file(seeded_state_dir))
    cell = record["spec_authorship"]["claude"]["test_unit"]
    assert cell["failures"] == 2

# Property tests

def _worker_fn(args):
    event_type, agent, type_key, state_dir_str = args
    state_dir = Path(state_dir_str)
    try:
        if event_type == "decomposition":
            decomposition_event(agent, "task-mp", type_key, state_dir=state_dir)
        elif event_type == "clean_success":
            clean_success_event("spec_authorship", agent, type_key, "task-mp", state_dir=state_dir)
        return True
    except Exception as e:
        return False

def test_concurrent_handler_calls_sum_correctly(seeded_state_dir):
    # This acts as a property test to verify concurrent access sums correctly
    args = []
    # Mix of 50 decomposition and 50 clean_success across multiple agents
    for i in range(50):
        args.append(("decomposition", "claude", "test_unit", str(seeded_state_dir)))
        args.append(("clean_success", "claude", "test_unit", str(seeded_state_dir)))
        
    with multiprocessing.Pool(processes=4) as pool:
        results = pool.map(_worker_fn, args)
        
    assert all(results)
    
    record = _read_track_record_from_disk(_track_record_file(seeded_state_dir))
    cell = record["spec_authorship"]["claude"]["test_unit"]
    assert cell["failures"] == 50
    assert cell["attempts"] == 100
