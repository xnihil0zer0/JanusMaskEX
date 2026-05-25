import pytest
from hypothesis import given, strategies as st
from harness.planner.diff_model import DiffItem, PlanDiff, DiffKind, FieldKind

def test_diff_item_id_deterministic():
    item1 = DiffItem(kind=DiffKind.claude_only, claude_task={"task_id": "T1"})
    item2 = DiffItem(kind=DiffKind.claude_only, claude_task={"task_id": "T1"})
    assert item1.diff_item_id == item2.diff_item_id

def test_diff_item_id_unique_for_different_kinds():
    item1 = DiffItem(kind=DiffKind.claude_only, claude_task={"task_id": "T1"})
    item2 = DiffItem(kind=DiffKind.gemini_only, claude_task={"task_id": "T1"})
    assert item1.diff_item_id != item2.diff_item_id

def test_plandiff_to_from_json_roundtrip():
    item = DiffItem(
        kind=DiffKind.divergent,
        claude_task={"task_id": "T1", "priority": 1},
        gemini_task={"task_id": "T1", "priority": 2},
        field_divergences=((FieldKind.priority, 1, 2),)
    )
    diff = PlanDiff((item,))
    json_str = diff.to_json()
    loaded = PlanDiff.from_json(json_str)
    assert loaded == diff

def test_plandiff_json_byte_stable():
    item = DiffItem(kind=DiffKind.claude_only, claude_task={"task_id": "T1"})
    diff = PlanDiff((item,))
    s1 = diff.to_json()
    s2 = diff.to_json()
    assert s1 == s2

def test_empty_plandiff_roundtrip():
    diff = PlanDiff(())
    assert PlanDiff.from_json(diff.to_json()) == diff

def test_plandiff_consumed_by_validator():
    items = tuple(DiffItem(kind=DiffKind.claude_only, claude_task={"task_id": f"T{i}"}) for i in range(10))
    diff = PlanDiff(items)
    json_str = diff.to_json()
    loaded = PlanDiff.from_json(json_str)
    ids = [item.diff_item_id for item in loaded.items]
    assert len(set(ids)) == 10

def json_value():
    return st.one_of(
        st.none(),
        st.booleans(),
        st.integers(),
        st.floats(allow_nan=False, allow_infinity=False),
        st.text()
    )

def task_dict():
    return st.dictionaries(
        keys=st.sampled_from(["task_id", "title", "priority"]),
        values=st.text()
    )

@st.composite
def diff_item_strategy(draw):
    kind = draw(st.sampled_from(DiffKind))
    claude_task = draw(st.one_of(st.none(), task_dict()))
    gemini_task = draw(st.one_of(st.none(), task_dict()))
    
    divs = draw(st.lists(
        st.tuples(st.sampled_from(FieldKind), json_value(), json_value()),
        max_size=3
    ))
    return DiffItem(kind=kind, claude_task=claude_task, gemini_task=gemini_task, field_divergences=tuple(divs))

@given(st.lists(diff_item_strategy(), max_size=5).map(tuple).map(PlanDiff))
def test_roundtrip_property(diff):
    assert PlanDiff.from_json(diff.to_json()) == diff

@given(st.lists(diff_item_strategy(), min_size=10, max_size=20))
def test_id_collision_low_probability(items):
    distinct_items = {
        (item.kind, 
         item.claude_task.get("task_id", "") if item.claude_task else "",
         item.gemini_task.get("task_id", "") if item.gemini_task else "",
         tuple(sorted(item.field_divergences, key=lambda x: x[0])))
         for item in items
    }
    
    ids = {item.diff_item_id for item in items}
    assert len(ids) >= len(distinct_items)

def test_none_field_divergence_value_preserved():
    item = DiffItem(
        kind=DiffKind.divergent,
        field_divergences=((FieldKind.priority, None, None),)
    )
    diff = PlanDiff((item,))
    assert diff.items[0].field_divergences[0] == (FieldKind.priority, None, None)
    loaded = PlanDiff.from_json(diff.to_json())
    assert loaded.items[0].field_divergences[0] == (FieldKind.priority, None, None)

def test_long_edge_case_list_handled():
    edge_cases = ["case" + str(i) for i in range(100)]
    item = DiffItem(
        kind=DiffKind.divergent,
        field_divergences=((FieldKind.edge_cases, edge_cases, []),)
    )
    diff = PlanDiff((item,))
    loaded = PlanDiff.from_json(diff.to_json())
    assert loaded.items[0].field_divergences[0][1] == edge_cases
