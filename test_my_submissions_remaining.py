from __future__ import annotations
import pathlib
import pytest
from unittest.mock import patch, MagicMock

from harness.hooks import _state_gates
import harness.hooks._ledger

def test_submissions_remaining_none():
    with patch("harness.hooks._state_gates.submissions_count", return_value=0):
        assert _state_gates.submissions_remaining("session_123", "agent_123") == 5

def test_submissions_remaining_some():
    with patch("harness.hooks._state_gates.submissions_count", return_value=2):
        assert _state_gates.submissions_remaining("session_123", "agent_123") == 3

def test_submissions_remaining_max():
    with patch("harness.hooks._state_gates.submissions_count", return_value=5):
        assert _state_gates.submissions_remaining("session_123", "agent_123") == 0

def test_submissions_remaining_exceeded():
    with patch("harness.hooks._state_gates.submissions_count", return_value=6):
        assert _state_gates.submissions_remaining("session_123", "agent_123") == 0
