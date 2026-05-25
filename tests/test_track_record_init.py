import json
import multiprocessing
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings, strategies as st, HealthCheck

from harness.track_record import (
    init_track_record,
    TrackRecordCorruptError,
    _track_record_file,
    _write_track_record_to_disk,
)
from harness.taxonomy import (
    load_meta_task_taxonomy,
    load_synthesis_target_taxonomy,
)

@pytest.fixture
def isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import shutil
    from harness.state import _default_state_dir
    src = _default_state_dir()
    for f in ["meta_task_taxonomy.json", "synthesis_target_taxonomy.json"]:
        if (src / f).exists():
            shutil.copy(src / f, tmp_path / f)
    
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
    return tmp_path


def test_init_creates_file_with_full_taxonomy(isolated_state_dir: Path) -> None:
    record = init_track_record(isolated_state_dir)
    assert _track_record_file(isolated_state_dir).exists()
    
    meta_tax = load_meta_task_taxonomy(isolated_state_dir)
    synth_tax = load_synthesis_target_taxonomy(isolated_state_dir)
    meta_keys = meta_tax["keys"].keys()
    synth_keys = synth_tax["keys"].keys()
    
    for agent in ["claude", "gemini"]:
        for mk in meta_keys:
            assert record["spec_authorship"][agent][mk] == {"failures": 0, "attempts": 0}
        for sk in synth_keys:
            assert record["synthesis"][agent][sk] == {"failures": 0, "attempts": 0}


def test_init_is_idempotent_preserves_counts(isolated_state_dir: Path) -> None:
    init_track_record(isolated_state_dir)
    
    record_path = _track_record_file(isolated_state_dir)
    with open(record_path, "r") as f:
        data = json.load(f)
    
    data["spec_authorship"]["claude"]["data_model"]["failures"] = 42
    
    with open(record_path, "w") as f:
        json.dump(data, f)
        
    record = init_track_record(isolated_state_dir)
    assert record["spec_authorship"]["claude"]["data_model"]["failures"] == 42
    assert record["spec_authorship"]["claude"]["data_model"]["attempts"] == 0


def test_init_adds_missing_taxonomy_keys(isolated_state_dir: Path) -> None:
    init_track_record(isolated_state_dir)
    
    meta_tax_path = isolated_state_dir / "meta_task_taxonomy.json"
    with open(meta_tax_path, "r") as f:
        meta_data = json.load(f)
    
    meta_data["keys"]["new_meta_task"] = "A new task"
    with open(meta_tax_path, "w") as f:
        json.dump(meta_data, f)
        
    record = init_track_record(isolated_state_dir)
    assert "new_meta_task" in record["spec_authorship"]["claude"]
    assert record["spec_authorship"]["claude"]["new_meta_task"] == {"failures": 0, "attempts": 0}
    assert "data_model" in record["spec_authorship"]["claude"]


def test_init_records_taxonomy_version(isolated_state_dir: Path) -> None:
    record = init_track_record(isolated_state_dir)
    meta_tax = load_meta_task_taxonomy(isolated_state_dir)
    synth_tax = load_synthesis_target_taxonomy(isolated_state_dir)
    
    assert record["meta_task_taxonomy_version"] == meta_tax["version"]
    assert record["synthesis_target_taxonomy_version"] == synth_tax["version"]


def test_init_rejects_corrupt_existing_file(isolated_state_dir: Path) -> None:
    record_path = _track_record_file(isolated_state_dir)
    with open(record_path, "w") as f:
        f.write("{corrupt json")
        
    with pytest.raises(TrackRecordCorruptError):
        init_track_record(isolated_state_dir)


def _init_worker(state_dir: str) -> None:
    from harness.track_record import init_track_record
    init_track_record(Path(state_dir))


def test_init_concurrent_safe(isolated_state_dir: Path) -> None:
    procs = []
    for _ in range(5):
        p = multiprocessing.Process(target=_init_worker, args=(str(isolated_state_dir),))
        procs.append(p)
        p.start()
        
    for p in procs:
        p.join()
        assert p.exitcode == 0
        
    with open(_track_record_file(isolated_state_dir), "r") as f:
        data = json.load(f)
    assert "spec_authorship" in data
    assert "synthesis" in data


@st.composite
def init_bump_sequence(draw: Any) -> list[str]:
    return draw(st.lists(st.sampled_from(["init", "bump"]), min_size=1, max_size=10))


@given(ops=init_bump_sequence())
@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_init_idempotent_over_random_sequences(isolated_state_dir: Path, ops: list[str]) -> None:
    for op in ops:
        if op == "init":
            init_track_record(isolated_state_dir)
        elif op == "bump":
            record_path = _track_record_file(isolated_state_dir)
            if record_path.exists():
                with open(record_path, "r") as f:
                    data = json.load(f)
                if "spec_authorship" in data and "claude" in data["spec_authorship"] and "data_model" in data["spec_authorship"]["claude"]:
                    data["spec_authorship"]["claude"]["data_model"]["failures"] += 1
                with open(record_path, "w") as f:
                    json.dump(data, f)
    
    record = init_track_record(isolated_state_dir)
    assert "spec_authorship" in record


def test_init_does_not_zero_populated_record(isolated_state_dir: Path) -> None:
    init_track_record(isolated_state_dir)
    record_path = _track_record_file(isolated_state_dir)
    with open(record_path, "r") as f:
        data = json.load(f)
    
    data["spec_authorship"]["gemini"]["test_unit"]["attempts"] = 100
    with open(record_path, "w") as f:
        json.dump(data, f)
        
    record = init_track_record(isolated_state_dir)
    assert record["spec_authorship"]["gemini"]["test_unit"]["attempts"] == 100


def test_init_adds_new_agent_without_nuking_others(isolated_state_dir: Path) -> None:
    init_track_record(isolated_state_dir)
    record_path = _track_record_file(isolated_state_dir)
    with open(record_path, "r") as f:
        data = json.load(f)
    
    data["synthesis"]["claude"]["array_transform"]["failures"] = 99
    del data["synthesis"]["gemini"]
    with open(record_path, "w") as f:
        json.dump(data, f)
        
    record = init_track_record(isolated_state_dir)
    assert "gemini" in record["synthesis"]
    assert record["synthesis"]["gemini"]["array_transform"] == {"failures": 0, "attempts": 0}
    assert record["synthesis"]["claude"]["array_transform"]["failures"] == 99
