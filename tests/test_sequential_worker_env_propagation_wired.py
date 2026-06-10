"""RED oracle (NGv2 gap: sequential-spawn env propagation).

The PARALLEL spawn ``_spawn_worker`` propagates the staged task's trusted
``working_dir`` as ``JANUSMASK_WORKING_DIR`` so an EXTERNAL target's synthesis
(and the smoke gate ``harness/sandbox_smoke.py:smoke_import``, which reads that
var to add the external root to PYTHONPATH/ro-binds) resolves the external
package. The SEQUENTIAL spawn inside ``_iteration`` omitted this, so an external
task's worker never had ``JANUSMASK_WORKING_DIR`` set and a NEW external module
(``from ngv2.contracts import ...``) failed the smoke gate with
``ModuleNotFoundError``.

The fix factors the env-building into a shared helper ``_build_worker_env`` used
by BOTH spawn paths. This oracle pins that helper's contract directly:

  * EXTERNAL task (``working_dir`` = a real external path) -> the returned env
    has ``JANUSMASK_WORKING_DIR`` == that path.
  * SELF task (``working_dir`` absent / None / empty) -> ``JANUSMASK_WORKING_DIR``
    is NOT present in the returned env (popped / never set), even if the parent
    process happens to have it set.
  * Missing / malformed task json -> fail-safe: the var is popped (never
    inherited from the parent).

These are unit-level on the helper to stay hermetic; ``_iteration`` is large and
the sequential branch is hard to drive directly.
"""
from __future__ import annotations

import json
import os

import harness.autowork_daemon as awd

__test__ = True


def _stage_task(state_dir, tid: str, *, working_dir=None) -> None:
    tasks_dir = state_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    obj: dict = {"task_id": tid}
    if working_dir is not None:
        obj["working_dir"] = working_dir
    (tasks_dir / f"{tid}.json").write_text(json.dumps(obj), encoding="utf-8")


def test_build_worker_env_helper_exists(tmp_path):
    # The shared helper must exist (both spawn paths call it).
    assert hasattr(awd, "_build_worker_env"), (
        "_build_worker_env shared helper missing -- sequential spawn cannot "
        "propagate JANUSMASK_WORKING_DIR without it"
    )


def test_external_task_sets_working_dir(tmp_path):
    ext = "/some/external/ngv2/root"
    _stage_task(tmp_path, "ext-task", working_dir=ext)
    env = awd._build_worker_env(tmp_path, "ext-task")
    assert env.get("JANUSMASK_WORKING_DIR") == ext


def test_self_task_pops_working_dir(tmp_path, monkeypatch):
    # SELF task: no working_dir. Even if the PARENT env has the var set, the
    # built env must NOT carry it (fail-safe: never inherit from parent).
    monkeypatch.setenv("JANUSMASK_WORKING_DIR", "/leaked/parent/value")
    _stage_task(tmp_path, "self-task", working_dir=None)
    env = awd._build_worker_env(tmp_path, "self-task")
    assert "JANUSMASK_WORKING_DIR" not in env


def test_empty_working_dir_pops(tmp_path, monkeypatch):
    monkeypatch.setenv("JANUSMASK_WORKING_DIR", "/leaked/parent/value")
    _stage_task(tmp_path, "empty-task", working_dir="")
    env = awd._build_worker_env(tmp_path, "empty-task")
    assert "JANUSMASK_WORKING_DIR" not in env


def test_missing_task_json_failsafe_pops(tmp_path, monkeypatch):
    # No tasks/<tid>.json staged at all -> fail-safe pop, never inherit.
    monkeypatch.setenv("JANUSMASK_WORKING_DIR", "/leaked/parent/value")
    env = awd._build_worker_env(tmp_path, "does-not-exist")
    assert "JANUSMASK_WORKING_DIR" not in env
