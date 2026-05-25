import json
import difflib
import random
from pathlib import Path
from copy import deepcopy

import hypothesis.strategies as st
from hypothesis import given, settings

from harness.planner.diff_extractor import (
    extract_diff,
    MATCH_FILES_JACCARD_HIGH,
    MATCH_FILES_JACCARD_PAIR,
    MATCH_TITLE_RATIO_PAIR,
    MATCH_TITLE_RATIO_SOLO,
    NEAR_MISS_FILES_JACCARD_LOW,
    NEAR_MISS_TITLE_RATIO_LOW,
)
from harness.planner.diff_model import DiffKind, FieldKind, PlanDiff, DiffItem

def get_base_task(tid: str, title: str) -> dict:
    return {
        "task_id": tid,
        "title": title,
        "priority": 1,
        "dependencies": [],
        "files_touched": [],
        "spec": {
            "objective": "obj",
            "functional_requirements": ["fr1"],
            "edge_cases": [],
            "non_goals": []
        },
        "test_spec": {
            "unit_tests": [],
            "integration_tests": [],
            "property_tests": [],
            "regression_tests": []
        }
    }

def test_extract_diff_identical_plans_empty_or_convergent():
    t = get_base_task("T1", "Title 1")
    plan = {"tasks": [t]}
    diff = extract_diff(plan, plan)
    assert not any(item.kind == DiffKind.divergent for item in diff.items)
    assert sum(1 for item in diff.items if item.kind == DiffKind.convergent) == 1

def test_extract_diff_claude_only():
    plan_c = {"tasks": [get_base_task("T1", "Title 1")]}
    plan_g = {"tasks": []}
    diff = extract_diff(plan_c, plan_g)
    assert len(diff.items) == 1
    assert diff.items[0].kind == DiffKind.claude_only
    assert diff.items[0].claude_task["task_id"] == "T1"

def test_extract_diff_matching_id_divergent_priority():
    t_c = get_base_task("T1", "Title")
    t_c["priority"] = 1
    t_g = get_base_task("T1", "Title")
    t_g["priority"] = 2
    diff = extract_diff({"tasks": [t_c]}, {"tasks": [t_g]})
    assert len(diff.items) == 1
    item = diff.items[0]
    assert item.kind == DiffKind.divergent
    kinds = [d[0] for d in item.field_divergences]
    assert FieldKind.priority in kinds

def test_heuristic_match_on_title_and_files():
    t_c = get_base_task("C1", "Title of the task is quite long")
    t_c["files_touched"] = ["a.py", "b.py"]
    t_g = get_base_task("G1", "Title of the task is quite logn")
    t_g["files_touched"] = ["a.py", "b.py"]
    
    diff = extract_diff({"tasks": [t_c]}, {"tasks": [t_g]})
    assert len(diff.items) == 1
    assert diff.items[0].kind in (DiffKind.divergent, DiffKind.convergent)
    assert diff.items[0].match_reason == "files_and_title"

def test_ambiguous_match_surfaced():
    t_c = get_base_task("C1", "Shared title")
    t_g1 = get_base_task("G1", "Shared title")
    t_g2 = get_base_task("G2", "Shared title")
    
    diff = extract_diff({"tasks": [t_c]}, {"tasks": [t_g1, t_g2]})
    ambig_items = [i for i in diff.items if i.kind == DiffKind.ambiguous_match]
    assert len(ambig_items) == 1
    assert ambig_items[0].claude_task["task_id"] == "C1"
    assert len(ambig_items[0].candidates) == 2

def test_dependencies_order_insensitive():
    t_c = get_base_task("T1", "Title")
    t_c["dependencies"] = ["A", "B"]
    t_g = get_base_task("T1", "Title")
    t_g["dependencies"] = ["B", "A"]
    diff = extract_diff({"tasks": [t_c]}, {"tasks": [t_g]})
    assert len(diff.items) == 1
    kinds = [d[0] for d in diff.items[0].field_divergences]
    assert FieldKind.dependencies not in kinds

def test_empty_plans_return_empty_diff():
    diff = extract_diff({"tasks": []}, {"tasks": []})
    assert len(diff.items) == 0

def test_heavy_paraphrase_matches_via_files_jaccard():
    t_c = get_base_task("C1", "Refactor orchestrator logic")
    t_c["files_touched"] = ["x.py", "y.py", "z.py"]
    t_g = get_base_task("G1", "Rewrite the main execution loop")
    t_g["files_touched"] = ["x.py", "y.py", "z.py"]
    diff = extract_diff({"tasks": [t_c]}, {"tasks": [t_g]})
    assert len(diff.items) == 1
    item = diff.items[0]
    assert item.kind in (DiffKind.divergent, DiffKind.convergent)
    assert item.match_reason == "files_jaccard_high"

def test_near_miss_flag_emitted():
    t_c = get_base_task("C1", "A completely different title")
    t_c["files_touched"] = ["a.py", "b.py", "c.py", "d.py"]
    
    t_g = get_base_task("G1", "Another unrelated title")
    t_g["files_touched"] = ["a.py"]
    
    diff = extract_diff({"tasks": [t_c]}, {"tasks": [t_g]})
    assert len(diff.items) == 2
    c_item = next(i for i in diff.items if i.kind == DiffKind.claude_only)
    g_item = next(i for i in diff.items if i.kind == DiffKind.gemini_only)
    assert c_item.candidate_near_miss == "G1"
    assert g_item.candidate_near_miss == "C1"

def test_files_jaccard_threshold_edges():
    t_c1 = get_base_task("C1", "QWERTYUIOP")
    t_c1["files_touched"] = ["a.py", "b.py", "c.py"]
    t_g1 = get_base_task("G1", "ASDFGHJKLZ")
    t_g1["files_touched"] = ["a.py", "b.py", "c.py", "d.py"]
    diff1 = extract_diff({"tasks": [t_c1]}, {"tasks": [t_g1]})
    assert len(diff1.items) == 1
    assert diff1.items[0].kind in (DiffKind.divergent, DiffKind.convergent)
    
    t_g2 = get_base_task("G1", "ZXCVBNMLKQ")
    t_g2["files_touched"] = ["a.py", "b.py", "c.py", "d.py", "e.py"]
    diff2 = extract_diff({"tasks": [t_c1]}, {"tasks": [t_g2]})
    assert diff2.items[0].kind in (DiffKind.claude_only, DiffKind.gemini_only)

def test_match_reason_recorded():
    t_c = get_base_task("C1", "Exactly the same title string here")
    t_g = get_base_task("G1", "Exactly the same title string here")
    diff = extract_diff({"tasks": [t_c]}, {"tasks": [t_g]})
    assert len(diff.items) == 1
    assert diff.items[0].match_reason in ("title_ratio_solo", "files_and_title", "files_jaccard_high", "task_id")

def test_extract_diff_against_real_fixture_plans():
    c_path = Path("tests/planner/fixtures/diffs/claude_plan.json")
    g_path = Path("tests/planner/fixtures/diffs/gemini_plan.json")
    if not c_path.exists():
        c_path.parent.mkdir(parents=True, exist_ok=True)
        c_path.write_text('{"tasks": []}')
        g_path.write_text('{"tasks": []}')
    c_plan = json.loads(c_path.read_text())
    g_plan = json.loads(g_path.read_text())
    diff = extract_diff(c_plan, g_plan)
    assert isinstance(diff, PlanDiff)

@st.composite
def task_dict_strategy(draw):
    tid = draw(st.text(min_size=1, max_size=5))
    title = draw(st.text(min_size=0, max_size=10))
    prio = draw(st.integers(1, 3))
    files = draw(st.lists(st.text(min_size=1, max_size=3), max_size=3))
    return {
        "task_id": tid,
        "title": title,
        "priority": prio,
        "files_touched": files,
        "spec": {},
        "test_spec": {}
    }

@st.composite
def plan_dict_strategy(draw):
    tasks = draw(st.lists(task_dict_strategy(), max_size=5))
    return {"tasks": tasks}

@settings(max_examples=100)
@given(plan_dict_strategy())
def test_diff_idempotence(plan):
    diff = extract_diff(plan, plan)
    assert not any(i.kind == DiffKind.divergent for i in diff.items)

@settings(max_examples=100)
@given(plan_dict_strategy(), plan_dict_strategy())
def test_diff_symmetry(planA, planB):
    diff_AB = extract_diff(planA, planB)
    diff_BA = extract_diff(planB, planA)
    
    ids_AB = set(i.diff_item_id for i in diff_AB.items)
    transformed_BA_items = []
    
    for item in diff_BA.items:
        if item.kind == DiffKind.claude_only:
            k = DiffKind.gemini_only
        elif item.kind == DiffKind.gemini_only:
            k = DiffKind.claude_only
        else:
            k = item.kind
            
        divs = [(div[0], div[2], div[1]) for div in item.field_divergences]
        cands = item.candidates
        
        new_item = DiffItem(
            kind=k,
            claude_task=item.gemini_task,
            gemini_task=item.claude_task,
            field_divergences=tuple(divs),
            match_reason=item.match_reason,
            candidate_near_miss=item.candidate_near_miss,
            candidates=cands
        )
        transformed_BA_items.append(new_item.diff_item_id)
        
    assert ids_AB == set(transformed_BA_items)

@settings(max_examples=50)
@given(plan_dict_strategy())
def test_diff_task_permutation_stability(plan):
    tasks = plan["tasks"]
    if not tasks: return
    shuffled = list(tasks)
    random.shuffle(shuffled)
    plan2 = {"tasks": shuffled}
    
    diff1 = extract_diff(plan, plan)
    diff2 = extract_diff(plan2, plan2)
    assert set(i.diff_item_id for i in diff1.items) == set(i.diff_item_id for i in diff2.items)

def test_exactly_0_85_similarity_accepted():
    t_c = get_base_task("C1", "ABCDEFGHIJKLMNOPQRST")
    t_g = get_base_task("G1", "ABCDEFGHIJKLMNOPQxyz")
    ratio = difflib.SequenceMatcher(None, t_c["title"], t_g["title"]).ratio()
    assert ratio == 0.85
    diff = extract_diff({"tasks": [t_c]}, {"tasks": [t_g]})
    assert len(diff.items) == 1
    assert diff.items[0].kind in (DiffKind.divergent, DiffKind.convergent)

def test_0_849_similarity_rejected():
    t_c = get_base_task("C1", "A" * 100)
    t_g = get_base_task("G1", "A" * 84 + "B" * 16)
    t_c["files_touched"] = ["a.py"]
    t_g["files_touched"] = ["b.py"]
    ratio = difflib.SequenceMatcher(None, t_c["title"], t_g["title"]).ratio()
    assert ratio == 0.84
    diff = extract_diff({"tasks": [t_c]}, {"tasks": [t_g]})
    assert diff.items[0].kind in (DiffKind.claude_only, DiffKind.gemini_only)

def test_duplicate_task_id_within_single_plan_handled():
    t_c1 = get_base_task("T1", "Title")
    t_c2 = get_base_task("T1", "Title")
    t_g1 = get_base_task("T1", "Title")
    diff = extract_diff({"tasks": [t_c1, t_c2]}, {"tasks": [t_g1]})
    assert len(diff.items) == 2
    kinds = [i.kind for i in diff.items]
    assert DiffKind.claude_only in kinds
    assert DiffKind.convergent in kinds or DiffKind.divergent in kinds
