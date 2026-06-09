"""Wiring oracle: run_chat_turn captures procedure artifacts from the agent turn.

For the procedure FSM's backed gates to auto-verify, each assistant turn's text
is scanned for __PROCEDURE_ARTIFACT__ / __PROCEDURE_ATTEST__ markers and merged
into the conversation record (which persists via the store). Next turn's
gate_runner then reads rec['procedure_artifacts'] / rec['procedure_attested'].
"""
import json

from overseer.session_store import SessionStore
from overseer import turn_runner


class _FakeParser:
    def handle_event(self, event):
        pass


def _canned_stream(text_chunks):
    lines = [json.dumps({"type": "system", "subtype": "init", "session_id": "s1"})]
    for chunk in text_chunks:
        lines.append(json.dumps({"type": "content_block_delta",
                                 "delta": {"type": "text_delta", "text": chunk}}))
    return lines


def _seams(lines):
    def jail_builder(argv, **kw):
        return list(argv)

    def env_builder(conversation, **kw):
        return {"X": "1"}

    def runner(cmd, *, env, stdin, **kw):
        return lines

    return (runner, env_builder, jail_builder, _FakeParser())


def _store(tmp_path):
    store = SessionStore(tmp_path / "sessions.json")
    store.create("c1", current_mode="observe", model="opus", agent_backend="claude")
    store.append_turn("c1", {"role": "user", "content": "go"})
    return store


def _run(tmp_path, text_chunks):
    store = _store(tmp_path)
    turn_runner.run_chat_turn(
        store, "c1", "go", config={}, repo_root=tmp_path,
        state_dir=tmp_path / "state", logs_dir=tmp_path / "logs",
        seams=_seams(_canned_stream(text_chunks)),
    )
    return store.get("c1")


def test_artifact_marker_in_turn_persisted_to_record(tmp_path):
    rec = _run(tmp_path, ('Done. __PROCEDURE_ARTIFACT__ {"oracle_path": "tests/t.py"}',))
    assert rec["procedure_artifacts"]["oracle_path"] == "tests/t.py"


def test_attestation_marker_in_turn_persisted(tmp_path):
    rec = _run(tmp_path, ('__PROCEDURE_ATTEST__ {"phase": "SCOPE"}',))
    assert rec["procedure_attested"]["SCOPE"] is True


def test_turn_without_markers_records_no_artifacts(tmp_path):
    rec = _run(tmp_path, ("just a normal reply",))
    assert not rec.get("procedure_artifacts")


def test_artifact_and_attestation_in_one_turn_both_persist(tmp_path):
    rec = _run(tmp_path, ('__PROCEDURE_ARTIFACT__ {"plan_path": "p.json"}\n'
                          '__PROCEDURE_ATTEST__ {"phase": "BUILD"}',))
    assert rec["procedure_artifacts"]["plan_path"] == "p.json"
    assert rec["procedure_attested"]["BUILD"] is True


def test_artifacts_accumulate_across_turns(tmp_path):
    store = _store(tmp_path)
    common = dict(config={}, repo_root=tmp_path, state_dir=tmp_path / "state",
                  logs_dir=tmp_path / "logs")
    turn_runner.run_chat_turn(store, "c1", "go", seams=_seams(_canned_stream(
        ('__PROCEDURE_ARTIFACT__ {"oracle_paths": ["a.py"]}',))), **common)
    turn_runner.run_chat_turn(store, "c1", "go", seams=_seams(_canned_stream(
        ('__PROCEDURE_ARTIFACT__ {"oracle_paths": ["b.py"]}',))), **common)
    assert store.get("c1")["procedure_artifacts"]["oracle_paths"] == ["a.py", "b.py"]
