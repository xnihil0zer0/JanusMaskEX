import json
import os
import re
from dataclasses import dataclass
from typing import Dict
from typing import List
from typing import Any
from typing import Union
from pathlib import Path
from harness.planner.taxonomies import META_TASK_TYPES
PRIORITY_CANONICAL = {'critical', 'high', 'medium', 'low'}


def _is_wiring_oracle(verification_command: Any) -> bool:
    """A wiring oracle is recognised when ``verification_command`` names a pytest
    path whose filename stem ends with ``_wired`` (e.g.
    ``tests/harness/test_newmod_wired.py``). Scan whitespace-separated tokens for
    a ``.py`` path and inspect its filename stem."""
    if not isinstance(verification_command, str):
        return False
    for token in verification_command.split():
        if not token.endswith('.py'):
            continue
        stem = token.rsplit('/', 1)[-1].rsplit('\\', 1)[-1][:-len('.py')]
        if stem.endswith('_wired'):
            return True
    return False

_PURE_EDIT_META_TASK_TYPES = {'refactor', 'logging_observability', 'docs_writing'}

def _is_module_creating(task: Any) -> bool:
    """A leaf is MODULE-CREATING when its ``files_touched`` contains a ``.py``
    path that is NOT under a ``tests/`` directory, is NOT already present on
    disk, AND its ``meta_task_type`` is not a pure-edit type (``refactor``,
    ``logging_observability``, ``docs_writing`` and any ``test_*`` type are
    exempt).

    Existence-aware: a non-test ``.py`` that already exists on disk (resolved
    against the repo root) is an EDIT and creates nothing, so it does not make
    the task module-creating. Only an absent path (including external /
    out-of-repo working_dir builds) makes the task module-creating (fail-safe:
    unknown/absent => creating)."""
    if not isinstance(task, dict):
        return False
    meta_task_type = task.get('meta_task_type')
    if isinstance(meta_task_type, str):
        if meta_task_type in _PURE_EDIT_META_TASK_TYPES or meta_task_type.startswith('test_'):
            return False
    files_touched = task.get('files_touched', [])
    if not isinstance(files_touched, list):
        return False
    repo_root = Path(__file__).resolve().parents[2]
    for path in files_touched:
        if not isinstance(path, str) or not path.endswith('.py'):
            continue
        if 'tests/' in path.replace('\\', '/'):
            continue
        p = Path(path)
        resolved = p if p.is_absolute() else (repo_root / p)
        if not resolved.exists():
            return True
    return False
def _valid_mutation_module(v: Any) -> bool:
    """A2: a ``mutation_target`` must be a bare dotted module name (the
    module-under-test), e.g. ``harness.symbol_ledger``. Mirrors the
    ``_valid_mut_module`` accepted by the auto-commit mutation gate
    (orchestrator.py): reject path-like values, parent-traversal, explicit
    ``.py`` extensions, and anything that is not dotted identifiers."""
    if not isinstance(v, str) or not v:
        return False
    if '/' in v or '\\' in v or '..' in v or v.endswith('.py'):
        return False
    return re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*', v) is not None

@dataclass(frozen=True, order=True)
class PlanViolation:
    code: str
    path: str
    message: str
    severity: str = 'error'

def check_missing_fields(task: Dict[str, Any], path_prefix: str) -> List[PlanViolation]:
    violations = []
    top_level_reqs = ['task_id', 'title', 'meta_task_type', 'priority', 'dependencies', 'files_touched', 'acceptance_criteria', 'spec_author', 'estimated_complexity', 'verification_command']
    for field in top_level_reqs:
        if field not in task:
            violations.append(PlanViolation('missing_field', f'{path_prefix}.{field}', f'Missing required field {field}'))
    vcmd = task.get('verification_command')
    if 'verification_command' in task and (not isinstance(vcmd, str) or not vcmd.strip()):
        violations.append(PlanViolation('invalid_verification_command', f'{path_prefix}.verification_command', 'verification_command must be a non-empty string'))
    spec = task.get('spec', {})
    if not isinstance(spec, dict):
        violations.append(PlanViolation('missing_field', f'{path_prefix}.spec', 'spec must be an object'))
        spec = {}
    spec_reqs = ['objective', 'functional_requirements', 'interfaces', 'edge_cases', 'non_goals', 'implementation_notes']
    for field in spec_reqs:
        if field not in spec:
            violations.append(PlanViolation('missing_field', f'{path_prefix}.spec.{field}', f'Missing required field spec.{field}'))
    test_spec = task.get('test_spec', {})
    if not isinstance(test_spec, dict):
        violations.append(PlanViolation('missing_field', f'{path_prefix}.test_spec', 'test_spec must be an object'))
        test_spec = {}
    test_spec_reqs = ['unit_tests', 'integration_tests', 'property_tests', 'regression_tests', 'minimum_test_count', 'test_data_requirements']
    for field in test_spec_reqs:
        if field not in test_spec:
            violations.append(PlanViolation('missing_field', f'{path_prefix}.test_spec.{field}', f'Missing required field test_spec.{field}'))
    budget = task.get('token_budget_ratio', {})
    if not isinstance(budget, dict):
        violations.append(PlanViolation('missing_field', f'{path_prefix}.token_budget_ratio', 'token_budget_ratio must be an object'))
        budget = {}
    for field in ['implementation_tokens', 'test_tokens', 'note']:
        if field not in budget:
            violations.append(PlanViolation('missing_field', f'{path_prefix}.token_budget_ratio.{field}', f'Missing required field token_budget_ratio.{field}'))
    attr = task.get('attribution_metadata', {})
    if not isinstance(attr, dict):
        violations.append(PlanViolation('missing_field', f'{path_prefix}.attribution_metadata', 'attribution_metadata must be an object'))
        attr = {}
    for field in ['proposed_by', 'reconciled', 'diff_resolution']:
        if field not in attr:
            violations.append(PlanViolation('missing_field', f'{path_prefix}.attribution_metadata.{field}', f'Missing required field attribution_metadata.{field}'))
    return violations

def _sensitive_glob_violations(task: dict, path_prefix: str) -> List[PlanViolation]:
    """Reject a non-``harness_self_fix`` task that lists a path under
    ``_SENSITIVE_APPLY_GLOBS`` (``harness/**``, ``config/**``, ``scripts/**``,
    ``services/**``) in ``files_touched``.

    Such a task can NEVER commit that path: ``_enforce_apply_scope`` refuses the
    sensitive-glob write at accept, dead-ending the leaf with
    ``auto_commit_failed`` retries to exhaustion. So the plan is rejected at
    planning time with a clear, path-naming ``sensitive_files_touched``
    violation instead.

    ``harness_self_fix`` tasks are legitimately allowed to touch sensitive globs
    (they commit via the decision file) and are exempt — the helper returns
    ``[]`` regardless of ``files_touched`` contents. Missing / ``None`` /
    non-list ``files_touched`` and non-``str`` entries are tolerated and skipped;
    the helper never raises.
    """
    import fnmatch
    if not isinstance(task, dict):
        return []
    if task.get('meta_task_type') == 'harness_self_fix':
        return []
    files_touched = task.get('files_touched')
    if not isinstance(files_touched, list):
        return []
    try:
        from harness.git_integration import _SENSITIVE_APPLY_GLOBS as _GLOBS
    except Exception:
        _GLOBS = ('harness/**', 'config/**', 'scripts/**', 'services/**')
    violations: List[PlanViolation] = []
    for entry in files_touched:
        if not isinstance(entry, str):
            continue
        norm = entry.replace('\\', '/')
        if any((fnmatch.fnmatch(norm, glob) for glob in _GLOBS)):
            violations.append(PlanViolation('sensitive_files_touched', f'{path_prefix}.files_touched', f'files_touched lists sensitive path {entry!r}: a non-harness_self_fix task can never commit a path under _SENSITIVE_APPLY_GLOBS ({', '.join(_GLOBS)}) — _enforce_apply_scope refuses the write at accept, so the plan is rejected at planning time'))
    return violations
def validate_plan(plan: Union[Dict[str, Any], str, Path]) -> List[PlanViolation]:
    if isinstance(plan, (str, Path)):
        try:
            with open(plan, 'r', encoding='utf-8') as f:
                plan = json.load(f)
        except Exception as e:
            return [PlanViolation('parse_error', 'plan', str(e))]
    if not isinstance(plan, dict):
        return [PlanViolation('invalid_structure', 'plan', 'Plan must be a JSON object')]
    if plan.get('plan_kind') == 'epic':
        return validate_epic_plan(plan)
    tasks = plan.get('tasks', [])
    if not isinstance(tasks, list):
        return [PlanViolation('invalid_structure', 'plan.tasks', 'tasks must be a list')]
    violations = []
    seen_task_ids = set()
    graph = {}
    for i, task in enumerate(tasks):
        if not isinstance(task, dict):
            violations.append(PlanViolation('invalid_structure', f'tasks[{i}]', 'Task must be an object'))
            continue
        task_id = task.get('task_id')
        path_prefix = f'tasks[{i}](id={task_id})' if task_id else f'tasks[{i}]'
        if task_id:
            if task_id in seen_task_ids:
                violations.append(PlanViolation('duplicate_task_id', path_prefix, f'Duplicate task_id: {task_id}'))
            seen_task_ids.add(task_id)
            graph[task_id] = task.get('dependencies', [])
            if not isinstance(graph[task_id], list):
                graph[task_id] = []
        violations.extend(check_missing_fields(task, path_prefix))
        violations.extend(_sensitive_glob_violations(task, path_prefix))
        meta_task_type = task.get('meta_task_type')
        if not isinstance(meta_task_type, str) or not meta_task_type:
            violations.append(PlanViolation('missing_meta_task_type', f'{path_prefix}.meta_task_type', 'meta_task_type must be a non-empty string from the canonical taxonomy'))
        elif meta_task_type not in META_TASK_TYPES:
            violations.append(PlanViolation('unknown_meta_task_type', f'{path_prefix}.meta_task_type', f'Unknown meta_task_type: {meta_task_type}'))
        # A2: a test_authoring task is forced through the auto-commit non-vacuity
        # gate, which fail-closed-rejects it unless it declares a mutation_target
        # (bare dotted module-under-test) or a non-empty mutations[]. Catch the
        # omission here at planning time instead of late at the mutation gate.
        if meta_task_type == 'test_authoring':
            mut_target = task.get('mutation_target')
            mutations = task.get('mutations')
            has_mutations = isinstance(mutations, list) and len(mutations) > 0
            if mut_target is not None:
                if not _valid_mutation_module(mut_target):
                    violations.append(PlanViolation('invalid_mutation_target', f'{path_prefix}.mutation_target', f'mutation_target must be a bare dotted module name (the module-under-test), got {mut_target!r}'))
            elif not has_mutations:
                violations.append(PlanViolation('missing_mutation_target', f'{path_prefix}.mutation_target', "test_authoring task must declare a 'mutation_target' (bare dotted module-under-test) or a non-empty 'mutations[]' so the non-vacuity gate can fail-detect"))
        # Wiring-oracle requirement: a leaf that creates a NEW module must declare a
        # wiring oracle (a *_wired test named in its verification_command) so the
        # module is proven reachable from a live importer. Reject pre-spawn otherwise.
        if _is_module_creating(task) and not _is_wiring_oracle(task.get('verification_command')):
            # Paired-auto-oracle exemption: a module-creating leaf whose vcmd is a
            # smoke check is EXEMPT when the SAME plan carries a test_authoring
            # oracle whose mutation_target (dotted) resolves to one of this leaf's
            # non-test .py files. The auto-authored, mutation-gated oracle is the
            # module's wiring/contract proof (impl-first ordering makes a *_wired
            # vcmd structurally impossible here).
            _created = {
                p.replace('\\', '/')
                for p in (task.get('files_touched') or [])
                if isinstance(p, str) and p.endswith('.py') and 'tests/' not in p.replace('\\', '/')
            }
            _has_paired_oracle = any(
                isinstance(o, dict)
                and o.get('meta_task_type') == 'test_authoring'
                and isinstance(o.get('mutation_target'), str)
                and o.get('mutation_target')
                and (o['mutation_target'].replace('.', '/') + '.py') in _created
                for o in tasks
            )
            if not _has_paired_oracle:
                violations.append(PlanViolation('missing_wiring_oracle', f'{path_prefix}.verification_command', 'a leaf that creates a new module must declare a wiring oracle (a *_wired test named in its verification_command) so the module is proven reachable from a live importer'))
        priority = task.get('priority')
        if priority is not None:
            if not isinstance(priority, str):
                violations.append(PlanViolation('invalid_priority_type', f'{path_prefix}.priority', f'priority must be lowercase str from {{critical,high,medium,low}}, got {type(priority).__name__}'))
            elif priority not in PRIORITY_CANONICAL:
                violations.append(PlanViolation('invalid_priority_encoding', f'{path_prefix}.priority', f'priority {priority!r} not in canonical {{critical,high,medium,low}} — run scripts/impl_normalize_priority.py to fix'))
        spec_author = task.get('spec_author')
        attr = task.get('attribution_metadata', {})
        if isinstance(attr, dict):
            proposed_by = attr.get('proposed_by')
            if spec_author is not None and proposed_by is None:
                violations.append(PlanViolation('attribution_mismatch', path_prefix, 'spec_author is non-null but proposed_by is null'))
        is_test = False
        if isinstance(meta_task_type, str) and meta_task_type.startswith('test_'):
            is_test = True
        if not is_test:
            budget = task.get('token_budget_ratio', {})
            if isinstance(budget, dict):
                impl_tokens = budget.get('implementation_tokens', 0)
                test_tokens = budget.get('test_tokens', 0)
                if isinstance(impl_tokens, (int, float)) and isinstance(test_tokens, (int, float)):
                    if impl_tokens == 0:
                        if test_tokens <= 0:
                            violations.append(PlanViolation('test_ratio_violation', f'{path_prefix}.token_budget_ratio', 'test_tokens must be > 0 when impl_tokens == 0'))
                    elif test_tokens < 1.5 * impl_tokens:
                        violations.append(PlanViolation('test_ratio_violation', f'{path_prefix}.token_budget_ratio', 'test_tokens must be >= 1.5 * impl_tokens'))
            spec = task.get('spec', {})
            test_spec = task.get('test_spec', {})
            if isinstance(spec, dict) and isinstance(test_spec, dict):
                frs = spec.get('functional_requirements', [])
                unit_tests = test_spec.get('unit_tests', [])
                if isinstance(frs, list) and isinstance(unit_tests, list):
                    if len(unit_tests) < len(frs):
                        violations.append(PlanViolation('insufficient_unit_tests', f'{path_prefix}.test_spec.unit_tests', 'len(unit_tests) >= len(functional_requirements)'))
                integration_tests = test_spec.get('integration_tests', [])
                non_goals = spec.get('non_goals', [])
                if isinstance(integration_tests, list) and isinstance(non_goals, list):
                    if len(integration_tests) == 0:
                        excused = any(('integration' in str(ng).lower() for ng in non_goals))
                        if not excused:
                            violations.append(PlanViolation('missing_integration_test', f'{path_prefix}.test_spec.integration_tests', 'At least one integration_test required unless excused in non_goals'))
                edge_cases = spec.get('edge_cases', [])
                prop_tests = test_spec.get('property_tests', [])
                reg_tests = test_spec.get('regression_tests', [])
                if isinstance(edge_cases, list) and isinstance(prop_tests, list) and isinstance(reg_tests, list):
                    needed = min(2, len(edge_cases))
                    if len(prop_tests) + len(reg_tests) < needed:
                        violations.append(PlanViolation('missing_edge_case_tests', f'{path_prefix}.test_spec', 'At least two edge_cases must be reflected in regression_tests or property_tests'))
                min_count = test_spec.get('minimum_test_count', 0)
                if isinstance(frs, list) and isinstance(min_count, (int, float)):
                    if min_count < 1.5 * len(frs):
                        violations.append(PlanViolation('insufficient_total_tests', f'{path_prefix}.test_spec.minimum_test_count', 'minimum_test_count >= 1.5 * len(functional_requirements)'))
    visited = set()
    path = []
    path_set = set()

    def dfs(node):
        if node in path_set:
            idx = path.index(node)
            cycle = path[idx:] + [node]
            violations.append(PlanViolation('dependency_cycle', 'plan.tasks', f'Cycle: {' -> '.join(cycle)}'))
            return True
        if node in visited:
            return False
        visited.add(node)
        path.append(node)
        path_set.add(node)
        found_cycle = False
        for neighbor in graph.get(node, []):
            if dfs(neighbor):
                found_cycle = True
        path.pop()
        path_set.remove(node)
        return found_cycle
    found_cycles_nodes = set()

    def dfs2(node, current_path):
        if node in current_path:
            idx = current_path.index(node)
            cycle = current_path[idx:] + [node]
            cycle_key = tuple(sorted(current_path[idx:]))
            if cycle_key not in found_cycles_nodes:
                found_cycles_nodes.add(cycle_key)
                violations.append(PlanViolation('dependency_cycle', 'plan.tasks', f'Cycle: {' -> '.join(cycle)}'))
            return
        if node in visited:
            return
        current_path.append(node)
        for neighbor in graph.get(node, []):
            dfs2(neighbor, current_path)
        current_path.pop()
        visited.add(node)
    visited.clear()
    for node in graph:
        if node not in visited:
            dfs2(node, [])
    return violations
_SHA256_HEX_CHARS = set('0123456789abcdef')

def validate_child_brief_plan(plan: Union[Dict[str, Any], str, Path]) -> List[PlanViolation]:
    """Validate the child-brief schema for epic-decomposition plans.

    Sibling of validate_plan that enforces the brief-level schema rather than
    the leaf-task schema. Each brief carries slug, title, scope, non_goals,
    inputs, deliverables, plus optional dependencies (a list of sibling slugs)
    and interfaces (a string). Returns an empty list when the plan is
    well-formed. Purely additive — reuses the frozen PlanViolation dataclass,
    requires/checks no leaf-task field, and is not wired into any call site.
    """
    if isinstance(plan, (str, Path)):
        try:
            with open(plan, 'r', encoding='utf-8') as f:
                plan = json.load(f)
        except Exception as e:
            return [PlanViolation('parse_error', 'plan', str(e))]
    if not isinstance(plan, dict):
        return [PlanViolation('invalid_structure', 'plan', 'Plan must be a JSON object')]
    children = plan.get('child_briefs', [])
    if not isinstance(children, list):
        return [PlanViolation('invalid_structure', 'plan.child_briefs', 'child_briefs must be a list')]
    violations: List[PlanViolation] = []
    if len(children) == 0:
        violations.append(PlanViolation('empty_child_briefs', 'plan.child_briefs', 'child_briefs must contain at least one brief'))
    required_fields = ['slug', 'title', 'scope', 'non_goals', 'inputs', 'deliverables']
    valid_slugs = set()
    for i, entry in enumerate(children):
        prefix = f'child_briefs[{i}]'
        if not isinstance(entry, dict):
            violations.append(PlanViolation('invalid_structure', prefix, 'Child brief must be an object'))
            continue
        for field in required_fields:
            if field not in entry:
                violations.append(PlanViolation('missing_field', f'{prefix}.{field}', f'Missing required field {field}'))
        if 'slug' in entry:
            slug = entry.get('slug')
            if not isinstance(slug, str) or not slug.strip():
                violations.append(PlanViolation('invalid_slug', f'{prefix}.slug', 'slug must be a non-empty string'))
            elif slug in valid_slugs:
                violations.append(PlanViolation('duplicate_slug', f'{prefix}.slug', f'Duplicate slug: {slug}'))
            else:
                valid_slugs.add(slug)
        if 'dependencies' in entry and (not isinstance(entry.get('dependencies'), list)):
            violations.append(PlanViolation('invalid_dependencies', f'{prefix}.dependencies', 'dependencies must be a list'))
        if 'interfaces' in entry and (not isinstance(entry.get('interfaces'), str)):
            violations.append(PlanViolation('invalid_interfaces', f'{prefix}.interfaces', 'interfaces must be a string'))
    for i, entry in enumerate(children):
        if not isinstance(entry, dict):
            continue
        prefix = f'child_briefs[{i}]'
        deps = entry.get('dependencies')
        if not isinstance(deps, list):
            continue
        for dep in deps:
            if dep not in valid_slugs:
                violations.append(PlanViolation('unknown_dependency', f'{prefix}.dependencies', f'Unknown dependency: {dep!r}'))
    return violations
def validate_epic_plan(plan: Union[Dict[str, Any], str, Path]) -> List[PlanViolation]:
    """Validate a persisted epic plan record (plan_kind='epic').

    Sibling of validate_plan / validate_child_brief_plan that validates the
    epic-record schema: the brief-level structure (delegated to
    validate_child_brief_plan) plus the epic-record-level fields plan_kind,
    child_slugs (each must match a child_briefs slug) and epic_slug. Returns
    list[PlanViolation] (empty when well-formed); never raises on malformed
    input. Reuses the frozen PlanViolation dataclass.
    """
    if isinstance(plan, (str, Path)):
        try:
            with open(plan, 'r', encoding='utf-8') as f:
                plan = json.load(f)
        except Exception as e:
            return [PlanViolation('parse_error', 'plan', str(e))]
    if not isinstance(plan, dict):
        return [PlanViolation('invalid_structure', 'plan', 'Plan must be a JSON object')]
    violations: List[PlanViolation] = []
    if plan.get('plan_kind') != 'epic':
        violations.append(PlanViolation('invalid_plan_kind', 'plan.plan_kind', "epic plan record must declare plan_kind == 'epic'"))
    violations.extend(validate_child_brief_plan(plan))
    valid_slugs = set()
    children = plan.get('child_briefs', [])
    if isinstance(children, list):
        for entry in children:
            if isinstance(entry, dict):
                slug = entry.get('slug')
                if isinstance(slug, str) and slug.strip():
                    valid_slugs.add(slug)
    if 'child_slugs' in plan:
        child_slugs = plan.get('child_slugs')
        if not isinstance(child_slugs, list):
            violations.append(PlanViolation('invalid_structure', 'plan.child_slugs', 'child_slugs must be a list'))
        else:
            for s in child_slugs:
                if not isinstance(s, str) or not s.strip():
                    violations.append(PlanViolation('invalid_slug', 'plan.child_slugs', 'child_slug must be a non-empty string'))
                elif s not in valid_slugs:
                    violations.append(PlanViolation('slug_mismatch', 'plan.child_slugs', f'child_slug {s!r} has no matching child brief'))
    if 'epic_slug' in plan:
        epic_slug = plan.get('epic_slug')
        if not isinstance(epic_slug, str) or not epic_slug.strip():
            violations.append(PlanViolation('invalid_epic_slug', 'plan.epic_slug', 'epic_slug must be a non-empty string'))
    return violations
def validate_draft(plan: Union[Dict[str, Any], str, Path], mode: str='leaf') -> List[PlanViolation]:
    """Unified entrypoint for draft validation that routes by ``mode``.

    Purely additive dispatcher sitting alongside validate_plan and
    validate_child_brief_plan. When ``mode == 'epic'`` the plan is validated
    against the child-brief schema via validate_child_brief_plan; for the
    'leaf' mode, the default, ``None``, or any other unexpected value, it falls
    back to leaf validation via validate_plan. Plan format issues (parse
    errors, non-dict input, etc.) are handled gracefully by the delegate
    validators, which return a list of PlanViolation rather than raising.
    """
    if mode == 'epic':
        return validate_child_brief_plan(plan)
    return validate_plan(plan)
def validate_plan_wrapper(plan):
    """Validate schema v2.1 wrapper fields (source_brief_path + source_brief_sha256).

    Returns list[PlanViolation] (empty when wrapper is well-formed). Decoupled from
    validate_plan so that wrapper-level checks can be run independently — e.g., when
    the planner writes a plan and wants to fail fast on missing traceability metadata.

    D8 addition: hard-raises ValueError when any task in plan['tasks'] is missing
    a non-empty string verification_command, mirroring the orchestrator-side V1
    gate at _auto_commit_accepted so bad plans cannot reach the dispatch queue.
    Predicate matches check_missing_fields lines 22-24 exactly.
    """
    if isinstance(plan, (str, Path)):
        try:
            with open(plan, 'r', encoding='utf-8') as f:
                plan = json.load(f)
        except Exception as e:
            return [PlanViolation('parse_error', 'plan', str(e))]
    if not isinstance(plan, dict):
        return [PlanViolation('invalid_structure', 'plan', 'Plan must be a JSON object')]
    violations = []
    sbp = plan.get('source_brief_path')
    if sbp is None or sbp == '':
        violations.append(PlanViolation('missing_wrapper_field', 'plan.source_brief_path', 'source_brief_path required for schema v2.1 traceability'))
    elif not isinstance(sbp, str):
        violations.append(PlanViolation('invalid_wrapper_type', 'plan.source_brief_path', f'source_brief_path must be str, got {type(sbp).__name__}'))
    sha = plan.get('source_brief_sha256')
    if sha is None or sha == '':
        violations.append(PlanViolation('missing_wrapper_field', 'plan.source_brief_sha256', 'source_brief_sha256 required for schema v2.1 traceability'))
    elif not isinstance(sha, str):
        violations.append(PlanViolation('invalid_wrapper_type', 'plan.source_brief_sha256', f'source_brief_sha256 must be str, got {type(sha).__name__}'))
    elif len(sha) != 64 or not all((c in _SHA256_HEX_CHARS for c in sha.lower())):
        violations.append(PlanViolation('invalid_sha256', 'plan.source_brief_sha256', 'source_brief_sha256 must be 64-char lowercase hex digest'))
    for i, task in enumerate(plan.get('tasks', [])):
        if not isinstance(task, dict):
            continue
        vcmd = task.get('verification_command')
        if not isinstance(vcmd, str) or not vcmd.strip():
            tid = task.get('task_id') or f'tasks[{i}]'
            raise ValueError(f'task {tid!r} has invalid verification_command (must be non-empty string)')
    return violations