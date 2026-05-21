"""Claude-worker hook entrypoints (P2 of the MCP → hooks migration).

Each module under this package is invoked by Claude Code as a hook
command: SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop,
PreCompact. Shared path/env helpers live in `_env`; the RPC verbs
themselves (`submit_code`, `submit_plan_draft`, ...) are reused from
`harness.hooks.rpc`.
"""
