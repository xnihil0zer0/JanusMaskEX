#!/usr/bin/env python3
"""ATTACK D -- AUTHENTICITY. Two forge vectors leaf-2's shared mount/netns enables:
(D1) a MOCK PoC that NEVER touches target code reads its own nonce and urlopens it
     -> forges a 'confirmed' SSRF. Is this new? (No -- pre-existing nonce injection.)
(D2) the PoC shares the work_dir with the listener; can it WRITE the fs_signature
     sentinel itself to forge the FS-snapshot verdict (a NEW cross-contamination)?"""
import os, sys, tempfile
sys.path.insert(0, "/tmp/p13_adv_wt")
from ngv2.workers._runner import _make_detonation_seam

seam=_make_detonation_seam()

# D1: a "mock" PoC that does NOT exploit any target -- it just calls back its own nonce.
print("=== D1: mock PoC forges SSRF confirm by self-calling its injected nonce ===")
mock_poc = (
    "import urllib.request\n"
    "# This PoC exploits NOTHING. It just echoes its own injected callback.\n"
    "urllib.request.urlopen('http://127.0.0.1:<<PORT>>/<<NONCE>>', timeout=4).read()\n"
)
finding = {"id":"F-forge-d1","cwe":"CWE-918"}
r1 = seam(poc=mock_poc, finding=finding)
print("ssrf_channel:", r1.get("ssrf_channel"), "success:", r1.get("success"), "ran_target:", r1.get("ran_target"))

# D2: PoC writes the fs_signature sentinel DIRECTLY to forge the FS-snapshot verdict.
print("\n=== D2: PoC forges FS-snapshot verdict by writing the sentinel itself ===")
# The sentinel the listener writes is named by expected_fs_signature parsed as 'A <name>'.
# The PoC shares work_dir; can it just create that file to fake an RCE fs-effect?
forge_poc = (
    "print('VULNERABLE')\n"
    "open('pwned_marker','w').write('forged by PoC, no real exploit')\n"
)
finding2 = {"id":"F-forge-d2","cwe":"CWE-78","expected_fs_signature":"A pwned_marker"}
r2 = seam(poc=forge_poc, finding=finding2)
print("verdict:", r2.get("verdict"), "success:", r2.get("success"), "fs_diff:", r2.get("fs_snapshot_diff"))
print("\nNOTE: D2 is the EXISTING FS-snapshot oracle behavior -- the PoC writing the file")
print("IS the observed effect. Authenticity of 'did real target code do it' is the")
print("pre-existing P1.2 concern, identical on legacy --unshare-net path.")
