"""Unit coverage for harness.hooks_equivalence (HOOK-50).

Locks the shadow-decision-log contract from sub-plan 06 §4.5:
  fields = {ts, session_id, tool_name, args_hash, policy_decision, policy_reason}
  path   = state/hooks/shadow/<session>.jsonl
  mode   = hooks.mode in {off, shadow, enforce}

fail-open: write failures must not propagate into the hook flow.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import types

import pytest

from harness import hooks_equivalence


# -- args_hash --------------------------------------------------------------


def test_args_hash_stable_across_key_order():
    h1 = hooks_equivalence.args_hash({"file_path": "/x", "content": "y"})
    h2 = hooks_equivalence.args_hash({"content": "y", "file_path": "/x"})
    assert h1 == h2


def test_args_hash_length_is_16_hex():
    h = hooks_equivalence.args_hash({"a": 1, "b": 2})
    assert re.fullmatch(r"[0-9a-f]{16}", h)


def test_args_hash_handles_none_and_empty():
    assert hooks_equivalence.args_hash(None) == hooks_equivalence.args_hash({})


def test_args_hash_tolerates_non_json_values():
    # Should not raise on tuples / bytes via default=str fallback.
    h = hooks_equivalence.args_hash({"tpl": (1, 2, 3), "b": b"raw"})
    assert re.fullmatch(r"[0-9a-f]{16}", h)


# -- shadow_path ------------------------------------------------------------


def test_shadow_path_default_under_state_hooks_shadow(tmp_path, monkeypatch):
    monkeypatch.setenv("JANUSMASK_PROJECT_DIR", str(tmp_path))
    p = hooks_equivalence.shadow_path("sess-A")
    assert p == tmp_path / "state" / "hooks" / "shadow" / "sess-A.jsonl"


def test_shadow_path_respects_custom_dir(tmp_path):
    custom = tmp_path / "altshadow"
    p = hooks_equivalence.shadow_path("sess-B", shadow_dir=custom)
    assert p == custom / "sess-B.jsonl"


def test_shadow_path_missing_session_falls_back_to_pid(tmp_path, monkeypatch):
    monkeypatch.setenv("JANUSMASK_PROJECT_DIR", str(tmp_path))
    p = hooks_equivalence.shadow_path(None)
    assert p.name == f"unknown-{os.getpid()}.jsonl"


# -- record_shadow_decision -------------------------------------------------


def _read_rows(p: pathlib.Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_record_writes_jsonl_row_with_six_fields(tmp_path):
    hooks_equivalence.record_shadow_decision(
        session_id="sess-1",
        tool_name="Write",
        tool_input={"file_path": "/x", "content": "y"},
        policy_decision="allow",
        policy_reason="",
        shadow_dir=tmp_path,
    )
    rows = _read_rows(tmp_path / "sess-1.jsonl")
    assert len(rows) == 1
    row = rows[0]
    assert set(row.keys()) == {
        "ts", "session_id", "tool_name", "args_hash",
        "policy_decision", "policy_reason",
    }
    assert row["session_id"] == "sess-1"
    assert row["tool_name"] == "Write"
    assert row["policy_decision"] == "allow"
    assert row["policy_reason"] == ""
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", row["ts"])
    assert re.fullmatch(r"[0-9a-f]{16}", row["args_hash"])


def test_record_appends_rather_than_overwrites(tmp_path):
    for i in range(3):
        hooks_equivalence.record_shadow_decision(
            session_id="sess-2",
            tool_name="Read",
            tool_input={"path": f"/f{i}"},
            policy_decision="allow",
            shadow_dir=tmp_path,
        )
    rows = _read_rows(tmp_path / "sess-2.jsonl")
    assert len(rows) == 3
    assert [r["args_hash"] for r in rows] == sorted({r["args_hash"] for r in rows}, key=[r["args_hash"] for r in rows].index)


def test_record_creates_parent_directory(tmp_path):
    nested = tmp_path / "deep" / "shadow"
    assert not nested.exists()
    hooks_equivalence.record_shadow_decision(
        session_id="sess-3",
        tool_name="Write",
        tool_input={},
        policy_decision="deny",
        policy_reason="forbidden",
        shadow_dir=nested,
    )
    assert (nested / "sess-3.jsonl").exists()


def test_record_isolates_sessions_to_separate_files(tmp_path):
    hooks_equivalence.record_shadow_decision(
        session_id="alpha", tool_name="Write", tool_input={},
        policy_decision="allow", shadow_dir=tmp_path,
    )
    hooks_equivalence.record_shadow_decision(
        session_id="beta", tool_name="Write", tool_input={},
        policy_decision="deny", shadow_dir=tmp_path,
    )
    assert (tmp_path / "alpha.jsonl").exists()
    assert (tmp_path / "beta.jsonl").exists()
    assert _read_rows(tmp_path / "alpha.jsonl")[0]["policy_decision"] == "allow"
    assert _read_rows(tmp_path / "beta.jsonl")[0]["policy_decision"] == "deny"


def test_record_fail_open_on_write_error(tmp_path, monkeypatch, capsys):
    """OSError inside record_shadow_decision must not propagate."""
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(pathlib.Path, "open", boom)
    # Must not raise.
    hooks_equivalence.record_shadow_decision(
        session_id="sess", tool_name="Write", tool_input={},
        policy_decision="allow", shadow_dir=tmp_path,
    )
    captured = capsys.readouterr()
    assert "hooks_equivalence" in captured.err


# -- maybe_record_shadow ----------------------------------------------------


def _fake_config_loader(mode: str, shadow_dir: str | pathlib.Path):
    hc = hooks_equivalence._HooksConfigView(mode=mode, shadow_dir=str(shadow_dir))
    stub = types.SimpleNamespace(
        read_hooks_config=lambda path=None: hc,
    )
    return stub


def test_maybe_record_off_mode_is_noop(tmp_path):
    payload = {"decision": "allow"}
    hooks_equivalence.maybe_record_shadow(
        session_id="s", tool_name="Write", tool_input={}, payload=payload,
        config_loader=_fake_config_loader("off", tmp_path),
    )
    assert not list(tmp_path.iterdir())


def test_maybe_record_shadow_mode_writes(tmp_path):
    payload = {"decision": "deny", "reason": "rate limit reached"}
    hooks_equivalence.maybe_record_shadow(
        session_id="s", tool_name="Write",
        tool_input={"file_path": "/x"}, payload=payload,
        config_loader=_fake_config_loader("shadow", tmp_path),
    )
    rows = _read_rows(tmp_path / "s.jsonl")
    assert len(rows) == 1
    assert rows[0]["policy_decision"] == "deny"
    assert rows[0]["policy_reason"] == "rate limit reached"


def test_maybe_record_enforce_mode_also_writes_for_audit(tmp_path):
    """Enforce mode still emits for L2 equivalence + post-canary audit."""
    hooks_equivalence.maybe_record_shadow(
        session_id="s", tool_name="Write", tool_input={},
        payload={"decision": "allow"},
        config_loader=_fake_config_loader("enforce", tmp_path),
    )
    assert (tmp_path / "s.jsonl").exists()


def test_maybe_record_swallows_config_errors(tmp_path, capsys):
    class Boom:
        def read_hooks_config(self, path=None):
            raise RuntimeError("bad config")
    hooks_equivalence.maybe_record_shadow(
        session_id="s", tool_name="Write", tool_input={},
        payload={"decision": "allow"},
        config_loader=Boom(),
    )
    captured = capsys.readouterr()
    assert "hooks_equivalence" in captured.err


# -- real config integration (HOOKS-50 end-to-end via config.yaml) ----------


def test_maybe_record_reads_live_config_yaml(tmp_path, monkeypatch):
    """Default call path (no config_loader kwarg) must load harness/config.yaml
    and honour its hooks.mode. Uses JANUSMASK_PROJECT_DIR so we don't depend on
    the checked-in mode during the test run."""
    proj = tmp_path / "proj"
    (proj / "harness").mkdir(parents=True)
    shadow = proj / "shadowlogs"
    (proj / "harness" / "config.yaml").write_text(
        f'hooks:\n  mode: "shadow"\n  shadow_dir: "{shadow}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("JANUSMASK_PROJECT_DIR", str(proj))
    hooks_equivalence.maybe_record_shadow(
        session_id="live", tool_name="Write", tool_input={"a": 1},
        payload={"decision": "allow"},
    )
    assert (shadow / "live.jsonl").exists()
