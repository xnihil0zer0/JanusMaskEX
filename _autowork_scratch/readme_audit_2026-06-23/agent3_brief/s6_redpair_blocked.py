#!/usr/bin/env python3
"""S6: Confirm load_sibling_tasks now scans blocked/ (in addition to processed/ and
base tasks/), skipping <sib>.exhausted dead siblings."""
import sys, json, inspect, tempfile, pathlib
sys.path.insert(0, "/home/xnihil0zer0/JanusMaskJR")
from harness import redpair_acceptance as rp

src = inspect.getsource(rp.load_sibling_tasks)
print("=== load_sibling_tasks scans blocked? ===")
print("  references 'blocked':", "blocked" in src)
print("  references '.exhausted':", ".exhausted" in src)

print("\n=== Live: a blocked sibling depending on our task is now discovered ===")
with tempfile.TemporaryDirectory() as td:
    sd = pathlib.Path(td)
    (sd / "tasks" / "processed").mkdir(parents=True)
    (sd / "tasks" / "blocked").mkdir(parents=True)
    # The impl sibling 't-impl' depends on our oracle 't-oracle', but it's BLOCKED.
    impl = {"task_id": "t-impl", "dependencies": ["t-oracle"], "meta_task_type": "harness_self_fix"}
    (sd / "tasks" / "blocked" / "t-impl.json").write_text(json.dumps(impl))
    # A second blocked sibling that is EXHAUSTED (dead) -> must be skipped.
    dead = {"task_id": "t-dead", "dependencies": ["t-oracle"]}
    (sd / "tasks" / "blocked" / "t-dead.json").write_text(json.dumps(dead))
    (sd / "tasks" / "blocked" / "t-dead.exhausted").write_text("")
    oracle = {"task_id": "t-oracle", "dependencies": [], "meta_task_type": "test_authoring"}
    sibs = rp.load_sibling_tasks(sd, oracle, "t-oracle")
    ids = sorted(s.get("task_id") for s in sibs)
    print("  sibling ids found:", ids)
    print("  t-impl (blocked, live) discovered:", "t-impl" in ids)
    print("  t-dead (blocked, exhausted) skipped:", "t-dead" not in ids)
