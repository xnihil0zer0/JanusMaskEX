"""CLAIM A empirical test against HEAD classify_poc_authenticity.

Doc claim: a bare attribute reference like `acmecorp_app.__name__` flips a
fully self-hosted mock to real_target/may_confirm=True; and network_live mode
confirms a non-localhost HTTP PoC with NO target import.
"""
import json
from ngv2.poc_authenticity_gate import classify_poc_authenticity

results = {}

# (A1) self-hosted mock with ONLY a bare attribute reference to target name.
# Per doc: this should flip to real_target/may_confirm=True.
poc_bare_attr_ref = '''
import acmecorp_app

def mock_handler(request):
    # self-hosted mock re-implementation of the vuln
    return "VULNERABLE"

# bare attribute reference -- NOT a call into the target
x = acmecorp_app.__name__
print(mock_handler(None))
'''
results['A1_bare_attr_ref'] = classify_poc_authenticity(
    poc_bare_attr_ref, ['acmecorp_app'])

# (A1b) bare attribute reference WITHOUT a call, no local vuln def, to isolate.
poc_bare_attr_only = '''
import acmecorp_app
x = acmecorp_app.__name__
'''
results['A1b_bare_attr_only'] = classify_poc_authenticity(
    poc_bare_attr_only, ['acmecorp_app'])

# (A1c) ACTUAL call into target (the new has_target_call requirement)
poc_real_call = '''
import acmecorp_app
acmecorp_app.run_request("payload")
'''
results['A1c_real_target_call'] = classify_poc_authenticity(
    poc_real_call, ['acmecorp_app'])

# (A2) network_live-mode PoC, NO target import, NON-localhost host.
# Per doc: should confirm (may_confirm=True via network_live).
poc_network_live_remote = '''
import requests
resp = requests.get("http://attacker.example.com:9000/x")
print(resp.status_code)
'''
results['A2_network_live_remote_no_target'] = classify_poc_authenticity(
    poc_network_live_remote, ['acmecorp_app'])

# (A2b) network PoC that targets localhost -- new targets_localhost guard
poc_network_localhost = '''
import requests
resp = requests.get("http://127.0.0.1:8000/x")
print(resp.status_code)
'''
results['A2b_network_localhost'] = classify_poc_authenticity(
    poc_network_localhost, ['acmecorp_app'])

# (A2c) network PoC with a local vuln def (defines_vuln_locally) -> self mock
poc_network_with_local_vuln = '''
import requests
def mock_server(): return "VULNERABLE"
resp = requests.get("http://attacker.example.com:9000/x")
'''
results['A2c_network_with_local_vuln'] = classify_poc_authenticity(
    poc_network_with_local_vuln, ['acmecorp_app'])

print(json.dumps(results, indent=2))

print("\n=== CLAIM A VERDICT SUMMARY ===")
a1 = results['A1_bare_attr_ref']
print("A1 bare-attr-ref flips mock->real_target/may_confirm? ",
      a1['mode'] == 'real_target' and a1['may_confirm'] is True,
      "| mode=%s may_confirm=%s" % (a1['mode'], a1['may_confirm']))
a2 = results['A2_network_live_remote_no_target']
print("A2 network_live remote no-target confirms (may_confirm)? ",
      a2['may_confirm'] is True,
      "| mode=%s may_confirm=%s" % (a2['mode'], a2['may_confirm']))
