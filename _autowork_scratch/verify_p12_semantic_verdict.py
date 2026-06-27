"""Adversarial verification of the hardened semantic_verdict (P1.2 / X3 / G10).
Runs against the LIVE NGv2 ngv2/detonation.py via PYTHONPATH.
"""
import sys
sys.path.insert(0, '/home/xnihil0zer0/NobleGreedv2')
from ngv2.detonation import semantic_verdict, DetonationChamber
from ngv2.contracts import PoC

def show(label, val, expect_not=None, expect=None):
    status = ""
    if expect_not is not None:
        status = "PASS" if val != expect_not else "FAIL"
    if expect is not None:
        status = "PASS" if val == expect else "FAIL"
    print(f"[{status}] {label} -> {val!r}")
    return val

print("=== 3. VACUITY CLOSED (empty / whitespace expected_fs_signature) ===")
# Pre-fix these returned 'confirmed' because '' in anything == True.
show("empty sig   : semantic_verdict(0,'VULNERABLE','','no fs changes',marker='VULNERABLE',sig='')",
     semantic_verdict(0, 'VULNERABLE', '', 'no fs changes',
                      success_marker='VULNERABLE', expected_fs_signature=''),
     expect_not='confirmed')
show("ws sig '   ' : semantic_verdict(0,'VULNERABLE','','no fs changes',marker='VULNERABLE',sig='   ')",
     semantic_verdict(0, 'VULNERABLE', '', 'no fs changes',
                      success_marker='VULNERABLE', expected_fs_signature='   '),
     expect_not='confirmed')
show("ws sig '\\n\\t': tabs/newlines only",
     semantic_verdict(0, 'VULNERABLE', '', 'no fs changes',
                      success_marker='VULNERABLE', expected_fs_signature='\n\t '),
     expect_not='confirmed')

print("\n=== 4. NONCE-BINDING NEGATIVES (non-empty nonce, missing in a channel) ===")
N = 'nonce_p12_alpha'
# 4a: nonce present in fs diff but ABSENT from stdout/stderr success evidence.
show("4a nonce missing in stdout/stderr (present in fs diff)",
     semantic_verdict(0, 'VULNERABLE', '', f'created /tmp/{N}_marker',
                      success_marker='VULNERABLE', expected_fs_signature=f'/tmp/{N}_marker', nonce=N),
     expect_not='confirmed')
# 4b: nonce present in stdout but ABSENT from fs diff.
show("4b nonce missing in fs diff (present in stdout)",
     semantic_verdict(0, f'VULNERABLE {N}', '', 'created /tmp/effect_marker',
                      success_marker='VULNERABLE', expected_fs_signature='/tmp/effect_marker', nonce=N),
     expect_not='confirmed')
# 4c: nonce absent from BOTH channels (everything else valid).
show("4c nonce absent from both channels",
     semantic_verdict(0, 'VULNERABLE', '', 'created /tmp/effect_marker',
                      success_marker='VULNERABLE', expected_fs_signature='/tmp/effect_marker', nonce=N),
     expect_not='confirmed')

print("\n=== 5. GENUINE POSITIVE (nonce in BOTH channels) ===")
show("5 nonce-bound effect in stdout AND fs diff",
     semantic_verdict(0, f'VULNERABLE token={N}', '', f'+++ wrote /tmp/{N}.pwn',
                      success_marker='VULNERABLE', expected_fs_signature=f'/tmp/{N}.pwn', nonce=N),
     expect='confirmed')
show("5b nonce in stderr (not stdout) AND fs diff",
     semantic_verdict(0, 'no marker here', f'VULNERABLE {N}', f'+++ /tmp/{N}.pwn',
                      success_marker='VULNERABLE', expected_fs_signature=f'/tmp/{N}.pwn', nonce=N),
     expect='confirmed')

print("\n=== 6. LIVE-CALLER NO-OVER-BLOCKING (NO nonce, real marker, real non-empty sig) ===")
# Reproduce the exact live call shape: positional (exit_code, stdout, stderr, fs_diff),
# keyword success_marker + expected_fs_signature, NO nonce.
# (a) poc_runner_live.py:296 shape
show("6a live poc_runner_live shape: genuine confirm (exit0, marker, real sig in fs diff)",
     semantic_verdict(0, 'BOOM VULNERABLE BOOM', '', '--- a/secret\n+++ created /tmp/proof_file',
                      success_marker='VULNERABLE', expected_fs_signature='/tmp/proof_file'),
     expect='confirmed')
# (b) workers/detonate.py:251 shape (all str-cast, fs_sig non-empty)
show("6b live detonate worker shape: genuine confirm via DetonationChamber.detonate path",
     semantic_verdict(0, 'pwned VULNERABLE', 'warn', 'M ngv2/x.py\n+++ /tmp/effect_signature_xyz',
                      success_marker='VULNERABLE', expected_fs_signature='/tmp/effect_signature_xyz'),
     expect='confirmed')
# (c) detonation.py:86 -> DetonationChamber.detonate (in-class). Exercise the real method.
def genuine_runner(poc, target_spec):
    return (0, 'attack ok VULNERABLE', '', 12, 'M file\n+++ /tmp/chamber_proof')
chamber = DetonationChamber(success_marker='VULNERABLE')
poc = PoC(finding_id='F-live-1', payload={'k': 'v'}) if 'payload' in PoC.__init__.__code__.co_varnames else None
if poc is None:
    # construct PoC minimally by inspecting signature
    import inspect
    sig = inspect.signature(PoC)
    kwargs = {}
    for name, p in sig.parameters.items():
        if p.default is inspect._empty:
            kwargs[name] = 'F-live-1' if 'id' in name else {}
    poc = PoC(**kwargs)
report = chamber.detonate(poc, {'host': 'x'}, genuine_runner, expected_fs_signature='/tmp/chamber_proof')
show("6c DetonationChamber.detonate genuine (NO nonce) verdict",
     report.verdict, expect='confirmed')

# Over-block sanity: a genuine NO-nonce confirm must NOT be refuted just because nonce defaulted ''.
show("6d no-nonce + empty-default does NOT over-block a real signature",
     semantic_verdict(0, 'VULNERABLE', '', '+++ /tmp/realsig', success_marker='VULNERABLE',
                      expected_fs_signature='/tmp/realsig'),
     expect='confirmed')

print("\n=== Extra: legacy NEGATIVES still refuted (no marker / no sig-in-diff) ===")
show("no marker present", semantic_verdict(0, 'nothing', '', '+++ /tmp/realsig',
     success_marker='VULNERABLE', expected_fs_signature='/tmp/realsig'), expect='refuted')
show("sig not in fs diff", semantic_verdict(0, 'VULNERABLE', '', 'no relevant change',
     success_marker='VULNERABLE', expected_fs_signature='/tmp/realsig'), expect='refuted')
show("nonzero exit dominates", semantic_verdict(1, 'VULNERABLE', '', '+++ /tmp/realsig',
     success_marker='VULNERABLE', expected_fs_signature='/tmp/realsig'), expect='error')

print("\nDONE")
