"""RED oracle: plan_normalizer must correct a leaf mis-typed to run the Python
diff-fuzzer on a NON-Python target.

Root cause (root-cause fix for the overseer-chat "pin every leaf" workaround):
epic decomposition / leaf planning sometimes types a frontend (.js/.html/.css)
edit as ``io_adapter`` (``bypass_fuzzer=False``), so the Python diff-fuzzer runs
on JavaScript and the otherwise-correct leaf fails with ``fuzz_error``. The hand
workaround was to force ``meta_task_type`` per leaf in a pinned brief. This makes
``normalize_plan`` apply that correction DETERMINISTICALLY, by target file.

Contract: ``normalize_plan(plan)`` retypes a task ONLY when its current
``meta_task_type`` is NOT already a bypass-fuzzer type AND its ``files_touched``
are uniformly off the Python fuzzer's domain:
  * all non-Python static assets (.js/.jsx/.ts/.tsx/.mjs/.html/.htm/.css/.scss)
    -> ``harness_plumbing``
  * all config files (.yaml/.yml/.toml/.ini/.cfg) -> ``harness_self_fix``
It never disturbs a task already on a bypass-fuzzer type, a Python (.py) target,
a mixed target set, or an empty ``files_touched``. Pure (no input mutation),
idempotent.
"""
from __future__ import annotations

import copy

from harness.planner.plan_normalizer import normalize_plan
from harness.planner.taxonomies import BYPASS_FUZZER_TYPES, META_TASK_POLICY


def _plan(meta, files):
    return {
        "tasks": [
            {
                "task_id": "leaf",
                "title": "t",
                "meta_task_type": meta,
                "files_touched": list(files),
                "dependencies": [],
                "verification_command": "python -m pytest tests/overseer/test_x.py -q",
                "spec": {"implementation_notes": ""},
            }
        ]
    }


def _type(plan):
    return normalize_plan(plan)["tasks"][0]["meta_task_type"]


def test_io_adapter_on_js_becomes_harness_plumbing():
    assert _type(_plan("io_adapter", ["tools/webui_static/app.js"])) == "harness_plumbing"


def test_frontend_bundle_js_html_css_becomes_harness_plumbing():
    assert _type(_plan("io_adapter", ["a/app.js", "a/index.html", "a/styles.css"])) == "harness_plumbing"


def test_corrected_asset_type_bypasses_fuzzer_and_structural_decomp():
    t = _type(_plan("io_adapter", ["x/app.js"]))
    assert META_TASK_POLICY[t]["bypass_fuzzer"] is True
    assert META_TASK_POLICY[t]["skip_structural_decomp"] is True


def test_fuzzer_running_config_edit_becomes_harness_self_fix():
    assert _type(_plan("cli_tooling", ["harness/config.yaml"])) == "harness_self_fix"


def test_python_target_is_left_untouched():
    assert _type(_plan("io_adapter", ["overseer/driver.py"])) == "io_adapter"


def test_already_bypass_type_is_not_disturbed():
    # data_model already bypasses the fuzzer; do not second-guess it, even on .js.
    assert "data_model" in BYPASS_FUZZER_TYPES
    assert _type(_plan("data_model", ["x/app.js"])) == "data_model"


def test_mixed_python_and_asset_is_left_untouched():
    assert _type(_plan("io_adapter", ["x/app.js", "x/mod.py"])) == "io_adapter"


def test_empty_files_touched_is_noop():
    assert _type(_plan("io_adapter", [])) == "io_adapter"


def test_pure_no_input_mutation():
    p = _plan("io_adapter", ["x/app.js"])
    snap = copy.deepcopy(p)
    normalize_plan(p)
    assert p == snap


def test_idempotent():
    p = _plan("io_adapter", ["x/app.js"])
    once = normalize_plan(p)
    twice = normalize_plan(copy.deepcopy(once))
    assert twice["tasks"][0]["meta_task_type"] == "harness_plumbing"
    assert once == twice
