"""Regression-lock oracle for ngv2.human_checkpoint_gate.check_human_approval.

Locks the committed human-in-the-loop gate: check_human_approval(path) -> bool
returns False for a missing file and reads an explicit approval token from a
JSON decision file. Fail-closed (no auto-approve). Deterministic, never raises.
"""
import inspect
import json

from ngv2.human_checkpoint_gate import check_human_approval, _approval_from_json


def test_signature():
    assert list(inspect.signature(check_human_approval).parameters) == ["decision_filepath"]


def test_missing_file_is_not_approved():
    assert check_human_approval("/no/such/decision/file.json") is False


def test_approved_json_file_is_approved(tmp_path):
    p = tmp_path / "decision.json"
    p.write_text(json.dumps({"approved": True}))
    assert check_human_approval(str(p)) is True


def test_denied_json_file_is_not_approved(tmp_path):
    p = tmp_path / "decision.json"
    p.write_text(json.dumps({"approved": False}))
    assert check_human_approval(str(p)) is False


def test_approval_from_json_helper():
    assert _approval_from_json({"approved": True}) is True
    assert _approval_from_json({"approved": False}) is False
