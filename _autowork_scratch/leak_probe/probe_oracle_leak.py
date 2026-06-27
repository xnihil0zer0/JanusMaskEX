#!/usr/bin/env python3
"""Empirical probe for the suspected 'answer-key leak' in
harness/planner/plan_normalizer.py::_inject_oracle_sources.

Two independent tests:
  A) SYNTHETIC: build a tiny RED oracle whose body contains a unique sentinel
     literal, run _inject_oracle_sources, and check whether the sentinel
     survives into task['spec']['implementation_notes'].
  B) REAL SCAN: walk state/tasks/processed/*.json. For each task with a
     COMMITTED ORACLE CONTRACT block, re-read the named oracle file and test
     whether its assert-line / string-literal fixtures appear verbatim in the
     injected notes (i.e. the worker could read the answers).
"""
import json
import os
import re
import sys
import tempfile
import ast
from pathlib import Path

REPO = Path("/home/xnihil0zer0/JanusMaskJR")
sys.path.insert(0, str(REPO))

from harness.planner.plan_normalizer import _inject_oracle_sources  # noqa: E402

SENTINEL = "ZZZ_SENTINEL_4711_answerkey"
NUM_SENTINEL = "918273645"  # unique numeric fixture


def test_synthetic():
    print("=" * 70)
    print("TEST A: SYNTHETIC SENTINEL (deterministic mechanism isolation)")
    print("=" * 70)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tdir = root / "tests" / "harness"
        tdir.mkdir(parents=True)
        oracle_rel = "tests/harness/test_probe_widget.py"
        oracle_src = (
            "import importlib.util\n"
            "from pathlib import Path\n"
            "\n"
            f'EXPECTED = "{SENTINEL}"\n'
            f"MAGIC_NUMBER = {NUM_SENTINEL}\n"
            "\n"
            "def _load(p):\n"
            "    spec = importlib.util.spec_from_file_location('m', p)\n"
            "    mod = importlib.util.module_from_spec(spec)\n"
            "    spec.loader.exec_module(mod)\n"
            "    return mod\n"
            "\n"
            "def test_compute_returns_expected(tmp_path):\n"
            "    mod = _load(Path('widget.py'))\n"
            f'    assert mod.compute() == "{SENTINEL}"\n'
            f"    assert mod.magic() == {NUM_SENTINEL}\n"
        )
        (root / oracle_rel).write_text(oracle_src)

        plan = {
            "tasks": [
                {
                    "id": "probe-impl-1",
                    "meta_task_type": "implementation",
                    "files_touched": ["widget.py"],
                    "verification_command": f"python -m pytest {oracle_rel} -q",
                    "spec": {
                        "implementation_notes": "Implement compute() and magic() in widget.py."
                    },
                }
            ]
        }
        out = _inject_oracle_sources(plan, str(root))
        notes = out["tasks"][0]["spec"]["implementation_notes"]

        print("\n--- injected implementation_notes (verbatim) ---")
        print(notes)
        print("--- end notes ---\n")

        str_leak = SENTINEL in notes
        num_leak = NUM_SENTINEL in notes
        has_block = "COMMITTED ORACLE CONTRACT" in notes
        has_sig = "def test_compute_returns_expected" in notes  # interface context preserved?

        print(f"COMMITTED ORACLE CONTRACT block injected : {has_block}")
        print(f"string sentinel '{SENTINEL}' present     : {str_leak}")
        print(f"numeric sentinel '{NUM_SENTINEL}' present : {num_leak}")
        print(f"test-fn signature preserved (interface)  : {has_sig}")
        return {"str_leak": str_leak, "num_leak": num_leak,
                "has_block": has_block, "has_sig": has_sig}


def _extract_oracle_block(notes):
    """Return list of (rel_path, code_block_text) from a notes string."""
    if not isinstance(notes, str) or "COMMITTED ORACLE CONTRACT" not in notes:
        return []
    out = []
    # blocks look like: '## <rel>\n```python\n...\n```'
    for m in re.finditer(r"##\s+(\S+)\n```python\n(.*?)\n```", notes, re.S):
        out.append((m.group(1), m.group(2)))
    return out


def _literal_fixtures(src):
    """Pull string + numeric literals that appear inside assert statements
    (these are the 'answer key' values a worker would game)."""
    fixtures = set()
    try:
        tree = ast.parse(src)
    except Exception:
        return fixtures
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, (str, int, float)):
                    v = sub.value
                    if isinstance(v, str) and len(v) >= 6:
                        fixtures.add(v)
                    elif isinstance(v, (int, float)) and abs(v) >= 1000:
                        fixtures.add(str(v))
    return fixtures


def test_real():
    print("\n" + "=" * 70)
    print("TEST B: REAL PLANNED-TASK SCAN (state/tasks/processed/*.json)")
    print("=" * 70)
    proc = REPO / "state" / "tasks" / "processed"
    files = sorted(proc.glob("*.json"))
    scanned = 0
    with_block = 0
    leaked = 0
    examples = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        # a task json may be a single task dict or wrap a 'spec'
        spec = data.get("spec") if isinstance(data, dict) else None
        if not isinstance(spec, dict):
            continue
        scanned += 1
        notes = spec.get("implementation_notes")
        blocks = _extract_oracle_block(notes)
        if not blocks:
            continue
        with_block += 1
        for rel, _blocktext in blocks:
            oracle_path = REPO / rel
            if not oracle_path.is_file():
                continue
            try:
                osrc = oracle_path.read_text(encoding="utf-8")
            except Exception:
                continue
            fixtures = _literal_fixtures(osrc)
            hit = [fx for fx in fixtures if fx and fx in notes]
            if hit:
                leaked += 1
                if len(examples) < 3:
                    tid = data.get("id") or data.get("task_id") or f.stem
                    examples.append((tid, rel, hit[:2]))
                break
    print(f"\ntasks scanned (have spec dict)        : {scanned}")
    print(f"tasks with COMMITTED ORACLE block     : {with_block}")
    print(f"tasks leaking an assert-fixture literal: {leaked}")
    if examples:
        print("\nconcrete leaked examples (task_id | oracle | leaked literal[redacted]):")
        for tid, rel, hit in examples:
            red = [(h[:14] + "...") if len(h) > 14 else h for h in hit]
            print(f"  - {tid} | {rel} | {red}")
    return {"scanned": scanned, "with_block": with_block, "leaked": leaked}


if __name__ == "__main__":
    a = test_synthetic()
    b = test_real()
    print("\n" + "=" * 70)
    print("VERDICT SUMMARY")
    print("=" * 70)
    syn_leak = a["str_leak"] or a["num_leak"]
    real_leak = b["leaked"] > 0
    print(f"synthetic leak (sentinel survives)    : {syn_leak}")
    print(f"real-task leak (assert fixture leaks) : {real_leak} ({b['leaked']}/{b['with_block']})")
    if syn_leak or real_leak:
        print(">>> LEAK PRESENT")
    else:
        print(">>> NO LEAK DETECTED (mitigated: AST-signature summary strips bodies/literals)")
