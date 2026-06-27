#!/usr/bin/env python3
"""G1 / P2.2 verification: the doc (§2 G1 evidence cell) claims
`_make_detonation_seam` passes ONLY `{'repo_root'}` (workers/_runner.py:267),
and (§4 SSRF row) that the SSRF/nonce path is "dead code -> must wire", and
(§7 P2.2) that the detonation seam still receives only {'repo_root'} and never
the env / nonce / SSRF-callback. Check current HEAD.
"""
import subprocess
NGV2 = "/home/xnihil0zer0/NobleGreedv2"

def grep(pat, f):
    return subprocess.run(["grep", "-n", pat, f], cwd=NGV2,
                          capture_output=True, text=True).stdout.strip()

print("=== target_spec construction in _make_detonation_seam (workers/_runner.py) ===")
print(grep("target_spec = ", "ngv2/workers/_runner.py") or "(none)")
print()
print("=== where _make_detonation_seam is defined ===")
print(grep("def _make_detonation_seam", "ngv2/workers/_runner.py") or "(none)")
print()
print("=== SSRF callback + nonce threading (the per-CWE SSRF channel) ===")
print(grep("NGV2_SSRF_CALLBACK\\|NGV2_SSRF_NONCE\\|listener.url_for", "ngv2/workers/_runner.py") or "(none)")
print()
print("=== detonate_live call with loopback=True (live SSRF channel) ===")
print(grep("loopback=True", "ngv2/workers/_runner.py") or "(none)")
print()
print("DOC G1 CLAIM: \"_make_detonation_seam passes only {'repo_root'} (workers/_runner.py:267)\"")
print("RESULT: STALE -- target_spec now includes 'env' with NGV2_SSRF_CALLBACK + NGV2_SSRF_NONCE,")
print("        and the seam drives detonate_live(..., loopback=True) for the live SSRF channel.")
