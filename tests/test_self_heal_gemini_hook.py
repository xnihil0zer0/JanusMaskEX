from __future__ import annotations

import io
import json
import pathlib
import pytest

import harness.hooks.gemini.user_prompt_submit as user_prompt_submit
from harness.hooks import _ledger


@pytest.fixture
def synth_workdir(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "gemini" / "sessUP"
    (workdir / "inbox").mkdir(parents=True)
    task_body = {"task_id": "T", "title": "do it", "constraints": {"deterministic": True}}
    (workdir / "inbox" / "task.json").write_text(json.dumps(task_body))
    (state / "STATE.json").write_text(
        json.dumps({"round": 2, "phase": "synthesis", "task_id": "T"})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    monkeypatch.setenv("JANUSMASK_ROUND", "2")
    return {
        "state": state,
        "workdir": workdir,
        "session_id": "sessUP",
        "task": task_body,
    }


def test_gemini_hook_appends_history_section_when_matches_found(synth_workdir):
    # Prepare task JSON with files_touched
    task_body = {
        "task_id": "T",
        "title": "do it",
        "files_touched": ["a.py", "b.py"]
    }
    (synth_workdir["workdir"] / "inbox" / "task.json").write_text(json.dumps(task_body))

    # Set up history directory and file
    state_dir = synth_workdir["state"]
    autowork_dir = state_dir / "control" / "autowork"
    autowork_dir.mkdir(parents=True, exist_ok=True)
    history_file = autowork_dir / "self_healing_history.jsonl"
    
    record1 = {
        "ts": 1600000000.0,
        "task_id": "prev_task",
        "outcome": "success",
        "files_touched": ["a.py"]
    }
    history_file.write_text(json.dumps(record1) + "\n")

    stdin = io.StringIO(json.dumps({"session_id": synth_workdir["session_id"]}))
    stdout = io.StringIO()
    rc = user_prompt_submit.main(stdin, stdout)
    assert rc == 0

    out = json.loads(stdout.getvalue())
    assert out["decision"] == "allow"
    msg = out["systemMessage"]
    assert "--- RECENT SELF-HEALING HISTORY FOR RELATED COMPONENTS ---" in msg
    assert "prev_task" in msg
    assert "success" in msg


def test_gemini_hook_omits_section_when_history_file_absent(synth_workdir):
    # Prepare task JSON with files_touched
    task_body = {
        "task_id": "T",
        "title": "do it",
        "files_touched": ["a.py", "b.py"]
    }
    (synth_workdir["workdir"] / "inbox" / "task.json").write_text(json.dumps(task_body))

    # Ensure no history file is written

    stdin = io.StringIO(json.dumps({"session_id": synth_workdir["session_id"]}))
    stdout = io.StringIO()
    rc = user_prompt_submit.main(stdin, stdout)
    assert rc == 0

    out = json.loads(stdout.getvalue())
    assert out["decision"] == "allow"
    msg = out["systemMessage"]
    assert "--- RECENT SELF-HEALING HISTORY FOR RELATED COMPONENTS ---" not in msg


def test_gemini_hook_omits_section_when_no_files_overlap(synth_workdir):
    # Prepare task JSON with files_touched
    task_body = {
        "task_id": "T",
        "title": "do it",
        "files_touched": ["a.py"]
    }
    (synth_workdir["workdir"] / "inbox" / "task.json").write_text(json.dumps(task_body))

    # Set up history directory and file with non-overlapping record
    state_dir = synth_workdir["state"]
    autowork_dir = state_dir / "control" / "autowork"
    autowork_dir.mkdir(parents=True, exist_ok=True)
    history_file = autowork_dir / "self_healing_history.jsonl"
    
    record1 = {
        "ts": 1600000000.0,
        "task_id": "prev_task",
        "outcome": "success",
        "files_touched": ["c.py"]
    }
    history_file.write_text(json.dumps(record1) + "\n")

    stdin = io.StringIO(json.dumps({"session_id": synth_workdir["session_id"]}))
    stdout = io.StringIO()
    rc = user_prompt_submit.main(stdin, stdout)
    assert rc == 0

    out = json.loads(stdout.getvalue())
    assert out["decision"] == "allow"
    msg = out["systemMessage"]
    assert "--- RECENT SELF-HEALING HISTORY FOR RELATED COMPONENTS ---" not in msg
