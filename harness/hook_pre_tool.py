"""Shim — delegates to ``harness.hooks.claude.pre_tool.legacy_dispatch``
for the legacy MCP-era payload shape (just ``{tool_name}``) and to
``harness.hooks.claude.pre_tool.main`` for the new Claude Code
``hook_event_name`` envelope shape. Retire at P6
(HOOK-50-retire-mcp).

The legacy branch exists only to keep in-repo callers (the
``tests/test_hook_pre_tool.py`` suite and any lingering subprocess
invocation without the new schema) working; the authoritative logic
lives in ``harness.hooks.claude.pre_tool``.
"""
from __future__ import annotations
import io
import json
import os
import pathlib
import sys
_PROJECT_ROOT = str(pathlib.Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from harness.hooks import _common
from harness.hooks.claude.pre_tool import _LEGACY_ALLOWED_SUBAGENT_TOOLS as ALLOWED_SUBAGENT_TOOLS
from harness.hooks.claude.pre_tool import _LEGACY_ALLOWED_TOOLS as ALLOWED_TOOLS
from harness.hooks.claude.pre_tool import legacy_dispatch

def _legacy_dispatch(payload: dict) -> None:
    """Backward-compat wrapper that writes the decision to ``sys.stdout``.
    The authoritative implementation is
    ``harness.hooks.claude.pre_tool.legacy_dispatch``."""
    json.dump(legacy_dispatch(payload), sys.stdout)

def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            json.dump(_common.decision_payload('allow'), sys.stdout)
            return
        payload = json.loads(raw)
    except Exception as exc:
        json.dump(_common.decision_payload('deny', reason=f'Malformed hook input: {exc}'), sys.stdout)
        return
    if isinstance(payload, dict) and 'hook_event_name' in payload:
        from harness.hooks.claude.pre_tool import main as _new_main
        _new_main(io.StringIO(raw), sys.stdout)
        return
    if not isinstance(payload, dict):
        json.dump(_common.decision_payload('deny', reason='Malformed hook input: expected JSON object.'), sys.stdout)
        return
    json.dump(legacy_dispatch(payload), sys.stdout)
if __name__ == '__main__':
    main()