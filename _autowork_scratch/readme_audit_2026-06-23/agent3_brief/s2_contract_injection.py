#!/usr/bin/env python3
"""S2: Prove normalize_plan now injects integration_contracts into task
constraints under key 'integration_contract', and cli.py passes them through."""
import sys, inspect
sys.path.insert(0, "/home/xnihil0zer0/JanusMaskJR")
from harness.planner import plan_normalizer as pn
from harness.planner import cli

print("=== normalize_plan signature ===")
print("  ", inspect.signature(pn.normalize_plan))

print("\n=== cli.main passes contracts to normalize_plan? ===")
csrc = inspect.getsource(cli.main)
print("  'contracts=' in cli.main:", "contracts=" in csrc)
print("  'integration_contracts' in cli.main:", "integration_contracts" in csrc)

print("\n=== Live injection test ===")
plan = {
    "tasks": [
        {"task_id": "t-impl", "meta_task_type": "harness_self_fix",
         "files_touched": ["harness/foo.py"], "constraints": {}},
        {"task_id": "t-other", "meta_task_type": "data_model"},
    ]
}
contracts = {"t-impl": {"entrypoints": ["harness.foo:do_thing"], "symbols": ["do_thing"]}}
out = pn.normalize_plan(plan, repo_root=None, contracts=contracts)
for t in out["tasks"]:
    print(f"  {t['task_id']}: constraints={t.get('constraints')}")
