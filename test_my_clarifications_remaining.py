from __future__ import annotations
import pytest
from unittest.mock import patch

from harness.hooks import _state_gates

def test_clarifications_remaining_none():
    with patch("harness.hooks._state_gates.clarifications_count", return_value=0):
        assert _state_gates.clarifications_remaining("session_123", "agent_123") == 2

def test_clarifications_remaining_some():
    with patch("harness.hooks._state_gates.clarifications_count", return_value=1):
        assert _state_gates.clarifications_remaining("session_123", "agent_123") == 1

def test_clarifications_remaining_max():
    with patch("harness.hooks._state_gates.clarifications_count", return_value=2):
        assert _state_gates.clarifications_remaining("session_123", "agent_123") == 0

def test_clarifications_remaining_exceeded():
    with patch("harness.hooks._state_gates.clarifications_count", return_value=3):
        assert _state_gates.clarifications_remaining("session_123", "agent_123") == 0
