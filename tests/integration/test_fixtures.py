import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"

def test_every_fixture_parses_as_json():
    for p in FIXTURES_DIR.rglob("*.json"):
        if p.name == "invalid.json":
            continue
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data is not None

def test_every_jsonl_fixture_parses_line_by_line():
    for p in FIXTURES_DIR.rglob("*.jsonl"):
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    assert isinstance(data, dict)

def test_track_record_fixtures_conform_to_schema():
    for p in (FIXTURES_DIR / "track_record").glob("*.json"):
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert "spec_authorship" in data
            assert "synthesis" in data
            assert isinstance(data["spec_authorship"], dict)
            assert isinstance(data["synthesis"], dict)

def test_taxonomy_fixtures_cover_all_keys():
    with open(FIXTURES_DIR / "taxonomies" / "meta_task_v1.json", "r", encoding="utf-8") as f:
        meta_tasks = json.load(f)
        assert len(meta_tasks) == 12

    with open(FIXTURES_DIR / "taxonomies" / "synthesis_target_v1.json", "r", encoding="utf-8") as f:
        synthesis = json.load(f)
        assert len(synthesis) == 14

def test_bogus_taxonomy_has_known_bad_key():
    with open(FIXTURES_DIR / "taxonomies" / "meta_task_v1_with_bogus_key.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        assert "__BOGUS__" in data

def test_fixtures_index_references_every_fixture():
    with open(FIXTURES_DIR / "FIXTURES_INDEX.md", "r", encoding="utf-8") as f:
        index_content = f.read()

    for p in FIXTURES_DIR.rglob("*"):
        if p.is_file() and p.name != "FIXTURES_INDEX.md":
            rel_path = p.relative_to(FIXTURES_DIR).as_posix()
            assert rel_path in index_content, f"{rel_path} not found in FIXTURES_INDEX.md"

def test_event_log_with_reversal_has_a_reversed_event():
    with open(FIXTURES_DIR / "track_record" / "event_log_with_reversal.jsonl", "r", encoding="utf-8") as f:
        events = [json.loads(line) for line in f if line.strip()]
        reversed_events = [e for e in events if e.get("reversed") is True]
        assert len(reversed_events) >= 1
        assert "reversal_reason" in reversed_events[0]
        assert reversed_events[0]["reversal_reason"]

def test_event_log_with_reversal_has_exactly_one_reversed_marker():
    with open(FIXTURES_DIR / "track_record" / "event_log_with_reversal.jsonl", "r", encoding="utf-8") as f:
        events = [json.loads(line) for line in f if line.strip()]
        reversed_events = sum(1 for e in events if e.get("reversed") is True)
        assert reversed_events == 1

def test_fixtures_index_covers_every_checked_in_fixture():
    with open(FIXTURES_DIR / "FIXTURES_INDEX.md", "r", encoding="utf-8") as f:
        index_content = f.read()

    listed_in_index = []
    for line in index_content.splitlines():
        if "* " in line and "`" in line:
            parts = line.split("`")
            if len(parts) >= 3:
                listed_in_index.append(parts[1])

    on_disk = []
    for p in (FIXTURES_DIR / "planning").glob("*"):
        if p.is_file():
            on_disk.append(p.relative_to(FIXTURES_DIR).as_posix())
    for p in (FIXTURES_DIR / "track_record").glob("*"):
        if p.is_file():
            on_disk.append(p.relative_to(FIXTURES_DIR).as_posix())

    assert set(listed_in_index) >= set(on_disk), "Orphaned fixtures found in planning/track_record"

def test_load_fixture_helper_round_trip(load_fixture):
    loaded = load_fixture("track_record", "empty.json")
    with open(FIXTURES_DIR / "track_record" / "empty.json", "r", encoding="utf-8") as f:
        direct = json.load(f)
    assert loaded == direct

def test_no_fixture_exceeds_size_cap():
    for p in FIXTURES_DIR.rglob("*.json"):
        with open(p, "r", encoding="utf-8") as f:
            lines = f.readlines()
            assert len(lines) <= 200, f"Fixture {p.name} exceeds 200 lines"
    for p in FIXTURES_DIR.rglob("*.jsonl"):
        with open(p, "r", encoding="utf-8") as f:
            lines = f.readlines()
            assert len(lines) <= 200, f"Fixture {p.name} exceeds 200 lines"
