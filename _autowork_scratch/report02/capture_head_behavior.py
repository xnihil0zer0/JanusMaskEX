"""Capture HEAD behavior of the P1/P2 seams so we can prove flag-OFF byte-identity post-landing.
Run with PYTHONPATH=. python _autowork_scratch/report02/capture_head_behavior.py <out.json>
"""
import sys, json, ast
sys.path.insert(0, '.')
from harness import diff_fuzzer as DF
from harness.rebuild import harvest as HV
from harness.planner.taxonomies import BYPASS_FUZZER_TYPES

out = {}

# --- P1 Seam 1: build_input_strategy strategy KIND for dict-typed params (repr of strategy) ---
# Use a code sample with bare dict + list[dict] params; record the strategy repr per param.
SAMPLE = (
    "def f(config: dict, candidates: list[dict], n: int) -> int:\n"
    "    return 0\n"
)
strat = DF.build_input_strategy(SAMPLE, "f")
out["build_input_strategy_repr"] = repr(strat)

# Per-annotation strategy kind via _strategy_for_annotation (the HEAD path for each)
for ann in ("dict", "list[dict]", "int", "str", "Path", "dict[str, int]"):
    out[f"strategy_for_annotation::{ann}"] = repr(DF._strategy_for_annotation(ann))

# --- P1 Seam 2: _is_fuzzable_annotation verdicts ---
def ann_node(s):
    return ast.parse(s, mode="eval").body
fuzzable = {}
for ann in ("dict", "list[dict]", "int", "str", "Path", "ast.FunctionDef",
            "dict[str, int]", "Config", "list[int]", "Optional[dict]"):
    try:
        fuzzable[ann] = HV._is_fuzzable_annotation(ann_node(ann))
    except Exception as e:
        fuzzable[ann] = f"ERR:{e}"
out["is_fuzzable_annotation"] = fuzzable

# --- BYPASS_FUZZER_TYPES membership (A6 guard) ---
out["bypass_fuzzer_types"] = sorted(BYPASS_FUZZER_TYPES)

# --- P2: one-side waiver result for a bypass meta type (equivalent=True skip) ---
code_a = "def g(x: int) -> int:\n    return x + 1\n"   # defined on a only
code_b = "def unrelated(y: int) -> int:\n    return y\n" # g absent on b
task = {"meta_task_type": "harness_self_fix",
        "constraints": {"function_signature": "def g(x: int) -> int:"}}
res = DF.fuzz_from_task(code_a, code_b, task, DF_CONFIG := {"fuzzing": {"function_level_inputs": 10}}, session_id="hbcap")
out["one_side_waiver"] = {"equivalent": res.equivalent, "skipped_reason": res.skipped_reason,
                          "error": getattr(res, "error", None)}

with open(sys.argv[1], "w") as fh:
    json.dump(out, fh, indent=2, sort_keys=True, default=str)
print("captured ->", sys.argv[1])
print(json.dumps(out, indent=2, default=str)[:1500])
