#!/usr/bin/env python3
import sys
from pathlib import Path

# Add repo root to python path to ensure imports work
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from harness.wire_up import (
    check_wired,
    validate_exemption,
    symbol_reachable_from_live_root,
    LIVE_ROOTS
)
from harness.ast_enforcer import validate_code

def test_check_wired_live_root():
    print("Testing check_wired on a live root module...")
    # harness/orchestrator.py is in LIVE_ROOTS
    result = check_wired(REPO_ROOT, "harness/orchestrator.py")
    print(f"  wired: {result.wired}")
    print(f"  importers: {result.importers}")
    print(f"  reason: {result.reason}")
    assert result.wired is True
    assert "itself a live entrypoint root" in result.reason or "reachable from a live root" in result.reason

def test_check_wired_non_existent():
    print("Testing check_wired on non-existent module...")
    result = check_wired(REPO_ROOT, "harness/non_existent_module.py")
    print(f"  wired: {result.wired}")
    print(f"  reason: {result.reason}")
    assert result.wired is False
    assert "not in the discovered module set" in result.reason

def test_validate_exemption_staged_sibling():
    print("Testing validate_exemption with category 'staged_sibling'...")
    verdict = validate_exemption("staged_sibling", "some_func", "harness/sandbox.py", REPO_ROOT)
    print(f"  honored: {verdict.honored}")
    print(f"  requires_recheck: {verdict.requires_recheck}")
    print(f"  reason: {verdict.reason}")
    assert verdict.honored is False
    assert verdict.requires_recheck is True

def test_validate_exemption_other_categories():
    print("Testing validate_exemption with 'pure_helper' and static floor...")
    
    # 1. FLOOR PASS: symbol is reachable from a live root
    # harness/sandbox.py: _jailed_popen (called internally)
    mod_pass = "harness/sandbox.py"
    sym_pass = "_jailed_popen"
    floor_pass = symbol_reachable_from_live_root(REPO_ROOT, mod_pass, sym_pass)
    print(f"  Static floor check for {mod_pass}::{sym_pass}: {floor_pass}")
    
    v_pass = validate_exemption("pure_helper", sym_pass, mod_pass, REPO_ROOT)
    print(f"  pure_helper exemption for reachable symbol: honored={v_pass.honored}, recheck={v_pass.requires_recheck}")
    assert v_pass.honored == floor_pass
    assert v_pass.requires_recheck is False
    
    # 2. FLOOR FAIL: symbol is not reachable from a live root
    # harness/diff_fuzzer.py: _one_sided_fuzz (not reachable statically)
    mod_fail = "harness/diff_fuzzer.py"
    sym_fail = "_one_sided_fuzz"
    floor_fail = symbol_reachable_from_live_root(REPO_ROOT, mod_fail, sym_fail)
    print(f"  Static floor check for {mod_fail}::{sym_fail}: {floor_fail}")
    
    v_fail = validate_exemption("pure_helper", sym_fail, mod_fail, REPO_ROOT)
    print(f"  pure_helper exemption for orphan symbol: honored={v_fail.honored}, recheck={v_fail.requires_recheck}")
    assert v_fail.honored == floor_fail
    assert v_fail.requires_recheck is False

def test_ast_validation_behavior():
    print("Testing AST validation and relaxation...")
    dangerous_code = """
def test_func():
    exec("import os")
"""
    # Default validation (relax_external_constructs=False)
    violations = validate_code(dangerous_code, relax_external_constructs=False)
    print(f"  Default violations count: {len(violations)}")
    for v in violations:
        print(f"    - [{v.rule}] {v.message} (severity: {v.severity})")
    assert any(v.rule == "security" and "banned for security reasons" in v.message for v in violations)

    # Relaxed validation (relax_external_constructs=True)
    violations_relaxed = validate_code(dangerous_code, relax_external_constructs=True)
    print(f"  Relaxed violations count: {len(violations_relaxed)}")
    for v in violations_relaxed:
        print(f"    - [{v.rule}] {v.message}")
    # The security violation for exec should be suppressed
    assert not any(v.rule == "security" and "banned for security reasons" in v.message for v in violations_relaxed)

def main():
    print("=== STARTING WIRE-UP EMPIRICAL TESTING ===")
    test_check_wired_live_root()
    print()
    test_check_wired_non_existent()
    print()
    test_validate_exemption_staged_sibling()
    print()
    test_validate_exemption_other_categories()
    print()
    test_ast_validation_behavior()
    print("=== ALL TEST CASES PASSED SUCCESSFULLY ===")

if __name__ == "__main__":
    main()
