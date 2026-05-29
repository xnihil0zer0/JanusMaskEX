"""Adversarial pins — harness/interceptors.py registry wiring (Plan 04, CASE-J).

Targets:
  1/2. registry.pre_tool_use('claude','submit_code',...) denies AST-bad code,
       returns None for clean code.
  3.   registry.pre_invocation(...) is a no-op (no built-in implements it) —
       documents the spawn-time hook does nothing.
  4.   GAP-3: BashSafetyInterceptor.pre_tool_use is UNREACHABLE via the only
       live caller (orchestrator passes tool_name='submit_code', which the
       bash interceptor's guard excludes) -> always returns None.
  5.   GAP-4: BashSafetyInterceptor falls back to a FOREIGN hardcoded workspace
       '/home/xnihil0zer0/NobleJanus' (line 95) when JANUSMASK_PROJECT_DIR is
       unset — must not crash, but flag the non-portable path.
"""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from harness.interceptors import (  # noqa: E402
    ASTVerificationInterceptor,
    BashSafetyInterceptor,
    registry,
)

_AST_BAD = "def broken(\n"  # syntax error -> AST verifier ERROR
_AST_CLEAN = "def ok():\n    return 1\n"


class TestRegistrySubmitCodeWiring:
    def test_registry_denies_ast_bad_submit_code(self):
        res = registry.pre_tool_use("claude", "submit_code", {"code": _AST_BAD})
        assert res is not None and res["decision"] == "deny"

    def test_registry_allows_clean_submit_code(self):
        res = registry.pre_tool_use("claude", "submit_code", {"code": _AST_CLEAN})
        assert res is None

    def test_pre_invocation_is_noop(self):
        # No built-in implements pre_invocation; registry must return None and
        # never raise. Documents that the orchestrator.py:291 spawn hook is dead.
        assert registry.pre_invocation("claude", "some prompt", {}) is None


class TestBashInterceptorUnreachableViaSubmitCode:
    def test_bash_interceptor_returns_none_for_submit_code(self):
        """GAP-3: the only live caller passes tool_name='submit_code'; the bash
        interceptor's guard only fires for Bash/execute_command/
        mcp__janusmask__execute, so it is UNREACHABLE in the orchestrator path."""
        bi = BashSafetyInterceptor()
        out = bi.pre_tool_use("claude", "submit_code", {"command": "rm -rf /"})
        assert out is None, "bash interceptor unexpectedly fired for submit_code"

    def test_registry_routes_submit_code_only_to_ast_not_bash(self):
        # A submit_code with a dangerous 'command' key but AST-clean 'code'
        # must NOT be denied — proving bash logic never runs for submit_code.
        res = registry.pre_tool_use(
            "claude", "submit_code",
            {"code": _AST_CLEAN, "command": "rm -rf /"},
        )
        assert res is None


class TestBashInterceptorForeignFallback:
    def test_no_project_dir_does_not_crash_uses_foreign_path(self, monkeypatch):
        """GAP-4: with JANUSMASK_PROJECT_DIR unset the workspace fallback is the
        foreign '/home/xnihil0zer0/NobleJanus'. Assert no crash and a decision is
        produced; flag the hardcoded foreign path in the source."""
        monkeypatch.delenv("JANUSMASK_PROJECT_DIR", raising=False)
        monkeypatch.delenv("JANUSMASK_PERMISSION_MODE", raising=False)
        bi = BashSafetyInterceptor()
        # Must not raise even though the workspace dir likely doesn't exist.
        out = bi.pre_tool_use("claude", "Bash", {"command": "ls -la"})
        # validate_command returns allow(None)/warn/deny — any is fine; key is no crash.
        assert out is None or out.get("decision") in ("allow", "deny")

    def test_source_still_hardcodes_foreign_path(self):
        import inspect
        src = inspect.getsource(BashSafetyInterceptor.pre_tool_use)
        assert "/home/xnihil0zer0/NobleJanus" in src, (
            "GAP-4 source pin: if this fails the foreign hardcoded fallback was "
            "fixed — update or drop this characterization assertion"
        )
        from harness.paths import PROJECT_ROOT_STR
        assert PROJECT_ROOT_STR not in src, (
            "bash interceptor still does NOT use PROJECT_ROOT for its fallback"
        )
