"""RED oracle for plan item P-UNB3: the submission interceptor must apply its
non-`.py` AST-validation exemption to NON-PYTHON targets (e.g. config.yaml).

Root cause (verified 2026-06-03 via a live `rev26_p5b_config_keys` dispatch):
`ASTVerificationInterceptor` (harness/interceptors.py:38-58) HAS a non-`.py`
exemption (`if path and not path.endswith(".py"): return None`), but
`poll_for_submission` (harness/orchestrator.py) invokes it for `submit_code`
as `{'code': code}` with NO `path`. So `path=""`, the exemption is skipped,
and a whole-file YAML submission (full config.yaml) is `ast.parse()`-d as
Python and DENIED (`SyntaxError: invalid syntax, L1`). The whole-file re-spec
of P5b config_keys never escaped this because the gate is PATH-BLIND.

This test uses the REAL interceptor registry (NOT a fake) so the bug manifests:
- RED on HEAD: poll denies the YAML submission every loop -> times out -> None.
- GREEN after fix: poll passes the task's non-`.py` target path to the
  interceptor -> exemption fires -> the submission is returned.

Contrast with test_poll_submission_paths.py::test_T12c, which fakes the
registry (always-allow) and therefore does NOT exercise the real AST gate.

No agy/claude spawned; FakePopen never execs.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness.orchestrator as orch


class _FakePopen:
    def __init__(self, work_dir, poll_seq=None):
        self._work_dir = work_dir
        self.pid = 777
        self.returncode = None
        self._poll_seq = list(poll_seq) if poll_seq else None

    def poll(self):
        if self._poll_seq:
            rc = self._poll_seq.pop(0)
            if rc is not None:
                self.returncode = rc
            return rc
        return None  # alive


@pytest.fixture
def state(tmp_path, monkeypatch):
    sd = tmp_path / "state"
    (sd / "sessions").mkdir(parents=True)
    (sd / "tasks").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("JANUSMASK_TASK_ID", "PUNB3")
    return sd


def test_punb3_non_py_yaml_submission_not_denied_by_real_interceptor(state, tmp_path):
    # Whole-file YAML submission for a non-.py target (harness/config.yaml).
    (state / "tasks" / "current_task_PUNB3.json").write_text(
        json.dumps({"files_touched": ["harness/config.yaml"]}))

    wd = tmp_path / "wd"
    (wd / "outbox").mkdir(parents=True)
    yaml_body = (
        "agent_sandbox:\n  bwrap: true\n"
        "synthesis:\n  antigravity_mode: false\n"
        "  enable_single_agent_promotion: false\n"
        "  single_agent_promotion_ceiling: 3\n"
    )
    (wd / "outbox" / "submission.py").write_text(yaml_body)
    proc = _FakePopen(wd)

    # REAL interceptor registry is used (not patched). On HEAD the YAML is
    # ast-parsed and denied -> poll never returns it -> times out to None.
    code = orch.poll_for_submission("claude", state, 1, proc, timeout=3)

    assert code is not None and "agent_sandbox" in code, (
        "P-UNB3: a non-.py (config.yaml) whole-file YAML submission must NOT be "
        "denied by the AST interceptor — poll_for_submission must pass the task's "
        "target path so the interceptors.py non-.py exemption fires."
    )


def test_punb3_py_target_still_ast_validated(state, tmp_path):
    """Guard: the fix must NOT loosen AST validation for real `.py` targets.
    A syntactically-invalid Python submission for a .py target must still be
    denied (poll returns None)."""
    (state / "tasks" / "current_task_PUNB3.json").write_text(
        json.dumps({"files_touched": ["harness/widget.py"]}))

    wd = tmp_path / "wd_py"
    (wd / "outbox").mkdir(parents=True)
    # invalid Python (would fail ast.parse)
    (wd / "outbox" / "submission.py").write_text("def broken(:\n    return\n")
    # process exits so the loop terminates instead of running the full timeout
    proc = _FakePopen(wd, poll_seq=[None, 0])

    code = orch.poll_for_submission("claude", state, 1, proc, timeout=3)
    assert code is None, (
        "invalid Python for a .py target must remain denied by the AST interceptor"
    )
