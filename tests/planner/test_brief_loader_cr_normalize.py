"""RED oracle: brief_loader content SHA-256 must be invariant across ALL line-ending
forms — \n, \r\n, AND a bare \r.

Contract for the brief-loader-cr-normalize leaf (HANDOFF §1): load_brief currently
collapses only \r\n -> \n (brief_loader.py:190), so a bare carriage return hashes
differently from its \n equivalent. After the fix, all three variants of the same
logical content produce an identical .sha256, and a \r-separated brief parses.
"""
import tempfile
from pathlib import Path

from harness.planner import load_brief

BASE = """---
title: Title
---
# Scope
line one
line two
# Non-Goals
x
# Inputs
x
# Deliverables
x
"""


def _load_variant(tmp: str, name: str, content: str):
    p = Path(tmp) / name
    p.write_bytes(content.encode("utf-8"))
    return load_brief(p)


def test_embedded_bare_cr_hashes_like_lf():
    # A bare \r inside a section body must hash identically to its \n form.
    with_cr = BASE.replace("line one\nline two", "line one\rline two")
    with tempfile.TemporaryDirectory() as td:
        lf = _load_variant(td, "lf.md", BASE)
        cr = _load_variant(td, "cr.md", with_cr)
        assert lf.sha256 == cr.sha256


def test_all_three_line_ending_forms_hash_identically():
    crlf = "\r\n".join(BASE.split("\n"))
    cr_only = "\r".join(BASE.split("\n"))
    with tempfile.TemporaryDirectory() as td:
        b_lf = _load_variant(td, "a.md", BASE)
        b_crlf = _load_variant(td, "b.md", crlf)
        b_cr = _load_variant(td, "c.md", cr_only)
        assert b_lf.sha256 == b_crlf.sha256
        # A fully \r-separated brief must also parse and hash identically.
        assert b_lf.sha256 == b_cr.sha256
        assert b_cr.title == b_lf.title
