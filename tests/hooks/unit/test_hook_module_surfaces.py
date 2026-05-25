"""Parametrised module-surface stability tests for Claude + Gemini hook modules.

Consolidates 11 copies of `test_module_surface_stable()` that previously lived
scattered across tests/hooks/unit/test_{claude,gemini}_*.py. Each copy asserted
hasattr() for a short list of public names — exactly the shape pytest.parametrize
is designed for.

The orchestrator rewire in P4 grep-imports these names; renames without a
corresponding edit here should surface as a parametrized failure with the
module_path of the offending import.

Idiosyncratic content assertions (Gemini worker allowlist must admit
"write_file" / "replace") live as a separate non-parametrised test below.

M3-4 / fix plan §2.3 / handoff wave W11.
"""
from __future__ import annotations

import importlib

import pytest


_SURFACES: list[tuple[str, tuple[str, ...]]] = [
    # Claude hook modules
    ("harness.hooks.claude.pre_tool", ("main", "ALLOWED_TOOLS")),
    ("harness.hooks.claude.post_tool", ("main",)),
    ("harness.hooks.claude.stop", ("main", "MANDATORY_VERBS")),
    ("harness.hooks.claude.session_start", ("main", "build_additional_context")),
    ("harness.hooks.claude.user_prompt_submit", ("main", "build_locked_fields_reminder")),
    ("harness.hooks.claude.pre_compact", ("main",)),
    ("harness.hooks.claude._env", ("inbox_ready", "ensure_workdir_skeleton", "INBOX_EXPECTATIONS")),
    # Gemini hook modules
    ("harness.hooks.gemini.pre_tool", ("main", "ALLOWED_TOOLS")),
    ("harness.hooks.gemini.post_tool", ("main",)),
    ("harness.hooks.gemini.stop", ("main", "MANDATORY_VERBS")),
    ("harness.hooks.gemini.session_start", ("main", "build_system_message")),
    ("harness.hooks.gemini.user_prompt_submit", ("main", "build_locked_fields_reminder")),
    (
        "harness.hooks.gemini._env",
        ("inbox_ready", "ensure_workdir_skeleton", "INBOX_EXPECTATIONS", "folder_trust_enabled"),
    ),
]


@pytest.mark.parametrize("module_path, expected_exports", _SURFACES)
def test_module_surface_stable(module_path: str, expected_exports: tuple[str, ...]) -> None:
    mod = importlib.import_module(module_path)
    for attr in expected_exports:
        assert hasattr(mod, attr), f"{module_path} missing public attribute {attr!r}"


def test_gemini_pre_tool_allowed_tools_content() -> None:
    pt_mod = importlib.import_module("harness.hooks.gemini.pre_tool")
    assert "write_file" in pt_mod.ALLOWED_TOOLS
    assert "replace" in pt_mod.ALLOWED_TOOLS
