from typing import Any

def decision_payload(decision: str, *, reason: str='', additional_context: str='', tool_input: dict | None=None) -> dict[str, Any]:
    payload: dict[str, Any] = {"decision": _normalise_decision(decision)}
    return payload
