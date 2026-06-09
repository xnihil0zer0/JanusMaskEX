"""Oracle for overseer/procedure_artifacts.py.

For the procedure FSM's backed gates to auto-verify, the conversation must
accumulate the task artifacts the gates need (oracle path, brief, plan, report)
and the operator/agent's attestations of judgment steps. The overseer agent
emits structured markers in its turn text:

    __PROCEDURE_ARTIFACT__ {"oracle_path": "tests/overseer/test_x.py"}
    __PROCEDURE_ATTEST__ {"phase": "SCOPE"}

This module parses those markers and merges them into the conversation record so
gate_runner can read rec['procedure_artifacts'] / rec['procedure_attested'].
"""
from overseer.procedure_artifacts import (parse_artifacts, parse_attestations,
                                          merge_artifacts, apply_to_record)


def test_parse_single_artifact_marker():
    text = 'working...\n__PROCEDURE_ARTIFACT__ {"oracle_path": "tests/t.py"}\ndone'
    assert parse_artifacts(text) == {"oracle_path": "tests/t.py"}


def test_parse_multiple_markers_merge_later_wins_and_lists_union():
    text = ('__PROCEDURE_ARTIFACT__ {"oracle_paths": ["a.py"], "brief_path": "b1.md"}\n'
            '__PROCEDURE_ARTIFACT__ {"oracle_paths": ["b.py"], "brief_path": "b2.md"}')
    out = parse_artifacts(text)
    assert out["oracle_paths"] == ["a.py", "b.py"]   # _paths union, de-duped
    assert out["brief_path"] == "b2.md"              # scalar: later wins


def test_parse_artifact_with_nested_json_object():
    text = '__PROCEDURE_ARTIFACT__ {"report": {"oracle_green": true, "new_regressions": 0}}'
    assert parse_artifacts(text) == {"report": {"oracle_green": True, "new_regressions": 0}}


def test_malformed_marker_is_ignored():
    text = '__PROCEDURE_ARTIFACT__ {not valid json\n__PROCEDURE_ARTIFACT__ {"plan_path": "p.json"}'
    assert parse_artifacts(text) == {"plan_path": "p.json"}


def test_no_markers_yields_empty():
    assert parse_artifacts("just a normal reply") == {}
    assert parse_attestations("nothing here") == []


def test_parse_attestations_collects_phases():
    text = ('__PROCEDURE_ATTEST__ {"phase": "SCOPE"}\n'
            '__PROCEDURE_ATTEST__ {"phase": "ORACLE"}\n'
            '__PROCEDURE_ATTEST__ {"phase": "SCOPE"}')
    assert parse_attestations(text) == ["SCOPE", "ORACLE"]   # ordered, de-duped


def test_merge_artifacts_does_not_mutate_inputs():
    a = {"oracle_paths": ["x.py"], "brief_path": "b.md"}
    b = {"oracle_paths": ["y.py"]}
    out = merge_artifacts(a, b)
    assert out["oracle_paths"] == ["x.py", "y.py"]
    assert a["oracle_paths"] == ["x.py"]   # input untouched


def test_apply_to_record_updates_artifacts_and_attestations():
    rec = {"procedure_artifacts": {"oracle_paths": ["x.py"]}}
    text = ('__PROCEDURE_ARTIFACT__ {"oracle_paths": ["y.py"], "report": {"ok": 1}}\n'
            '__PROCEDURE_ATTEST__ {"phase": "BUILD"}')
    apply_to_record(rec, text)
    assert rec["procedure_artifacts"]["oracle_paths"] == ["x.py", "y.py"]
    assert rec["procedure_artifacts"]["report"] == {"ok": 1}
    assert rec["procedure_attested"]["BUILD"] is True


def test_apply_to_record_noop_when_no_markers():
    rec = {"procedure_artifacts": {"oracle_path": "x.py"}}
    apply_to_record(rec, "ordinary assistant text")
    assert rec["procedure_artifacts"] == {"oracle_path": "x.py"}
    assert "procedure_attested" not in rec or rec["procedure_attested"] == {}
