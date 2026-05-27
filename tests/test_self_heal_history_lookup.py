import json
import pathlib
import pytest
from datetime import datetime
from harness.hooks._paths import (
    load_self_healing_history,
    matching_history_records,
    format_self_healing_section
)

def test_load_history_returns_empty_when_file_missing(tmp_path):
    # Pass a path that definitely does not have the JSONL file
    records = load_self_healing_history(tmp_path)
    assert records == []

def test_load_history_parses_valid_jsonl_records(tmp_path):
    # Set up directory structure
    state_dir = tmp_path / "state"
    autowork_dir = state_dir / "control" / "autowork"
    autowork_dir.mkdir(parents=True, exist_ok=True)
    
    jsonl_file = autowork_dir / "self_healing_history.jsonl"
    record1 = {"ts": 1600000000.0, "task_id": "task1", "outcome": "success", "files_touched": ["a.py"]}
    record2 = {"ts": 1600000001.0, "task_id": "task2", "outcome": "failed", "files_touched": ["b.py"]}
    
    with open(jsonl_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(record1) + "\n")
        f.write(json.dumps(record2) + "\n")
        
    records = load_self_healing_history(tmp_path)
    assert len(records) == 2
    assert records[0]["task_id"] == "task1"
    assert records[1]["task_id"] == "task2"

def test_load_history_skips_malformed_lines_without_raising(tmp_path):
    state_dir = tmp_path / "state"
    autowork_dir = state_dir / "control" / "autowork"
    autowork_dir.mkdir(parents=True, exist_ok=True)
    
    jsonl_file = autowork_dir / "self_healing_history.jsonl"
    record1 = {"ts": 1600000000.0, "task_id": "task1", "outcome": "success", "files_touched": ["a.py"]}
    
    with open(jsonl_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(record1) + "\n")
        f.write("not a valid json line\n")
        f.write("\n") # empty line
        f.write("[]\n") # valid json but not dict
        f.write(json.dumps(record1) + "\n")
        
    records = load_self_healing_history(tmp_path)
    assert len(records) == 2
    assert records[0]["task_id"] == "task1"
    assert records[1]["task_id"] == "task1"

def test_matching_records_filters_by_files_touched_overlap():
    records = [
        {"task_id": "t1", "files_touched": ["a.py", "b.py"]},
        {"task_id": "t2", "files_touched": ["c.py"]},
        {"task_id": "t3", "files_touched": ["b.py", "d.py"]},
    ]
    
    matches = matching_history_records(records, ["b.py"])
    assert len(matches) == 2
    assert matches[0]["task_id"] == "t1"
    assert matches[1]["task_id"] == "t3"

def test_matching_records_handles_non_list_files_touched_defensively():
    records = [
        {"task_id": "t1", "files_touched": "a.py"},
        {"task_id": "t2", "files_touched": ["b.py"]},
        {"task_id": "t3", "files_touched": None},
    ]
    
    matches = matching_history_records(records, ["a.py", "b.py"])
    assert len(matches) == 2
    assert matches[0]["task_id"] == "t1"
    assert matches[1]["task_id"] == "t2"

def test_format_section_returns_empty_string_for_no_matches():
    res = format_self_healing_section([])
    assert res == ''

def test_format_section_header_and_record_lines():
    dt_float = 1600000000.0
    expected_iso = datetime.fromtimestamp(dt_float).isoformat()
    
    records = [
        {"ts": dt_float, "task_id": "task1", "outcome": "success", "files_touched": ["a.py", "b.py"]}
    ]
    
    res = format_self_healing_section(records)
    assert res.startswith('--- RECENT SELF-HEALING HISTORY FOR RELATED COMPONENTS ---')
    assert "task1" in res
    assert "success" in res
    assert expected_iso in res
    assert "a.py" in res
    assert "b.py" in res

def test_history_helper_round_trip_with_real_jsonl_fixture(tmp_path):
    # Tests the complete integration of the three helpers
    state_dir = tmp_path / "state"
    autowork_dir = state_dir / "control" / "autowork"
    autowork_dir.mkdir(parents=True, exist_ok=True)
    
    jsonl_file = autowork_dir / "self_healing_history.jsonl"
    
    # 3 valid records, 1 blank line, 1 malformed line
    record1 = {"ts": 1600000000.0, "task_id": "task1", "outcome": "fail", "files_touched": ["a.py"]}
    record2 = {"ts": 1600000001.0, "task_id": "task2", "outcome": "success", "files_touched": ["b.py"]}
    record3 = {"ts": 1600000002.0, "task_id": "task3", "outcome": "fail", "files_touched": ["c.py"]}
    
    with open(jsonl_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(record1) + "\n")
        f.write("{\n") # malformed
        f.write(json.dumps(record2) + "\n")
        f.write("\n") # blank
        f.write(json.dumps(record3) + "\n")
        
    # load
    records = load_self_healing_history(tmp_path)
    assert len(records) == 3
    
    # match against files_touched list overlapping record 1 and record 3
    matches = matching_history_records(records, ["a.py", "c.py"])
    assert len(matches) == 2
    assert matches[0]["task_id"] == "task1"
    assert matches[1]["task_id"] == "task3"
    
    # format
    res = format_self_healing_section(matches)
    assert "--- RECENT SELF-HEALING HISTORY FOR RELATED COMPONENTS ---" in res
    assert "task1" in res
    assert "task3" in res
    assert "task2" not in res
