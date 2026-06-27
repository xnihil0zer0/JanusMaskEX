"""(c) _restrict_sidecar_to_declared: drops undeclared, idempotent, robust to bad input."""
import sys, os, json, tempfile, pathlib
sys.path.insert(0, "/home/xnihil0zer0/JanusMaskJR")
from harness.orchestrator import _restrict_sidecar_to_declared as R

tmp = pathlib.Path(tempfile.mkdtemp(prefix="adv_c_"))

# c1: drops undeclared keys, rewrites sidecar to declared subset
p1 = tmp / "t1.files.json"
p1.write_text(json.dumps({
    "harness/target_bootstrap.py": "x=1",
    "config/target_bootstrap.yaml": "k: v",      # undeclared stray
    "harness/other.py": "y=2",                    # undeclared stray
}))
dropped1 = R(p1, ["harness/target_bootstrap.py"])
after1 = json.loads(p1.read_text())
print("=== c1 drop ===")
print("dropped1:", sorted(dropped1))
print("remaining keys:", sorted(after1.keys()))
print("PASS_C1:", sorted(dropped1) == ["config/target_bootstrap.yaml", "harness/other.py"]
      and sorted(after1.keys()) == ["harness/target_bootstrap.py"])

# c2: idempotent on a clean sidecar => returns [] and leaves bytes UNCHANGED
p2 = tmp / "t2.files.json"
p2.write_text(json.dumps({"harness/target_bootstrap.py": "x=1"}, indent=2, sort_keys=True))
before2 = p2.read_bytes()
dropped2 = R(p2, ["harness/target_bootstrap.py"])
after2 = p2.read_bytes()
print("=== c2 idempotent/clean ===")
print("dropped2:", dropped2, "bytes_unchanged:", before2 == after2)
print("PASS_C2:", dropped2 == [] and before2 == after2)

# c3a: missing file => [] no raise
dropped3a = R(tmp / "does_not_exist.files.json", ["a.py"])
# c3b: malformed JSON => [] no raise
p3b = tmp / "t3b.files.json"; p3b.write_text("{not valid json")
dropped3b = R(p3b, ["a.py"])
# c3c: non-dict JSON (a list) => [] no raise; file left unchanged
p3c = tmp / "t3c.files.json"; p3c.write_text(json.dumps(["a", "b"]))
before3c = p3c.read_bytes()
dropped3c = R(p3c, ["a.py"])
after3c = p3c.read_bytes()
print("=== c3 robustness ===")
print("missing:", dropped3a, "malformed:", dropped3b, "nondict:", dropped3c,
      "nondict_unchanged:", before3c == after3c)
print("PASS_C3:", dropped3a == [] and dropped3b == [] and dropped3c == [] and before3c == after3c)
