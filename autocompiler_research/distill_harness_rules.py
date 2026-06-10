import ast
import inspect
from pathlib import Path

def analyze_ast_difference(rich_code: str, ablated_code: str) -> dict:
    """Compares the AST structures of a rich metadata execution and an ablated one.
    
    Detects if the ablated code is a 'vacuous stub' (e.g. returning a constant)
    while the rich metadata version had functional logic.
    """
    rich_tree = ast.parse(rich_code)
    ablated_tree = ast.parse(ablated_code)
    
    rich_funcs = {node.name: node for node in ast.walk(rich_tree) if isinstance(node, ast.FunctionDef)}
    ablated_funcs = {node.name: node for node in ast.walk(ablated_tree) if isinstance(node, ast.FunctionDef)}
    
    lost_heuristics = {}
    
    for name, ablated_node in ablated_funcs.items():
        if name not in rich_funcs:
            continue
        rich_node = rich_funcs[name]
        
        # Check if ablated version is a simple return statement or exception raise
        is_ablated_stub = False
        stub_type = None
        
        body = ablated_node.body
        # Skip docstrings
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            body = body[1:]
            
        if len(body) == 1:
            stmt = body[0]
            if isinstance(stmt, ast.Return):
                if isinstance(stmt.value, ast.Constant):
                    is_ablated_stub = True
                    stub_type = f"ConstantReturn({stmt.value.value})"
            elif isinstance(stmt, ast.Raise):
                if isinstance(stmt.exc, (ast.Name, ast.Call)):
                    exc_name = stmt.exc.id if isinstance(stmt.exc, ast.Name) else (stmt.exc.func.id if isinstance(stmt.exc.func, ast.Name) else None)
                    if exc_name == 'NotImplementedError':
                        is_ablated_stub = True
                        stub_type = "NotImplementedErrorStub"
                        
        if is_ablated_stub:
            # Verify if rich version had more complexity
            rich_body_len = len(rich_node.body)
            if rich_body_len > 1 or (rich_body_len == 1 and not isinstance(rich_node.body[0], (ast.Return, ast.Raise))):
                lost_heuristics[name] = {
                    'lost_complexity': True,
                    'stub_type': stub_type,
                    'rich_statement_count': len(rich_node.body),
                    'signature': {
                        'args': [arg.arg for arg in ablated_node.args.args],
                        'returns': ast.unparse(ablated_node.returns) if ablated_node.returns else None
                    }
                }
                
    return lost_heuristics

def synthesize_ast_checker(function_name: str, heuristic_info: dict) -> str:
    """Generates Python code for a custom AST visitor that blocks this specific stub behavior."""
    return f'''# Auto-generated AST Checker for Harness Distillation
# Target: {function_name} ({heuristic_info["stub_type"]})

import ast

class Synthesized_{function_name}_Validator(ast.NodeVisitor):
    def __init__(self):
        self.violations = []

    def visit_FunctionDef(self, node):
        if node.name == "{function_name}":
            # Rule: Ensure it is not a stub returning a constant or raising NotImplementedError
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body = body[1:] # skip docstring
            if len(body) == 1:
                stmt = body[0]
                if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Constant):
                    self.violations.append(
                        f"Validation Error: '{function_name}' returning constant {{stmt.value.value}} was auto-banned."
                    )
                elif isinstance(stmt, ast.Raise):
                    exc_id = None
                    if isinstance(stmt.exc, ast.Name):
                        exc_id = stmt.exc.id
                    elif isinstance(stmt.exc, ast.Call) and isinstance(stmt.exc.func, ast.Name):
                        exc_id = stmt.exc.func.id
                    if exc_id == "NotImplementedError":
                        self.violations.append(
                            f"Validation Error: '{function_name}' has a NotImplementedError stub which is auto-banned."
                        )
        self.generic_visit(node)
'''

# --- Working Demonstration ---
if __name__ == '__main__':
    print("=== HARNESS DISTILLATION WORKING DEMONSTRATION ===")
    
    # Simulate an agent's code written with full metadata
    # The agent understood the complexity requirements and implemented proper calculation
    rich_metadata_impl = """
def calculate_hash_digest(payload: str) -> str:
    \"\"\"Calculates SHA-256 hash representation of string input.\"\"\"
    import hashlib
    if not payload:
        return ""
    hasher = hashlib.sha256()
    hasher.update(payload.encode('utf-8'))
    return hasher.hexdigest()
"""

    # Simulate an agent's code written with ablated metadata (briefs, constraints removed)
    # The agent bypassed implementation by returning a static stub to pass type checkers
    ablated_metadata_impl = """
def calculate_hash_digest(payload: str) -> str:
    \"\"\"Calculates SHA-256 hash representation of string input.\"\"\"
    return "static_mock_hash_val_for_tests"
"""

    print("Analyzing trace implementation differences...")
    gaps = analyze_ast_difference(rich_metadata_impl, ablated_metadata_impl)
    
    for func_name, info in gaps.items():
        print(f"\\n[!] Lost Heuristic Detected in function: {func_name}")
        print(f"    Reason: Omitted complexity. Ablated run used: {info['stub_type']}")
        print(f"    Rich run had {info['rich_statement_count']} statements.")
        
        print("\\nSynthesizing deterministic static checker...")
        checker_code = synthesize_ast_checker(func_name, info)
        print("-" * 50)
        print(checker_code)
        print("-" * 50)
        
        # Save compiled checker to autocompiler_research
        target_path = Path(__file__).parent / f"synthesized_{func_name}_checker.py"
        target_path.write_text(checker_code)
        print(f"Saved synthesized verification gate to: {target_path}")
