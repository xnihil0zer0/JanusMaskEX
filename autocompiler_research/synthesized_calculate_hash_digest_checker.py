# Auto-generated AST Checker for Harness Distillation
# Target: calculate_hash_digest (ConstantReturn(static_mock_hash_val_for_tests))

import ast

class Synthesized_calculate_hash_digest_Validator(ast.NodeVisitor):
    def __init__(self):
        self.violations = []

    def visit_FunctionDef(self, node):
        if node.name == "calculate_hash_digest":
            # Rule: Ensure it is not a stub returning a constant or raising NotImplementedError
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body = body[1:] # skip docstring
            if len(body) == 1:
                stmt = body[0]
                if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Constant):
                    self.violations.append(
                        f"Validation Error: 'calculate_hash_digest' returning constant {stmt.value.value} was auto-banned."
                    )
                elif isinstance(stmt, ast.Raise):
                    exc_id = None
                    if isinstance(stmt.exc, ast.Name):
                        exc_id = stmt.exc.id
                    elif isinstance(stmt.exc, ast.Call) and isinstance(stmt.exc.func, ast.Name):
                        exc_id = stmt.exc.func.id
                    if exc_id == "NotImplementedError":
                        self.violations.append(
                            f"Validation Error: 'calculate_hash_digest' has a NotImplementedError stub which is auto-banned."
                        )
        self.generic_visit(node)
