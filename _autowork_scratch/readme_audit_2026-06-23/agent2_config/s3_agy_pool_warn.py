#!/usr/bin/env python3
"""S3: Search agy_pool.py for a runtime warn when size < parallel_cap.
README §8 caveat claims the rule is 'comment-only -- NOT runtime-enforced'.
Confirm/refute by locating any warning/log call referencing parallel_cap or size."""
import pathlib, re, subprocess
root = pathlib.Path("/home/xnihil0zer0/JanusMaskJR")
src = (root / "harness/agy_pool.py").read_text()
lines = src.splitlines()

print("=== lines mentioning warn / log / parallel_cap / size-comparison ===")
for i, ln in enumerate(lines, 1):
    if re.search(r"warn|logg|logger|parallel_cap|\bsize\s*<|<\s*parallel|print\(", ln, re.I):
        print(f"{i:>4}: {ln}")

print("\n=== diff of agy_pool.py since baseline e5c0f9fb (any warn added?) ===")
diff = subprocess.check_output(
    ["git", "log", "--oneline", "e5c0f9fb..HEAD", "--", "harness/agy_pool.py"],
    cwd=root, text=True)
print("commits since baseline touching agy_pool.py:")
print(diff or "  (none)")

print("\n=== any 'import logging' or logger in file? ===")
print("has 'logging':", "logging" in src, " | has 'warn':", bool(re.search(r"warn", src, re.I)))
