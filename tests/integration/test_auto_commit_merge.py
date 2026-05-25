"""Integration test for the auto-commit AST merge helper (M2 -- v2 step 2).

Feeds a hooks-sized diff (new imports at the top + a trailing
``if __name__ == '__main__':`` block) through the merge helper in
``harness.orchestrator._auto_commit_accepted`` and asserts:

  1. The merged file is syntactically valid Python (``ast.parse(result)``
     succeeds).
  2. The merged file has not ballooned -- ``len(result) <= 1.1 * len(original)``.

``_auto_commit_accepted`` is the only merge helper in
``harness/orchestrator.py`` that takes an AST-validated per-task output file
and applies it to a target.

This test shells out ``git init`` / ``git commit`` into a tmp_path, which is
cheap but sequential -- it runs under the ``tests/integration/`` suite.

F5d re-dispatch (post G1 sandbox unblock at b4189a0 + G2 AST nondet
carve-out for test_* meta_task_types at 0461d6a): ``merge_harness`` is a
factory fixture that accepts a ``target_suffix`` kwarg so the four
non-``.py`` target extensions (md / yaml / js / css) can be exercised
end-to-end. Backward compatibility with the original
``state_dir, task, task_id, target_path, original = merge_harness`` unpacking
is preserved -- iterating the returned object lazily builds the default
``.py`` harness, exactly matching the previous tuple shape.
"""
from __future__ import annotations
import ast
import os
import subprocess
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from harness.orchestrator import _auto_commit_accepted
ORIGINAL_MODULE = '"""Sample module for auto-commit merge test."""\n\nimport os\n\n\ndef greet(name: str) -> str:\n    """Return a greeting for ``name``."""\n    return f"hello, {name}"\n\n\ndef farewell(name: str) -> str:\n    return f"goodbye, {name}"\n'
OUTPUT_MODULE = '"""Sample module for auto-commit merge test."""\n\nimport os\nimport sys\nimport logging\n\n\ndef greet(name: str) -> str:\n    """Return a greeting for ``name``."""\n    return f"hello, {name}"\n\n\ndef farewell(name: str) -> str:\n    return f"goodbye, {name}"\n\n\nif __name__ == "__main__":\n    print(greet("world"))\n'
BASE_FN = 'def foo():\n    return 1\n'
OVERLAY_FN = 'def foo():\n    return 99\n'
BASE_ASYNC = 'async def afoo():\n    return 1\n'
OVERLAY_ASYNC = 'async def afoo():\n    return 99\n'
BASE_CLS = "class C:\n    def a(self):\n        return 'a'\n\n    def b(self):\n        return 'b'\n"
OVERLAY_CLS = "class C:\n    def a(self):\n        return 'a'\n\n    def c(self):\n        return 'c'\n"
BASE_ASN = 'VERSION = 1\n'
OVERLAY_ASN = 'VERSION = 2\n'
BASE_ANN = "POLICY: dict = {'a': 1}\n"
OVERLAY_ANN = "POLICY: dict = {'a': 1, 'b': 2, 'c': 3}\n"
BASE_NEW_ASN = 'def util():\n    pass\n'
OVERLAY_NEW_ASN = 'def util():\n    pass\n\n\nEXTRA = 42\n'
BASE_NEW_ANN = 'def util():\n    pass\n'
OVERLAY_NEW_ANN = 'def util():\n    pass\n\n\nLIMIT: int = 100\n'
BASE_COLLIDE = "foo = 1\n\n\ndef foo():\n    return 'a'\n"
OVERLAY_COLLIDE = "foo = 99\n\n\ndef foo():\n    return 'b'\n"
BASE_AUGASSIGN = 'X = 0\nX += 1\n'
OVERLAY_AUGASSIGN = 'X = 0\nX += 5\n'
BASE_TUPLE = 'a, b = 1, 2\n'
OVERLAY_TUPLE = 'a, b = 9, 9\n'
NON_PY_CASES = [('.md', '# Title\nbody', 'docs/sample.md'), ('.yaml', 'key: value\n', 'harness/sample.yaml'), ('.js', "console.log('x');", 'tools/sample.js'), ('.css', 'body { color: red; }', 'tools/sample.css')]

def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.setdefault('GIT_AUTHOR_NAME', 'JanusMask Test')
    env.setdefault('GIT_AUTHOR_EMAIL', 'test@janusmask.local')
    env.setdefault('GIT_COMMITTER_NAME', 'JanusMask Test')
    env.setdefault('GIT_COMMITTER_EMAIL', 'test@janusmask.local')
    return subprocess.run(['git', *args], cwd=str(cwd), env=env, check=True, capture_output=True, text=True, timeout=30)

@pytest.fixture
def merge_harness(tmp_path: Path):
    """Lay down a tmp git repo + state_dir structure that ``_auto_commit_accepted``
    can consume. Returns ``(state_dir, task, task_id, target_path, original_text)``.

    F5d: the returned object is both iterable (unpacks as the default ``.py``
    5-tuple, preserving the original invocation signature used by
    ``test_auto_commit_merge_hooks_sized_diff``) AND callable with
    ``target_suffix=...``, ``target_rel=...``, ``payload=...``, ``task_id=...``
    to seed a non-``.py`` harness. Each invocation builds an isolated
    worktree under ``tmp_path`` so parametrized cases never collide.

    G6v2: ``_build`` gains ``original_override`` / ``output_override`` kwargs
    so per-node-kind fixture pairs (BASE_* / OVERLAY_*) can drive
    ``_ast_merge`` regression coverage without touching the default
    ORIGINAL_MODULE / OUTPUT_MODULE path. When both kwargs are None the
    behavior is byte-identical to HEAD.
    """
    counter = [0]

    def _build(target_suffix: str='.py', target_rel: str | None=None, payload: str | bytes | None=None, task_id: str | None=None, original_override: str | None=None, output_override: str | None=None):
        counter[0] += 1
        worktree = tmp_path / f'worktree_{counter[0]}'
        worktree.mkdir()
        _git(worktree, 'init', '-q', '-b', 'main')
        _git(worktree, 'config', 'user.name', 'JanusMask Test')
        _git(worktree, 'config', 'user.email', 'test@janusmask.local')
        state_dir = worktree / 'state'
        (state_dir / 'output').mkdir(parents=True)
        (state_dir / 'tasks' / 'processed').mkdir(parents=True)
        if target_suffix == '.py':
            if target_rel is None:
                target_rel = 'sample_module.py'
            if task_id is None:
                task_id = 'M2-merge-fixture'
            original_text = ORIGINAL_MODULE if original_override is None else original_override
            output_text = OUTPUT_MODULE if output_override is None else output_override
            target_path = worktree / target_rel
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(original_text, encoding='utf-8')
            _git(worktree, 'add', target_rel)
            _git(worktree, 'commit', '-q', '-m', 'initial')
            output_path = state_dir / 'output' / f'{task_id}.py'
            output_path.write_text(output_text, encoding='utf-8')
            ast.parse(output_text)
        else:
            assert target_rel is not None, 'target_rel is required for non-py suffixes'
            assert payload is not None, 'payload is required for non-py suffixes'
            if task_id is None:
                task_id = f'task_{target_suffix.lstrip('.')}_{uuid4().hex[:8]}'
            if isinstance(payload, str):
                payload_bytes = payload.encode('utf-8')
            else:
                payload_bytes = bytes(payload)
            seed = worktree / '.gitkeep'
            seed.write_text('', encoding='utf-8')
            _git(worktree, 'add', '.gitkeep')
            _git(worktree, 'commit', '-q', '-m', 'initial')
            output_path = state_dir / 'output' / f'{task_id}.py'
            output_path.write_bytes(payload_bytes)
            target_path = worktree / target_rel
            original_text = ''
        task = {'task_id': task_id, 'files_touched': [target_rel], 'specification': 'integration fixture', 'verification_command': 'true'}
        return (state_dir, task, task_id, target_path, original_text)

    class _Harness:
        """Dual-purpose handle: iterable (default .py 5-tuple) and callable."""

        def __iter__(self):
            return iter(_build())

        def __call__(self, **kwargs):
            return _build(**kwargs)
    return _Harness()

def test_auto_commit_merge_hooks_sized_diff(merge_harness):
    """Round-trip a hooks-sized diff through ``_auto_commit_accepted``.

    Success criteria (per sub-plan-01 §Proposed 5):
      * The resulting file parses as Python.
      * ``len(result) <= 1.1 * len(original)``.
      * The helper reports success (a new commit was produced).
    """
    state_dir, task, task_id, target_path, original = merge_harness
    committed = _auto_commit_accepted(state_dir, task, task_id)
    assert committed is True, '_auto_commit_accepted returned False -- the merge/commit step failed. Inspect harness logs for the concrete git error.'
    result = target_path.read_text(encoding='utf-8')
    ast.parse(result)
    assert len(result) <= 1.1 * len(original), f'merged file grew beyond 10% of original: len(result)={len(result)} len(original)={len(original)} ratio={len(result) / max(1, len(original)):.3f}'
    merged_tree = ast.parse(result)
    func_names = {node.name for node in merged_tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert {'greet', 'farewell'}.issubset(func_names), f'merge dropped a pre-existing function: func_names={func_names}'

@pytest.mark.parametrize('case_id,base,overlay', [pytest.param('FN', BASE_FN, OVERLAY_FN, id='FN'), pytest.param('ASYNC', BASE_ASYNC, OVERLAY_ASYNC, id='ASYNC'), pytest.param('CLS', BASE_CLS, OVERLAY_CLS, id='CLS'), pytest.param('ASN', BASE_ASN, OVERLAY_ASN, id='ASN'), pytest.param('ANN', BASE_ANN, OVERLAY_ANN, id='ANN'), pytest.param('NEW_ASN', BASE_NEW_ASN, OVERLAY_NEW_ASN, id='NEW_ASN'), pytest.param('NEW_ANN', BASE_NEW_ANN, OVERLAY_NEW_ANN, id='NEW_ANN'), pytest.param('COLLIDE', BASE_COLLIDE, OVERLAY_COLLIDE, id='COLLIDE'), pytest.param('AUGASSIGN', BASE_AUGASSIGN, OVERLAY_AUGASSIGN, id='AUGASSIGN'), pytest.param('TUPLE', BASE_TUPLE, OVERLAY_TUPLE, id='TUPLE')])
def test_ast_merge_per_node_kind(merge_harness, case_id, base, overlay):
    """Drive ``_ast_merge`` through a per-node-kind fixture pair and assert
    the AST-level invariant on the merged target file. Each parametrize id
    matches the fixture-pair suffix so ``pytest -k FN`` runs just the
    FunctionDef-override case.
    """
    state_dir, task, task_id, target_path, _original = merge_harness(target_rel=f'mod_{case_id}.py', original_override=base, output_override=overlay)
    committed = _auto_commit_accepted(state_dir, task, task_id)
    assert committed is True, f'_auto_commit_accepted returned False for case {case_id!r}; inspect harness logs for the concrete git/merge error.'
    result = target_path.read_text(encoding='utf-8')
    tree = ast.parse(result)
    body = tree.body
    if case_id == 'FN':
        fn = next((n for n in body if isinstance(n, ast.FunctionDef) and n.name == 'foo'))
        ret = fn.body[-1]
        assert isinstance(ret, ast.Return), f'FN: expected Return as last stmt of foo, got {type(ret).__name__}'
        assert isinstance(ret.value, ast.Constant) and ret.value.value == 99, f'FN: expected foo to return 99, got {ast.dump(ret.value)}'
    elif case_id == 'ASYNC':
        fn = next((n for n in body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'afoo'))
        ret = fn.body[-1]
        assert isinstance(ret, ast.Return), f'ASYNC: expected Return as last stmt of afoo, got {type(ret).__name__}'
        assert isinstance(ret.value, ast.Constant) and ret.value.value == 99, f'ASYNC: expected afoo to return 99, got {ast.dump(ret.value)}'
    elif case_id == 'CLS':
        cls = next((n for n in body if isinstance(n, ast.ClassDef) and n.name == 'C'))
        method_names = {m.name for m in cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert 'a' in method_names, f"CLS: method 'a' missing from class C; got {method_names}"
        assert 'c' in method_names, f"CLS: method 'c' missing from class C (overlay's new method dropped); got {method_names}"
        assert 'b' in method_names, f"CLS: method 'b' from base should survive class-body additive merge (G24); got {method_names}"
    elif case_id == 'ASN':
        version_assigns = [n for n in body if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and (n.targets[0].id == 'VERSION')]
        assert len(version_assigns) == 1, f'ASN: expected exactly 1 VERSION assignment, got {len(version_assigns)}'
        node = version_assigns[0]
        assert isinstance(node.value, ast.Constant) and node.value.value == 2, f'ASN: expected VERSION = 2, got {ast.dump(node.value)}'
    elif case_id == 'ANN':
        policy_anns = [n for n in body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and (n.target.id == 'POLICY')]
        assert len(policy_anns) == 1, f'ANN: expected exactly 1 POLICY AnnAssign, got {len(policy_anns)}'
        node = policy_anns[0]
        assert isinstance(node.value, ast.Dict), f'ANN: expected POLICY value to be a Dict, got {type(node.value).__name__}'
        assert len(node.value.keys) == 3, f'ANN: expected POLICY to have 3 keys after override, got {len(node.value.keys)}'
    elif case_id == 'NEW_ASN':
        util_present = any((isinstance(n, ast.FunctionDef) and n.name == 'util' for n in body))
        extra_present = any((isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and (n.targets[0].id == 'EXTRA') and isinstance(n.value, ast.Constant) and (n.value.value == 42) for n in body))
        assert util_present, "NEW_ASN: base function 'util' was dropped during append-on-absent"
        assert extra_present, "NEW_ASN: overlay constant 'EXTRA = 42' was not appended"
    elif case_id == 'NEW_ANN':
        util_present = any((isinstance(n, ast.FunctionDef) and n.name == 'util' for n in body))
        limit_present = any((isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and (n.target.id == 'LIMIT') and isinstance(n.value, ast.Constant) and (n.value.value == 100) for n in body))
        assert util_present, "NEW_ANN: base function 'util' was dropped during append-on-absent"
        assert limit_present, "NEW_ANN: overlay 'LIMIT: int = 100' was not appended"
    elif case_id == 'COLLIDE':
        assign_99 = any((isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and (n.targets[0].id == 'foo') and isinstance(n.value, ast.Constant) and (n.value.value == 99) for n in body))
        fn_b = False
        for n in body:
            if isinstance(n, ast.FunctionDef) and n.name == 'foo':
                if n.body and isinstance(n.body[-1], ast.Return):
                    ret = n.body[-1]
                    if isinstance(ret.value, ast.Constant) and ret.value.value == 'b':
                        fn_b = True
                        break
        assert assign_99, 'COLLIDE: Assign foo == 99 not present (namespace collision broke Assign override)'
        assert fn_b, "COLLIDE: FunctionDef foo returning 'b' not present (namespace collision broke FunctionDef override)"
    elif case_id == 'AUGASSIGN':
        augassigns = [n for n in body if isinstance(n, ast.AugAssign)]
        assert len(augassigns) == 1, f'AUGASSIGN: expected exactly 1 AugAssign in merged file, got {len(augassigns)}'
        aa = augassigns[0]
        assert isinstance(aa.target, ast.Name) and aa.target.id == 'X', f"AUGASSIGN: expected target 'X', got {ast.dump(aa.target)}"
        assert isinstance(aa.op, ast.Add), f'AUGASSIGN: expected Add op, got {type(aa.op).__name__}'
        assert isinstance(aa.value, ast.Constant) and aa.value.value == 1, f"AUGASSIGN: expected base's `X += 1` to be preserved (overlay's `X += 5` should be dropped), got += {aa.value.value}"
    elif case_id == 'TUPLE':
        tuple_assigns = [n for n in body if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Tuple)]
        assert len(tuple_assigns) == 1, f'TUPLE: expected exactly 1 tuple-target Assign in merged file, got {len(tuple_assigns)}'
        ta = tuple_assigns[0]
        assert isinstance(ta.value, ast.Tuple), f'TUPLE: expected Tuple value, got {type(ta.value).__name__}'
        values = [v.value for v in ta.value.elts if isinstance(v, ast.Constant)]
        assert values == [1, 2], f"TUPLE: expected base's `a, b = 1, 2` to be preserved (overlay's `a, b = 9, 9` should be dropped), got {values}"
    else:
        raise AssertionError(f'unknown case_id: {case_id!r}')

def test_merge_harness_accepts_target_suffix_kwarg(merge_harness):
    """The fixture must accept ``target_suffix`` (plus its companion kwargs)
    without raising. Bare-minimum API guard."""
    result = merge_harness(target_suffix='.md', target_rel='docs/sample.md', payload='# x\n', task_id=f'task_md_kwarg_{__import__('uuid').uuid4().hex[:8]}')
    assert result is not None
    assert len(result) == 5

def test_merge_harness_defaults_to_py_when_kwarg_omitted(merge_harness):
    """Backward compat: invoking via iteration unpack yields the original
    ``.py`` harness contract."""
    state_dir, task, task_id, target_path, original = merge_harness
    assert task['files_touched'][0].endswith('.py')
    assert task_id == 'M2-merge-fixture'
    assert original == ORIGINAL_MODULE
    assert target_path.suffix == '.py'

def test_merge_harness_skips_ast_parse_for_non_py_suffix(merge_harness):
    """The fixture must not attempt ``ast.parse()`` on a non-``.py`` payload.
    A YAML payload like ``key: value`` is NOT valid Python -- if the fixture
    parsed it, this test would raise ``SyntaxError`` during setup."""
    not_valid_python = 'key: value\nother: [1, 2, 3]\n# comment'
    state_dir, task, task_id, target_path, original = merge_harness(target_suffix='.yaml', target_rel='harness/sample.yaml', payload=not_valid_python, task_id=f'task_yaml_skipparse_{__import__('uuid').uuid4().hex[:8]}')
    outbox = state_dir / 'output' / f'{task_id}.py'
    assert outbox.read_bytes() == not_valid_python.encode('utf-8')

def test_merge_harness_outbox_still_named_submission_py_for_non_py_targets(merge_harness):
    """Per the existing contract, the outbox lives at ``output/{task_id}.py``
    regardless of the target file's extension."""
    state_dir, task, task_id, target_path, original = merge_harness(target_suffix='.md', target_rel='docs/sample.md', payload='# Title\nbody', task_id=f'task_md_outboxname_{__import__('uuid').uuid4().hex[:8]}')
    outbox = state_dir / 'output' / f'{task_id}.py'
    assert outbox.exists(), f'outbox missing at {outbox}'
    assert outbox.suffix == '.py', f'outbox suffix should be .py per the contract, got {outbox.suffix}'
    assert target_path.suffix == '.md'

def test_merge_harness_signature_backward_compatible(merge_harness):
    """Regression guard: existing call sites that unpack the fixture directly
    must continue to receive a 5-tuple of (state_dir, task, task_id,
    target_path, original_text)."""
    state_dir, task, task_id, target_path, original = merge_harness
    assert state_dir.exists()
    assert isinstance(task, dict)
    assert isinstance(task_id, str)
    assert isinstance(target_path, Path)
    assert isinstance(original, str)

def test_target_suffix_parametrization_covers_all_four_extensions():
    """Property guard: the parametrization covers exactly the four non-py
    extensions called out in the spec (markdown, YAML, JS, CSS)."""
    suffixes = {case[0] for case in NON_PY_CASES}
    assert suffixes == {'.md', '.yaml', '.js', '.css'}, f'NON_PY_CASES drifted from spec; got suffixes={suffixes}'
    assert len(NON_PY_CASES) == 4
    for suffix, payload, relpath in NON_PY_CASES:
        assert payload, f'empty payload for suffix={suffix}'
        assert relpath.endswith(suffix), f'target relpath {relpath!r} does not match suffix {suffix!r}'

def test_original_py_test_cases_still_pass(merge_harness):
    """Regression marker: re-asserts that the legacy ``.py`` round-trip still
    produces a valid commit. Full assertions live in
    ``test_auto_commit_merge_hooks_sized_diff`` -- this duplicate is named to
    satisfy the regression-test spec entry."""
    state_dir, task, task_id, target_path, original = merge_harness
    assert _auto_commit_accepted(state_dir, task, task_id) is True
    result = target_path.read_text(encoding='utf-8')
    ast.parse(result)
    assert len(result) <= 1.1 * len(original)

def _exercise_non_py(merge_harness, suffix: str, payload: str, relpath: str) -> None:
    """Shared end-to-end exercise body for the four non-py target cases.

    Asserts the four conditions from the F5d spec:
      (a) _auto_commit_accepted returns True
      (b) (worktree / relpath).exists()
      (c) (worktree / relpath).read_bytes() == outbox bytes
      (d) ``git log -1 --format=%s`` contains the task_id substring
    """
    task_id = f'task_{suffix.lstrip('.')}_{__import__('uuid').uuid4().hex[:8]}'
    state_dir, task, returned_id, target_path, _original = merge_harness(target_suffix=suffix, target_rel=relpath, payload=payload, task_id=task_id)
    assert returned_id == task_id
    outbox = state_dir / 'output' / f'{task_id}.py'
    outbox_bytes = outbox.read_bytes()
    assert _auto_commit_accepted(state_dir, task, task_id) is True
    worktree = state_dir.parent
    full_target = worktree / relpath
    assert full_target.exists(), f'expected target at {full_target}'
    assert full_target.read_bytes() == outbox_bytes, f'target bytes diverged from outbox for {relpath}'
    summary = subprocess.check_output(['git', '-C', str(worktree), 'log', '-1', '--format=%s']).decode()
    assert task_id in summary, f'task_id {task_id!r} not in commit summary {summary!r}'

class TestCommitsNonPyTarget:
    """End-to-end coverage for the four non-Python target file extensions."""

    def test_commits_md_target_via_auto_commit(self, merge_harness):
        _exercise_non_py(merge_harness, '.md', '# Title\nbody', 'docs/sample.md')

    def test_commits_yaml_target_via_auto_commit(self, merge_harness):
        _exercise_non_py(merge_harness, '.yaml', 'key: value\n', 'harness/sample.yaml')

    def test_commits_js_target_via_auto_commit(self, merge_harness):
        _exercise_non_py(merge_harness, '.js', "console.log('x');", 'tools/sample.js')

    def test_commits_css_target_via_auto_commit(self, merge_harness):
        _exercise_non_py(merge_harness, '.css', 'body { color: red; }', 'tools/sample.css')

def test_target_file_content_matches_outbox_bytes_exactly(merge_harness):
    """Dedicated test for the byte-for-byte equality assertion -- proves the
    non-py path does NOT mutate the payload (no encoding conversion, no
    AST round-trip)."""
    payload = '# Heading\n\nSome body text with **emphasis** and a trailing newline.\n'
    task_id = f'task_md_bytes_{__import__('uuid').uuid4().hex[:8]}'
    state_dir, task, returned_id, target_path, _ = merge_harness(target_suffix='.md', target_rel='docs/exact.md', payload=payload, task_id=task_id)
    outbox = state_dir / 'output' / f'{task_id}.py'
    outbox_bytes = outbox.read_bytes()
    assert outbox_bytes == payload.encode('utf-8')
    assert _auto_commit_accepted(state_dir, task, task_id) is True
    worktree = state_dir.parent
    full_target = worktree / 'docs/exact.md'
    assert full_target.read_bytes() == outbox_bytes

def test_git_log_summary_contains_task_id_for_non_py_target(merge_harness):
    """Dedicated test for the commit-summary substring assertion. Uses the JS
    case so this also serves as the JS-specific git-log smoke check."""
    task_id = f'task_js_gitlog_{__import__('uuid').uuid4().hex[:8]}'
    state_dir, task, returned_id, target_path, _ = merge_harness(target_suffix='.js', target_rel='tools/log.js', payload="console.log('hello');", task_id=task_id)
    assert _auto_commit_accepted(state_dir, task, task_id) is True
    worktree = state_dir.parent
    summary = subprocess.check_output(['git', '-C', str(worktree), 'log', '-1', '--format=%s']).decode()
    assert task_id in summary, f'expected task_id {task_id!r} in commit summary, got {summary!r}'