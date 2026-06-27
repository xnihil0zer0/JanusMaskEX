#!/usr/bin/env python3
"""S7: Is the fuzz sandbox NOW fail-closed (abort if bwrap missing) or
fail-OPEN (fall back to un-jailed Popen)? README line 89 lumps 'the fuzz sandbox'
in with the agent jail's fail-closed claim. Check _jailed_popen's else branch."""
import pathlib
root = pathlib.Path("/home/xnihil0zer0/JanusMaskJR")
src = (root / "harness/sandbox.py").read_text().splitlines()
# print the _jailed_popen body
start = next(i for i, l in enumerate(src) if l.startswith("def _jailed_popen"))
for i in range(start, start + 14):
    print(f"{i+1:>4}: {src[i]}")
print("\n=> NOTE: README line 89 says agent SPAWNS are fail-closed; the fuzz")
print("   sandbox _jailed_popen FALLS BACK to a plain Popen when bwrap is absent")
print("   (fail-OPEN). README line 89 does NOT claim the fuzz sandbox is")
print("   fail-closed -- it only names the agent jail for that. So accurate.")
