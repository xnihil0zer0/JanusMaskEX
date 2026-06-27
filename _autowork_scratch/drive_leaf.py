#!/usr/bin/env python3
"""Manual single-file leaf drive: stage -> inject oracle source -> set pytest vcmd.

Usage: python3 _autowork_scratch/drive_leaf.py <plan.json> <impl_task_id> <oracle1> [oracle2 ...]
Then run: python -m harness.orchestrator_worker --state-dir state --task-id <impl_task_id> --config harness/config.yaml
"""
import json
import sys
import glob
import os
from pathlib import Path
from harness.planner.staging import stage_task

plan, tid, *oracles = sys.argv[1], sys.argv[2], *sys.argv[3:]

# clean prior state for a fresh retry budget
for pat in (f"state/tasks/{tid}.json", f"state/output/{tid}.*"):
    for p in glob.glob(pat):
        os.remove(p)
for p in glob.glob(f"state/sessions/*_{tid}_*"):
    os.remove(p)

stage_task(Path(plan), tid, Path("state"))
tp = f"state/tasks/{tid}.json"
t = json.load(open(tp))
vcmd = "python -m pytest " + " ".join(oracles) + " -q"
t["verification_command"] = vcmd
notes = (t.get("spec", {}) or {}).get("implementation_notes", "") or ""
inject = "\n\n=== EXACT ORACLE CONTRACT (your code MUST make ALL these committed pytest files pass; match every name, signature, return type, and string format EXACTLY) ===\n\n"
for o in oracles:
    inject += f"# {o}\n" + open(o).read() + "\n\n"
inject += "=== END ORACLE CONTRACT ===\n"
t.setdefault("spec", {})["implementation_notes"] = notes + inject
json.dump(t, open(tp, "w"), indent=2)
print(f"STAGED {tid} | vcmd={vcmd} | notes_len={len(t['spec']['implementation_notes'])}")
