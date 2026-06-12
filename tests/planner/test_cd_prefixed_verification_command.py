from harness.planner.plan_validator import validate_plan

def _task(vcmd):
    return {"task_id":"CD_1","title":"leaf with cd-prefixed vcmd","meta_task_type":"harness_self_fix","priority":"high","dependencies":[],"files_touched":["harness/planner/plan_normalizer.py"],"acceptance_criteria":["x"],"spec_author":"test","estimated_complexity":"S","verification_command":vcmd}

def _codes(vcmd):
    return {v.code for v in validate_plan({"plan_kind":"implementation","tasks":[_task(vcmd)]})}

def test_leading_cd_prefix_rejected():
    assert "cd_prefixed_verification_command" in _codes("cd /home/xnihil0zer0/NobleGreedv2 && python -m pytest tests/x.py -q")

def test_embedded_cd_reroot_rejected():
    assert "cd_prefixed_verification_command" in _codes("python -m pytest a.py ; cd /elsewhere && python -m pytest b.py")

def test_normal_vcmd_not_rejected():
    assert "cd_prefixed_verification_command" not in _codes("python -m pytest tests/planner/test_plan_normalizer.py -q")
