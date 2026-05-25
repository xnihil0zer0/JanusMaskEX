from __future__ import annotations
import pytest
from harness.hooks._common import decision_payload

def test_decision_payload_allow_minimal_envelope():
    """A bare allow decision yields exactly {"decision": "allow"}."""
    result = decision_payload("allow")
    assert result == {"decision": "allow"}

def test_decision_payload_deny_minimal_envelope():
    """A bare deny decision yields exactly {"decision": "deny"}."""
    result = decision_payload("deny")
    assert result == {"decision": "deny"}

def test_decision_payload_minimal_has_only_decision_key():
    """With no optional args, the only key present is "decision"."""
    result = decision_payload("allow")
    assert set(result) == {"decision"}

def test_decision_payload_normalises_uppercase_decision():
    """Decision tokens are lower-cased: "ALLOW" -> "allow"."""
    assert decision_payload("ALLOW")["decision"] == "allow"
    assert decision_payload("DENY")["decision"] == "deny"

def test_decision_payload_normalises_mixed_case_and_whitespace():
    """Surrounding whitespace is stripped and case folded before storing."""
    assert decision_payload("  Allow  ")["decision"] == "allow"
    assert decision_payload("\tDeny\n")["decision"] == "deny"

def test_decision_payload_unknown_decision_raises_value_error():
    """A token outside {allow, deny} propagates a ValueError."""
    with pytest.raises(ValueError):
        decision_payload("maybe")

def test_decision_payload_empty_decision_raises_value_error():
    """An empty string normalises to "" which is not a valid decision."""
    with pytest.raises(ValueError):
        decision_payload("")

def test_decision_payload_whitespace_only_decision_raises_value_error():
    """Whitespace strips to "" and is rejected."""
    with pytest.raises(ValueError):
        decision_payload("   ")

def test_decision_payload_includes_truthy_reason():
    """A non-empty reason is stored under the "reason" key."""
    result = decision_payload("deny", reason="not allowed")
    assert result["reason"] == "not allowed"
    assert result == {"decision": "deny", "reason": "not allowed"}

def test_decision_payload_omits_empty_reason_by_default():
    """The default empty reason is falsy and therefore omitted."""
    result = decision_payload("allow")
    assert "reason" not in result

def test_decision_payload_omits_explicit_empty_reason():
    """An explicitly passed empty reason is still omitted (truthiness check)."""
    result = decision_payload("allow", reason="")
    assert "reason" not in result

def test_decision_payload_includes_additional_context_as_camelcase_key():
    """A non-empty additional_context is stored under "additionalContext"."""
    result = decision_payload("allow", additional_context="extra info")
    assert result["additionalContext"] == "extra info"
    assert "additional_context" not in result

def test_decision_payload_omits_empty_additional_context():
    """An empty additional_context is falsy and therefore omitted."""
    result = decision_payload("allow", additional_context="")
    assert "additionalContext" not in result
    assert result == {"decision": "allow"}

def test_decision_payload_includes_tool_input_dict():
    """A provided tool_input dict is stored verbatim under "tool_input"."""
    ti = {"command": "ls", "args": ["-l"]}
    result = decision_payload("allow", tool_input=ti)
    assert result["tool_input"] == {"command": "ls", "args": ["-l"]}

def test_decision_payload_tool_input_stored_by_reference():
    """The tool_input object is stored as-is, not copied."""
    ti = {"k": "v"}
    result = decision_payload("allow", tool_input=ti)
    assert result["tool_input"] is ti

def test_decision_payload_omits_tool_input_when_none():
    """The default tool_input of None is omitted entirely."""
    result = decision_payload("allow")
    assert "tool_input" not in result

def test_decision_payload_includes_empty_dict_tool_input():
    """An empty dict is not None, so it is included despite being falsy."""
    result = decision_payload("allow", tool_input={})
    assert "tool_input" in result
    assert result["tool_input"] == {}

def test_decision_payload_all_fields_combined():
    """All optional fields appear together with their correct keys."""
    result = decision_payload(
        "DENY",
        reason="blocked",
        additional_context="ctx",
        tool_input={"x": 1},
    )
    assert result == {
        "decision": "deny",
        "reason": "blocked",
        "additionalContext": "ctx",
        "tool_input": {"x": 1},
    }

def test_decision_payload_returns_fresh_dict_each_call():
    """Each call builds an independent dict, not a shared/mutated singleton."""
    first = decision_payload("allow")
    second = decision_payload("allow")
    assert first is not second
    first["mutated"] = True
    assert "mutated" not in second
