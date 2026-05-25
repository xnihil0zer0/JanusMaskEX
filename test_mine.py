from __future__ import annotations
import pytest
from typing import Any
from harness.hooks._decide_common import DeciderContext, decide_error_report, ERROR_MAX_BYTES
import harness.hooks._common

class MockJournal:
    def __init__(self):
        self.calls = []

    def __call__(self, verb: str, outcome: str, detail: dict[str, Any] | None = None):
        self.calls.append((verb, outcome, detail))

def make_ctx(journal):
    return DeciderContext(
        session_id="sess-123",
        agent="gemini",
        phase="synthesis",
        round_number=1,
        journal=journal,
        allow_with_warnings=lambda warnings: {"warned": warnings}
    )

def test_decide_error_report_allow():
    journal = MockJournal()
    ctx = make_ctx(journal)
    content = "Hello World"
    result = decide_error_report(ctx, content)
    
    assert result == {"decision": "allow"}
    assert len(journal.calls) == 0

def test_decide_error_report_deny():
    journal = MockJournal()
    ctx = make_ctx(journal)
    content = "A" * (ERROR_MAX_BYTES + 1)
    result = decide_error_report(ctx, content)
    
    expected_reason = f"error.md exceeds 64 KB cap ({ERROR_MAX_BYTES + 1} bytes > {ERROR_MAX_BYTES})."
    assert result == {"decision": "deny", "reason": expected_reason}
    assert journal.calls == [("error", "deny", {"size": ERROR_MAX_BYTES + 1})]

def test_decide_error_report_exact_boundary():
    journal = MockJournal()
    ctx = make_ctx(journal)
    content = "A" * ERROR_MAX_BYTES
    result = decide_error_report(ctx, content)
    
    assert result == {"decision": "allow"}
    assert len(journal.calls) == 0
