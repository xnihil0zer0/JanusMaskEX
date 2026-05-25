"""Shared verb implementations for MCP + Claude/Gemini hook entrypoints.

Extracted from `harness.mcp_server.cmd_*` at HOOK-11 so both sides call a
single source of truth for validation + persistence + response shapes.
State counters, console streaming, and inbox gates remain caller-side.
"""
__version__ = '1.0.0'