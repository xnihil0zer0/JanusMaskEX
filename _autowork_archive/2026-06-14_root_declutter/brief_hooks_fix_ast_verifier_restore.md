---
epic: false
working_dir: "/home/xnihil0zer0/NobleGreedv2"
interfaces: "pure stdlib-ast policy verifier; restores ASTVerifier (f67c091) + keeps PocMarkerStubChecker dispatch"
---

# Title

Restore the gutted ASTVerifier in NobleGreedv2 ngv2/ast_verifier.py (regression from e55ac66) while keeping the PocMarkerStubChecker marker check wired

Commit `e55ac66` ("A5_ast_verifier_marker") was supposed to ADDITIVELY add `PocMarkerStubChecker` to
`ngv2/ast_verifier.py` but instead REPLACED the original `ASTVerifier` (from `f67c091`,
"ast-verifier-impl") with a gutted reflection-based version: `ASTResult.valid` is now always `None`,
the syntax-error / `os_system` / `subprocess_no_check` / `devnull_no_comment` checks are GONE
(empirically `os.system("rm -rf /")` returns ZERO violations), and `verify_file()` was removed. The
pre-existing committed oracle `tests/test_ast_verifier.py` is RED 8/11 on HEAD. This is a CRITICAL
security regression: the verifier is the policy gate over generated code.

# Scope

- `ngv2/ast_verifier.py` (EDIT, partial_edit, ONE file): replace ONLY the `ASTVerifier` class with the
  verbatim original f67c091 implementation PLUS the marker-check dispatch wired into its walk. The
  restored class is: original f67c091 `ASTVerifier` (embedded VERBATIM below) + a `__init__` holding a
  `PocMarkerStubChecker` instance + a `_check_poc_marker` dispatch in the `verify()` walk loop that
  appends a `Violation(rule='poc_success_marker', ..., severity=SEVERITY_WARNING)` when
  `PocMarkerStubChecker.marker_for_return(node)` returns a marker. Net dual contract: BOTH committed
  oracles pass together — `tests/test_ast_verifier.py` (strong original contract, currently RED) AND
  `tests/ngv2/test_ast_verifier_marker_wired.py` (marker contract, currently GREEN and must stay GREEN).

# Non-Goals

The word integration appears here deliberately. DO NOT touch any other file. DO NOT alter `Violation`,
`ASTResult`, `SEVERITY_ERROR`, `SEVERITY_WARNING`, `_DEVNULL_TOKEN`, or `PocMarkerStubChecker` — they
are correct as committed on HEAD and both oracles import them. DO NOT keep ANY of the gutted version's
reflection machinery (`_make_violation`, `_build_result`, `inspect`-based construction): it is the
regression. DO NOT emit whole-file. No new modules, no test edits, no integration glue elsewhere, no
network/subprocess/clock/randomness — the module is pure stdlib `ast` and fully deterministic.

# Inputs

- CURRENT `ngv2/ast_verifier.py` on HEAD (staged read-only at `{WORK_DIR}/inbox/targets/ngv2/ast_verifier.py`):
  keep its module docstring, imports, `SEVERITY_*`, `_DEVNULL_TOKEN`, `Violation`, `ASTResult`, and
  `PocMarkerStubChecker` byte-for-byte unchanged. Only the `ASTVerifier` symbol is replaced.
- `PocMarkerStubChecker` API (already on HEAD, consume as-is): `SUCCESS_MARKERS = frozenset({'VULNERABLE',
  'CONFIRMED', 'SUCCESS'})`, `rule = 'poc_success_marker'`, and
  `marker_for_return(node) -> Optional[str]` which returns the marker string iff `node` is an
  `ast.Return` of a literal marker-string `ast.Constant`, else `None`.
- The committed oracles (DO NOT modify): `tests/test_ast_verifier.py` pins the dataclass shapes, rule
  names (`syntax`, `bare_except`, `os_system`, `subprocess_no_check`, `devnull_no_comment`, `file_read`),
  severity literals, `valid = not has_errors()` semantics, `summary()` format, and `verify_file()`
  delegation. `tests/ngv2/test_ast_verifier_marker_wired.py` pins the marker behavior (rule contains
  "marker", flags `def poc(): return "VULNERABLE"`, zero false positives on ngv2/ast_constraint.py,
  ngv2/contracts.py, ngv2/state_machine.py, ngv2/debate_router.py).
- VERBATIM ORIGINAL `ASTVerifier` from f67c091 — reproduce this FAITHFULLY (it is the reproduction
  surface; copy it, then add ONLY the marker wiring described in Deliverables):

```python
class ASTVerifier:
    """Walks a parsed ``ast`` tree and evaluates a fixed set of policy rules."""

    def verify(self, source: str) -> ASTResult:
        """Parse ``source`` and return an :class:`ASTResult` of findings."""
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            line = exc.lineno if exc.lineno and exc.lineno >= 1 else 1
            detail = exc.msg if exc.msg else str(exc)
            return ASTResult(valid=False, violations=[Violation(rule='syntax', line=line, message=f'SyntaxError: {detail}', severity=SEVERITY_ERROR)])
        source_lines = source.splitlines()
        handles_returncode = any((isinstance(node, ast.Attribute) and node.attr == 'returncode' for node in ast.walk(tree)))
        violations: List[Violation] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                violations.append(Violation(rule='bare_except', line=node.lineno, message='Bare except: catches everything and hides errors', severity=SEVERITY_ERROR))
            elif isinstance(node, ast.Call):
                self._check_call(node, violations, handles_returncode)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                self._check_string(node, source_lines, violations)
        valid = not any((v.severity == SEVERITY_ERROR for v in violations))
        return ASTResult(valid=valid, violations=violations)

    def verify_file(self, path: str) -> ASTResult:
        """Read ``path`` and delegate to :meth:`verify`."""
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                source = fh.read()
        except OSError as exc:
            return ASTResult(valid=False, violations=[Violation(rule='file_read', line=0, message=f'Cannot read file {path}: {exc}', severity=SEVERITY_ERROR)])
        return self.verify(source)

    def _check_call(self, node: ast.Call, violations: List[Violation], handles_returncode: bool) -> None:
        func = node.func
        if not isinstance(func, ast.Attribute):
            return
        value = func.value
        base = value.id if isinstance(value, ast.Name) else None
        if base == 'os' and func.attr == 'system':
            violations.append(Violation(rule='os_system', line=node.lineno, message='os.system() call: use subprocess with check instead', severity=SEVERITY_ERROR))
        elif base == 'subprocess' and func.attr == 'run':
            has_check = any((kw.arg == 'check' and self._is_truthy(kw.value) for kw in node.keywords))
            if not has_check and (not handles_returncode):
                violations.append(Violation(rule='subprocess_no_check', line=node.lineno, message='subprocess.run() without check=True or returncode handling', severity=SEVERITY_ERROR))

    def _check_string(self, node: ast.Constant, source_lines: List[str], violations: List[Violation]) -> None:
        if _DEVNULL_TOKEN not in node.value:
            return
        if self._line_has_comment(node, source_lines):
            return
        violations.append(Violation(rule='devnull_no_comment', line=node.lineno, message='Redirection to /dev/null without an explanatory comment', severity=SEVERITY_WARNING))

    @staticmethod
    def _is_truthy(node: ast.AST) -> bool:
        return isinstance(node, ast.Constant) and bool(node.value)

    @staticmethod
    def _line_has_comment(node: ast.Constant, source_lines: List[str]) -> bool:
        start = node.lineno
        end = getattr(node, 'end_lineno', None) or start
        for lineno in range(start, end + 1):
            idx = lineno - 1
            if 0 <= idx < len(source_lines) and '#' in source_lines[idx]:
                return True
        return False
```

# Deliverables

1. `ngv2/ast_verifier.py` with `ASTVerifier` restored as the embedded f67c091 class above, modified
   ONLY as follows (the marker wiring, mirroring how the other checks append `Violation`s):
   - add `def __init__(self): self._poc_marker_checker = PocMarkerStubChecker()` (with this exact
     attribute name);
   - add one private dispatch method:
     ```python
     def _check_poc_marker(self, node: ast.AST, violations: List[Violation]) -> None:
         marker = self._poc_marker_checker.marker_for_return(node)
         if marker is not None:
             violations.append(Violation(rule='poc_success_marker', line=node.lineno, message=f'function returns hardcoded success marker {marker!r} (suspected PoC stub)', severity=SEVERITY_WARNING))
     ```
   - in the `verify()` walk loop, add the dispatch as an additional branch so `ast.Return` nodes are
     checked: `elif isinstance(node, ast.Return): self._check_poc_marker(node, violations)` (placed
     after the existing branches; the existing branches and their order are otherwise UNCHANGED).
   Everything else in the embedded class is reproduced byte-for-byte: `valid` MUST be computed as
   `not any ERROR` (never `None`), `verify_file()` MUST exist with the `file_read` error path, the
   syntax short-circuit returns `valid=False` with the single `syntax` ERROR violation. The marker
   finding is SEVERITY_WARNING so it never flips `valid` (the strong oracle's clean/devnull cases
   stay valid=True). Deterministic: no time, no random, no I/O beyond `verify_file`'s explicit read.

# Required plan shape

EXACTLY ONE leaf task. This is a single non-epic plan — the planner emits this task directly; do NOT
decompose into child briefs.

- LEAF `fix-ast-verifier-restore` (task_id pinned VERBATIM: `fix-ast-verifier-restore`) —
  meta_task_type `validation`, EDIT mode `partial_edit`,
  files_touched `["ngv2/ast_verifier.py"]` ONLY (no other file),
  verification_command: `pytest tests/test_ast_verifier.py tests/ngv2/test_ast_verifier_marker_wired.py`.
  - test_spec edge_cases (>=2, mirror EACH verbatim into regression_tests — the plan validator
    hard-drops any leaf without this):
    1. `os.system('rm -rf /')` source yields an `os_system` ERROR violation and `valid is False`
       (the regression's empirical zero-violation hole).
    2. `def poc(): return "VULNERABLE"` yields a `poc_success_marker` WARNING violation while
       `valid` stays True (marker check survives the restore).
    3. `ASTVerifier().verify('def (:')` returns `valid=False` with exactly one `syntax` ERROR whose
       message starts with `SyntaxError:` (valid is computed, never None).
    4. `verify_file('/nonexistent/path.py')` returns the single `file_read` ERROR at line 0
       (verify_file restored).
  - leaf non_goals MUST carry the literal word `integration` and forbid touching Violation/ASTResult/
    SEVERITY_*/PocMarkerStubChecker/tests.

PATCH FORMAT (MANDATORY — restorative edit that REPLACES exactly the existing `ASTVerifier` symbol):
emit a single `__JANUSMASK_PATCHES__` with EXACTLY ONE entry, kind `'symbol'`, name `'ASTVerifier'`,
whose `code` is the FULL restored class (the embedded f67c091 class + the three marker-wiring additions
from Deliverables, nothing else). The harness swaps the symbol in place and preserves every other byte
of the module — so the module docstring, imports, `SEVERITY_*`, `_DEVNULL_TOKEN`, `Violation`,
`ASTResult`, and `PocMarkerStubChecker` survive untouched. DO NOT emit whole-file; DO NOT emit a second
patch entry; DO NOT carry over `_make_violation`/`_build_result`/`import inspect` from the gutted HEAD
version. The worker must reproduce the embedded source faithfully — it is the contract, not a
suggestion.
