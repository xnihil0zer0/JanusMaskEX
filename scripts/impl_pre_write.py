#!/usr/bin/env python3
"""PreToolUse:Write|Edit meta-hook. Five gates, any deny short-circuits.

See hooks-augmented-hooks-implementation-plan.md §3.2.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from impl_common import (
    PROJECT_DIR,
    derive_state,
    load_ledger,
    path_in_allow,
    phase_allow_globs,
    recent_start_for_path,
    task_manifest,
    _glob_match,
)


def _coerce_paths(raw) -> list[str]:
    """Coerce a row's `paths` field into a list[str].

    Defensive against hostile / malformed producers: if `paths` is a bare
    string, wrap it in a single-element list instead of iterating its
    characters; if it's None or missing, return []; otherwise list() it.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    try:
        return [s for s in raw if isinstance(s, str)]
    except TypeError:
        return []


def _canon(path: str) -> str:
    """Canonicalise a path string for scope_exception/scope_revoke matching.

    Uses os.path.normpath to collapse `./`, `//`, and `/./` segments so
    string equality works across equivalent spellings. normpath is a pure
    string operation and leaves glob metacharacters (`*`, `**`, `?`)
    untouched.
    """
    if not path:
        return path
    return os.path.normpath(path)


def _revoke_matches_exception_path(rev_path: str, exc_path: str) -> bool:
    """Return True if a scope_revoke path cancels a scope_exception path.

    Matching rules (after canonicalisation):
      1. Exact string equality (handles `./`, `//`, `/./` normalisation).
      2. A specific-file revoke path matches the exception's wildcard
         pattern via `_glob_match` (punches a hole in wildcard scopes).
      3. A wildcard revoke pattern matches the specific exception path.
    """
    r = _canon(rev_path)
    e = _canon(exc_path)
    if r == e:
        return True
    # Glob-aware cancellation: either side may contain wildcards.
    has_wild_e = any(c in e for c in "*?[")
    has_wild_r = any(c in r for c in "*?[")
    if has_wild_e and not has_wild_r:
        if _glob_match(r, e):
            return True
    if has_wild_r and not has_wild_e:
        if _glob_match(e, r):
            return True
    return False


def _read_scope_revokes(ledger: list[dict]) -> list[dict]:
    """Return scope_revoke rows from the last-150-row window.

    Each returned dict preserves the raw row (including `ts` and `paths`) so
    callers can correlate revokes with earlier exceptions. Mirrors the
    last-150-row window used by scope_exception_paths().
    """
    out: list[dict] = []
    for row in ledger[-150:]:
        if not isinstance(row, dict):
            continue
        if row.get("event") == "scope_revoke":
            out.append(row)
    return out


def _effective_scope_exception_paths(ledger: list[dict]) -> list[str]:
    """Compute scope_exception paths within the last-150-row window, with
    per-path cancellation applied.

    A scope_revoke row cancels a scope_exception row's contribution for any
    path it names, provided the revoke appears LATER in the window and its
    ts is at least as new as the exception's ts (ts-ties broken by ledger
    position). Cancellation is per-path: a revoke naming [A] closes any
    earlier exception for A without affecting other paths that exception
    also opened.

    Path comparison is canonicalised via os.path.normpath (collapsing
    `./`, `//`, and `/./`) and is glob-aware: a specific-file revoke
    matching a wildcard exception pattern cancels that wildcard entry.
    """
    window = ledger[-150:] if ledger else []
    effective: list[str] = []
    for i, row in enumerate(window):
        if not isinstance(row, dict):
            continue
        if row.get("event") != "scope_exception":
            continue
        exc_ts = row.get("ts", "") or ""
        exc_paths = _coerce_paths(row.get("paths"))
        for p in exc_paths:
            revoked = False
            for j in range(i + 1, len(window)):
                later = window[j]
                if not isinstance(later, dict):
                    continue
                if later.get("event") != "scope_revoke":
                    continue
                rev_ts = later.get("ts", "") or ""
                # ts-tie: later-in-ledger satisfies "at least as new".
                if rev_ts < exc_ts:
                    continue
                rev_paths = _coerce_paths(later.get("paths"))
                if any(_revoke_matches_exception_path(rp, p) for rp in rev_paths):
                    revoked = True
                    break
            if not revoked:
                effective.append(p)
    return effective

CRITICAL_PATHS = {
    ".claude/settings.local.json",
    ".claude/settings.json",
    "harness/config.yaml",
}


def _deny(reason: str) -> None:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(out))
    sys.exit(0)


def _allow() -> None:
    sys.exit(0)


# Cross-session auto-memory root: Claude writes persistent memory files here,
# outside PROJECT_DIR. Permitted as a second allowed root; all other gates
# (phase-scope, AST, CRITICAL_PATHS, etc.) are skipped for paths under it.
# Slug derives from PROJECT_DIR per Claude Code convention (path with / -> -).
_MEMORY_SLUG = "-" + str(PROJECT_DIR.resolve()).replace("/", "-").lstrip("-")
MEMORY_DIR = pathlib.Path.home() / ".claude" / "projects" / _MEMORY_SLUG / "memory"


def _rel_to_project(file_path: str) -> str | None:
    try:
        abs_path = pathlib.Path(file_path)
        if not abs_path.is_absolute():
            abs_path = (PROJECT_DIR / abs_path).resolve()
        else:
            abs_path = abs_path.resolve()
        rel = abs_path.relative_to(PROJECT_DIR.resolve())
        return str(rel)
    except (ValueError, OSError):
        return None


def _introduces_new_public_symbol(content: str) -> bool:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                return True
    return False


def _expected_test_path(rel_path: str) -> str:
    base = pathlib.Path(rel_path).stem
    return f"tests/test_{base}.py"


def _content_from_input(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Write":
        return tool_input.get("content", "") or ""
    if tool_name == "Edit":
        return tool_input.get("new_string", "") or ""
    return ""


def _scope_exception_write_errors(content: str) -> list[str]:
    """Inspect ledger content for malformed scope_exception rows.

    Scans ``content`` for JSONL rows whose ``event`` field is
    ``scope_exception`` and returns a list of human-readable error strings
    for rows that omit ``paths``, have ``paths`` set to None, or whose
    ``paths`` is not a non-empty list of strings. Rows that do not parse
    as JSON are ignored (Edit often carries fragments); the caller is
    expected to gate only when writing the ledger file.

    Historical six rows (2026-04-17 / 2026-04-20 with task_ids
    META-01-plan-addendum, HOOK-14-*, HOOK-20-*, and three empty-task_id
    B3 handoff rows) were appended with paths absent or None and silently
    authorised nothing. This helper blocks future rows of that shape.
    """
    errors: list[str] = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(row, dict):
            continue
        if row.get("event") != "scope_exception":
            continue
        if "paths" not in row:
            errors.append(
                f"scope_exception row missing 'paths' key "
                f"(ts={row.get('ts')} task_id={row.get('task_id')})"
            )
            continue
        paths = row.get("paths")
        if paths is None:
            errors.append(
                f"scope_exception row with paths=None "
                f"(ts={row.get('ts')} task_id={row.get('task_id')})"
            )
            continue
        if not isinstance(paths, list) or not paths:
            errors.append(
                f"scope_exception row requires non-empty list paths "
                f"(ts={row.get('ts')} task_id={row.get('task_id')} "
                f"type={type(paths).__name__})"
            )
            continue
        if not all(isinstance(p, str) for p in paths):
            errors.append(
                f"scope_exception row paths must be list of strings "
                f"(ts={row.get('ts')} task_id={row.get('task_id')})"
            )
    return errors


def main() -> int:
    try:
        raw = sys.stdin.read()
        inp = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        _allow()

    tool_name = inp.get("tool_name", "")
    tool_input = inp.get("tool_input", {}) or {}
    file_path = tool_input.get("file_path", "") or ""
    if not file_path:
        _allow()

    # Allow writes under the cross-session auto-memory dir unconditionally;
    # all other gates below are skipped for paths under MEMORY_DIR.
    try:
        pathlib.Path(file_path).resolve().relative_to(MEMORY_DIR.resolve())
        _allow()
    except (ValueError, OSError):
        pass

    rel_path = _rel_to_project(file_path)
    if rel_path is None:
        _deny(f"Write target {file_path} is outside project directory {PROJECT_DIR}.")

    content = _content_from_input(tool_name, tool_input)

    # Gate 0: ledger write-integrity. Reject any Write/Edit to
    # state/impl_progress.jsonl whose new content contains a
    # scope_exception row with missing/None/non-list paths. Historical
    # drift left six such rows in the ledger; this gate blocks future
    # regressions (read-side warning lives in
    # scripts/impl_common.scope_exception_paths).
    if rel_path == "state/impl_progress.jsonl" and content:
        sx_errors = _scope_exception_write_errors(content)
        if sx_errors:
            _deny(
                "scope_exception ledger row requires a non-empty 'paths' list: "
                + "; ".join(sx_errors)
            )

    ledger = load_ledger()
    state = derive_state(ledger)
    phase = state["current_phase"] or "META"
    current_task = state["current_task_id"]

    # Gate 1: phase-scope allow-list (with scope_exception bypass, honouring
    # any scope_revoke rows that closed those exceptions within the window).
    sx = _effective_scope_exception_paths(ledger)
    sx_hit = any(_glob_match(rel_path, p) for p in sx)
    if not sx_hit:
        manifest = task_manifest(current_task) if current_task else {}
        task_globs = manifest.get("scope_globs") or []
        if task_globs and not path_in_allow(rel_path, task_globs):
            _deny(
                f"Task {current_task} scope_globs {task_globs} do not permit {rel_path}. "
                f"Close out this task or append a scope_exception ledger row."
            )
        allow_globs = phase_allow_globs(phase)
        if not path_in_allow(rel_path, allow_globs):
            _deny(
                f"Phase {phase} only permits writes under {allow_globs}; "
                f"{rel_path} is out of scope. Close current task first, or append a "
                f"scope_exception ledger row paired with a human_gate task pointer."
            )

    # Gate 2: Python AST parse gate. For Edit, parse the resulting full
    # file (snippet-in-isolation rejects valid mid-function indentation).
    # For Write, `content` IS the full file, so parse it directly.
    if rel_path.endswith(".py") and content:
        parse_src = content
        if tool_name == "Edit":
            old = tool_input.get("old_string", "") or ""
            if old:
                try:
                    disk = (PROJECT_DIR / rel_path).read_text(encoding="utf-8")
                    if tool_input.get("replace_all"):
                        if old in disk:
                            parse_src = disk.replace(old, content)
                    elif disk.count(old) == 1:
                        parse_src = disk.replace(old, content, 1)
                    # else: ambiguous (>1) or absent (0) - Claude Code's
                    # own Edit uniqueness check will fail; fall back to
                    # snippet parse so we still catch obvious syntax junk.
                except OSError:
                    pass
        try:
            ast.parse(parse_src)
        except SyntaxError as e:
            lineno = getattr(e, "lineno", "?")
            offset = getattr(e, "offset", "?")
            _deny(
                f"Python AST parse failed for {rel_path} at line {lineno}, col {offset}: "
                f"{e.msg}. Fix the syntax before writing."
            )

    # Gate 3: test-partner gate for new public symbols under harness/.
    if rel_path.startswith("harness/") and rel_path.endswith(".py") and content:
        if _introduces_new_public_symbol(content):
            test_rel = _expected_test_path(rel_path)
            if not (PROJECT_DIR / test_rel).exists():
                # Allow if ANY test file in tests/ imports this module path.
                module_path = rel_path.replace("/", ".").removesuffix(".py")
                tests_dir = PROJECT_DIR / "tests"
                found = False
                if tests_dir.exists():
                    for py in tests_dir.rglob("test_*.py"):
                        try:
                            if module_path in py.read_text(encoding="utf-8", errors="ignore"):
                                found = True
                                break
                        except OSError:
                            continue
                if not found:
                    _deny(
                        f"New public symbol introduced in {rel_path} but no test module "
                        f"found at {test_rel} or elsewhere under tests/. "
                        f"Create the test file first."
                    )

    # Gate 4: settings-mutation gate.
    if rel_path in CRITICAL_PATHS:
        recent = recent_start_for_path(ledger, window_seconds=600)
        if recent is None:
            _deny(
                f"{rel_path} is meta-config; edits require a ledger 'start' row within the "
                f"last 10 minutes authorising this edit. None found."
            )

    # Gate 5: enforce-flag coherence gate.
    if rel_path == "harness/config.yaml" and content:
        if re.search(r"hooks:\s*(?:\n\s+.*)*\n\s*mode:\s*enforce", content):
            gate_rows = [
                r for r in ledger
                if r.get("event") == "phase_gate_pass" and r.get("phase") == "P5"
            ]
            if not gate_rows:
                _deny(
                    "Setting hooks.mode: enforce requires Phase 5 shadow gate to have passed. "
                    "No P5 phase_gate_pass in ledger."
                )

    _allow()


if __name__ == "__main__":
    sys.exit(main() or 0)
