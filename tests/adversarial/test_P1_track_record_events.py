"""Adversarial battery for HOOK-14-track-record-ast-events.

Mutation-style tests that pin the call-site wiring in
JanusMaskServer.cmd_submit_code so that a regression which drops the
``emit_ast_rejection`` / ``emit_clean_success`` calls fails at least one test.

Coverage axes (hooks-implementation-plan.md §Phase 1 item 5,
sub-plan-04 §3.8 / §5 step 14):

    1. emit_ast_rejection / emit_clean_success are direct attributes on
       harness.hooks.rpc.submit_code (not bound via a name alias).
    2. MCP's cmd_submit_code source references both helpers.
    3. Deny path — invalid code triggers ast_rejection row in
       track_record_events.jsonl, with delta {failures:1, attempts:1}.
    4. Allow path — valid code triggers clean_success row with
       delta {failures:0, attempts:1}.
    5. Missing / unknown synthesis_target_type never blocks the verb: the
       rejection payload still returns and the verb still persists.
"""

from __future__ import annotations

import inspect
import json
import pathlib

import pytest

import harness.hooks.rpc.submit_code as submit_code_mod
import harness.mcp_server as mcp_mod


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


_REAL_STATE_DIR = REPO_ROOT.parent.parent / "state"  # fallback, overridden below
for _cand in (REPO_ROOT / "state", REPO_ROOT.parent / "state"):
    if _cand.exists():
        _REAL_STATE_DIR = _cand
        break


def _seed_taxonomy(state_dir: pathlib.Path) -> None:
    """Copy the repo taxonomy files into the test state dir so
    track_record_events.append_track_event's validator can resolve synthesis-target
    and meta-task keys."""
    real = REPO_ROOT / "state"
    for name in ("synthesis_target_taxonomy.json", "meta_task_taxonomy.json"):
        src_path = real / name
        if src_path.exists():
            (state_dir / name).write_text(src_path.read_text(encoding="utf-8"),
                                          encoding="utf-8")


def _write_task(state_dir: pathlib.Path, *, task_id: str, target_type: str,
                deterministic: bool = True) -> None:
    _seed_taxonomy(state_dir)
    tasks = state_dir / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    # Post-RP7: per-task spec path; helper writes to current_task_<task_id>.json
    # so cmd_submit_code's post-glob-miss fallback (which uses JANUSMASK_TASK_ID
    # via task_paths.current_task_spec_path) finds the spec.
    (tasks / f"current_task_{task_id}.json").write_text(json.dumps({
        "task_id": task_id,
        "synthesis_target_type": target_type,
        "constraints": {"deterministic": deterministic},
    }), encoding="utf-8")


def _read_events(state_dir: pathlib.Path) -> list[dict]:
    path = state_dir / "track_record_events.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


# ---------- Surface-presence pins ----------------------------------------


class TestHelperSurfacePresent:
    def test_emit_ast_rejection_is_present(self):
        assert hasattr(submit_code_mod, "emit_ast_rejection")
        assert callable(submit_code_mod.emit_ast_rejection)

    def test_emit_clean_success_is_present(self):
        assert hasattr(submit_code_mod, "emit_clean_success")
        assert callable(submit_code_mod.emit_clean_success)


class TestMcpCallSiteReferencesBothHelpers:
    """Source-level regression guard — the MCP rewrite must continue to call
    both helpers. Using inspect rather than runtime interception so a
    refactor that inlines the calls still trips this test."""

    def test_cmd_submit_code_source_mentions_emit_ast_rejection(self):
        src = inspect.getsource(mcp_mod.JanusMaskServer.cmd_submit_code)
        assert "emit_ast_rejection" in src

    def test_cmd_submit_code_source_mentions_emit_clean_success(self):
        src = inspect.getsource(mcp_mod.JanusMaskServer.cmd_submit_code)
        assert "emit_clean_success" in src


# ---------- End-to-end: deny path ----------------------------------------


class TestDenyPathEmitsAstRejection:
    def test_rejected_submission_logs_ast_rejection_row(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("JANUSMASK_TASK_ID", "T-DENY")
        _write_task(tmp_path, task_id="T-DENY", target_type="array_transform")

        srv = mcp_mod.JanusMaskServer("claude", tmp_path)
        args = srv._inject_locked_fields({
            "code": "def bad(:\n    return",  # syntax error → AST error
            "explanation": "e",
        })
        result = srv.cmd_submit_code(args)

        assert result.get("status") == "rejected"
        rows = _read_events(tmp_path)
        ast_rows = [r for r in rows if r["event_type"] == "ast_rejection"]
        assert len(ast_rows) == 1
        r = ast_rows[0]
        assert r["book"] == "synthesis"
        assert r["agent"] == "claude"
        assert r["type"] == "array_transform"
        assert r["task_id"] == "T-DENY"
        assert r["delta"] == {"failures": 1, "attempts": 1}


# ---------- End-to-end: allow path ---------------------------------------


class TestAllowPathEmitsCleanSuccess:
    def test_accepted_submission_logs_clean_success_row(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("JANUSMASK_TASK_ID", "T-ALLOW")
        _write_task(tmp_path, task_id="T-ALLOW", target_type="numerical_computation")

        srv = mcp_mod.JanusMaskServer("gemini", tmp_path)
        args = srv._inject_locked_fields({
            "code": "def add(a, b):\n    return a + b\n",
            "explanation": "trivial",
        })
        result = srv.cmd_submit_code(args)

        assert result.get("status") == "accepted"
        rows = _read_events(tmp_path)
        clean_rows = [r for r in rows if r["event_type"] == "clean_success"]
        assert len(clean_rows) == 1
        r = clean_rows[0]
        assert r["book"] == "synthesis"
        assert r["agent"] == "gemini"
        assert r["type"] == "numerical_computation"
        assert r["task_id"] == "T-ALLOW"
        assert r["delta"] == {"failures": 0, "attempts": 1}


# ---------- Defensive: missing synthesis_target_type ----------------------


class TestMissingTargetTypeDoesNotBlock:
    def test_unknown_target_skips_event_but_still_persists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("JANUSMASK_TASK_ID", "T-NOTYPE")
        _write_task(tmp_path, task_id="T-NOTYPE", target_type="unknown_non_taxonomy_key")

        srv = mcp_mod.JanusMaskServer("claude", tmp_path)
        args = srv._inject_locked_fields({
            "code": "def f():\n    return 1\n",
            "explanation": "ok",
        })
        result = srv.cmd_submit_code(args)
        # Verb path must still succeed.
        assert result.get("status") == "accepted"
        rows = _read_events(tmp_path)
        # No clean_success row because taxonomy rejected — but helper
        # swallowed the error and the verb proceeded.
        assert [r for r in rows if r["event_type"] == "clean_success"] == []


# ---------- Defensive: emit helpers never raise ---------------------------


class TestEmitHelpersAreDefensive:
    @pytest.mark.parametrize("kw", [
        {"agent": "bogus", "task_id": "T", "synthesis_target_type": "array_transform"},
        {"agent": "claude", "task_id": "T", "synthesis_target_type": "not_a_key"},
    ])
    def test_emit_ast_rejection_no_raise(self, tmp_path, kw):
        assert submit_code_mod.emit_ast_rejection(state_dir=tmp_path, **kw) is None

    @pytest.mark.parametrize("kw", [
        {"agent": "bogus", "task_id": "T", "synthesis_target_type": "array_transform"},
        {"agent": "gemini", "task_id": "T", "synthesis_target_type": "not_a_key"},
    ])
    def test_emit_clean_success_no_raise(self, tmp_path, kw):
        assert submit_code_mod.emit_clean_success(state_dir=tmp_path, **kw) is None
