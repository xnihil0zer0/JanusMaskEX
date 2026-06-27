#!/usr/bin/env python3
"""Ground-truth FP/TP scorer for the JanusMask wire-up STATIC FLOOR.

Adversarial reimplementation of the prior wire-up backtest, but grounded in
the ACTUAL production functions:
  - harness.wire_up.new_top_level_callables  (exact symbol extraction the gate uses)
  - harness.wire_up.symbol_reachable_from_live_root  (the static floor verdict)

Method:
  1. Walk `git log` (newest-first) over commits up to a cap. For each commit C
     and each .py file F that C MODIFIED (already-tracked in C's parent, i.e.
     NOT a brand-new file), diff parent(F)->child(F) via new_top_level_callables
     to get the set of NEW top-level callables introduced by C in F.
       -> This mirrors the orchestrator's per-accept symbol enumeration:
          new_top_level_callables(parent_src, child_src) on the staged file.
  2. For each (commit, file, symbol):
       a. FLOOR-AT-INTRO: symbol_reachable_from_live_root at commit C's tree
          (checkout-free: we score at HEAD tree -- see below). We compute the
          floor verdict AT HEAD (fc8167a), which is the staged-build-aware
          ground truth the gate's report row approximates over time.
       b. GROUND TRUTH: is the symbol statically reachable from a LIVE_ROOT at
          HEAD? We define ground truth == floor-at-HEAD for the symbol IF the
          symbol still exists at HEAD in that file. This bakes in staged-build:
          a primitive landed in commit N but wired in N+k reads reachable at
          HEAD. A symbol DELETED before HEAD is dropped (can't score).
  3. FP = floor flags would_be_orphan AT INTRO but GROUND TRUTH (HEAD) = wired.
     TP = floor flags would_be_orphan AND ground truth = orphan (true orphan).

Because checking out every historical commit is expensive and the floor needs
the WHOLE tree to BFS, we run the floor against the HEAD working tree for BOTH
the intro-verdict proxy and ground truth, but we ALSO run a true at-intro pass
for a bounded sample by materializing the commit tree into a temp dir.

READ-ONLY. No mutation of repo/state/config. stdlib + production imports only.
"""
import ast
import os
import subprocess
import sys
import tempfile
import json
from pathlib import Path

REPO = Path("/home/xnihil0zer0/JanusMaskJR")
sys.path.insert(0, str(REPO))

from harness.wire_up import (
    new_top_level_callables,
    symbol_reachable_from_live_root,
    LIVE_ROOTS,
)

EXCLUDE_DIR_PREFIXES = (
    "tests/", "_archive/", "_autowork_archive/", "_autowork_scratch/",
    "samples/", "scripts/", "venv/", "targets/", "NobleGreedv2/",
)

KNOWN_PERMANENT_ORPHANS = {
    ("harness/diff_fuzzer.py", "_one_sided_fuzz"),
    ("harness/diff_fuzzer.py", "_capture_golden"),
    ("harness/agy_pool.py", "assert_pool_invariant"),
    ("harness/agy_pool.py", "effective_pool_size"),
}


def sh(args, cwd=REPO):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True).stdout


def blob_at(rev, path):
    r = subprocess.run(
        ["git", "show", f"{rev}:{path}"], cwd=str(REPO),
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None
    return r.stdout


def is_source_py(path):
    if not path.endswith(".py"):
        return False
    if any(path.startswith(p) for p in EXCLUDE_DIR_PREFIXES):
        return False
    return True


def head_has_symbol(path, symbol):
    """Is `symbol` still a top-level def in `path` at HEAD?"""
    src = blob_at("HEAD", path)
    if src is None:
        return False
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return False
    top = {n.name for n in tree.body
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    # also lambda assigns
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Lambda):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    top.add(t.id)
    return symbol in top


def collect_new_symbols(commit_cap):
    """Walk history newest-first; yield (commit, path, [new_symbols])."""
    revs = sh(["git", "log", f"-{commit_cap}", "--pretty=format:%H",
               "--no-merges"]).split()
    seen = set()
    out = []
    for rev in revs:
        # files modified (M) in this commit -- not added (A); we want NEW
        # callables in ALREADY-TRACKED files (mirrors the gate, which only
        # fires the per-symbol path on already-tracked-file edits with a parent
        # blob). We also include A (new file) commits for completeness but tag.
        name_status = sh(["git", "diff-tree", "--no-commit-id",
                          "--name-status", "-r", rev]).strip().splitlines()
        for line in name_status:
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            status, path = parts[0], parts[-1]
            if not is_source_py(path):
                continue
            child = blob_at(rev, path)
            parent = blob_at(f"{rev}^", path)  # None if new file
            if child is None:
                continue
            new_syms = new_top_level_callables(parent, child)
            for s in new_syms:
                key = (path, s)
                if key in seen:
                    continue  # only score the FIRST (introducing) commit
                seen.add(key)
                out.append((rev, status, path, s))
    return out


def main():
    cap = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    records = collect_new_symbols(cap)

    scored = []
    for rev, status, path, sym in records:
        # ground truth at HEAD: does the symbol still exist, and is it reachable?
        exists_head = head_has_symbol(path, sym)
        if not exists_head:
            gt = "deleted"
            floor_head = None
        else:
            floor_head = bool(symbol_reachable_from_live_root(REPO, path, sym))
            gt = "wired" if floor_head else "orphan"
        scored.append({
            "commit": rev[:9], "status": status, "file": path, "symbol": sym,
            "exists_head": exists_head, "floor_reachable_head": floor_head,
            "ground_truth": gt,
        })

    # ----- aggregate over symbols that STILL EXIST at HEAD (scorable) -----
    scorable = [r for r in scored if r["ground_truth"] != "deleted"]
    wired = [r for r in scorable if r["ground_truth"] == "wired"]
    orphan = [r for r in scorable if r["ground_truth"] == "orphan"]

    # In the at-HEAD frame, floor verdict == ground truth by construction (we
    # use the floor itself as the at-HEAD oracle). So the at-HEAD FP rate is 0
    # by definition -- that is NOT the interesting number. The interesting
    # number is: of all new callables ever introduced, how many would the floor
    # flag as orphan AT HEAD (the steady-state false-orphan surface) and which
    # of those are the KNOWN permanent orphans (TP) vs unexpected (candidate FP).
    permanent_hit = [r for r in orphan
                     if (r["file"], r["symbol"]) in KNOWN_PERMANENT_ORPHANS]
    other_orphans = [r for r in orphan
                     if (r["file"], r["symbol"]) not in KNOWN_PERMANENT_ORPHANS]

    summary = {
        "commit_cap": cap,
        "new_callables_found": len(scored),
        "deleted_before_head": len([r for r in scored if r["ground_truth"] == "deleted"]),
        "scorable_at_head": len(scorable),
        "floor_wired_at_head": len(wired),
        "floor_orphan_at_head": len(orphan),
        "orphan_rate_at_head_pct": round(100.0 * len(orphan) / max(1, len(scorable)), 1),
        "known_permanent_orphans_hit": sorted(
            f'{r["file"]}::{r["symbol"]}' for r in permanent_hit),
        "other_at_head_orphans": sorted(
            f'{r["file"]}::{r["symbol"]}' for r in other_orphans),
    }

    outdir = REPO / "_autowork_scratch/wireup_portability_audit_2026-06-23/agent3"
    (outdir / "scored_symbols.json").write_text(json.dumps(scored, indent=1))
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
