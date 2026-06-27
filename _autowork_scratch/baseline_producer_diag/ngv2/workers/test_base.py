"""Regression-lock oracle for ngv2.workers.base.StageWorker.

Locks the committed StageWorker pipeline contract: fetch context once via
get_task_fn, feed it to stage_fn, normalize the result (bare dict -> [dict],
None -> [], list -> list), write each artifact via write_fn(output_path, art),
and return the written artifacts in order. Hermetic: all seams are stubs.
"""
import inspect

import pytest

from ngv2.workers import base
from ngv2.workers.base import StageWorker


def test_signature():
    params = list(inspect.signature(StageWorker).parameters)
    assert params == ["task", "get_task_fn", "stage_fn", "write_fn"]


def test_missing_output_path_raises_keyerror():
    with pytest.raises(KeyError):
        StageWorker({}, lambda t: {}, lambda c: [], lambda p, a: None)


def test_pipeline_order_and_write_fanout():
    writes = []
    task = {"output_path": "/tmp/out/hunt.json", "session_id": "s1"}
    arts = [{"a": 1}, {"a": 2}]
    out = StageWorker(
        task,
        get_task_fn=lambda t: {"ctx_for": t["session_id"]},
        stage_fn=lambda c: arts,
        write_fn=lambda p, a: writes.append((p, a)),
    )
    assert out == arts
    assert writes == [("/tmp/out/hunt.json", {"a": 1}),
                      ("/tmp/out/hunt.json", {"a": 2})]


def test_single_dict_result_is_wrapped():
    out = StageWorker({"output_path": "/x"}, lambda t: {}, lambda c: {"only": 1},
                      lambda p, a: None)
    assert out == [{"only": 1}]


def test_none_result_yields_empty_no_write():
    writes = []
    out = StageWorker({"output_path": "/x"}, lambda t: {}, lambda c: None,
                      lambda p, a: writes.append(a))
    assert out == []
    assert writes == []
