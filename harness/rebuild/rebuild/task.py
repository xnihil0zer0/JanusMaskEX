"""TASK: build a generalized per-unit dual-agent task spec for orchestrator_worker.

The spec is the BLIND contract handed to Claude + Gemini: signature, docstring,
callable sibling signatures, and the unit's scoped tests. It never reveals the
original body. The ``verification_command`` chains the two post-merge gates the
existing worker already enforces for us: the oracle (merged==original) and the
unit's scoped pytest, both with ``PYTHONPATH`` pointed at the parent JanusMask
so ``harness`` and ``pytest`` import inside the output repo.
"""

from __future__ import annotations

from harness.rebuild import venv as _venv
from harness.rebuild.harvest import Unit
from harness.rebuild.target import TargetDescriptor


def _build_spec(
    unit: Unit,
    sibling_signatures: list[str],
    unit_test_text: str,
    sibling_bodies: list[str] | None = None,
    cross_signatures: list[str] | None = None,
    partial_edit: bool = False,
    module_rel: str | None = None,
) -> str:
    is_whole = bool(getattr(unit, 'whole_class', False))
    is_method = unit.cls is not None and not is_whole
    if is_whole:
        parts = [
            'You are reconstructing an ENTIRE Python class -- ALL of its methods at '
            'once. The methods SHARE instance state (a common __init__), so they '
            'must be implemented together to satisfy the class\'s tests below.',
            '',
            f'Target class: {unit.cls}',
            '',
            'Class skeleton (public signatures + docstrings; every method body is a '
            'NotImplementedError stub you must fill in):',
            '',
            unit.class_skeleton or unit.signature,
        ]
    elif is_method:
        parts = [
            'You are reconstructing ONE METHOD of a Python class.',
            'Implement it so it satisfies its docstring and the tests below.',
            '',
            f'Target class: {unit.cls}',
            'Target method signature:',
            f'    {unit.signature}',
        ]
    else:
        parts = [
            'You are reconstructing ONE Python function from its specification.',
            'Implement it so it satisfies its docstring and the tests below.',
            '',
            'Target signature:',
            f'    {unit.signature}',
        ]
    if not is_whole:
        # Signature fidelity: reproduce the signature VERBATIM. In particular an
        # UN-typed parameter must stay un-annotated -- adding a TypeVar/annotation
        # forces a new module-level import + assignment that the AST merge can
        # place AFTER the function that references it (a forward-reference
        # NameError; the merge's reorder pass does not track annotation refs).
        parts += [
            '',
            'Reproduce the signature EXACTLY as shown: identical parameter names '
            'and identical type annotations (if a parameter is un-annotated, leave '
            'it un-annotated). Do NOT add, remove, or change any annotation, and do '
            'NOT introduce TypeVars or imports solely to annotate.',
        ]
    if unit.decorators:
        parts += ['', 'Decorators (apply them):', *[f'    @{d}' for d in unit.decorators]]
    if unit.docstring:
        parts += ['', 'Docstring (the intended behavior):', '', _indent(unit.docstring)]
    cross_signatures = cross_signatures or []
    if cross_signatures:
        parts += [
            '',
            'You may also call these functions defined in OTHER modules of this '
            'project (already imported in the target module). Call them QUALIFIED '
            'exactly as shown:',
            *[f'    {s}' for s in cross_signatures],
        ]
    sibling_bodies = sibling_bodies or []
    if sibling_bodies:
        # Sibling-body injection: this unit CALLS these already-reconstructed
        # siblings, so the differential fuzzer needs their real bodies in the
        # submission to execute the unit. The agent must reproduce them verbatim.
        parts += [
            '',
            'This function CALLS the following sibling functions, which are ALREADY '
            'reconstructed. Include each of them VERBATIM at the top of your file '
            '(unchanged), then define the target function below them:',
            '',
            *sibling_bodies,
        ]
    elif sibling_signatures:
        parts += [
            '',
            'Sibling functions already present in the module (signatures only; you may call them):',
            *[f'    {s}' for s in sibling_signatures],
        ]
    if unit_test_text:
        parts += ['', 'The function MUST pass these tests:', '', unit_test_text]
    if partial_edit:
        # P1 (C9.14): this unit lives in a MODULE FILE too large to round-trip as a
        # whole-file submission through the AST merge. Per the PARTIAL-EDIT DISPATCH
        # section the worker prepends, the agent emits a __JANUSMASK_PATCHES__ symbol
        # patch carrying ONLY this unit's reconstructed def/class; git_integration
        # applies it in place, preserving every other byte of the large file. No
        # sibling bodies are inlined (the patch is one block); sibling/cross calls
        # resolve from the already-reconstructed file (dep order).
        # The __JANUSMASK_PATCHES__ 'name' is the in-file symbol path that
        # _apply_symbol_patch resolves: a bare top-level name, or dotted
        # ``Class.method`` for a method. (unit.qualname is ``module:Class.method`` --
        # the module prefix must NOT appear in the patch name.)
        if is_whole:
            patch_name = unit.cls
        elif unit.cls:
            patch_name = f'{unit.cls}.{unit.name}'
        else:
            patch_name = unit.name
        what = f'class {unit.cls}' if is_whole else f'def {unit.name}'
        parts += [
            '',
            'PARTIAL EDIT (the target module file is large -- do NOT reproduce it). '
            'Per the PARTIAL-EDIT DISPATCH instructions above, submit ONE '
            '__JANUSMASK_PATCHES__ list with EXACTLY this single entry:',
            '',
            '    __JANUSMASK_PATCHES__ = [',
            f'        {{{"file"!r}: {module_rel!r}, {"kind"!r}: {"symbol"!r}, {"name"!r}: {patch_name!r},',
            "         'code': r'''<your fully reconstructed " + what + " here>'''},",
            '    ]',
            '',
            f'The ``code`` value MUST be exactly the ONE reconstructed {what} (with '
            'its decorators if any) and nothing else. Call any sibling or cross-module '
            'functions by name -- they already exist in the file. Do NOT include the '
            'tests, imports, or any other top-level statement in the patch code.',
        ]
    elif is_whole:
        sib_note = (
            'You may include the verbatim sibling functions shown above at module '
            'scope (outside the class) if a method calls them. '
            if sibling_bodies else ''
        )
        parts += [
            '',
            f'Write a single self-contained Python file that defines the COMPLETE '
            f'class {unit.cls} with EVERY method fully implemented (use the exact '
            f'signatures from the skeleton above; do not add or drop methods). '
            f'{sib_note}Include any imports needed at the top of the file. Do NOT '
            f'include the tests in your submission.',
        ]
    elif is_method:
        sib_note = (
            'You may include the verbatim sibling functions shown above at module '
            'scope (outside the class) if your method calls them. '
            if sibling_bodies else ''
        )
        parts += [
            '',
            f'Write a single self-contained Python file that defines:\n'
            f'    class {unit.cls}:\n'
            f'        <the method `{unit.name}` fully implemented with the signature above>\n'
            f'Define ONLY this one method inside the class -- the harness preserves the '
            f'class\'s other methods. {sib_note}Include any imports needed at the top of '
            f'the file. Do NOT include the tests in your submission.',
        ]
    elif sibling_bodies:
        parts += [
            '',
            'Write a single self-contained Python file that includes the verbatim '
            'sibling functions above AND defines the target function (include any '
            'imports needed at the top). Do NOT include the tests in your submission.',
        ]
    else:
        parts += [
            '',
            'Write a single self-contained Python file that DEFINES this function '
            '(include any imports it needs at the top of the file). Define ONLY this '
            'function. Do NOT include the tests in your submission.',
        ]
    return '\n'.join(parts)


def _indent(text: str, prefix: str = '    ') -> str:
    return '\n'.join(prefix + line for line in text.splitlines())


def _cls_token(cls: str) -> str:
    """Normalize a class name to the lower, underscore-stripped token used by the
    CLASS-FIRST method-test convention ``test_<clstoken>_<method>_<behaviour>``
    (e.g. ``BriefValidationError`` -> ``briefvalidationerror``). Keeping this in
    one place keeps ``_k_expr`` (the selector) and the gen-testless author token
    (loop.py) from drifting apart."""
    return cls.strip('_').replace('_', '').lower()


def _k_expr(name: str, cls: str | None = None) -> str:
    """A quoted pytest ``-k`` expression matching ``name``'s tests robustly.

    pytest ``-k`` does case-insensitive substring matching against the full
    node id (file::Class::method). The author convention (``build_author_prompt``)
    is ``test_<unit>_<behaviour>`` for functions and ``Test<Camel>`` for classes,
    so we ANCHOR the match to those boundaries: ``test_<unit>`` and ``Test<Camel>``.

    For a METHOD unit (``cls`` given, the class name) the convention is CLASS-FIRST
    ``test_<clstoken>_<method>_<behaviour>`` and the selector is the single anchored
    token ``test_<clstoken>_<method>_`` (P0/#44). This is load-bearing for ANY OOP
    project: two same-named methods in different classes (every project's
    ``__init__``) otherwise both reduce to a bare ``test_<method>_`` (here ``__init__``
    -> ``test_init_``) and ENTANGLE -- verifying one runs the OTHER's scoped test,
    so while a sibling class's method is still a NotImplementedError stub it
    false-fails, cascading to dependents (witnessed #43: ``BriefValidationError.__init__``
    + ``BriefTooLargeError.__init__`` -> the stubbed sibling crashed ``_parse_frontmatter``).
    The class token disambiguates: ``test_briefvalidationerror_init_`` vs
    ``test_brieftoolargeerror_init_`` are DISJOINT. A bare ``Test<ClassCamel>`` variant
    is deliberately NOT emitted for a single method (it would re-pull the class's
    OTHER method tests); whole_class units pass ``cls=None`` and keep the class form.

    Anchoring is load-bearing for PRECISION (session #39, inflection). Two
    collision modes both bit a real external lib:
      (1) a BARE de-underscored token (``irregular`` for ``_irregular``)
          substring-matches a SIBLING's behaviour-named test
          (``test_pluralize_irregular_word``), pulling in pluralize's still-
          stubbed test; ``test_irregular_`` does not.
      (2) a unit name that is a PREFIX of a sibling (``ordinal`` vs
          ``ordinalize``): bare ``test_ordinal`` substring-matches
          ``test_ordinalize_*``. The TRAILING underscore disambiguates -- the
          author convention is ``test_<UNIT>_<behaviour>``, so
          ``test_ordinal_`` matches ``test_ordinal_suffixes`` but NOT
          ``test_ordinalize_keeps_sign`` (after ``test_ordinal`` comes ``ize``,
          not ``_``).
    So the function form is anchored as ``test_<unit>_`` (leading + trailing
    boundary). The trailing ``_`` relies on the author always appending a
    behaviour suffix (build_author_prompt mandates ``test_<UNIT>_<behaviour>``);
    a suffix-less ``test_<unit>`` would miss -> pytest exit 5 -> the whole-file
    fallback (task.build_unit_task) still runs it.

    ``Test<Camel>`` matches a CamelCase test class directly (vendored suites).
    These prefixes also subsume the older de-underscored hack: a dunder
    ``__post_init__`` -> ``test_post_init_`` matches ``test_post_init_*`` (#37).
    Single-quoted so the ``or`` expression survives the shell.
    """
    stripped = name.strip('_')
    if cls:
        return "'" + f'test_{_cls_token(cls)}_{stripped}_' + "'"
    camel = ''.join(part.capitalize() for part in stripped.split('_'))
    variants: list[str] = []
    for v in (f'test_{stripped}_', f'Test{camel}'):
        if v and v not in variants:
            variants.append(v)
    return "'" + ' or '.join(variants) + "'"


def _module_test_files(descriptor: TargetDescriptor, module_rel: str) -> list[str]:
    """Test files relevant to ``module_rel`` ONLY: its generated oracle
    (``test_<stem>_generated.py``) plus shipped test files that import it.

    Scopes the per-unit test gate (both the ``-k`` selector and the oracle-SKIP
    whole-file fallback) to a SINGLE module so a multi-module gen_testless batch
    does not CROSS-cascade (EG3, session #47): without this, a unit's whole-file
    fallback runs EVERY module's generated oracle, and a sibling module's test that
    calls a still-stubbed unit (NotImplementedError) FALSELY rejects this unit's
    correct reconstruction. Returns ``[]`` when nothing matches (caller keeps the
    full list as a safe fallback).
    """
    base = (module_rel[:-3] if module_rel.endswith('.py') else module_rel).replace('/', '.')
    stem = base.split('.')[-1]
    gen = f'test_{stem}_generated.py'
    out: list[str] = []
    for tf in descriptor.test_files:
        if tf.rsplit('/', 1)[-1] == gen:
            out.append(tf)
            continue
        try:
            src = (descriptor.source_root / tf).read_text(encoding='utf-8')
        except OSError:
            continue
        if base in src or f'import {stem}' in src or f'.{stem} import' in src:
            out.append(tf)
    return out


def build_unit_task(
    *,
    descriptor: TargetDescriptor,
    unit: Unit,
    module_rel: str,
    oracle_original_path: str,
    sibling_signatures: list[str],
    unit_test_text: str,
    parent_root: str,
    sibling_bodies: list[str] | None = None,
    cross_signatures: list[str] | None = None,
    fuzz_str_ascii: bool = False,
    partial_edit: bool = False,
    rebuild_oracle_primary: bool = False,
) -> dict:
    """Return the task dict orchestrator_worker consumes to reconstruct ``unit``.

    For an IMPURE unit (``unit.impure``) the merged==original oracle is
    unreliable (nondeterministic / IO output), so the verification_command
    drops the oracle gate and relies on the unit's scoped tests only. When the
    unit calls already-reconstructed siblings, ``sibling_bodies`` are injected
    into the spec so the fuzzer can execute the call. ``cross_signatures`` lists
    callees defined in OTHER project modules (already reconstructed, in dep
    order) so a cross-module caller can be reconstructed against them. A method
    unit (``unit.cls`` set) gets a class-scoped task_id so two same-named methods
    in different classes never collide.
    """
    if getattr(unit, 'whole_class', False):
        task_id = f'RB_{descriptor.name}_{unit.cls}'
    elif unit.cls:
        task_id = f'RB_{descriptor.name}_{unit.cls}_{unit.name}'
    else:
        task_id = f'RB_{descriptor.name}_{unit.name}'
    spec = _build_spec(
        unit, sibling_signatures, unit_test_text,
        # A partial-edit submission is a single-symbol __JANUSMASK_PATCHES__ entry,
        # so sibling BODIES are not inlined (they already live in the large file);
        # only their signatures are surfaced for call-by-name.
        sibling_bodies=[] if partial_edit else sibling_bodies,
        cross_signatures=cross_signatures,
        partial_edit=partial_edit, module_rel=module_rel,
    )
    config_abs = f'{parent_root}/harness/config.yaml'
    # Scoped pytest runs under the replicant's OWN venv python when one has been
    # provisioned (descriptor.python_exe, or a ready ``<out>/.venv``), so the
    # rebuilt module's external deps resolve from ``<out>/.venv`` -- the
    # environment-faithful path. The merged==original ORACLE always stays on the
    # parent ambient python (``oracle.py`` imports ``harness``). NO parent
    # PYTHONPATH, so ``import <reconstructed module>`` resolves to the output
    # repo (cwd) and the test verifies the rebuilt code, not the parent original.
    out = descriptor.output_dir
    if descriptor.python_exe:
        test_py = descriptor.python_exe
    elif _venv.venv_ready(out):
        test_py = str(_venv.venv_python(out))
    else:
        test_py = 'python'
    # EG3: scope the gate to THIS module's test files (its generated oracle +
    # shipped tests that import it), never every module's generated oracle, so a
    # multi-module gen_testless batch does not cross-cascade.
    _module_tfs = _module_test_files(descriptor, module_rel)
    _gate_tfs = _module_tfs if _module_tfs else descriptor.test_files
    whole_file_args = ' '.join(_gate_tfs)
    # P0a (C9.16): compute oracle-usability BEFORE the test gate so the ``-k``
    # exit-5 fallback can choose oracle-only (ground truth) vs whole-file. The
    # full oracle_skip rationale is documented just below, before its vcmd use.
    oracle_skip = (
        bool(getattr(unit, 'impure', False))
        or bool(getattr(unit, 'needs_deps', False))
        or bool(getattr(unit, 'untyped', False))
        or bool(getattr(unit, 'whole_class', False))
        or bool(getattr(unit, 'rel_import', False))
        or bool(getattr(unit, 'self_mutating', False))
        or bool(getattr(unit, 'unfuzzable', False))
    )
    has_oracle = not oracle_skip
    if descriptor.unit_test_selector:
        _kcls = unit.cls if (unit.cls and not getattr(unit, 'whole_class', False)) else None
        _kexpr = _k_expr(unit.name, _kcls)
        # EG3: scope -k selection to THIS module's test files. The selector template
        # is "<files> -k {unit}"; rebuild it from the module-scoped file list so a
        # sibling module's generated oracle never enters this unit's pytest
        # invocation (a collection error / stubbed-sibling test there would poison
        # an otherwise-correct reconstruction).
        if _module_tfs:
            sel_args = f'{whole_file_args} -k {_kexpr}'
        else:
            sel_args = descriptor.unit_test_selector.replace('{unit}', _kexpr)
        # ``-k <unit>`` scoping keeps a MULTI-unit module's still-stubbed siblings
        # out of the run. But some suites name tests by behavior, not by the
        # function under test, so ``-k`` can match NOTHING -> pytest exit 5.
        if has_oracle:
            # Oracle-USABLE unit: on exit 5 (no -k match) the merged==original
            # ORACLE alone is the gate (we possess the original = ground truth).
            # NEVER fall to the whole test file -- it runs still-STUBBED siblings'
            # tests and cascade-rejects a CORRECT reconstruction (C9.15e/#39 g14).
            # A real test failure (exit 1) is never masked.
            test_cmd = (
                f'{test_py} -m pytest {sel_args} -q; __rc=$?; '
                f'if [ "$__rc" = "5" ]; then __rc=0; fi; exit $__rc'
            )
        elif whole_file_args:
            # Oracle-SKIP unit: no usable oracle, so the scoped tests are the only
            # gate -> keep the whole-file fallback on exit 5 (a behaviour-named
            # suite can still cascade here; supply a per-unit-named operator test).
            test_cmd = (
                f'{test_py} -m pytest {sel_args} -q; __rc=$?; '
                f'if [ "$__rc" = "5" ]; then {test_py} -m pytest {whole_file_args} -q; __rc=$?; fi; '
                f'exit $__rc'
            )
        else:
            test_cmd = f'{test_py} -m pytest {sel_args} -q'
    elif whole_file_args:
        test_cmd = f'{test_py} -m pytest {whole_file_args} -q'
    else:
        # No -k selector AND no test files: a bare ``pytest -q`` (no path) collects
        # the WHOLE output dir, sweeping in any stray agent scratch test_*.py left in
        # the output root. A scratch file with a top-level ``sys.exit(pytest.main())``
        # crashes collection with a pytest INTERNALERROR (exit 3) -> the unit's
        # correct reconstruction is spuriously rolled back. Emit NO test gate here;
        # the merged==original oracle is the sole gate. (A test-less module rebuilt
        # WITH gen_testless registers its generated oracle into descriptor.test_files
        # + unit_test_selector, so this branch only hits a misconfigured/no-oracle
        # --no-gen-testless run.)
        test_cmd = None
    # A unit oracle-skips when the merged==original differential oracle is
    # unusable: nondeterministic/IO (impure); module imports an external dep
    # (needs_deps); UN-typed signature (untyped -> the hint-aware fuzzer's input
    # domain is unconstrained, so a correct body false-diverges, the #34
    # ``longest([[]])`` reject); a whole CLASS (no per-function fuzz); or a
    # RELATIVE import (rel_import -> the oracle execs the source standalone, where
    # ``from .x import y`` raises ImportError). The unit's scoped tests (run in
    # the replicant venv for needs_deps) are then its real spec.
    # A whole_class unit is gated by the class's (shared, multi-method) tests, not
    # the per-function differential fuzzer / merged==original oracle (neither can
    # fuzz or compare a CLASS as if it were one function), so it always oracle-skips.
    # A SELF-MUTATING method (dataclass __post_init__ / value-less setter) has no
    # constructible fuzz domain and the oracle resolves it by module-namespace name
    # -> a method is never found there, so every input matches as a NameError and
    # the merged==original gate reports a VACUOUS equivalent=True; route it to the
    # tests-only path so the pytest oracle is the sole, honest gate (C9.11e).
    # A unit with a NON-FUZZABLE typed param (unfuzzable: a ``Path``/domain-object
    # the fuzzer can only synth as a garbage int) over-fuzzes a correct body into a
    # FALSE divergence (e.g. a thin constructor wrapper forwarding paths into a
    # dataclass), so it too routes to tests-only. (oracle_skip / has_oracle are
    # computed above, before the test gate, so the ``-k`` exit-5 fallback can pick
    # oracle-only vs whole-file -- P0a.)
    if oracle_skip:
        # Oracle-skip: tests-only path for nondeterministic / IO / dep units. If
        # there is no test gate either (misconfigured test-less + no oracle), fail
        # LOUD rather than emit a path-less whole-dir pytest (cruft-collection crash).
        vcmd = test_cmd if test_cmd else (
            "echo 'rebuild misconfig: oracle-skip unit has no scoped tests' >&2; exit 1"
        )
    else:
        # Oracle: invoked as a FILE (not -m) so it bootstraps the parent harness
        # on sys.path itself and is immune to the output repo's cwd shadowing its
        # own harness package. It reads recon/orig as file text, so it never
        # imports the replicant package.
        oracle_cmd = (
            f'python {parent_root}/harness/rebuild/oracle.py '
            f'--target {module_rel} --original {oracle_original_path} '
            f'--unit {unit.name} --config {config_abs}'
            + (' --str-ascii' if fuzz_str_ascii else '')
        )
        # When no scoped test gate exists, the merged==original oracle is the sole
        # gate (never append a path-less ``&& pytest -q`` whole-dir collection).
        vcmd = f'{oracle_cmd} && {test_cmd}' if test_cmd else oracle_cmd
    spec_dict = {
        'task_id': task_id,
        'specification': spec,
        'constraints': {'function_signature': unit.signature},
        'files_touched': [module_rel],
        'verification_command': vcmd,
    }
    if fuzz_str_ascii:
        # REBUILD-SCOPED: opt the worker's Claude==Gemini differential gate into the
        # restricted str alphabet (fuzz_from_task reads this off the task spec). Only
        # set on rebuild units, so the main pipeline's fuzzing is unaffected (W1).
        spec_dict['fuzz_str_ascii'] = True
    if oracle_skip:
        # An impure / dep-importing unit's two agent drafts legitimately diverge
        # on out-of-spec fuzz inputs (the same nondeterminism / unavailable dep
        # that makes the oracle unreliable), which would push the orchestrator
        # into a meaningless DECOMPOSITION of an atomic function. So route these
        # units through a fuzzer-bypass meta_task_type: the worker validates the
        # merged body via the scoped verification_command (the unit's tests, run
        # in the replicant venv for dep units = its real spec) and AST-merges the
        # accepted draft, instead of requiring Claude==Gemini agreement.
        spec_dict['meta_task_type'] = 'harness_plumbing'
    if partial_edit:
        # P1 KEYSTONE (C9.14): an over-budget MODULE file can't round-trip as a
        # whole-file submission, so the unit is reconstructed as a single-symbol
        # __JANUSMASK_PATCHES__ patch applied in place by git_integration. The patch
        # list is not normal module code and is un-fuzzable, so route it through the
        # fuzz-bypass + smoke-skip harness_plumbing policy; the merged==original
        # oracle (when not oracle_skip) + scoped tests run against the PATCHED file
        # post-commit and remain the gate (V2 rolls back on failure).
        spec_dict['partial_edit'] = True
        spec_dict['meta_task_type'] = 'harness_plumbing'
    if rebuild_oracle_primary and not oracle_skip:
        # P0 (C9.15): ORACLE-PRIMARY rebuild gate. For a clean-room rebuild we
        # POSSESS the original, so the merged==original oracle (word-domain when
        # fuzz_str_ascii) is GROUND TRUTH; the Claude==Gemini differential is a
        # redundant proxy whose FALSE-divergence blocks a CORRECT reconstruction
        # of a quirky rule-table fn (one blind draft omits a catch-all rule and
        # RAISES on a no-match word, the other returns -> the differential fires
        # FIRST and decomposes a correct unit; inflection's stochastic
        # exception_vs_return residual, W1). Route an oracle-USABLE unit through
        # the fuzz-bypass harness_plumbing policy while KEEPING the oracle vcmd
        # (built above): the worker takes a draft and gates on oracle && scoped
        # tests, and reconstruct_unit retries up to max_attempts fresh drafts on
        # failure -- a buggy draft fails the oracle and retries, a correct draft
        # passes. Only for non-oracle-skip units (oracle-skip already routes to
        # tests-only harness_plumbing above); opt-in so the default path keeps the
        # differential's redundancy on units that converge cleanly.
        spec_dict['meta_task_type'] = 'harness_plumbing'
    return spec_dict
