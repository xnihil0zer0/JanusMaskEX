#!/usr/bin/env python3
"""S2: Show which autowork flags existed at baseline e5c0f9fb vs HEAD, and
whether the README §8 config block (inner content) already lists each."""
import subprocess, yaml, re, pathlib
root = pathlib.Path("/home/xnihil0zer0/JanusMaskJR")

base = subprocess.check_output(["git", "show", "e5c0f9fb:harness/config.yaml"], cwd=root, text=True)
head = (root / "harness/config.yaml").read_text()
base_a = yaml.safe_load(base)["autowork"]
head_a = yaml.safe_load(head)["autowork"]
base_w = yaml.safe_load(base)["workers"]
head_w = yaml.safe_load(head)["workers"]

readme = (root / "README.md").read_text()

flags = ["onesided_metamorphic", "wire_up_runtime_gate", "wire_up_runtime_gate_enforce", "claude_parallel_cap"]
print("flag                              base_e5c0f9fb   HEAD       in_README_text?")
for k in flags:
    bv = base_a.get(k, "<ABSENT>")
    hv = head_a.get(k, "<ABSENT>")
    in_readme = re.search(rf"\b{re.escape(k)}\b", readme) is not None
    print(f"{k:<33} {str(bv):<14} {str(hv):<10} {in_readme}")

print("\nworkers.claude_backend  base =", repr(base_w.get("claude_backend")), " HEAD =", repr(head_w.get("claude_backend")))
# Does README literally contain 'claude_backend: tmux' (the stale config-block line)?
print("README contains 'claude_backend: tmux'    :", "claude_backend: tmux" in readme)
print("README contains 'claude_backend: headless':", "claude_backend: headless" in readme)
print("README contains 'currently **`tmux`**'    :", "currently **`tmux`**" in readme)
print("README contains 'hands-off default'       :", "hands-off default" in readme)
