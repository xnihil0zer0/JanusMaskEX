"""AST Verifier — Symbolic validation of Python code using stdlib ast module.

Validates code syntactically and semantically before execution or commit.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import List

# Regular expression patterns for scanning credentials
CREDENTIAL_PATTERNS = [
    re.compile(r'sk-[a-zA-Z0-9]{32,}'),
    re.compile(r'(?:api_key|client_secret|private_key|github_token|aws_access)[a-zA-Z0-9_\-\/\=\+]*', re.IGNORECASE),
    re.compile(r'(?:token|password|secret)\s*=\s*[\'"][a-zA-Z0-9_\-\/\=\+]{10,}[\'"]', re.IGNORECASE)
]

DANGEROUS_SHELL_KEYWORDS = [
    "rm -rf", "sudo ", "chmod ", "chown ", "curl ", "wget ", "mkfifo", "ncat ", "nc -", "/dev/tcp"
]


@dataclass
class Violation:
    rule: str
    line: int
    message: str
    severity: str  # 'ERROR' or 'WARNING'

    def __str__(self) -> str:
        return f"[{self.severity}] line {self.line} ({self.rule}): {self.message}"


@dataclass
class ASTResult:
    valid: bool
    violations: List[Violation] = field(default_factory=list)

    def has_errors(self) -> bool:
        return any(v.severity == "ERROR" for v in self.violations)

    def has_warnings(self) -> bool:
        return any(v.severity == "WARNING" for v in self.violations)

    def summary(self) -> str:
        if not self.violations:
            return "OK (no violations)"
        errors = sum(1 for v in self.violations if v.severity == "ERROR")
        warnings = sum(1 for v in self.violations if v.severity == "WARNING")
        return f"{errors} error(s), {warnings} warning(s)"


class _ASTVisitor(ast.NodeVisitor):
    def __init__(self, code: str):
        self.code = code
        self.violations: List[Violation] = []
        self.has_seed = False
        self.random_calls: List[ast.Call] = []
        self.current_function: str | None = None

    def visit_Call(self, node: ast.Call):
        func = node.func
        
        # 1. Check for random.seed()
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "seed"
            and isinstance(func.value, ast.Name)
            and func.value.id in ("random", "np", "numpy")
        ):
            self.has_seed = True
        elif isinstance(func, ast.Name) and func.id == "seed":
            self.has_seed = True

        # 2. Collect random calls
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "random"
        ):
            self.random_calls.append(node)

        # 3. Detect non-determinism (time.time, time.time_ns, uuid.uuid4)
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            module_name = func.value.id
            method_name = func.attr
            if module_name == "time" and method_name in ("time", "time_ns", "sleep"):
                self.violations.append(Violation(
                    rule="non_determinism",
                    line=node.lineno,
                    message=f"Non-deterministic call detected: {module_name}.{method_name}()",
                    severity="WARNING"
                ))
            elif module_name == "uuid" and method_name == "uuid4":
                self.violations.append(Violation(
                    rule="non_determinism",
                    line=node.lineno,
                    message="Non-deterministic UUID generation: uuid.uuid4()",
                    severity="WARNING"
                ))

        # 4. Recursion Depth check
        if self.current_function and isinstance(func, ast.Name) and func.id == self.current_function:
            self.violations.append(Violation(
                rule="recursion",
                line=node.lineno,
                message=f"Recursive call to '{self.current_function}' detected.",
                severity="WARNING"
            ))

        # 5. subprocess check
        if isinstance(func, ast.Attribute) and func.attr in ("run", "call", "check_call", "check_output"):
            if isinstance(func.value, ast.Name) and func.value.id == "subprocess":
                if func.attr in ("run", "call"):
                    # Check for check=True
                    has_check = any(
                        isinstance(kw, ast.keyword) and kw.arg == "check" and getattr(kw.value, "value", None) is True
                        for kw in node.keywords
                    )
                    if not has_check:
                        self.violations.append(Violation(
                            rule="subprocess_no_check",
                            line=node.lineno,
                            message=f"subprocess.{func.attr}() called without check=True.",
                            severity="ERROR"
                        ))

        # 6. os.system check
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "system"
            and isinstance(func.value, ast.Name)
            and func.value.id == "os"
        ):
            self.violations.append(Violation(
                rule="os_system",
                line=node.lineno,
                message="os.system() detected. Use subprocess.run() with explicit args instead.",
                severity="ERROR"
            ))

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        old_func = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = old_func

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        old_func = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = old_func

    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        # Bare except: except:
        if node.type is None:
            self.violations.append(Violation(
                rule="bare_except",
                line=node.lineno,
                message="Bare `except:` catches all exceptions including system signals. Use specific exceptions.",
                severity="ERROR"
            ))
        else:
            # Check except Exception/BaseException with pass
            type_name = ""
            if isinstance(node.type, ast.Name):
                type_name = node.type.id
            elif isinstance(node.type, ast.Attribute):
                type_name = node.type.attr
            
            if type_name in ("Exception", "BaseException"):
                is_empty = all(
                    isinstance(stmt, (ast.Pass, ast.Expr)) and (
                        isinstance(stmt, ast.Pass) or
                        (isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str))
                    )
                    for stmt in node.body
                )
                if is_empty:
                    self.violations.append(Violation(
                        rule="except_exception_pass",
                        line=node.lineno,
                        message=f"'except {type_name}: pass' silently swallows exceptions. Add logging/handling.",
                        severity="ERROR"
                    ))

        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, str):
            val = node.value
            lineno = node.lineno
            # Check for credentials in strings
            for pattern in CREDENTIAL_PATTERNS:
                if pattern.search(val):
                    self.violations.append(Violation(
                        rule="credential_leak",
                        line=lineno,
                        message="Potential credential/API key pattern in string literal.",
                        severity="ERROR"
                    ))
                    break

            # Check for dangerous shell keywords
            for kw in DANGEROUS_SHELL_KEYWORDS:
                if kw in val:
                    self.violations.append(Violation(
                        rule="dangerous_shell",
                        line=lineno,
                        message=f"Dangerous shell keyword '{kw}' found in string literal.",
                        severity="WARNING"
                    ))

        self.generic_visit(node)


class ASTVerifier:
    """Verifies Python code against security, quality, and semantic rules using AST."""

    def verify(self, code: str, filename: str = "<string>") -> ASTResult:
        violations: List[Violation] = []

        # Rule 1: Syntax validity
        try:
            tree = ast.parse(code, filename=filename)
        except SyntaxError as e:
            violations.append(Violation(
                rule="syntax",
                line=e.lineno or 0,
                message=f"SyntaxError: {e.msg}",
                severity="ERROR"
            ))
            return ASTResult(valid=False, violations=violations)

        visitor = _ASTVisitor(code)
        visitor.visit(tree)
        violations.extend(visitor.violations)

        # Post-pass: Non-determinism random check (if random was called but no seed set)
        if visitor.random_calls and not visitor.has_seed:
            for call in visitor.random_calls:
                violations.append(Violation(
                    rule="unseeded_random",
                    line=call.lineno,
                    message="Use of random module without setting seed first. This is non-deterministic.",
                    severity="WARNING"
                ))

        # Check devnull comments in the raw source string
        violations.extend(self._check_devnull_without_comment(code))

        has_errors = any(v.severity == "ERROR" for v in violations)
        return ASTResult(valid=not has_errors, violations=violations)

    def verify_file(self, path: str) -> ASTResult:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                code = f.read()
        except OSError as e:
            return ASTResult(
                valid=False,
                violations=[Violation(
                    rule="file_read",
                    line=0,
                    message=f"Cannot read file: {e}",
                    severity="ERROR"
                )]
            )
        return self.verify(code, filename=path)

    def _check_devnull_without_comment(self, code: str) -> List[Violation]:
        violations = []
        lines = code.splitlines()
        for lineno, line in enumerate(lines, start=1):
            if "2>/dev/null" not in line:
                continue
            
            if "#" in line:
                continue
            
            prev_line = lines[lineno - 2] if lineno > 1 else ""
            next_line = lines[lineno] if lineno < len(lines) else ""
            if "#" in prev_line or "#" in next_line:
                continue

            violations.append(Violation(
                rule="devnull_no_comment",
                line=lineno,
                message="'2>/dev/null' suppresses stderr without documentation. Add a comment explaining why.",
                severity="WARNING"
            ))
        return violations
