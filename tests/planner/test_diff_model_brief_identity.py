"""Oracle for Brief 8: widen ``FieldKind`` with brief-level members and give
``DiffItem`` a slug identity fallback when ``task_id`` is absent.

RED on HEAD: ``FieldKind`` is a closed Enum (scope/priority/tests/dependencies/
files_touched/edge_cases/non_goals) with no member for the brief-level fields a
child-brief diff produces (scope_text/deliverables/interfaces/inputs). And
``DiffItem.__post_init__`` hashes identity purely on ``task_id``; child briefs
have no ``task_id`` (only ``slug``), so two distinct child briefs both resolve
to ``task_id == ""`` and hash-COLLIDE. Brief 8 closes both gaps without
disturbing the leaf-task identity (task_id still wins when present).
"""
from __future__ import annotations

from harness.planner.diff_model import DiffItem, DiffKind, FieldKind, PlanDiff


# ---- Part A: FieldKind brief-level members --------------------------------

def test_fieldkind_has_brief_members() -> None:
    for name in ("scope_text", "deliverables", "interfaces", "inputs"):
        assert hasattr(FieldKind, name), f"FieldKind missing {name}"
        assert FieldKind(name).value == name  # str-Enum value round-trip


def test_fieldkind_preserves_leaf_members() -> None:
    for name in (
        "scope", "priority", "tests", "dependencies",
        "files_touched", "edge_cases", "non_goals",
    ):
        assert FieldKind(name).value == name


# ---- Part B: DiffItem slug identity fallback ------------------------------

def test_identity_falls_back_to_slug_when_no_task_id() -> None:
    a = DiffItem(kind=DiffKind.convergent,
                 claude_task={"slug": "child_a"}, gemini_task={"slug": "child_a"})
    b = DiffItem(kind=DiffKind.convergent,
                 claude_task={"slug": "child_b"}, gemini_task={"slug": "child_b"})
    # Distinct slugs must not hash-collide (the latent bug on HEAD).
    assert a.diff_item_id != b.diff_item_id


def test_identity_task_id_wins_when_present() -> None:
    # Back-compat: when task_id is present, slug must NOT influence identity,
    # so the diff_item_id is byte-identical to the slug-less form.
    with_slug = DiffItem(kind=DiffKind.convergent,
                         claude_task={"task_id": "t1", "slug": "s1"},
                         gemini_task={"task_id": "t1", "slug": "s2"})
    without_slug = DiffItem(kind=DiffKind.convergent,
                            claude_task={"task_id": "t1"},
                            gemini_task={"task_id": "t1"})
    assert with_slug.diff_item_id == without_slug.diff_item_id


def test_identity_degenerate_no_taskid_no_slug() -> None:
    # Neither task_id nor slug: must still produce a stable 40-char sha1, no crash.
    x = DiffItem(kind=DiffKind.claude_only, claude_task={})
    assert isinstance(x.diff_item_id, str) and len(x.diff_item_id) == 40


def test_one_sided_brief_identity_distinct() -> None:
    a = DiffItem(kind=DiffKind.claude_only, claude_task={"slug": "only_a"})
    b = DiffItem(kind=DiffKind.claude_only, claude_task={"slug": "only_b"})
    assert a.diff_item_id != b.diff_item_id


# ---- Part C: round-trip with brief-level FieldKind ------------------------

def test_brief_diffitem_roundtrips() -> None:
    item = DiffItem(
        kind=DiffKind.divergent,
        claude_task={"slug": "c"}, gemini_task={"slug": "c"},
        field_divergences=((FieldKind.deliverables, "x", "y"),
                           (FieldKind.interfaces, "a", "b")),
    )
    rt = PlanDiff.from_json(PlanDiff(items=(item,)).to_json())
    kinds = {d[0] for d in rt.items[0].field_divergences}
    assert FieldKind.deliverables in kinds
    assert FieldKind.interfaces in kinds
    assert rt.items[0].diff_item_id == item.diff_item_id
