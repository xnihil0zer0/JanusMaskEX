from pathlib import Path
from harness.planner.plan_normalizer import normalize_plan

def _impl(mod_relpath, vcmd):
    return {"task_id":"IMPL_1","title":"edit existing module","meta_task_type":"io_adapter","priority":"high","dependencies":[],"files_touched":[mod_relpath],"verification_command":vcmd}

def _oracle(target):
    return {"task_id":"ORACLE_1","title":"redundant oracle sibling","meta_task_type":"test_authoring","priority":"high","dependencies":[],"mutation_target":target,"files_touched":["tests/pkg/test_mod_new.py"],"verification_command":"python -m pytest tests/pkg/test_mod_new.py -q"}

def test_singleton_sibling_dropped_when_committed_oracle_exists(tmp_path):
    (tmp_path/"pkg").mkdir(); (tmp_path/"pkg"/"mod.py").write_text("def f():\n    return 1\n")
    (tmp_path/"tests"/"pkg").mkdir(parents=True); (tmp_path/"tests"/"pkg"/"test_mod.py").write_text("from pkg.mod import f\n\ndef test_f():\n    assert f() == 1\n")
    plan={"plan_kind":"implementation","tasks":[_impl("pkg/mod.py","python -m pytest tests/pkg/test_mod.py -q"),_oracle("pkg.mod")]}
    out=normalize_plan(plan, repo_root=tmp_path)
    ids={t["task_id"] for t in out["tasks"]}
    assert "ORACLE_1" not in ids
    assert "IMPL_1" in ids

def test_sibling_kept_when_no_committed_oracle(tmp_path):
    (tmp_path/"pkg").mkdir(); (tmp_path/"pkg"/"mod.py").write_text("def f():\n    return 1\n")
    plan={"plan_kind":"implementation","tasks":[_impl("pkg/mod.py","python -m pytest tests/pkg/test_mod_new.py -q"),_oracle("pkg.mod")]}
    out=normalize_plan(plan, repo_root=tmp_path)
    ids={t["task_id"] for t in out["tasks"]}
    assert "ORACLE_1" in ids
