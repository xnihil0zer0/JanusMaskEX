import sys
from pathlib import Path
from harness.planner.brief_loader import load_brief

p = Path("/home/xnihil0zer0/JanusMaskJR/brief_hooks_planner_blind_draft_outbox_per_spawn.md")
try:
    brief = load_brief(p)
except Exception as e:
    print("FAIL load_brief raised:", type(e).__name__, e)
    sys.exit(1)

print("OK load_brief did NOT raise")
print("type:", type(brief).__name__)
print("required_task_ids:", getattr(brief, "required_task_ids", "<absent>"))
print("working_dir:", getattr(brief, "working_dir", "<absent>"))
for sec in ("title", "scope", "non_goals", "inputs", "deliverables"):
    v = getattr(brief, sec, None)
    nonempty = bool(v and str(v).strip())
    print(f"section {sec!r}: nonempty={nonempty} len={len(str(v)) if v else 0}")

# Internal consistency of the # Required plan shape: both required_task_ids must
# appear literally in the body as the two declared task_ids.
body = p.read_text()
impl_id = "planner-blind-draft-outbox-per-spawn-impl"
oracle_id = "planner-blind-draft-outbox-per-spawn-oracle"
test_path = "tests/harness/test_planner_blind_draft_outbox_per_spawn.py"
assert impl_id in body, "impl id missing from body"
assert oracle_id in body, "oracle id missing from body"
rti = tuple(getattr(brief, "required_task_ids", ()))
assert impl_id in rti and oracle_id in rti, f"required_task_ids mismatch: {rti}"
# red-pair: impl vcmd substring-contains the oracle test path
assert body.count(test_path) >= 2, "test path should appear for both impl+oracle vcmd"
# non_goals contains literal 'integration'
assert "integration" in getattr(brief, "non_goals", ""), "non_goals must contain 'integration'"
print("CONSISTENCY OK: required_task_ids match declared task_ids; red-pair vcmd shares test path; non_goals has 'integration'")
print("decision file to stage:", f"state/control/decisions/{impl_id}.json (orchestrator.py in _NEVER_AUTO_APPROVE)")
