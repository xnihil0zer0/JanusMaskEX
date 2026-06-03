"""Self-heal Link #3c oracle: the diagnosing-agent prompt in ``_escalate_to_autobrief``
must direct a CORRECTED specification for the ORIGINAL task_id (so dependents like
method_d_06 still resolve on the same id) and must forbid the banned construct that
caused the failure (eval/exec/decorators — the motivating method_d_05 case).

RED on HEAD: the current prompt only asks for a free-form "self-healing plan" brief;
it neither preserves the original task_id for a corrected spec nor forbids eval/exec.
"""
from __future__ import annotations

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
DAEMON = REPO / "harness" / "autowork_daemon.py"


def _func_source(name: str) -> str:
    src = DAEMON.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            seg = ast.get_source_segment(src, node)
            assert seg is not None
            return seg
    raise AssertionError(f"{name} not found in {DAEMON.name}")


def test_escalation_prompt_directs_corrected_same_id_no_eval() -> None:
    body = _func_source("_escalate_to_autobrief")
    low = body.lower()

    forbids_banned = ("eval" in low) and ("exec" in low)
    keeps_id = any(
        marker in low
        for marker in ("same task_id", "same task id", "original task_id",
                       "original task id", "corrected spec", "keep the original",
                       "preserve the task_id")
    )
    assert forbids_banned, (
        "diagnosing-agent prompt must forbid the banned construct (eval/exec) in the "
        "corrective constraint so the re-run does not repeat the AST rejection"
    )
    assert keeps_id, (
        "diagnosing-agent prompt must direct a corrected specification for the ORIGINAL "
        "task_id (so dependents resolve), not a new <task>_fix id"
    )
