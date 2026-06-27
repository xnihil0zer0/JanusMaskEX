#!/usr/bin/env python3
"""Memory-audit evidence engine.

For every memory ``*.md`` file, extract VERIFIABLE claims and test them against
live ground truth (the JanusMaskJR repo tree, the NobleGreedv2 external target,
``harness/config.yaml``, README.md, and git history). Emits a JSON evidence
record per file so that any proposed change to MEMORY.md / a topic file can cite
objective test results rather than opinion.

Usage:
  python _autowork_scratch/memory_audit/audit_memory.py            # full sweep -> evidence.json + summary
  python _autowork_scratch/memory_audit/audit_memory.py FILE...    # targeted re-check of named files (prints JSON)

Tested claim classes (each carries pass/fail evidence):
  * commit SHAs           -> exists in repo?  reachable from HEAD?
  * file / dir paths      -> exists on disk (JanusMaskJR or NobleGreedv2)?
  * config flag claims    -> claimed bool matches harness/config.yaml live value?
  * symbol names (def/class) referenced as code -> present in tree (grep)?
  * index linkage         -> is this file's slug present in MEMORY.md?  do its [[links]] resolve?
"""
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/xnihil0zer0/AI-Data/JanusMaskEX")
NGV2 = Path("/home/xnihil0zer0/NobleGreedv2")
MEMDIR = Path("/home/xnihil0zer0/.claude/projects/-home-xnihil0zer0-AI-Data-JanusMaskEX/memory")
CONFIG = REPO / "harness" / "config.yaml"
README = REPO / "README.md"

# ---------------------------------------------------------------- git helpers
def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)

def _exists_in(repo, sha):
    return _git(repo, "cat-file", "-e", sha + "^{commit}").returncode == 0

def _reachable_in(repo, sha):
    return _git(repo, "merge-base", "--is-ancestor", sha, "HEAD").returncode == 0

def sha_locate(sha):
    """Return where a SHA lives: 'jm', 'ngv2', or '' (nowhere).

    Also reports reachability from each repo's HEAD."""
    if _exists_in(REPO, sha):
        return {"exists": True, "repo": "jm", "reachable": _reachable_in(REPO, sha)}
    if NGV2.exists() and _exists_in(NGV2, sha):
        return {"exists": True, "repo": "ngv2", "reachable": _reachable_in(NGV2, sha)}
    return {"exists": False, "repo": "", "reachable": False}

# ---------------------------------------------------------------- config flags
def load_config_flags():
    """Flatten harness/config.yaml to dotted-key -> value for bool lookups."""
    flat = {}
    try:
        import yaml
        with open(CONFIG) as fh:
            data = yaml.safe_load(fh)
        def walk(prefix, node):
            if isinstance(node, dict):
                for k, v in node.items():
                    walk(f"{prefix}.{k}" if prefix else str(k), v)
            else:
                flat[prefix] = node
        walk("", data)
    except Exception as exc:  # noqa
        flat["__error__"] = repr(exc)
    return flat

CONFIG_FLAGS = load_config_flags()

def config_lookup(name):
    """Return (found, value, ambiguous) for a bare or dotted flag name.

    Prefers an exact dotted-key match (so 'hierarchical_planning.enabled'
    resolves cleanly); only falls back to trailing-segment matching for a bare
    name, and reports ambiguous=True when >1 key shares that segment (e.g. the
    bare 'enabled', which many subtrees define) so callers do NOT treat an
    ambiguous lookup as a real mismatch."""
    # 1. exact dotted (or exact bare) key
    if name in CONFIG_FLAGS:
        return True, CONFIG_FLAGS[name], False
    # 2. dotted name whose suffix uniquely identifies a flat key
    if "." in name:
        suff_hits = [(k, v) for k, v in CONFIG_FLAGS.items()
                     if k == name or k.endswith("." + name)]
        if len(suff_hits) == 1:
            return True, suff_hits[0][1], False
    # 3. bare trailing-segment match
    hits = [(k, v) for k, v in CONFIG_FLAGS.items() if k.split(".")[-1] == name]
    if len(hits) == 1:
        return True, hits[0][1], False
    if len(hits) > 1:
        return True, {k: v for k, v in hits}, True   # ambiguous
    return False, None, False

# ---------------------------------------------------------------- extractors
# a git SHA: 7-40 hex, NOT inside a UUID (no adjacent hyphen+hex), and must
# contain BOTH a hex letter and a digit (kills timestamps and hex-words)
SHA_RE = re.compile(r"(?<![0-9a-fA-F-])([0-9a-f]{7,40})(?![0-9a-fA-F-])")
# paths like harness/foo.py, tools/x/y.py, config/a.yaml, scripts/z.py,
# state/control/..., ngv2/..., NobleGreedv2/...
PATH_RE = re.compile(
    r"`?((?:harness|tools|scripts|services|config|state|tests|autocompiler|docs|ngv2|NobleGreedv2|NobleGreedv2/ngv2)/[A-Za-z0-9_./\-]+)`?"
)
# flag: true / flag = false  /  `flag: true`
FLAG_RE = re.compile(r"`?([A-Za-z_][A-Za-z0-9_.]*)\s*[:=]\s*(true|false|True|False)`?")
# code symbol references: _foo, do_thing, ClassName referenced with () or as `def x`
SYMBOL_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]{3,})`")
LINK_RE = re.compile(r"\[\[([a-z0-9\-]+)\]\]")

KNOWN_FLAG_NAMES = {
    "enabled", "archive_spent_briefs", "wire_up_gate", "state_reconcile",
    "auto_approve_sensitive_harness", "auto_approve_ro_gate",
    "selfheal_auto_promote", "bwrap", "population", "determinism",
    "decode", "js", "symbol_ledger", "failure_propagation",
    "accept_single_agent_leaf_plans", "enable_single_agent_promotion",
    "conservative_missing_files",
}

# things that look like SHAs but are common false-positives (hex words)
SHA_DENY = {"deadbeef", "decade", "facade", "effaced", "accede", "defaced"}

def looks_like_sha(tok):
    if tok in SHA_DENY:
        return False
    # real git short SHAs ~always contain BOTH a hex letter and a digit;
    # this kills pure-digit timestamps (20260616) and pure-letter hex-words
    return (len(tok) >= 7
            and re.search(r"[a-f]", tok)
            and re.search(r"[0-9]", tok))

def strip_frontmatter(text):
    """Remove the leading --- ... --- block so session UUIDs etc. are not
    mis-read as SHAs / claims."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:]
    return text

def path_exists(p):
    cand = []
    if p.startswith("NobleGreedv2/"):
        cand.append(NGV2 / p[len("NobleGreedv2/"):])
    elif p.startswith("ngv2/"):
        cand.append(NGV2 / p)
        cand.append(REPO / p)
    else:
        cand.append(REPO / p)
    return any(c.exists() for c in cand)

# cache full-tree grep results per symbol
_SYM_CACHE = {}
def symbol_present(sym):
    if sym in _SYM_CACHE:
        return _SYM_CACHE[sym]
    r = subprocess.run(
        ["grep", "-rIlnE", rf"(def|class)\s+{re.escape(sym)}\b",
         str(REPO / "harness"), str(REPO / "tools"), str(REPO / "scripts")],
        capture_output=True, text=True)
    present = r.returncode == 0 and bool(r.stdout.strip())
    _SYM_CACHE[sym] = present
    return present

# ---------------------------------------------------------------- per-file
def parse_frontmatter(text):
    fm = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            block = text[3:end]
            for line in block.splitlines():
                m = re.match(r"\s*([A-Za-z_]+):\s*(.*)", line)
                if m:
                    fm[m.group(1)] = m.group(2).strip()
    return fm

def audit_file(path, index_text, all_slugs):
    raw = path.read_text(errors="replace")
    fm = parse_frontmatter(raw)
    slug = fm.get("name") or path.stem
    text = strip_frontmatter(raw)  # exclude session UUIDs / frontmatter from claims

    # SHAs (checked against BOTH JanusMaskJR and NobleGreedv2 histories)
    shas = {}
    for tok in SHA_RE.findall(text):
        if looks_like_sha(tok):
            shas[tok] = sha_locate(tok)
    # cap noise
    shas = dict(list(shas.items())[:50])

    # paths
    paths = {}
    for p in set(PATH_RE.findall(text)):
        paths[p] = path_exists(p)

    # flags
    flags = {}
    for name, claimed in FLAG_RE.findall(text):
        bare = name.split(".")[-1]
        if bare in KNOWN_FLAG_NAMES:
            found, actual, ambiguous = config_lookup(name)
            claimed_bool = claimed.lower() == "true"
            flags[name] = {
                "claimed": claimed_bool,
                "config_found": found,
                "config_value": actual,
                "ambiguous": ambiguous,
                # a real mismatch requires an UNAMBIGUOUS resolved bool that differs
                "match": (found and not ambiguous and actual == claimed_bool),
                "verdict": ("ambiguous_skip" if ambiguous
                            else "mismatch" if (found and actual != claimed_bool)
                            else "match" if found else "not_in_config"),
            }

    # symbols (sampled — only those that look like identifiers, dedupe, cap)
    syms = {}
    for sym in set(SYMBOL_RE.findall(text)):
        if sym in KNOWN_FLAG_NAMES:
            continue
        if re.match(r"^[a-z_][a-z0-9_]+$", sym) and ("_" in sym or sym.startswith("_")):
            syms[sym] = symbol_present(sym)
    syms = dict(list(syms.items())[:30])

    # index linkage
    in_index = slug in index_text
    links = LINK_RE.findall(text)
    dangling_links = [l for l in links if l not in all_slugs]

    # tallies
    sha_dead = [s for s, r in shas.items() if not r["exists"]]
    sha_unreachable = [s for s, r in shas.items()
                       if r["exists"] and r["repo"] == "jm" and not r["reachable"]]
    sha_ngv2 = [s for s, r in shas.items() if r["repo"] == "ngv2"]
    path_missing = [p for p, ok in paths.items() if not ok]
    flag_mismatch = [f for f, r in flags.items() if r["verdict"] == "mismatch"]
    flag_ambiguous = [f for f, r in flags.items() if r["verdict"] == "ambiguous_skip"]
    flag_not_in_config = [f for f, r in flags.items() if r["verdict"] == "not_in_config"]
    sym_missing = [s for s, ok in syms.items() if not ok]

    return {
        "file": path.name,
        "slug": slug,
        "type": fm.get("type") or "(none)",
        "bytes": path.stat().st_size,
        "mtime": path.stat().st_mtime,
        "in_index": in_index,
        "dangling_links": dangling_links,
        "counts": {
            "shas": len(shas), "sha_dead": len(sha_dead),
            "sha_unreachable": len(sha_unreachable), "sha_ngv2": len(sha_ngv2),
            "paths": len(paths), "path_missing": len(path_missing),
            "flags": len(flags), "flag_mismatch": len(flag_mismatch),
            "syms": len(syms), "sym_missing": len(sym_missing),
        },
        "sha_dead": sha_dead,
        "sha_unreachable": sha_unreachable,
        "sha_ngv2": sha_ngv2,
        "path_missing": path_missing,
        "flag_mismatch": {f: flags[f] for f in flag_mismatch},
        "sym_missing": sym_missing,
    }

def main():
    index_text = (MEMDIR / "MEMORY.md").read_text(errors="replace")
    files = sorted(p for p in MEMDIR.glob("*.md") if p.name != "MEMORY.md")
    all_slugs = set()
    for p in files:
        fm = parse_frontmatter(p.read_text(errors="replace"))
        all_slugs.add(fm.get("name") or p.stem)

    targets = files
    if len(sys.argv) > 1:
        want = set(sys.argv[1:])
        targets = [p for p in files if p.name in want or p.stem in want]

    records = [audit_file(p, index_text, all_slugs) for p in targets]

    if len(sys.argv) > 1:
        print(json.dumps(records, indent=2))
        return

    out = MEMDIR / ".." / ".."  # noqa - just compute then write to scratch
    evidence_path = REPO / "_autowork_scratch" / "memory_audit" / "evidence.json"
    evidence_path.write_text(json.dumps(records, indent=2))

    # summary
    not_in_index = [r["file"] for r in records if not r["in_index"]]
    with_dead_sha = [(r["file"], r["sha_dead"]) for r in records if r["sha_dead"]]
    with_flag_mismatch = [(r["file"], list(r["flag_mismatch"])) for r in records if r["flag_mismatch"]]
    with_missing_paths = [(r["file"], r["counts"]["path_missing"], r["counts"]["paths"]) for r in records if r["path_missing"]]
    with_dangling = [(r["file"], r["dangling_links"]) for r in records if r["dangling_links"]]

    print(f"TOTAL memory topic files audited: {len(records)}")
    print(f"MEMORY.md index slugs referenced : {sum(r['in_index'] for r in records)} present / {len(records)} files")
    print(f"\n=== {len(not_in_index)} files NOT referenced in MEMORY.md (orphan topic files) ===")
    for f in not_in_index:
        print("  ", f)
    print(f"\n=== {len(with_dead_sha)} files citing SHAs absent from the repo ===")
    for f, shas in with_dead_sha:
        print("  ", f, "->", shas)
    print(f"\n=== {len(with_flag_mismatch)} files with config-flag claims that MISMATCH live config.yaml ===")
    for f, fl in with_flag_mismatch:
        print("  ", f, "->", fl)
    print(f"\n=== {len(with_missing_paths)} files citing paths that do NOT exist (missing/total) ===")
    for f, miss, tot in sorted(with_missing_paths, key=lambda x: -x[1]):
        print(f"   {f} -> {miss}/{tot} missing")
    print(f"\n=== {len(with_dangling)} files with dangling [[links]] (no such slug) ===")
    for f, dl in with_dangling:
        print("  ", f, "->", dl)
    print(f"\nEvidence written: {evidence_path}")

if __name__ == "__main__":
    main()
