"""CLAIM B & C empirical test.

CLAIM B: the §3.2 FAITHFUL() source-meta + nonce-bound-listener checks are
SPEC not wired -- in the wired gate_executor path the detonate->novelty gates
carry no source-meta filter and no baseline differential.

CLAIM C: is there now a positive "effect originated in target code" check
(sink instrumentation / target-owned-file provenance / real-entrypoint response
assertion) that P1.2 says must be added?

We inspect:
 1. gate_executor._TRANSITION_GATES for the ('detonate','novelty') gates --
    do any consult source_meta / provenance / baseline?
 2. DetonationChamber.detonate -- does it plumb the new `nonce` arg into
    semantic_verdict (i.e. is the nonce provenance check actually live in the
    wired chamber)?
 3. semantic_verdict -- does the nonce-bound check exist and is it reachable?
"""
import inspect
import json
import textwrap
import ast as _ast

from ngv2 import gate_executor
from ngv2 import detonation

out = {}

# (B1) Inspect the detonate->novelty gate specs. What evidence keys/funcs?
specs = gate_executor._TRANSITION_GATES.get(('detonate', 'novelty'), ())
out['B1_detonate_novelty_gates'] = [
    {'name': name, 'req_fields': list(req)} for name, req, _fn in specs]

# Does ANY required field or gate name mention provenance/source_meta/baseline?
prov_tokens = ('source_meta', 'provenance', 'faithful', 'baseline',
               'nonce', 'origin', 'instrument')
all_req = [f for _n, req, _fn in specs for f in req]
all_names = [n for n, _req, _fn in specs]
all_poc_specs = gate_executor._TRANSITION_GATES.get(('poc', 'detonate'), ())
all_req += [f for _n, req, _fn in all_poc_specs for f in req]
all_names += [n for n, _req, _fn in all_poc_specs]
hits = [t for t in prov_tokens
        if any(t in f.lower() for f in all_req) or any(t in n.lower() for n in all_names)]
out['B1_provenance_tokens_in_gate_evidence_keys'] = hits
out['B1_all_gate_required_fields'] = sorted(set(all_req))

# (B2) Does DetonationChamber.detonate plumb `nonce` into semantic_verdict?
det_src = inspect.getsource(detonation.DetonationChamber.detonate)
out['B2_detonate_passes_nonce_to_semantic_verdict'] = 'nonce=' in det_src
out['B2_detonate_calls_semantic_verdict'] = 'semantic_verdict(' in det_src
# parse the semantic_verdict call args inside detonate
tree = _ast.parse(textwrap.dedent(det_src))
sv_kwargs = []
for node in _ast.walk(tree):
    if isinstance(node, _ast.Call):
        f = node.func
        fname = getattr(f, 'id', None) or getattr(f, 'attr', None)
        if fname == 'semantic_verdict':
            sv_kwargs = sorted(kw.arg for kw in node.keywords if kw.arg)
out['B2_semantic_verdict_call_kwargs_in_chamber'] = sv_kwargs

# (B3) semantic_verdict signature -- does it accept nonce, default what?
sig = inspect.signature(detonation.semantic_verdict)
out['B3_semantic_verdict_signature'] = str(sig)
out['B3_nonce_default'] = repr(sig.parameters['nonce'].default) if 'nonce' in sig.parameters else 'NO nonce param'

# (B4) Behaviorally: with default nonce='' does the nonce check engage?
# A confirmed-shaped run WITHOUT the nonce present anywhere should still confirm
# if nonce defaults to '' (check skipped) -- proving nonce provenance is OPT-IN.
v_default = detonation.semantic_verdict(
    0, 'VULNERABLE', '', 'sig123', success_marker='VULNERABLE',
    expected_fs_signature='sig123')
out['B4_verdict_default_no_nonce'] = v_default
# Now WITH an explicit nonce that is ABSENT from outputs -> must refute
v_nonce_absent = detonation.semantic_verdict(
    0, 'VULNERABLE', '', 'sig123', success_marker='VULNERABLE',
    expected_fs_signature='sig123', nonce='NONCE_XYZ')
out['B4_verdict_explicit_nonce_absent'] = v_nonce_absent
# WITH nonce present in stdout AND fs_diff -> confirm
v_nonce_present = detonation.semantic_verdict(
    0, 'VULNERABLE NONCE_XYZ', '', 'sig123 NONCE_XYZ',
    success_marker='VULNERABLE', expected_fs_signature='sig123',
    nonce='NONCE_XYZ')
out['B4_verdict_explicit_nonce_present'] = v_nonce_present

print(json.dumps(out, indent=2))

print("\n=== CLAIM B/C VERDICT ===")
print("detonate->novelty gates consult provenance/source_meta/baseline? ",
      bool(out['B1_provenance_tokens_in_gate_evidence_keys']),
      "(hits=%s)" % out['B1_provenance_tokens_in_gate_evidence_keys'])
print("DetonationChamber.detonate plumbs nonce into semantic_verdict? ",
      out['B2_detonate_passes_nonce_to_semantic_verdict'],
      "(sv kwargs in chamber=%s)" % out['B2_semantic_verdict_call_kwargs_in_chamber'])
print("nonce check OPT-IN (default '' skips it)? ",
      out['B3_nonce_default'] == "''")
