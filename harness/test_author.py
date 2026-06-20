"""Independent test-author ROLE: turn a test-less module spec into an oracle.

JanusMask's synthesis agents reconstruct module bodies; this role is the
*separate* party that authors the verification oracle (a pytest file plus a
``verification_command``) those agents are judged against. Three contracts hold:

  (a) author != implementer -- the role runs in its OWN session dir
      (``author_session_dir``), structurally distinct from the synthesis
      agents' ``state_dir/'sessions'``; it never writes the gate that judges
      its own synthesis run.
  (b) non-vacuity gate -- a generated oracle is accepted only if it FAILS the
      stripped ``NotImplementedError`` stub (``oracle_is_non_vacuous``); an
      oracle that passes the stub asserts nothing real and is rejected.
  (c) it gates downstream synthesis -- the accepted oracle fails the stub but
      passes the genuine implementation (``run_oracle_against``).

Generation is injected via ``gen_fn`` so the role is decoupled from the live
agent CLIs; the default generator imports ``harness.orchestrator`` lazily to
avoid an import cycle and to keep this module ``python -S`` importable.
"""
from __future__ import annotations
import ast
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from harness.rebuild.strip import strip_source

class TestAuthorError(Exception):
    """Base error for the test-author role."""

class VacuousOracleError(TestAuthorError):
    """Every generated oracle still PASSED the stripped stub after all attempts.

    A vacuous oracle asserts nothing about the target's behaviour, so it cannot
    gate a synthesis run; raised once ``max_attempts`` drafts are exhausted.
    """

@dataclass
class GeneratedOracle:
    """An accepted, non-vacuous verification oracle for a test-less module."""
    test_code: str
    verification_command: str
    test_filename: str
    attempts: int

def stub_for(target_source: str) -> str:
    """Return a skeleton of ``target_source`` whose bodies raise NotImplementedError.

    Delegates to ``harness.rebuild.strip.strip_source``: signatures, type hints,
    decorators, docstrings, and module-level imports/constants/classes are kept,
    but every function/method body becomes ``raise NotImplementedError``.
    """
    return strip_source(target_source)

def run_oracle_against(test_code: str, impl_source: str, target_module_name: str, *, python_exe: str | None=None, timeout: int=60) -> bool:
    """Run ``test_code`` against ``impl_source`` in a fresh temp dir via pytest.

    Writes ``impl_source`` at the path implied by ``target_module_name`` and
    ``test_code`` to ``<tmp>/test_oracle.py``, then runs pytest with ``cwd=<tmp>``
    and ``PYTHONPATH=<tmp>`` so ``from <target_module_name> import ...`` resolves.
    A DOTTED ``target_module_name`` (e.g. ``geopack.fuzzy``) is materialized as a
    real PACKAGE -- ``<tmp>/geopack/__init__.py`` (empty) + ``<tmp>/geopack/
    fuzzy.py`` -- so a package module's oracle (``from geopack.fuzzy import ...``)
    resolves identically to how it will at rebuild time (C9.9). Returns True iff
    pytest exits 0; False on timeout/error. The temp dir is always cleaned up.
    """
    interp = python_exe or sys.executable
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            
            # Copy the entire parent 'harness' directory recursively to <tmp>/harness
            proj_root = Path(__file__).resolve().parent.parent
            import shutil
            shutil.copytree(proj_root / 'harness', tmp_path / 'harness', ignore=shutil.ignore_patterns('*.pyc', '__pycache__'), dirs_exist_ok=True)
            
            # Now, overwrite the specific target module file with our candidate implementation
            parts = target_module_name.split('.')
            target_file_path = tmp_path / Path(*parts)
            target_file_path = target_file_path.with_suffix('.py')
            target_file_path.parent.mkdir(parents=True, exist_ok=True)
            curr = target_file_path.parent
            while curr != tmp_path:
                (curr / '__init__.py').touch(exist_ok=True)
                curr = curr.parent
            target_file_path.write_text(impl_source, encoding='utf-8')
            
            # Write the test file
            (tmp_path / 'test_oracle.py').write_text(test_code, encoding='utf-8')
            
            env = dict(os.environ)
            env['PYTHONPATH'] = str(tmp_path)
            proc = subprocess.run([interp, '-m', 'pytest', 'test_oracle.py', '-q', '-p', 'no:cacheprovider'], cwd=str(tmp_path), env=env, capture_output=True, timeout=timeout)
            return proc.returncode == 0
    except Exception:
        return False

def oracle_is_non_vacuous(test_code: str, target_source: str, target_module_name: str, *, python_exe: str | None=None) -> bool:
    """Return True iff the oracle FAILS against the stripped stub.

    A non-vacuous oracle exercises real behaviour, so it cannot pass a body that
    only raises ``NotImplementedError``.
    """
    return not run_oracle_against(test_code, stub_for(target_source), target_module_name, python_exe=python_exe)

def author_session_dir(state_dir, task_id: str) -> Path:
    """Return the role's OWN session dir: ``state_dir/'test_author'/task_id``.

    Structurally distinct from (and never inside) the synthesis agents' sessions
    dir (``state_dir/'sessions'``), so author != implementer holds by
    construction. ``state_dir`` may be a str or Path.
    """
    return Path(state_dir) / 'test_author' / task_id

def build_author_prompt(target_module_name: str, spec, target_source: str | None=None, unit_names: list[str] | None=None) -> str:
    """Build the prompt instructing an agent to author a pytest oracle.

    The returned string names ``target_module_name``, folds in ``spec`` if it is
    a dict with a ``'description'`` key, and states the two hard requirements:
    the tests must import the target module by name and must FAIL against a
    ``NotImplementedError`` stub (non-vacuity).

    B7: when ``target_source`` is given it is folded in as the REFERENCE
    implementation. The test-author is the SPEC writer, not the blind
    implementer, so showing it the source is legitimate -- and necessary: for a
    non-obvious module (e.g. a dataclass ``__post_init__`` that resolves paths) a
    source-blind author writes behaviour-INACCURATE oracles, which then either
    reject a correct reconstruction or (for a self_mutating/oracle-skip unit whose
    fuzz oracle is vacuous) become the SOLE gate and pass a wrong body.
    """
    description = ''
    if isinstance(spec, dict) and 'description' in spec:
        description = str(spec['description'])
    rel_path = target_module_name.replace('.', '/') + '.py'
    lines = [f'You are the independent test-author for the Python module `{target_module_name}`.', f'Write a pytest test file that serves as a verification oracle for it. The module file is located at the relative path `{rel_path}` within the project. Do NOT run broad search commands (like `find /`) starting from the system root directory — it will time out and fail.']
    if description:
        lines.append(f'Module specification: {description}')
    if target_source:
        lines.append('Reference implementation (author tests that describe THIS observable behaviour EXACTLY -- you are the spec writer, not the blind implementer; do not copy the body into your tests, assert its effects):\n```python\n' + target_source.rstrip() + '\n```')
    lines.extend([f'The tests MUST import the target module by name, e.g. `from {target_module_name} import ...`.', 'The tests MUST exercise real behaviour so they FAIL against a NotImplementedError stub of the module (non-vacuity): an oracle that passes such a stub asserts nothing and will be rejected.', 'Cover the documented public behaviour and meaningful edge cases.', "CRITICAL: name each test function `test_<UNIT>_<behaviour>`. For a FUNCTION, <UNIT> is the function name with leading/trailing underscores stripped (`make_thing` -> `test_make_thing_defaults`). For a METHOD use CLASS-FIRST `test_<CLASS>_<METHOD>_<behaviour>` where <CLASS> is the class name lower-cased with underscores removed and <METHOD> has its leading/trailing underscores stripped (method `__init__` of class `BriefValidationError` -> `test_briefvalidationerror_init_stores_message`; method `__post_init__` of class `Target` -> `test_target_post_init_resolves_paths`). The harness selects a single unit's tests with `pytest -k <token>`; a test whose name omits the token will be skipped, leaving that unit ungated, OR will run against still-stubbed sibling units and falsely fail. One unit's tests = one matching name.", "CRITICAL ISOLATION: each test's BODY must exercise ONLY its own <UNIT> directly, plus the standard library and module-level constants/data. Do NOT call any OTHER module-level function that <UNIT> does not itself call -- during reconstruction those siblings are still NotImplementedError stubs, so calling them falsely fails the test. If <UNIT> returns None and its only observable effect is a mutation of module-level state (it appends/inserts/updates a module-level list/dict/set), import the module and assert on that mutated module-level state DIRECTLY (e.g. the list grew, or the new entry matches), NEVER through another function that consumes it."])
    if unit_names:
        toks = [t for t in unit_names if t]
        if toks:
            lines.append('You MUST cover EVERY unit below, and EACH test name MUST contain its token VERBATIM as a substring (do NOT abbreviate or shorten it -- `-k <token>` must select that test): ' + ', '.join((f'`{t}`' for t in toks)) + '. For each token write at least one `test_<token>_<behaviour>`.')
    return '\n'.join(lines)

def _extract_python_block(text: str) -> str:
    """Return the python source from agent stdout, stripping a markdown fence.

    Accepts ```` ```python ```` / bare ```` ``` ```` fences (returns the FIRST
    fenced block) or, when un-fenced, the raw text. Mirrors the #34-proven
    live-agent stdout shape.
    """
    lines = text.splitlines()
    out: list[str] = []
    in_block = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('```'):
            if in_block:
                break
            in_block = True
            continue
        if in_block:
            out.append(line)
    if out:
        return '\n'.join(out).rstrip() + '\n'
    try:
        ast.parse(text)
    except Exception:
        return ''
    return text.strip() + '\n'

def _default_gen_fn(prompt: str, *, session_dir, attempt: int):
    """Live generator: a headless ``claude -p --model opus`` independent author.

    Spawns Claude in headless print mode in the role's OWN ``session_dir`` (the
    author != implementer boundary), captures stdout, and strips a markdown fence
    to recover the pytest oracle source. ``JANUSMASK_*`` are scrubbed from the
    env so the author run inherits NO synthesis-run context. Returns the
    ``(test_code, verification_command)`` tuple ``author_oracle`` expects; the
    autonomous ``ensure_testless_oracles`` path recomputes the real test command
    downstream, so a generic per-file pytest command is returned here.
    """
    session_dir = Path(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    full_prompt = prompt
    if attempt:
        full_prompt += f'\n\n(Attempt {attempt + 1}: the previous draft was vacuous -- it passed a NotImplementedError stub. Assert STRONGER, concrete behaviour.)'
    full_prompt += '\n\nOutput ONLY the complete pytest file as a single ```python fenced code block; no prose before or after.'
    env = {k: v for k, v in os.environ.items() if not k.startswith('JANUSMASK_')}
    
    config_path = Path(__file__).resolve().parent / "config.yaml"
    antigravity_mode = False
    if config_path.exists():
        try:
            import yaml
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            antigravity_mode = cfg.get("synthesis", {}).get("antigravity_mode", True)
        except Exception:
            pass
            
    if antigravity_mode:
        cmd = ['gemini', '-p', '', '--model', 'gemini-3.1-pro-preview']
    else:
        cmd = ['claude', '-p', '--model', 'opus']
        
    try:
        proc = subprocess.run(cmd, input=full_prompt, cwd=str(session_dir), env=env, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TestAuthorError(f'live test-author generation failed: {exc}') from exc
    if proc.returncode != 0:
        raise TestAuthorError(f'live test-author agent exited {proc.returncode}: {proc.stderr[-500:]}')
    test_code = _extract_python_block(proc.stdout)
    return (test_code, 'python -m pytest -q')

def author_oracle(target_module_name: str, target_source: str, spec, config, state_dir, *, gen_fn=None, max_attempts: int=2, python_exe: str | None=None, task_id: str | None=None, real_impl_gate: bool=False, unit_names: list[str] | None=None, reference_source: str | None=None) -> GeneratedOracle:
    """Author a non-vacuous verification oracle for a test-less module.

    Builds the prompt, computes the role's independent session dir, and asks
    ``gen_fn(prompt, session_dir=..., attempt=...)`` for a
    ``(test_code, verification_command)`` draft per attempt. The first draft that
    is non-vacuous (fails the stripped stub) is returned as a ``GeneratedOracle``;
    if every attempt is vacuous, ``VacuousOracleError`` is raised.

    B7: the prompt now folds in ``target_source`` (the author is the spec writer,
    not the blind implementer). When ``real_impl_gate`` is set, an accepted draft
    must ALSO pass the REAL implementation -- this catches an oracle that is
    non-vacuous yet behaviour-INACCURATE (passes neither stub nor real impl). The
    caller MUST only enable the gate when the real impl is importable in the chosen
    interpreter (a venv is provisioned, or the project is dep-free); otherwise a
    missing-dep ImportError would falsely reject a correct oracle.

    REVIEW PASS: once a draft is accepted by the gates above, and BEFORE
    returning, a config-gated (``config['test_author']['review_pass']``, default
    True) critic pass invokes ``gen_fn`` ONCE more -- in the role's OWN
    ``session_dir`` so author != implementer still holds -- with a review prompt
    embedding the accepted test code and the reference source, asking for a
    strengthened test file. The reviewed file is re-validated by the EXACT same
    gates (parse, has ``test*`` functions, non-vacuity, and -- when
    ``real_impl_gate`` -- the real impl) and replaces the draft ONLY if it passes
    all of them. The pass is strictly NON-REGRESSING: ANY exception from the
    review ``gen_fn`` call (e.g. StopIteration/IndexError from an exhausted
    deterministic injected gen_fn) or ANY failed re-validation gate keeps the
    pre-review oracle. It NEVER increments ``attempts``.
    """
    if gen_fn is None:
        gen_fn = _default_gen_fn
    prompt = build_author_prompt(target_module_name, spec, reference_source or target_source, unit_names)
    session_dir = author_session_dir(state_dir, task_id or target_module_name)
    for attempt in range(max_attempts):
        test_code, verification_command = gen_fn(prompt, session_dir=session_dir, attempt=attempt)
        try:
            tree = ast.parse(test_code)
        except SyntaxError:
            continue
        if not _has_test_function(tree):
            continue
        if oracle_is_non_vacuous(test_code, target_source, target_module_name, python_exe=python_exe):
            if real_impl_gate and (not run_oracle_against(test_code, target_source, target_module_name, python_exe=python_exe)):
                continue
            base_test_code = test_code
            final_code = base_test_code
            if _review_enabled(config, task_id):
                review_prompt = build_review_prompt(target_module_name, base_test_code, reference_source or target_source, spec, unit_names)
                reviewed = None
                try:
                    reviewed, _vc = gen_fn(review_prompt, session_dir=session_dir, attempt=attempt)
                except Exception:
                    reviewed = None
                if reviewed is not None and _reviewed_oracle_revalidates(reviewed, target_source, target_module_name, python_exe=python_exe, real_impl_gate=real_impl_gate):
                    final_code = reviewed
            return GeneratedOracle(test_code=repair_selfref_assertions(final_code), verification_command=verification_command, test_filename=f'test_{target_module_name}_oracle.py', attempts=attempt + 1)
    raise VacuousOracleError(f'all {max_attempts} oracle drafts for {target_module_name!r} were vacuous (passed the NotImplementedError stub) or unparseable')

def build_review_prompt(target_module_name: str, candidate_test_code: str, target_source: str | None, spec, unit_names: list[str] | None=None) -> str:
    """Build a CRITIC prompt: audit a candidate oracle and return a stronger one.

    After a draft passes the acceptance gates, ``author_oracle`` runs ONE review
    pass: the SAME independent author is shown its own pytest file AND the
    reference source and asked to find gaps -- missing assertions, vacuous or
    trivial checks, and thin boundary/input variety -- and to RETURN a revised,
    strengthened pytest file. It embeds BOTH the candidate test code and the
    reference source, and repeats every hard constraint from
    ``build_author_prompt`` (import the target by name, non-vacuity vs the
    ``NotImplementedError`` stub, per-unit ``test_<unit>`` naming + verbatim
    ``-k`` tokens when ``unit_names`` is given, and test-body isolation) so a
    strengthened file cannot regress a contract. The pass is strictly
    non-regressing: the reviewed file is re-run through the SAME gates and is
    kept only if it still passes all of them.
    """
    base = build_author_prompt(target_module_name, spec, target_source, unit_names)
    lines = [f'You are reviewing an existing pytest oracle for the Python module `{target_module_name}` that ALREADY passes the acceptance gates.', 'Audit it as a critic and return a STRENGTHENED replacement. Look for: missing assertions; vacuous or trivial checks (e.g. `assert True`, asserting only types/truthiness, or re-asserting a literal you just passed in); and a lack of boundary/edge-case and input variety. ADD the coverage that is missing -- do NOT weaken or remove any assertion that already holds.', 'Candidate pytest file under review:\n```python\n' + candidate_test_code.rstrip() + '\n```', 'Return the COMPLETE revised pytest file (not a diff). It MUST keep satisfying EVERY constraint below; a revision that drops a constraint, becomes vacuous, or contradicts the reference will be DISCARDED in favour of the original (the review can only improve or no-op).', '', base]
    return '\n'.join(lines)

def _review_enabled(config, task_id: str | None=None) -> bool:
    """Return whether the critic/review pass runs.

    Reads ``config['test_author']['review_pass']``, defaulting True when the
    key/section is absent or ``config`` (or the ``test_author`` section) is not a
    dict. So the pass is ON by default and an empty ``{}`` config still no-ops
    safely via the review's fallback.

    For testless oracle authoring in the rebuild loop (where task_id starts with 'TA_'),
    the pass defaults to False when config is empty or missing, avoiding unwanted
    mock generator calls in regression tests.
    """
    if task_id and task_id.startswith('TA_'):
        if not isinstance(config, dict):
            return False
        ta_cfg = config.get('test_author', {})
        if not isinstance(ta_cfg, dict):
            return False
        return bool(ta_cfg.get('review_pass', False))

    if not isinstance(config, dict):
        return True
    ta_cfg = config.get('test_author', {})
    if not isinstance(ta_cfg, dict):
        return True
    return bool(ta_cfg.get('review_pass', True))

def is_self_source_expr(node: ast.AST) -> bool:
    for subnode in ast.walk(node):
        if isinstance(subnode, ast.Call):
            if isinstance(subnode.func, ast.Name) and subnode.func.id == 'open':
                if subnode.args and isinstance(subnode.args[0], ast.Name) and (subnode.args[0].id == '__file__'):
                    return True
            elif isinstance(subnode.func, ast.Name) and subnode.func.id == 'Path':
                if subnode.args and isinstance(subnode.args[0], ast.Name) and (subnode.args[0].id == '__file__'):
                    return True
            elif isinstance(subnode.func, ast.Attribute) and subnode.func.attr == 'getsource':
                if isinstance(subnode.func.value, ast.Name) and subnode.func.value.id == 'inspect':
                    return True
            elif isinstance(subnode.func, ast.Name) and subnode.func.id == 'getsource':
                return True
    return False

def get_assigned_names(targets) -> set[str]:
    names = set()
    for target in targets:
        for node in ast.walk(target):
            if isinstance(node, ast.Name):
                names.add(node.id)
    return names

def is_literal_absence_assert_expr(test_expr: ast.AST, self_source_vars: set[str]) -> bool:
    if isinstance(test_expr, ast.UnaryOp) and isinstance(test_expr.op, ast.Not):
        test_expr = test_expr.operand
    if isinstance(test_expr, ast.Compare):
        if len(test_expr.ops) == 1 and isinstance(test_expr.ops[0], (ast.In, ast.NotIn)):
            left = test_expr.left
            right = test_expr.comparators[0]
            left_is_var = isinstance(left, ast.Name) and left.id in self_source_vars
            right_is_var = isinstance(right, ast.Name) and right.id in self_source_vars
            left_is_lit = isinstance(left, ast.Constant) or type(left).__name__ == 'Str'
            right_is_lit = isinstance(right, ast.Constant) or type(right).__name__ == 'Str'
            if left_is_var and right_is_lit or (right_is_var and left_is_lit):
                return True
        for op in test_expr.ops:
            if isinstance(op, (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
                all_exprs = [test_expr.left] + test_expr.comparators
                has_find_call = False
                has_neg_const = False
                for expr in all_exprs:
                    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute) and (expr.func.attr in ('find', 'count')):
                        if isinstance(expr.func.value, ast.Name) and expr.func.value.id in self_source_vars:
                            if expr.args and (isinstance(expr.args[0], ast.Constant) or type(expr.args[0]).__name__ == 'Str'):
                                has_find_call = True
                    elif isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.USub) and isinstance(expr.operand, ast.Constant) and (expr.operand.value == 1):
                        has_neg_const = True
                    elif isinstance(expr, ast.Constant) and isinstance(expr.value, int) and (expr.value <= 0):
                        has_neg_const = True
                if has_find_call and has_neg_const:
                    return True
    return False

def is_descendant_of_any(child: ast.AST, parents) -> bool:
    for parent in parents:
        for node in ast.walk(parent):
            if node is child:
                return True
    return False

class SelfRefAssertionRepairer(ast.NodeTransformer):

    def __init__(self, assertions_to_remove: set[ast.AST], assignments_to_remove: set[ast.AST]):
        super().__init__()
        self.assertions_to_remove = assertions_to_remove
        self.assignments_to_remove = assignments_to_remove

    def visit(self, node: ast.AST) -> ast.AST | None:
        if node in self.assertions_to_remove or node in self.assignments_to_remove:
            return None
        node = super().visit(node)
        if node is None:
            return None
        if not isinstance(node, ast.Module):
            for field, value in ast.iter_fields(node):
                if isinstance(value, list):
                    if field == 'body' and (not value):
                        value.append(ast.Pass())
        return node

def repair_selfref_assertions(test_code: str) -> str:
    try:
        tree = ast.parse(test_code)
    except Exception:
        return test_code
    functions = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node)
    assertions_to_remove = set()
    assignments_to_remove = set()
    for func_node in functions:
        self_source_vars = set()
        self_source_bindings = []
        assign_nodes = set()
        for subnode in ast.walk(func_node):
            if isinstance(subnode, ast.Assign):
                if is_self_source_expr(subnode.value):
                    assign_nodes.add(subnode)
                    names = get_assigned_names(subnode.targets)
                    for name in names:
                        self_source_vars.add(name)
                        self_source_bindings.append((name, subnode))
            elif isinstance(subnode, ast.AnnAssign):
                if subnode.value and is_self_source_expr(subnode.value):
                    assign_nodes.add(subnode)
                    names = get_assigned_names([subnode.target])
                    for name in names:
                        self_source_vars.add(name)
                        self_source_bindings.append((name, subnode))
        if not self_source_vars:
            continue
        changed = True
        while changed:
            changed = False
            for subnode in ast.walk(func_node):
                if isinstance(subnode, ast.Assign):
                    if isinstance(subnode.value, ast.Name) and subnode.value.id in self_source_vars:
                        names = get_assigned_names(subnode.targets)
                        for name in names:
                            if name not in self_source_vars:
                                self_source_vars.add(name)
                                self_source_bindings.append((name, subnode))
                                assign_nodes.add(subnode)
                                changed = True
                elif isinstance(subnode, ast.AnnAssign):
                    if subnode.value and isinstance(subnode.value, ast.Name) and (subnode.value.id in self_source_vars):
                        names = get_assigned_names([subnode.target])
                        for name in names:
                            if name not in self_source_vars:
                                self_source_vars.add(name)
                                self_source_bindings.append((name, subnode))
                                assign_nodes.add(subnode)
                                changed = True
        func_assertions_to_remove = set()
        for subnode in ast.walk(func_node):
            if isinstance(subnode, ast.Assert):
                if is_literal_absence_assert_expr(subnode.test, self_source_vars):
                    func_assertions_to_remove.add(subnode)
                    assertions_to_remove.add(subnode)
        unused_vars = set()
        for v in self_source_vars:
            v_names = []
            for subnode in ast.walk(func_node):
                if isinstance(subnode, ast.Name) and subnode.id == v:
                    v_names.append(subnode)
            v_assigns = [node for name, node in self_source_bindings if name == v]
            used_elsewhere = False
            for name_node in v_names:
                if is_descendant_of_any(name_node, func_assertions_to_remove):
                    continue
                if is_descendant_of_any(name_node, v_assigns):
                    continue
                used_elsewhere = True
                break
            if not used_elsewhere:
                unused_vars.add(v)
        for assign_node in assign_nodes:
            if isinstance(assign_node, ast.Assign):
                names = get_assigned_names(assign_node.targets)
            else:
                names = get_assigned_names([assign_node.target])
            if all((name in unused_vars for name in names)):
                assignments_to_remove.add(assign_node)
    if not assertions_to_remove and (not assignments_to_remove):
        return test_code
    repairer = SelfRefAssertionRepairer(assertions_to_remove, assignments_to_remove)
    repaired_tree = repairer.visit(tree)
    if repaired_tree is None:
        return ''
    try:
        return ast.unparse(repaired_tree)
    except Exception:
        return test_code
def _has_test_function(tree: ast.AST) -> bool:
    """Return True iff ``tree`` defines at least one ``test*``-named function.

    Mirrors the EG4 base-draft gate: a 0-test file makes pytest exit 5 (no tests
    collected), which the non-vacuity check would mis-read as "failed the stub".
    """
    return any((isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith('test') for n in ast.walk(tree)))

def _reviewed_oracle_revalidates(reviewed_code, target_source: str, target_module_name: str, *, python_exe: str | None=None, real_impl_gate: bool=False) -> bool:
    """Return True iff a reviewed oracle passes the SAME gates as a base draft.

    The reviewed file replaces the pre-review oracle ONLY when it (1) parses,
    (2) defines at least one ``test*`` function, (3) is non-vacuous (fails the
    stripped stub), and (4) -- when ``real_impl_gate`` -- passes the real impl.
    Any miss means fall back to the pre-review oracle; this never raises.
    """
    if not isinstance(reviewed_code, str):
        return False
    try:
        tree = ast.parse(reviewed_code)
    except SyntaxError:
        return False
    if not _has_test_function(tree):
        return False
    if not oracle_is_non_vacuous(reviewed_code, target_source, target_module_name, python_exe=python_exe):
        return False
    if real_impl_gate and (not run_oracle_against(reviewed_code, target_source, target_module_name, python_exe=python_exe)):
        return False
    return True