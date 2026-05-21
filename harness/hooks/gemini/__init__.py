"""Gemini-side hook entrypoints (P3).

Mirrors ``harness.hooks.claude`` one-for-one: every Claude hook has a
Gemini twin here that reads the same per-session ledger, enforces the
same allowlists, and writes the same canonical ``state/sessions/``
records via ``harness.hooks.rpc.*``. The asymmetries the plan calls out
(regex matchers, `deny` vs `block` vocabulary, `systemMessage` vs
`additionalContext`) are isolated inside these modules so the rest of
the harness sees one uniform contract across both agents.
"""
__version__ = '1.0.0'