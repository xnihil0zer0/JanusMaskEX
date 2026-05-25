"""Planner stage: attach a generated verification oracle to a test-less task.

The planner ORCHESTRATES the independent test-author role (``harness.test_author``)
the same way it orchestrates the draft/reconcile agents -- it does not reimplement
test generation inline. When a task arrives with no ``verification_command`` (its
target project ships no adequate tests), this stage invokes the role to GENERATE a
non-vacuous oracle and attaches it as the task's ``verification_command`` so a
downstream blind synthesis is gated. The non-vacuity guarantee (the oracle must
fail the stripped stub) is owned by the role, not duplicated here.

Self-modification keeps the operator-reviewed-oracle bar (see
``brief_hooks_test_author_role.md`` Non-Goals): callers pass
``allow_self_modification=False`` (the default) so a task whose target lives under
``harness/`` is left untouched for operator review.
"""

from __future__ import annotations

from typing import Any, Callable

from harness import test_author


def task_needs_oracle(task: dict[str, Any]) -> bool:
    """True iff ``task`` carries no usable ``verification_command``."""
    vcmd = task.get("verification_command")
    return not (isinstance(vcmd, str) and vcmd.strip())


def _target_is_self_modification(target_module_name: str, files_touched) -> bool:
    if isinstance(files_touched, (list, tuple)):
        for f in files_touched:
            if str(f).startswith("harness/") or str(f).startswith("harness."):
                return True
    return False


def attach_oracle(
    task: dict[str, Any],
    target_source: str,
    target_module_name: str,
    config: dict[str, Any],
    state_dir,
    *,
    gen_fn: Callable | None = None,
    max_attempts: int = 2,
    python_exe: str | None = None,
    allow_self_modification: bool = False,
) -> dict[str, Any]:
    """Return ``task`` with a generated, non-vacuous ``verification_command``.

    No-op (returns the task unchanged) when the task already has a
    ``verification_command`` or when the target is a self-modification of the
    harness and ``allow_self_modification`` is False. Otherwise invokes the
    independent test-author role; on success sets ``verification_command`` and
    records the generated oracle under ``generated_oracle`` (its test code +
    filename + attempt count) so a caller can persist the test file. Propagates
    ``test_author.VacuousOracleError`` if the role cannot produce a non-vacuous
    oracle.
    """
    if not task_needs_oracle(task):
        return task
    if not allow_self_modification and _target_is_self_modification(
        target_module_name, task.get("files_touched")
    ):
        return task
    spec = {
        "description": task.get("specification") or task.get("title") or target_module_name,
        "module": target_module_name,
    }
    oracle = test_author.author_oracle(
        target_module_name,
        target_source,
        spec,
        config,
        state_dir,
        gen_fn=gen_fn,
        max_attempts=max_attempts,
        python_exe=python_exe,
        task_id=task.get("task_id"),
    )
    task["verification_command"] = oracle.verification_command
    task["generated_oracle"] = {
        "test_code": oracle.test_code,
        "test_filename": oracle.test_filename,
        "attempts": oracle.attempts,
    }
    return task
