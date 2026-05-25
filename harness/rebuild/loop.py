"""LOOP: dep-ordered per-unit blind reconstruction into the output repo.

For each unit (in dependency order) the loop writes a task spec into the output
repo's state dir and runs ``harness.orchestrator_worker`` against it. The worker
spawns Claude + Gemini blind, fuzzes Claude==Gemini, AST-merges the body into
the skeleton, and runs the unit's ``verification_command`` (oracle + scoped
tests). Because the worker resolves its git root from ``state_dir.parent`` and
its commit target via cwd, pointing ``--state-dir`` at ``<output_repo>/state``
lands every accepted body as a commit IN THE OUTPUT REPO, not the parent.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

from harness.rebuild import discover as _discover
from harness.rebuild import harvest as _harvest
from harness.rebuild import strip as _strip
from harness.rebuild import task as _task
from harness.rebuild import venv as _venv
from harness.rebuild.deps import module_has_top_level_external_import
from harness.rebuild.target import (
    TargetDescriptor,
    mathlib_descriptor,
)

PARENT_ROOT = Path(__file__).resolve().parents[2]


def _dep_import_names(dependencies: list[str] | None) -> set[str]:
    """Best-effort top-level import names for a list of pip requirement lines.

    ``six>=1.16`` -> ``six``; ``requests[security]==2`` -> ``requests``;
    ``typing-extensions`` -> ``typing_extensions``. Used to tell harvest which
    units import an external dep (import name usually == distribution name; the
    rare divergences like PyYAML->yaml are a known limitation).
    """
    names: set[str] = set()
    for line in dependencies or []:
        m = re.match(r'[A-Za-z0-9_.-]+', line.strip())
        if not m:
            continue
        pkg = m.group(0).split('[')[0]
        if pkg:
            names.add(pkg.replace('-', '_'))
    return names


def _is_stub_body(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    stmts = list(node.body)
    if stmts and isinstance(stmts[0], ast.Expr) and isinstance(
        getattr(stmts[0], 'value', None), ast.Constant
    ):
        stmts = stmts[1:]
    return (
        len(stmts) == 1
        and isinstance(stmts[0], ast.Raise)
        and isinstance(stmts[0].exc, ast.Name)
        and stmts[0].exc.id == 'NotImplementedError'
    )


def has_notimplemented(module_file: Path, name: str, cls: str | None = None) -> bool:
    """True iff function/method ``name`` in ``module_file`` is still a stub.

    A stub body is exactly a (optional docstring) + ``raise NotImplementedError``.
    When ``cls`` is given, the method ``cls.name`` inside that class is checked
    (live class/method reconstruction); otherwise the top-level function ``name``.
    Used to assert a unit's body actually landed after reconstruction.
    """
    try:
        tree = ast.parse(Path(module_file).read_text(encoding='utf-8'))
    except (OSError, SyntaxError):
        return True
    if cls is not None:
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == cls:
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name == name:
                        return _is_stub_body(sub)
        return True
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return _is_stub_body(node)
    return True


def class_has_notimplemented(module_file: Path, cls: str) -> bool:
    """True iff ANY method of class ``cls`` in ``module_file`` is still a stub.

    The class-granular (whole_class) body-landed check: a stateful class is
    reconstructed in one submission, so it has landed only when EVERY method has
    a real body. Returns True (not landed) if the class is absent or unparseable.
    """
    try:
        tree = ast.parse(Path(module_file).read_text(encoding='utf-8'))
    except (OSError, SyntaxError):
        return True
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_stub_body(sub):
                    return True
            return False
    return True


def _git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(['git', *args], cwd=str(cwd), capture_output=True, text=True, check=check)


def extract_unit_source(module_file: Path, name: str, cls: str | None = None) -> str | None:
    """Return the verbatim source of function/method ``name`` in ``module_file``.

    Used to inject an already-reconstructed sibling's BODY into a caller unit's
    task spec (the differential fuzzer needs the callee to actually run). When
    ``cls`` is given the method ``cls.name`` is extracted. Returns ``None`` if the
    target is absent or still a stripped stub.
    """
    try:
        text = Path(module_file).read_text(encoding='utf-8')
        tree = ast.parse(text)
    except (OSError, SyntaxError):
        return None
    if cls is not None:
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == cls:
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name == name:
                        if _is_stub_body(sub):
                            return None
                        return ast.get_source_segment(text, sub)
        return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            if has_notimplemented(module_file, name):
                return None
            return ast.get_source_segment(text, node)
    return None


def build_worker_invocation(
    descriptor: TargetDescriptor, task_id: str, *, env: dict | None = None
) -> tuple[list[str], str, dict]:
    """Return ``(cmd, cwd, env)`` for dispatching ``task_id`` into the output repo.

    This is the single source of truth for the four retarget invariants (LAW;
    see memory feedback-rebuild-engine-retarget). Extracted so the contract is
    unit-testable without spawning the worker:

    1. The worker is invoked by FILE PATH (``orchestrator_worker.py``), never
       ``python -m`` -- with cwd=output repo, ``-m harness...`` cannot resolve.
    2. ``cwd`` is the output repo: the spawned Claude agent inherits it as its
       acceptEdits write boundary and its outbox lives under ``<out>/state``.
    3. ``PYTHONPATH`` is scrubbed: if it pointed at the parent JanusMask it would
       leak into the verification subprocess and shadow the reconstructed module
       with the parent original (critical when the output repo shares a package
       name with the parent, e.g. JR's ``harness``).
    4. ``JANUSMASK_*`` is scrubbed so the parent's phase/journal env never bleeds
       into the replicant's worker run.
    """
    out = descriptor.output_dir
    state_dir = out / 'state'
    cmd = [
        sys.executable,
        str(PARENT_ROOT / 'harness' / 'orchestrator_worker.py'),
        '--state-dir',
        str(state_dir),
        '--task-id',
        task_id,
        '--config',
        str(PARENT_ROOT / 'harness' / 'config.yaml'),
    ]
    base = os.environ if env is None else env
    run_env = {k: v for k, v in base.items() if not k.startswith('JANUSMASK_')}
    run_env.pop('PYTHONPATH', None)
    return cmd, str(out), run_env


def init_output_repo(descriptor: TargetDescriptor) -> dict:
    """Materialize the skeleton, git-init the output repo, commit the seed.

    Returns the materialize info dict (``{'stash': {...}, ...}``). The state dir
    and the out-of-repo stash are gitignored so only the replicant's own source
    is tracked.
    """
    info = _strip.materialize_skeleton(descriptor)
    out = descriptor.output_dir
    gitignore = out / '.gitignore'
    existing_ignore = gitignore.read_text(encoding='utf-8') if gitignore.exists() else ''
    ignore_lines = [ln.strip() for ln in existing_ignore.splitlines()]
    for entry in ('state/', '.venv/'):
        if entry not in ignore_lines:
            existing_ignore += ('' if existing_ignore.endswith('\n') or not existing_ignore else '\n') + entry + '\n'
    gitignore.write_text(existing_ignore if existing_ignore else 'state/\n.venv/\n', encoding='utf-8')
    # Materialize a tracked requirements.txt so the replicant carries its own
    # dependency manifest (the binaries live in the gitignored .venv/). pytest is
    # added so the standalone proof (`pip install -r requirements.txt && pytest`)
    # runs the replicant's own tests with no ambient deps.
    if descriptor.dependencies:
        req_lines = list(descriptor.dependencies)
        if not any(re.match(r'pytest(\b|[<>=!~\[])', d.strip(), re.I) for d in req_lines):
            req_lines.append('pytest')
        (out / 'requirements.txt').write_text('\n'.join(req_lines) + '\n', encoding='utf-8')
    if not (out / '.git').exists():
        _git(['init', '-q'], out)
        _git(['config', 'user.email', 'rebuild-engine@janusmask.local'], out)
        _git(['config', 'user.name', 'JanusMask Rebuild Engine'], out)
    _git(['add', '-A'], out)
    _git(
        ['commit', '-q', '-m', f'skeleton: {descriptor.name} (bodies stripped to NotImplementedError)'],
        out,
        check=False,
    )
    # Provision the replicant's OWN .venv (after the commit, so it stays
    # gitignored) and install its deps + pytest, so per-unit + full-suite
    # verification runs IN the venv and the replicant is standalone-runnable.
    # Idempotent/resumable: provision_venv is a fast no-op once .venv exists.
    if descriptor.dependencies:
        _venv.provision_venv(out, requirements_files=['requirements.txt'])
        descriptor.python_exe = str(_venv.venv_python(out))
    return info


def _parse_outcome(stdout: str) -> dict:
    last = {}
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith('{') and line.endswith('}'):
            try:
                last = json.loads(line)
            except json.JSONDecodeError:
                continue
    return last


def modules_without_tests(descriptor: TargetDescriptor) -> list[str]:
    """Return rel paths of modules NOT imported by any of the project's tests.

    A module is "test-less" when no shipped test file imports it by name -- the
    case the independent test-author role exists to fill (generate an oracle).
    """
    # Collect both FULL dotted module names and bare leaves the tests import, so a
    # PACKAGED module ``geopack/base.py`` imported via ``from geopack.base import
    # x`` matches by its dotted name ``geopack.base`` (not just the top-level
    # ``geopack``). Flat modules (``from metrics import f``) still match by leaf.
    imported: set[str] = set()
    for tf in descriptor.test_files:
        try:
            tree = ast.parse((descriptor.source_root / tf).read_text(encoding='utf-8'))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    imported.add(a.name)  # full dotted
                    imported.add(a.name.split('.')[-1])  # leaf
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                imported.add(node.module)  # from pkg.mod import x -> pkg.mod
                imported.add(node.module.split('.')[-1])
                for a in node.names:  # from pkg import mod -> pkg.mod
                    imported.add(f'{node.module}.{a.name}')
    out: list[str] = []
    for m in descriptor.modules:
        dotted = (m[:-3] if m.endswith('.py') else m).replace('/', '.')
        leaf = dotted.split('.')[-1]
        if dotted not in imported and leaf not in imported:
            out.append(m)
    return out


def _unit_source_segments(src: str) -> dict:
    """Map each top-level function / class / method name to its source segment.

    Used by per-unit oracle authoring so each TA call sees ONLY the unit under
    test (a small prompt) instead of the whole module (which times the live
    ``claude -p`` out at 600s on a large module -- P1/C9.16).
    """
    seg: dict = {}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return seg

    def _collect(nodes):
        for n in nodes:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                seg.setdefault(n.name, ast.get_source_segment(src, n) or '')
                if isinstance(n, ast.ClassDef):
                    _collect(n.body)
    _collect(tree.body)
    return seg


def author_unit_oracles(
    descriptor: TargetDescriptor, module_rel: str, src: str, *,
    gen_fn=None, config=None, max_attempts: int = 3, only: str | None = None,
) -> str:
    """Author a verification oracle PER UNIT for a test-less module and return the
    concatenated test source.

    The whole-module ``author_oracle`` call embeds the ENTIRE module source in one
    ``claude -p`` prompt, which times out (600s) on a large module and produces
    behaviour-named tests that ``pytest -k <unit>`` misses (-> whole-file cascade).
    Authoring per-unit fixes both: each call sees only the unit's own source slice
    (small + fast prompt) and is told the unit's ``-k`` token so it names tests
    ``test_<unit>_*`` (scopable). The role's stub-must-fail non-vacuity gate +
    optional real-impl gate run per unit (reused from ``author_oracle``). Blocks
    are concatenated into one ``test_<stem>_generated.py`` body.
    """
    from harness import test_author
    dotted = (module_rel[:-3] if module_rel.endswith('.py') else module_rel).replace('/', '.')
    stem = dotted.split('.')[-1]
    segments = _unit_source_segments(src)
    # The per-unit slice must carry the module's TOP-LEVEL IMPORTS, or the
    # real-impl gate (run_oracle_against execs the slice as a standalone module)
    # raises NameError on a name the unit uses from a module import (e.g. ``re``)
    # and FALSELY rejects every draft -> VacuousOracleError. Prepend them.
    imports_prefix = ''
    try:
        _tree = ast.parse(src)
        _imp = [n for n in _tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        if _imp:
            imports_prefix = '\n'.join(ast.get_source_segment(src, n) or '' for n in _imp) + '\n\n'
    except SyntaxError:
        pass
    # B7: only gate on the real impl when it is importable in the chosen
    # interpreter (a provisioned venv, or a dep-free project under ambient python).
    real_impl_gate = bool(descriptor.python_exe) or not descriptor.dependencies
    # Collect the units to author (dedup by -k token), each with its own
    # imports-prefixed source slice.
    jobs: list[tuple[int, str, str, str]] = []  # (idx, name, tok, unit_src)
    seen_tokens: list[str] = []
    for u in _harvest.harvest_module(module_rel, src, include_methods=True):
        # EG1: when reconstructing a single unit (--only), author ONLY that unit's
        # oracle -- authoring is ~6min/unit, so authoring the whole module's oracles
        # for a one-unit keystone is pure waste.
        if only is not None and u.name != only:
            continue
        tok = u.name.strip('_') or u.name
        # CLASS-FIRST token for a method unit (P0/#44): matches the _k_expr
        # selector ``test_<clstoken>_<method>_`` and keeps two same-named methods
        # in different classes from de-duping to a single authored oracle.
        if u.cls and not getattr(u, 'whole_class', False):
            tok = f'{_task._cls_token(u.cls)}_{tok}'
        if tok in seen_tokens:
            continue
        seen_tokens.append(tok)
        _seg = segments.get(u.name)
        unit_src = (imports_prefix + _seg) if _seg else src
        jobs.append((len(jobs), u.name, tok, unit_src))

    def _author_one(job):
        idx, name, tok, unit_src = job
        try:
            oracle = test_author.author_oracle(
                dotted, src,
                {'description': f'verification oracle for {dotted}.{name}'},
                config or {}, descriptor.output_dir / 'state',
                gen_fn=gen_fn, max_attempts=max_attempts,
                python_exe=descriptor.python_exe,
                task_id=f'TA_{descriptor.name}_{stem}_{name}',
                real_impl_gate=real_impl_gate, unit_names=[tok],
                reference_source=unit_src,
            )
        except (test_author.VacuousOracleError, test_author.TestAuthorError) as e:
            import traceback, sys
            sys.stderr.write(f"TA FAILED: {e}\n")
            traceback.print_exc(file=sys.stderr)
            # One hard unit must NOT abort the whole module's oracle authoring
            # (which crashes the up-front ensure_testless_oracles -> the whole
            # loop, landing ZERO units). Two failure modes degrade identically:
            #   - VacuousOracleError: the live author can't produce a non-vacuous,
            #     behaviour-accurate draft in max_attempts.
            #   - TestAuthorError: the live ``claude -p`` author call timed out
            #     (600s) or otherwise failed to generate a parseable oracle.
            # DEGRADE: skip this unit's test. An oracle-USABLE unit then gates on
            # the merged==original oracle alone (C9.16a oracle-only); an
            # oracle-SKIP unit loud-fails at reconstruct (surfaced, not silent).
            # The module's OTHER units still get oracles.
            return (idx, name, None)
        return (idx, name, oracle.test_code)

    # P0/C9.17: author units IN PARALLEL. Each live ``claude -p`` author call is
    # ~5-7 min and the per-unit calls are INDEPENDENT (distinct task_id -> distinct
    # session dir, subprocess-isolated), so a bounded thread pool turns N x 7min
    # SERIAL into ~ceil(N/workers) x 7min -- the latency wall that made a many-unit
    # live rebuild infeasible (#42/W1). Block ORDER is made DETERMINISTIC by sorting
    # on the unit index, NOT completion order. ``author_workers`` is config-tunable
    # (loop --author-workers); default 4.
    workers = 4
    if isinstance(config, dict) and isinstance(config.get('rebuild'), dict):
        workers = int(config['rebuild'].get('author_workers', 4))
    workers = max(1, min(workers, len(jobs) or 1))
    if workers == 1 or len(jobs) <= 1:
        results = [_author_one(j) for j in jobs]
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_author_one, jobs))
    results.sort(key=lambda r: r[0])
    blocks = [f'# ----- {name} -----\n{code.rstrip()}\n'
              for _idx, name, code in results if code is not None]
    return '\n\n'.join(blocks)


def ensure_testless_oracles(
    descriptor: TargetDescriptor, *, gen_fn=None, config=None, max_attempts: int = 3,
    only: str | None = None, reuse_existing: bool = False,
) -> dict:
    """Generate a non-vacuous oracle for every test-less module via the TA role.

    For each module no shipped test imports, invoke the INDEPENDENT test-author
    role (``harness.test_author.author_oracle``) to generate a verification
    oracle, write it into the OUTPUT repo as ``test_<stem>_generated.py`` (NEVER
    the committed source tree -- that would dirty an arbitrary input project and
    make the module no-longer test-less on the next run), and register it on the
    descriptor (test_files + recomputed test commands) so the engine reconstructs
    that module's units BLIND against the generated oracle.
    The non-vacuity guarantee (the generated test must FAIL the stripped stub) is
    owned by the role. Returns ``{module_rel: GeneratedOracle}``. Call BEFORE
    ``reconstruct_all`` so the skeleton materializes the generated test. ``gen_fn``
    is the generator (injected in tests; the live default spawns an agent).
    """
    from harness import test_author
    generated: dict = {}
    for m in modules_without_tests(descriptor):
        # The TA target is the IMPORTABLE module name: the full DOTTED path for a
        # packaged module (``geopack/fuzzy.py`` -> ``geopack.fuzzy``), so the
        # generated oracle imports ``from geopack.fuzzy import ...`` and resolves
        # against the real package at rebuild time (C9.9). A flat module's dotted
        # name is just its stem.
        dotted = (m[:-3] if m.endswith('.py') else m).replace('/', '.')
        stem = dotted.split('.')[-1]
        src = (descriptor.source_root / m).read_text(encoding='utf-8')
        # EG1: when reconstructing a single unit (--only), skip modules that don't
        # contain it (don't author oracles for out-of-scope modules) and author only
        # that unit's oracle within its own module.
        unit_filter = None
        if only is not None:
            mod_unit_names = {u.name for u in _harvest.harvest_module(m, src, include_methods=True)}
            if only not in mod_unit_names:
                continue
            unit_filter = only
        test_name = f'test_{stem}_generated.py'
        descriptor.output_dir.mkdir(parents=True, exist_ok=True)
        existing = descriptor.output_dir / test_name
        # EG2: on --resume a non-empty on-disk generated oracle is already satisfied.
        # Re-authoring it re-spends ~6min/unit AND -- because author_oracle EMPTIES
        # the file before writing -- a failed re-author would DESTROY the good oracle.
        # Reuse it: register on the descriptor and skip the author call.
        if reuse_existing and existing.exists() and existing.read_text(encoding='utf-8').strip():
            if test_name not in descriptor.test_files:
                descriptor.test_files.append(test_name)
            generated[m] = test_author.GeneratedOracle(
                test_code=existing.read_text(encoding='utf-8'),
                verification_command='python -m pytest -q',
                test_filename=test_name, attempts=0,
            )
            continue
        # P1/C9.16: author the oracle PER UNIT (small, fast prompts that beat the
        # 600s whole-module ``claude -p`` timeout, and name tests test_<unit>_* so
        # ``pytest -k <unit>`` scopes each unit -- no whole-file cascade). The
        # per-unit non-vacuity (stub-must-fail) + real-impl gates run inside
        # author_unit_oracles (which reuses the test_author role per unit).
        test_code = author_unit_oracles(
            descriptor, m, src, gen_fn=gen_fn, config=config,
            max_attempts=max_attempts, only=unit_filter,
        )
        (descriptor.output_dir / test_name).write_text(test_code, encoding='utf-8')
        if test_name not in descriptor.test_files:
            descriptor.test_files.append(test_name)
        generated[m] = test_author.GeneratedOracle(
            test_code=test_code, verification_command='python -m pytest -q',
            test_filename=test_name, attempts=1,
        )
    if generated:
        descriptor.full_test_command = 'python -m pytest -q ' + ' '.join(descriptor.test_files)
        descriptor.unit_test_selector = ' '.join(descriptor.test_files) + ' -k {unit}'
    return generated


def _unit_test_tokens(unit) -> list[str]:
    """The lowercased ``-k`` substrings that select ``unit``'s OWN tests, derived
    from the SAME ``task._k_expr`` the verification gate uses (task.build_unit_task)
    so the PROMPT shows exactly the tests the gate will run -- never a sibling's."""
    kcls = unit.cls if (unit.cls and not getattr(unit, 'whole_class', False)) else None
    expr = _task._k_expr(unit.name, kcls).strip("'")
    return [t.strip().lower() for t in expr.split(' or ') if t.strip()]


def _filter_tests_for_unit(src: str, tokens: list[str]) -> str:
    """Return only the test funcs/classes in ``src`` whose name matches one of
    ``tokens`` (pytest ``-k`` is case-insensitive substring), preceded by the
    file's module-level prologue (imports/fixtures/helpers). Empty string if none
    match, so an UNRELATED test file contributes NOTHING to a unit's prompt.

    Without this the prompt embedded EVERY module's generated tests verbatim
    (a 51KB blob led by an unrelated unit's oracle), which starved oracle-skip
    synthesis -- both agents returned empty -> synthesis_or_ast_failed (session
    #46; the whole discover/harvest oracle-skip frontier blocked on it)."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return ''
    prologue: list[str] = []
    matched: list[str] = []
    for node in tree.body:
        is_test_fn = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.lower().startswith('test')
        is_test_cls = isinstance(node, ast.ClassDef) and node.name.lower().startswith('test')
        seg = ast.get_source_segment(src, node)
        if seg is None:
            continue
        if is_test_fn or is_test_cls:
            hay = node.name.lower()
            if is_test_cls:
                hay += ' ' + ' '.join(
                    m.name.lower() for m in node.body
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
            if any(t in hay for t in tokens):
                matched.append(seg)
        else:
            prologue.append(seg)
    if not matched:
        return ''
    return '\n'.join(prologue + [''] + matched)


def _read_unit_tests(descriptor: TargetDescriptor, unit=None) -> str:
    parts = []
    tokens = _unit_test_tokens(unit) if unit is not None else None
    for rel in descriptor.test_files:
        # Prefer the OUTPUT repo: after skeleton materialization it holds the
        # shipped tests (copied) AND any test-author-GENERATED oracle (written
        # there, never into the committed source). Fall back to source_root for
        # programmatic callers that read tests before materialization.
        text = None
        for base in (descriptor.output_dir, descriptor.source_root):
            try:
                text = (base / rel).read_text(encoding='utf-8')
                break
            except OSError:
                continue
        if text is None:
            continue
        if tokens is not None:
            # Per-unit isolation: embed ONLY this unit's tests (a file with no
            # matching test contributes nothing). Falls through to '' if NO file
            # matches -- better a missing test section than a sibling's oracle.
            text = _filter_tests_for_unit(text, tokens)
            if not text:
                continue
        parts.append(text)
    return '\n\n'.join(parts)


def reconstruct_unit(
    descriptor: TargetDescriptor,
    unit: _harvest.Unit,
    module_rel: str,
    stash_map: dict,
    *,
    sibling_signatures: list[str] | None = None,
    sibling_bodies: list[str] | None = None,
    cross_signatures: list[str] | None = None,
    timeout: int = 1200,
    max_attempts: int = 3,
    fuzz_str_ascii: bool = False,
    partial_edit: bool = False,
    rebuild_oracle_primary: bool = False,
) -> dict:
    """Dispatch a blind dual-agent reconstruction of ``unit`` into the output repo.

    B5: bounded test-gated RETRY. A single stochastic differential miss must not
    be terminal for a non-oversized unit (the oversized driver already retries;
    this mirrors it). Each attempt dispatches a fresh worker; success = the body
    landed AND the unit's scoped tests pass (the worker already gates on its
    verification_command, so the test re-run is a cheap honest confirm -- it is
    the SOLE real gate for a self_mutating/oracle-skip unit whose merged==original
    fuzz oracle is vacuous). On a miss the stub is restored from the pre-dispatch
    module text (mirror reconstruct_oversized_unit) so the next attempt starts
    clean instead of inheriting a partial body left by an auto_commit_failed.
    """
    out = descriptor.output_dir
    state_dir = out / 'state'
    tasks_dir = state_dir / 'tasks'
    tasks_dir.mkdir(parents=True, exist_ok=True)
    orig_path = stash_map[module_rel]
    spec = _task.build_unit_task(
        descriptor=descriptor,
        unit=unit,
        module_rel=module_rel,
        oracle_original_path=orig_path,
        sibling_signatures=sibling_signatures or [],
        sibling_bodies=sibling_bodies or [],
        cross_signatures=cross_signatures or [],
        unit_test_text=_read_unit_tests(descriptor, unit),
        parent_root=str(PARENT_ROOT),
        fuzz_str_ascii=fuzz_str_ascii,
        partial_edit=partial_edit,
        rebuild_oracle_primary=rebuild_oracle_primary,
    )
    task_id = spec['task_id']
    out_module = out / module_rel
    stub_source = out_module.read_text(encoding='utf-8')
    last: dict = {}
    for attempt in range(max_attempts):
        (tasks_dir / f'{task_id}.json').write_text(json.dumps(spec, indent=2), encoding='utf-8')
        # The 4 retarget invariants (file-path worker, cwd=output, scrubbed
        # PYTHONPATH/JANUSMASK_*) live in build_worker_invocation so they are
        # unit-locked (tests/adversarial/test_rebuild_retarget.py).
        cmd, cwd, env = build_worker_invocation(descriptor, task_id)
        try:
            proc = subprocess.run(
                cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env
            )
            stdout, stderr, rc = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or '')
            stderr = (exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or '')) + '\n[timeout]'
            rc = 124
        outcome = _parse_outcome(stdout)
        if getattr(unit, 'whole_class', False):
            body_landed = not class_has_notimplemented(out_module, unit.cls)
        else:
            body_landed = not has_notimplemented(out_module, unit.name, cls=unit.cls)
        sha = None
        head = _git(['rev-parse', 'HEAD'], out, check=False)
        if head.returncode == 0:
            sha = head.stdout.strip()
        last = {
            'task_id': task_id,
            'unit': unit.qualname,
            'module': module_rel,
            'worker_rc': rc,
            'outcome': outcome.get('outcome'),
            'reason': outcome.get('reason'),
            'body_landed': body_landed,
            'head_sha': sha,
            'stderr_tail': stderr[-1200:],
            'attempts': attempt + 1,
        }
        if body_landed:
            tests = _run_unit_tests(descriptor, unit)
            last['tests_passed'] = tests.get('returncode') == 0
            if last['tests_passed']:
                return last
            last['body_landed'] = False  # committed-but-tests-failed -> retry clean
        # miss: restore the stub so the next attempt starts from a clean body.
        out_module.write_text(stub_source, encoding='utf-8')
    _git(['checkout', 'HEAD', '--', module_rel], out, check=False)
    return last


def _propagate_needs_deps(descriptor, ext_modules, src_by_module, units_by_module) -> None:
    """Flag every unit of a (transitively) dep-importing module ``needs_deps``.

    A module with a TOP-LEVEL external import is already flagged blanket by
    harvest. This adds the TRANSITIVE case: a module that imports (directly or
    indirectly) such a module also cannot use the parent merged==original oracle,
    because the oracle execs the original module, whose import chain reaches the
    absent dependency. Those units route to the venv-tests-only path too.
    """
    if not ext_modules:
        return
    modules = list(descriptor.modules)
    graph = _discover.module_import_graph(descriptor.source_root, modules)
    tainted = {
        m for m in modules
        if module_has_top_level_external_import(src_by_module.get(m, ''), ext_modules)
    }
    changed = True
    while changed:
        changed = False
        for m in modules:
            if m not in tainted and any(dep in tainted for dep in graph.get(m, ())):
                tainted.add(m)
                changed = True
    for m in tainted:
        for u in units_by_module.get(m, []):
            u.needs_deps = True


def _global_order(units_by_module, cross_by_module, module_order):
    """Order ALL units across all modules so every callee precedes its caller.

    Edges come from intra-module sibling calls AND cross-module calls; a true
    unit-level cycle (mutual recursion) falls back to source order (stable),
    mirroring :func:`harvest.order_units`. Returns ``[(module_rel, Unit), ...]``.
    """
    flat = [(m, u) for m in module_order for u in units_by_module.get(m, [])]
    source_index = {(m, u.qualname): i for i, (m, u) in enumerate(flat)}
    by_key = {(m, u.qualname): u for (m, u) in flat}

    def resolve(m, name):
        units = units_by_module.get(m, [])
        for u in units:
            if u.name == name and u.cls is None:
                return (m, u.qualname)
        for u in units:
            if u.name == name:
                return (m, u.qualname)
        return None

    edges: dict[tuple, set] = {k: set() for k in by_key}
    for (m, u) in flat:
        key = (m, u.qualname)
        for c in u.calls:
            ck = resolve(m, c)
            if ck and ck != key:
                edges[key].add(ck)
        for (cm, cn) in cross_by_module.get(m, {}).get(u.name, set()):
            ck = resolve(cm, cn)
            if ck and ck != key:
                edges[key].add(ck)

    ordered_keys: list[tuple] = []
    placed: set = set()
    visiting: set = set()

    def visit(k):
        if k in placed or k in visiting:
            return
        visiting.add(k)
        for dep in sorted(edges.get(k, ()), key=lambda x: source_index.get(x, 1 << 30)):
            visit(dep)
        visiting.discard(k)
        if k not in placed:
            placed.add(k)
            ordered_keys.append(k)

    for k in sorted(by_key, key=lambda x: source_index[x]):
        visit(k)
    return [(k[0], by_key[k]) for k in ordered_keys]


def _unit_body_segment(original_source: str, unit) -> str | None:
    try:
        tree = ast.parse(original_source)
    except SyntaxError:
        return None
    if unit.cls:
        for n in tree.body:
            if isinstance(n, ast.ClassDef) and n.name == unit.cls:
                for m in n.body:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name == unit.name:
                        return ast.get_source_segment(original_source, m)
        return None
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == unit.name:
            return ast.get_source_segment(original_source, n)
    return None


def unit_exceeds_byte_budget(original_source: str, unit, config=None) -> bool:
    """True iff ``unit``'s original body is larger than the rebuild byte budget.

    A unit whose body exceeds the budget is too large for a single blind
    dual-agent reconstruction (it blows the AST-merge byte budget), so it is a
    candidate for decomposition. Budget defaults to 4000 chars; override via
    ``config['rebuild']['unit_byte_budget']``.
    """
    budget = 4000
    if isinstance(config, dict) and isinstance(config.get('rebuild'), dict):
        budget = int(config['rebuild'].get('unit_byte_budget', budget))
    seg = _unit_body_segment(original_source, unit)
    return seg is not None and len(seg) > budget


def decompose_oversized_unit(unit, original_source: str, config, state_dir):
    """Route an oversized/failed unit through the task decomposer (P3 fallback).

    Invokes :func:`harness.task_decomposer.decompose_task` with the unit's spec
    and enqueues the resulting subtasks, returning the ``DecompositionResult``.
    This is the integration POINT between the rebuild loop and the decomposer;
    full recomposition of the decomposed sub-bodies back into the rebuilt unit is
    the orchestrator.py rebuildability arc (SCAFFOLDED).
    """
    from harness.task_decomposer import decompose_task, enqueue_subtasks
    seg = _unit_body_segment(original_source, unit) or ''
    task = {
        'task_id': f'RB_decompose_{unit.cls + "_" if unit.cls else ""}{unit.name}',
        'specification': unit.docstring or unit.signature,
        'meta_task_type': 'refactor',
    }
    result = decompose_task(task, [], config or {}, code_a=seg, code_b=seg, depth=0)
    if result.subtasks:
        try:
            enqueue_subtasks(result.subtasks, Path(state_dir))
        except OSError:
            pass
    return result


def _budget_from_config(config) -> int:
    budget = 4000
    if isinstance(config, dict) and isinstance(config.get('rebuild'), dict):
        budget = int(config['rebuild'].get('unit_byte_budget', budget))
    return budget


def _file_merge_budget_from_config(config) -> int:
    # P1 (C9.14): the whole-file AST-merge "budget" is operational, not a hard
    # constant -- an agent cannot reliably round-trip a very large module file as a
    # single whole-file submission, so its per-unit reconstruction (which today
    # rewrites the WHOLE file) fails to land. Default 50_000 bytes cleanly separates
    # the small sample/external-lib targets (whole-file path, unchanged) from the
    # large harness modules (sandbox.py ~74KB, orchestrator.py ~136KB) that must
    # route per-unit through the __JANUSMASK_PATCHES__ partial-edit path.
    budget = 50000
    if isinstance(config, dict) and isinstance(config.get('rebuild'), dict):
        budget = int(config['rebuild'].get('file_merge_budget', budget))
    return budget


def file_exceeds_merge_budget(source: str, config=None) -> bool:
    """True when a MODULE FILE is too large to round-trip as a whole-file submission.

    Distinct from ``unit_exceeds_byte_budget`` (a single oversized FUNCTION body,
    handled by decompose/recompose). This is the FILE dimension: a module with many
    normal units whose whole-file bytes exceed the merge budget -> route each unit's
    reconstruction through the partial-edit (__JANUSMASK_PATCHES__) path.
    """
    return len(source.encode('utf-8')) > _file_merge_budget_from_config(config)


def _segment_stmt_count(seg: str) -> int:
    try:
        return len(ast.parse(textwrap.dedent(seg)).body)
    except SyntaxError:
        return 0


def _segment_prompt(unit, header: str, prior_segments: list, seg_index: int,
                    total: int, unit_test_text: str, expected_stmts: int = 0) -> str:
    prior = '\n'.join(prior_segments)
    final_note = (
        'This is the FINAL segment -- it MUST include the function\'s concluding '
        'statement(s) (e.g. the return) so the function is complete. '
        if seg_index == total - 1 else
        'More segments follow this one; do NOT emit a premature return that ends '
        'the function early. '
    )
    count_note = (
        f'This segment contains EXACTLY {expected_stmts} top-level body statement(s). '
        if expected_stmts else ''
    )
    return (
        'You are reconstructing ONE oversized Python function body BLIND, segment by segment.\n'
        f'Function header (signature + docstring):\n{header}\n\n'
        'Body reconstructed so far'
        f' (segments 0..{seg_index - 1}):\n{prior if prior else "(none yet)"}\n\n'
        f'Produce ONLY the source statements for segment {seg_index} of {total} -- a contiguous '
        'block of the function body that continues seamlessly from the code so far, reusing the '
        'SAME variable names already in scope. ' + count_note + final_note +
        'Preserve the body indentation (every statement indented under the function, normally 4 '
        'spaces; nested blocks deeper). Do NOT repeat the header, the docstring, or prior '
        'segments. Output the segment as a SINGLE ```python fenced code block containing only '
        'those statements; no prose.\n\n'
        f'Behavioral specification (the whole function MUST satisfy these tests):\n{unit_test_text}\n'
    )


def _normalize_segment_indent(seg: str) -> str:
    """Re-base a reconstructed segment to function-body indentation (4 spaces).

    A blind agent may emit the segment at column 0 or already indented; dedent to
    the common margin then add one body indent so recompose stitches a valid
    function regardless. Idempotent on a segment already at 4-space body indent.
    """
    ded = textwrap.dedent(seg)
    return '\n'.join(('    ' + ln) if ln.strip() else ln for ln in ded.splitlines())


def _run_unit_tests(descriptor: TargetDescriptor, unit) -> dict:
    """Run the unit's scoped tests in the output repo (the oversized gate).

    Mirrors build_unit_task's -k scoping + exit-5 whole-file fallback, run under
    the replicant venv when provisioned (env-faithful) with PYTHONPATH=output so
    the rebuilt module resolves from the output repo, not the parent original.
    """
    out = descriptor.output_dir
    env = {k: v for k, v in os.environ.items() if not k.startswith('JANUSMASK_')}
    env['PYTHONPATH'] = str(out)
    if descriptor.python_exe:
        py = descriptor.python_exe
    elif _venv.venv_ready(out):
        py = str(_venv.venv_python(out))
    else:
        py = 'python'
    whole = ' '.join(descriptor.test_files)
    if descriptor.unit_test_selector:
        _kcls = unit.cls if (unit.cls and not getattr(unit, 'whole_class', False)) else None
        sel = descriptor.unit_test_selector.replace('{unit}', _task._k_expr(unit.name, _kcls))
        cmd = (
            f'{py} -m pytest {sel} -q; __rc=$?; '
            f'if [ "$__rc" = "5" ]; then {py} -m pytest {whole} -q; __rc=$?; fi; exit $__rc'
        )
    elif whole:
        cmd = f'{py} -m pytest {whole} -q'
    else:
        # No selector AND no test files: a path-less ``pytest -q`` would collect the
        # whole output dir and crash on stray agent scratch test_*.py. There is no
        # scoped test gate to re-run here -- the worker already gated this unit via
        # its oracle, so the honest-confirm re-run is a no-op pass.
        return {'returncode': 0, 'stdout_tail': 'no scoped tests; oracle-gated'}
    proc = subprocess.run(cmd, shell=True, cwd=str(out), capture_output=True, text=True, env=env)
    return {'returncode': proc.returncode, 'stdout_tail': proc.stdout[-2000:]}


def reconstruct_oversized_unit(
    descriptor: TargetDescriptor,
    unit,
    module_rel: str,
    stash_map: dict,
    *,
    gen_fn=None,
    config=None,
    timeout: int = 1200,
    sibling_signatures=None,
    sibling_bodies=None,
    cross_signatures=None,
    commit: bool = True,
    max_attempts: int = 3,
    seg_max_retries: int = 2,
) -> dict:
    """Rebuild an OVERSIZED function via decompose -> reconstruct -> recompose.

    A function whose body exceeds the AST-merge byte budget cannot land in one
    blind dual-agent reconstruction. Instead the original body (from the stash)
    is split into byte-budget contiguous segments
    (``decompose.decompose_function_body``), each segment is reconstructed BLIND
    via ``gen_fn`` (default: the live test-author generator) with only the
    signature + prior segments + the unit's tests as context, the segments are
    recomposed (``decompose.recompose_function``), AST-merged into the output
    module, and the unit's tests gate acceptance. This is the REAL
    decompose->reconstruct->recompose path -- ``decompose_oversized_unit`` (the
    SCAFFOLDED fallback) only enqueued a retry. On rejection the stub is restored
    so a later pass retries cleanly.
    """
    from harness.rebuild import decompose as _decompose
    from harness.git_integration import _ast_merge
    out = descriptor.output_dir
    out_module = out / module_rel
    task_id = f'RB_{descriptor.name}_{unit.name}_oversized'
    base = {'task_id': task_id, 'unit': unit.qualname, 'module': module_rel}
    orig_path = stash_map.get(module_rel)
    func_src = None
    if orig_path:
        func_src = _unit_body_segment(Path(orig_path).read_text(encoding='utf-8'), unit)
    if func_src is None:
        return {**base, 'outcome': 'oversized_no_source', 'body_landed': False,
                'segments': 0, 'tests_passed': False}
    budget = _budget_from_config(config)
    dec = _decompose.decompose_function_body(func_src, budget)
    header, segments = dec['header'], dec['segments']
    if gen_fn is None:
        from harness.test_author import _extract_python_block, author_session_dir
        _sess = author_session_dir(out / 'state', task_id)
        _sess.mkdir(parents=True, exist_ok=True)

        def gen_fn(prompt):
            env = {k: v for k, v in os.environ.items() if not k.startswith('JANUSMASK_')}
            try:
                proc = subprocess.run(
                    ['claude', '-p', '--model', 'opus', prompt],
                    cwd=str(_sess), env=env, capture_output=True, text=True, timeout=600,
                )
            except (OSError, subprocess.TimeoutExpired):
                return ''
            if proc.returncode != 0:
                return ''
            block = _extract_python_block(proc.stdout)
            return block if block.strip() else proc.stdout
    unit_test_text = _read_unit_tests(descriptor, unit)
    module_source = out_module.read_text(encoding='utf-8')

    def _accumulated_parses(prior: list, candidate: str) -> bool:
        # header + prior segments + candidate must form a parseable function so
        # far. Each segment is whole top-level statements, so a well-formed
        # candidate keeps the accumulated body syntactically valid; a candidate
        # that opens a block it does not close (premature/garbled output) fails.
        try:
            ast.parse(_decompose.recompose_function(header, prior + [candidate]))
            return True
        except SyntaxError:
            return False

    def _gen_segment(prior: list, i: int) -> str:
        # B2: per-segment parse-validity retry. Regenerate a segment up to
        # seg_max_retries extra times until it keeps the accumulated function
        # parseable; fall back to the first candidate (the whole-unit test gate
        # is the real arbiter, so a best-effort segment still gets a verdict).
        expected = _segment_stmt_count(segments[i])
        best = None
        for _ in range(seg_max_retries + 1):
            prompt = _segment_prompt(unit, header, prior, i, len(segments),
                                     unit_test_text, expected)
            produced = _normalize_segment_indent((gen_fn(prompt) or '').strip('\n'))
            if best is None:
                best = produced
            if _accumulated_parses(prior, produced):
                return produced
        return best if best is not None else ''

    last = {**base, 'outcome': 'oversized_failed', 'body_landed': False,
            'segments': len(segments), 'tests_passed': False, 'attempts': 0}
    for attempt in range(max_attempts):
        # B2: whole-unit regenerate-and-retry, gated by the unit's behavioral
        # tests. A partial function cannot be tested mid-stream, so the unit
        # tests are the per-attempt oracle; on failure the stub is restored and
        # every segment is reconstructed afresh.
        rebuilt: list = []
        for i in range(len(segments)):
            rebuilt.append(_gen_segment(rebuilt, i))
        rebuilt_func = _decompose.recompose_function(header, rebuilt)
        try:
            merged = _ast_merge(rebuilt_func, module_source)
            ast.parse(merged)
        except SyntaxError as exc:
            last = {**base, 'outcome': 'oversized_merge_syntax_error', 'body_landed': False,
                    'segments': len(segments), 'tests_passed': False,
                    'reason': str(exc)[:300], 'attempts': attempt + 1}
            continue
        out_module.write_text(merged, encoding='utf-8')
        body_landed = not has_notimplemented(out_module, unit.name, cls=unit.cls)
        tests = _run_unit_tests(descriptor, unit)
        tests_passed = tests.get('returncode') == 0
        if body_landed and tests_passed:
            sha = None
            if commit:
                try:
                    _git(['add', module_rel], out)
                    _git(['commit', '-m',
                          f'oversized rebuild: {unit.qualname} (decompose/recompose, {len(segments)} segments)'],
                         out)
                    head = _git(['rev-parse', 'HEAD'], out, check=False)
                    if head.returncode == 0:
                        sha = head.stdout.strip()
                except subprocess.CalledProcessError:
                    pass
            return {**base, 'outcome': 'oversized_recomposed', 'body_landed': True,
                    'segments': len(segments), 'tests_passed': True, 'head_sha': sha,
                    'attempts': attempt + 1}
        out_module.write_text(module_source, encoding='utf-8')
        last = {**base, 'outcome': 'oversized_failed', 'body_landed': False,
                'segments': len(segments), 'tests_passed': tests_passed,
                'stdout_tail': tests.get('stdout_tail', '')[-1000:], 'attempts': attempt + 1}
    _git(['checkout', 'HEAD', '--', module_rel], out, check=False)
    return last


def reconstruct_all(
    descriptor: TargetDescriptor,
    *,
    only: str | None = None,
    timeout: int = 1200,
    init: bool = True,
    resume: bool = False,
    gen_testless: bool = False,
    gen_fn=None,
    config=None,
) -> dict:
    """Reconstruct every unit (or just ``only``) of the target, dep-ordered.

    ``resume=True`` skips units whose body is already real in the output repo
    (idempotent re-runs after an interruption). ``init=False`` reuses an
    existing skeleton/stash instead of re-materializing. ``gen_testless=True``
    (the autonomous daemon/WebUI path) first invokes the independent test-author
    role to generate oracles for every test-less module INTO the output repo, so
    those modules are reconstructed blind without operator pre-staging.
    """
    if init:
        info = init_output_repo(descriptor)
    elif resume and _existing_stash_map(descriptor):
        # Resume must NOT re-materialize: re-stripping would overwrite the
        # already-reconstructed bodies in the output repo with fresh stubs. The
        # stash + skeleton already exist, so reuse the stash map as-is.
        info = {'stash': _existing_stash_map(descriptor)}
    else:
        info = _strip.materialize_skeleton(descriptor)
    stash_map = info['stash']
    # Autonomous test-less oracle generation: AFTER the skeleton exists (shipped
    # tests copied into the output repo), let the independent test-author role
    # fill any test-less module's oracle INTO the output repo. Inert when every
    # module already has a shipped test (modules_without_tests == []).
    if gen_testless:
        # EG1: gate authoring to the --only unit's module (no whole-descriptor
        # re-author for a one-unit keystone). EG2: on --resume, reuse a non-empty
        # on-disk generated oracle instead of re-authoring (and risking its
        # destruction via the empty-then-write author).
        ensure_testless_oracles(
            descriptor, gen_fn=gen_fn, config=config, only=only, reuse_existing=resume,
        )
    # On resume (init=False) the venv already exists on disk -> re-resolve the
    # replicant's python so the per-unit vcmd targets it (init=True already set it).
    if _venv.venv_ready(descriptor.output_dir):
        descriptor.python_exe = str(_venv.venv_python(descriptor.output_dir))
    fuzz_str_ascii = bool(isinstance(config, dict)
                          and isinstance(config.get('rebuild'), dict)
                          and config['rebuild'].get('fuzz_str_ascii', False))
    oracle_primary = bool(isinstance(config, dict)
                          and isinstance(config.get('rebuild'), dict)
                          and config['rebuild'].get('oracle_primary', False))
    ext_modules = _dep_import_names(descriptor.dependencies)
    # Harvest EVERY module (methods included for live class/method recon) and
    # detect cross-module callees, so a caller in one module can be reconstructed
    # against an already-real callee in another module.
    stem_map = _discover._stem_map(descriptor.modules)
    units_by_module: dict[str, list] = {}
    cross_by_module: dict[str, dict] = {}
    src_by_module: dict[str, str] = {}
    for module_rel in descriptor.modules:
        src = (descriptor.source_root / module_rel).read_text(encoding='utf-8')
        src_by_module[module_rel] = src
        units_by_module[module_rel] = _harvest.harvest_module(
            module_rel, src, include_methods=True, external_modules=ext_modules
        )
        aliases = {k: v for k, v in stem_map.items() if v != module_rel}
        cross_by_module[module_rel] = _harvest.unit_cross_calls(src, aliases, module_rel)
    # Transitive needs_deps: a module that imports (even indirectly) a module
    # with a top-level external dep cannot use the parent oracle either (the
    # oracle execs the original, which transitively ImportErrors on the dep).
    _propagate_needs_deps(descriptor, ext_modules, src_by_module, units_by_module)
    # Global dep order across ALL modules at UNIT granularity: a module-level
    # import CYCLE is fine as long as the unit call graph is acyclic (the
    # importer's units only call the imported module's units, which come first).
    ordered = _global_order(units_by_module, cross_by_module, descriptor.modules)
    results: list[dict] = []
    for module_rel, unit in ordered:
        if only and unit.name != only:
            continue
        out_module = descriptor.output_dir / module_rel
        if unit.whole_class:
            already = not class_has_notimplemented(out_module, unit.cls)
        else:
            already = not has_notimplemented(out_module, unit.name, cls=unit.cls)
        if resume and already:
            results.append({
                'task_id': f'RB_{descriptor.name}_{unit.name}',
                'unit': unit.qualname,
                'module': module_rel,
                'outcome': 'resume_skip',
                'body_landed': True,
            })
            continue
        by_name = {u.name: u for u in units_by_module[module_rel] if u.cls is None}
        sib = [by_name[c].signature for c in sorted(unit.calls) if c in by_name]
        # Sibling-body injection: pull the verbatim, already-reconstructed bodies
        # of intra-module callees (dep order guarantees they are real) so the
        # fuzzer can execute this caller.
        sib_bodies = []
        for c in sorted(unit.calls):
            if c in by_name:
                body = extract_unit_source(out_module, c)
                if body:
                    sib_bodies.append(body)
        # Cross-module sibling SIGNATURE injection: the callee module is already
        # reconstructed (dep order) and imported in the target module, so the
        # agent calls it qualified (module.func). Bodies are not needed -- the
        # real callee resolves at test time from the reconstructed module.
        cross_sigs = []
        # A whole_class unit aggregates the cross-calls of ALL its methods (the
        # cross-call map is keyed by method short name).
        if unit.whole_class:
            xcalls: set = set()
            for mn in unit.methods:
                xcalls |= cross_by_module.get(module_rel, {}).get(mn, set())
        else:
            xcalls = cross_by_module.get(module_rel, {}).get(unit.name, set())
        for cm, cn in sorted(xcalls):
            cu = next((u for u in units_by_module.get(cm, []) if u.name == cn and u.cls is None), None)
            if cu is None:
                continue
            stem = cm[:-3].replace('/', '.') if cm.endswith('.py') else cm.replace('/', '.')
            call = cu.signature[len('def '):].rstrip(':') if cu.signature.startswith('def ') else cn
            cross_sigs.append(f'{stem}.{call}')
        # C9.10: an oversized unit (body > byte budget) cannot land in one blind
        # dual-agent pass -- route it to the REAL decompose->reconstruct->recompose
        # driver. All other units take the normal single-pass dual-agent path.
        if unit_exceeds_byte_budget(src_by_module[module_rel], unit, config):
            res = reconstruct_oversized_unit(
                descriptor, unit, module_rel, stash_map,
                gen_fn=gen_fn, config=config, timeout=timeout,
                sibling_signatures=sib, sibling_bodies=sib_bodies,
                cross_signatures=cross_sigs,
            )
        else:
            res = reconstruct_unit(
                descriptor, unit, module_rel, stash_map,
                sibling_signatures=sib, sibling_bodies=sib_bodies,
                cross_signatures=cross_sigs, timeout=timeout,
                fuzz_str_ascii=fuzz_str_ascii,
                # P1 KEYSTONE: a unit in an over-budget MODULE file reconstructs via
                # the __JANUSMASK_PATCHES__ partial-edit path (single-symbol in-place
                # patch) instead of a whole-file submission the AST merge can't land.
                partial_edit=file_exceeds_merge_budget(src_by_module[module_rel], config),
                rebuild_oracle_primary=oracle_primary,
            )
        # Legacy fallback: a unit the budget did NOT flag as oversized but which
        # still failed to land routes to the task decomposer (inert on the happy
        # path; oversized units already went to the recompose driver above).
        if (not res.get('body_landed')
                and not str(res.get('outcome', '')).startswith('oversized')
                and unit_exceeds_byte_budget(src_by_module[module_rel], unit, config)):
            try:
                d = decompose_oversized_unit(
                    unit, src_by_module[module_rel], config or {}, descriptor.output_dir / 'state'
                )
                res['decomposed'] = d.strategy
            except Exception:
                res['decomposed'] = 'error'
        results.append(res)
    suite = None
    reverify_failures: list[str] = []
    if not only:
        # EG5: re-verify every reconstructed oracle-usable unit against the
        # original BEFORE declaring complete -- a sibling's carry-forward can
        # corrupt an already-accepted unit that --resume would silently skip.
        reverify_failures = _reverify_modules(
            descriptor, ordered, stash_map, fuzz_str_ascii=fuzz_str_ascii,
        )
        suite = _run_full_suite(descriptor)
    remaining = _remaining_stubs(descriptor)
    return {
        'target': descriptor.name,
        'output_dir': str(descriptor.output_dir),
        'results': results,
        'full_suite': suite,
        'remaining_stubs': remaining,
        'reverify_failures': reverify_failures,
        'complete': bool(
            not remaining
            and not reverify_failures
            and (suite is None or suite.get('returncode') == 0)
        ),
    }


def _existing_stash_map(descriptor: TargetDescriptor) -> dict:
    """Return ``{module_rel: stash_abs_path}`` for stash files that already exist.

    Mirrors ``strip.materialize_skeleton``'s naming so a resumed run can recover
    the oracle originals without re-materializing (which would clobber bodies).
    """
    stash = descriptor.stash_dir
    out: dict[str, str] = {}
    for mod in descriptor.modules:
        f = stash / (mod.replace('/', '__') + '.orig')
        if f.exists():
            out[mod] = str(f)
    return out


def _remaining_stubs(descriptor: TargetDescriptor) -> list[str]:
    out = descriptor.output_dir
    stubs = []
    for module_rel in descriptor.modules:
        src = (descriptor.source_root / module_rel).read_text(encoding='utf-8')
        for unit in _harvest.harvest_module(module_rel, src, include_methods=True):
            if unit.whole_class:
                if class_has_notimplemented(out / module_rel, unit.cls):
                    stubs.append(unit.qualname)
            elif has_notimplemented(out / module_rel, unit.name, cls=unit.cls):
                stubs.append(unit.qualname)
    return stubs


def _reverify_modules(
    descriptor: TargetDescriptor,
    ordered: list,
    stash_map: dict,
    *,
    fuzz_str_ascii: bool = False,
) -> list[str]:
    """EG5: post-rebuild whole-module STANDALONE re-verify (silent-fake-accept guard).

    Per-unit gating holds only at the instant a unit is reconstructed. A LATER
    sibling's blind reconstruction re-emits the already-accepted unit's body (it
    is injected as context), the AST merge applies that re-emission, and the
    sibling's own gate never re-checks it -- so a carry-forward can corrupt an
    accepted unit (#43 g33; #47 ``get_latest_submission`` lost its ``Path()``
    coercion). ``--resume`` then SKIPS the corrupted unit (its body is no longer a
    stub), fake-accepting it. The reject path already restores the whole module
    (``reconstruct_unit`` write_text(stub_source)), so this closes the remaining
    SUCCESS-corrupts-sibling hole: re-run each oracle-USABLE top-level unit's
    merged==original ORACLE (GROUND TRUTH -- we possess the original) against its
    CURRENTLY COMMITTED body and return the qualnames that now diverge, so
    ``reconstruct_all`` refuses ``complete`` and surfaces them instead of fake-
    accepting. Oracle-skip units (impure/needs_deps/untyped/whole_class/rel_import/
    self_mutating/unfuzzable) and methods have a vacuous merged==original oracle
    (the gate task.py routes to tests-only), so they are not re-verified here.
    """
    out = descriptor.output_dir
    config_abs = f'{PARENT_ROOT}/harness/config.yaml'
    env = {k: v for k, v in os.environ.items() if not k.startswith('JANUSMASK_')}
    env.pop('PYTHONPATH', None)
    failures: list[str] = []
    seen: set[str] = set()
    for module_rel, unit in ordered:
        if unit.cls is not None or getattr(unit, 'whole_class', False):
            continue
        if (getattr(unit, 'impure', False) or getattr(unit, 'needs_deps', False)
                or getattr(unit, 'untyped', False) or getattr(unit, 'rel_import', False)
                or getattr(unit, 'self_mutating', False) or getattr(unit, 'unfuzzable', False)):
            continue
        if unit.qualname in seen:
            continue
        seen.add(unit.qualname)
        if has_notimplemented(out / module_rel, unit.name, cls=None):
            continue  # never landed -> _remaining_stubs already reports it
        orig = stash_map.get(module_rel)
        if not orig:
            continue
        cmd = (
            f'python {PARENT_ROOT}/harness/rebuild/oracle.py '
            f'--target {module_rel} --original {orig} '
            f'--unit {unit.name} --config {config_abs}'
            + (' --str-ascii' if fuzz_str_ascii else '')
        )
        proc = subprocess.run(
            cmd, shell=True, cwd=str(out), capture_output=True, text=True, env=env
        )
        if proc.returncode != 0:
            failures.append(unit.qualname)
    return failures


def _run_full_suite(descriptor: TargetDescriptor) -> dict:
    out = descriptor.output_dir
    env = {k: v for k, v in os.environ.items() if not k.startswith('JANUSMASK_')}
    env['PYTHONPATH'] = str(out)
    # Run the whole suite in the replicant's OWN venv when provisioned, so its
    # external deps resolve from <out>/.venv (environment-faithful).
    cmd = descriptor.full_test_command
    if _venv.venv_ready(out):
        cmd = cmd.replace('python -m pytest', f'{_venv.venv_python(out)} -m pytest', 1)
    proc = subprocess.run(
        cmd,
        shell=True,
        cwd=str(out),
        capture_output=True,
        text=True,
        env=env,
    )
    return {
        'returncode': proc.returncode,
        'stdout_tail': proc.stdout[-2000:],
        'stderr_tail': proc.stderr[-1000:],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='Clean-room AST-rebuild loop.')
    p.add_argument('--target', required=True, help="Target name ('mathlib') or path to a descriptor.")
    p.add_argument('--output', required=True, help='Output repo dir (created if absent).')
    p.add_argument('--stash', required=True, help='Out-of-repo stash dir for original bodies.')
    p.add_argument('--only', default=None, help='Reconstruct only this single unit (keystone mode).')
    p.add_argument('--source-root', default=None, help='Override source root (defaults per target).')
    p.add_argument('--timeout', type=int, default=1200, help='Per-unit worker timeout (s).')
    p.add_argument('--resume', action='store_true', help='Skip units already reconstructed in the output repo.')
    p.add_argument('--no-gen-testless', dest='gen_testless', action='store_false',
                   help='Do NOT auto-generate oracles for test-less modules (default: generate via the test-author role).')
    p.add_argument('--unit-byte-budget', type=int, default=None,
                   help='Override the per-unit decompose byte budget (default 4000). A unit whose '
                        'original body exceeds this is rebuilt via the oversized '
                        'decompose->reconstruct->recompose driver. Threads to reconstruct_all(config=) '
                        'so the autonomous daemon/loop path (B4, session #37) can exercise large-body rebuild.')
    p.add_argument('--file-merge-budget', type=int, default=None,
                   help='Override the whole-file AST-merge byte budget (default 50000). A MODULE '
                        'file whose whole-file bytes exceed this is rebuilt per-unit via the '
                        '__JANUSMASK_PATCHES__ partial-edit path (in-place single-symbol patches) '
                        'instead of a whole-file submission. P1/C9.14 large-file keystone.')
    p.add_argument('--fuzz-str-ascii', dest='fuzz_str_ascii', action='store_true',
                   help='REBUILD-SCOPED restricted str fuzz alphabet (ASCII-printable). Closes '
                        'the unicode-ambiguity false-divergence frontier for pure str transforms '
                        '(titleize/pluralize); threads to both the Claude==Gemini gate (per-unit '
                        'task) and the merged==original oracle (--str-ascii). Main pipeline '
                        'unchanged. W1/C9.14.')
    p.add_argument('--oracle-primary', dest='oracle_primary', action='store_true',
                   help='ORACLE-PRIMARY rebuild gate: route oracle-USABLE units through the '
                        'fuzz-bypass harness_plumbing policy while KEEPING the merged==original '
                        'oracle vcmd, so a clean-room rebuild gates on the GROUND-TRUTH oracle '
                        '(we possess the original) + scoped tests + retry, NOT the redundant '
                        'Claude==Gemini differential whose false-divergence blocks a correct '
                        'reconstruction of a quirky rule-table fn (inflection exception_vs_return). '
                        'W1/C9.15.')
    p.add_argument('--author-workers', dest='author_workers', type=int, default=None,
                   help='Parallel per-unit gen_testless author calls (ThreadPoolExecutor). '
                        'Each live claude -p author call is ~5-7 min and per-unit calls are '
                        'independent, so N units author in ~ceil(N/workers) x that instead of '
                        'N x. Default 4. P0/C9.17.')
    p.set_defaults(gen_testless=True)
    args = p.parse_args(argv)

    output = Path(args.output)
    stash = Path(args.stash)
    if args.target == 'mathlib':
        source_root = Path(args.source_root) if args.source_root else (PARENT_ROOT / 'samples' / 'mathlib')
        descriptor = mathlib_descriptor(output, stash, source_root)
    elif Path(args.target).is_dir():
        # Bare DIRECTORY target: discover the descriptor by scanning the project
        # (C9.9 -- rebuild an arbitrary real package directly, no hand-authored
        # descriptor JSON). --source-root, if given, overrides the scanned root.
        src = Path(args.source_root) if args.source_root else Path(args.target)
        descriptor = _discover.build_descriptor(
            src, output_dir=output, stash_dir=stash, name=Path(args.target).resolve().name
        )
    else:
        descriptor = _load_descriptor_json(Path(args.target), output, stash, args.source_root)

    config = None
    if (args.unit_byte_budget is not None or args.fuzz_str_ascii
            or args.file_merge_budget is not None or args.oracle_primary
            or args.author_workers is not None):
        rebuild_cfg: dict = {}
        if args.unit_byte_budget is not None:
            rebuild_cfg['unit_byte_budget'] = args.unit_byte_budget
        if args.fuzz_str_ascii:
            rebuild_cfg['fuzz_str_ascii'] = True
        if args.file_merge_budget is not None:
            rebuild_cfg['file_merge_budget'] = args.file_merge_budget
        if args.oracle_primary:
            rebuild_cfg['oracle_primary'] = True
        if args.author_workers is not None:
            rebuild_cfg['author_workers'] = args.author_workers
        config = {'rebuild': rebuild_cfg}

    summary = reconstruct_all(
        descriptor, only=args.only, timeout=args.timeout,
        init=not args.resume, resume=args.resume,
        gen_testless=args.gen_testless,
        config=config,
    )
    sys.stdout.write(json.dumps(summary, indent=2) + '\n')
    return 0 if summary['complete'] or (args.only and _only_ok(summary, args.only)) else 1


def _only_ok(summary: dict, only: str) -> bool:
    for r in summary['results']:
        if r['unit'] == only:
            return bool(r['body_landed'] and r['outcome'] in ('accepted', 'no_diff'))
    return False


def _load_descriptor_json(path: Path, output: Path, stash: Path, source_root: str | None) -> TargetDescriptor:
    data = json.loads(path.read_text(encoding='utf-8'))
    return TargetDescriptor(
        name=data['name'],
        source_root=Path(source_root or data['source_root']),
        modules=data['modules'],
        test_files=data['test_files'],
        output_dir=output,
        stash_dir=stash,
        seed_files=data.get('seed_files', []),
        full_test_command=data.get('full_test_command', 'python -m pytest -q'),
        unit_test_selector=data.get('unit_test_selector', ''),
        dependencies=data.get('dependencies', []),
        requirements_files=data.get('requirements_files', []),
    )


if __name__ == '__main__':
    sys.exit(main())
