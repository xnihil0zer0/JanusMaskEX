import difflib
from typing import Dict, Any, List, Tuple, Set, Optional
from harness.planner.diff_model import PlanDiff, DiffItem, DiffKind, FieldKind

MATCH_FILES_JACCARD_HIGH = 0.75
MATCH_FILES_JACCARD_PAIR = 0.5
MATCH_TITLE_RATIO_PAIR = 0.6
MATCH_TITLE_RATIO_SOLO = 0.85
NEAR_MISS_FILES_JACCARD_LOW = 0.25
NEAR_MISS_TITLE_RATIO_LOW = 0.6

def _jaccard(set1: Set[str], set2: Set[str]) -> float:
    if not set1 and not set2:
        return 1.0
    intersection = len(set1.intersection(set2))
    union = len(set1.union(set2))
    return intersection / union if union > 0 else 0.0

def _compare_fields(claude_task: dict, gemini_task: dict) -> Tuple[Tuple[FieldKind, Any, Any], ...]:
    divergences = []
    
    claude_spec = claude_task.get("spec", {})
    gemini_spec = gemini_task.get("spec", {})
    
    # scope
    claude_scope = (claude_spec.get("objective", ""), tuple(claude_spec.get("functional_requirements", [])))
    gemini_scope = (gemini_spec.get("objective", ""), tuple(gemini_spec.get("functional_requirements", [])))
    if claude_scope != gemini_scope:
        divergences.append((FieldKind.scope, claude_scope, gemini_scope))
        
    # priority
    if claude_task.get("priority") != gemini_task.get("priority"):
        divergences.append((FieldKind.priority, claude_task.get("priority"), gemini_task.get("priority")))
        
    # dependencies
    claude_deps = claude_task.get("dependencies", [])
    gemini_deps = gemini_task.get("dependencies", [])
    if set(claude_deps) != set(gemini_deps):
        divergences.append((FieldKind.dependencies, claude_deps, gemini_deps))
        
    # files_touched
    claude_files = claude_task.get("files_touched", [])
    gemini_files = gemini_task.get("files_touched", [])
    if set(claude_files) != set(gemini_files):
        divergences.append((FieldKind.files_touched, claude_files, gemini_files))
        
    # edge_cases
    claude_ec = claude_spec.get("edge_cases", [])
    gemini_ec = gemini_spec.get("edge_cases", [])
    if set(claude_ec) != set(gemini_ec):
        divergences.append((FieldKind.edge_cases, claude_ec, gemini_ec))
        
    # non_goals
    claude_ng = claude_spec.get("non_goals", [])
    gemini_ng = gemini_spec.get("non_goals", [])
    if set(claude_ng) != set(gemini_ng):
        divergences.append((FieldKind.non_goals, claude_ng, gemini_ng))
        
    # test_spec
    claude_ts = claude_task.get("test_spec", {})
    gemini_ts = gemini_task.get("test_spec", {})
    
    def _extract_test_info(ts):
        unit = ts.get("unit_tests", [])
        integration = ts.get("integration_tests", [])
        property_ = ts.get("property_tests", [])
        regression = ts.get("regression_tests", [])
        
        def _get_name(t):
            if isinstance(t, dict):
                return t.get("name", str(t))
            return str(t)
            
        return {
            "unit": (len(unit), tuple(_get_name(t) for t in unit)),
            "integration": (len(integration), tuple(_get_name(t) for t in integration)),
            "property": (len(property_), tuple(_get_name(t) for t in property_)),
            "regression": (len(regression), tuple(_get_name(t) for t in regression))
        }
        
    if _extract_test_info(claude_ts) != _extract_test_info(gemini_ts):
        divergences.append((FieldKind.tests, claude_ts, gemini_ts))
        
    return tuple(divergences)

def _get_match_reason_and_score(c_task: dict, g_task: dict) -> Tuple[Optional[str], Tuple[float, float]]:
    c_files = set(c_task.get("files_touched", []))
    g_files = set(g_task.get("files_touched", []))
    jaccard = _jaccard(c_files, g_files)
    ratio = difflib.SequenceMatcher(None, c_task.get("title", ""), g_task.get("title", "")).ratio()
    
    if jaccard >= MATCH_FILES_JACCARD_PAIR and ratio >= MATCH_TITLE_RATIO_PAIR:
        return "files_and_title", (jaccard, ratio)
    if jaccard >= MATCH_FILES_JACCARD_HIGH:
        return "files_jaccard_high", (jaccard, ratio)
    if ratio >= MATCH_TITLE_RATIO_SOLO:
        return "title_ratio_solo", (jaccard, ratio)
    return None, (jaccard, ratio)

def _is_near_miss(c_task: dict, g_task: dict) -> bool:
    c_files = set(c_task.get("files_touched", []))
    g_files = set(g_task.get("files_touched", []))
    jaccard = _jaccard(c_files, g_files)
    ratio = difflib.SequenceMatcher(None, c_task.get("title", ""), g_task.get("title", "")).ratio()
    
    # We round to avoid float precision issues if exactly on threshold edge
    return (NEAR_MISS_FILES_JACCARD_LOW <= round(jaccard, 5) < MATCH_FILES_JACCARD_PAIR) or \
           (NEAR_MISS_TITLE_RATIO_LOW <= round(ratio, 5) < MATCH_TITLE_RATIO_SOLO)

def extract_diff(claude_plan: dict, gemini_plan: dict) -> PlanDiff:
    items = []
    
    c_tasks = claude_plan.get("tasks", [])
    g_tasks = gemini_plan.get("tasks", [])
    
    # 1. task_id matching
    from collections import defaultdict
    c_by_id = defaultdict(list)
    g_by_id = defaultdict(list)
    c_unmatched = []
    g_unmatched = []

    for c in c_tasks:
        tid = c.get("task_id")
        if tid is None:
            c_unmatched.append(c)
        else:
            c_by_id[tid].append(c)

    for g in g_tasks:
        tid = g.get("task_id")
        if tid is None:
            g_unmatched.append(g)
        else:
            g_by_id[tid].append(g)
    
    for tid in set(c_by_id.keys()).union(g_by_id.keys()):
        c_list = c_by_id[tid]
        g_list = g_by_id[tid]
        if c_list and g_list:
            min_len = min(len(c_list), len(g_list))
            for i in range(min_len):
                divs = _compare_fields(c_list[i], g_list[i])
                kind = DiffKind.divergent if divs else DiffKind.convergent
                items.append(DiffItem(
                    kind=kind,
                    claude_task=c_list[i],
                    gemini_task=g_list[i],
                    field_divergences=divs,
                    match_reason="task_id"
                ))
            c_unmatched.extend(c_list[min_len:])
            g_unmatched.extend(g_list[min_len:])
        elif c_list:
            c_unmatched.extend(c_list)
        else:
            g_unmatched.extend(g_list)
            
    # 2. Heuristic matching
    # Build candidate graph
    c_candidates = defaultdict(list)
    g_candidates = defaultdict(list)
    
    for i, c_task in enumerate(c_unmatched):
        for j, g_task in enumerate(g_unmatched):
            reason, score = _get_match_reason_and_score(c_task, g_task)
            if reason:
                c_candidates[i].append((j, reason, score))
                g_candidates[j].append((i, reason, score))
                
    matched_c = set()
    matched_g = set()
    
    # Find components
    for i in range(len(c_unmatched)):
        if i in matched_c: continue
        c_cands = c_candidates[i]
        if len(c_cands) == 1:
            j, reason, score = c_cands[0]
            if len(g_candidates[j]) == 1:
                # strict 1-to-1 heuristic match
                divs = _compare_fields(c_unmatched[i], g_unmatched[j])
                kind = DiffKind.divergent if divs else DiffKind.convergent
                items.append(DiffItem(
                    kind=kind,
                    claude_task=c_unmatched[i],
                    gemini_task=g_unmatched[j],
                    field_divergences=divs,
                    match_reason=reason
                ))
                matched_c.add(i)
                matched_g.add(j)
                
    ambiguous_c = set()
    ambiguous_g = set()
    
    # Now for degree > 1
    for i in range(len(c_unmatched)):
        if i in matched_c: continue
        if len(c_candidates[i]) > 1:
            cand_tuples = tuple(
                (g_unmatched[j].get("task_id", ""), r, s) 
                for j, r, s in c_candidates[i]
            )
            cand_tuples = tuple(sorted(cand_tuples, key=lambda x: x[0]))
            items.append(DiffItem(
                kind=DiffKind.ambiguous_match,
                claude_task=c_unmatched[i],
                candidates=cand_tuples
            ))
            ambiguous_c.add(i)
            for j, _, _ in c_candidates[i]:
                ambiguous_g.add(j)
                
    for j in range(len(g_unmatched)):
        if j in matched_g: continue
        if len(g_candidates[j]) > 1:
            cand_tuples = tuple(
                (c_unmatched[i].get("task_id", ""), r, s) 
                for i, r, s in g_candidates[j]
            )
            cand_tuples = tuple(sorted(cand_tuples, key=lambda x: x[0]))
            items.append(DiffItem(
                kind=DiffKind.ambiguous_match,
                gemini_task=g_unmatched[j],
                candidates=cand_tuples
            ))
            ambiguous_g.add(j)
            for i, _, _ in g_candidates[j]:
                ambiguous_c.add(i)

    # 3. Unmatched and Near miss
    for i in range(len(c_unmatched)):
        if i in matched_c or i in ambiguous_c: continue
        c_task = c_unmatched[i]
        near_miss = None
        for g_task in g_tasks:
            if _is_near_miss(c_task, g_task):
                near_miss = g_task.get("task_id", "")
                break
        items.append(DiffItem(
            kind=DiffKind.claude_only,
            claude_task=c_task,
            candidate_near_miss=near_miss
        ))
        
    for j in range(len(g_unmatched)):
        if j in matched_g or j in ambiguous_g: continue
        g_task = g_unmatched[j]
        near_miss = None
        for c_task in c_tasks:
            if _is_near_miss(c_task, g_task):
                near_miss = c_task.get("task_id", "")
                break
        items.append(DiffItem(
            kind=DiffKind.gemini_only,
            gemini_task=g_task,
            candidate_near_miss=near_miss
        ))
        
    return PlanDiff(items=tuple(items))
