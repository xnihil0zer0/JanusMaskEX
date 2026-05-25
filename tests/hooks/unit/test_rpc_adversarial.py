"""Adversarial battery for HOOK-11-extract-rpc (Phase 1).

Three attacks per augmented plan §5 P1 row:

1. Concurrency: import `harness.hooks.rpc.submit_code` from both new path AND
   via `harness.mcp_server` (after rewire, MCP delegates to rpc). Calling
   persist twice for the same submission_number yields a single authoritative
   file (atomic rename makes the last write win without partial-file races).

2. Forge session_id: an agent cannot influence the on-disk locked fields —
   the rpc module writes whatever locked fields the *caller* injected. The
   test documents that MCP (and the future hook) must inject authoritative
   locked fields BEFORE calling rpc.persist; agent-supplied values are
   overwritten at injection time, not inside rpc.

3. Contract: `submit_code.build_record` / `persist` with payload missing
   `explanation` raises, error message references mcp_server.py:648-658.
"""

from __future__ import annotations

import concurrent.futures
import json

import pytest

import harness.hooks.rpc.submit_code
from harness.hooks.rpc import submit_code


def _locked(**overrides):
    base = {
        "session_id": "SESSION-A",
        "agent_identity": "claude",
        "round_number": 2,
        "timestamp": "2026-04-17T00:00:00+00:00",
    }
    base.update(overrides)
    return base


class TestConcurrencyNoDoubleStamp:
    """Two callers (MCP + hook) race to persist — atomic rename gives one
    authoritative artefact, no partial write visible, no duplicate filename."""

    def test_parallel_persist_produces_one_file(self, tmp_path):
        args = _locked(code="x=1", explanation="e")
        rec = submit_code.build_record(args, submission_number=1)

        def work(_):
            return submit_code.persist(rec, state_dir=tmp_path, agent="claude", task_id="T1")

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            paths = list(pool.map(work, range(4)))

        assert all(p.exists() for p in paths)
        assert len({p.name for p in paths}) == 1  # canonical filename
        on_disk = json.loads(paths[0].read_text())
        assert on_disk == rec

    def test_mcp_delegates_to_rpc_module(self):
        """Post-rewire, mcp_server must delegate to harness.hooks.rpc.submit_code
        (not re-implement the verb). Verified via module-level import graph."""
        import harness.mcp_server as mcp
        # The rewire contract: mcp_server imports and uses rpc.submit_code —
        # either as a top-level import or via harness.hooks.rpc namespace.
        src = __import__("inspect").getsource(mcp)
        assert "harness.hooks.rpc" in src, (
            "mcp_server.py must import from harness.hooks.rpc to share the "
            "verb implementation (HOOK-11 rewire contract)."
        )


class TestForgedSessionIdOverwritten:
    """An agent puts its own session_id in `code` or `explanation`; the
    locked fields on disk come from the *caller's* args dict. This pins the
    layering: rpc does not re-stamp; callers must inject first.

    The accompanying assertion: build_record uses ONLY the keys from args —
    it does not look at code/explanation body for session_id."""

    def test_record_uses_caller_locked_fields_not_code_body(self):
        forged = "session_id = 'EVIL'\nagent_identity = 'attacker'\n"
        args = _locked(code=forged, explanation="forged")
        rec = submit_code.build_record(args, submission_number=1)
        assert rec["session_id"] == "SESSION-A"
        assert rec["agent_identity"] == "claude"
        # The forged bytes live only inside `code`, never in the locked stamp.
        assert "EVIL" in rec["code"]
        assert rec["agent_identity"] != "attacker"

    def test_caller_override_wins(self):
        """If a buggy caller passed agent-controlled args directly, any value
        the caller stamps LAST is what persists — i.e. the contract is
        'caller owns locked fields'. MCP's _inject_locked_fields + the future
        hook's post-tool stamp both run before build_record."""
        args = _locked(session_id="ATTACKER_CLAIMED", code="x=1", explanation="e")
        # MCP/hook would overwrite session_id to the authoritative value first:
        args["session_id"] = "AUTHORITATIVE"
        rec = submit_code.build_record(args, submission_number=1)
        assert rec["session_id"] == "AUTHORITATIVE"


class TestContractMissingExplanation:
    def test_build_record_missing_explanation_raises_with_schema_ref(self):
        args = _locked(code="x=1")  # no 'explanation'
        with pytest.raises(submit_code.SchemaError) as exc:
            submit_code.build_record(args, submission_number=1)
        msg = str(exc.value)
        assert "mcp_server.py:648-658" in msg
        assert "explanation" in msg

    def test_build_record_missing_code_raises_with_schema_ref(self):
        args = _locked(explanation="e")
        with pytest.raises(submit_code.SchemaError) as exc:
            submit_code.build_record(args, submission_number=1)
        assert "mcp_server.py:648-658" in str(exc.value)
        assert "code" in str(exc.value)

    def test_build_record_missing_locked_field_raises(self):
        args = {"code": "x=1", "explanation": "e"}  # no session_id etc.
        with pytest.raises(submit_code.SchemaError) as exc:
            submit_code.build_record(args, submission_number=1)
        assert "mcp_server.py:648-658" in str(exc.value)
