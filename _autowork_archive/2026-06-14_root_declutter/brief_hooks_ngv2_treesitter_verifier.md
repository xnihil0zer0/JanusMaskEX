---
interfaces: "creates NEW module ngv2/treesitter_verifier.py — a multi-language (C/Java/JavaScript) tree-sitter policy verifier with detection rules held as DATA (a module-level LANGUAGE_QUERIES dict of tree-sitter S-expression query strings evaluated via tree_sitter.Query/QueryCursor, semgrep/ast-grep architecture, NEVER manual recursive tree walks); public surface TreeSitterVerifier.verify(code: str, language: str) -> ngv2.ast_verifier.ASTResult reusing the existing Violation/ASTResult dataclasses; language 'python' delegates to the stdlib ngv2.ast_verifier.ASTVerifier (differential anchor); tree_sitter imported ONLY in-body behind a guard (z3_bridge optional-dependency pattern)"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

NEW module ngv2/treesitter_verifier.py — multi-language tree-sitter policy verifier (C / Java / JavaScript) with detection rules held as DATA (per-language dict of S-expression query strings, evaluated via `tree_sitter.Query` / `tree_sitter.QueryCursor`), public surface `TreeSitterVerifier.verify(code: str, language: str) -> ASTResult` reusing the `Violation` / `ASTResult` dataclasses imported from `ngv2.ast_verifier`, with a Python differential anchor that delegates `language == 'python'` to the existing stdlib `ASTVerifier`

# Scope

CREATE the NEW module ngv2/treesitter_verifier.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). This is a PARALLEL capability module: ngv2/ast_verifier.py and ngv2/ast_constraint.py are stdlib-only by committed contract and are NEVER edited — tree-sitter capability lands ONLY as this new sibling module. Importing the `Violation` / `ASTResult` dataclasses (and `ASTVerifier`, `SEVERITY_ERROR`, `SEVERITY_WARNING`) FROM `ngv2.ast_verifier` into the new module IS allowed and REQUIRED — do NOT redeclare those dataclasses.

THE CONTRACT (pinned by the committed RED oracle tests/ngv2/test_treesitter_verifier_wired.py, NGv2 commit 167d391 — currently RED with `ModuleNotFoundError: No module named 'ngv2.treesitter_verifier'`):

1. Module-level constant `LANGUAGE_QUERIES`: a dict mapping language name -> {rule_id -> tree-sitter S-expression query string}. It MUST contain languages `"c"`, `"java"`, `"javascript"`, each with rule ids `"process_exec"` and `"return_constant_stub"`, whose values are EXACTLY (byte-for-byte) the six query strings given VERBATIM in # Inputs below. The oracle asserts exact string equality — copy them verbatim, do not reformat, re-quote, or re-wrap them. Rules are DATA (semgrep/ast-grep architecture); detection is performed by evaluating these queries, NEVER by manual recursive tree walks (no hand-rolled `node.children` recursion).

2. Class `TreeSitterVerifier` with method `verify(self, code: str, language: str) -> ASTResult`:
   - `language == 'python'`: DELEGATE to the existing stdlib verifier — `return ASTVerifier().verify(code)` (this is the differential anchor; the oracle compares `valid` verdicts and the multiset of violation rule names against `ngv2.ast_verifier.ASTVerifier` on identical source).
   - Otherwise: import tree-sitter IN-BODY behind a guard (see point 3), build `lang = Language(grammar_module.language())` where `grammar_module` is `tree_sitter_c` / `tree_sitter_java` / `tree_sitter_javascript` resolved from the language name (`importlib.import_module("tree_sitter_" + language)` is the clean shape), parse with `Parser(lang).parse(code.encode("utf-8"))`, then for each `(rule_id, query_str)` in `LANGUAGE_QUERIES[language].items()` evaluate `QueryCursor(Query(lang, query_str)).matches(tree.root_node)` and emit EXACTLY ONE `Violation` PER MATCH (not per capture — the Java query has four captures per logical match; use `matches()`, not `captures()`). Every pinned query carries a designated `@viol` capture: `node = captures["viol"][0]`; `Violation.line = node.start_point[0] + 1`; `Violation.rule = rule_id`; `Violation.message` = any non-empty human-readable string (the oracle pins only that it is a non-empty `str`); `Violation.severity` = `SEVERITY_ERROR` for rule `process_exec`, `SEVERITY_WARNING` for rule `return_constant_stub` (imported severity literals, not new strings). Return `ASTResult(valid=<no ERROR-severity violation present>, violations=<the list>)` — same `valid` semantics as ast_verifier (WARNINGs do not invalidate). Sort violations deterministically (e.g. by `(line, rule)`); the oracle's fixtures each produce exactly one violation so any deterministic order passes.

3. OPTIONAL-DEPENDENCY GUARD (mirror ngv2/z3_bridge.py's pattern of never hard-importing the heavy dependency): `import tree_sitter` (and the grammar modules) MUST appear ONLY inside a function/method body, wrapped in `try/except ImportError`; on ImportError return a failed `ASTResult` (valid=False) carrying a single ERROR `Violation` (e.g. rule `"tree_sitter_unavailable"`, line 0). The oracle parses the module source with stdlib `ast` and asserts NO top-level `import tree_sitter*` / `from tree_sitter import ...` exists. (tree-sitter IS installed in the NGv2 venv — tree-sitter 0.25.2, tree-sitter-c 0.24.2, tree-sitter-java 0.23.5, tree-sitter-javascript 0.25.0, verified live 2026-06-11 — so the guard is a pattern requirement, not a skip path.)

4. Determinism: no network, no subprocess, no clock, no randomness, no file I/O in `verify`. Pure function of (code, language).

Verify GREEN with `python -m pytest tests/ngv2/test_treesitter_verifier_wired.py -q`; working_dir is /home/xnihil0zer0/NobleGreedv2.

DISPATCH DIRECTIVE — NEW MODULE = SINGLE-FILE WHOLE-FILE (LOUD): this task creates a file that DOES NOT EXIST at HEAD. Emit the COMPLETE module source of ngv2/treesitter_verifier.py as a single whole-file deliverable. NEVER emit a `__JANUSMASK_PATCHES__` list for this task — there is no existing symbol to patch; a patches-format submission against a non-existent file is the known NEW-file+patches → auto_commit_failed trap. ONE file only: ngv2/treesitter_verifier.py. The module must contain the `LANGUAGE_QUERIES` constant, the `TreeSitterVerifier` class, a module docstring, and nothing else surprising (a small private severity-mapping constant and private helpers are fine; no `__main__` block, no side effects at import time, no module-level tree_sitter import).

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle is keyed to this brief): `task_id`: `ngv2-treesitter-verifier`. meta_task_type=`data_model` (external NGv2 target — the diff-fuzzer cannot resolve external imports, so use a fuzzer-bypassed, smoke-gated meta-type; the module is dominated by a frozen data table of query strings plus a thin evaluation shell). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["ngv2/treesitter_verifier.py"]` ONLY. NEW-module semantics: single-file WHOLE-FILE dispatch per the DISPATCH DIRECTIVE above — never `__JANUSMASK_PATCHES__`, never a manifest, never a multi-file emission. The DISPATCH DIRECTIVE — NEW MODULE paragraph above MUST be copied VERBATIM into the task's `implementation_notes` so the blind worker sees it, along with the full # Inputs section (the worker sees ONLY the brief-derived spec; the query strings and oracle assertions below are its only source of truth). verification_command: `python -m pytest tests/ngv2/test_treesitter_verifier_wired.py -q`. The committed RED oracle tests/ngv2/test_treesitter_verifier_wired.py (NGv2 commit 167d391) is the authoritative acceptance contract — make it GREEN; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from the committed oracle tests/ngv2/test_treesitter_verifier_wired.py (plan descriptors referencing committed/landed tests — this does NOT authorize authoring new tests), so every `spec.edge_cases` entry is reflected per the validator's edge-case rule (e.g. `test_language_queries_are_data_and_pinned_exactly`, `test_c_process_exec_flagged_as_error`, `test_clean_snippets_yield_zero_violations`, `test_python_differential_anchor_matches_stdlib_astverifier`).

# Non-Goals

This is a NEW leaf module and integration is out of scope: the task's non_goals MUST declare integration testing out of scope — do NOT add integration/e2e tests; the module is verified solely by the committed unit oracle tests/ngv2/test_treesitter_verifier_wired.py. Do NOT author or modify any test — that oracle is committed and authoritative. Do NOT touch ngv2/ast_verifier.py or ngv2/ast_constraint.py (both stdlib-only by committed contract — importing FROM ast_verifier is allowed; editing it is forbidden) or any other existing module (ngv2/z3_bridge.py is a read-only pattern reference). Do NOT add new third-party dependencies and do NOT import any of: tree-sitter-language-pack, tree_sitter_languages, semgrep, ast-grep / sgpt, srcML — ONLY `tree_sitter`, `tree_sitter_c`, `tree_sitter_java`, `tree_sitter_javascript` (each in-body, guarded). Do NOT use the legacy pre-0.25 API (`lang.query(...)`, `Language(path, name)`, `parser.set_language(...)`) — the installed tree-sitter is 0.25.2 and uses the `Query(lang, src)` / `QueryCursor(q)` CONSTRUCTORS (verified live; exact idiom embedded in # Inputs). Do NOT implement detection via manual recursive tree walks (`node.children`/`node.named_children` recursion) — rules live as query-string DATA in `LANGUAGE_QUERIES` and are evaluated via Query/QueryCursor only. Do NOT redeclare `Violation` / `ASTResult` / severity literals — import them from `ngv2.ast_verifier`. Do NOT alter, reformat, re-wrap, or "improve" the six pinned query strings (the oracle asserts byte-for-byte equality). Do NOT add extra languages, extra rules, a CLI, file I/O surface (`verify_file`), caching, or a `__main__` block. No network, no subprocess, no wall-clock, no randomness.

# Inputs

The committed authoritative oracle at tests/ngv2/test_treesitter_verifier_wired.py (NGv2 commit 167d391; currently RED at collection with `ModuleNotFoundError: No module named 'ngv2.treesitter_verifier'`). A reference implementation of the contract below was validated GREEN (11/11) against this oracle in the live NGv2 venv on 2026-06-11 before commit — the contract is satisfiable exactly as written.

THE LIVE-VERIFIED tree-sitter 0.25 API IDIOM (verified 2026-06-11 in /home/xnihil0zer0/NobleGreedv2/.venv — tree-sitter 0.25.2, tree-sitter-c 0.24.2, tree-sitter-java 0.23.5, tree-sitter-javascript 0.25.0; note Query/QueryCursor CONSTRUCTORS, not `lang.query()`):

    from tree_sitter import Language, Parser, Query, QueryCursor
    import tree_sitter_c
    lang = Language(tree_sitter_c.language())
    parser = Parser(lang)
    tree = parser.parse(b'int main(){ system("id"); return 0; }')
    q = Query(lang, '(call_expression function: (identifier) @fn (#eq? @fn "system"))')
    caps = QueryCursor(q).captures(tree.root_node)   # -> {'fn': [<node 'system'>]}
    # and the per-match form the module MUST use (one Violation per MATCH):
    for _pattern_index, captures in QueryCursor(q).matches(tree.root_node):
        node = captures['fn'][0]                      # in this module: captures['viol'][0]
        line = node.start_point[0] + 1

THE SIX PINNED QUERY STRINGS — copy each VERBATIM into `LANGUAGE_QUERIES` (every one was live-validated in the venv against the installed grammar wheels: hits on the malicious/stub fixtures at the exact lines the oracle pins, zero captures on the clean fixtures; real node-type names taken from live parse trees — Java string literals contain `string_fragment`, JS strings are `(string)`, JS numbers `(number)`, booleans are named `(true)` / `(false)` nodes in all three grammars; the `.` anchors restrict the stub rule to bodies that are EXACTLY one return-of-a-literal statement):

    LANGUAGE_QUERIES = {
        "c": {
            "process_exec": '(call_expression function: (identifier) @viol (#match? @viol "^(system|popen|execl|execle|execlp|execv|execve|execvp|execvpe)$"))',
            "return_constant_stub": '(function_definition body: (compound_statement . (return_statement [(number_literal) (string_literal) (true) (false)]) .)) @viol',
        },
        "java": {
            "process_exec": '(method_invocation object: (method_invocation object: (identifier) @cls name: (identifier) @factory) name: (identifier) @method (#eq? @cls "Runtime") (#eq? @factory "getRuntime") (#eq? @method "exec")) @viol',
            "return_constant_stub": '(method_declaration body: (block . (return_statement [(string_literal) (decimal_integer_literal) (true) (false)]) .)) @viol',
        },
        "javascript": {
            "process_exec": '(call_expression function: (member_expression property: (property_identifier) @method) (#any-of? @method "exec" "execSync")) @viol',
            "return_constant_stub": '(function_declaration body: (statement_block . (return_statement [(string) (number) (true) (false)]) .)) @viol',
        },
    }

THE REUSED DATACLASS SHAPES — the EXACT committed source from ngv2/ast_verifier.py at HEAD (READ-ONLY — import these, never redeclare, never edit):

    SEVERITY_ERROR = 'ERROR'
    SEVERITY_WARNING = 'WARNING'

    @dataclass
    class Violation:
        """A single policy finding reported by :class:`ASTVerifier`."""
        rule: str
        line: int
        message: str
        severity: str

    @dataclass
    class ASTResult:
        """Outcome of verifying a unit of source.

        ``valid`` is ``True`` when no ERROR-severity violation is present; WARNING
        findings do not invalidate the result.
        """
        valid: bool
        violations: List[Violation] = field(default_factory=list)

        def has_errors(self) -> bool:
            return any((v.severity == SEVERITY_ERROR for v in self.violations))

        def has_warnings(self) -> bool:
            return any((v.severity == SEVERITY_WARNING for v in self.violations))

The import the new module needs:

    from ngv2.ast_verifier import (ASTResult, ASTVerifier, SEVERITY_ERROR,
                                   SEVERITY_WARNING, Violation)

THE ORACLE'S FIXTURES AND KEY ASSERTIONS (verbatim from the committed oracle — line numbers refer to THESE exact snippets):

    C_MALICIOUS = '#include <stdlib.h>\nint main(void) {\n    system("id");\n    return 0;\n}\n'
    C_STUB = 'int is_vulnerable(void) {\n    return 1;\n}\n'
    C_CLEAN = '#include <stdio.h>\nint add(int a, int b) {\n    int s = a + b;\n    printf("%d\\n", s);\n    return s;\n}\n'
    JAVA_MALICIOUS = 'public class Poc {\n    public void run() throws Exception {\n        Runtime.getRuntime().exec("id");\n    }\n}\n'
    JAVA_STUB = 'public class Poc {\n    public String check() {\n        return "VULNERABLE";\n    }\n}\n'
    JAVA_CLEAN = 'public class Calc {\n    public int add(int a, int b) {\n        int s = a + b;\n        return s;\n    }\n}\n'
    JS_MALICIOUS_EXECSYNC = 'const cp = require("child_process");\ncp.execSync("id");\n'
    JS_MALICIOUS_EXEC = 'const cp = require("child_process");\ncp.exec("id", function (e, out) { console.log(out); });\n'
    JS_STUB = 'function poc() {\n    return "VULNERABLE";\n}\n'
    JS_CLEAN = 'function add(a, b) {\n    const s = a + b;\n    return s;\n}\nconsole.log(add(1, 2));\n'
    PY_MALICIOUS = "import os\nos.system('id')\n"
    PY_CLEAN = 'x = 1\nprint(x)\n'

    # _rules(result) -> [(v.rule, v.line, v.severity)] and also asserts
    # isinstance(result, ASTResult), isinstance(v, Violation),
    # v.message is a non-empty str, v.line >= 1.

    # exact per-fixture expectations:
    verify(C_MALICIOUS, 'c')            -> [('process_exec', 3, 'ERROR')];  valid is False; has_errors() is True
    verify(C_STUB, 'c')                 -> [('return_constant_stub', 1, 'WARNING')]; valid is True; has_warnings() is True
    verify(C_CLEAN, 'c')                -> violations == []; valid is True
    verify(JAVA_MALICIOUS, 'java')      -> [('process_exec', 3, 'ERROR')];  valid is False
    verify(JAVA_STUB, 'java')           -> [('return_constant_stub', 2, 'WARNING')]; valid is True
    verify(JAVA_CLEAN, 'java')          -> violations == []; valid is True
    verify(JS_MALICIOUS_EXECSYNC, 'javascript') -> [('process_exec', 2, 'ERROR')]; valid is False
    verify(JS_MALICIOUS_EXEC, 'javascript')     -> [('process_exec', 2, 'ERROR')]; valid is False
    verify(JS_STUB, 'javascript')       -> [('return_constant_stub', 1, 'WARNING')]; valid is True
    verify(JS_CLEAN, 'javascript')      -> violations == []; valid is True

    # differential anchor (python DELEGATES to stdlib ASTVerifier):
    for snippet in (PY_MALICIOUS, PY_CLEAN):
        ts = TreeSitterVerifier().verify(snippet, 'python')
        ref = ASTVerifier().verify(snippet)
        assert ts.valid == ref.valid
        assert sorted(v.rule for v in ts.violations) == sorted(v.rule for v in ref.violations)
    mal = TreeSitterVerifier().verify(PY_MALICIOUS, 'python')
    assert mal.valid is False
    assert any(v.rule == 'os_system' for v in mal.violations)

    # rules-as-data pin (byte-for-byte on all six strings):
    LANGUAGE_QUERIES[language][rule_id] == <the exact pinned string>   # for all 6

    # guarded-import pin: stdlib ast parse of the module source — NO top-level
    # `import tree_sitter*` and NO top-level `from tree_sitter... import ...`;
    # the tree_sitter import must live inside a function/method body.

OPTIONAL-DEPENDENCY PATTERN REFERENCE (read-only): ngv2/z3_bridge.py never imports `z3` at module level and stays importable without the heavy dependency — mirror that posture for `tree_sitter` via the in-body guarded import described in Scope point 3.

# Deliverables

NEW file ngv2/treesitter_verifier.py (whole-file, single-file) containing: a module docstring; the module-level `LANGUAGE_QUERIES` dict carrying the six pinned S-expression query strings byte-for-byte for languages c / java / javascript and rules process_exec / return_constant_stub; and the `TreeSitterVerifier` class whose `verify(code: str, language: str) -> ASTResult` (a) delegates `language == 'python'` to `ngv2.ast_verifier.ASTVerifier().verify(code)`, (b) otherwise evaluates the language's query DATA via in-body guarded `tree_sitter` imports using the 0.25 `Query` / `QueryCursor` constructor API with `matches()` (one `Violation` per match, line from the `@viol` capture's `start_point[0] + 1`, severity ERROR for process_exec / WARNING for return_constant_stub, `valid` = no-ERROR-present), reusing the imported `Violation` / `ASTResult` / severity literals from `ngv2.ast_verifier`, with no module-level tree_sitter import, no manual tree walks, no edits to any existing file, and no nondeterminism. Verified GREEN by `python -m pytest tests/ngv2/test_treesitter_verifier_wired.py -q` (the committed oracle, NGv2 commit 167d391).
