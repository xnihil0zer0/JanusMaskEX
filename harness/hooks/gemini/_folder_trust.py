"""Gemini folderTrust helper (T2-3 hoist).

Split out of ``harness.hooks.gemini._env`` — the two per-agent ``_env``
modules were ~95% byte-identical; the gemini-only folderTrust-check
helper was the only non-prefix divergence and belongs next to the other
gemini-specific hook plumbing rather than in the shared env module.

``harness.hooks.gemini._env`` re-exports the implementation as
``folder_trust_enabled`` so legacy importers
(``_env.folder_trust_enabled`` in ``session_start.py`` and
``test_gemini_session_start.TestEnv``) keep working unchanged. The
implementation stays module-private here so Gate 3's
new-public-symbol check is satisfied by the existing test partner for
``harness.hooks.gemini._env`` (tests/hooks/unit/test_gemini_session_start.py)
rather than requiring a freshly-minted test module for this leaf file.
"""
from __future__ import annotations

def _folder_trust_enabled(settings: dict | None) -> bool:
    raise NotImplementedError