#!/usr/bin/env python3
"""Extract every code citation from both NGv2 design docs.

Citation forms targeted:
  path/to/file.py:NNN
  path/to/file.py:NNN-MMM
  file.py::symbol
  module.symbol  (dotted python path, heuristic)
  bare file.py
  Symbol:NNN  (rare)
Each hit is dumped with the doc line it appears on.
"""
import re
import json
import sys

DOCS = {
    "DOC-A": "/home/xnihil0zer0/AI-Data/Research-JanusMask/NobleGreedv2-end2end-gap-analysis.md",
    "DOC-B": "/home/xnihil0zer0/AI-Data/Research-JanusMask/NGv2-closure-deliverables-and-acceptance-contract.md",
}

# file.py optionally with a path prefix, optionally with :NNN or :NNN-MMM, or ::symbol
# path part allows letters, digits, _, /, -, .
FILE_CITE = re.compile(
    r'(?P<path>[A-Za-z0-9_./-]+\.py)'           # file.py possibly with path
    r'(?:::(?P<dsym>[A-Za-z_][A-Za-z0-9_.]*))?'  # ::symbol
    r'(?::(?P<line>\d+)(?:-(?P<endline>\d+))?)?' # :NNN or :NNN-MMM
)

# yaml/cfg with line numbers (config/autocompiler.yaml:21)
CFG_CITE = re.compile(
    r'(?P<path>[A-Za-z0-9_./-]+\.(?:yaml|yml|json|toml|cfg|ini))'
    r'(?::(?P<line>\d+)(?:-(?P<endline>\d+))?)?'
)

def main():
    out = []
    for docid, path in DOCS.items():
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        for lineno, text in enumerate(lines, 1):
            for m in FILE_CITE.finditer(text):
                rec = {
                    "doc": docid,
                    "doc_line": lineno,
                    "kind": "py",
                    "raw": m.group(0),
                    "path": m.group("path"),
                    "symbol": m.group("dsym"),
                    "line": m.group("line"),
                    "endline": m.group("endline"),
                    "context": text.strip()[:200],
                }
                out.append(rec)
            for m in CFG_CITE.finditer(text):
                rec = {
                    "doc": docid,
                    "doc_line": lineno,
                    "kind": "cfg",
                    "raw": m.group(0),
                    "path": m.group("path"),
                    "symbol": None,
                    "line": m.group("line"),
                    "endline": m.group("endline"),
                    "context": text.strip()[:200],
                }
                out.append(rec)
    # de-dup identical (doc,doc_line,raw)
    seen = set()
    uniq = []
    for r in out:
        k = (r["doc"], r["doc_line"], r["raw"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    json.dump(uniq, sys.stdout, indent=1)
    print(file=sys.stderr)
    print(f"TOTAL CITATIONS: {len(uniq)}", file=sys.stderr)
    # how many have explicit line numbers
    withline = [r for r in uniq if r["line"]]
    print(f"  with explicit line number: {len(withline)}", file=sys.stderr)
    withsym = [r for r in uniq if r["symbol"]]
    print(f"  with ::symbol: {len(withsym)}", file=sys.stderr)

if __name__ == "__main__":
    main()
