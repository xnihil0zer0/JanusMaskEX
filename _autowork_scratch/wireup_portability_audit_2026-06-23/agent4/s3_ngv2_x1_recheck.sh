#!/bin/bash
# S3: Re-check the X1 / P1.1 cross-process wiring gap at NGv2 HEAD ed91619.
NG=/home/xnihil0zer0/NobleGreedv2
echo "=== NGv2 HEAD ==="; git -C $NG rev-parse --short HEAD
echo
echo "=== A) _PHASE_COUNT_KEY literal (still 3-of-7?) ==="
grep -n "_PHASE_COUNT_KEY = " $NG/ngv2/conductor_seams.py
echo
echo "=== B) Are intermediate-gate keys emitted anywhere in ngv2/ NON-TEST code? ==="
for k in triage_result verify_result novelty_result report_artifact; do
  echo "--- key: $k ---"
  grep -rn "$k" $NG/ngv2/ --include=*.py | grep -v "/tests/" | grep -v "test_" || echo "   (none in non-test ngv2/ code)"
done
echo
echo "=== C) Are the intermediate COUNT keys set by persist? (triaged/verified/novelties/report_count) ==="
for k in triaged verified novelties report_count; do
  echo "--- count key: $k ---"
  grep -rn "'$k'\|\"$k\"" $NG/ngv2/ --include=*.py | grep -v "/tests/" || echo "   (none)"
done
echo
echo "=== D) build_evidence — nested or top-level? (the prior nested-closure blocker) ==="
grep -n "def build_evidence" $NG/ngv2/conductor_seams.py
python3 - <<'PY'
import ast, pathlib
src = pathlib.Path("/home/xnihil0zer0/NobleGreedv2/ngv2/conductor_seams.py").read_text()
tree = ast.parse(src)
top = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
print("  top-level functions:", sorted(top))
print("  build_evidence is TOP-LEVEL:", "build_evidence" in top)
# find enclosing of build_evidence
for n in ast.walk(tree):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for c in ast.walk(n):
            if c is not n and isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef)) and c.name=="build_evidence":
                print(f"  build_evidence is NESTED inside top-level '{n.name}'" if n.name in top else f"  build_evidence nested inside '{n.name}'")
PY
echo
echo "=== E) Is the p11-build-evidence-perphase IMPL in NGv2 master? (grep for intermediate-key emission) ==="
git -C $NG log --oneline -15 | head -15
