#!/usr/bin/env python3
"""S6: Confirm sandbox.py now routes fuzz subprocesses through a bwrap jail with
bind_credentials=False (the g7-fuzz-jail-credfree change), and that this was
added since README baseline e5c0f9fb."""
import subprocess, pathlib, re
root = pathlib.Path("/home/xnihil0zer0/JanusMaskJR")
src = (root / "harness/sandbox.py").read_text()

print("=== _jailed_popen definition + bind_credentials usage ===")
for i, ln in enumerate(src.splitlines(), 1):
    if re.search(r"_jailed_popen|bind_credentials|build_jail_argv|bwrap_available", ln):
        print(f"{i:>4}: {ln.strip()}")

print("\n=== call sites that switched subprocess.Popen -> _jailed_popen ===")
print("count of _jailed_popen( call sites:", src.count("_jailed_popen("))

base = subprocess.check_output(["git", "show", "e5c0f9fb:harness/sandbox.py"], cwd=root, text=True)
print("\nbaseline e5c0f9fb sandbox.py has '_jailed_popen' :", "_jailed_popen" in base)
print("baseline e5c0f9fb sandbox.py has 'bind_credentials':", "bind_credentials" in base)
print("HEAD     sandbox.py has '_jailed_popen'           :", "_jailed_popen" in src)
print("HEAD     sandbox.py has 'bind_credentials=False'  :", "bind_credentials=False" in src)

log = subprocess.check_output(
    ["git", "log", "--oneline", "-S", "_jailed_popen", "--", "harness/sandbox.py"],
    cwd=root, text=True)
print("\ncommit introducing _jailed_popen:\n", log or "  (not found)")
