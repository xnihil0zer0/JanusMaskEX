"""Thin stdio MCP transport shim for session phase control.

This module is a pure transport over :class:`ngv2.session_api.SessionApi`.
It registers exactly three tools -- ``create_session``, ``submit_artifacts``
and ``transition`` -- each delegating straight through to the matching
``SessionApi`` method and returning that method's dict result unchanged.

Import purity is load-bearing here: at module top-level we import ONLY the
standard library and ``SessionApi``. The MCP SDK (``FastMCP``) is imported
lazily inside the ``if __name__ == "__main__":`` guard, so importing this
module never pulls ``mcp`` into ``sys.modules`` and has zero side effects --
no FastMCP construction, no bound socket, no server ``.run()``.
"""
from __future__ import annotations
from typing import Callable
from typing import Dict
from ngv2.session_api import SessionApi
from typing import Any

def build_tools(api: SessionApi) -> Dict[str, Callable[..., Any]]:
    """Build the MCP tool mapping for ``api``.

    The returned dict maps each tool name to a bound handler.  The four new
    lifecycle operations are always present; any other public ``SessionApi``
    methods are included additively so that existing tools continue to work.
    """
    tools: Dict[str, Callable[..., Any]] = {}
    for ident in _NEW_OPERATIONS:
        handler = getattr(api, ident, None)
        if callable(handler):
            tools[ident] = handler
    for ident in dir(api):
        if ident.startswith('_') or ident in tools:
            continue
        handler = getattr(api, ident, None)
        if callable(handler):
            tools[ident] = handler
    return tools
import os
import sys

def resolve_db_path(argv=None, env=None) -> str:
    if argv is None:
        argv = sys.argv
    if env is None:
        env = os.environ
    if argv is not None and len(argv) >= 2:
        return argv[1]
    value = env.get('NGV2_SESSION_DB')
    if value:
        return value
    return 'ngv2_session.db'
__all__ = ['build_tools']
_NEW_OPERATIONS = ('get_current_phase', 'get_parked_package', 'get_readiness_reason', 'advance')
'MCP tool surface for the session API.\n\nExposes the :class:`~ngv2.session_api.SessionApi` operations as a flat mapping\nof tool name to callable.  :func:`build_tools` is additively extended to export\nthe new read/advance operations (``get_current_phase``, ``get_parked_package``,\n``get_readiness_reason`` and ``advance``) alongside any pre-existing public\noperations on the API.\n\nThe module is pure and deterministic: it performs no I/O, network, randomness,\nor subprocess calls and imports only the standard library plus ``ngv2``.\n'
if __name__ == '__main__':
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        FastMCP = None
    if FastMCP is None:
        raise SystemExit("The 'mcp' SDK is required to run the session MCP server. Install it to launch the stdio transport.")
    from ngv2.session_db import SessionDB
    server = FastMCP('session_mcp')
    api = SessionApi(SessionDB(resolve_db_path()))
    for tool_name, handler in build_tools(api).items():
        server.tool(name=tool_name)(handler)
    server.run()