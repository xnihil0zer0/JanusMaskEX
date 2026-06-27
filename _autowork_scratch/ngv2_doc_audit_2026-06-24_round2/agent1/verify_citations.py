#!/usr/bin/env python3
"""Verify each extracted citation against current HEAD of the correct repo.

For each citation:
  - resolve to an absolute filesystem path (try NGv2 ngv2/, NGv2 root, JM, JM harness/)
  - file exists?
  - if it has a :line, read that line (1-based) and capture content
  - if it has a ::symbol or the context implies a symbol, grep for def/class current line(s)
Classify: FILE_OK / FILE_DEAD, and emit captured line content for manual line-drift judgment.
"""
import json
import os
import re
import subprocess

NGV2 = "/home/xnihil0zer0/NobleGreedv2"
JM = "/home/xnihil0zer0/JanusMaskJR"

# Known NGv2-only basenames (hunt engine modules) so a bare/relative cite resolves right.
NGV2_BASENAMES = {
    "poc_runner_live.py", "detonation.py", "gate_executor.py", "transition_planner.py",
    "conductor_seams.py", "poc_writer.py", "pattern_scanner.py", "auth_bootstrap.py",
    "loopback_listener.py", "run_hunt.py", "hunt_lead_client.py", "poc_authenticity_gate.py",
    "fsm_detect.py", "_loopback_netns.py",
}
JM_BASENAMES = {
    "wire_up.py", "orchestrator.py", "sandbox.py", "diff_fuzzer.py", "state_reconciler.py",
    "target_bootstrap.py", "agent_jail.py", "git_integration.py", "selfheal.py",
    "scorer_at_intro.py",
}


def candidates(path):
    """Yield candidate absolute paths in priority order."""
    p = path
    base = os.path.basename(p)
    cands = []
    # If path already has a recognizable prefix
    if p.startswith("ngv2/"):
        cands.append(os.path.join(NGV2, p))
    if p.startswith("harness/") or p.startswith("config/") or p.startswith("tests/harness") or p.startswith("tests/ngv2"):
        cands.append(os.path.join(JM, p))
    if p.startswith("workers/"):
        cands.append(os.path.join(NGV2, "ngv2", p))
        cands.append(os.path.join(JM, "harness", p))
    if p.startswith("narrow_fuzz/"):
        cands.append(os.path.join(JM, "harness", p))
    # basename-based routing
    if base in NGV2_BASENAMES:
        cands.append(os.path.join(NGV2, "ngv2", base))
        cands.append(os.path.join(NGV2, p))
    if base in JM_BASENAMES:
        cands.append(os.path.join(JM, "harness", base))
    # generic fallbacks
    cands.append(os.path.join(NGV2, "ngv2", p))
    cands.append(os.path.join(NGV2, p))
    cands.append(os.path.join(JM, "harness", p))
    cands.append(os.path.join(JM, p))
    cands.append(os.path.join(NGV2, "ngv2", base))
    cands.append(os.path.join(JM, "harness", base))
    # de-dup preserve order
    seen = set()
    out = []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def resolve(path):
    for c in candidates(path):
        if os.path.isfile(c):
            return c
    return None


def read_lines(absfile, start, end):
    try:
        with open(absfile, encoding="utf-8", errors="replace") as f:
            alll = f.readlines()
    except Exception as e:
        return f"<read error {e}>"
    s = int(start)
    e = int(end) if end else s
    out = []
    for i in range(s, e + 1):
        if 1 <= i <= len(alll):
            out.append(f"{i}: {alll[i-1].rstrip()}")
        else:
            out.append(f"{i}: <OUT OF RANGE (file has {len(alll)} lines)>")
    return "\n".join(out)


def find_symbol(absfile, sym):
    """grep for def/class SYM, return list of (lineno, text)."""
    try:
        r = subprocess.run(
            ["grep", "-nE", rf"^\s*(def|class|async def)\s+{re.escape(sym)}\b", absfile],
            capture_output=True, text=True)
        hits = [l for l in r.stdout.splitlines() if l]
        return hits
    except Exception as e:
        return [f"<grep error {e}>"]


def main():
    with open("citations.json") as f:
        cites = json.load(f)
    results = []
    for c in cites:
        absfile = resolve(c["path"])
        rec = dict(c)
        rec["resolved"] = absfile
        rec["file_ok"] = bool(absfile)
        rec["line_content"] = None
        rec["symbol_hits"] = None
        if absfile:
            if c["line"]:
                rec["line_content"] = read_lines(absfile, c["line"], c["endline"])
            if c["symbol"]:
                # symbol may be dotted; check last component
                sym = c["symbol"].split(".")[-1]
                rec["symbol_hits"] = find_symbol(absfile, sym)
        results.append(rec)
    with open("verified.json", "w") as f:
        json.dump(results, f, indent=1)

    dead = [r for r in results if not r["file_ok"]]
    print(f"=== RESOLUTION SUMMARY ===")
    print(f"total: {len(results)}")
    print(f"file resolved: {sum(1 for r in results if r['file_ok'])}")
    print(f"file DEAD (unresolved): {len(dead)}")
    print()
    print("=== DEAD FILE CITATIONS ===")
    for r in dead:
        print(f"  [{r['doc']}:{r['doc_line']}] {r['raw']}  ctx: {r['context'][:90]}")
    print()
    print("=== CITATIONS WITH LINE NUMBERS (content dump) ===")
    for r in results:
        if r["line"] and r["file_ok"]:
            print(f"\n--- [{r['doc']}:{r['doc_line']}] {r['raw']}  -> {r['resolved']}")
            print(f"    DOC CTX: {r['context'][:160]}")
            print(f"    SRC:\n      " + (r['line_content'] or '').replace("\n", "\n      "))
    print()
    print("=== ::SYMBOL CITATIONS ===")
    for r in results:
        if r["symbol"] and r["file_ok"]:
            print(f"  [{r['doc']}:{r['doc_line']}] {r['raw']} -> {r['resolved']}")
            print(f"     symbol_hits: {r['symbol_hits']}")

if __name__ == "__main__":
    main()
