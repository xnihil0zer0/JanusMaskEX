#!/usr/bin/env python3
"""TRUE at-intro FP/TP scorer for the wire-up STATIC FLOOR.

This is the adversarial measurement: it replays what the REPORT-ONLY gate
would have emitted at each historical accept, then labels each verdict against
ground truth at HEAD.

For each (introducing-commit C, file F, new top-level callable S):
  * FLOOR-AT-INTRO  = symbol_reachable_from_live_root(tree@C, F, S)
                      -> exactly what the gate row's floor_reachable would say
                         the moment the symbol landed.
  * GROUND-TRUTH    = symbol_reachable_from_live_root(tree@HEAD, F, S) if S still
                      exists at HEAD in F (staged-build aware: a primitive wired
                      k commits later reads reachable at HEAD); if S was deleted
                      before HEAD -> drop (unscorable).

Confusion matrix on `would_be_orphan_at_intro = not FLOOR-AT-INTRO`:
  FP (false orphan)  : flagged orphan at intro BUT wired at HEAD  -> staged-build
  TP (true orphan)   : flagged orphan at intro AND orphan at HEAD
  TN                 : reachable at intro, reachable at HEAD
  "late-break" FN    : reachable at intro but orphan at HEAD (symbol later
                       un-wired) -- rare; reported separately.

The B7-RECHECK SIMULATION: a FP under the naive intro verdict is RESCUED if we
re-score it at the HEAD tree (the staged-build symbol is now reachable). So the
"FP rate WITH B7 recheck" == FP that are STILL orphan at HEAD == TP only.
We report BOTH the naive intro FP rate and the post-recheck FP rate.

Materializes each commit tree with `git archive | tar` into a temp dir (cheap,
read-only). stdlib + production imports only. READ-ONLY on repo/state/config.
"""
import ast
import subprocess
import sys
import tempfile
import json
import shutil
from pathlib import Path

REPO = Path("/home/xnihil0zer0/JanusMaskJR")
sys.path.insert(0, str(REPO))

from harness.wire_up import new_top_level_callables, symbol_reachable_from_live_root

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
    r = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=str(REPO),
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def is_source_py(path):
    return path.endswith(".py") and not any(path.startswith(p) for p in EXCLUDE_DIR_PREFIXES)


def materialize(rev, dest):
    """git archive rev -> dest dir (read-only snapshot of the full tree)."""
    arch = subprocess.run(["git", "archive", "--format=tar", rev], cwd=str(REPO),
                          capture_output=True)
    if arch.returncode != 0:
        return False
    tar = subprocess.run(["tar", "-x", "-C", str(dest)], input=arch.stdout)
    return tar.returncode == 0


def head_exists(path, symbol):
    src = blob_at("HEAD", path)
    if src is None:
        return False
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return False
    top = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Lambda):
            top.update(t.id for t in n.targets if isinstance(t, ast.Name))
    return symbol in top


def collect(commit_cap):
    revs = sh(["git", "log", f"-{commit_cap}", "--pretty=format:%H", "--no-merges"]).split()
    seen = set()
    out = []
    for rev in revs:
        ns = sh(["git", "diff-tree", "--no-commit-id", "--name-status", "-r", rev]).strip().splitlines()
        for line in ns:
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            status, path = parts[0], parts[-1]
            if not is_source_py(path):
                continue
            child = blob_at(rev, path)
            parent = blob_at(f"{rev}^", path)
            if child is None:
                continue
            for s in new_top_level_callables(parent, child):
                if (path, s) in seen:
                    continue
                seen.add((path, s))
                out.append((rev, status, path, s))
    return out


def main():
    cap = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    records = collect(cap)

    # Cache HEAD ground-truth per symbol (one floor call each at the live tree).
    scored = []
    intro_cache = {}  # rev -> materialized dir
    tmproot = Path(tempfile.mkdtemp(prefix="wireup_intro_"))
    try:
        for rev, status, path, sym in records:
            exists = head_exists(path, sym)
            gt_head = bool(symbol_reachable_from_live_root(REPO, path, sym)) if exists else None

            # at-intro floor: materialize rev tree once, reuse for all its symbols
            if rev not in intro_cache:
                d = tmproot / rev[:12]
                d.mkdir(parents=True, exist_ok=True)
                ok = materialize(rev, d)
                intro_cache[rev] = d if ok else None
            d = intro_cache[rev]
            floor_intro = None
            if d is not None:
                try:
                    floor_intro = bool(symbol_reachable_from_live_root(d, path, sym))
                except Exception:
                    floor_intro = None

            scored.append({
                "commit": rev[:9], "status": status, "file": path, "symbol": sym,
                "floor_intro": floor_intro, "exists_head": exists,
                "gt_head_reachable": gt_head,
            })
    finally:
        shutil.rmtree(tmproot, ignore_errors=True)

    # confusion matrix on symbols scorable at BOTH intro and HEAD
    M = [r for r in scored if r["floor_intro"] is not None and r["gt_head_reachable"] is not None]
    fp, tp, tn, late_fn = [], [], [], []
    for r in M:
        orphan_at_intro = not r["floor_intro"]
        orphan_at_head = not r["gt_head_reachable"]
        if orphan_at_intro and not orphan_at_head:
            fp.append(r)            # staged build / late wiring -> false orphan
        elif orphan_at_intro and orphan_at_head:
            tp.append(r)            # true orphan, correctly flagged
        elif not orphan_at_intro and not orphan_at_head:
            tn.append(r)
        else:
            late_fn.append(r)       # reachable@intro, orphan@head (later un-wired)

    flagged_at_intro = len(fp) + len(tp)
    perm_in_tp = [r for r in tp if (r["file"], r["symbol"]) in KNOWN_PERMANENT_ORPHANS]
    perm_missed = sorted(KNOWN_PERMANENT_ORPHANS - {(r["file"], r["symbol"]) for r in tp})

    summary = {
        "commit_cap": cap,
        "new_callables_found": len(scored),
        "deleted_before_head": len([r for r in scored if not r["exists_head"]]),
        "materialize_failed": len([r for r in scored if r["floor_intro"] is None and r["exists_head"]]),
        "scorable_both_frames": len(M),
        "confusion": {"TP_true_orphan": len(tp), "FP_staged_false_orphan": len(fp),
                      "TN_wired": len(tn), "FN_late_unwired": len(late_fn)},
        "flagged_orphan_at_intro": flagged_at_intro,
        "naive_intro_FP_rate_pct": round(100.0 * len(fp) / max(1, flagged_at_intro), 1),
        "post_B7recheck_FP_rate_pct": round(100.0 * 0 / max(1, len(tp)), 1) if tp else 0.0,
        "intro_orphan_flag_rate_pct": round(100.0 * flagged_at_intro / max(1, len(M)), 1),
        "permanent_orphans_flagged_TP": sorted(f'{r["file"]}::{r["symbol"]}' for r in perm_in_tp),
        "permanent_orphans_NOT_flagged": [f"{f}::{s}" for f, s in perm_missed],
        "staged_build_FP_examples": sorted(
            f'{r["commit"]} {r["file"]}::{r["symbol"]}' for r in fp)[:25],
    }
    outdir = REPO / "_autowork_scratch/wireup_portability_audit_2026-06-23/agent3"
    (outdir / "scored_at_intro.json").write_text(json.dumps(scored, indent=1))
    (outdir / "summary_at_intro.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
