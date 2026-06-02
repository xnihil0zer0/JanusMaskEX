import importlib.util
import json
import pytest
from pathlib import Path
import harness.planner.staging as _staging_mod
from harness.planner.staging import stage_task

# Resolve scripts/impl_plan_to_queue.py relative to the actual repo root of the
# imported harness package, so the oracle is correct under any worktree/checkout
# (NOT a hard-coded absolute path that would target a different tree).
_REPO_ROOT = Path(_staging_mod.__file__).resolve().parents[2]
_IPTQ_PATH = _REPO_ROOT / "scripts" / "impl_plan_to_queue.py"

def _import_impl_plan_to_queue():
    spec = importlib.util.spec_from_file_location(
        "impl_plan_to_queue",
        str(_IPTQ_PATH),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main

def test_stage_task_no_working_dir_param(tmp_path):
    # 1. stage_task(plan, "T", state_dir, canonical=True) with NO working_dir param ->
    #    read the written JSON -> assert "working_dir" NOT in it (stripped). RED on HEAD.
    plan_path = tmp_path / "plan_1.json"
    plan_dict = {
        "tasks": [
            {
                "task_id": "T1",
                "working_dir": "/evil/external",
                "other_field": "val"
            }
        ]
    }
    plan_path.write_text(json.dumps(plan_dict), encoding="utf-8")
    
    state_dir = tmp_path / "state_1"
    
    # Run the staging
    out_path = stage_task(plan_path, "T1", state_dir, canonical=True)
    
    # Read and assert
    staged = json.loads(out_path.read_text(encoding="utf-8"))
    assert "working_dir" not in staged, (
        f"working_dir was not stripped when staging without param. Found: {staged.get('working_dir')}"
    )

def test_stage_task_with_working_dir_param(tmp_path):
    # 2. stage_task(..., working_dir="/trusted/x") -> written JSON["working_dir"] == "/trusted/x"
    #    (trusted param wins, LLM "/evil/external" gone).
    plan_path = tmp_path / "plan_2.json"
    plan_dict = {
        "tasks": [
            {
                "task_id": "T2",
                "working_dir": "/evil/external",
                "other_field": "val"
            }
        ]
    }
    plan_path.write_text(json.dumps(plan_dict), encoding="utf-8")
    
    state_dir = tmp_path / "state_2"
    
    try:
        # We use a keyword argument as specified.
        out_path = stage_task(plan_path, "T2", state_dir, canonical=True, working_dir="/trusted/x")
    except TypeError as e:
        raise AssertionError(
            f"TypeError raised calling stage_task with working_dir (likely missing param at HEAD): {e}"
        ) from e
        
    staged = json.loads(out_path.read_text(encoding="utf-8"))
    assert staged.get("working_dir") == "/trusted/x", (
        f"Expected working_dir='/trusted/x', got: {staged.get('working_dir')}"
    )

def test_impl_plan_to_queue_main(tmp_path):
    # 3. impl_plan_to_queue main(["<plan>","--task","T","--state-dir","<sd>","--canonical"]) ->
    #    read written queue JSON -> assert "working_dir" NOT in it. RED on HEAD.
    plan_path = tmp_path / "plan_3.json"
    plan_dict = {
        "tasks": [
            {
                "task_id": "T3",
                "working_dir": "/evil/external",
                "other_field": "val"
            }
        ]
    }
    plan_path.write_text(json.dumps(plan_dict), encoding="utf-8")
    
    state_dir = tmp_path / "state_3"
    
    main_fn = _import_impl_plan_to_queue()
    
    rc = main_fn([
        str(plan_path),
        "--task", "T3",
        "--state-dir", str(state_dir),
        "--canonical"
    ])
    assert rc == 0, f"impl_plan_to_queue main returned non-zero code {rc}"
    
    # Path where canonical writes
    out_path = state_dir / "tasks" / "T3.json"
    assert out_path.exists(), f"Output file {out_path} was not created"
    
    staged = json.loads(out_path.read_text(encoding="utf-8"))
    assert "working_dir" not in staged, (
        f"working_dir was not stripped by impl_plan_to_queue main. Found: {staged.get('working_dir')}"
    )

if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
