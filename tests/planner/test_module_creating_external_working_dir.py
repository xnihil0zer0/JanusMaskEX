import pytest
from pathlib import Path
from harness.planner.plan_validator import validate_plan, _is_module_creating

def _task(*, files, vcmd="python -m pytest tests/test_smoke.py -q"):
    return {"task_id":"EXT_EDIT_1","title":"edit an existing external module","meta_task_type":"io_adapter","priority":"high","dependencies":[],"files_touched":files,"acceptance_criteria":["edit lands"],"spec_author":"test","estimated_complexity":"S","verification_command":vcmd}

def _codes(task, working_dir):
    plan={"plan_kind":"implementation","working_dir":working_dir,"tasks":[task]}
    return {v.code for v in validate_plan(plan)}

def test_existing_external_file_not_module_creating(tmp_path):
    ext_root=tmp_path/"NobleGreedv2"; (ext_root/"noblegreed").mkdir(parents=True); (ext_root/"noblegreed"/"adapter.py").write_text("x = 1\n")
    t=_task(files=["noblegreed/adapter.py"])
    assert _is_module_creating(t, working_dir=str(ext_root)) is False
    assert "missing_wiring_oracle" not in _codes(t, str(ext_root))

def test_absent_external_file_still_module_creating(tmp_path):
    ext_root=tmp_path/"NobleGreedv2"; ext_root.mkdir()
    t=_task(files=["noblegreed/brand_new.py"])
    assert _is_module_creating(t, working_dir=str(ext_root)) is True
    assert "missing_wiring_oracle" in _codes(t, str(ext_root))

def test_jm_self_case_unchanged():
    existing="harness/planner/plan_normalizer.py"; new="harness/planner/zz_definitely_not_existing_module.py"
    assert _is_module_creating(_task(files=[existing])) is False
    assert _is_module_creating(_task(files=[new])) is True
