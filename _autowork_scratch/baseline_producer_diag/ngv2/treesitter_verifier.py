"""Multi-language tree-sitter policy verifier (C / Java / JavaScript).

A sibling of :mod:`ngv2.ast_verifier` whose detection rules live as DATA: the
module-level :data:`LANGUAGE_QUERIES` table maps each supported language to a
``{rule_id -> S-expression query string}`` mapping that is evaluated against a
parsed source tree via the tree-sitter 0.25 ``Query`` / ``QueryCursor``
constructor API (the semgrep / ast-grep "rules-as-data" architecture). Each
query match yields exactly one :class:`~ngv2.ast_verifier.Violation`.

``TreeSitterVerifier.verify`` delegates ``language == 'python'`` to the stdlib
:class:`~ngv2.ast_verifier.ASTVerifier` as a differential anchor, so the two
verifiers agree on Python source. Following the optional-dependency posture of
``ngv2/z3_bridge.py``, ``tree_sitter`` is imported lazily inside the method
body behind a ``try/except ImportError`` guard rather than at module scope; the
module stays importable even when the grammar wheels are absent.
"""
import importlib
from ngv2.ast_verifier import ASTResult, ASTVerifier, SEVERITY_ERROR, SEVERITY_WARNING, Violation
LANGUAGE_QUERIES = {'c': {'process_exec': '(call_expression function: (identifier) @viol (#match? @viol "^(system|popen|execl|execle|execlp|execv|execve|execvp|execvpe)$"))', 'return_constant_stub': '(function_definition body: (compound_statement . (return_statement [(number_literal) (string_literal) (true) (false)]) .)) @viol'}, 'java': {'process_exec': '(method_invocation object: (method_invocation object: (identifier) @cls name: (identifier) @factory) name: (identifier) @method (#eq? @cls "Runtime") (#eq? @factory "getRuntime") (#eq? @method "exec")) @viol', 'return_constant_stub': '(method_declaration body: (block . (return_statement [(string_literal) (decimal_integer_literal) (true) (false)]) .)) @viol'}, 'javascript': {'process_exec': '(call_expression function: (member_expression property: (property_identifier) @method) (#any-of? @method "exec" "execSync")) @viol', 'return_constant_stub': '(function_declaration body: (statement_block . (return_statement [(string) (number) (true) (false)]) .)) @viol'}}
_RULE_SEVERITY = {'process_exec': SEVERITY_ERROR, 'return_constant_stub': SEVERITY_WARNING}
_RULE_MESSAGE = {'process_exec': 'process execution sink invoked', 'return_constant_stub': 'function body is a single return of a constant (stub)'}

class TreeSitterVerifier:
    """Policy verifier that evaluates :data:`LANGUAGE_QUERIES` over source.

    Detection is performed purely by running the pinned tree-sitter queries; no
    manual tree walking is involved. ``verify`` is a deterministic function of
    its ``(code, language)`` arguments with no I/O, clock, or randomness.
    """

    def verify(self, code: str, language: str) -> ASTResult:
        """Verify ``code`` written in ``language`` against the policy rules."""
        if language == 'python':
            return ASTVerifier().verify(code)
        try:
            from tree_sitter import Language, Parser, Query, QueryCursor
        except ImportError:
            return ASTResult(valid=False, violations=[Violation(rule='tree_sitter_unavailable', line=0, message='tree_sitter is not installed', severity=SEVERITY_ERROR)])
        grammar_module = importlib.import_module('tree_sitter_' + language)
        lang = Language(grammar_module.language())
        tree = Parser(lang).parse(code.encode('utf-8'))
        violations = []
        for rule_id, query_str in LANGUAGE_QUERIES[language].items():
            severity = _RULE_SEVERITY[rule_id]
            message = _RULE_MESSAGE[rule_id]
            cursor = QueryCursor(Query(lang, query_str))
            for _pattern_index, captures in cursor.matches(tree.root_node):
                node = captures['viol'][0]
                violations.append(Violation(rule=rule_id, line=node.start_point[0] + 1, message=message, severity=severity))
        violations.sort(key=lambda v: (v.line, v.rule))
        valid = not any((v.severity == SEVERITY_ERROR for v in violations))
        return ASTResult(valid=valid, violations=violations)