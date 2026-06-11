"""RED oracle: _finalize_epic_children must SANITIZE child slugs of path
separators / ``..`` before they flow into a filesystem path.

THE BUG (CWE-22 / CWE-20, verified 2026-06-11): ``harness/planner/cli.py``
canonicalizes each reconciled child-brief slug with ONLY
``str(slug).strip().replace('_', '-')`` (``_finalize_epic_children``, ~cli.py:154)
and then ``_run_epic_pipeline`` (~cli.py:210) writes
``(repo_root / ('brief_hooks_' + child['slug'] + '.md')).write_text(...)``. The
slug originates from LLM-reconciled child briefs, so it is untrusted input. The
canonicalizer never strips ``/`` or ``..``, so a crafted slug like
``a/../../x`` survives intact and the constructed path lexically escapes
``repo_root`` (``(repo_root / 'brief_hooks_a/../../x.md').resolve()`` lands at
``<parent>/x.md``, OUTSIDE repo_root). ``foo/bar`` writes into a subdirectory
(``brief_hooks_foo/bar.md``). The ``brief_hooks_`` prefix and the lack of
intermediate-dir creation make some payloads fail closed by accident, but an
unsanitized slug flowing into a filesystem path is a real defensive gap.

THE CONTRACT this oracle pins: the canonical slug returned by
``_finalize_epic_children`` must contain NO ``/`` and NO ``..`` path component,
and ``(repo_root / ('brief_hooks_' + canonical + '.md')).resolve()`` must stay
within ``repo_root.resolve()`` for any malicious input slug. Benign slugs keep
their documented ``strip()`` + ``_`` -> ``-`` behavior unchanged.

RED today: ``a/../../x`` survives canonicalization with separators intact and
escapes repo_root. GREEN after the fix: the slug is reduced to a safe
``[A-Za-z0-9_-]`` token, no separators survive, and every constructed path
stays inside repo_root.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from harness.planner.cli import _finalize_epic_children


def _canon(slug):
    """Drive the REAL top-level canonicalizer and return the resulting slug.

    ``_finalize_epic_children`` is the importable public seam that performs the
    canonicalization used by the epic child-brief write site; it returns a NEW
    list of NEW child dicts whose ``slug`` is the canonical form.
    """
    out = _finalize_epic_children(
        [{"slug": slug, "title": "t", "scope": "s"}], None, False
    )
    return out[0]["slug"] if out else None


def _stays_inside(repo_root: Path, canonical: str) -> bool:
    target = (repo_root / ("brief_hooks_" + canonical + ".md")).resolve()
    root = repo_root.resolve()
    return target == root or str(target).startswith(str(root) + "/")


MALICIOUS = ["../../evil", "a/../../x", "foo/bar", ".."]


@pytest.mark.parametrize("raw", MALICIOUS)
def test_malicious_slug_has_no_path_separator(raw):
    canonical = _canon(raw)
    # An all-traversal slug like ".." may legitimately sanitize to empty and be
    # dropped (None); that is acceptable -- it never reaches a write.
    if canonical is None:
        return
    assert "/" not in canonical, (
        "canonical slug must not contain a path separator; got %r" % canonical
    )
    components = canonical.split("/")
    assert ".." not in components, (
        "canonical slug must not contain a '..' path component; got %r" % canonical
    )


@pytest.mark.parametrize("raw", MALICIOUS)
def test_malicious_slug_path_stays_in_repo_root(raw, tmp_path):
    canonical = _canon(raw)
    if canonical is None:
        return
    assert _stays_inside(tmp_path, canonical), (
        "constructed brief path escaped repo_root for slug %r -> canonical %r"
        % (raw, canonical)
    )


def test_benign_slug_preserves_documented_behavior():
    # Regression: a normal slug keeps the documented strip() + '_'->'-' behavior
    # and is otherwise untouched by the new sanitization.
    assert _canon("spine_token_roi") == "spine-token-roi"
    assert _canon("  alpha-one  ") == "alpha-one"
    assert _canon("plain") == "plain"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-x", "-q"]))
