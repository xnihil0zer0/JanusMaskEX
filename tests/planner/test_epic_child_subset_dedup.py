"""RED oracle (B1 fix): _finalize_epic_children must collapse near-synonym child
sub-epics, not just exact hyphen/underscore variants.

The epic decomposer reconciles TWO agents' child-grouping proposals (the brief's
suggested grouping + the agent's re-derived grouping). They produce the SAME
semantic sub-epics under slightly different slugs that differ only by an added
domain-qualifier token, e.g. ``analytics-and-roi`` vs ``kg-analytics-and-roi``
or ``kg-graph-and-extraction`` vs ``kg-knowledge-graph-and-extraction``. The
existing canonical (``_`` -> ``-``) dedup keeps BOTH, so every leaf is built
~twice (the twin decomposes into the same leaves which then self-dedup at build
time, blocking redundantly). This ~2x's wall-time across the whole epic tree.

Fix: in addition to exact-canonical dedup, ``_finalize_epic_children`` dedupes by
the slug's SIGNIFICANT-TOKEN SET (kebab tokens minus stopwords). A child whose
token set is a subset of, equal to, or a superset of an already-kept child's
token set is a near-synonym twin and is DROPPED (first-seen of each group wins).
This is safe: twins decompose into the same leaves, so coverage is preserved.
Genuinely distinct sub-epics (no subset/superset token relationship) are kept.

The helper stays PURE (returns new list, never mutates input) and keeps its
existing canonicalization / working_dir stamping / epic-marking behavior.
"""
from __future__ import annotations

import copy

from harness.planner.cli import _finalize_epic_children


def _cb(slug, **over):
    base = dict(slug=slug, title=f"Child {slug}", scope=f"build {slug}")
    base.update(over)
    return base


def _slugs(out):
    return [c["slug"] for c in out]


def test_near_synonym_twins_collapse_first_wins():
    """The 8-way knowledge duplication (4 dup pairs) collapses to 4, first wins."""
    children = [
        _cb("analytics-and-roi"),
        _cb("kg-graph-and-extraction"),
        _cb("kg-analytics-and-roi"),               # superset of analytics-and-roi -> drop
        _cb("kg-knowledge-graph-and-extraction"),  # superset of kg-graph-and-extraction -> drop
        _cb("kg-persistence-and-ledgers"),
        _cb("kg-submission-tooling"),
        _cb("persistence-and-ledgers"),            # subset of kg-persistence-and-ledgers -> drop
        _cb("submission-tooling"),                 # subset of kg-submission-tooling -> drop
    ]
    out = _finalize_epic_children(children, None, False)
    assert _slugs(out) == [
        "analytics-and-roi",
        "kg-graph-and-extraction",
        "kg-persistence-and-ledgers",
        "kg-submission-tooling",
    ]


def test_exact_canonical_dedup_unchanged():
    """Hyphen/underscore exact variants still collapse, first wins (regression)."""
    out = _finalize_epic_children([_cb("alpha-one"), _cb("alpha_one"), _cb("beta")], None, False)
    assert _slugs(out) == ["alpha-one", "beta"]


def test_distinct_subepics_preserved():
    """Sub-epics with no subset/superset token relationship are all kept."""
    out = _finalize_epic_children(
        [_cb("state-lifecycle"), _cb("scheduling-cascades"), _cb("workers-coordination")],
        None, False,
    )
    assert _slugs(out) == ["state-lifecycle", "scheduling-cascades", "workers-coordination"]


def test_single_token_distinct_slugs_preserved():
    """Two distinct single-token slugs are not over-collapsed."""
    out = _finalize_epic_children([_cb("alpha"), _cb("beta")], None, False)
    assert _slugs(out) == ["alpha", "beta"]


def test_qualifier_added_to_single_token_collapses():
    """A base token + the same base with an added qualifier are one group."""
    out = _finalize_epic_children([_cb("workers"), _cb("workers-coordination")], None, False)
    assert _slugs(out) == ["workers"]


def test_pure_no_input_mutation():
    inp = [_cb("a-b"), _cb("kg-a-b")]
    snap = copy.deepcopy(inp)
    _finalize_epic_children(inp, None, False)
    assert inp == snap


def test_working_dir_and_epic_marking_preserved():
    """Existing stamping/marking behavior is retained for kept children."""
    out = _finalize_epic_children([_cb("suba"), _cb("subb")], "/ext/wd", True)
    assert _slugs(out) == ["suba", "subb"]
    assert all(c.get("working_dir") == "/ext/wd" and c.get("epic") is True for c in out)
