from __future__ import annotations
import json
import pytest
from unittest.mock import patch, MagicMock

import harness.hooks._decide_common as dc
from harness.hooks._decide_common import DeciderContext, decide_plan_draft

class _Journal:
    def __init__(self):
        self.calls = []

    def __call__(self, verb, outcome, detail=None):
        self.calls.append((verb, outcome, detail))

def _make_ctx(journal):
    return DeciderContext(
        session_id="sess-test",
        agent="claude",
        phase="planning",
        round_number=1,
        journal=journal,
        allow_with_warnings=lambda warnings: {"warned": warnings},
    )

def test_decide_plan_draft_already_submitted():
    journal = _Journal()
    events = [{"verb": "plan_draft", "outcome": "allow"}]
    
    with patch("harness.hooks._ledger.has_verb", return_value=True) as mock_has_verb, \
         patch("harness.hooks._common.decision_payload", return_value={"decision": "deny", "reason": "plan_draft already submitted (single-shot per round)."}) as mock_payload:
        
        result = decide_plan_draft(_make_ctx(journal), '{"plan": "test"}', events)
        
        mock_has_verb.assert_called_once_with(events, "plan_draft", outcome="allow")
        assert result["decision"] == "deny"
        assert journal.calls == [("plan_draft", "deny", {"reason": "plan_draft already submitted (single-shot per round)."})]

def test_decide_plan_draft_invalid_json():
    journal = _Journal()
    events = []
    
    with patch("harness.hooks._ledger.has_verb", return_value=False), \
         patch("harness.hooks._common.decision_payload", side_effect=lambda dec, *, reason="", **kwargs: {"decision": dec, "reason": reason}):
        
        result = decide_plan_draft(_make_ctx(journal), '{invalid json', events)
        
        assert result["decision"] == "deny"
        assert "plan_draft content must be valid JSON:" in result["reason"]
        assert len(journal.calls) == 1
        assert journal.calls[0][0] == "plan_draft"
        assert journal.calls[0][1] == "invalid"
        assert "plan_draft content must be valid JSON:" in journal.calls[0][2]["reason"]

def test_decide_plan_draft_validation_fails():
    journal = _Journal()
    events = []
    
    fake_violations = [{"code": "E1", "path": "root", "message": "error msg"}]
    fake_payload = {"error": "plan_draft validation failed.", "violations": fake_violations}
    
    with patch("harness.hooks._ledger.has_verb", return_value=False), \
         patch("harness.hooks.rpc.submit_plan_draft.validate", return_value=fake_violations, create=True) as mock_validate, \
         patch("harness.hooks.rpc.submit_plan_draft.rejected_payload", return_value=fake_payload, create=True) as mock_rejected_payload, \
         patch("harness.hooks._common.decision_payload", side_effect=lambda dec, *, reason="", **kwargs: {"decision": dec, "reason": reason}):
        
        result = decide_plan_draft(_make_ctx(journal), '{"plan": "bad"}', events)
        
        mock_validate.assert_called_once_with({"plan": "bad"})
        mock_rejected_payload.assert_called_once_with(fake_violations, max_show=50)
        assert result["decision"] == "deny"
        assert "plan_draft validation failed.\n- [E1] root: error msg" in result["reason"]
        assert journal.calls == [("plan_draft", "deny", {"violation_count": 1})]

def test_decide_plan_draft_success():
    journal = _Journal()
    events = []
    
    with patch("harness.hooks._ledger.has_verb", return_value=False), \
         patch("harness.hooks.rpc.submit_plan_draft.validate", return_value=[], create=True), \
         patch("harness.hooks._common.decision_payload", return_value={"decision": "allow"}):
        
        result = decide_plan_draft(_make_ctx(journal), '{"plan": "good"}', events)
        
        assert result["decision"] == "allow"
        assert journal.calls == []
