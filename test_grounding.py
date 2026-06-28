import sys
sys.path.append("/mnt/ai-data/JanusMaskEX")
import harness.grounding as grounding
import json
import hmac
import hashlib
import os

key = "test_key"
payload = {"axioms": ["axiom 1"]}
header = {"alg": "HS256"}
header_str = json.dumps(header, sort_keys=True, separators=(',', ':'))
payload_str = json.dumps(payload, sort_keys=True, separators=(',', ':'))
message = f'{header_str}.{payload_str}'.encode('utf-8')
signature = hmac.new(key.encode('utf-8'), message, hashlib.sha256).hexdigest()

data = {
    "header": header,
    "payload": payload,
    "signature": signature
}
with open("test_bundle.json", "w") as f:
    json.dump(data, f)

valid = grounding.validate_grounding_bundle("test_bundle.json", key)
print("Valid bundle:", valid)

# Test manipulated bundle
data["header"]["alg"] = "none"
with open("test_bundle_manip.json", "w") as f:
    json.dump(data, f)
valid_manip = grounding.validate_grounding_bundle("test_bundle_manip.json", key)
print("Manipulated bundle (alg: none):", valid_manip)

# Test manipulated signature
data["header"]["alg"] = "HS256"
data["signature"] = "fake"
with open("test_bundle_sig.json", "w") as f:
    json.dump(data, f)
valid_sig = grounding.validate_grounding_bundle("test_bundle_sig.json", key)
print("Manipulated signature:", valid_sig)

# Test conceptual failure classification
tb_conceptual = '''Traceback (most recent call last):
  File "/usr/lib/python3.10/site-packages/some_lib.py", line 10, in <module>
    import missing_module
ModuleNotFoundError: No module named 'missing_module'
'''
print("Conceptual failure classification:", grounding.classify_failure_severity(tb_conceptual))

tb_conceptual2 = '''Traceback (most recent call last):
  File "/mnt/ai-data/JanusMaskEX/harness/grounding.py", line 10, in <module>
    import missing_module
ModuleNotFoundError: No module named 'missing_module'
'''
print("Target failure classification:", grounding.classify_failure_severity(tb_conceptual2))

tb_syntax = '''Traceback (most recent call last):
  File "/usr/lib/python3.10/site-packages/some_lib.py", line 10, in <module>
SyntaxError: invalid syntax
'''
print("Syntax error in external lib classification:", grounding.classify_failure_severity(tb_syntax))
