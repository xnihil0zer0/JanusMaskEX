from __future__ import annotations
import pathlib
import pytest
from unittest.mock import patch, MagicMock

from harness.hooks import _state_gates
import harness.hooks._ledger

def test_plan_submitted_true():
    mock_events = [
        {"verb": "plan_draft", "outcome": "allow"},
        {"verb": "submit_code", "outcome": "allow"}
    ]
    with patch("harness.hooks._ledger.read_events", return_value=mock_events):
        assert _state_gates.plan_submitted("session_123", "agent_123") is True

def test_plan_submitted_false_no_events():
    mock_events = []
    with patch("harness.hooks._ledger.read_events", return_value=mock_events):
        assert _state_gates.plan_submitted("session_123", "agent_123") is False

def test_plan_submitted_false_different_outcome():
    mock_events = [
        {"verb": "plan_draft", "outcome": "deny"}
    ]
    with patch("harness.hooks._ledger.read_events", return_value=mock_events):
        assert _state_gates.plan_submitted("session_123", "agent_123") is False

def test_plan_submitted_false_different_verb():
    mock_events = [
        {"verb": "submit_code", "outcome": "allow"}
    ]
    with patch("harness.hooks._ledger.read_events", return_value=mock_events):
        assert _state_gates.plan_submitted("session_123", "agent_123") is False
