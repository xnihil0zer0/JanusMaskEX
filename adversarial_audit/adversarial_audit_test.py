import sys
import os
import json
import hmac
import hashlib
import traceback

# Add project root to path
sys.path.append("/home/xnihil0zer0/AI-Data/JanusMaskEX")

from harness.grounding import validate_grounding_bundle, classify_failure_severity

def test_signature_validation():
    print("=== Testing validate_grounding_bundle ===")
    
    # 1. Test Valid Bundle
    key = "my_secret_key"
    header = {"alg": "HS256"}
    payload = {"axioms": ["always use valid path"], "task_id": "task_1"}
    
    header_str = json.dumps(header, sort_keys=True, separators=(',', ':'))
    payload_str = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    message = f"{header_str}.{payload_str}".encode('utf-8')
    sig = hmac.new(key.encode('utf-8'), message, hashlib.sha256).hexdigest()
    
    bundle_data = {
        "header": header,
        "payload": payload,
        "signature": sig
    }
    
    bundle_path = "temp_valid_bundle.json"
    with open(bundle_path, "w") as f:
        json.dump(bundle_data, f)
        
    try:
        res = validate_grounding_bundle(bundle_path, key)
        print(f"Valid Signature Test: {res} (Expected: True)")
        
        # 2. Test Alg None Exploitation
        bundle_data_none = bundle_data.copy()
        bundle_data_none["header"] = {"alg": "none"}
        bundle_path_none = "temp_none_bundle.json"
        with open(bundle_path_none, "w") as f:
            json.dump(bundle_data_none, f)
        res_none = validate_grounding_bundle(bundle_path_none, key)
        print(f"Alg None Exploitation Test: {res_none} (Expected: False)")
        os.remove(bundle_path_none)
        
        # 3. Test Default Secret Key Vulnerability
        default_key = "default_secret_key"
        default_sig = hmac.new(default_key.encode('utf-8'), message, hashlib.sha256).hexdigest()
        bundle_data_default = {
            "header": header,
            "payload": payload,
            "signature": default_sig
        }
        bundle_path_default = "temp_default_bundle.json"
        with open(bundle_path_default, "w") as f:
            json.dump(bundle_data_default, f)
        res_default = validate_grounding_bundle(bundle_path_default, default_key)
        print(f"Default Key Vulnerability Test: {res_default} (Expected: True - shows default key is vulnerable if not overridden)")
        os.remove(bundle_path_default)
        
    finally:
        if os.path.exists(bundle_path):
            os.remove(bundle_path)

def test_failure_classification():
    print("\n=== Testing classify_failure_severity ===")
    
    # 1. External dependency SyntaxError
    tb_external = """Traceback (most recent call last):
  File "harness/orchestrator.py", line 3770, in run
    import some_external_lib
  File "/usr/lib/python3.10/site-packages/some_external_lib.py", line 15
    def invalid_syntax_here(
                           ^
SyntaxError: unexpected EOF while parsing
"""
    res_external = classify_failure_severity(tb_external)
    print(f"External Dep SyntaxError: {res_external} (Expected: conceptual_mismatch)")
    
    # 2. Project file SyntaxError
    tb_project = """Traceback (most recent call last):
  File "harness/orchestrator.py", line 3770, in run
    import harness.grounding
  File "/home/xnihil0zer0/AI-Data/JanusMaskEX/harness/grounding.py", line 25
    def validate_grounding_bundle(
                                 ^
SyntaxError: unexpected EOF while parsing
"""
    res_project = classify_failure_severity(tb_project)
    print(f"Project File SyntaxError: {res_project} (Expected: implementation_defect)")
    
    # 3. Path Parsing Bug (.venv in project path)
    tb_venv_bug = """Traceback (most recent call last):
  File "harness/orchestrator.py", line 3770, in run
    import harness.grounding
  File "/home/xnihil0zer0/AI-Data/.venv-project/JanusMaskEX/harness/grounding.py", line 25
    def validate_grounding_bundle(
                                 ^
SyntaxError: unexpected EOF while parsing
"""
    res_venv_bug = classify_failure_severity(tb_venv_bug)
    print(f"Path Parsing Bug (.venv in path): {res_venv_bug} (Expected: implementation_defect, Actual: {res_venv_bug})")
    
    # 4. Chained Exception ignoring root cause
    tb_chained = """Traceback (most recent call last):
  File "/usr/lib/python3.10/site-packages/some_external_lib.py", line 15, in <module>
    def invalid_syntax_here(
                           ^
SyntaxError: unexpected EOF while parsing

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "harness/orchestrator.py", line 3770, in run
    raise ValueError("Wrapper error")
ValueError: Wrapper error
"""
    res_chained = classify_failure_severity(tb_chained)
    print(f"Chained Exception: {res_chained} (Expected: conceptual_mismatch, Actual: {res_chained})")
    
    # 5. Non-SyntaxError conceptual mismatch (e.g. ModuleNotFoundError)
    tb_module_not_found = """Traceback (most recent call last):
  File "/usr/lib/python3.10/site-packages/some_lib.py", line 10, in <module>
    import missing_module
ModuleNotFoundError: No module named 'missing_module'
"""
    res_mnf = classify_failure_severity(tb_module_not_found)
    print(f"ModuleNotFoundError: {res_mnf} (Expected: conceptual_mismatch, Actual: {res_mnf})")

if __name__ == "__main__":
    test_signature_validation()
    test_failure_classification()
