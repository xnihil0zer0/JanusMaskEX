import json
import os
import multiprocessing
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings, HealthCheck
import hypothesis.strategies as st

from harness.track_record_events import (
    append_track_event,
    read_events,
    EventValidationError,
    EventLogCorruptError,
)

@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state_dir))
    
    meta_task = {
        "version": 1,
        "keys": {
            "data_model": "Data Model",
            "cli_tooling": "CLI Tooling"
        }
    }
    synthesis_target = {
        "version": 1,
        "keys": {
            "array_transform": "Array Transform"
        }
    }
    
    with open(state_dir / "meta_task_taxonomy.json", "w") as f:
        json.dump(meta_task, f)
    with open(state_dir / "synthesis_target_taxonomy.json", "w") as f:
        json.dump(synthesis_target, f)
        
    return state_dir


def test_append_track_event_writes_well_formed_line(state_dir):
    event = append_track_event(
        event_type="decomposition",
        book="spec_authorship",
        agent="claude",
        type="data_model",
        task_id="task-1",
        delta={"failures": 1, "attempts": 1},
        state_dir=state_dir
    )
    
    log_path = state_dir / "track_record_events.jsonl"
    with open(log_path, "r") as f:
        lines = f.readlines()
        
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    
    expected_keys = {"event_id", "timestamp", "event_type", "book", "agent", "type", "task_id", "delta", "reversed", "reversal_reason"}
    assert set(parsed.keys()) == expected_keys
    assert parsed["reversed"] is False
    assert parsed["reversal_reason"] is None
    assert parsed["event_id"] == event["event_id"]


def test_append_track_event_rejects_invalid_event_type(state_dir):
    with pytest.raises(EventValidationError):
        append_track_event(
            event_type="not_a_real_type",
            book="spec_authorship",
            agent="claude",
            type="data_model",
            task_id="task-1",
            delta={"failures": 1, "attempts": 1},
            state_dir=state_dir
        )
    assert not (state_dir / "track_record_events.jsonl").exists()


def test_append_track_event_rejects_invalid_book(state_dir):
    with pytest.raises(EventValidationError):
        append_track_event(
            event_type="decomposition",
            book="invalid_book",
            agent="claude",
            type="data_model",
            task_id="task-1",
            delta={"failures": 1, "attempts": 1},
            state_dir=state_dir
        )


def test_append_track_event_rejects_invalid_agent(state_dir):
    with pytest.raises(EventValidationError):
        append_track_event(
            event_type="decomposition",
            book="spec_authorship",
            agent="invalid_agent",
            type="data_model",
            task_id="task-1",
            delta={"failures": 1, "attempts": 1},
            state_dir=state_dir
        )


def test_append_track_event_rejects_type_outside_taxonomy_for_book(state_dir):
    # array_transform is a synthesis-target key, so it should be rejected for spec_authorship
    with pytest.raises(EventValidationError):
        append_track_event(
            event_type="decomposition",
            book="spec_authorship",
            agent="claude",
            type="array_transform",
            task_id="task-1",
            delta={"failures": 1, "attempts": 1},
            state_dir=state_dir
        )


def test_append_track_event_rejects_delta_missing_keys(state_dir):
    with pytest.raises(EventValidationError):
        append_track_event(
            event_type="decomposition",
            book="spec_authorship",
            agent="claude",
            type="data_model",
            task_id="task-1",
            delta={"failures": 1}, # missing attempts
            state_dir=state_dir
        )


def test_read_events_returns_order(state_dir):
    e1 = append_track_event("decomposition", "spec_authorship", "claude", "data_model", "t1", {"failures": 1, "attempts": 1}, state_dir)
    e2 = append_track_event("refactor", "spec_authorship", "gemini", "data_model", "t2", {"failures": 0, "attempts": 1}, state_dir)
    
    events = read_events(state_dir)
    assert len(events) == 2
    assert events[0]["event_id"] == e1["event_id"]
    assert events[1]["event_id"] == e2["event_id"]


def test_read_events_raises_on_partial_trailing_line(state_dir):
    append_track_event("decomposition", "spec_authorship", "claude", "data_model", "t1", {"failures": 1, "attempts": 1}, state_dir)
    
    log_path = state_dir / "track_record_events.jsonl"
    with open(log_path, "a") as f:
        f.write('{"event_id": "partial_')
        
    with pytest.raises(EventLogCorruptError) as exc_info:
        read_events(state_dir)
        
    assert "line 2" in str(exc_info.value)


def worker(state_dir, count, start_id):
    for i in range(count):
        append_track_event(
            event_type="decomposition",
            book="spec_authorship",
            agent="claude",
            type="data_model",
            task_id=f"task-{start_id}-{i}",
            delta={"failures": 1, "attempts": 1},
            state_dir=state_dir
        )

def test_concurrent_append_subprocess(state_dir):
    N = 50
    p1 = multiprocessing.Process(target=worker, args=(state_dir, N, "p1"))
    p2 = multiprocessing.Process(target=worker, args=(state_dir, N, "p2"))
    
    p1.start()
    p2.start()
    p1.join()
    p2.join()
    
    assert p1.exitcode == 0
    assert p2.exitcode == 0
    
    events = read_events(state_dir)
    assert len(events) == 2 * N
    
    event_ids = {e["event_id"] for e in events}
    assert len(event_ids) == 2 * N


@given(
    events=st.lists(
        st.fixed_dictionaries({
            "event_type": st.sampled_from(["decomposition", "refactor"]),
            "book": st.just("spec_authorship"),
            "agent": st.sampled_from(["claude", "gemini"]),
            "type": st.sampled_from(["data_model", "cli_tooling"]),
            "task_id": st.text(min_size=1),
            "delta": st.just({"failures": 1, "attempts": 1})
        }),
        max_size=10
    )
)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_sequence_of_random_appends_roundtrips(state_dir, events):
    # clear file
    log_path = state_dir / "track_record_events.jsonl"
    if log_path.exists():
        log_path.unlink()
        
    written = []
    for e in events:
        written.append(append_track_event(
            **e,
            state_dir=state_dir
        ))
        
    read_back = read_events(state_dir)
    assert len(read_back) == len(written)
    for w, r in zip(written, read_back):
        assert w == r


def test_fsync_before_lock_release(state_dir, monkeypatch):
    import harness.track_record_events as tre
    
    fsync_called = False
    original_fsync = os.fsync
    
    def spy_fsync(fd):
        nonlocal fsync_called
        fsync_called = True
        return original_fsync(fd)
        
    monkeypatch.setattr(os, "fsync", spy_fsync)
    
    append_track_event("decomposition", "spec_authorship", "claude", "data_model", "t1", {"failures": 1, "attempts": 1}, state_dir)
    
    assert fsync_called is True


def test_event_id_unique_across_rapid_appends(state_dir):
    events = [
        append_track_event("decomposition", "spec_authorship", "claude", "data_model", "t1", {"failures": 1, "attempts": 1}, state_dir)
        for _ in range(100)
    ]
    
    ids = {e["event_id"] for e in events}
    assert len(ids) == 100
