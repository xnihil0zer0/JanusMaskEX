import sys
from pathlib import Path
REPO=Path("/home/xnihil0zer0/JanusMaskJR"); sys.path.insert(0,str(REPO))
import importlib.util
spec=importlib.util.spec_from_file_location("pn", REPO/"harness/planner/plan_normalizer.py")
pn=importlib.util.module_from_spec(spec); spec.loader.exec_module(pn)
# generate_ast_summary is a closure inside _inject_oracle_sources; exercise via the public injector
SENT="SENT_EDGE_55501"
src=f'''"""module docstring with {SENT}_docstr fixture"""
import pytest

@pytest.mark.parametrize("v", ["{SENT}_decorator"])
def test_a(v, default="{SENT}_default"):
    assert v == "{SENT}_assertbody"

class Cfg(dict, key="{SENT}_classkw"):
    EXPECTED = "{SENT}_classattr"
    def method(self):
        return "{SENT}_methodbody"
'''
import tempfile
with tempfile.TemporaryDirectory() as td:
    root=Path(td); (root/"tests").mkdir()
    rel="tests/test_edge.py"; (root/rel).write_text(src)
    plan={"tasks":[{"id":"e","meta_task_type":"implementation","files_touched":["w.py"],
        "verification_command":f"python -m pytest {rel} -q","spec":{"implementation_notes":"x"}}]}
    out=pn._inject_oracle_sources(plan,str(root))
    notes=out["tasks"][0]["spec"]["implementation_notes"]
    print("--- summary ---"); print(notes); print("--- checks ---")
    for tag in ["docstr","decorator","default","assertbody","classkw","classattr","methodbody"]:
        s=f"{SENT}_{tag}"
        print(f"  {tag:11s} leaked: {s in notes}")
