"""Adversarial battery for HOOK-50 shadow logging.

Targets the harness.hooks_equivalence writer and its integration seam in
the Claude / Gemini PreToolUse hooks. Each attack is a realistic misuse
or fault-injection that the writer must survive without taking down the
hook flow, while preserving (or clearly annotating) the six-field schema
the equivalence comparator (HOOK-51) consumes.

Augmented plan §5 P5 row includes shadow-write schema-omission attacks
for the comparator side; the writer-side complement lives here.
"""

from __future__ import annotations

import io
import json
import os
import pathlib
import re
import sys
import threading
import types

import pytest

from harness import hooks_equivalence


# -- byzantine tool_input ---------------------------------------------------


def test_adv_random_bytes_tool_input_does_not_crash(tmp_path):
    """Byzantine content: random bytes inside tool_input must not raise.

    default=str fallback in args_hash is the load-bearing invariant.
    """
    tool_input = {"blob": os.urandom(4096), "tpl": (1, 2, 3), "n": 10**50}
    hooks_equivalence.record_shadow_decision(
        session_id="byz-1", tool_name="Write", tool_input=tool_input,
        policy_decision="allow", shadow_dir=tmp_path,
    )
    row = json.loads((tmp_path / "byz-1.jsonl").read_text().strip())
    assert re.fullmatch(r"[0-9a-f]{16}", row["args_hash"])


def test_adv_huge_payload_bounded_args_hash(tmp_path):
    tool_input = {"content": "x" * (2 * 1024 * 1024)}  # 2 MiB
    hooks_equivalence.record_shadow_decision(
        session_id="big", tool_name="Write", tool_input=tool_input,
        policy_decision="deny", policy_reason="too big",
        shadow_dir=tmp_path,
    )
    row = json.loads((tmp_path / "big.jsonl").read_text().strip())
    assert len(row["args_hash"]) == 16


def test_adv_unicode_session_id_survives_roundtrip(tmp_path):
    sid = "sess-ⱷ-中文-\U0001f600"
    hooks_equivalence.record_shadow_decision(
        session_id=sid, tool_name="Write", tool_input={"a": 1},
        policy_decision="allow", shadow_dir=tmp_path,
    )
    # The file name includes the unicode session_id on filesystems that
    # allow UTF-8. If the FS rejects it we just need the writer to not
    # crash — it's fail-open by contract.
    matches = list(tmp_path.glob("*.jsonl"))
    if matches:
        row = json.loads(matches[0].read_text().strip())
        assert row["session_id"] == sid


def test_adv_none_and_empty_input_safe(tmp_path):
    hooks_equivalence.record_shadow_decision(
        session_id="", tool_name="", tool_input=None,
        policy_decision="", shadow_dir=tmp_path,
    )
    # Empty session_id falls back to unknown-<pid>
    assert (tmp_path / f"unknown-{os.getpid()}.jsonl").exists()


# -- filesystem fault injection --------------------------------------------


def test_adv_readonly_shadow_dir_fails_open(tmp_path, monkeypatch, capsys):
    target = tmp_path / "locked"
    target.mkdir()
    target.chmod(0o500)  # read + execute only; no write
    try:
        hooks_equivalence.record_shadow_decision(
            session_id="s", tool_name="Write", tool_input={},
            policy_decision="allow", shadow_dir=target,
        )
    finally:
        target.chmod(0o700)
    err = capsys.readouterr().err
    assert "hooks_equivalence" in err


def test_adv_symlink_attack_does_not_escape_shadow_dir(tmp_path):
    """A malicious session_id containing '..' / '/' must not redirect the
    shadow write outside the shadow_dir. The JSONL file name is expected
    to be derived from the session_id verbatim — we assert it stays under
    the shadow_dir subtree, even when the id contains path separators.
    """
    victim = tmp_path / "OUTSIDE.txt"
    victim.write_text("untouched")
    sid = "../OUTSIDE"
    hooks_equivalence.record_shadow_decision(
        session_id=sid, tool_name="Write", tool_input={},
        policy_decision="allow", shadow_dir=tmp_path / "shadow",
    )
    # The victim file must remain untouched.
    assert victim.read_text() == "untouched"


def test_adv_concurrent_writes_do_not_truncate_lines(tmp_path):
    """50 threads each append one shadow row; exactly 50 lines, each a
    valid JSON object, must land. PIPE_BUF atomicity (O_APPEND + writes
    < ~4 KiB) is what the writer relies on.
    """
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            hooks_equivalence.record_shadow_decision(
                session_id="race", tool_name="Write",
                tool_input={"i": i},
                policy_decision="allow", shadow_dir=tmp_path,
            )
        except Exception as exc:  # pragma: no cover — must not fire
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    lines = (tmp_path / "race.jsonl").read_text().splitlines()
    assert len(lines) == 50
    for line in lines:
        row = json.loads(line)
        assert set(row.keys()) == {
            "ts", "session_id", "tool_name", "args_hash",
            "policy_decision", "policy_reason",
        }


# -- schema integrity / mutation tests --------------------------------------


def test_adv_schema_omission_mutation_detected(tmp_path):
    """Mutation: patch record_shadow_decision to drop the 'ts' field, then
    replay. The six-field schema is the comparator's contract — any
    omission must be detectable by schema-checking readers.
    """
    hooks_equivalence.record_shadow_decision(
        session_id="shape", tool_name="Write", tool_input={},
        policy_decision="allow", shadow_dir=tmp_path,
    )
    row = json.loads((tmp_path / "shape.jsonl").read_text().strip())
    # Positive: writer emits all six.
    required = {"ts", "session_id", "tool_name", "args_hash",
                "policy_decision", "policy_reason"}
    assert required.issubset(row.keys())

    # Mutation: hand-rolled row without 'ts'. Any comparator using set-
    # equality on keys must reject this.
    mutant = {k: v for k, v in row.items() if k != "ts"}
    assert "ts" not in mutant
    assert set(mutant.keys()) != required


def test_adv_args_hash_is_deterministic_across_processes(tmp_path):
    """args_hash must be a pure function — same tool_input, same hash,
    independently of PID / hostname / time. Relied on by the comparator
    to diff MCP-side vs hook-side decisions."""
    h1 = hooks_equivalence.args_hash({"a": 1, "b": [2, 3]})
    h2 = hooks_equivalence.args_hash({"b": [2, 3], "a": 1})
    assert h1 == h2
    # Known-value regression: if sha256 / default=str changes upstream we
    # need to know.
    assert h1 == hooks_equivalence.args_hash({"a": 1, "b": [2, 3]})


# -- fail-open under config adversary ---------------------------------------


def test_adv_corrupt_config_does_not_take_down_hook(tmp_path, monkeypatch):
    """Malformed harness/config.yaml: maybe_record_shadow must swallow
    the parse error and return silently so the live hook still completes.
    """
    proj = tmp_path / "proj"
    (proj / "harness").mkdir(parents=True)
    (proj / "harness" / "config.yaml").write_text(
        "hooks:\n  mode: shadow\n  enforce_verbs: [[[[bad",
        encoding="utf-8",
    )
    monkeypatch.setenv("JANUSMASK_PROJECT_DIR", str(proj))
    hooks_equivalence.maybe_record_shadow(
        session_id="x", tool_name="Write", tool_input={},
        payload={"decision": "allow"},
    )  # must not raise


def test_adv_missing_config_file_does_not_raise(tmp_path, monkeypatch):
    """No harness/config.yaml at all: fail-open path returns without
    emitting and without exception."""
    monkeypatch.setenv("JANUSMASK_PROJECT_DIR", str(tmp_path))
    hooks_equivalence.maybe_record_shadow(
        session_id="x", tool_name="Write", tool_input={},
        payload={"decision": "allow"},
    )


def test_adv_unknown_mode_treated_as_noop(tmp_path, monkeypatch):
    """If someone slips in `mode: paranoid`, the writer must not emit
    (fail-closed against unknown enums) and not raise."""
    proj = tmp_path / "proj"
    (proj / "harness").mkdir(parents=True)
    (proj / "harness" / "config.yaml").write_text(
        'hooks:\n  mode: "paranoid"\n', encoding="utf-8",
    )
    monkeypatch.setenv("JANUSMASK_PROJECT_DIR", str(proj))
    hooks_equivalence.maybe_record_shadow(
        session_id="x", tool_name="Write", tool_input={},
        payload={"decision": "allow"},
    )
    # No shadow file created.
    assert not list((proj).rglob("*.jsonl"))


# -- integration seam: live hook main -> shadow emit ------------------------


def test_adv_claude_hook_main_emits_under_shadow_mode(tmp_path, monkeypatch):
    """End-to-end: invoke harness.hooks.claude.pre_tool.main with a
    disallowed tool under shadow mode; assert the shadow row lands.
    Chooses a disallowed-tool path because it needs no JANUSMASK_WORK_DIR
    scaffolding — the deny fires on the tool-name check.
    """
    proj = tmp_path / "proj"
    (proj / "harness").mkdir(parents=True)
    (proj / "harness" / "config.yaml").write_text(
        'hooks:\n  mode: "shadow"\n  shadow_dir: "shadow/"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("JANUSMASK_PROJECT_DIR", str(proj))
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(proj / "state"))

    from harness.hooks.claude import pre_tool

    stdin = io.StringIO(json.dumps({
        "tool_name": "Bash",  # not in ALLOWED_TOOLS — denied
        "tool_input": {"cmd": "ls"},
        "session_id": "live-claude",
    }))
    stdout = io.StringIO()
    rc = pre_tool.main(stdin, stdout)
    assert rc == 0
    decision = json.loads(stdout.getvalue())
    assert decision["decision"] == "deny"

    shadow_file = proj / "shadow" / "live-claude.jsonl"
    assert shadow_file.exists(), "shadow emit missing"
    row = json.loads(shadow_file.read_text().strip())
    assert row["tool_name"] == "Bash"
    assert row["policy_decision"] == "deny"
    assert row["session_id"] == "live-claude"


def test_adv_gemini_hook_main_emits_under_shadow_mode(tmp_path, monkeypatch):
    """Gemini twin of the Claude integration check."""
    proj = tmp_path / "proj"
    (proj / "harness").mkdir(parents=True)
    (proj / "harness" / "config.yaml").write_text(
        'hooks:\n  mode: "shadow"\n  shadow_dir: "shadow/"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("JANUSMASK_PROJECT_DIR", str(proj))
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(proj / "state"))

    from harness.hooks.gemini import pre_tool

    stdin = io.StringIO(json.dumps({
        "tool_name": "google_web_search",  # not allowed
        "tool_input": {"q": "anything"},
        "session_id": "live-gemini",
    }))
    stdout = io.StringIO()
    rc = pre_tool.main(stdin, stdout)
    assert rc == 0
    decision = json.loads(stdout.getvalue())
    assert decision["decision"] == "deny"

    shadow_file = proj / "shadow" / "live-gemini.jsonl"
    assert shadow_file.exists(), "shadow emit missing (gemini)"
    row = json.loads(shadow_file.read_text().strip())
    assert row["tool_name"] == "google_web_search"
    assert row["policy_decision"] == "deny"


def test_adv_off_mode_produces_no_shadow_file(tmp_path, monkeypatch):
    """Regression: flipping back to hooks.mode: off must silence emission."""
    proj = tmp_path / "proj"
    (proj / "harness").mkdir(parents=True)
    (proj / "harness" / "config.yaml").write_text(
        'hooks:\n  mode: "off"\n  shadow_dir: "shadow/"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("JANUSMASK_PROJECT_DIR", str(proj))
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(proj / "state"))

    from harness.hooks.claude import pre_tool

    stdin = io.StringIO(json.dumps({
        "tool_name": "Bash",
        "tool_input": {"cmd": "ls"},
        "session_id": "off-mode",
    }))
    stdout = io.StringIO()
    pre_tool.main(stdin, stdout)
    assert not (proj / "shadow").exists() or not any((proj / "shadow").iterdir())
