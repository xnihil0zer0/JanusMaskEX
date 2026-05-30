import ast
import fnmatch
import os
import pathlib
import subprocess
import shutil
import logging

# AGENT-ISOLATION §1b: apply-path target-scoping. Any accepted manifest/patch
# whose target lands under one of these globs is a harness/config/script
# rewrite — the exact rogue-edit incident vector. It is committed ONLY when the
# task is a sanctioned ``harness_self_fix`` AND an operator-approval gate fired
# (see harness/orchestrator.py:_apply_approval_granted). This guard is
# independent of every CWD/shell isolation control and defends the
# submission-application boundary regardless of agent isolation.
_SENSITIVE_APPLY_GLOBS: tuple[str, ...] = ('harness/**', 'config/**', 'scripts/**')


def _matches_sensitive(rel_str: str, globs: tuple[str, ...]) -> bool:
    """True iff ``rel_str`` is inside one of the protected ``globs``.

    ``fnmatch`` does not treat ``**`` as a recursive wildcard, so a
    ``foo/**`` glob is interpreted as "the directory ``foo`` or anything
    beneath it" via an explicit prefix test; any other glob falls back to
    plain ``fnmatch`` matching.
    """
    # GAP_H2: normalize ('./', '..', '//') AND casefold before the prefix test
    # so 'Harness/x.py' / 'HARNESS/x.py' / './harness/x.py' cannot evade the
    # protected-root gate while still writing the real (lowercase-ASCII) dir on a
    # case-insensitive FS. Protected roots are lowercase ASCII, so casefolding the
    # glob base is safe and preserves the existing '**'-prefix-boundary semantics.
    p = os.path.normpath(rel_str.replace('\\', '/')).replace('\\', '/').casefold()
    for g in globs:
        if g.endswith('/**'):
            base = g[:-3].casefold()
            if p == base or p.startswith(base + '/'):
                return True
        elif fnmatch.fnmatch(p, g.casefold()):
            return True
    return False


def _enforce_apply_scope(rel_strs, *, allowed_files, meta_task_type, approval_ok,
                         sensitive_globs: tuple[str, ...] = _SENSITIVE_APPLY_GLOBS):
    """Return an error string if any rel path violates apply-path policy, else None.

    AGENT-ISOLATION §1b. Two independent constraints:

    * **membership** — when ``allowed_files`` is not None, every committed
      rel-path must be a member of the task's resolved ``files_touched``.
      Callers that pass ``None`` (e.g. low-level unit tests) opt out of the
      membership check but still get the sensitive-path gate below.
    * **sensitive** — a rel-path under ``harness/**`` / ``config/**`` /
      ``scripts/**`` is rejected unless the task is a sanctioned
      ``harness_self_fix`` AND ``approval_ok`` is True (operator approval).
    """
    # GAP_H1: normalize ('./', '..', '//') BOTH sides before the membership
    # compare. The candidate rel-path is derived from a .resolve()d relative_to
    # (already collapsed), so an un-normalized files_touched member like
    # './pkg/mod.py' or 'pkg/../pkg/mod.py' must be collapsed too or a LEGITIMATE
    # commit is falsely locked out. Keep rel-vs-rel (do NOT resolve to absolute).
    def _norm(s):
        return os.path.normpath(str(s).replace('\\', '/')).replace('\\', '/')
    allowed = None
    if allowed_files is not None:
        allowed = {_norm(f) for f in allowed_files}
    for rel in rel_strs:
        reln = _norm(rel)
        if allowed is not None and reln not in allowed:
            return (f'apply-path scope violation: {reln} is not a member of the '
                    f'declared files_touched {sorted(allowed)}')
        if _matches_sensitive(reln, sensitive_globs):
            if not (meta_task_type == 'harness_self_fix' and approval_ok):
                return (f'apply-path scope violation: {reln} targets a protected path '
                        f'(harness/**, config/**, scripts/**); requires '
                        f'meta_task_type=harness_self_fix + operator approval '
                        f'(got meta_task_type={meta_task_type!r}, approval_ok={approval_ok})')
    return None


def _ast_merge(output_code: str, target_code: str) -> str:
    """Merge output_code into target_code at the top level by name.

    Mirrors the inline _auto_commit_accepted in harness/orchestrator.py
    (pre-T10 stopgap). Handled top-level node kinds, each keyed by a
    namespaced tuple to prevent cross-kind collisions:

      * ``ast.FunctionDef`` / ``ast.AsyncFunctionDef`` / ``ast.ClassDef``
        keyed as ``('name', node.name)``. FunctionDef / AsyncFunctionDef
        matched targets are replaced WHOLESALE by the output version (no
        per-method recursive merge for function bodies). G24: matched
        ClassDef targets receive an ADDITIVE class-body merge so target-
        only class attributes (AnnAssign / single-Name Assign) and
        target-only methods (FunctionDef / AsyncFunctionDef) survive
        when the agent's same-name ClassDef omits them; agent's body
        nodes win for matched-name nodes; agent-only nodes append.
        Nested ClassDef inside a ClassDef recurses; recursion depth
        capped at 5 to avoid runaway on pathological input.
      * ``ast.AnnAssign`` with a simple ``ast.Name`` target keyed as
        ``('assign', target.id)``.
      * ``ast.Assign`` with ``len(targets) == 1`` and an ``ast.Name``
        target keyed as ``('assign', targets[0].id)``.
      * ``ast.Import`` (G23a) with a single alias keyed as
        ``('import', alias.asname or alias.name)``. Multi-alias top-
        level Imports are pre-split into single-alias clones before
        keying (see ``_expand_imports`` below) so each imported name
        gets its own merge slot.
      * ``ast.ImportFrom`` (G23a) with a single alias keyed as
        ``('import_from', node.module or '', node.level or 0,
        alias.asname or alias.name)``. The 4-tuple disambiguates
        module name, relative-import level, and bound name, so
        ``from . import foo`` / ``from .. import foo`` / ``from
        foo_module import foo`` do not collide, and ``from x import
        y as z`` (key 'z') and ``from x import y`` (key 'y') coexist
        when present. Multi-alias top-level ImportFroms are
        pre-split into single-alias clones before keying.
      * ``ast.Assign`` with ``len(targets) == 1`` whose single target is
        an ``ast.Tuple`` or ``ast.List`` containing only ``ast.Name``
        elements (G7) keyed as ``('assign_tuple', tuple_of_name_ids)``.

    The namespaced keys (``('name', 'foo')`` vs ``('assign', 'foo')``)
    keep a FunctionDef ``foo`` and a module-level constant ``foo`` in
    distinct slots, so neither shadows the other during the merge.

    All other node kinds -- the module docstring (``ast.Expr`` with
    ``ast.Constant`` value at body[0]), conditional / try blocks,
    ``ast.AugAssign``, star-target / Attribute-target / Subscript-target
    assigns, and ``ast.AnnAssign`` / ``ast.Assign`` with non-Name single
    targets -- yield a None key from the keying step and are preserved
    positionally from the target tree.

    G20: Within the non-keyed-preserve loop, ``ast.AugAssign`` whose
    target is an ``ast.Name`` receives an additional positional-preserve
    guard: if the target's ``.target.id`` already appears as the target
    of any ``ast.AugAssign`` already present in ``tgt_tree.body``, the
    overlay's AugAssign is dropped (target's accumulator wins). NEW
    AugAssign target names that the submission introduces still append
    normally. AugAssign with non-Name target (Attribute, Subscript,
    Starred) falls through to the existing ``ast.dump`` dedup path.

    G23a: Top-level Import / ImportFrom nodes are pre-split per-alias
    before keying. ``from tools import webui_auth, webui_control`` is
    expanded into two single-alias ImportFroms so the agent's
    ``from tools import webui_control`` no longer wholesale-replaces
    the target's ImportFrom and drops webui_auth. The pre-split is
    local to ``_ast_merge`` (mutates only the freshly parsed
    out_tree.body / tgt_tree.body lists) and never recurses into
    FunctionDef / ClassDef bodies.

    G24: When BOTH the agent's out_tree and the target's tgt_tree have
    a top-level ClassDef with the same name (same key from
    ``_node_key``), the matched-key replacement step no longer
    wholesale-replaces target's class with agent's. Instead it invokes
    ``_merge_class_body``, which:
      * Buckets agent's class body into keyed (via ``_node_key``) and
        non-keyed nodes, dropping orphan bare-string docstrings at
        position > 0 to mirror module-level ``out_no_key`` collection.
      * Walks target's class body in order. For each target node whose
        key matches an agent-keyed entry: if both are ClassDef, recurse
        (depth + 1, capped at 5); otherwise agent's node replaces
        target's at that position. Target-only keyed nodes and all
        non-keyed target nodes flow through unchanged.
      * Appends agent-only keyed nodes after the surviving target
        nodes, then non-keyed agent nodes with ast.dump dedup and the
        same AugAssign-by-target-id guard used at module level.
      * Returns agent's ClassDef (with bases / keywords / decorators /
        type_params intact) but with the merged body assigned. Agent
        wins for the class wrapper; target wins for body nodes the
        agent omitted.
    Function / AsyncFunctionDef bodies are NOT recursively merged --
    only class bodies. The recursion cap (5) is a safety belt against
    pathological deeply-nested class hierarchies; beyond it the merge
    falls back to wholesale agent replacement at that depth.

    Nodes that exist only in output (with a non-None key) are appended
    after the loop, matching the prior behaviour for new functions and
    now also covering new constants / typed assignments / per-alias
    from-imports / tuple-target assigns added by the agent.

    When the target tree contains a top-level if __name__ == "__main__":
    guard block, nodes that exist only in output are inserted BEFORE
    that block rather than appended to end-of-body.

    G17: After keyed-replace and before the guard-aware append, run a
    forward-reference reorder pass: helpers (FunctionDef /
    AsyncFunctionDef / ClassDef / Assign / AnnAssign) still in
    out_nodes that are referenced by a top-level Assign/AnnAssign's
    value subtree get inserted BEFORE the earliest referencing node.

    G18d: A JANUSMASK_DELETE comment directive in ``output_code`` lets
    a submission explicitly request deletion of named top-level keyed
    nodes from the target tree.

    Raises on ast.parse failure; caller must catch and fall back.
    """

    def _node_key(node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return ('name', node.name)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            return ('assign', node.target.id)
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            return ('assign', node.targets[0].id)
        if isinstance(node, ast.Import):
            if len(node.names) == 1:
                alias = node.names[0]
                return ('import', alias.asname or alias.name)
            return None
        if isinstance(node, ast.ImportFrom):
            if len(node.names) == 1:
                alias = node.names[0]
                return ('import_from', node.module or '', node.level or 0, alias.asname or alias.name)
            return None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], (ast.Tuple, ast.List)):
            elts = node.targets[0].elts
            if elts and all((isinstance(e, ast.Name) for e in elts)):
                return ('assign_tuple', tuple((e.id for e in elts)))
            return None
        return None

    def _is_main_guard(node) -> bool:
        if not isinstance(node, ast.If):
            return False
        test = node.test
        if not isinstance(test, ast.Compare):
            return False
        if len(test.ops) != 1 or len(test.comparators) != 1:
            return False
        op = test.ops[0]
        if not isinstance(op, (ast.Eq, ast.Is)):
            return False
        left = test.left
        right = test.comparators[0]

        def _is_name_dunder(n):
            return isinstance(n, ast.Name) and n.id == '__name__'

        def _is_main_const(n):
            return isinstance(n, ast.Constant) and n.value == '__main__'
        if _is_name_dunder(left) and _is_main_const(right):
            return True
        if _is_main_const(left) and _is_name_dunder(right):
            return True
        return False

    def _is_bare_string_expr(node) -> bool:
        return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)

    def _def_time_scan_roots(node):
        """Return the subtrees of a top-level node that are evaluated when the
        node itself executes (so a Name in them must already be bound), used by
        the forward-reference reorder. Excludes function/class BODIES, where a
        name resolves at call time and a forward reference is legal. Covers:
        Assign/AnnAssign values (+ AnnAssign annotation); FunctionDef /
        AsyncFunctionDef decorators, return + arg annotations, defaults +
        kw_defaults; ClassDef decorators, bases, keyword values."""
        roots = []
        if isinstance(node, ast.Assign):
            if node.value is not None:
                roots.append(node.value)
        elif isinstance(node, ast.AnnAssign):
            if node.value is not None:
                roots.append(node.value)
            if node.annotation is not None:
                roots.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            roots.extend(node.decorator_list)
            if node.returns is not None:
                roots.append(node.returns)
            a = node.args
            for arg in (*a.posonlyargs, *a.args, *a.kwonlyargs):
                if arg.annotation is not None:
                    roots.append(arg.annotation)
            for special in (a.vararg, a.kwarg):
                if special is not None and special.annotation is not None:
                    roots.append(special.annotation)
            roots.extend((d for d in a.defaults if d is not None))
            roots.extend((d for d in a.kw_defaults if d is not None))
        elif isinstance(node, ast.ClassDef):
            roots.extend(node.decorator_list)
            roots.extend(node.bases)
            roots.extend((kw.value for kw in node.keywords))
        return roots

    def _bound_names(node):
        """Module-level names a top-level node binds (used by the agent-node
        topological stabilization). Covers Import / ImportFrom aliases,
        single-name + tuple/list Assign / AnnAssign targets, and def/class
        names. Star-imports bind nothing knowable -> skipped."""
        names = []
        if isinstance(node, ast.Import):
            for a in node.names:
                names.append(a.asname or a.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name == '*':
                    continue
                names.append(a.asname or a.name)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                names.append(node.target.id)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                for sub in ast.walk(tgt):
                    if isinstance(sub, ast.Name):
                        names.append(sub.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        return names

    def _expand_imports(body):
        """Pre-split top-level multi-alias Import / ImportFrom into single-alias clones.

        Only immediate Module children are expanded; nested imports inside
        FunctionDef / ClassDef bodies are passed through untouched. Each
        clone gets ast.copy_location from the original to preserve
        lineno/col_offset (matters for downstream error messages and the
        forward-reference reorder pass). Returns a new list; the caller
        is responsible for reassigning it to tree.body so the original
        Module object's body identity is preserved but its contents are
        replaced with the expanded form.
        """
        new_body = []
        for node in body:
            if isinstance(node, (ast.Import, ast.ImportFrom)) and len(node.names) > 1:
                for alias in node.names:
                    if isinstance(node, ast.Import):
                        clone = ast.Import(names=[alias])
                    else:
                        clone = ast.ImportFrom(module=node.module, names=[alias], level=node.level)
                    ast.copy_location(clone, node)
                    new_body.append(clone)
            else:
                new_body.append(node)
        return new_body

    def _merge_class_body(agent_class, target_class, depth):
        """G24: additive merge of agent_class.body into target_class.body.

        Mutates and returns agent_class with the merged body assigned.
        Recursion depth is the current nesting level (1 at the first
        class merge). Beyond depth 5, falls back to wholesale agent
        replacement to bound pathological inputs.
        """
        if depth > 5:
            return agent_class
        base_assigned_names = set()
        for node in target_class.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                base_assigned_names.update(_bound_names(node))
        agent_keyed = {}
        agent_no_key = []
        for i, node in enumerate(agent_class.body):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], (ast.Tuple, ast.List)):
                overlay_names = set(_bound_names(node))
                if overlay_names & base_assigned_names:
                    continue
            key = _node_key(node)
            if key is not None:
                agent_keyed[key] = node
                continue
            if i > 0 and _is_bare_string_expr(node):
                continue
            agent_no_key.append(node)
        merged_body = []
        for node in target_class.body:
            key = _node_key(node)
            if key is not None and key in agent_keyed:
                agent_node = agent_keyed[key]
                if isinstance(node, ast.ClassDef) and isinstance(agent_node, ast.ClassDef):
                    merged_body.append(_merge_class_body(agent_node, node, depth + 1))
                else:
                    merged_body.append(agent_node)
                del agent_keyed[key]
            else:
                merged_body.append(node)
        for node in agent_keyed.values():
            merged_body.append(node)
        if agent_no_key:
            existing_augassign_targets = {n.target.id for n in merged_body if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name)}
            existing_dumps = {ast.dump(n, annotate_fields=True, include_attributes=False) for n in merged_body}
            for node in agent_no_key:
                if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and (node.target.id in existing_augassign_targets):
                    continue
                node_dump = ast.dump(node, annotate_fields=True, include_attributes=False)
                if node_dump in existing_dumps:
                    continue
                merged_body.append(node)
                existing_dumps.add(node_dump)
        agent_class.body = merged_body
        return agent_class
    out_tree = ast.parse(output_code)
    tgt_tree = ast.parse(target_code)
    out_tree.body = _expand_imports(out_tree.body)
    deletes = _extract_delete_directives(output_code) if isinstance(output_code, str) else set()
    if deletes:
        matched: set[str] = set()
        new_body = []
        for node in tgt_tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in deletes:
                matched.add(node.name)
                continue
            new_body.append(node)
        tgt_tree.body = new_body
        unmatched = deletes - matched
        if unmatched:
            logging.getLogger(__name__).warning('JANUSMASK_DELETE directive: unmatched names %s', sorted(unmatched))
    tgt_tree.body = _expand_imports(tgt_tree.body)
    seen_tgt_futures = set()
    new_tgt_body = []
    for node in tgt_tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == '__future__':
            names = [alias.name for alias in node.names]
            if all((name in seen_tgt_futures for name in names)):
                continue
            seen_tgt_futures.update(names)
        new_tgt_body.append(node)
    tgt_tree.body = new_tgt_body
    out_futures = []
    new_out_body = []
    for node in out_tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == '__future__':
            out_futures.append(node)
        else:
            new_out_body.append(node)
    out_tree.body = new_out_body
    new_futures_to_insert = []
    for node in out_futures:
        names = [alias.name for alias in node.names]
        if any((name not in seen_tgt_futures for name in names)):
            new_futures_to_insert.append(node)
            seen_tgt_futures.update(names)
    insert_idx = 0
    if tgt_tree.body and _is_bare_string_expr(tgt_tree.body[0]):
        insert_idx = 1
    for node in new_futures_to_insert:
        tgt_tree.body.insert(insert_idx, node)
        insert_idx += 1
    base_assigned_names = set()
    for node in tgt_tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            base_assigned_names.update(_bound_names(node))
    out_nodes = {}
    out_no_key = []
    for i, node in enumerate(out_tree.body):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], (ast.Tuple, ast.List)):
            overlay_names = set(_bound_names(node))
            if overlay_names & base_assigned_names:
                continue
        key = _node_key(node)
        if key is not None:
            out_nodes[key] = node
            continue
        if _is_main_guard(node):
            continue
        if i > 0 and _is_bare_string_expr(node):
            continue
        out_no_key.append(node)
    for i, node in enumerate(tgt_tree.body):
        key = _node_key(node)
        if key is not None and key in out_nodes:
            agent_node = out_nodes[key]
            if isinstance(node, ast.ClassDef) and isinstance(agent_node, ast.ClassDef):
                tgt_tree.body[i] = _merge_class_body(agent_node, node, 1)
            else:
                tgt_tree.body[i] = agent_node
            del out_nodes[key]
    agent_block_ids = {id(n) for n in out_nodes.values()}
    if out_nodes:
        name_lookup = {}
        for key in out_nodes:
            if key[0] in ('name', 'assign', 'import'):
                name_lookup[key[1]] = key
            elif key[0] == 'import_from':
                name_lookup[key[3]] = key
            elif key[0] == 'assign_tuple':
                for nm in key[1]:
                    name_lookup[nm] = key
        if name_lookup:
            records = {}
            for i, node in enumerate(tgt_tree.body):
                for root in _def_time_scan_roots(node):
                    for sub in ast.walk(root):
                        if isinstance(sub, ast.Name) and sub.id in name_lookup:
                            key = name_lookup[sub.id]
                            if key in out_nodes and key not in records:
                                records[key] = i
            for key, idx in sorted(records.items(), key=lambda kv: kv[1], reverse=True):
                tgt_tree.body.insert(idx, out_nodes[key])
                del out_nodes[key]
    guard_idx = next((i for i, n in enumerate(tgt_tree.body) if _is_main_guard(n)), None)
    for node in out_nodes.values():
        if guard_idx is None:
            tgt_tree.body.append(node)
        else:
            tgt_tree.body.insert(guard_idx, node)
            guard_idx += 1
    if out_no_key:
        existing_augassign_targets = {n.target.id for n in tgt_tree.body if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name)}
        existing_dumps = {ast.dump(n, annotate_fields=True, include_attributes=False) for n in tgt_tree.body}
        for node in out_no_key:
            if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and (node.target.id in existing_augassign_targets):
                continue
            node_dump = ast.dump(node, annotate_fields=True, include_attributes=False)
            if node_dump in existing_dumps:
                continue
            if guard_idx is None:
                tgt_tree.body.append(node)
            else:
                tgt_tree.body.insert(guard_idx, node)
                guard_idx += 1
            existing_dumps.add(node_dump)
    if agent_block_ids:
        agent_binders = {}
        for node in tgt_tree.body:
            if id(node) in agent_block_ids:
                for nm in _bound_names(node):
                    agent_binders.setdefault(nm, node)
        for _ in range(len(tgt_tree.body) + 1):
            moved = False
            for i, node in enumerate(tgt_tree.body):
                if id(node) not in agent_block_ids:
                    continue
                refs = {sub.id for root in _def_time_scan_roots(node) for sub in ast.walk(root) if isinstance(sub, ast.Name)}
                for nm in refs:
                    binder = agent_binders.get(nm)
                    if binder is not None and binder is not node and (id(binder) in agent_block_ids):
                        j = tgt_tree.body.index(binder)
                        if j > i:
                            tgt_tree.body.pop(j)
                            tgt_tree.body.insert(i, binder)
                            moved = True
                            break
                if moved:
                    break
            if not moved:
                break
    return ast.unparse(tgt_tree)

def _run_streamed_command(cmd: list[str], cwd: str, timeout: int, check: bool=False) -> subprocess.CompletedProcess:
    """Run a command using Popen, streaming stdout/stderr to logger incrementally."""
    logger = logging.getLogger(__name__)
    with subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as proc:
        output_lines = []
        if proc.stdout:
            for line in proc.stdout:
                line_stripped = line.strip()
                logger.info(f'git: {line_stripped}')
                output_lines.append(line)
        try:
            retcode = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise subprocess.TimeoutExpired(cmd, timeout, ''.join(output_lines))
        stdout_str = ''.join(output_lines)
        if check and retcode != 0:
            raise subprocess.CalledProcessError(retcode, cmd, output=stdout_str)
        return subprocess.CompletedProcess(cmd, retcode, stdout=stdout_str, stderr='')

def _is_tracked(file_path: str, cwd: str) -> bool:
    """Check if a file path is tracked in the repository HEAD / index (before staging)."""
    try:
        res = _run_streamed_command(['git', 'ls-files', '--error-unmatch', '--', file_path], cwd=cwd, timeout=10, check=False)
        return res.returncode == 0
    except Exception:
        return False

def commit_accepted_output(task_id: str, target_file: str, state_dir: pathlib.Path, worktree_root: pathlib.Path | None=None, *, allowed_files=None, meta_task_type=None, approval_ok: bool=False) -> dict:
    """Copy validated output to target, then commit it scoped to target_file.

    Args:
        task_id: The task ID (e.g., 'GIT-COMMIT-001'). Output expected at state/output/<task_id>.py
        target_file: Destination path relative to or absolute within worktree root
        state_dir: Path to state/ directory (used to locate state/output/)
        worktree_root: Optional custom worktree root (e.g. staging workspace)

    Returns:
        A dict with keys:
          - 'committed': bool, True iff commit succeeded
          - 'sha': str or None, the commit SHA if committed=True, else None
          - 'error': str or None, error message if committed=False or any validation failed
          - 'target': str, the target_file path

    Synchronous: all git operations run in the caller's thread; stdout/stderr is
    streamed to the logger in real-time to prevent pipeline stalls.

    G19a-2: If state/output/<task_id>.files.json exists, dispatches to
    _commit_accepted_output_multi for multi-file commit.

    AW10d: If state/output/<task_id>.patches.json exists, dispatches to
    _commit_accepted_output_patches for partial-edit (named symbol/region)
    commit. Both sidecar branches are byte-inert when their sidecar is
    absent; otherwise falls through to the legacy singular path,
    byte-identical to pre-G19a-2.
    """
    result = {'committed': False, 'sha': None, 'error': None, 'target': target_file}
    try:
        if worktree_root is None:
            output = _run_streamed_command(['git', 'rev-parse', '--show-toplevel'], cwd=str(state_dir), timeout=30, check=True)
            worktree_root = pathlib.Path(output.stdout.strip())
        else:
            worktree_root = pathlib.Path(worktree_root)
        parent_output = _run_streamed_command(['git', 'rev-parse', '--show-toplevel'], cwd=str(state_dir), timeout=30, check=True)
        parent_root = pathlib.Path(parent_output.stdout.strip()).resolve()
        try:
            untracked_output = _run_streamed_command(['git', 'status', '--porcelain', 'tests/'], cwd=str(parent_root), timeout=30, check=True)
            untracked_files = []
            import fnmatch
            for line in untracked_output.stdout.splitlines():
                line = line.strip()
                if line.startswith('?? '):
                    filepath = line[3:].strip().strip('"\'')
                    if fnmatch.fnmatch(filepath, 'tests/test_*.py'):
                        untracked_files.append(filepath)
            if untracked_files:
                import json
                sidecar_path = state_dir / 'output' / f'{task_id}.files.json'
                manifest = {}
                if sidecar_path.exists():
                    try:
                        manifest = json.loads(sidecar_path.read_text(encoding='utf-8'))
                    except Exception:
                        manifest = {}
                else:
                    target_path = pathlib.Path(target_file).resolve()
                    try:
                        rel_target = target_path.relative_to(parent_root)
                    except ValueError:
                        try:
                            rel_target = target_path.relative_to(worktree_root)
                        except ValueError:
                            rel_target = pathlib.Path(target_file)
                    output_file = state_dir / 'output' / f'{task_id}.py'
                    if output_file.exists():
                        manifest[str(rel_target)] = output_file.read_text(encoding='utf-8')
                for filepath in untracked_files:
                    file_in_parent = parent_root / filepath
                    if file_in_parent.exists():
                        manifest[filepath] = file_in_parent.read_text(encoding='utf-8')
                sidecar_path.parent.mkdir(parents=True, exist_ok=True)
                sidecar_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        except Exception as e:
            logging.getLogger(__name__).warning('Failed to auto-detect and commit untracked test files: %s', e)
        sidecar_path = state_dir / 'output' / f'{task_id}.files.json'
        if sidecar_path.exists():
            return _commit_accepted_output_multi(task_id, sidecar_path, state_dir, worktree_root, result, allowed_files=allowed_files, meta_task_type=meta_task_type, approval_ok=approval_ok)
        patches_sidecar = state_dir / 'output' / f'{task_id}.patches.json'
        if patches_sidecar.exists():
            return _commit_accepted_output_patches(task_id, patches_sidecar, state_dir, worktree_root, result, allowed_files=allowed_files, meta_task_type=meta_task_type, approval_ok=approval_ok)
        target_path = pathlib.Path(target_file).resolve()
        if worktree_root is not None:
            parent_output = _run_streamed_command(['git', 'rev-parse', '--show-toplevel'], cwd=str(state_dir), timeout=30, check=True)
            parent_root = pathlib.Path(parent_output.stdout.strip()).resolve()
            try:
                rel = target_path.relative_to(parent_root)
                target_path = (worktree_root / rel).resolve()
            except ValueError:
                pass
        try:
            target_path.relative_to(worktree_root)
        except ValueError:
            result['error'] = 'target escapes worktree'
            return result
        scope_err = _enforce_apply_scope([str(target_path.relative_to(worktree_root))], allowed_files=allowed_files, meta_task_type=meta_task_type, approval_ok=approval_ok)
        if scope_err:
            logging.getLogger(__name__).error('commit_accepted_output: %s rejected: %s', task_id, scope_err)
            result['error'] = scope_err
            return result
        is_python_target = str(target_path).endswith('.py')
        output_file = state_dir / 'output' / f'{task_id}.py'
        if not output_file.exists():
            result['error'] = 'no output file'
            return result
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if is_python_target:
            try:
                out_code = output_file.read_text(encoding='utf-8')
                if target_path.exists():
                    tgt_code = target_path.read_text(encoding='utf-8')
                    if out_code == tgt_code:
                        final_code = tgt_code
                    else:
                        final_code = _ast_merge(out_code, tgt_code)
                else:
                    final_code = ast.unparse(ast.parse(out_code))
                target_path.write_text(final_code, encoding='utf-8')
            except Exception as merge_exc:
                # Fail-CLOSED (M3): a whole-file shutil.copy2 fallback would
                # silently discard the target's other top-level symbols on a
                # transient parse/merge error (data loss). Refuse the commit
                # instead of overwriting; the target on disk is left untouched.
                logging.getLogger(__name__).error('commit_accepted_output: AST merge failed for %s (%s); refusing whole-file copy fallback (fail-closed)', task_id, merge_exc)
                result['committed'] = False
                result['sha'] = None
                result['error'] = f'merge_failed: refusing whole-file overwrite to avoid data loss: {merge_exc}'
                return result
        else:
            shutil.copy2(str(output_file), str(target_path))
        rel_target = target_path.relative_to(worktree_root)
        is_tracked = _is_tracked(str(rel_target), str(worktree_root))
        _run_streamed_command(['git', 'add', '--', str(rel_target)], cwd=str(worktree_root), timeout=30, check=True)
        diff_result = _run_streamed_command(['git', 'diff', '--cached', '--quiet', '--', str(rel_target)], cwd=str(worktree_root), timeout=30, check=False)
        if diff_result.returncode == 0:
            logging.getLogger(__name__).warning('commit_accepted_output: %s produced no staged diff against %s (AST merge byte-identical to target); rejecting as no_diff', task_id, str(rel_target))
            result['committed'] = False
            result['error'] = 'no_diff: AST merge produced byte-identical content; no commit created'
            return result
        commit_msg = format_auto_commit_message(task_id)
        if is_tracked:
            _run_streamed_command(['git', 'commit', '--only', '-m', commit_msg, '--', str(rel_target)], cwd=str(worktree_root), timeout=300, check=True)
        else:
            _run_streamed_command(['git', 'commit', '-m', commit_msg], cwd=str(worktree_root), timeout=300, check=True)
        sha_output = _run_streamed_command(['git', 'rev-parse', 'HEAD'], cwd=str(worktree_root), timeout=30, check=True)
        result['committed'] = True
        result['sha'] = sha_output.stdout.strip()
        result['error'] = None
        return result
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        result['committed'] = False
        result['error'] = str(exc)
        result['sha'] = None
        return result
    except Exception as exc:
        result['committed'] = False
        result['error'] = str(exc)
        result['sha'] = None
        return result

def _extract_delete_directives(source: str) -> set[str]:
    """Scan `source` for '# JANUSMASK_DELETE: name1, name2' comment lines.

    Tokenize-scans COMMENT tokens only, so occurrences of the directive
    inside string literals are ignored. Splits the payload on commas,
    strips whitespace per name, filters via ``str.isidentifier()``, and
    unions all matches into a single set. Catches tokenize errors and
    returns an empty set on any failure (warn-not-fail).
    """
    import io
    import tokenize
    names: set[str] = set()
    try:
        tokens = tokenize.tokenize(io.BytesIO(source.encode('utf-8')).readline)
        for tok in tokens:
            if tok.type != tokenize.COMMENT:
                continue
            text = tok.string.lstrip('#').strip()
            if not text.startswith('JANUSMASK_DELETE:'):
                continue
            payload = text[len('JANUSMASK_DELETE:'):]
            for raw in payload.split(','):
                candidate = raw.strip()
                if candidate.isidentifier():
                    names.add(candidate)
    except (tokenize.TokenizeError, SyntaxError, UnicodeDecodeError):
        return set()
    return names

def _apply_file_to_target(out_code: str, target_path: pathlib.Path, task_id: str) -> None:
    """Apply out_code to target_path with AST-merge-or-copy semantics.

    For .py targets: read existing target (if any), AST-merge if out and target
    differ, write final_code. On any merge exception, log warning and write
    out_code verbatim as fallback. For non-.py targets: write out_code verbatim.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if str(target_path).endswith('.py'):
        try:
            if target_path.exists():
                tgt_code = target_path.read_text(encoding='utf-8')
                if out_code == tgt_code:
                    final_code = tgt_code
                else:
                    final_code = _ast_merge(out_code, tgt_code)
            else:
                final_code = ast.unparse(ast.parse(out_code))
            target_path.write_text(final_code, encoding='utf-8')
        except Exception as merge_exc:
            logging.getLogger(__name__).warning('AST merge failed for %s entry %s (%s); writing verbatim', task_id, target_path, merge_exc)
            target_path.write_text(out_code, encoding='utf-8')
    else:
        target_path.write_text(out_code, encoding='utf-8')

def _commit_accepted_output_multi(task_id: str, sidecar_path: pathlib.Path, state_dir: pathlib.Path, worktree_root: pathlib.Path, result: dict, *, allowed_files=None, meta_task_type=None, approval_ok: bool=False) -> dict:
    """Multi-file commit driven by a state/output/<task_id>.files.json sidecar.

    Reads the sidecar (JSON dict mapping rel-path -> source-code string),
    applies each entry via _apply_file_to_target, stages all rel-paths via
    a single git add, runs ONE git commit --only covering all files, and
    returns the same {committed, sha, error, target} dict shape as
    commit_accepted_output. All failure modes return committed=False with
    a descriptive error string and never invoke git commit.
    """
    try:
        manifest_text = sidecar_path.read_text(encoding='utf-8')
        manifest = json.loads(manifest_text)
    except (json.JSONDecodeError, OSError) as exc:
        result['committed'] = False
        result['sha'] = None
        result['error'] = f'sidecar parse: {exc}'
        return result
    if not isinstance(manifest, dict) or not manifest:
        result['committed'] = False
        result['sha'] = None
        result['error'] = 'sidecar empty or non-dict'
        return result
    rel_targets: list[str] = []
    tracked_flags: list[bool] = []
    # Atomicity: validate (worktree-escape + apply-scope) ALL entries FIRST so a
    # scope violation on a later entry cannot leave earlier entries already
    # written to the worktree. Only after every entry passes do we apply writes.
    validated: list[tuple[str, pathlib.Path]] = []
    for rel, src in manifest.items():
        if not isinstance(rel, str) or not isinstance(src, str):
            result['committed'] = False
            result['sha'] = None
            result['error'] = f'sidecar entry has non-string key/value: {rel!r}'
            return result
        target_path = (worktree_root / rel).resolve()
        try:
            target_path.relative_to(worktree_root)
        except ValueError:
            result['committed'] = False
            result['sha'] = None
            result['error'] = f'target escapes worktree: {rel}'
            return result
        rel_str = str(target_path.relative_to(worktree_root))
        scope_err = _enforce_apply_scope([rel_str], allowed_files=allowed_files, meta_task_type=meta_task_type, approval_ok=approval_ok)
        if scope_err:
            logging.getLogger(__name__).error('_commit_accepted_output_multi: %s rejected: %s', task_id, scope_err)
            result['committed'] = False
            result['sha'] = None
            result['error'] = scope_err
            return result
        validated.append((rel_str, target_path))
    for (rel_str, target_path), src in zip(validated, manifest.values()):
        tracked_flags.append(_is_tracked(rel_str, str(worktree_root)))
        try:
            _apply_file_to_target(src, target_path, task_id)
        except OSError as exc:
            result['committed'] = False
            result['sha'] = None
            result['error'] = f'write failed for {rel_str}: {exc}'
            return result
        rel_targets.append(rel_str)
    try:
        _run_streamed_command(['git', 'add', '--'] + rel_targets, cwd=str(worktree_root), timeout=60, check=True)
        diff_result = _run_streamed_command(['git', 'diff', '--cached', '--quiet', '--'] + rel_targets, cwd=str(worktree_root), timeout=30, check=False)
        if diff_result.returncode == 0:
            logging.getLogger(__name__).warning('_commit_accepted_output_multi: %s produced no staged diff against %s (AST merge byte-identical to targets); rejecting as no_diff', task_id, rel_targets)
            result['committed'] = False
            result['sha'] = None
            result['error'] = 'no_diff: AST merge produced byte-identical content; no commit created'
            return result
        commit_msg = format_auto_commit_message(task_id)
        if all(tracked_flags):
            _run_streamed_command(['git', 'commit', '--only', '-m', commit_msg, '--'] + rel_targets, cwd=str(worktree_root), timeout=300, check=True)
        else:
            _run_streamed_command(['git', 'commit', '-m', commit_msg], cwd=str(worktree_root), timeout=300, check=True)
        sha_output = _run_streamed_command(['git', 'rev-parse', 'HEAD'], cwd=str(worktree_root), timeout=30, check=True)
        result['committed'] = True
        result['sha'] = sha_output.stdout.strip()
        result['error'] = None
        result['target'] = str(sidecar_path)
        return result
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        result['committed'] = False
        result['sha'] = None
        result['error'] = str(exc)
        return result
import json
"G23a: per-alias additive merge for top-level Import / ImportFrom.\n\nCloses the import-drop class surfaced by session #11's BSP1b regression.\n``_node_key`` keyed ImportFrom per-module, so when target had multiple\nImportFrom statements from the same module and the agent body listed\nonly a subset, the agent's node wholesale-replaced target's and\ntarget-only names were dropped.\n\nFix is two-part and confined to ``_ast_merge``:\n\n  1. ``_node_key`` keys single-alias ``ast.Import`` / ``ast.ImportFrom``\n     at per-imported-name granularity:\n       ``ast.Import``      -> ``('import', alias.asname or alias.name)``\n       ``ast.ImportFrom``  -> ``('import_from', module or '',\n                              level or 0, alias.asname or alias.name)``\n     Multi-alias nodes still return ``None`` from ``_node_key`` itself\n     (the pre-split below makes that path unreachable for top-level\n     nodes).\n\n  2. A new local ``_expand_imports`` pass walks each Module's immediate\n     ``.body``, replaces any top-level multi-alias Import / ImportFrom\n     with one single-alias clone per alias (``ast.copy_location`` from\n     the original to preserve lineno/col_offset), and feeds the\n     expanded body into the existing keyed-merge. The pre-split is\n     local to ``_ast_merge``: it builds a fresh list and reassigns\n     ``out_tree.body`` / ``tgt_tree.body``, but never mutates the\n     callers' original Module objects (callers pass strings; the trees\n     are parsed inside _ast_merge anyway).\n\nNested imports inside FunctionDef / ClassDef bodies are NOT touched --\nonly immediate Module children are expanded.\n\nAll other merge semantics (FunctionDef / AsyncFunctionDef / ClassDef\nwholesale-replace, AnnAssign / Assign / AugAssign keying, tuple-target\nassigns, main-guard insert, bare-string-expr filter, forward-reference\nreorder, JANUSMASK_DELETE directive) are preserved unchanged.\n\nSource-only change for G23a; regression tests land in G23b.\n"
from harness.commit_message_formatter import format_auto_commit_message

def _parse_patches(code: str) -> list[dict] | None:
    """Detect and parse a ``__JANUSMASK_PATCHES__`` partial-edit submission.

    Structurally parallel to ``_parse_manifest`` (harness/orchestrator.py),
    but the assignment value is an ``ast.List`` of ``ast.Dict`` entries
    instead of a single ``ast.Dict``. Returns a ``list[dict]`` of decoded
    ``{str: str}`` entries when *code* parses to a top-level single-target
    ``Assign`` whose ``ast.Name`` target id is ``__JANUSMASK_PATCHES__`` and
    whose value is an ``ast.List`` where every element is an ``ast.Dict`` of
    ``ast.Constant`` string keys -> ``ast.Constant`` string values, and each
    decoded entry passes per-kind validation:

      * ``'file'`` and ``'kind'`` are present;
      * ``kind`` is one of ``{'symbol', 'region'}``;
      * ``kind == 'symbol'`` requires ``'name'`` and ``'code'``;
      * ``kind == 'region'`` requires ``'marker'`` and ``'code'``.

    Returns ``None`` (never raises) on: ``SyntaxError``; no/wrong-name/
    multi-target ``Assign``; non-``List`` value; any non-``Dict`` element;
    any non-string-``Constant`` key or value; missing required key; or
    unknown ``kind``. Mirrors ``_parse_manifest``'s None-on-malformed
    discipline. ``__JANUSMASK_PATCHES__`` keys strictly on the target name,
    so it never collides with ``__JANUSMASK_MANIFEST__``.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id != '__JANUSMASK_PATCHES__':
            continue
        if not isinstance(node.value, ast.List):
            return None
        result: list[dict] = []
        for element in node.value.elts:
            if not isinstance(element, ast.Dict):
                return None
            entry: dict[str, str] = {}
            for k, v in zip(element.keys, element.values):
                if not isinstance(k, ast.Constant) or not isinstance(k.value, str):
                    return None
                if not isinstance(v, ast.Constant) or not isinstance(v.value, str):
                    return None
                entry[k.value] = v.value
            if 'file' not in entry or 'kind' not in entry:
                return None
            kind = entry['kind']
            if kind not in ('symbol', 'region'):
                return None
            if kind == 'symbol' and ('name' not in entry or 'code' not in entry):
                return None
            if kind == 'region' and ('marker' not in entry or 'code' not in entry):
                return None
            result.append(entry)
        return result
    return None

def _apply_symbol_patch(source: str, qualname: str, new_block: str) -> str:
    """Text-slice-replace the def/class named by *qualname* with *new_block*.

    Resolves *qualname* as either a top-level ``FunctionDef`` /
    ``AsyncFunctionDef`` / ``ClassDef`` (single name) or a dotted
    ``Outer.inner`` lookup (the ``ClassDef`` ``Outer`` then a def/class
    named ``inner`` in its body). The located node's ``lineno`` /
    ``end_lineno`` (extended upward to the first decorator's ``lineno`` when
    decorators are present) drive a raw line-slice replacement of exactly
    that block, preserving every byte outside it. For a nested target the
    replacement is re-indented to the located node's ``col_offset``.

    *new_block* must itself ``ast.parse`` to exactly one def/class node whose
    leaf name equals *qualname*'s leaf -- otherwise ``ValueError`` (prevents
    an agent silently renaming the symbol or smuggling extra top-level
    statements). Raises ``KeyError`` when *qualname* is not found.
    """
    tree = ast.parse(source)
    parts = qualname.split('.')
    leaf_name = parts[-1]

    def _is_def(n: ast.AST) -> bool:
        return isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    if len(parts) == 1:
        located = None
        for n in tree.body:
            if _is_def(n) and n.name == leaf_name:
                located = n
                break
        if located is None:
            raise KeyError(qualname)
    elif len(parts) == 2:
        outer_name, inner_name = parts
        outer = None
        for n in tree.body:
            if isinstance(n, ast.ClassDef) and n.name == outer_name:
                outer = n
                break
        if outer is None:
            raise KeyError(qualname)
        located = None
        for n in outer.body:
            if _is_def(n) and n.name == inner_name:
                located = n
                break
        if located is None:
            raise KeyError(qualname)
    else:
        raise KeyError(qualname)
    try:
        nb_tree = ast.parse(new_block)
    except SyntaxError as exc:
        raise ValueError(f'new_block is not parseable Python: {exc}')
    nb_defs = [n for n in nb_tree.body if _is_def(n)]
    if len(nb_tree.body) != 1 or len(nb_defs) != 1:
        raise ValueError('new_block must be exactly one def/class node')
    if nb_defs[0].name != leaf_name:
        raise ValueError(f'new_block defines {nb_defs[0].name!r}, expected {leaf_name!r}')
    start_lineno = located.lineno
    decorators = getattr(located, 'decorator_list', None)
    if decorators:
        start_lineno = min((d.lineno for d in decorators))
    end_lineno = located.end_lineno
    lines = source.splitlines(keepends=True)
    before = lines[:start_lineno - 1]
    replaced = lines[start_lineno - 1:end_lineno]
    after = lines[end_lineno:]
    new_text = new_block
    col_offset = getattr(located, 'col_offset', 0) or 0
    if col_offset > 0:
        indent = ' ' * col_offset
        new_text = ''.join((indent + ln if ln.strip() else ln for ln in new_text.splitlines(keepends=True)))
    orig_ends_nl = bool(replaced) and replaced[-1].endswith('\n')
    if (after or orig_ends_nl) and (not new_text.endswith('\n')):
        new_text += '\n'
    return ''.join(before) + new_text + ''.join(after)

def _apply_region_patch(source: str, sentinel: str, new_region: str) -> str:
    """Replace the lines strictly between a sentinel-delimited region.

    Operates on raw text only (NEVER ``ast.parse`` -- language-agnostic, so
    ``.js`` and other non-Python targets round-trip). Finds exactly one line
    whose stripped text equals ``'# JANUSMASK_REGION:' + sentinel`` and
    exactly one whose stripped text equals
    ``'# JANUSMASK_ENDREGION:' + sentinel``, replaces the lines strictly
    between (exclusive of) the two sentinel lines with *new_region*, and
    preserves both sentinel lines and all surrounding text.

    Raises ``KeyError`` on zero or multiple start/end sentinel matches
    (duplicate-sentinel safety prevents ambiguous splices) and ``ValueError``
    when the end sentinel precedes the start.
    """
    start_token = '# JANUSMASK_REGION:' + sentinel
    end_token = '# JANUSMASK_ENDREGION:' + sentinel
    lines = source.splitlines(keepends=True)
    start_idxs = [i for i, ln in enumerate(lines) if ln.strip() == start_token]
    end_idxs = [i for i, ln in enumerate(lines) if ln.strip() == end_token]
    if len(start_idxs) != 1:
        raise KeyError(f'expected exactly one start sentinel {start_token!r}, found {len(start_idxs)}')
    if len(end_idxs) != 1:
        raise KeyError(f'expected exactly one end sentinel {end_token!r}, found {len(end_idxs)}')
    start_i = start_idxs[0]
    end_i = end_idxs[0]
    if end_i <= start_i:
        raise ValueError(f'end sentinel precedes start sentinel for {sentinel!r}')
    before = lines[:start_i + 1]
    after = lines[end_i:]
    new_text = new_region
    if new_text and (not new_text.endswith('\n')):
        new_text += '\n'
    return ''.join(before) + new_text + ''.join(after)

def _commit_accepted_output_patches(task_id, patches_sidecar_path, state_dir, worktree_root, result, *, allowed_files=None, meta_task_type=None, approval_ok=False):
    """Partial-edit commit driven by a ``state/output/<task_id>.patches.json`` sidecar.

    Modeled on ``_commit_accepted_output_multi``: loads the JSON list of
    ``{file, kind, name|marker, code}`` entries, groups them by ``'file'``
    (preserving first-seen order), and for each file resolves
    ``(worktree_root / rel).resolve()`` with a ``relative_to`` worktree-escape
    guard, reads the on-disk target text, and applies each entry in list
    order via ``_apply_symbol_patch`` (kind=symbol) or ``_apply_region_patch``
    (kind=region). Multiple entries to one file compose because each apply
    operates on the already-modified text and ``_apply_symbol_patch``
    re-parses that in-progress text per call (so shifted line offsets are
    recomputed). It then runs the SAME ``git add`` / ``git diff --cached
    --quiet`` no_diff guard / ``format_auto_commit_message`` / ``git commit
    --only`` / ``git rev-parse HEAD`` tail as ``_commit_accepted_output_multi``
    and returns the ``{committed, sha, error, target}`` dict shape.

    ``KeyError`` / ``ValueError`` from the appliers and ``OSError`` from
    read/write are converted to ``committed=False`` with a descriptive error;
    git commit is never invoked on failure.
    """
    try:
        sidecar_text = patches_sidecar_path.read_text(encoding='utf-8')
        entries = json.loads(sidecar_text)
    except (json.JSONDecodeError, OSError) as exc:
        result['committed'] = False
        result['sha'] = None
        result['error'] = f'patches sidecar parse: {exc}'
        return result
    if not isinstance(entries, list) or not entries:
        result['committed'] = False
        result['sha'] = None
        result['error'] = 'patches sidecar empty or non-list'
        return result
    grouped: dict[str, list[dict]] = {}
    order: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            result['committed'] = False
            result['sha'] = None
            result['error'] = f'patches entry not a dict: {entry!r}'
            return result
        rel = entry.get('file')
        kind = entry.get('kind')
        if not isinstance(rel, str) or kind not in ('symbol', 'region'):
            result['committed'] = False
            result['sha'] = None
            result['error'] = f'patches entry malformed: {entry!r}'
            return result
        if rel not in grouped:
            grouped[rel] = []
            order.append(rel)
        grouped[rel].append(entry)
    rel_targets: list[str] = []
    tracked_flags: list[bool] = []
    # Atomicity: validate (worktree-escape + apply-scope) ALL rels FIRST so a
    # scope violation on a later entry cannot leave earlier entries already
    # written to the worktree. Only after every rel passes do we apply patches.
    validated: list[tuple[str, str, pathlib.Path]] = []
    for rel in order:
        target_path = (worktree_root / rel).resolve()
        try:
            target_path.relative_to(worktree_root)
        except ValueError:
            result['committed'] = False
            result['sha'] = None
            result['error'] = f'target escapes worktree: {rel}'
            return result
        rel_str = str(target_path.relative_to(worktree_root))
        scope_err = _enforce_apply_scope([rel_str], allowed_files=allowed_files, meta_task_type=meta_task_type, approval_ok=approval_ok)
        if scope_err:
            logging.getLogger(__name__).error('_commit_accepted_output_patches: %s rejected: %s', task_id, scope_err)
            result['committed'] = False
            result['sha'] = None
            result['error'] = scope_err
            return result
        validated.append((rel, rel_str, target_path))
    for rel, rel_str, target_path in validated:
        tracked_flags.append(_is_tracked(rel_str, str(worktree_root)))
        try:
            text = target_path.read_text(encoding='utf-8')
        except OSError as exc:
            result['committed'] = False
            result['sha'] = None
            result['error'] = f'read failed for {rel}: {exc}'
            return result
        try:
            for entry in grouped[rel]:
                if entry['kind'] == 'symbol':
                    text = _apply_symbol_patch(text, entry['name'], entry['code'])
                else:
                    text = _apply_region_patch(text, entry['marker'], entry['code'])
        except (KeyError, ValueError) as exc:
            result['committed'] = False
            result['sha'] = None
            result['error'] = f'patch apply failed for {rel}: {exc}'
            return result
        try:
            target_path.write_text(text, encoding='utf-8')
        except OSError as exc:
            result['committed'] = False
            result['sha'] = None
            result['error'] = f'write failed for {rel}: {exc}'
            return result
        rel_targets.append(rel_str)
    try:
        _run_streamed_command(['git', 'add', '--'] + rel_targets, cwd=str(worktree_root), timeout=60, check=True)
        diff_result = _run_streamed_command(['git', 'diff', '--cached', '--quiet', '--'] + rel_targets, cwd=str(worktree_root), timeout=30, check=False)
        if diff_result.returncode == 0:
            logging.getLogger(__name__).warning('_commit_accepted_output_patches: %s produced no staged diff against %s (patches byte-identical to targets); rejecting as no_diff', task_id, rel_targets)
            result['committed'] = False
            result['sha'] = None
            result['error'] = 'no_diff: patches produced byte-identical content; no commit created'
            return result
        commit_msg = format_auto_commit_message(task_id)
        if all(tracked_flags):
            _run_streamed_command(['git', 'commit', '--only', '-m', commit_msg, '--'] + rel_targets, cwd=str(worktree_root), timeout=300, check=True)
        else:
            _run_streamed_command(['git', 'commit', '-m', commit_msg], cwd=str(worktree_root), timeout=300, check=True)
        sha_output = _run_streamed_command(['git', 'rev-parse', 'HEAD'], cwd=str(worktree_root), timeout=30, check=True)
        result['committed'] = True
        result['sha'] = sha_output.stdout.strip()
        result['error'] = None
        result['target'] = str(patches_sidecar_path)
        return result
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        result['committed'] = False
        result['sha'] = None
        result['error'] = str(exc)
        return result

def create_staging_worktree(staging_path: str, parent_root: str | pathlib.Path | None=None) -> None:
    """Prunes stale worktrees, handles existing paths, and creates a staging worktree."""
    import logging
    import shutil
    import pathlib
    import subprocess
    logger = logging.getLogger(__name__)
    staging_path_obj = pathlib.Path(staging_path).resolve()
    if parent_root is None:
        try:
            res = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True, check=True)
            parent_root_obj = pathlib.Path(res.stdout.strip()).resolve()
        except Exception:
            parent_root_obj = pathlib.Path(__file__).resolve().parent.parent
    else:
        parent_root_obj = pathlib.Path(parent_root).resolve()
    cwd_str = str(parent_root_obj)
    if staging_path_obj.parent != parent_root_obj.parent:
        raise ValueError('Staging worktree must be placed in a sibling directory of the repository root.')
    try:
        subprocess.run(['git', 'worktree', 'prune'], cwd=cwd_str, check=True, capture_output=True, text=True)
    except subprocess.SubprocessError as e:
        logger.warning(f'git worktree prune failed: {e}')
    try:
        res = subprocess.run(['git', 'worktree', 'list', '--porcelain'], cwd=cwd_str, check=True, capture_output=True, text=True)
        worktrees = []
        for line in res.stdout.splitlines():
            if line.startswith('worktree '):
                worktrees.append(pathlib.Path(line[9:]).resolve())
    except Exception:
        worktrees = []
    if staging_path_obj in worktrees or staging_path_obj.exists():
        logger.info(f'Staging path {staging_path} is already a worktree or exists. Removing.')
        try:
            subprocess.run(['git', 'worktree', 'remove', '-f', str(staging_path_obj)], cwd=cwd_str, check=False, capture_output=True)
        except Exception:
            pass
        if staging_path_obj.is_dir():
            shutil.rmtree(staging_path_obj, ignore_errors=True)
        elif staging_path_obj.exists():
            staging_path_obj.unlink(missing_ok=True)
    cmd = ['git', 'worktree', 'add', '--detach', str(staging_path_obj)]
    try:
        subprocess.run(cmd, cwd=cwd_str, check=True, capture_output=True, text=True)
        logger.info(f'Created staging worktree at {staging_path}')
    except subprocess.CalledProcessError as e:
        logger.error(f'Failed to create staging worktree: {e.stderr}')
        raise

def remove_staging_worktree(staging_path: str, parent_root: str | pathlib.Path | None=None) -> None:
    """Removes the staging worktree cleanly."""
    import logging
    import shutil
    import pathlib
    import subprocess
    logger = logging.getLogger(__name__)
    staging_path_obj = pathlib.Path(staging_path).resolve()
    if parent_root is None:
        try:
            res = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True, check=True)
            parent_root_obj = pathlib.Path(res.stdout.strip()).resolve()
        except Exception:
            parent_root_obj = pathlib.Path(__file__).resolve().parent.parent
    else:
        parent_root_obj = pathlib.Path(parent_root).resolve()
    cwd_str = str(parent_root_obj)
    try:
        subprocess.run(['git', 'worktree', 'prune'], cwd=cwd_str, check=False, capture_output=True)
    except Exception:
        pass
    try:
        subprocess.run(['git', 'worktree', 'remove', '-f', str(staging_path_obj)], cwd=cwd_str, check=True, capture_output=True, text=True)
        logger.info(f'Removed staging worktree reference for {staging_path}')
    except subprocess.CalledProcessError as e:
        logger.warning(f'git worktree remove failed: {e.stderr}')
        try:
            subprocess.run(['git', 'worktree', 'prune'], cwd=cwd_str, check=True, capture_output=True)
        except Exception:
            pass
    if staging_path_obj.exists():
        shutil.rmtree(staging_path_obj, ignore_errors=True)
        logger.info(f'Deleted staging directory at {staging_path}')

def merge_staging_to_parent(staging_path: pathlib.Path, parent_root: pathlib.Path | None = None) -> None:
    """Merges the HEAD commit from staging_path back to the parent repository."""
    import logging
    import time
    logger = logging.getLogger(__name__)

    # 1. Get HEAD commit of staging
    try:
        res = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=str(staging_path), check=True, capture_output=True, text=True)
        staging_sha = res.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to get staging HEAD: {e.stderr}")
        raise RuntimeError(f"Failed to get staging HEAD: {e.stderr}")

    # 2. Get parent repo root
    if parent_root is None:
        try:
            res_common = subprocess.run(['git', 'rev-parse', '--git-common-dir'], cwd=str(staging_path), check=True, capture_output=True, text=True)
            git_common = pathlib.Path(res_common.stdout.strip())
            if not git_common.is_absolute():
                git_common = (staging_path / git_common).resolve()
            if git_common.name == '.git':
                parent_root = git_common.parent
            else:
                # Inside git worktrees structure: .git/worktrees/<name>
                parent_root = git_common.parent.parent
        except Exception:
            parent_root = pathlib.Path(__file__).resolve().parent.parent

    logger.info(f"Merging staging commit {staging_sha} into parent repo at {parent_root}")

    stashed = False
    try:
        # M-b/M-c: WHOLE-TREE stash (no pathspec). If the parent working tree
        # has ANY local changes, stash the entire tree -- including untracked
        # files (-u) -- so the fast-forward merge can never collide with dirty
        # or untracked content ('untracked working tree files would be
        # overwritten by merge'). Detect dirtiness with a pathspec-less
        # `git status --porcelain`.
        res_status = subprocess.run(['git', 'status', '--porcelain'], cwd=str(parent_root), capture_output=True, text=True, check=False)
        if res_status.stdout.strip():
            logger.info("Parent repository working tree is dirty; stashing whole tree before merge.")
            cmd_stash = ['git', 'stash', 'push', '-u', '-m', f'janusmask-pre-merge-{int(time.time())}']
            try:
                stash_res = subprocess.run(cmd_stash, cwd=str(parent_root), capture_output=True, text=True, check=True)
            except subprocess.CalledProcessError as stash_exc:
                # Fail-closed: do NOT swallow the stash failure and proceed into
                # a doomed merge. Raise BEFORE any merge is attempted; the
                # finally below removes the staging worktree on the way out.
                logger.error(f"Failed to stash parent repository working tree before merge: {stash_exc.stderr}")
                raise RuntimeError(f"Failed to stash parent repository working tree before merge: {stash_exc.stderr}")
            if "No local changes to save" not in stash_res.stdout:
                stashed = True

        subprocess.run(['git', 'merge', '--ff-only', staging_sha], cwd=str(parent_root), check=True, capture_output=True, text=True)
        logger.info("Fast-forward merge successful.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Fast-forward merge failed: {e.stderr}")
        raise RuntimeError(f"Fast-forward merge failed: {e.stderr}")
    finally:
        if stashed:
            logger.info("Restoring parent repository local changes from stash.")
            pop = subprocess.run(['git', 'stash', 'pop'], cwd=str(parent_root), capture_output=True, text=True, check=False)
            if pop.returncode != 0:
                # G-M-POPCONFLICT: the local stash conflicts with the just-merged
                # commit. The merged commit content WINS; discard the conflicted
                # partial pop and drop the stranded stash so we never hand back an
                # unmerged (UU) tree or an orphaned stash.
                logger.error(f"Stash pop conflicted after merge; resolving to merged content (stash dropped): {pop.stderr}")
                subprocess.run(['git', 'reset', '--hard', 'HEAD'], cwd=str(parent_root), capture_output=True, text=True, check=False)
                subprocess.run(['git', 'stash', 'drop'], cwd=str(parent_root), capture_output=True, text=True, check=False)
        remove_staging_worktree(str(staging_path), parent_root=parent_root)
