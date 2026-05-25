"""Heredoc/segment-aware tests for scripts/impl_pre_bash.py gate.

Drives the hook as a subprocess with crafted JSON stdin and asserts
that:
  * gated verbs hidden inside heredoc bodies do NOT trigger the gate
    (gate must exit 0 with empty stdout, i.e. allow);
  * gated verbs at top level (or in a non-heredoc segment of a
    compound command) DO trigger the gate (denied because the seeded
    ledger has no test_pass / adv_pass);
  * benign chained commands stay allowed.

All tests use a tmp_path-scoped ledger so the real
state/impl_progress.jsonl is untouched. Companion to
tests/adversarial/test_meta_hooks.py (shared subprocess pattern).
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"


def _run(stdin_payload: dict, tmp_path: pathlib.Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    env["JANUSMASK_PROJECT_DIR"] = str(tmp_path)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "impl_pre_bash.py")],
        input=json.dumps(stdin_payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


def _recent_start(task: str, phase: str) -> dict:
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"ts": ts, "phase": phase, "task_id": task, "event": "start",
            "detail": "", "files": [], "exit": 0}


def _seed_ledger(tmp_path: pathlib.Path, rows: list) -> None:
    ledger = tmp_path / "state" / "impl_progress.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(r) for r in rows)
    ledger.write_text(body + ("\n" if body else ""), encoding="utf-8")


def _bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _assert_allow(proc: subprocess.CompletedProcess) -> None:
    """Gate exited without emitting a deny payload."""
    assert proc.returncode == 0, proc.stderr
    if proc.stdout.strip():
        payload = json.loads(proc.stdout)
        hso = payload.get("hookSpecificOutput") or {}
        assert hso.get("permissionDecision") != "deny", proc.stdout


def _assert_deny(proc: subprocess.CompletedProcess) -> str:
    """Gate processed the command and denied (no test_pass in ledger)."""
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    hso = payload.get("hookSpecificOutput") or {}
    assert hso.get("permissionDecision") == "deny", proc.stdout
    return hso.get("permissionDecisionReason", "")


# --------- PASS cases (no gated verb at top level) ---------


def test_heredoc_body_with_git_commit_verb_not_gated(tmp_path):
    """python3 <<EOF\\nprint('git commit')\\nEOF -- verb only inside heredoc."""
    _seed_ledger(tmp_path, [_recent_start("META-PB", "META")])
    cmd = "python3 <<EOF\nprint('git commit')\nEOF\n"
    _assert_allow(_run(_bash(cmd), tmp_path))


def test_heredoc_dash_variant_with_gated_verb_not_gated(tmp_path):
    """`<<-EOF` (tab-stripping) heredoc body must also be stripped."""
    _seed_ledger(tmp_path, [_recent_start("META-PB", "META")])
    cmd = "python3 <<-EOF\n\tprint('git push origin main')\n\tEOF\n"
    _assert_allow(_run(_bash(cmd), tmp_path))


def test_heredoc_quoted_delim_with_gated_verb_not_gated(tmp_path):
    """`<<'EOF'` (no interpolation) heredoc body must also be stripped."""
    _seed_ledger(tmp_path, [_recent_start("META-PB", "META")])
    cmd = "python3 <<'EOF'\nprint('git rebase -i HEAD~3')\nEOF\n"
    _assert_allow(_run(_bash(cmd), tmp_path))


def test_benign_chain_no_gated_verb(tmp_path):
    """ls && grep foo -- no gated verb anywhere."""
    _seed_ledger(tmp_path, [_recent_start("META-PB", "META")])
    _assert_allow(_run(_bash("ls && grep foo /etc/hosts"), tmp_path))


def test_python_inline_with_chain_no_gated_verb(tmp_path):
    """python3 -c 'x=1' && echo done -- no gated verb anywhere."""
    _seed_ledger(tmp_path, [_recent_start("META-PB", "META")])
    _assert_allow(_run(_bash("python3 -c 'x=1' && echo done"), tmp_path))


def test_git_status_not_gated(tmp_path):
    """`git status` is not in GATED_PATTERNS (only commit/push/reset --hard/rebase)."""
    _seed_ledger(tmp_path, [_recent_start("META-PB", "META")])
    _assert_allow(_run(_bash("git status"), tmp_path))


# --------- FAIL / gate-triggers cases ---------


def test_bare_git_commit_triggers_gate(tmp_path):
    """git commit -m x -- bare top-level invocation must hit the gate."""
    _seed_ledger(tmp_path, [_recent_start("META-PB", "META")])
    reason = _assert_deny(_run(_bash("git commit -m x"), tmp_path))
    assert "test_pass" in reason


def test_segmented_git_push_triggers_gate(tmp_path):
    """ls && git push origin main -- second segment is real."""
    _seed_ledger(tmp_path, [_recent_start("META-PB", "META")])
    reason = _assert_deny(_run(_bash("ls && git push origin main"), tmp_path))
    assert "test_pass" in reason


def test_semicolon_chained_reset_hard_triggers_gate(tmp_path):
    """git reset --hard HEAD~1; echo done -- first segment is real."""
    _seed_ledger(tmp_path, [_recent_start("META-PB", "META")])
    reason = _assert_deny(
        _run(_bash("git reset --hard HEAD~1; echo done"), tmp_path)
    )
    assert "test_pass" in reason


def test_heredoc_then_real_git_commit_triggers_gate(tmp_path):
    """python3 <<EOF...EOF && git commit -m x -- second segment is real."""
    _seed_ledger(tmp_path, [_recent_start("META-PB", "META")])
    cmd = "python3 <<EOF\nprint('hello')\nEOF\n && git commit -m x"
    reason = _assert_deny(_run(_bash(cmd), tmp_path))
    assert "test_pass" in reason


# --------- KNOWN LIMITATIONS ---------


@pytest.mark.xfail(
    reason=(
        "known limitation: connectors inside double-quoted strings are "
        'naively split. `echo "git commit && go"` will be segmented and '
        "matched. Documented in impl_pre_bash.py header comment; fix would "
        "require a quote-aware tokenizer (shlex doesn't preserve `&&`)."
    ),
    strict=True,
)
def test_connector_inside_quoted_string_overgates(tmp_path):
    _seed_ledger(tmp_path, [_recent_start("META-PB", "META")])
    _assert_allow(_run(_bash('echo "git commit && go"'), tmp_path))
