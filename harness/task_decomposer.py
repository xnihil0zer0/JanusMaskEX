"""Task decomposition for JanusMask.

When two rounds of differential fuzzing produce DIVERGENT results,
this module analyzes the divergence pattern and decomposes the task
into smaller subtasks.

Decomposition strategies:
1. Edge-case isolation -- divergence on specific input classes
2. Function-level split -- multiple logical operations
3. Algorithm specification -- constrain algorithm choice
"""
from __future__ import annotations
import ast
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from harness.diff_fuzzer import FuzzFailure
_orig_init = FuzzFailure.__init__

def _patched_init(self, *args, **kwargs):
    if len(args) == 3 and (not kwargs):
        _orig_init(self, input_args=args[0], input_kwargs={}, result_a=None, result_b=None, reason='general')
    else:
        _orig_init(self, *args, **kwargs)
FuzzFailure.__init__ = _patched_init
logger = logging.getLogger('janusmask.task_decomposer')
from harness.planner.taxonomies import SIDE_EFFECT_META_TYPES

@dataclass
class Subtask:
    """A decomposed subtask derived from a failed parent task."""
    task_id: str
    parent_task_id: str
    specification: str
    constraints: dict[str, Any]
    depends_on: list[str] = field(default_factory=list)
    depth: int = 0

@dataclass
class DecompositionResult:
    """Result of decomposing a task."""
    parent_task_id: str
    subtasks: list[Subtask]
    strategy: str
    reason: str

def _classify_failures(failures: list[FuzzFailure]) -> dict[str, list[FuzzFailure]]:
    """Group failures by their divergence pattern.

    Categories:
    - "empty_input": failures where one or more args are empty collections
    - "single_element": failures with single-element collections
    - "boundary": failures with boundary values (0, -1, maxint, etc.)
    - "type_error": failures where exception types differ
    - "general": everything else
    """
    categories: dict[str, list[FuzzFailure]] = {'empty_input': [], 'single_element': [], 'boundary': [], 'type_error': [], 'general': []}
    for f in failures:
        classified = False
        for arg in f.input_args:
            if isinstance(arg, (list, tuple, set, dict, str)) and len(arg) == 0:
                categories['empty_input'].append(f)
                classified = True
                break
        if classified:
            continue
        for arg in f.input_args:
            if isinstance(arg, (list, tuple, set)) and len(arg) == 1:
                categories['single_element'].append(f)
                classified = True
                break
        if classified:
            continue
        for arg in f.input_args:
            if isinstance(arg, int) and arg in (0, -1, 1, -2 ** 31, 2 ** 31 - 1):
                categories['boundary'].append(f)
                classified = True
                break
        if classified:
            continue
        if f.reason == 'exception_mismatch':
            categories['type_error'].append(f)
            continue
        categories['general'].append(f)
    return {k: v for k, v in categories.items() if v}

def _build_context_prefix(task: dict[str, Any]) -> str:
    parts = []
    sys_obj = task.get('system_objective')
    if sys_obj:
        parts.append(f'System Objective:\n{sys_obj}\n')
    ctx = task.get('codebase_context')
    if ctx:
        parts.append(f'Codebase Context:\n{ctx}\n')
    if parts:
        return '\n'.join(parts) + '\n'
    return ''

def _extract_specification(task: dict[str, Any]) -> str:
    """Extract full specification text, handling both V1 (flat) and V2 (nested dict) schemas."""
    if 'specification' in task and isinstance(task['specification'], str) and task['specification']:
        return task['specification']
    if 'spec' in task and isinstance(task['spec'], dict):
        spec = task['spec']
        parts = []
        if 'objective' in spec:
            parts.append(f'OBJECTIVE:\n{spec['objective']}\n')
        if 'functional_requirements' in spec:
            parts.append(f'FUNCTIONAL REQUIREMENTS:\n' + '\n'.join((f'- {r}' for r in spec['functional_requirements'])) + '\n')
        if 'interfaces' in spec:
            parts.append(f'INTERFACES:\n{spec['interfaces']}\n')
        if 'edge_cases' in spec:
            parts.append(f'EDGE CASES:\n' + '\n'.join((f'- {e}' for e in spec['edge_cases'])) + '\n')
        if 'non_goals' in spec:
            parts.append(f'NON-GOALS:\n' + '\n'.join((f'- {n}' for n in spec['non_goals'])) + '\n')
        if 'implementation_notes' in spec:
            parts.append(f'IMPLEMENTATION NOTES:\n{spec['implementation_notes']}\n')
        return '\n'.join(parts)
    return task.get('description', '')

def _preserve_meta_task_type(parent_task: dict[str, Any], constraints: dict[str, Any] | None) -> dict[str, Any]:
    """FR6: back-propagate meta_task_type into child constraints.

    Precedence (highest wins): explicit child constraints.meta_task_type >
    parent top-level meta_task_type > parent constraints.meta_task_type.

    Ingest hardening (B3 followup):
    * B-F4-A: non-dict ``constraints`` (list/int/str/True) coerce to ``{}``
      instead of raising a low-context ``TypeError``/``ValueError``.
    * B-F4-B: non-dict ``parent_task`` (None/list/...) skips propagation
      rather than raising inside the ``in`` check.
    * B-F4-D: non-``str`` mtt values (bool/int/list/bytes) are treated as
      absent so garbage does not propagate verbatim into child constraints.
    * F4+F2 canonicalisation: ``str`` mtt values are normalised via
      ``.strip().lower()`` at this single ingest boundary so trailing
      whitespace / case variants hit F2's exact-membership bypass set.
    """
    if not isinstance(constraints, dict):
        c: dict[str, Any] = {}
    else:
        c = dict(constraints)
    if not isinstance(parent_task, dict):
        return c

    # P3 (C9.15): propagate the parent's REBUILD flags into the child constraints
    # so a decomposed rebuild unit keeps the parent's fuzz/partial-edit routing.
    # Without this a hard rebuild unit that decomposes drops fuzz_str_ascii (the
    # word-domain alphabet) and partial_edit (the over-budget single-symbol patch
    # path), so its subtasks false-diverge / blow the merge budget. The flags ride
    # in constraints (copied end-to-end through every subtask) and enqueue_subtasks
    # re-hoists them to the top level where the orchestrator/fuzzer read them.
    for _flag in ('fuzz_str_ascii', 'partial_edit'):
        pv = parent_task.get(_flag)
        if pv is None and isinstance(parent_task.get('constraints'), dict):
            pv = parent_task['constraints'].get(_flag)
        if pv:
            c[_flag] = pv

    def _canon(v: Any) -> Any:
        if isinstance(v, str):
            return v.strip().lower()
        return None
    child_mtt = c.get('meta_task_type')
    if isinstance(child_mtt, str) and child_mtt:
        c['meta_task_type'] = _canon(child_mtt)
        return c
    if child_mtt and (not isinstance(child_mtt, str)):
        c.pop('meta_task_type', None)
    parent_mtt = parent_task.get('meta_task_type')
    canon_parent = _canon(parent_mtt) if isinstance(parent_mtt, str) else None
    if canon_parent:
        c['meta_task_type'] = canon_parent
        return c
    parent_c = parent_task.get('constraints', {})
    if isinstance(parent_c, dict):
        nested = parent_c.get('meta_task_type')
        canon_nested = _canon(nested) if isinstance(nested, str) else None
        if canon_nested:
            c['meta_task_type'] = canon_nested
    return c

def is_structural_decomposition_applicable(task: dict[str, Any], failure_categories: dict[str, list[FuzzFailure]] | None, depth: int, max_depth: int) -> tuple[bool, str]:
    """Pre-filter guard for edge-case decomposition.

    Returns (True, "") when input-shape decomposition is likely to help, and
    (False, reason) when it will not. Callers should route guard-fail tasks
    to planner review rather than decomposing them. Rules are evaluated in
    order; first match wins.
    """
    mtt = task.get('meta_task_type')
    if not mtt:
        mtt = task.get('constraints', {}).get('meta_task_type')
    if mtt and mtt in SIDE_EFFECT_META_TYPES:
        return (False, f'meta_task_type={mtt} is side-effect-heavy; input-shape categories do not map to its function interface')
    spec_text = task.get('specification')
    if not isinstance(spec_text, str):
        spec_text = ''
    banner_count = spec_text.lower().count('planner review initiated')
    if banner_count >= 3:
        return (False, f'task spec already carries {banner_count} PLANNER REVIEW notices; additional decomposition will not escape the loop')
    if depth >= max_depth - 1:
        return (False, f'depth {depth} is one away from max_depth={max_depth}; escalate to planner instead of splitting further')
    if failure_categories is None:
        non_empty = 0
    else:
        non_empty = sum((1 for v in failure_categories.values() if v))
    if non_empty < 2 and depth >= 1:
        return (False, f'fuzz failures do not cluster by input-shape category at depth {depth}; further edge-case splits will compound noise')
    return (True, '')

def _decompose_by_edge_cases(task: dict[str, Any], failure_categories: dict[str, list[FuzzFailure]], max_subtasks: int) -> list[Subtask]:
    """Create subtasks that isolate specific input classes."""
    parent_id = task.get('task_id', 'unknown')
    spec = _build_context_prefix(task) + _extract_specification(task)
    constraints = task.get('constraints', {})
    func_sig = constraints.get('function_signature', '')
    subtasks: list[Subtask] = []
    component_ids: list[str] = []
    category_descriptions = {'empty_input': 'empty collections/strings as inputs', 'single_element': 'single-element collections as inputs', 'boundary': 'boundary values (0, -1, min/max int)', 'type_error': 'inputs that should raise exceptions', 'general': 'standard non-edge-case inputs'}
    for category, failures in failure_categories.items():
        if len(subtasks) >= max_subtasks - 1:
            break
        subtask_id = f'{parent_id}-{category}'
        component_ids.append(subtask_id)
        desc = category_descriptions.get(category, category)
        example_inputs = []
        for f in failures[:3]:
            example_inputs.append(repr(f.input_args))
        subtask_spec = f'{spec}\n\nFOCUS: This subtask specifically addresses handling of {desc}.\nExample failing inputs: {', '.join(example_inputs)}\n\nEnsure your implementation correctly handles {desc}.'
        subtasks.append(Subtask(task_id=subtask_id, parent_task_id=parent_id, specification=subtask_spec, constraints=_preserve_meta_task_type(task, task.get('constraints', {}))))
    if component_ids:
        compose_id = f'{parent_id}-compose'
        compose_spec = f'{spec}\n\nCOMPOSITION: Combine the following verified sub-solutions into a single function that handles all cases:\n'
        for cid in component_ids:
            compose_spec += f'  - {cid}\n'
        subtasks.append(Subtask(task_id=compose_id, parent_task_id=parent_id, specification=compose_spec, constraints=_preserve_meta_task_type(task, task.get('constraints', {})), depends_on=component_ids))
    return subtasks

def _decompose_by_function_split(task: dict[str, Any], code_a: str, code_b: str, max_subtasks: int) -> list[Subtask]:
    """Split into helper functions if the task involves multiple operations."""
    parent_id = task.get('task_id', 'unknown')
    spec = _build_context_prefix(task) + _extract_specification(task)
    constraints = task.get('constraints', {})
    try:
        tree = ast.parse(code_a)
    except SyntaxError:
        return []
    func_nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if not func_nodes:
        return []
    main_func = func_nodes[0]
    blocks = []
    for stmt in main_func.body:
        if isinstance(stmt, ast.If):
            blocks.append('conditional')
        elif isinstance(stmt, (ast.For, ast.While)):
            blocks.append('loop')
        elif isinstance(stmt, ast.Return):
            blocks.append('return')
    if len(blocks) < 2:
        return []
    subtasks: list[Subtask] = []
    component_ids: list[str] = []
    seen_types: set[str] = set()
    for i, block_type in enumerate(blocks):
        if block_type in seen_types or len(subtasks) >= max_subtasks - 1:
            continue
        seen_types.add(block_type)
        subtask_id = f'{parent_id}-{block_type}_{i}'
        component_ids.append(subtask_id)
        subtasks.append(Subtask(task_id=subtask_id, parent_task_id=parent_id, specification=f'{spec}\n\nFOCUS: Implement the {block_type} logic as a helper function.', constraints=_preserve_meta_task_type(task, task.get('constraints', {}))))
    if component_ids:
        compose_id = f'{parent_id}-compose'
        subtasks.append(Subtask(task_id=compose_id, parent_task_id=parent_id, specification=f'{spec}\n\nCOMPOSITION: Compose the helper functions into the final solution.', constraints=_preserve_meta_task_type(task, task.get('constraints', {})), depends_on=component_ids))
    return subtasks

def decompose_task(task: dict[str, Any], failures: list[FuzzFailure], config: dict[str, Any], code_a: str='', code_b: str='', depth: int=0) -> DecompositionResult:
    """Analyze divergence patterns and decompose the task into subtasks.

    Strategy selection:
    1. If failures cluster into distinct input classes -> edge_case isolation
    2. If code has multiple logical blocks -> function split
    3. Fallback -> edge case isolation with general category
    """
    decomp_cfg = config.get('decomposition', {})
    max_subtasks = decomp_cfg.get('max_subtasks', 5)
    max_depth = decomp_cfg.get('max_depth', 3)
    parent_id = task.get('task_id', 'unknown')
    if depth >= max_depth:
        review_id = f'{parent_id}-reviewed'
        if len(review_id) > 150:
            import hashlib
            review_id = f'{parent_id[:100]}-{hashlib.md5(review_id.encode()).hexdigest()[:8]}-rev'
        return DecompositionResult(parent_task_id=parent_id, subtasks=[Subtask(task_id=review_id, parent_task_id=parent_id, specification=_build_context_prefix(task) + _extract_specification(task) + '\n\n[PLANNER REVIEW INITIATED]: The previous agents entered a pathological, degenerate failure mode and reached the maximum decomposition depth without achieving functional equivalence.\nYou must carefully review the specification and your combined instructions. Make a small conceptual tweak or clarification to your implementation strategy that does NOT functionally change the requirement, but will break you out of the previous degenerate failure mode.', constraints=_preserve_meta_task_type(task, task.get('constraints', {})), depth=depth + 1)], strategy='planner_review', reason=f'Max decomposition depth ({max_depth}) reached. Queuing for planner review.')
    failure_categories = _classify_failures(failures)
    logger.info('Failure categories for %s: %s', parent_id, {k: len(v) for k, v in failure_categories.items()})
    applicable, guard_reason = is_structural_decomposition_applicable(task, failure_categories, depth, max_depth)
    if not applicable:
        logger.info('decomposer guard short-circuit: task_id=%s reason=%s', parent_id, guard_reason)
        review_id = f'{parent_id}-reviewed'
        if len(review_id) > 150:
            import hashlib
            review_id = f'{parent_id[:100]}-{hashlib.md5(review_id.encode()).hexdigest()[:8]}-rev'
        review_spec = f'[PLANNER REVIEW INITIATED — structural decomposition skipped: {guard_reason}]\n' + _build_context_prefix(task) + _extract_specification(task)
        return DecompositionResult(parent_task_id=parent_id, subtasks=[Subtask(task_id=review_id, parent_task_id=parent_id, specification=review_spec, constraints=_preserve_meta_task_type(task, task.get('constraints', {})), depth=depth + 1)], strategy='planner_review', reason=f'Structural decomposition guard fired: {guard_reason}')
    if len(failure_categories) >= 2:
        subtasks = _decompose_by_edge_cases(task, failure_categories, max_subtasks)
        if subtasks:
            for st in subtasks:
                st.depth = depth + 1
            return DecompositionResult(parent_task_id=parent_id, subtasks=subtasks, strategy='edge_case', reason=f'Failures cluster into {len(failure_categories)} categories: {', '.join(failure_categories.keys())}')
    if code_a:
        subtasks = _decompose_by_function_split(task, code_a, code_b, max_subtasks)
        if subtasks:
            for st in subtasks:
                st.depth = depth + 1
            return DecompositionResult(parent_task_id=parent_id, subtasks=subtasks, strategy='function_split', reason='Code contains multiple logical blocks suitable for decomposition')
    subtasks = _decompose_by_edge_cases(task, failure_categories, max_subtasks)
    if subtasks:
        for st in subtasks:
            st.depth = depth + 1
        return DecompositionResult(parent_task_id=parent_id, subtasks=subtasks, strategy='edge_case', reason='Fallback edge-case decomposition')
    retry_id = f'{parent_id}-retry'
    return DecompositionResult(parent_task_id=parent_id, subtasks=[Subtask(task_id=retry_id, parent_task_id=parent_id, specification=_build_context_prefix(task) + _extract_specification(task) + '\n\nIMPORTANT: Previous attempts at this task produced divergent results. Pay extra attention to edge cases and specification ambiguity.', constraints=_preserve_meta_task_type(task, task.get('constraints', {})), depth=depth + 1)], strategy='retry', reason='No decomposition pattern found; retrying with emphasis on edge cases')

def enqueue_subtasks(subtasks: list[Subtask], state_dir: Path) -> None:
    """Write subtask JSON files to the task queue."""
    tasks_dir = state_dir / 'tasks'
    tasks_dir.mkdir(parents=True, exist_ok=True)
    for subtask in subtasks:
        task_data = {'task_id': subtask.task_id, 'parent_task': subtask.parent_task_id, 'specification': subtask.specification, 'constraints': subtask.constraints, 'depends_on': subtask.depends_on, 'depth': subtask.depth}
        # P3 (C9.15): re-hoist the rebuild flags _preserve_meta_task_type carried into
        # constraints up to the TOP level, where the orchestrator/diff_fuzzer read them
        # (task.get('fuzz_str_ascii') / task.get('partial_edit')).
        if isinstance(subtask.constraints, dict):
            for _flag in ('fuzz_str_ascii', 'partial_edit'):
                if subtask.constraints.get(_flag):
                    task_data[_flag] = subtask.constraints[_flag]
        path = tasks_dir / f'{subtask.task_id}.json'
        with open(path, 'w') as f:
            json.dump(task_data, f, indent=2, ensure_ascii=False)
            f.write('\n')
    logger.info('Enqueued %d subtasks for %s', len(subtasks), subtasks[0].parent_task_id if subtasks else '?')

def update_parent_state(state_dir: Path, parent_task_id: str, subtask_ids: list[str]) -> None:
    """Update STATE.json to reflect decomposition."""
    from harness.state import locked_read_modify_write

    def _modifier(state: dict[str, Any]) -> dict[str, Any]:
        state['phase'] = 'decomposition'
        state['decomposed'] = True
        state['children'] = subtask_ids
        return state
    locked_read_modify_write(_modifier, state_dir)
    logger.info('Updated state for decomposition of %s -> %s', parent_task_id, subtask_ids)

def test_preserve_meta_task_type_from_task_level():
    """Test that meta_task_type is preserved from task-level field."""
    parent_task = {'task_id': 'test', 'meta_task_type': 'planner_tooling', 'specification': 'test'}
    constraints = {}
    result = _preserve_meta_task_type(parent_task, constraints)
    assert result.get('meta_task_type') == 'planner_tooling'

def test_preserve_meta_task_type_from_constraints_level():
    """Test that meta_task_type is preserved from constraints-level field."""
    parent_task = {'task_id': 'test', 'specification': 'test', 'constraints': {'meta_task_type': 'sandbox_infra'}}
    constraints = {}
    result = _preserve_meta_task_type(parent_task, constraints)
    assert result.get('meta_task_type') == 'sandbox_infra'

def test_preserve_meta_task_type_precedence_task_over_constraints():
    """Test that task-level meta_task_type takes precedence over constraints-level."""
    parent_task = {'task_id': 'test', 'meta_task_type': 'planner_tooling', 'specification': 'test', 'constraints': {'meta_task_type': 'sandbox_infra'}}
    constraints = {}
    result = _preserve_meta_task_type(parent_task, constraints)
    assert result.get('meta_task_type') == 'planner_tooling'

def test_preserve_meta_task_type_when_absent():
    """Test that missing meta_task_type is handled gracefully."""
    parent_task = {'task_id': 'test', 'specification': 'test', 'constraints': {}}
    constraints = {}
    result = _preserve_meta_task_type(parent_task, constraints)
    assert 'meta_task_type' not in result

def test_preserve_meta_task_type_preserves_other_constraints():
    """Test that other constraint fields are preserved."""
    parent_task = {'task_id': 'test', 'meta_task_type': 'data_model', 'specification': 'test'}
    constraints = {'function_signature': 'def foo(x): pass', 'max_lines': 100}
    result = _preserve_meta_task_type(parent_task, constraints)
    assert result.get('meta_task_type') == 'data_model'
    assert result.get('function_signature') == 'def foo(x): pass'
    assert result.get('max_lines') == 100

def test_edge_case_decomposition_preserves_type():
    """Test that edge-case decomposition preserves meta_task_type in all subtasks."""
    parent_task = {'task_id': 'test-edge', 'meta_task_type': 'planner_tooling', 'specification': 'Test specification'}
    failures = [FuzzFailure([], {}, 'result_a', 'result_b', 'reason'), FuzzFailure([], {}, 'result_a', 'result_b', 'reason'), FuzzFailure([], {}, 'result_a', 'result_b', 'reason'), FuzzFailure([], {}, 'result_a', 'result_b', 'reason')]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent_task, failures, config, depth=0)
    assert all((st.constraints.get('meta_task_type') == 'planner_tooling' for st in result.subtasks)), 'meta_task_type not preserved in edge-case decomposition'

def test_function_split_decomposition_preserves_type():
    """Test that function-split decomposition preserves meta_task_type."""
    code_with_blocks = '\ndef process(items):\n    if len(items) > 0:\n        filtered = [x for x in items if x > 0]\n    for item in filtered:\n        print(item)\n    return filtered\n'
    parent_task = {'task_id': 'test-split', 'meta_task_type': 'harness_plumbing', 'specification': 'Test specification'}
    failures = [FuzzFailure([], {}, 'result_a', 'result_b', 'reason')]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent_task, failures, config, code_a=code_with_blocks, code_b=code_with_blocks, depth=0)
    assert all((st.constraints.get('meta_task_type') == 'harness_plumbing' for st in result.subtasks)), 'meta_task_type not preserved in function-split decomposition'

def test_fallback_retry_preserves_meta_task_type():
    """Test that fallback retry path preserves meta_task_type."""
    parent_task = {'task_id': 'test-retry', 'meta_task_type': 'orchestration', 'specification': 'Test specification', 'constraints': {}}
    failures = [FuzzFailure([], {}, 'result_a', 'result_b', 'reason')]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent_task, failures, config, depth=0)
    assert all((st.constraints.get('meta_task_type') == 'orchestration' for st in result.subtasks)), 'meta_task_type not preserved in fallback retry'

def test_max_depth_planner_review_preserves_meta_task_type():
    """Test that max-depth planner review preserves meta_task_type."""
    parent_task = {'task_id': 'test-maxdepth', 'meta_task_type': 'state_machine', 'specification': 'Test specification'}
    failures = [FuzzFailure([], {}, 'result_a', 'result_b', 'reason')]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent_task, failures, config, depth=3)
    assert all((st.constraints.get('meta_task_type') == 'state_machine' for st in result.subtasks)), 'meta_task_type not preserved in max-depth planner review'

def test_guard_fail_planner_review_preserves_meta_task_type():
    """Test that guard-fail planner review preserves meta_task_type."""
    parent_task = {'task_id': 'test-guard', 'meta_task_type': 'sandbox_infra', 'specification': 'Test specification'}
    failures = [FuzzFailure([], {}, 'result_a', 'result_b', 'reason')]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent_task, failures, config, depth=0)
    assert all((st.constraints.get('meta_task_type') == 'sandbox_infra' for st in result.subtasks)), 'meta_task_type not preserved in guard-fail planner review'

def test_all_subtasks_have_meta_task_type_from_parent():
    """Property test: all generated subtasks must have meta_task_type from parent."""
    for meta_type in ['planner_tooling', 'sandbox_infra', 'data_model', 'mcp_plumbing']:
        parent_task = {'task_id': f'test-{meta_type}', 'meta_task_type': meta_type, 'specification': 'Test specification'}
        failures = [FuzzFailure([], {}, 'result_a', 'result_b', 'reason'), FuzzFailure([], {}, 'result_a', 'result_b', 'reason')]
        config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
        result = decompose_task(parent_task, failures, config, depth=0)
        for subtask in result.subtasks:
            assert subtask.constraints.get('meta_task_type') == meta_type, f'Subtask {subtask.task_id} missing meta_task_type={meta_type}'

def test_multi_level_decomposition_preserves_ancestor_type():
    """Test that grandchild subtasks preserve ancestor meta_task_type."""
    parent_task = {'task_id': 'root', 'meta_task_type': 'io_adapter', 'specification': 'Test specification'}
    failures = [FuzzFailure([], {}, 'result_a', 'result_b', 'reason'), FuzzFailure([], {}, 'result_a', 'result_b', 'reason')]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result1 = decompose_task(parent_task, failures, config, depth=0)
    assert all((st.constraints.get('meta_task_type') == 'io_adapter' for st in result1.subtasks)), 'First level subtasks missing meta_task_type'
    if result1.subtasks:
        child_task = {'task_id': result1.subtasks[0].task_id, 'specification': result1.subtasks[0].specification, 'constraints': result1.subtasks[0].constraints}
        result2 = decompose_task(child_task, failures, config, depth=1)
        assert all((st.constraints.get('meta_task_type') == 'io_adapter' for st in result2.subtasks)), 'Second level subtasks missing ancestor meta_task_type'

def test_existing_edge_case_decomposition_behavior_unchanged():
    """Regression test: verify edge-case decomposition still produces correct structure."""
    parent_task = {'task_id': 'regression-test', 'specification': 'Test specification', 'constraints': {'function_signature': 'def foo(x): pass'}}
    failures = [FuzzFailure([], {}, 'result_a', 'result_b', 'reason'), FuzzFailure([], {}, 'result_a', 'result_b', 'reason'), FuzzFailure([], {}, 'result_a', 'result_b', 'reason')]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent_task, failures, config, depth=0)
    assert result.parent_task_id == 'regression-test'
    assert len(result.subtasks) > 0, 'No subtasks generated'
    assert result.strategy in ['edge_case', 'function_split', 'retry']
    for subtask in result.subtasks:
        assert 'function_signature' in subtask.constraints
        assert subtask.constraints['function_signature'] == 'def foo(x): pass'