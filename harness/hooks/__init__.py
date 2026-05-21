"""JanusMask worker-side hook scaffold.

Shared helpers for Claude Code + Gemini CLI hook entrypoints. Phases 2-3 will
plug `claude/` and `gemini/` event scripts on top. Phase 1 (this scaffold) only
adds pure-new modules; MCP path remains authoritative.

Layout (per hooks-implementation-plan.md Phase 1 + sub-plan 02 §3.2):
    _common        -- stdin/stdout JSON envelope + unified decision vocab
    _paths         -- env resolution + safe_subpath wrapper
    _ledger        -- per-session append-only JSONL journal
    _state_gates   -- STATE.json reader + ledger-backed counters
"""
