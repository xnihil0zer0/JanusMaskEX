---
interfaces: "edits ngv2/submission_package.py to ADDITIVELY reconcile the two leaves that clobbered each other — leaf bd69ecb (builder) overwrote leaf 1312d31 (template loader), dropping load_submission_template's path=None parameter and file-reading fallback semantics and replacing {{token}}+NOT_PROVIDED_MARKER regex rendering with a single-brace format_map — so that load_submission_template(path=None) again reads a template file with DEFAULT_TEMPLATE fallback, render_template supports BOTH placeholder styles ({{token}} regex substitution with NOT_PROVIDED_MARKER for missing/blank values, and the builder's single-brace format_map path unchanged), the dead loader exports (SECTION_LAYOUT, _PLACEHOLDER_RE, NOT_PROVIDED_MARKER, DEFAULT_TEMPLATE, LEGACY_TEMPLATE_PATH) are live again, and build_submission_package defaults to DEFAULT_SUBMISSION_TEMPLATE directly so the currently-green builder oracle stays green"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/submission_package.py — merge the clobbered template-loader contract (leaf 1312d31) back into the builder module (leaf bd69ecb) ADDITIVELY: restore `load_submission_template(path=None)` file-read + `DEFAULT_TEMPLATE` fallback, make `render_template` dual-mode (`{{token}}`/NOT_PROVIDED_MARKER regex path alongside the single-brace format_map path), and pin `build_submission_package`'s default template to `DEFAULT_SUBMISSION_TEMPLATE` so BOTH committed oracles pass

# Scope

EDIT the EXISTING module ngv2/submission_package.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). This brief is independent of the three session-stack briefs and may be dispatched in parallel.

DEFECT (verified against NGv2 HEAD `44bfb3c`, 2026-06-11): the builder leaf `bd69ecb` ("submission-package-builder") rewrote the module on top of the loader leaf `1312d31` ("submission-package-template-loader") and clobbered the loader's committed contract. Current HEAD source, lines 35-58:

    def load_submission_template() -> str:
        """Return the submission report template.

        The loader task may provide a richer legacy template; when none is
        available the built-in :data:`DEFAULT_SUBMISSION_TEMPLATE` is returned so
        the renderer always has all nine sections to work with.
        """
        return DEFAULT_SUBMISSION_TEMPLATE
    from typing import Any

    def render_template(template: str, context: Mapping[str, Any]) -> str:
        """Fill ``{token}`` placeholders in ``template`` from ``context``.
        ...
        """
        safe = _SafeContext()
        for field_name, value in context.items():
            if value is None or value == '':
                safe[field_name] = PLACEHOLDER
            else:
                safe[field_name] = value
        return template.format_map(safe)

Compared to `git -C /home/xnihil0zer0/NobleGreedv2 show 1312d31:ngv2/submission_package.py`, `load_submission_template()` LOST its `path: Optional[str]=None` parameter and its read-file-then-fallback-to-`DEFAULT_TEMPLATE` body; `render_template` LOST the `{{token}}` `_PLACEHOLDER_RE` regex substitution with `NOT_PROVIDED_MARKER` for missing/None/blank values (single-brace `format_map` cannot substitute `{{title}}` — it renders it as the literal `{title}`); and the loader's module constants `SECTION_LAYOUT`, `_PLACEHOLDER_RE`, `NOT_PROVIDED_MARKER`, `DEFAULT_TEMPLATE` (built by `_build_default_template()` from `SECTION_LAYOUT`) and `LEGACY_TEMPLATE_PATH` were left as DEAD code (still defined at lines 20-33, referenced by nothing). Result: tests/test_submission_package.py has 6/19 failing while tests/ngv2/test_submission_package_wired.py (builder contract, 17 tests) is GREEN and MUST STAY GREEN.

CRITICAL constraint discovered during triage: the legacy template file `/home/xnihil0zer0/AI-Data/NobleGreed-legacy/orchestrator/templates/submission_report_template.md` EXISTS on this machine and contains NO `{{token}}` placeholders and different section headings — so `build_submission_package` MUST NOT default its template through `load_submission_template()` (which, restored, would read that file and break every green builder test, besides being unhermetic). The builder's default is pinned to the module constant `DEFAULT_SUBMISSION_TEMPLATE` directly.

THE FIX (data_model — three whole-function replacements, everything else byte-for-byte):

(1) `load_submission_template` — restore the leaf-1312d31 version VERBATIM (the `Optional` import already exists at line 19):

    def load_submission_template(path: Optional[str]=None) -> str:
        """Return the submission report template's contents.

        Reads the Markdown template from ``path`` (defaulting to the legacy
        template path). If the resolved path does not exist or cannot be read,
        the built-in default template -- which still contains all nine required
        section headers in order -- is returned instead.
        """
        resolved = LEGACY_TEMPLATE_PATH if path is None else path
        try:
            with open(resolved, 'r', encoding='utf-8') as handle:
                return handle.read()
        except OSError:
            return DEFAULT_TEMPLATE

(2) `render_template` — dual-mode merge: when the template contains `{{token}}` placeholders (`_PLACEHOLDER_RE.search`), use the loader's regex substitution (each `{{name}}` becomes `str(context[name])`, with `NOT_PROVIDED_MARKER` for missing keys, `None`, or whitespace-only values; unreferenced context keys are ignored); otherwise the builder's single-brace `format_map` path runs BYTE-IDENTICAL to HEAD. EXACT corrected target (reproduce VERBATIM):

    def render_template(template: str, context: Mapping[str, Any]) -> str:
        """Fill placeholders in ``template`` from ``context``.

        Supports BOTH committed placeholder styles:

        * ``{{token}}`` (template-loader contract): each placeholder is replaced
          with ``str(context[token])``; missing keys, ``None`` and blank values
          render as :data:`NOT_PROVIDED_MARKER`; context keys not referenced by
          any placeholder are ignored (never appended to the output).
        * ``{token}`` (builder contract): rendered via :meth:`str.format_map`
          over a safe mapping; empty or ``None`` values collapse to
          :data:`PLACEHOLDER`.  Substituted values are inserted verbatim (they
          are not re-parsed for braces).
        """
        mapping = context or {}
        if _PLACEHOLDER_RE.search(template):

            def _substitute(match: 're.Match[str]') -> str:
                field_name = match.group(1)
                value = mapping.get(field_name)
                if value is None:
                    return NOT_PROVIDED_MARKER
                text = value if isinstance(value, str) else str(value)
                if text.strip() == '':
                    return NOT_PROVIDED_MARKER
                return text
            return _PLACEHOLDER_RE.sub(_substitute, template)
        safe = _SafeContext()
        for field_name, value in mapping.items():
            if value is None or value == '':
                safe[field_name] = PLACEHOLDER
            else:
                safe[field_name] = value
        return template.format_map(safe)

(3) `build_submission_package` — reproduce the HEAD function byte-for-byte EXCEPT the default-template branch, which becomes:

    if template is None:
        template = DEFAULT_SUBMISSION_TEMPLATE

(replacing `template = load_submission_template()` — see the CRITICAL constraint above; an explicit `template=` argument keeps overriding as today).

After this merge every formerly-dead loader export is live again: `LEGACY_TEMPLATE_PATH` and `DEFAULT_TEMPLATE` are used by `load_submission_template`, `_PLACEHOLDER_RE` and `NOT_PROVIDED_MARKER` by `render_template`, and `SECTION_LAYOUT` by `_build_default_template` (which builds `DEFAULT_TEMPLATE`). Do NOT change `__all__` — the loader oracle accesses these via module attributes, which works regardless. Read the read-only staged target at `{WORK_DIR}/inbox/targets/ngv2/submission_package.py` FIRST and reproduce everything outside the three pinned functions byte-for-byte. NO new imports are needed (`re`, `Mapping`, `Optional`, `Any` are all already imported at module level). Verify GREEN with `python -m pytest tests/test_submission_package.py tests/ngv2/test_submission_package_wired.py -q`; working_dir is /home/xnihil0zer0/NobleGreedv2.

DISPATCH DIRECTIVE — PATCH FORMAT (whole-symbol patches on EXISTING 1-part top-level functions — the canonical safe shape): emit a single top-level `__JANUSMASK_PATCHES__` list with EXACTLY THREE entries:

    __JANUSMASK_PATCHES__ = [
        {'file': 'ngv2/submission_package.py', 'kind': 'symbol', 'name': 'load_submission_template',
         'code': r'''<the EXACT corrected load_submission_template pinned in Scope (1), byte-for-byte>'''},
        {'file': 'ngv2/submission_package.py', 'kind': 'symbol', 'name': 'render_template',
         'code': r'''<the EXACT corrected render_template pinned in Scope (2), byte-for-byte>'''},
        {'file': 'ngv2/submission_package.py', 'kind': 'symbol', 'name': 'build_submission_package',
         'code': r'''<the staged target's build_submission_package reproduced byte-for-byte with ONLY the default branch changed to: template = DEFAULT_SUBMISSION_TEMPLATE>'''},
    ]

Each `name` MUST be the 1-part TOP-LEVEL function name — never a dotted qualname, never a manifest, never a whole-file rewrite, never any extra top-level node (the fix needs NO new symbol and NO new import; `_SafeContext`, `PLACEHOLDER`, `DEFAULT_SUBMISSION_TEMPLATE`, `LEGACY_TEMPLATE_PATH`, `DEFAULT_TEMPLATE`, `_PLACEHOLDER_RE`, `NOT_PROVIDED_MARKER`, `re`, `Mapping`, `Optional`, `Any` all already exist at module level). POST-EMIT SELF-CHECK (mandatory): the `load_submission_template` code must START with `def load_submission_template(path: Optional[str]=None) -> str:` at column 0 and contain `LEGACY_TEMPLATE_PATH if path is None else path`, `open(resolved, 'r', encoding='utf-8')` and `return DEFAULT_TEMPLATE`; the `render_template` code must START with `def render_template(template: str, context: Mapping[str, Any]) -> str:` at column 0, contain `_PLACEHOLDER_RE.search(template)`, `NOT_PROVIDED_MARKER` (twice), `_PLACEHOLDER_RE.sub(_substitute, template)`, AND the unchanged format_map tail (`safe = _SafeContext()` ... `return template.format_map(safe)`); the `build_submission_package` code must START with `def build_submission_package(finding: dict, poc: dict, live_report: dict, template: Optional[str]=None) -> str:` at column 0, contain `template = DEFAULT_SUBMISSION_TEMPLATE`, NOT contain `load_submission_template()`, and keep the context dict and `return render_template(template, context)` line unchanged; each entry must contain exactly ONE top-level `def` (an inner nested `def _substitute` is expected inside render_template) and no `class ` / `import ` statements.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM: `task_id`: `ngv2-submission-package-reconcile`. meta_task_type=`data_model` (external NGv2 target — the diff-fuzzer cannot resolve external imports, so use a fuzzer-bypassed, smoke-gated meta-type). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["ngv2/submission_package.py"]` ONLY. partial_edit semantics: a single `__JANUSMASK_PATCHES__` list with EXACTLY THREE `'symbol'` entries whose `name`s are the 1-part top-level `'load_submission_template'`, `'render_template'`, `'build_submission_package'` (whole-function replacements per the DISPATCH DIRECTIVE — never dotted, never a manifest, never a whole-file rewrite, no extra nodes). The DISPATCH DIRECTIVE — PATCH FORMAT paragraph above MUST be copied VERBATIM into the task's `implementation_notes` together with the corrected function sources so the blind worker sees them. verification_command: `python -m pytest tests/test_submission_package.py tests/ngv2/test_submission_package_wired.py -q`. The committed RED oracle tests/test_submission_package.py (6 failing of 19) is the authoritative acceptance contract and the committed GREEN oracle tests/ngv2/test_submission_package_wired.py (17 passing) is the non-regression contract — make the former GREEN while the latter STAYS green; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from this brief's committed RED oracle file (plan descriptors referencing committed/landed tests — this does NOT authorize authoring new tests), so every `spec.edge_cases` entry is reflected per the validator's edge-case rule (e.g. `test_render_template_substitutes_named_placeholders` and `test_load_template_falls_back_to_default_when_missing`; also good: `test_render_template_marks_missing_fields`, `test_extra_fields_are_ignored_not_appended`, `test_load_template_reads_legacy_path_when_present`).

# Non-Goals

This is an EDIT and integration is out of scope: the task's non_goals MUST declare integration testing out of scope — do NOT add integration/e2e tests; this fix is verified solely by the two committed unit oracles in the verification command. Do NOT author or modify any test — both oracles are committed and authoritative. Replace ONLY the three pinned functions. Do NOT change `SECTION_LAYOUT`, `_build_default_template`, `DEFAULT_TEMPLATE`, `_PLACEHOLDER_RE`, `NOT_PROVIDED_MARKER`, `LEGACY_TEMPLATE_PATH`, `PLACEHOLDER`, `SECTION_HEADERS`, `DEFAULT_SUBMISSION_TEMPLATE`, `__all__`, `_SafeContext`, or any `_render_*` / `_text` / `_fenced` helper — they are all correct at HEAD and the merge re-wires the dead ones purely by USING them. Do NOT make `build_submission_package` read the on-disk legacy template (unhermetic — the file exists on this machine and is placeholder-free; the builder default is the in-module `DEFAULT_SUBMISSION_TEMPLATE` constant) and do NOT remove or rename its `template: Optional[str]=None` keyword. Do NOT unify the two placeholder syntaxes, "simplify" to a single rendering path, or strip/re-parse substituted values for braces (the builder contract requires verbatim insertion). Do NOT add new imports, module-level symbols, network access, wall-clock, randomness, or third-party dependencies (the only I/O in the module is `load_submission_template`'s explicit, fallback-guarded file read — exactly the committed loader contract). Do NOT touch ngv2/session_gate.py (its `build_submission_package` seam binding picks this module up unchanged), tests/, or any other module.

# Inputs

The committed authoritative oracles (NGv2 HEAD `44bfb3c`; counts confirmed live 2026-06-11):

- RED: tests/test_submission_package.py — 6 failing of 19: `test_load_template_reads_legacy_path_when_present` (calls `sp.load_submission_template(str(tmp_file))` — TypeError today: takes 0 args), `test_load_template_falls_back_to_default_when_missing` (missing path → must return `sp.DEFAULT_TEMPLATE`), `test_render_template_substitutes_named_placeholders` (`'Name: {{title}} / Class: {{cwe}}'` must render fully, no `{{` left — format_map renders the literal `{title}` today), `test_render_template_marks_missing_fields` (absent key AND whitespace-only `'   '` value → `sp.NOT_PROVIDED_MARKER`), `test_loaded_template_renders_cleanly_with_full_field_set` (the `{{token}}` `DEFAULT_TEMPLATE` over `SECTION_LAYOUT` field names renders with no braces and no marker), `test_extra_fields_are_ignored_not_appended` (unreferenced context keys must not appear). The other 13 (including the in-file builder tests and `test_render_template_never_leaves_unsubstituted_placeholder_for_known_fields`) pass today and must stay green.
- GREEN / non-regression: tests/ngv2/test_submission_package_wired.py — 17 passing builder tests (nine ordered `## ` sections from `DEFAULT_SUBMISSION_TEMPLATE`, strict source routing finding/poc/live_report with no sentinel leakage, `PLACEHOLDER` degradation for missing keys/None inputs) — every one must still pass after the merge.

The EXACT current defective HEAD source of the two clobbered functions is quoted in Scope; the HEAD `build_submission_package` (lines 168-186) is correct except its `template = load_submission_template()` default line. The clobbered loader reference is `git -C /home/xnihil0zer0/NobleGreedv2 show 1312d31:ngv2/submission_package.py` — its `load_submission_template(path: Optional[str]=None)` is restored VERBATIM in Scope (1) and its `_substitute` regex renderer is merged into Scope (2)'s dual-mode `render_template`. The builder leaf is `bd69ecb`. Module constants involved (READ-ONLY, all already at HEAD): `LEGACY_TEMPLATE_PATH` (line 20), `NOT_PROVIDED_MARKER = '_Not provided_'` (line 21), `SECTION_LAYOUT` (line 22 — note its fourth field name is `vulnerable_code_references`, which is WHY the `{{token}}` `DEFAULT_TEMPLATE` cannot serve as the builder default whose context key is `code_refs`), `DEFAULT_TEMPLATE` (line 32), `_PLACEHOLDER_RE = re.compile('\\{\\{\\s*([A-Za-z0-9_]+)\\s*\\}\\}')` (line 33), `PLACEHOLDER = '_Not provided_'` (line 61), `DEFAULT_SUBMISSION_TEMPLATE` (line 63, single-brace), `_SafeContext` (line 66). stdlib only.

# Deliverables

Edited ngv2/submission_package.py in which `load_submission_template(path=None)` reads a template file with `DEFAULT_TEMPLATE` fallback exactly as leaf 1312d31 shipped it, `render_template` serves BOTH committed contracts (the `{{token}}`/`NOT_PROVIDED_MARKER` regex path when `_PLACEHOLDER_RE` matches, the byte-identical single-brace `format_map`/`PLACEHOLDER` path otherwise), and `build_submission_package` defaults to the in-module `DEFAULT_SUBMISSION_TEMPLATE` (hermetic, never the on-disk legacy file) — with `SECTION_LAYOUT`, `_PLACEHOLDER_RE`, `NOT_PROVIDED_MARKER`, `DEFAULT_TEMPLATE` and `LEGACY_TEMPLATE_PATH` all live again and no other line changed. Verified GREEN by `python -m pytest tests/test_submission_package.py tests/ngv2/test_submission_package_wired.py -q` (19 + 17 passing: the 6 loader regressions flip green, all 30 currently-green cases stay green).
