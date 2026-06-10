# Addendum: Semantic Loop Invariants & Assertions in JanusMaskJR

This addendum outlines the feasibility, architecture, and concrete implementation details for integrating **Semantic Loop Invariants & Assertions** into the [JanusMaskJR](file:///home/xnihil0zer0/JanusMaskJR) harness optimization pipeline.

---

## 1. Adversarial Critique of the Optimization Method

While injecting loop invariants as dynamic check assertions can catch incorrect state transitions early and prevent infinite loop divergence, it introduces substantial adversarial risks to code quality, developer maintainability, and synthesis flexibility.

### A. Code Quality Degradation and Runtime Overhead
*   **Boilerplate Clutter:** Production source files are often degraded by verbose, multi-line logic-check assertions. These checks obscure the core business logic, reducing readability for human reviewers.
*   **Algorithmic Complexity Shifting:** Python evaluates `assert` statements at runtime unless optimization (`-O`) flags are set. If an invariant checks a non-trivial property (such as asserting a list is sorted, requiring $O(N)$ operations), running it inside an $O(N)$ loop increases the overall runtime complexity to $O(N^2)$. This overhead can trigger execution timeouts in time-bounded fuzzing or unit-testing environments.

### B. Barriers to Refactoring and Optimization
*   **Construct Deletion:** Refactoring loops into list comprehensions, generator expressions, or functional constructs (such as `map` or `filter`) eliminates the loop nodes (`ast.For` or `ast.While`) entirely. If assertions are bound to loop nodes, the refactored code will fail verification.
*   **Name Mapping Fragility:** Assertions are tightly bound to specific variable names. If an LLM generator renames local variables during an optimization or cleaning step, the injected assertions will fail with `NameError` or cause spurious validation failures.
*   **Recursion Conversion:** Converting a loop into recursive calls to eliminate iteration removes the loop constructs, causing AST enforcers expecting a physical loop to reject the code.

### C. Prevention of Deletion (Deletion of Asserts)
*   **The Deletion Incentive:** Generator agents naturally delete assertions that fail or introduce performance penalties in order to make their submissions pass external tests.
*   **AST-Level Enforcement:** To prevent this, [ast_enforcer.py](file:///home/xnihil0zer0/JanusMaskJR/harness/ast_enforcer.py) must verify the structural presence of the required assertions using static analysis.
*   **Structural Normalization:** Invariants must be normalized to strip whitespace, formatting variations, and comment changes, ensuring the agent cannot easily bypass them by altering the expression string without changing the semantic logic.

---

## 2. Research on Implementation Details

The loop invariant lifecycle involves three main phases: planner extraction, synthesizer injection, and AST-level verification.

### A. Planner Extraction
The planning brief defines loop invariants inside the frontmatter block. The [brief_loader.py](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/brief_loader.py) module parses this metadata.
*   **Frontmatter Schema:**
    ```yaml
    loop_invariants:
      - function: "calculate_hash_digest"
        loop_index: 0
        expression: "isinstance(digest, bytes) and len(digest) == i"
        message: "Digest length must match loop counter"
    ```
*   **Data Representation:** Loaded into the [PlanningBrief](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/brief_loader.py#L27) dataclass as a tuple of dictionaries containing the parsed elements.

### B. Synthesizer Injection (Assertion Compiler)
Two paths exist for injecting assertions:
1.  **Prompt-Driven Injection:** Appending the assertions to the synthesis prompt, instructing the model to write them manually. This is prone to syntax errors and variable name mismatches.
2.  **Automated AST Injection:** Utilizing an automated `AssertionCompiler` (an `ast.NodeTransformer`) as a post-generation step. This tool parses the draft code, locates the target loop, and inserts the `ast.Assert` node programmatically.

### C. AST Enforcer Validation
The validation is executed by [validate_code](file:///home/xnihil0zer0/JanusMaskJR/harness/ast_enforcer.py#L187) within [ast_enforcer.py](file:///home/xnihil0zer0/JanusMaskJR/harness/ast_enforcer.py).
*   **AST Walker:** A `LoopInvariantEnforcer` visitor locates the target function and retrieves the loop at the specified `loop_index`.
*   **AST Expression Comparison:** It parses the expected invariant string into a comparison AST, normalizes it, and asserts its presence at the top of the target loop body.
*   **Violation Logging:** If the assertion is missing or structurally altered, the enforcer logs a `missing_loop_invariant` violation.

---

## 3. Concrete Implementation Plan

### A. Modify [brief_loader.py](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/brief_loader.py)
*   Extend [PlanningBrief](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/brief_loader.py#L27) to include `loop_invariants: tuple[dict, ...] = ()`.
*   Modify [_coerce_optional_brief_fields](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/brief_loader.py#L126) to parse `loop_invariants` list entries, validating that each entry contains `function`, `loop_index`, and `expression`.

### B. Modify [orchestrator.py](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py)
*   In [_validate_submission](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py#L1586), extract invariants from the task context:
    ```python
    expected_invariants = task.get('loop_invariants', None)
    ```
*   Pass `expected_invariants` to [validate_code](file:///home/xnihil0zer0/JanusMaskJR/harness/ast_enforcer.py#L187).

### C. Modify [ast_enforcer.py](file:///home/xnihil0zer0/JanusMaskJR/harness/ast_enforcer.py)
*   Add `expected_invariants: list[dict] | None = None` to [validate_code](file:///home/xnihil0zer0/JanusMaskJR/harness/ast_enforcer.py#L187).
*   Run the `LoopInvariantEnforcer` visitor inside [validate_code](file:///home/xnihil0zer0/JanusMaskJR/harness/ast_enforcer.py#L187) when expected invariants are provided.

---

## 4. Code Outlines

### A. The Assertion Compiler
This component runs post-synthesis to inject assertions programmatically, shielding the generator LLM from syntax formatting errors.

```python
import ast

class AssertionCompiler(ast.NodeTransformer):
    """
    AST Transformer to inject assert statements into designated loops.
    """
    def __init__(self, function_name: str, loop_index: int, invariant_expr: str, message: str | None = None):
        self.function_name = function_name
        self.loop_index = loop_index
        self.invariant_expr = invariant_expr
        self.message = message
        self.current_loop_count = 0
        self.in_target_function = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        if node.name == self.function_name:
            self.in_target_function = True
            self.current_loop_count = 0
            self.generic_visit(node)
            self.in_target_function = False
        else:
            self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        if node.name == self.function_name:
            self.in_target_function = True
            self.current_loop_count = 0
            self.generic_visit(node)
            self.in_target_function = False
        else:
            self.generic_visit(node)
        return node

    def _inject_assert(self, node: ast.AST) -> ast.AST:
        if self.in_target_function:
            if self.current_loop_count == self.loop_index:
                # Parse expression to expression AST node
                expr_ast = ast.parse(self.invariant_expr, mode='eval').body
                # Construct assertion statement
                assert_stmt = ast.Assert(
                    test=expr_ast,
                    msg=ast.Constant(value=self.message) if self.message else None
                )
                # Inject at the very beginning of the loop body
                node.body.insert(0, assert_stmt)
            self.current_loop_count += 1
        return node

    def visit_For(self, node: ast.For) -> ast.For:
        node = self._inject_assert(node)
        self.generic_visit(node)
        return node

    def visit_While(self, node: ast.While) -> ast.While:
        node = self._inject_assert(node)
        self.generic_visit(node)
        return node
```

### B. The AST Loop Invariant Checker
This validator is integrated into [validate_code](file:///home/xnihil0zer0/JanusMaskJR/harness/ast_enforcer.py#L187) to ensure the submission contains the matching loop invariants.

```python
import ast
from harness.ast_enforcer import Violation

class LoopInvariantEnforcer(ast.NodeVisitor):
    """
    AST Visitor to verify the presence and equivalence of expected loop invariants.
    """
    def __init__(self, function_name: str, loop_index: int, expected_expr: str):
        self.function_name = function_name
        self.loop_index = loop_index
        self.expected_expr = expected_expr
        self.current_loop_count = 0
        self.in_target_function = False
        self.found = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name == self.function_name:
            self.in_target_function = True
            self.current_loop_count = 0
            self.generic_visit(node)
            self.in_target_function = False
        else:
            self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node.name == self.function_name:
            self.in_target_function = True
            self.current_loop_count = 0
            self.generic_visit(node)
            self.in_target_function = False
        else:
            self.generic_visit(node)

    def _check_assert(self, node: ast.AST) -> None:
        if self.in_target_function:
            if self.current_loop_count == self.loop_index:
                # Scan statements for asserts matching the expected invariant
                for stmt in node.body:
                    if isinstance(stmt, ast.Assert):
                        # Canonical comparison of unparsed expressions
                        actual_unparsed = ast.unparse(stmt.test)
                        expected_unparsed = ast.unparse(ast.parse(self.expected_expr, mode='eval').body)
                        # Remove whitespaces for canonical match
                        if "".join(actual_unparsed.split()) == "".join(expected_unparsed.split()):
                            self.found = True
                            break
            self.current_loop_count += 1

    def visit_For(self, node: ast.For) -> None:
        self._check_assert(node)
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self._check_assert(node)
        self.generic_visit(node)
```
