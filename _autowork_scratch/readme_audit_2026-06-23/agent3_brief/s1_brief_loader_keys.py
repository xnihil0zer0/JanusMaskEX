#!/usr/bin/env python3
"""S1: Enumerate the frontmatter keys load_brief actually reads, and confirm
the NEW integration_contracts dataclass field + parsing path."""
import sys, ast, inspect
sys.path.insert(0, "/home/xnihil0zer0/JanusMaskJR")
from harness.planner import brief_loader as bl

print("=== PlanningBrief dataclass fields ===")
import dataclasses
for f in dataclasses.fields(bl.PlanningBrief):
    print(f"  {f.name}")

print("\n=== Does load_brief source mention integration_contracts? ===")
src = inspect.getsource(bl.load_brief)
print("  'integration_contracts' in load_brief:", "integration_contracts" in src)
print("  recognized sub-keys in contract coercion:",
      [k for k in ("entrypoints", "symbols", "runtime_oracle") if k in src])

print("\n=== Live parse of a brief WITH integration_contracts frontmatter ===")
import tempfile, pathlib
brief_text = '''---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
required_task_ids:
  - t-impl
integration_contracts:
  t-impl:
    entrypoints: ["harness.foo:do_thing"]
    symbols: ["do_thing"]
    runtime_oracle: "tests/harness/test_foo_wired.py"
---
# Title
X
# Scope
EDIT harness/foo.py
# Inputs
READ harness/foo.py
# Non-Goals
integration out of scope
# Deliverables
done
'''
with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
    fh.write(brief_text)
    p = fh.name
b = bl.load_brief(pathlib.Path(p))
print("  parsed integration_contracts:", b.integration_contracts)
