"""Deterministic backstop normalizer for auto-planned leaf plans.

This module exposes a single pure, deterministic function
:func:`normalize_plan` that auto-corrects a merged (or single-agent) leaf
plan so the daemon's auto-planned child plans are executable with zero
operator vetting.  It performs two corrections:

1. **Dedupe oracles** -- collapses duplicate ``test_authoring`` tasks that
   share the same ``mutation_target`` down to a single surviving oracle,
   rewiring every dependency that referenced a dropped task.
2. **Enforce module-first ordering** -- ensures each surviving oracle
   depends on the impl task that creates its module (instead of the
   inverted oracle-first ordering), while keeping the dependency graph
   acyclic.

``normalize_plan`` is pure (operates on a deep copy, performs no I/O),
idempotent, and a strict no-op for already-correct plans.  It only ever
touches the ``dependencies`` of affected tasks and removes duplicate
oracle tasks; every other task field is preserved verbatim.
"""
from __future__ import annotations
import copy
from typing import Any, Dict, List, Optional, Set

def _module_path(mutation_target: str) -> str:
    """Return the module file path for a dotted ``mutation_target``."""
    return mutation_target.replace('.', '/') + '.py'

def _task_id(task: Dict[str, Any]) -> str:
    """Return a task's id as a string (empty string when absent)."""
    tid = task.get('task_id')
    return tid if isinstance(tid, str) else '' if tid is None else str(tid)

def _files_touched(task: Dict[str, Any]) -> List[str]:
    files = task.get('files_touched')
    return list(files) if isinstance(files, list) else []

def _dependencies(task: Dict[str, Any]) -> List[str]:
    deps = task.get('dependencies')
    return list(deps) if isinstance(deps, list) else []

def _mutation_target(task: Dict[str, Any]) -> str:
    target = task.get('mutation_target')
    return target if isinstance(target, str) else ''

def _is_test_authoring(task: Dict[str, Any]) -> bool:
    return task.get('meta_task_type') == 'test_authoring'

def _impl_for_module(tasks: List[Dict[str, Any]], module_path: str) -> Optional[Dict[str, Any]]:
    """Find the impl task that creates ``module_path``.

    A candidate is any non-``test_authoring`` task whose ``files_touched``
    contains the module file path.  When several qualify, the first by
    ``task_id`` is chosen so the result is stable across reordered inputs.
    """
    candidates = [t for t in tasks if isinstance(t, dict) and (not _is_test_authoring(t)) and (module_path in _files_touched(t))]
    if not candidates:
        return None
    return min(candidates, key=_task_id)

def _build_graph(tasks: List[Dict[str, Any]]) -> Dict[str, Set[str]]:
    """Build a ``task_id -> set(dependency task_ids)`` adjacency map."""
    ids = {_task_id(t) for t in tasks if isinstance(t, dict)}
    graph: Dict[str, Set[str]] = {}
    for t in tasks:
        if not isinstance(t, dict):
            continue
        tid = _task_id(t)
        graph[tid] = {d for d in _dependencies(t) if d in ids}
    return graph

def _reaches(graph: Dict[str, Set[str]], start: str, target: str) -> bool:
    """Return True if ``target`` is reachable from ``start`` in ``graph``."""
    stack = [start]
    seen: Set[str] = set()
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(graph.get(node, ()))
    return False

def _dedupe_oracles(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse duplicate oracles sharing a mutation_target.

    Returns the surviving task list with every dependency that referenced a
    dropped task rewired to the kept task_id (de-duplicated, no dangling
    references introduced).
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for t in tasks:
        if not isinstance(t, dict) or not _is_test_authoring(t):
            continue
        target = _mutation_target(t)
        if not target:
            continue
        groups.setdefault(target, []).append(t)
    drop_map: Dict[str, str] = {}
    for target, group in groups.items():
        if len(group) <= 1:
            continue
        impl = _impl_for_module(tasks, _module_path(target))
        kept: Optional[Dict[str, Any]] = None
        if impl is not None:
            vc = impl.get('verification_command')
            if isinstance(vc, str) and vc:
                referenced = [o for o in group if any((f and f in vc for f in _files_touched(o)))]
                if referenced:
                    kept = min(referenced, key=_task_id)
        if kept is None:
            kept = min(group, key=_task_id)
        kept_id = _task_id(kept)
        for o in group:
            if o is kept:
                continue
            drop_map[_task_id(o)] = kept_id
    if not drop_map:
        return tasks
    survivors = [t for t in tasks if not (isinstance(t, dict) and _task_id(t) in drop_map)]
    for t in survivors:
        if not isinstance(t, dict):
            continue
        deps = t.get('dependencies')
        if not isinstance(deps, list):
            continue
        if not any((d in drop_map for d in deps)):
            continue
        own_id = _task_id(t)
        rewritten: List[str] = []
        for d in deps:
            new_d = drop_map.get(d, d)
            if new_d == own_id:
                continue
            if new_d not in rewritten:
                rewritten.append(new_d)
        t['dependencies'] = rewritten
    return survivors

def _enforce_module_first(tasks: List[Dict[str, Any]]) -> None:
    """Flip oracle-first inversions to module-first, keeping graph acyclic."""
    oracles = sorted((t for t in tasks if isinstance(t, dict) and _is_test_authoring(t) and _mutation_target(t)), key=_task_id)
    for oracle in oracles:
        target = _mutation_target(oracle)
        impl = _impl_for_module(tasks, _module_path(target))
        if impl is None:
            continue
        oid = _task_id(oracle)
        iid = _task_id(impl)
        if not oid or not iid or oid == iid:
            continue
        oracle_deps = oracle.get('dependencies')
        if not isinstance(oracle_deps, list):
            oracle_deps = []
            oracle['dependencies'] = oracle_deps
        if iid not in oracle_deps:
            oracle_deps.append(iid)
        impl_deps = impl.get('dependencies')
        if isinstance(impl_deps, list) and oid in impl_deps:
            impl['dependencies'] = [d for d in impl_deps if d != oid]
        while True:
            graph = _build_graph(tasks)
            if not _reaches(graph, iid, oid):
                break
            current = impl.get('dependencies')
            if not isinstance(current, list) or not current:
                break
            removed = False
            for d in sorted(current):
                if d == oid or _reaches(graph, d, oid):
                    impl['dependencies'] = [x for x in current if x != d]
                    removed = True
                    break
            if not removed:
                break

def _sanitize_impl_verification_commands(plan: Dict[str, Any], repo_root: Optional[Any]=None) -> Dict[str, Any]:
    """Rewrite impl verification_commands that reference a sibling oracle's tests.

    ``ORACLE_FILES`` is the union of ``files_touched`` across every
    ``test_authoring`` task.  Each non-``test_authoring`` task whose
    ``verification_command`` is a non-empty string naming any oracle file is
    rewritten so it actually exercises its own touched module(s) rather than a
    sibling oracle's tests.

    A task's importable targets are its ``files_touched`` entries ending in
    ``.py``, not under ``tests/`` and not themselves oracle files, with slashes
    turned into dots and the trailing ``.py`` dropped, in stable
    ``files_touched`` order.

    When ``repo_root`` is ``None`` the behaviour is unchanged (pure, no I/O):
    the command becomes a smoke import (``python -c "import <m1>, <m2>"``) of
    those importable modules; when the task has no importable target the oracle
    tokens are stripped from the command while the rest is preserved; if
    nothing meaningful would remain the command is left unchanged (never a
    bare ``pytest``).

    When ``repo_root`` is not ``None``, each importable target's leaf module
    name is used to glob ``Path(repo_root).glob('tests/**/test_<leaf>.py')``;
    matches recorded as repo-relative posix paths, excluding any path present
    in ``ORACLE_FILES``, de-duplicated and stably sorted.  If one or more such
    existing test files are found the command becomes
    ``'python -m pytest ' + ' '.join(existing_tests) + ' -q'``; otherwise the
    smoke-import / token-strip fallback chain above applies.

    The pass operates on a deep copy and is idempotent; with ``repo_root=None``
    it is byte-identical to its prior behaviour and a strict no-op when no impl
    command references an oracle file.
    """
    import os
    if not isinstance(plan, dict):
        return plan
    result = copy.deepcopy(plan)
    tasks = result.get('tasks')
    if not isinstance(tasks, list):
        return result
    oracle_files: Set[str] = set()
    for t in tasks:
        if isinstance(t, dict) and _is_test_authoring(t):
            for f in _files_touched(t):
                if isinstance(f, str) and f:
                    oracle_files.add(f)
    if not oracle_files:
        return result
    boilerplate = {'python', 'python3', 'pytest'}
    for t in tasks:
        if not isinstance(t, dict) or _is_test_authoring(t):
            continue
        vcmd = t.get('verification_command')
        if not isinstance(vcmd, str) or not vcmd:
            continue
        references_oracle = any((of in vcmd for of in oracle_files))
        # A.2: also handle a WEAK import-smoke (python -c "import ...") that
        # names no oracle file — when a paired committed tests/**/test_<leaf>.py
        # exists on disk we must still upgrade it to a real pytest gate, else a
        # buggy-but-importable new-module / harness_self_fix impl ACCEPTs vacuously.
        is_import_smoke = 'python -c' in vcmd and 'import' in vcmd
        if not references_oracle and not is_import_smoke:
            continue
        # Fix-forward red-pair guard: leave the impl's verification_command
        # intact when it mirrors the runtime is_fix_forward_redpair predicate
        # (harness/redpair_acceptance.py) -- a sibling test_authoring oracle
        # whose mutation_target maps into THIS impl's files_touched, and whose
        # own authored test file is already named in this vcmd. Rewriting it
        # here would strip the oracle filename the acceptance gate re-checks,
        # so the legitimate RED oracle would be wrongly rejected.
        _impl_files = set(_files_touched(t))
        _is_fix_forward_redpair = False
        for _o in tasks:
            if not isinstance(_o, dict) or not _is_test_authoring(_o):
                continue
            _omt = _mutation_target(_o)
            if (not _omt) or '/' in _omt or '\\' in _omt or '..' in _omt or _omt.endswith('.py'):
                continue
            if _module_path(_omt) not in _impl_files:
                continue
            _ofiles = [f for f in _files_touched(_o) if isinstance(f, str) and f]
            if any(of in vcmd for of in _ofiles):
                _is_fix_forward_redpair = True
                break
        if _is_fix_forward_redpair:
            continue
        modules: List[str] = []
        leaves: List[str] = []
        for f in _files_touched(t):
            if not isinstance(f, str) or not f.endswith('.py'):
                continue
            if f.startswith('tests/') or '/tests/' in f or '\\tests\\' in f:
                continue
            if f in oracle_files:
                continue
            mod = f[:-len('.py')].replace(os.sep, '.').replace('/', '.')
            if mod and mod not in modules:
                modules.append(mod)
            leaf = mod.rsplit('.', 1)[-1] if mod else ''
            if leaf and leaf not in leaves:
                leaves.append(leaf)
        if repo_root is not None and leaves:
            from pathlib import Path
            root = Path(repo_root)
            existing_tests: List[str] = []
            seen: Set[str] = set()
            for leaf in leaves:
                for match in root.glob('tests/**/test_' + leaf + '.py'):
                    try:
                        rel = match.relative_to(root).as_posix()
                    except ValueError:
                        rel = match.as_posix()
                    if rel in oracle_files or rel in seen:
                        continue
                    seen.add(rel)
                    existing_tests.append(rel)
            existing_tests = sorted(existing_tests)
            if existing_tests:
                t['verification_command'] = 'python -m pytest ' + ' '.join(existing_tests) + ' -q'
                continue
        if modules:
            t['verification_command'] = 'python -c "import ' + ', '.join(modules) + '"'
            continue
        tokens = vcmd.split()
        kept = [tok for tok in tokens if tok not in oracle_files]
        meaningful = [tok for tok in kept if tok not in boilerplate and (not tok.startswith('-'))]
        if meaningful:
            t['verification_command'] = ' '.join(kept)
    return result
def _inject_oracle_sources(plan: Dict[str, Any], repo_root: Optional[Any]) -> Dict[str, Any]:
    """Embed each impl task's committed oracle source into its spec notes.

    For every non-``test_authoring`` task that carries a dict ``spec`` and a
    non-empty ``verification_command``, the pytest test-file paths named in
    that command are resolved under ``repo_root`` and, when the file exists,
    its source is read and appended verbatim to
    ``task['spec']['implementation_notes']`` under a clearly-labeled block
    carrying the literal marker ``COMMITTED ORACLE CONTRACT`` and the test
    file's repo-relative path.  This turns a vague "see the oracle" spec into a
    self-contained contract the jailed synthesis agent can actually satisfy.

    The pass is pure (operates on a deep copy, never mutates the input) and
    idempotent: a task whose notes already contain the marker is skipped, and
    ``repo_root is None`` (or a non-dict ``plan``) is a strict no-op.
    """
    from pathlib import Path
    if repo_root is None or not isinstance(plan, dict):
        return plan
    result = copy.deepcopy(plan)
    tasks = result.get('tasks')
    if not isinstance(tasks, list):
        return result
    root = Path(repo_root)
    for t in tasks:
        if not isinstance(t, dict) or _is_test_authoring(t):
            continue
        spec = t.get('spec')
        if not isinstance(spec, dict):
            continue
        vcmd = t.get('verification_command')
        if not isinstance(vcmd, str) or not vcmd:
            continue
        notes = spec.get('implementation_notes')
        if isinstance(notes, str) and 'COMMITTED ORACLE CONTRACT' in notes:
            continue
        oracles: List[Any] = []
        seen: Set[str] = set()
        for tok in vcmd.split():
            if tok.startswith('-') or not tok.endswith('.py'):
                continue
            if tok in seen:
                continue
            seen.add(tok)
            path = root / tok
            try:
                if not path.is_file():
                    continue
                src = path.read_text(encoding='utf-8')
            except OSError:
                continue
            oracles.append((tok, src))
        if not oracles:
            continue
        block = '\n\n# COMMITTED ORACLE CONTRACT (authoritative; you cannot read these files at synthesis time so they are reproduced verbatim -- your code MUST make them pass):\n'
        for rel, src in oracles:
            block += '\n## ' + rel + '\n```python\n' + src + '\n```\n'
        if isinstance(notes, str) and notes:
            spec['implementation_notes'] = notes + block
        else:
            spec['implementation_notes'] = block
    return result
def _force_smoke_gated_leaf_impl(plan: Dict[str, Any], repo_root: Optional[Any]) -> Dict[str, Any]:
    """Force an EXTERNAL-build leaf plan to a single smoke-gated impl task.

    For an external-build leaf plan (``repo_root`` outside ``PROJECT_ROOT``),
    tasks that share the same committed oracle-test set are collapsed to a
    single impl task retyped to ``data_model`` -- which is bypass_fuzzer and
    smoke-gated per ``META_TASK_POLICY`` -- routing correct external builds away
    from the diff-fuzzer (which cannot resolve external ``ngv2.*`` imports) and
    the stateful-fuzz path (which diverges).

    A task's oracle-test set is the set of whitespace tokens in its
    ``verification_command`` that end in ``.py``, do not start with ``-``, and
    resolve to an existing file under ``repo_root``.  Tasks with an empty oracle
    set are never grouped and are left untouched.  Each group with at least one
    impl candidate (a task whose ``meta_task_type`` is not an oracle-authoring
    type) keeps the lexicographically-smallest ``task_id`` candidate, retypes it
    to ``data_model``, removes the rest, and strips any removed id from every
    surviving task's ``dependencies``.

    The pass is pure (deep copy, no mutation of the input, no I/O beyond the
    ``is_file()`` existence checks under ``repo_root``) and idempotent.  It is a
    strict no-op returning the input object unchanged when ``repo_root`` is
    ``None``, when ``plan`` is not a dict, when ``plan`` is an epic plan
    (``child_slugs`` truthy), when ``repo_root`` resolves to ``PROJECT_ROOT`` (a
    JM-internal self-fix plan, which must never be retyped), or when resolving
    ``repo_root`` raises ``TypeError``/``ValueError``/``OSError``.
    """
    from pathlib import Path
    from harness.paths import PROJECT_ROOT
    if repo_root is None or not isinstance(plan, dict):
        return plan
    if plan.get('child_slugs'):
        return plan
    try:
        if Path(repo_root).resolve() == Path(PROJECT_ROOT).resolve():
            return plan
    except (TypeError, ValueError, OSError):
        return plan
    result = copy.deepcopy(plan)
    tasks = result.get('tasks')
    if not isinstance(tasks, list) or not tasks:
        return result
    root = Path(repo_root)
    non_impl = {'test_authoring', 'test_acceptance', 'test_unit', 'test_integration', 'test_e2e', 'validation'}

    def _oracle_set(task: Dict[str, Any]) -> frozenset:
        vcmd = task.get('verification_command')
        if not isinstance(vcmd, str) or not vcmd:
            return frozenset()
        found: Set[str] = set()
        for tok in vcmd.split():
            if tok.startswith('-') or not tok.endswith('.py'):
                continue
            try:
                if (root / tok).is_file():
                    found.add(tok)
            except (TypeError, ValueError, OSError):
                continue
        return frozenset(found)
    groups: Dict[frozenset, List[Dict[str, Any]]] = {}
    for t in tasks:
        if not isinstance(t, dict):
            continue
        oset = _oracle_set(t)
        if not oset:
            continue
        groups.setdefault(oset, []).append(t)
    removed_ids: Set[str] = set()
    for group in groups.values():
        impl_candidates = [t for t in group if t.get('meta_task_type') not in non_impl]
        if not impl_candidates:
            continue
        survivor = min(impl_candidates, key=_task_id)
        survivor['meta_task_type'] = 'data_model'
        for t in group:
            if t is survivor:
                continue
            removed_ids.add(_task_id(t))
    if removed_ids:
        result['tasks'] = [t for t in tasks if not (isinstance(t, dict) and _task_id(t) in removed_ids)]
        for t in result['tasks']:
            if not isinstance(t, dict):
                continue
            deps = t.get('dependencies')
            if isinstance(deps, list):
                t['dependencies'] = [d for d in deps if d not in removed_ids]
    return result
def _inject_credential_naming_constraint(plan: Dict[str, Any], repo_root: Optional[Any]) -> Dict[str, Any]:
    """Steer an EXTERNAL-build leaf plan away from synthesis-quality failures.

    The ``ast_enforcer`` security gate flags ANY variable whose name contains
    (case-insensitive) ``password``/``secret``/``key`` assigned a string
    *literal* as a hardcoded credential -- strict even for an external
    clean-room target with no real secret.  A leaf whose natural implementation
    binds a field label or check id to a variable named ``key`` therefore fails
    synthesis and exhausts its retry budget even though the code is correct.

    Beyond that credential-naming heuristic, the STDLIB-ONLY DETERMINISTIC
    verification jail rejects two further blind-synthesis failure classes: a
    third-party import (e.g. ``pydantic`` / ``pydantic_settings``) is absent in
    the verification env and fails collection, and a wall-clock /
    nondeterministic call (``datetime.now`` / ``time.time`` / unseeded
    ``random`` / ``uuid`` / ``secrets``) is rejected by the AST nondeterminism
    gate.  Both park the leaf.

    For an external-build leaf plan this pass appends a single multi-directive
    constraint block (carrying the literal marker ``CREDENTIAL-NAMING
    CONSTRAINT``) to every non-``test_authoring`` task's
    ``spec['implementation_notes']``: (a) the credential-naming directive, (b) a
    stdlib-only directive forbidding third-party imports, and (c) a determinism
    directive forbidding wall-clock / nondeterministic sources.  Like
    :func:`_inject_oracle_sources`, it changes only the spec the agent reads,
    never the code the AST gate inspects, and does not loosen any gate.

    The pass is pure (operates on a deep copy, never mutates the input) and
    idempotent: a task whose notes already contain the marker is skipped.  It is
    a strict no-op returning the input object unchanged when ``repo_root`` is
    ``None``, when ``plan`` is not a dict, when ``plan`` is an epic plan
    (``child_slugs`` truthy), when ``repo_root`` resolves to ``PROJECT_ROOT`` (a
    JM-internal self-fix plan, which must never be steered), or when resolving
    ``repo_root`` raises ``TypeError``/``ValueError``/``OSError``.
    """
    from pathlib import Path
    from harness.paths import PROJECT_ROOT
    if repo_root is None or not isinstance(plan, dict):
        return plan
    if plan.get('child_slugs'):
        return plan
    try:
        if Path(repo_root).resolve() == Path(PROJECT_ROOT).resolve():
            return plan
    except (TypeError, ValueError, OSError):
        return plan
    result = copy.deepcopy(plan)
    tasks = result.get('tasks')
    if not isinstance(tasks, list):
        return result
    marker = 'CREDENTIAL-NAMING CONSTRAINT'
    block = (
        '\n\n# CREDENTIAL-NAMING CONSTRAINT (the AST security gate FAILS the build if a variable whose name contains (case-insensitive) "password", "secret", or "key" is assigned a string literal -- it reads as a hardcoded credential even though this is an external clean-room target with no real secret). NEVER bind a string literal to such a variable. Use a neutral name instead (field_name, check_id, label, name, ident, column) or iterate a collection literal / build the mapping from a list of tuples. This applies to dict keys held in a temp var, field labels, and constant identifiers.\n'
        '\n# STDLIB-ONLY CONSTRAINT (the verification environment installs NO third-party packages, so importing one fails collection -> the whole build is rolled back and the leaf is parked). Import ONLY the Python standard library. Import NO third-party package: NO pydantic, NO pydantic_settings, NO attrs, NO pyyaml, NO numpy, NO requests, etc. For data models / config use stdlib dataclasses (dataclasses.dataclass), enum.Enum, typing, and plain dict / json instead of pydantic BaseModel / BaseSettings. If the spec mentions pydantic-style validation, re-express it with stdlib dataclasses + manual checks.\n'
        '\n# DETERMINISM CONSTRAINT (the AST nondeterminism gate FAILS the build if it sees a wall-clock or nondeterministic source). Do NOT call datetime.now / datetime.utcnow, time.time / time.monotonic, unseeded random, uuid, os.urandom, or secrets to obtain a timestamp / id / randomness. Instead accept any timestamp, seed, or clock as an EXPLICIT parameter with a deterministic default (the oracle injects it, e.g. via now_fn / make_scripted_clock), so the same inputs always produce the same output.\n'
    )
    for t in tasks:
        if not isinstance(t, dict) or _is_test_authoring(t):
            continue
        spec = t.get('spec')
        if not isinstance(spec, dict):
            continue
        notes = spec.get('implementation_notes')
        if isinstance(notes, str) and marker in notes:
            continue
        if isinstance(notes, str) and notes:
            spec['implementation_notes'] = notes + block
        else:
            spec['implementation_notes'] = block
    return result
def _correct_meta_task_type_by_target(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministically retype a leaf whose targets are off the fuzzer domain.

    The Python diff-fuzzer must not run on non-Python targets.  A task is
    retyped ONLY when its current ``meta_task_type`` is NOT already a
    bypass-fuzzer type and its ``files_touched`` extensions are uniform:

      * all non-Python static assets
        (.js/.jsx/.ts/.tsx/.mjs/.html/.htm/.css/.scss) -> ``harness_plumbing``
      * all config files (.yaml/.yml/.toml/.ini/.cfg) -> ``harness_self_fix``

    A Python (.py) target, a mixed target set, an unknown-extension set, and an
    empty/missing ``files_touched`` are all left untouched, as is any task
    already on a bypass-fuzzer type.  Extensions are compared lower-cased so
    ``.JS``/``.YAML`` still match.  The pass mutates tasks in place (consistent
    with the sibling hooks) and returns the plan; it never raises on a non-list
    ``tasks`` value or non-dict task entries.
    """
    import os
    from harness.planner.taxonomies import BYPASS_FUZZER_TYPES
    _ASSET_EXTS = {'.js', '.jsx', '.ts', '.tsx', '.mjs', '.html', '.htm', '.css', '.scss'}
    _CONFIG_EXTS = {'.yaml', '.yml', '.toml', '.ini', '.cfg'}
    if not isinstance(plan, dict):
        return plan
    tasks = plan.get('tasks')
    if not isinstance(tasks, list):
        return plan
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if task.get('meta_task_type') in BYPASS_FUZZER_TYPES:
            continue
        exts = {os.path.splitext(f)[1].lower() for f in _files_touched(task) if isinstance(f, str) and f}
        if not exts:
            continue
        if exts <= _ASSET_EXTS:
            task['meta_task_type'] = 'harness_plumbing'
        elif exts <= _CONFIG_EXTS:
            task['meta_task_type'] = 'harness_self_fix'
    return plan
_ORACLE_TESTS_SEGMENT = '/tests/'

def _canonicalize_oracle_paths(plan: Dict[str, Any], repo_root: Optional[Any]=None) -> Dict[str, Any]:
    """Deterministically repair a REVERSED external oracle verification path.

    A blindly-drafted external leaf sometimes emits a ``verification_command``
    whose test path is reversed -- ``pytest ngv2/tests/test_x_wired.py`` -- when
    the real on-disk oracle lives at ``tests/ngv2/test_x_wired.py``.  This pure
    pass rewrites every whitespace-split ``.py`` token in each task's
    ``verification_command`` that does NOT resolve as-is under ``repo_root`` but
    whose ``<pkg>/tests/<rest>`` <-> ``tests/<pkg>/<rest>`` swap DOES resolve to
    an existing file under ``repo_root``.

    The pass is pure (it deep-copies ``plan`` and never mutates the input) and
    idempotent.  It is a strict no-op when ``repo_root is None`` (no filesystem
    to resolve against), when ``plan`` is not a dict, when ``tasks`` is not a
    list, and when ``Path(repo_root)`` raises.  A token that resolves neither
    as-is nor swapped is left byte-identical (a missing oracle is never guessed
    into existence); the swap only fires on a 3+-segment shape, so a SELF/JM
    ``tests/test_bar.py`` command is never touched.
    """
    if repo_root is None or not isinstance(plan, dict):
        return plan
    from pathlib import Path
    try:
        root = Path(repo_root)
    except (TypeError, ValueError, OSError):
        return plan
    normalized = copy.deepcopy(plan)
    tasks = normalized.get('tasks')
    if not isinstance(tasks, list):
        return normalized

    def _resolves(rel: str) -> bool:
        try:
            return (root / rel).is_file()
        except (TypeError, ValueError, OSError):
            return False

    def _swap(tok: str) -> List[str]:
        parts = tok.split('/')
        if len(parts) < 3:
            return []
        candidates: List[str] = []
        if parts[1] == 'tests':
            candidates.append('/'.join(['tests', parts[0]] + parts[2:]))
        if parts[0] == 'tests':
            candidates.append('/'.join([parts[1], 'tests'] + parts[2:]))
        return candidates
    for task in tasks:
        if not isinstance(task, dict):
            continue
        vcmd = task.get('verification_command')
        if not isinstance(vcmd, str) or not vcmd:
            continue
        tokens = vcmd.split()
        changed = False
        for i, tok in enumerate(tokens):
            if tok.startswith('-') or not tok.endswith('.py'):
                continue
            if _resolves(tok):
                continue
            for cand in _swap(tok):
                if cand != tok and _resolves(cand):
                    tokens[i] = cand
                    changed = True
                    break
        if changed:
            task['verification_command'] = ' '.join(tokens)
    return normalized
def _strip_unresolvable_dependencies(tasks: list) -> None:
    """Drop each task ``dependency`` that is not the ``task_id`` of another
    in-plan task.

    Epic child briefs can carry frontmatter ``dependencies:`` naming sibling
    brief SLUGS; when such a child is planned in isolation those slug strings
    land in the generated task's ``dependencies`` and never match a real
    in-plan ``task_id``, permanently wedging the task at the autowork daemon
    dispatch gate.  This in-place pass keeps only entries that are ``str`` and
    members of the in-plan ``task_id`` set, preserving original order.  It
    tolerates missing/None/non-list ``dependencies`` and non-str entries, is
    idempotent, and a strict byte-identical no-op for already-clean plans.
    """
    in_plan_ids = {task['task_id'] for task in tasks if isinstance(task, dict) and isinstance(task.get('task_id'), str)}
    for task in tasks:
        if not isinstance(task, dict):
            continue
        deps = task.get('dependencies')
        if not isinstance(deps, list):
            continue
        task['dependencies'] = [dep for dep in deps if isinstance(dep, str) and dep in in_plan_ids]
def _drop_redundant_precommitted_oracles(tasks: List[Dict[str, Any]], repo_root: Optional[Any]) -> List[Dict[str, Any]]:
    """Drop a SINGLETON test_authoring oracle already covered on disk.

    A *singleton* oracle is a ``test_authoring`` task whose non-empty
    ``mutation_target`` appears on exactly one ``test_authoring`` task, so
    multi-oracle groups already collapsed by :func:`_dedupe_oracles` (its
    ``len(group) <= 1`` guard) are never touched here.

    An oracle is dropped ONLY on a confident on-disk match: its
    ``mutation_target`` module file (``_module_path(target)``) must EXIST
    under ``repo_root`` AND a committed covering oracle must exist -- a
    ``tests/**/test_<leaf>.py`` (leaf = ``target.rsplit('.', 1)[-1]``,
    following the glob/leaf-stem convention of
    :func:`_sanitize_impl_verification_commands`) OR any ``tests/**/*.py``
    that imports the dotted module (``from <target> import`` /
    ``import <target>``) -- where the matching file is NOT one of the
    oracle's own ``files_touched``.  When in doubt the oracle is KEPT.

    Additionally, the drop now fires ONLY when the SAME plan also contains a
    non-``test_authoring`` (impl) task whose ``files_touched`` includes the
    oracle's target module path (``_module_path(target) in impl_paths``).  A
    standalone oracle with no such impl sibling -- the brief's only
    deliverable -- is therefore always KEPT, even when the target module is
    merely imported by some committed test.  This guard is purely additive
    and STRICTER: it can only KEEP more oracles, never drop more.

    Dependents of a dropped oracle are rewired with the same drop-map
    pattern as :func:`_dedupe_oracles`: the dropped id is removed from
    every other task's ``dependencies`` (never pointing at a non-existent
    task), de-duplicated, with no self-edge or dangling reference
    introduced.  The pass is idempotent, a strict no-op (NO filesystem
    access) when ``repo_root`` is ``None``, and KEEPs on any
    ``TypeError``/``ValueError``/``OSError``.
    """
    if repo_root is None:
        return tasks
    from pathlib import Path
    try:
        root = Path(repo_root)
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for t in tasks:
            if not isinstance(t, dict) or not _is_test_authoring(t):
                continue
            target = _mutation_target(t)
            if not target:
                continue
            groups.setdefault(target, []).append(t)
        impl_paths = {f for t in tasks if isinstance(t, dict) and (not _is_test_authoring(t)) for f in _files_touched(t) if isinstance(f, str) and f}
        drop_ids: Set[str] = set()
        for target, group in groups.items():
            if len(group) != 1:
                continue
            oracle = group[0]
            module_path = _module_path(target)
            if not Path(root, module_path).is_file():
                continue
            own_files = {f for f in _files_touched(oracle) if isinstance(f, str) and f}
            leaf = target.rsplit('.', 1)[-1]
            covered = False
            for match in root.glob('tests/**/test_' + leaf + '.py'):
                try:
                    rel = match.relative_to(root).as_posix()
                except ValueError:
                    rel = match.as_posix()
                if rel in own_files:
                    continue
                if match.is_file():
                    covered = True
                    break
            if not covered:
                from_needle = 'from ' + target + ' import'
                import_needle = 'import ' + target
                for match in root.glob('tests/**/*.py'):
                    try:
                        rel = match.relative_to(root).as_posix()
                    except ValueError:
                        rel = match.as_posix()
                    if rel in own_files:
                        continue
                    try:
                        text = match.read_text(encoding='utf-8')
                    except OSError:
                        continue
                    if from_needle in text or import_needle in text:
                        covered = True
                        break
            if covered and _module_path(target) in impl_paths:
                # Red-pair guard: KEEP an oracle whose paired impl is verified by
                # the oracle's OWN authored test file (a deliberate fix-forward
                # red-pair), even when the target module is covered on disk. Only
                # a genuinely redundant oracle -- one whose impl is verified by a
                # DIFFERENT, pre-existing committed test (NOT the oracle's own
                # file) -- is still dropped here.
                _own_oracle_files = {f for f in own_files if isinstance(f, str) and f}
                _redpair = any(
                    (not _is_test_authoring(it))
                    and isinstance(it.get('verification_command'), str)
                    and any(of in it['verification_command'] for of in _own_oracle_files)
                    for it in tasks if isinstance(it, dict)
                )
                if not _redpair:
                    drop_ids.add(_task_id(oracle))
        if not drop_ids:
            return tasks
        survivors = [t for t in tasks if not (isinstance(t, dict) and _task_id(t) in drop_ids)]
        for t in survivors:
            if not isinstance(t, dict):
                continue
            deps = t.get('dependencies')
            if not isinstance(deps, list):
                continue
            if not any((d in drop_ids for d in deps)):
                continue
            own_id = _task_id(t)
            rewritten: List[str] = []
            for d in deps:
                if d in drop_ids or d == own_id:
                    continue
                if d not in rewritten:
                    rewritten.append(d)
            t['dependencies'] = rewritten
        return survivors
    except (TypeError, ValueError, OSError):
        return tasks
def _drop_committed_module_impls(plan: Dict[str, Any], repo_root: Optional[Any]) -> Dict[str, Any]:
    """Drop an impl that RE-BUILDS a module already committed at HEAD.

    The planner decomposes each brief in isolation and only dedups
    ``test_authoring`` oracles -- never impl ``files_touched`` -- so it can
    emit an impl task targeting a module a DIFFERENT brief already committed,
    silently clobbering it.  This conservative repo_root-aware pass detects a
    *re-build clobber*: an impl whose ``files_touched`` names a path that
    EXISTS at HEAD in the resolved target root AND that is re-created by a
    paired ``test_authoring`` oracle in the SAME plan (an oracle whose
    ``_module_path(_mutation_target(oracle))`` equals one of those
    HEAD-existing paths).  When matched, BOTH the impl and that paired oracle
    are dropped and the telemetry marker ``duplicate_module_skipped`` is
    surfaced on the plan-level ``normalizer_telemetry`` field.

    HEAD membership is probed with ``git cat-file -e HEAD:<rel>`` run with
    ``cwd=str(repo_root)`` (rc == 0 means present) -- working-tree presence
    alone never triggers the drop.  A genuinely-new module (not at HEAD) and a
    same-brief fix-forward EDIT (module at HEAD but with NO paired re-creating
    oracle) are both KEPT, with no marker.

    Dependents of a dropped clobber-impl are rewired with the same drop-map
    pattern as :func:`_dedupe_oracles`: the dropped ids are removed from every
    other task's ``dependencies`` (de-duplicated, never a self-edge or a
    dangling reference).  The pass is conservative and idempotent: it is a
    strict no-op (NO git/filesystem access) when ``repo_root`` is ``None`` and
    KEEPs on any
    ``TypeError``/``ValueError``/``OSError``/``subprocess.SubprocessError``.
    """
    if repo_root is None or not isinstance(plan, dict):
        return plan
    import subprocess
    try:
        tasks = plan.get('tasks')
        if not isinstance(tasks, list):
            return plan
        root = str(repo_root)

        def _in_head(rel: str) -> bool:
            try:
                proc = subprocess.run(['git', 'cat-file', '-e', 'HEAD:' + rel], cwd=root, capture_output=True, text=True, timeout=30)
            except (OSError, subprocess.SubprocessError):
                return False
            return proc.returncode == 0
        oracle_modules: Dict[str, List[Dict[str, Any]]] = {}
        for t in tasks:
            if not isinstance(t, dict) or not _is_test_authoring(t):
                continue
            target = _mutation_target(t)
            if not target:
                continue
            oracle_modules.setdefault(_module_path(target), []).append(t)
        drop_ids: Set[str] = set()
        markers: List[str] = []
        for t in tasks:
            if not isinstance(t, dict) or _is_test_authoring(t):
                continue
            head_paths = [f for f in _files_touched(t) if isinstance(f, str) and f and _in_head(f)]
            if not head_paths:
                continue
            paired_oracles: List[Dict[str, Any]] = []
            matched_path: Optional[str] = None
            for rel in head_paths:
                if rel in oracle_modules:
                    paired_oracles = oracle_modules[rel]
                    matched_path = rel
                    break
            if not paired_oracles:
                continue
            # Red-pair guard: if this impl is verified by one of its paired
            # oracles' OWN authored test files, it is a deliberate fix-forward
            # (red-pair), NOT an accidental cross-brief clobber -- KEEP the impl
            # and its paired oracle. An accidental clobber (impl verified by a
            # different/pre-existing test) still drops below.
            _vc = t.get('verification_command')
            if isinstance(_vc, str) and any(
                of in _vc
                for o in paired_oracles
                for of in _files_touched(o) if isinstance(of, str) and of
            ):
                continue
            drop_ids.add(_task_id(t))
            for o in paired_oracles:
                drop_ids.add(_task_id(o))
            markers.append('duplicate_module_skipped:' + matched_path)
        if not drop_ids:
            return plan
        telemetry = plan.setdefault('normalizer_telemetry', [])
        if isinstance(telemetry, list):
            for m in markers:
                telemetry.append(m)
        survivors = [t for t in tasks if not (isinstance(t, dict) and _task_id(t) in drop_ids)]
        for t in survivors:
            if not isinstance(t, dict):
                continue
            deps = t.get('dependencies')
            if not isinstance(deps, list):
                continue
            if not any((d in drop_ids for d in deps)):
                continue
            own_id = _task_id(t)
            rewritten: List[str] = []
            for d in deps:
                if d in drop_ids or d == own_id:
                    continue
                if d not in rewritten:
                    rewritten.append(d)
            t['dependencies'] = rewritten
        plan['tasks'] = survivors
        return plan
    except (TypeError, ValueError, OSError, subprocess.SubprocessError):
        return plan
def _split_multifile_module_tasks(tasks: list, repo_root: Optional[Any]=None) -> list:
    """Split a multi-file module-creating task into one task per new module.

    For every NON-``test_authoring`` task whose ``files_touched`` lists MORE
    THAN ONE *new module* path -- a ``.py`` not under ``tests/`` that does not
    already exist on disk under the repo root, mirroring
    ``plan_validator._is_module_creating`` -- the task is replaced by ``N``
    tasks, one per created module.  Each split task carries a single-element
    ``files_touched`` (just its module), copies every other field from the
    original, and gets a deterministic, unique id ``f"{orig_id}__{stem}"``
    (``stem = Path(path).stem``); colliding stems within one task are
    disambiguated by parent folder, then a numeric counter.  The split tasks
    never depend on one another (they only inherit the original's
    dependencies).

    Any OTHER task whose ``dependencies`` named the original ``task_id`` is
    fanned out to depend on ALL of the split ids (the original id removed).
    When the original had a paired ``test_authoring`` sibling whose
    ``mutation_target`` is one of the created modules, the pairing is extended
    only as needed: a sibling oracle is cloned for any other split module that
    has neither its own oracle nor a wiring oracle already covering it.

    The pass is pure (it builds new dicts via deep copy and never mutates the
    input tasks) and idempotent: once a multi-file task has been split it no
    longer exists, so a second application is a strict no-op.  ``repo_root``
    defaults to the project root so the on-disk existence probe matches the
    planner's notion of a freshly-created module.
    """
    if not isinstance(tasks, list):
        return tasks
    from pathlib import Path
    root: Optional[Any] = None
    try:
        if repo_root is not None:
            root = Path(repo_root)
        else:
            from harness.paths import PROJECT_ROOT
            root = Path(PROJECT_ROOT)
    except (TypeError, ValueError, OSError):
        root = None

    def _new_modules(task: Dict[str, Any]) -> List[str]:
        mods: List[str] = []
        for f in _files_touched(task):
            if not isinstance(f, str) or not f.endswith('.py'):
                continue
            if 'tests/' in f:
                continue
            exists = False
            if root is not None:
                try:
                    exists = (root / f).exists()
                except (TypeError, ValueError, OSError):
                    exists = False
            if exists:
                continue
            if f not in mods:
                mods.append(f)
        return mods
    result: List[Dict[str, Any]] = []
    fanout: Dict[str, List[str]] = {}
    split_modules: Dict[str, Dict[str, str]] = {}
    for task in tasks:
        if not isinstance(task, dict) or _is_test_authoring(task):
            result.append(copy.deepcopy(task) if isinstance(task, dict) else task)
            continue
        mods = _new_modules(task)
        if len(mods) <= 1:
            result.append(copy.deepcopy(task))
            continue
        orig_id = _task_id(task)
        used: Set[str] = set()
        module_to_id: Dict[str, str] = {}
        split_ids: List[str] = []
        for mod in mods:
            stem = Path(mod).stem
            base = orig_id + '__' + stem if orig_id else '__' + stem
            new_id = base
            if new_id in used:
                parent = Path(mod).parent.name
                new_id = base + '__' + parent if parent else base
                counter = 1
                while new_id in used:
                    new_id = base + '__' + str(counter)
                    counter += 1
            used.add(new_id)
            clone = copy.deepcopy(task)
            clone['task_id'] = new_id
            clone['files_touched'] = [mod]
            result.append(clone)
            split_ids.append(new_id)
            module_to_id[mod] = new_id
        fanout[orig_id] = split_ids
        split_modules[orig_id] = module_to_id
    if fanout:
        for task in result:
            if not isinstance(task, dict):
                continue
            deps = task.get('dependencies')
            if not isinstance(deps, list):
                continue
            if not any((d in fanout for d in deps)):
                continue
            own_id = _task_id(task)
            rewritten: List[str] = []
            for d in deps:
                targets = fanout.get(d, [d]) if isinstance(d, str) else [d]
                for nd in targets:
                    if nd == own_id:
                        continue
                    if nd not in rewritten:
                        rewritten.append(nd)
            task['dependencies'] = rewritten
        try:
            for orig_id, module_to_id in split_modules.items():
                module_set = set(module_to_id.keys())
                if not module_set:
                    continue
                paired = [t for t in result if isinstance(t, dict) and _is_test_authoring(t) and (_module_path(_mutation_target(t)) in module_set)]
                if not paired:
                    continue
                covered: Set[str] = set()
                for t in result:
                    if not isinstance(t, dict) or not _is_test_authoring(t):
                        continue
                    mp = _module_path(_mutation_target(t))
                    if mp in module_set:
                        covered.add(mp)
                    vc = t.get('verification_command')
                    files = _files_touched(t)
                    for mod in module_set:
                        dotted = mod[:-3].replace('/', '.') if mod.endswith('.py') else mod
                        if isinstance(vc, str) and (mod in vc or dotted in vc):
                            covered.add(mod)
                        elif any((isinstance(f, str) and mod in f for f in files)):
                            covered.add(mod)
                template = min(paired, key=_task_id)
                existing_ids = {_task_id(t) for t in result if isinstance(t, dict)}
                for mod in sorted(module_set):
                    if mod in covered:
                        continue
                    stem = Path(mod).stem
                    base = _task_id(template) + '__' + stem
                    clone_id = base
                    counter = 1
                    while clone_id in existing_ids:
                        clone_id = base + '__' + str(counter)
                        counter += 1
                    existing_ids.add(clone_id)
                    clone = copy.deepcopy(template)
                    clone['task_id'] = clone_id
                    clone['mutation_target'] = mod[:-3].replace('/', '.')
                    clone['dependencies'] = [module_to_id[mod]]
                    result.append(clone)
                    covered.add(mod)
        except (TypeError, ValueError, KeyError):
            pass
    return result
def _strip_stray_mutation_targets(tasks: List[Dict[str, Any]]) -> None:
    """Delete a stray scalar ``mutation_target`` from non-``test_authoring`` tasks.

    The blind planner reflexively attaches ``mutation_target =
    "<module>.<function>"`` to NEW-FILE implementation/data_model tasks; the
    downstream orchestrator non-vacuity mutation gate then triggers on that
    stray field, maps the dotted value to a path that does not exist, and
    fail-closes the task with ``mutation_gate_error``.  This final pass
    enforces the planner-schema invariant "omit ``mutation_target`` for all
    non-``test_authoring`` tasks" by dropping the scalar key in place, while
    preserving it verbatim on genuine ``test_authoring`` oracles where the
    non-vacuity gate legitimately needs it.

    Pure and deterministic: mutates ``tasks`` in place and returns ``None``.
    Non-dict entries and tasks lacking ``mutation_target`` are left untouched.
    """
    for t in tasks:
        if isinstance(t, dict) and (not _is_test_authoring(t)) and ('mutation_target' in t):
            del t['mutation_target']
def normalize_plan(plan: Dict[str, Any], repo_root: Optional[Any]=None) -> Dict[str, Any]:
    """Auto-correct a leaf plan: dedupe oracles + enforce module-first order.

    The function is pure: it deep-copies ``plan`` and never mutates the
    input.  It is idempotent and a strict no-op for already-correct plans,
    preserving every top-level key and every task field it does not
    explicitly touch.

    ``repo_root`` is threaded into
    :func:`_sanitize_impl_verification_commands` so impl verification commands
    can be mapped to existing regression tests; with ``repo_root=None`` the
    output is byte-identical to its prior behaviour.
    """
    normalized = copy.deepcopy(plan)
    if not isinstance(normalized, dict):
        return normalized
    tasks = normalized.get('tasks')
    if not isinstance(tasks, list):
        return normalized
    tasks = _split_multifile_module_tasks(tasks, repo_root)
    tasks = _dedupe_oracles(tasks)
    tasks = _drop_redundant_precommitted_oracles(tasks, repo_root)
    normalized['tasks'] = tasks
    normalized = _drop_committed_module_impls(normalized, repo_root)
    _enforce_module_first(tasks)
    _strip_unresolvable_dependencies(tasks)
    normalized = _correct_meta_task_type_by_target(normalized)
    normalized = _canonicalize_oracle_paths(normalized, repo_root)
    normalized = _sanitize_impl_verification_commands(normalized, repo_root)
    normalized = _force_smoke_gated_leaf_impl(normalized, repo_root)
    normalized = _inject_credential_naming_constraint(normalized, repo_root)
    normalized = _inject_oracle_sources(normalized, repo_root)
    if isinstance(normalized.get('tasks'), list):
        _strip_stray_mutation_targets(normalized['tasks'])
    return normalized
