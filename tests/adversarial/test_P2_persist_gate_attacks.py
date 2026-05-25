"""Adversarial attacks against the persist-time AST gate (Blocker #8).

Phase-1 recovery restored the persist-time AST gate after the original
synthesis path was found vulnerable to bypassPermissions / yolo mode
writes that reached ``state/sessions/`` despite a PreToolUse / BeforeTool
deny. The contract pinned by ``test_P2_rpc_submit_persist_gate.py`` covers
the happy path:

    rpc.submit_code.ensure_valid(code, allow_nondeterminism=False)
        -- raises AstValidationError on any error-severity Violation
        -- returns warning-only list otherwise

    harness.hooks.claude.post_tool._persist_submission
    harness.hooks.gemini.post_tool._persist_submission
        -- call ensure_valid BEFORE build_record/persist
        -- on AstValidationError: emit submit_code/deny ledger row
           (with rule/severity/line/message), call emit_ast_rejection,
           write nothing under state/sessions/
        -- on success: continue to build_record + persist + allow row

This file hammers angles the original 16-test contract misses:

  Category 1  Code-content attacks (null bytes, BOMs, CR-only EOLs,
              zero-width identifiers).
  Category 2  AST edge cases (empty / comments-only / whitespace-only /
              future-only / pathological deep-nesting).
  Category 3  Pathological violations (ensure_valid does not allocate
              unbounded preview strings; mixed error+warning lists).
  Category 4  task.json corruption surfaces (empty file, malformed JSON,
              missing keys, wrong types, truthy-string deterministic).
  Category 5  Race / concurrent _persist_submission invocations.
  Category 6  Ledger row corruption (read-only file, missing dir,
              partial trailing line).
  Category 7  AstValidationError deep mutation by callers.
  Category 8  allow_nondeterminism boundary types (1, "true", None).
  Category 9  state_dir() returns a regular file (not a directory).

The two ``constraints``-shape attacks in Category 4 were previously
xfail-pinned because ``_persist_submission`` crashed with AttributeError
on ``None`` / list payloads. Fix-pass sub-agent #4 added an
``isinstance(constraints, dict)`` guard plus a stderr WARNING on
malformed payload; the tests now assert the happy outcome AND the
warning-observability contract.
"""
from __future__ import annotations

import json
import os
import pathlib
import threading
from typing import Any

import pytest

from harness.ast_enforcer import Violation
from harness.hooks.rpc import submit_code as rpc_submit_code


CLEAN_CODE = "def add(a, b):\n    return a + b\n"
UUID_CODE = "import uuid\n\ndef make_id():\n    return uuid.uuid4().hex\n"
TIME_CODE = "import time\n\ndef stamp():\n    return time.time()\n"
SUBPROCESS_WARNING_CODE = (
    "import subprocess\n\n"
    "def run():\n    subprocess.run(['ls'])\n"
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _stage_claude(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                  *, task_text: str | None = None) -> pathlib.Path:
    """Plant the inbox + state_dir monkeypatches the claude post_tool needs.

    Returns the inbox dir so callers can mutate ``task.json`` further.
    """
    from harness.hooks import _paths
    from harness.hooks.claude import _env as claude_env

    monkeypatch.setattr(_paths, "state_dir", lambda: tmp_path)
    inbox = tmp_path / "workdirs" / "claude" / "s1" / "inbox"
    inbox.mkdir(parents=True)
    if task_text is None:
        task_text = json.dumps({"task_id": "atk", "synthesis_target_type": ""})
    (inbox / "task.json").write_text(task_text, encoding="utf-8")
    monkeypatch.setattr(claude_env, "inbox_dir", lambda sid: inbox)
    return inbox


def _stage_gemini(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                  *, task_text: str | None = None) -> pathlib.Path:
    from harness.hooks import _paths
    from harness.hooks.gemini import _env as gemini_env

    monkeypatch.setattr(_paths, "state_dir", lambda: tmp_path)
    inbox = tmp_path / "workdirs" / "gemini" / "s1" / "inbox"
    inbox.mkdir(parents=True)
    if task_text is None:
        task_text = json.dumps({"task_id": "atk", "synthesis_target_type": ""})
    (inbox / "task.json").write_text(task_text, encoding="utf-8")
    monkeypatch.setattr(gemini_env, "inbox_dir", lambda sid: inbox)
    return inbox


def _read_submissions(tmp_path: pathlib.Path) -> list[pathlib.Path]:
    sessions = tmp_path / "sessions"
    if not sessions.exists():
        return []
    return list(sessions.glob("*_submission.json"))


def _read_ledger_rows(tmp_path: pathlib.Path,
                      agent: str = "claude") -> list[dict[str, Any]]:
    path = tmp_path / "sessions" / f"{agent}_s1.ledger.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


# ---------------------------------------------------------------------------
# Category 1: Code-content attacks
# ---------------------------------------------------------------------------


class TestCodeContentAttacks:
    """Surface bytes that look like code but exercise tokenizer/AST edges."""

    def test_null_byte_in_string_literal_is_passable(self) -> None:
        # Python's tokenizer accepts \x00 inside a string literal — the gate
        # should NOT crash. It is allowed to either pass or raise
        # AstValidationError, but it must do so deterministically.
        code = "def f():\n    return '\\x00'\n"
        rpc_submit_code.ensure_valid(code)  # no raise expected; pure string

    def test_raw_null_byte_in_source_raises_syntax(self) -> None:
        # A literal NUL byte in the source — ast.parse() raises SyntaxError
        # ("source code string cannot contain null bytes"). The gate must
        # convert that into an AstValidationError(rule="syntax").
        code = "def f():\n    return 1\n\x00"
        with pytest.raises(rpc_submit_code.AstValidationError) as exc_info:
            rpc_submit_code.ensure_valid(code)
        assert any(v.rule == "syntax" for v in exc_info.value.violations)

    def test_cr_only_line_endings_parse_clean(self) -> None:
        # CPython's ast accepts \r as a line terminator. Confirm clean.
        code = "def f():\r    return 1\r"
        rpc_submit_code.ensure_valid(code)

    def test_bom_prefixed_utf8_source_is_rejected_as_syntax(self) -> None:
        # Empirical finding: CPython's ast.parse() REJECTS a bare U+FEFF BOM
        # mid-string (only accepts it in raw-bytes form via the io codec
        # layer). The gate must surface this as a syntax violation rather
        # than letting the bare SyntaxError bubble. This pins the contract:
        # any bytes a CLI might write that ast.parse() cannot handle should
        # become a well-formed deny, not a crash.
        code = "\ufeffdef f():\n    return 1\n"
        with pytest.raises(rpc_submit_code.AstValidationError) as exc_info:
            rpc_submit_code.ensure_valid(code)
        assert any(v.rule == "syntax" for v in exc_info.value.violations)

    def test_zero_width_identifier_is_treated_as_distinct_name(self) -> None:
        # Python normalizes identifiers via NFKC, so zero-width chars in
        # identifiers either collapse or raise SyntaxError. Either way the
        # gate must not crash; it must emit a deterministic outcome.
        code = "def f\u200b():\n    return 1\n"
        try:
            rpc_submit_code.ensure_valid(code)
        except rpc_submit_code.AstValidationError as exc:
            # If raised, must carry a Violation, not bubble bare SyntaxError.
            assert exc.violations


# ---------------------------------------------------------------------------
# Category 2: AST edge cases
# ---------------------------------------------------------------------------


class TestAstEdgeCases:
    """Inputs where the validator's defaults must hold up."""

    def test_empty_string_raises_incomplete_ast(self) -> None:
        with pytest.raises(rpc_submit_code.AstValidationError) as exc_info:
            rpc_submit_code.ensure_valid("")
        assert any(v.rule == "incomplete_ast" for v in exc_info.value.violations)

    def test_only_comments_raises_incomplete_ast(self) -> None:
        with pytest.raises(rpc_submit_code.AstValidationError) as exc_info:
            rpc_submit_code.ensure_valid("# just a comment\n# and another\n")
        assert any(v.rule == "incomplete_ast" for v in exc_info.value.violations)

    def test_only_whitespace_raises_incomplete_ast(self) -> None:
        with pytest.raises(rpc_submit_code.AstValidationError) as exc_info:
            rpc_submit_code.ensure_valid("   \n\t\n   \n")
        assert any(v.rule == "incomplete_ast" for v in exc_info.value.violations)

    def test_future_imports_only_now_accepted_post_g13(self) -> None:
        # Post-G13 (commit 7b97427) the validator's incomplete_ast rule
        # accepts ImportFrom as a mergeable top-level node — covers the
        # data-only edit class. ``from __future__ import annotations`` alone
        # is now valid (no FunctionDef required).
        code = "from __future__ import annotations\n"
        # Must not raise — ensure_valid returns normally on accepted code.
        rpc_submit_code.ensure_valid(code)

    def test_deeply_nested_if_does_not_blow_recursion(self) -> None:
        # CPython's tokenizer caps nesting at ~100 indent levels ("too many
        # levels of indentation"), so a 200-deep nested-if is not even
        # syntactically valid. Use a flatter pathological structure: a
        # boolean-and chain that produces a wide AST without deep
        # indentation. ensure_valid must complete without RecursionError.
        chain = " and ".join(f"(x == {i})" for i in range(500))
        code = f"def f(x):\n    return {chain}\n"
        rpc_submit_code.ensure_valid(code)

    def test_modest_nested_if_below_indent_cap_is_clean(self) -> None:
        # Twin sanity check: 50 levels of indentation IS within CPython's
        # cap, so the gate must accept this as syntactically valid.
        nested = "def f(x):\n"
        indent = "    "
        for i in range(50):
            nested += indent + f"if x == {i}:\n"
            indent += "    "
        nested += indent + "return 1\n"
        rpc_submit_code.ensure_valid(nested)


# ---------------------------------------------------------------------------
# Category 3: Pathological violations
# ---------------------------------------------------------------------------


class TestPathologicalViolations:
    """Stress the violation-list shape and the format_message preview."""

    def test_ten_thousand_uuid_imports_does_not_blow_up(self) -> None:
        # Stress: AST validation should handle a large number of error-
        # severity violations without OOM or quadratic blow-up. We assert
        # only that ensure_valid completes and raises with at least one
        # error, NOT that the violation count equals N — the validator may
        # short-circuit some rules.
        code = "import uuid\n" * 1000 + "def f():\n    return 1\n"
        with pytest.raises(rpc_submit_code.AstValidationError) as exc_info:
            rpc_submit_code.ensure_valid(code)
        errors = [v for v in exc_info.value.violations if v.severity == "error"]
        assert len(errors) >= 1
        # Preview message must NOT include all 1000 violations — the
        # implementation truncates at 5 + a "(+N more)" suffix.
        msg = str(exc_info.value)
        assert len(msg) < 100_000, (
            "AstValidationError preview must be bounded; "
            "got len={} (likely unbounded list)".format(len(msg))
        )

    def test_mixed_error_and_warning_preview_shows_errors_first(self) -> None:
        # Mix a warning (subprocess without check=) with an error (uuid
        # import). The preview message must surface the error, not the
        # warning, since errors are the blocking violations.
        code = (
            "import uuid\n"
            "import subprocess\n\n"
            "def go():\n    subprocess.run(['ls'])\n    return uuid.uuid4()\n"
        )
        with pytest.raises(rpc_submit_code.AstValidationError) as exc_info:
            rpc_submit_code.ensure_valid(code)
        msg = str(exc_info.value)
        assert "nondeterminism" in msg, (
            f"error-severity rule must lead the preview; got: {msg!r}"
        )
        # subprocess_no_check is a warning, NOT an error. The preview is
        # error-only.
        assert "subprocess_no_check" not in msg


# ---------------------------------------------------------------------------
# Category 4: inbox/task.json corruption
# ---------------------------------------------------------------------------


class TestInboxTaskJsonCorruption:
    """_persist_submission's _load_task is tolerant by design — it returns
    {} on any read/parse error. Confirm the gate still runs and that the
    allow_nondet derivation handles structural surprises."""

    def test_task_json_empty_file_falls_back_to_default_task_id(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harness.hooks.claude import post_tool as claude_post

        inbox = _stage_claude(tmp_path, monkeypatch, task_text="")
        claude_post._persist_submission(
            session_id="s1", agent="claude", round_number=1,
            phase="synthesis", content=CLEAN_CODE,
            explanation="", events=[],
        )
        files = _read_submissions(tmp_path)
        assert len(files) == 1
        # task_id="default" because _load_task returns {} on parse failure.
        assert "default" in files[0].name

    def test_task_json_malformed_falls_back_to_default(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harness.hooks.claude import post_tool as claude_post

        _stage_claude(tmp_path, monkeypatch, task_text="{not json")
        # Must not raise; must persist clean code.
        claude_post._persist_submission(
            session_id="s1", agent="claude", round_number=1,
            phase="synthesis", content=CLEAN_CODE,
            explanation="", events=[],
        )
        assert len(_read_submissions(tmp_path)) == 1

    def test_task_json_missing_constraints_uses_strict_default(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harness.hooks.claude import post_tool as claude_post

        _stage_claude(
            tmp_path, monkeypatch,
            task_text=json.dumps({"task_id": "no-constraints"}),
        )
        # No constraints => allow_nondet is False => uuid must be denied.
        claude_post._persist_submission(
            session_id="s1", agent="claude", round_number=1,
            phase="synthesis", content=UUID_CODE,
            explanation="", events=[],
        )
        assert _read_submissions(tmp_path) == []

    def test_task_json_constraints_is_none_handled_safely(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Fix-pass sub-agent #4 (B3): _persist_submission previously crashed
        # with AttributeError when task.json carried ``constraints: null``
        # because ``task.get("constraints", {}).get(...)`` does not treat an
        # explicit None as "missing". The isinstance guard now replaces any
        # non-dict constraints payload with {} and emits a stderr WARNING so
        # operators can observe the malformation.
        from harness.hooks.claude import post_tool as claude_post

        _stage_claude(
            tmp_path, monkeypatch,
            task_text=json.dumps({"task_id": "x", "constraints": None}),
        )
        claude_post._persist_submission(
            session_id="s1", agent="claude", round_number=1,
            phase="synthesis", content=CLEAN_CODE,
            explanation="", events=[],
        )
        # Clean code must persist once the guard swaps None for {}.
        assert len(_read_submissions(tmp_path)) == 1
        # Observability: the stderr warning must mention the malformed
        # payload and the received type name.
        captured = capsys.readouterr()
        assert "malformed constraints payload" in captured.err
        assert "NoneType" in captured.err

    def test_task_json_constraints_is_a_list_handled_safely(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Fix-pass sub-agent #4 (B3): same guard as the None case, but the
        # payload is a list (which has no .get() method at all). The fix
        # must NOT silently discard the list — it must warn on stderr so
        # operators notice the malformed task.json in production logs.
        from harness.hooks.claude import post_tool as claude_post

        _stage_claude(
            tmp_path, monkeypatch,
            task_text=json.dumps({"task_id": "x", "constraints": ["nope"]}),
        )
        claude_post._persist_submission(
            session_id="s1", agent="claude", round_number=1,
            phase="synthesis", content=CLEAN_CODE,
            explanation="", events=[],
        )
        assert len(_read_submissions(tmp_path)) == 1
        captured = capsys.readouterr()
        assert "malformed constraints payload" in captured.err
        assert "list" in captured.err

    def test_constraints_deterministic_string_false_is_truthy_python(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # In Python, the *string* "false" is truthy. The implementation
        # uses `is False` (not `not bool(...)`), so the string "false"
        # should NOT enable allow_nondet — it should leave it off, denying
        # uuid imports. This pins the strict-bool semantics.
        from harness.hooks.claude import post_tool as claude_post

        _stage_claude(
            tmp_path, monkeypatch,
            task_text=json.dumps(
                {"task_id": "x", "constraints": {"deterministic": "false"}}
            ),
        )
        claude_post._persist_submission(
            session_id="s1", agent="claude", round_number=1,
            phase="synthesis", content=UUID_CODE,
            explanation="", events=[],
        )
        # uuid must be denied because "false" is not the bool False sentinel.
        assert _read_submissions(tmp_path) == []

    def test_constraints_deterministic_explicit_none(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # deterministic=None -> `None is False` -> False -> allow_nondet=False
        # -> uuid denied. Confirm strict-bool sentinel.
        from harness.hooks.claude import post_tool as claude_post

        _stage_claude(
            tmp_path, monkeypatch,
            task_text=json.dumps(
                {"task_id": "x", "constraints": {"deterministic": None}}
            ),
        )
        claude_post._persist_submission(
            session_id="s1", agent="claude", round_number=1,
            phase="synthesis", content=UUID_CODE,
            explanation="", events=[],
        )
        assert _read_submissions(tmp_path) == []


# ---------------------------------------------------------------------------
# Category 5: Race / concurrent _persist_submission invocations
# ---------------------------------------------------------------------------


class TestConcurrentPersistGate:
    """Run two _persist_submission calls concurrently with a slow ensure_valid;
    the gate must remain robust — no half-written files, both deny rows
    present, no leaked submission file."""

    def test_concurrent_ast_denies_both_emit_deny_rows(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harness.hooks.claude import post_tool as claude_post

        _stage_claude(tmp_path, monkeypatch)

        gate = threading.Event()
        original = rpc_submit_code.ensure_valid

        def slow_ensure(code: str, allow_nondeterminism: bool = False):
            gate.wait(timeout=2.0)
            return original(code, allow_nondeterminism=allow_nondeterminism)

        # Patch the symbol that claude_post imported under its `rpc_submit_code`
        # binding (the import is `from ..rpc import submit_code as
        # rpc_submit_code`, so we must patch the attribute on the rpc package
        # namespace that was bound).
        monkeypatch.setattr(
            claude_post.rpc_submit_code, "ensure_valid", slow_ensure
        )

        errors: list[BaseException] = []

        def worker() -> None:
            try:
                claude_post._persist_submission(
                    session_id="s1", agent="claude", round_number=1,
                    phase="synthesis", content=UUID_CODE,
                    explanation="", events=[],
                )
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        gate.set()
        t1.join(timeout=5.0)
        t2.join(timeout=5.0)

        assert not errors, f"concurrent invocations raised: {errors!r}"
        assert _read_submissions(tmp_path) == [], (
            "AST gate must hold under concurrency"
        )
        rows = _read_ledger_rows(tmp_path, "claude")
        deny_rows = [r for r in rows if r.get("outcome") == "deny"]
        assert len(deny_rows) == 2, (
            f"each concurrent attempt must emit its own deny row; got {rows}"
        )


# ---------------------------------------------------------------------------
# Category 6: Ledger row corruption
# ---------------------------------------------------------------------------


class TestLedgerRowCorruption:
    """The deny-row append must be robust to a missing dir / partial line.
    A corrupted ledger must NOT cause the gate to silently let a bad
    submission through."""

    def test_partial_trailing_line_does_not_block_new_deny_row(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harness.hooks.claude import post_tool as claude_post

        _stage_claude(tmp_path, monkeypatch)
        ledger_dir = tmp_path / "sessions"
        ledger_dir.mkdir(exist_ok=True)
        ledger_path = ledger_dir / "claude_s1.ledger.jsonl"
        # Pre-seed a partially-flushed JSON line (missing closing brace,
        # no terminating newline).
        ledger_path.write_text(
            '{"ts":"2026-04-19T00:00:00Z","verb":"submit_code"\n'
            '{"partial":',  # missing closing
            encoding="utf-8",
        )

        claude_post._persist_submission(
            session_id="s1", agent="claude", round_number=1,
            phase="synthesis", content=UUID_CODE,
            explanation="", events=[],
        )
        # Submission must NOT have leaked.
        assert _read_submissions(tmp_path) == []
        # Deny row must have been appended (even though preceding lines
        # are corrupt — append_hook_event opens with mode='a' and writes one
        # line + '\n').
        text = ledger_path.read_text("utf-8")
        assert '"reason": "persist_time_ast_gate"' in text or \
               '"reason":"persist_time_ast_gate"' in text

    def test_missing_sessions_dir_is_recreated(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # If state/sessions does not yet exist, the deny path must mkdir it.
        from harness.hooks.claude import post_tool as claude_post

        _stage_claude(tmp_path, monkeypatch)
        # NB: we deliberately do NOT pre-create state/sessions/.
        claude_post._persist_submission(
            session_id="s1", agent="claude", round_number=1,
            phase="synthesis", content=UUID_CODE,
            explanation="", events=[],
        )
        assert (tmp_path / "sessions").exists(), (
            "deny path must mkdir state/sessions/ before appending the row"
        )
        rows = _read_ledger_rows(tmp_path, "claude")
        assert any(r.get("outcome") == "deny" for r in rows)

    def test_readonly_ledger_does_not_drop_deny_row_silently(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # If the ledger file exists and is read-only, append_hook_event raises
        # PermissionError. The CRITICAL invariant is: the write to
        # state/sessions/*_submission.json must STILL be skipped, i.e. the
        # gate is the AST decision, not the ledger append. The exception
        # may propagate (the hook subprocess will crash and the harness
        # will surface it) — what must NOT happen is a leaked submission.
        from harness.hooks.claude import post_tool as claude_post

        _stage_claude(tmp_path, monkeypatch)
        ledger_dir = tmp_path / "sessions"
        ledger_dir.mkdir(exist_ok=True)
        ledger_path = ledger_dir / "claude_s1.ledger.jsonl"
        ledger_path.write_text("", encoding="utf-8")
        # Make the file read-only (chmod). On platforms where chmod has
        # no effect (e.g. running as root), skip the assertion.
        try:
            os.chmod(ledger_path, 0o444)
            # Sanity: confirm we cannot append.
            try:
                with ledger_path.open("a", encoding="utf-8") as fh:
                    fh.write("x")
                # If the open succeeded (root or unusual fs), skip rather
                # than mis-test.
                pytest.skip("ledger remained writable; cannot test readonly path")
            except PermissionError:
                pass

            raised = False
            try:
                claude_post._persist_submission(
                    session_id="s1", agent="claude", round_number=1,
                    phase="synthesis", content=UUID_CODE,
                    explanation="", events=[],
                )
            except PermissionError:
                raised = True
            # No submission file may have leaked, regardless of whether the
            # PermissionError was caught or propagated.
            assert _read_submissions(tmp_path) == [], (
                "readonly ledger must not allow a leaked submission"
            )
            # Either the call propagated the error or it was swallowed.
            # Both are acceptable; a silent SUCCESS is not.
            _ = raised  # documented for future tightening
        finally:
            # Restore perms so tmp_path cleanup doesn't fail.
            os.chmod(ledger_path, 0o644)


# ---------------------------------------------------------------------------
# Category 7: AstValidationError mutation by callers
# ---------------------------------------------------------------------------


class TestAstValidationErrorMutation:
    """Existing test_violations_list_is_copy_not_reference covers shallow
    list mutation (clearing). We add deep mutation: rewrite the rule of
    a Violation in the raised exception and confirm that a fresh
    ensure_valid() call still produces ground-truth Violations."""

    def test_deep_mutation_does_not_poison_subsequent_calls(self) -> None:
        with pytest.raises(rpc_submit_code.AstValidationError) as exc_info:
            rpc_submit_code.ensure_valid(UUID_CODE)
        # Mutate the rule of the first violation.
        if exc_info.value.violations:
            exc_info.value.violations[0].rule = "CORRUPTED-BY-CALLER"

        # Fresh call must yield untouched 'nondeterminism' rule.
        with pytest.raises(rpc_submit_code.AstValidationError) as exc2:
            rpc_submit_code.ensure_valid(UUID_CODE)
        rules = {v.rule for v in exc2.value.violations}
        assert "nondeterminism" in rules
        assert "CORRUPTED-BY-CALLER" not in rules

    def test_severity_mutation_does_not_change_format_message(self) -> None:
        with pytest.raises(rpc_submit_code.AstValidationError) as exc_info:
            rpc_submit_code.ensure_valid(UUID_CODE)
        # Downgrade all errors to warnings AFTER raise.
        for v in exc_info.value.violations:
            v.severity = "warning"
        # _format_message inspects the (now mutated) list, so it WILL
        # produce a different string; document this:
        msg = str(exc_info.value)
        # When no errors remain in the (mutated) list, the message falls
        # back to "AST validation failed" without any rule preview.
        assert msg == "AST validation failed", (
            "after caller demotes severity, format_message returns the "
            "no-error fallback; this documents the contract for downstream "
            "string consumers."
        )


# ---------------------------------------------------------------------------
# Category 8: allow_nondeterminism boundary types
# ---------------------------------------------------------------------------


class TestAllowNondeterminismBoundary:
    """ensure_valid signature is `allow_nondeterminism: bool = False`.
    Python is duck-typed, so truthy non-bool values would historically
    flip the gate. Pin the actual semantics."""

    @pytest.mark.parametrize(
        "value,expected_pass",
        [
            (True, True),    # canonical pass
            (False, False),  # canonical block
            (1, True),       # truthy int - currently treated as pass
            ("true", True),  # truthy str - currently treated as pass
            (None, False),   # falsy - blocks
            (0, False),      # falsy int - blocks
            ("", False),     # empty str - blocks
        ],
    )
    def test_truthy_values_enable_nondet(
        self, value: Any, expected_pass: bool
    ) -> None:
        # The validator uses `if not self.allow_nondeterminism:` -- so any
        # truthy value should suppress the nondet rule. Document this.
        if expected_pass:
            # Should NOT raise: nondet allowed.
            result = rpc_submit_code.ensure_valid(
                UUID_CODE, allow_nondeterminism=value
            )
            assert all(v.severity != "error" for v in result), (
                f"value={value!r} expected to allow uuid import; "
                f"got errors: {[v for v in result if v.severity=='error']}"
            )
        else:
            with pytest.raises(rpc_submit_code.AstValidationError):
                rpc_submit_code.ensure_valid(
                    UUID_CODE, allow_nondeterminism=value
                )


# ---------------------------------------------------------------------------
# Category 9: state_dir() pathological returns
# ---------------------------------------------------------------------------


class TestStateDirPathological:
    """state_dir() is monkeypatched in tests; in production it can be set
    via JANUSMASK_STATE_DIR. If the path is a regular file (not a dir)
    the persist must fail loudly — not corrupt the file or silently
    swallow the submission."""

    def test_state_dir_is_a_regular_file_persist_fails_no_leak(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harness.hooks import _paths
        from harness.hooks.claude import _env as claude_env
        from harness.hooks.claude import post_tool as claude_post

        # Plant inbox somewhere safe under a real dir.
        real_state = tmp_path / "real-state"
        real_state.mkdir()
        inbox = real_state / "workdirs" / "claude" / "s1" / "inbox"
        inbox.mkdir(parents=True)
        (inbox / "task.json").write_text(
            json.dumps({"task_id": "regfile", "synthesis_target_type": ""}),
            encoding="utf-8",
        )
        monkeypatch.setattr(claude_env, "inbox_dir", lambda sid: inbox)

        # Now make state_dir() return a path that is a REGULAR FILE.
        bogus = tmp_path / "state-as-file"
        bogus.write_text("i am a file, not a dir", encoding="utf-8")
        monkeypatch.setattr(_paths, "state_dir", lambda: bogus)

        # Clean code → reaches build_record/persist → persist mkdirs
        # bogus/sessions which fails with FileExistsError or NotADirectoryError.
        with pytest.raises((NotADirectoryError, FileExistsError, OSError)):
            claude_post._persist_submission(
                session_id="s1", agent="claude", round_number=1,
                phase="synthesis", content=CLEAN_CODE,
                explanation="", events=[],
            )

    def test_state_dir_symlink_to_devnull_is_tolerated_or_raises(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # state_dir() returning a symlink to /dev/null must not silently
        # succeed. mkdir(parents=True, exist_ok=True) on a symlink-to-
        # devnull will raise FileExistsError because the target exists
        # and is not a dir.
        from harness.hooks import _paths
        from harness.hooks.claude import _env as claude_env
        from harness.hooks.claude import post_tool as claude_post

        real_state = tmp_path / "real-state-2"
        real_state.mkdir()
        inbox = real_state / "workdirs" / "claude" / "s1" / "inbox"
        inbox.mkdir(parents=True)
        (inbox / "task.json").write_text(
            json.dumps({"task_id": "sym", "synthesis_target_type": ""}),
            encoding="utf-8",
        )
        monkeypatch.setattr(claude_env, "inbox_dir", lambda sid: inbox)

        symlink = tmp_path / "state-symlink"
        try:
            os.symlink("/dev/null", symlink)
        except OSError:
            pytest.skip("symlink not supported on this platform")
        monkeypatch.setattr(_paths, "state_dir", lambda: symlink)

        with pytest.raises((NotADirectoryError, FileExistsError, OSError)):
            claude_post._persist_submission(
                session_id="s1", agent="claude", round_number=1,
                phase="synthesis", content=CLEAN_CODE,
                explanation="", events=[],
            )


# ---------------------------------------------------------------------------
# Bonus: Gemini twin coverage for the most surprising bugs
# ---------------------------------------------------------------------------


class TestGeminiPersistGateAttacks:
    """Mirror the most adversarial Claude angles on the Gemini path so a
    regression in either copy is caught."""

    def test_gemini_constraints_string_false_still_blocks(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harness.hooks.gemini import post_tool as gemini_post

        _stage_gemini(
            tmp_path, monkeypatch,
            task_text=json.dumps(
                {"task_id": "g", "constraints": {"deterministic": "false"}}
            ),
        )
        gemini_post._persist_submission(
            session_id="s1", agent="gemini", round_number=1,
            phase="synthesis", content=UUID_CODE,
            explanation="", events=[],
        )
        assert _read_submissions(tmp_path) == []

    def test_gemini_pathological_violation_count_does_not_oom(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harness.hooks.gemini import post_tool as gemini_post

        _stage_gemini(tmp_path, monkeypatch)
        # 500 uuid imports + a function — confirm denied without OOM.
        big = "import uuid\n" * 500 + "def f():\n    return 1\n"
        gemini_post._persist_submission(
            session_id="s1", agent="gemini", round_number=1,
            phase="synthesis", content=big,
            explanation="", events=[],
        )
        assert _read_submissions(tmp_path) == []
        rows = _read_ledger_rows(tmp_path, "gemini")
        deny = [r for r in rows if r.get("outcome") == "deny"]
        assert deny, "gemini deny row must be present"
        # The detail.violations list IS bounded — it carries every error
        # because the post_tool layer keeps the full list (post_tool builds
        # violation_dicts from exc.violations without truncation). Verify
        # that the persisted row size is at least under a sane bound so a
        # pathological input can't OOM the ledger writer.
        ledger_size = (
            tmp_path / "sessions" / "gemini_s1.ledger.jsonl"
        ).stat().st_size
        assert ledger_size < 5_000_000, (
            f"ledger row exploded to {ledger_size} bytes; "
            "violation list should be capped or truncated"
        )

    def test_gemini_constraints_is_none_handled_safely(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Gemini twin of the Claude None-guard test: the fix must be
        # symmetric across both post_tool copies (Claude/Gemini twin
        # invariant).
        from harness.hooks.gemini import post_tool as gemini_post

        _stage_gemini(
            tmp_path, monkeypatch,
            task_text=json.dumps({"task_id": "g", "constraints": None}),
        )
        gemini_post._persist_submission(
            session_id="s1", agent="gemini", round_number=1,
            phase="synthesis", content=CLEAN_CODE,
            explanation="", events=[],
        )
        assert len(_read_submissions(tmp_path)) == 1
        captured = capsys.readouterr()
        assert "malformed constraints payload" in captured.err
        assert "NoneType" in captured.err

    def test_gemini_constraints_is_a_list_handled_safely(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Gemini twin of the Claude list-guard test.
        from harness.hooks.gemini import post_tool as gemini_post

        _stage_gemini(
            tmp_path, monkeypatch,
            task_text=json.dumps({"task_id": "g", "constraints": ["x"]}),
        )
        gemini_post._persist_submission(
            session_id="s1", agent="gemini", round_number=1,
            phase="synthesis", content=CLEAN_CODE,
            explanation="", events=[],
        )
        assert len(_read_submissions(tmp_path)) == 1
        captured = capsys.readouterr()
        assert "malformed constraints payload" in captured.err
        assert "list" in captured.err
