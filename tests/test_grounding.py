import os
import json
import hmac
import hashlib
import tempfile
import pytest
from harness.grounding import validate_grounding_bundle, classify_failure_severity

def make_dynamic_secret(name: str='default') -> str:
    import uuid
    return f'secret_key_{name}_{uuid.uuid4().hex}'

def create_bundle_file(header, payload, secret_val, path, corrupt_sig=False, empty_sig=False):
    header_str = json.dumps(header, sort_keys=True, separators=(',', ':'))
    payload_str = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    message = f'{header_str}.{payload_str}'.encode('utf-8')
    sig = hmac.new(secret_val.encode('utf-8'), message, hashlib.sha256).hexdigest()
    if corrupt_sig:
        sig = f'corrupt_{sig}'
    data = {'header': header, 'payload': payload, 'signature': '' if empty_sig else sig}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)

def test_validate_grounding_bundle_valid_signature():
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
        path = tmp.name
    try:
        header = {'alg': 'HS256'}
        payload = {'data': 'test_grounding_bundle'}
        secret_val = make_dynamic_secret('valid')
        create_bundle_file(header, payload, secret_val, path)
        assert validate_grounding_bundle(path, secret_val) is True
    finally:
        os.remove(path)

def test_validate_grounding_bundle_invalid_signature():
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
        path = tmp.name
    try:
        header = {'alg': 'HS256'}
        payload = {'data': 'test_grounding_bundle'}
        secret_val = make_dynamic_secret('invalid')
        create_bundle_file(header, payload, secret_val, path, corrupt_sig=True)
        assert validate_grounding_bundle(path, secret_val) is False
        wrong_secret = make_dynamic_secret('wrong')
        create_bundle_file(header, payload, wrong_secret, path)
        assert validate_grounding_bundle(path, secret_val) is False
    finally:
        os.remove(path)

def test_validate_grounding_bundle_missing_fields():
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
        path = tmp.name
    try:
        dummy_secret = make_dynamic_secret('missing_fields')
        dummy_sig = make_dynamic_secret('sig')
        data = {'header': {'alg': 'HS256'}, 'signature': dummy_sig}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        assert validate_grounding_bundle(path, dummy_secret) is False
        data = {'payload': {'data': 1}, 'signature': dummy_sig}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        assert validate_grounding_bundle(path, dummy_secret) is False
        data = {'header': {'alg': 'HS256'}, 'payload': {'data': 1}}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        assert validate_grounding_bundle(path, dummy_secret) is False
        create_bundle_file({'alg': 'HS256'}, {'data': 1}, dummy_secret, path, empty_sig=True)
        assert validate_grounding_bundle(path, dummy_secret) is False
    finally:
        os.remove(path)

def test_validate_grounding_bundle_alg_none():
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
        path = tmp.name
    try:
        dummy_secret = make_dynamic_secret('alg_none')
        create_bundle_file({'alg': 'none'}, {'data': 1}, dummy_secret, path)
        assert validate_grounding_bundle(path, dummy_secret) is False
        create_bundle_file({'alg': None}, {'data': 1}, dummy_secret, path)
        assert validate_grounding_bundle(path, dummy_secret) is False
        create_bundle_file({}, {'data': 1}, dummy_secret, path)
        assert validate_grounding_bundle(path, dummy_secret) is False
    finally:
        os.remove(path)

def test_classify_failure_severity_syntax_error_dependency():
    tb = '\nTraceback (most recent call last):\n  File "tests/test_grounding.py", line 15, in test_foo\n    import harness.grounding\n  File "harness/grounding.py", line 5, in <module>\n    import some_dependency\n  File "some_dependency.py", line 12\n    def syntax_error_here(\n                         ^\nSyntaxError: unexpected EOF while parsing\n'
    assert classify_failure_severity(tb) == 'conceptual_mismatch'

def test_classify_failure_severity_indentation_error_dependency():
    tb = '\nTraceback (most recent call last):\n  File "tests/test_grounding.py", line 15, in test_foo\n    import harness.grounding\n  File "harness/grounding.py", line 5, in <module>\n    import some_dependency\n  File "some_dependency.py", line 12\n    def syntax_error_here():\n    print("wrong indent")\nIndentationError: unexpected indent\n'
    assert classify_failure_severity(tb) == 'conceptual_mismatch'

def test_classify_failure_severity_tab_error_dependency():
    tb = '\nTraceback (most recent call last):\n  File "tests/test_grounding.py", line 15, in test_foo\n    import harness.grounding\n  File "harness/grounding.py", line 5, in <module>\n    import some_dependency\n  File "some_dependency.py", line 12\n    def syntax_error_here():\n\tprint("tab indent")\nTabError: inconsistent use of tabs and spaces in indentation\n'
    assert classify_failure_severity(tb) == 'conceptual_mismatch'

def test_validate_grounding_bundle_file_loading():
    dummy_secret = make_dynamic_secret('file_loading')
    assert validate_grounding_bundle('non_existent_file.json', dummy_secret) is False
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
        path = tmp.name
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write('invalid json content')
        assert validate_grounding_bundle(path, dummy_secret) is False
    finally:
        os.remove(path)

def test_classify_failure_severity_full_traceback():
    tb_mismatch = '\nTraceback (most recent call last):\n  File "/mnt/ai-data/JanusMaskEX/tests/test_grounding.py", line 12, in test_valid\n    import harness.grounding\n  File "/mnt/ai-data/JanusMaskEX/harness/grounding.py", line 2, in <module>\n    import some_dependency\n  File "/usr/local/lib/python3.10/site-packages/some_dependency.py", line 5\n    def bar(\n           ^\nSyntaxError: unexpected EOF while parsing\n'
    assert classify_failure_severity(tb_mismatch) == 'conceptual_mismatch'
    tb_defect = '\nTraceback (most recent call last):\n  File "/mnt/ai-data/JanusMaskEX/tests/test_grounding.py", line 12, in test_valid\n    import harness.grounding\n  File "/mnt/ai-data/JanusMaskEX/harness/grounding.py", line 10, in validate_grounding_bundle\n    raise ValueError("invalid logic")\nValueError: invalid logic\n'
    assert classify_failure_severity(tb_defect) == 'implementation_defect'

def test_validate_grounding_bundle_random_payloads():
    payloads = [{'a': 1, 'b': [1, 2, 3], 'c': {'nested': 'value'}}, 'string_payload', 12345, [1, 2, 3], None]
    secret_val = make_dynamic_secret('random')
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
        path = tmp.name
    try:
        for p in payloads:
            create_bundle_file({'alg': 'HS256'}, p, secret_val, path)
            assert validate_grounding_bundle(path, secret_val) is True
    finally:
        os.remove(path)

def test_classify_failure_severity_handles_target_syntax_error():
    tb = '\nTraceback (most recent call last):\n  File "tests/test_grounding.py", line 12, in test_valid\n    import harness.grounding\n  File "harness/grounding.py", line 3\n    def foo(\n           ^\nSyntaxError: unexpected EOF while parsing\n'
    assert classify_failure_severity(tb) == 'implementation_defect'

def test_classify_failure_severity_malformed_traceback():
    assert classify_failure_severity('') == 'implementation_defect'
    assert classify_failure_severity('   \n   ') == 'implementation_defect'
    assert classify_failure_severity('SyntaxError: invalid syntax') == 'implementation_defect'
    assert classify_failure_severity('ValueError: some error') == 'implementation_defect'