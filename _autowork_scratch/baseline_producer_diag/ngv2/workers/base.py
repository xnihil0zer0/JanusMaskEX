"""Base worker orchestration primitive for ngv2.

This module provides :func:`StageWorker`, the deterministic glue that wires a
task fetch, a staging step, and an artifact write into a single pipeline. All
collaborators (the task fetcher, the staging function, and the write sink) are
injected, so no concrete seam, conductor, ``get_task``, or phase-worker logic
lives here.
"""
from typing import Any, Callable, Dict, List, Union
Task = Dict[str, Any]
Context = Any
Artifact = Dict[str, Any]
StageResult = Union[Artifact, List[Artifact]]
GetTaskFn = Callable[[Task], Context]
StageFn = Callable[[Context], StageResult]
WriteFn = Callable[[Any, Artifact], None]
OUTPUT_PATH_FIELD = 'output_path'

def _normalize_artifacts(result: StageResult) -> List[Artifact]:
    """Normalize a stage result into a list of artifact dicts.

    ``stage_fn`` may return either a single bare dict or a list of dicts. A
    single dict is wrapped so callers can always iterate one artifact at a
    time. A ``None`` or empty result yields an empty list.
    """
    if result is None:
        return []
    if isinstance(result, dict):
        return [result]
    return list(result)

def StageWorker(task: Task, get_task_fn: GetTaskFn, stage_fn: StageFn, write_fn: WriteFn) -> List[Artifact]:
    """Run a single stage of the worker pipeline.

    The pipeline is strictly ordered: the working context is fetched once via
    ``get_task_fn(task)``, that context is fed to ``stage_fn`` to produce the
    artifact result, and each resulting artifact dict is written to the task's
    output path via ``write_fn``.

    Args:
        task: The session row. Must contain ``output_path``.
        get_task_fn: Injected fetcher returning the downstream context.
        stage_fn: Injected staging step returning a dict or list of dicts.
        write_fn: Injected sink invoked as ``write_fn(output_path, artifact)``.

    Returns:
        The list of artifact dicts that were written, in order.

    Raises:
        KeyError: If the task has no ``output_path``.
    """
    if not isinstance(task, dict) or OUTPUT_PATH_FIELD not in task:
        raise KeyError("task is missing required '%s'; cannot route artifacts" % OUTPUT_PATH_FIELD)
    output_path = task[OUTPUT_PATH_FIELD]
    context = get_task_fn(task)
    result = stage_fn(context)
    artifacts = _normalize_artifacts(result)
    for artifact in artifacts:
        write_fn(output_path, artifact)
    return artifacts