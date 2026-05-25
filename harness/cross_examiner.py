from __future__ import annotations

import ast
from harness.session_namer import generate_feedback_filename, feedback_glob_pattern
import json
import logging
import os
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness.ast_enforcer import normalize_ast, ast_to_canonical
from harness.diff_fuzzer import FuzzFailure

logger = logging.getLogger("janusmask.cross_examiner")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ExamPacket:
    """Everything an agent needs to perform a blind code review."""
    agent: str                  # "claude" or "gemini" -- the reviewer
    code_under_review: str      # Anonymized code (NOT the reviewer's own)
    task_specification: str
    fuzz_failures: list[dict]   # Serialized failure cases
    review_prompt: str          # The full prompt to send to the agent


@dataclass
class Critique:
    """Structured critique returned by an agent."""
    agent: str
    bugs: list[str]
    proposed_fixes: list[str]
    edge_cases: list[str]
    confidence: float           # 0-1
    revised_code: str | None = None


@dataclass
class CrossExamResult:
    """Result of the cross-examination phase."""
    claude_critique: Critique | None = None
    gemini_critique: Critique | None = None
    claude_revised_code: str | None = None
    gemini_revised_code: str | None = None


# ---------------------------------------------------------------------------
# Code anonymization
# ---------------------------------------------------------------------------

class _VariableAnonymizer(ast.NodeTransformer):
    """Replace all local variable names with generic var_0, var_1, etc.

    Preserves:
    - Function parameters (part of the spec)
    - Function/class names (part of the spec)
    - Module-level names
    - Imported names
    """

    def __init__(self) -> None:
        super().__init__()
        self._counter = 0
        self._rename_map: dict[str, str] = {}
        self._protected: set[str] = set()

    def _next_name(self) -> str:
        name = f"var_{self._counter}"
        self._counter += 1
        return name

    def visit_Module(self, node: ast.Module) -> ast.Module:
        self._collect_protected(node)
        self.generic_visit(node)
        return node

    def _collect_protected(self, module: ast.Module) -> None:
        """Collect names that must not be renamed."""
        for stmt in module.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._protected.add(stmt.name)
                self._collect_params(stmt)
            elif isinstance(stmt, ast.ClassDef):
                self._protected.add(stmt.name)
            elif isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    name = alias.asname or alias.name.split(".")[0]
                    self._protected.add(name)
            elif isinstance(stmt, ast.ImportFrom):
                for alias in stmt.names:
                    name = alias.asname or alias.name
                    self._protected.add(name)

    def _collect_params(self, func: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for arg in func.args.args + func.args.posonlyargs + func.args.kwonlyargs:
            self._protected.add(arg.arg)
        if func.args.vararg:
            self._protected.add(func.args.vararg.arg)
        if func.args.kwarg:
            self._protected.add(func.args.kwarg.arg)

    def visit_Name(self, node: ast.Name) -> ast.Name:
        if node.id in self._protected:
            return node
        if isinstance(node.ctx, ast.Store):
            if node.id not in self._rename_map:
                self._rename_map[node.id] = self._next_name()
        if node.id in self._rename_map:
            node.id = self._rename_map[node.id]
        return node


def anonymize_code(code: str) -> str:
    """Anonymize code to prevent agents from recognizing authorship.

    Steps:
    1. Parse to AST
    2. Strip comments and docstrings (handled by AST parsing)
    3. Rename local variables to var_0, var_1, ...
    4. Normalize imports
    5. Normalize whitespace via unparse
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # If code can't be parsed, return it with just comment stripping
        lines = []
        for line in code.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            lines.append(line)
        return "\n".join(lines)

    # Remove docstrings by using the normalization pipeline's docstring remover
    tree = normalize_ast(code)

    # Apply variable anonymization
    anonymizer = _VariableAnonymizer()
    tree = anonymizer.visit(tree)
    ast.fix_missing_locations(tree)

    return ast.unparse(tree)


# ---------------------------------------------------------------------------
# Failure serialization
# ---------------------------------------------------------------------------

def serialize_failure(failure: FuzzFailure) -> dict:
    """Convert a FuzzFailure to a JSON-serializable dict for inclusion in
    exam packets."""
    def _result_summary(result) -> dict:
        if result.timed_out:
            return {"status": "timeout"}
        if not result.success:
            return {
                "status": "exception",
                "exception_type": result.exception_type,
                "exception_message": result.exception_message,
            }
        return {
            "status": "success",
            "return_value": result.return_repr,
        }

    return {
        "input": {
            "args": _safe_repr(failure.input_args),
            "kwargs": _safe_repr(failure.input_kwargs),
        },
        "result_a": _result_summary(failure.result_a),
        "result_b": _result_summary(failure.result_b),
        "reason": failure.reason,
    }


def _safe_repr(obj: Any) -> str:
    """Safe repr that truncates long strings."""
    r = repr(obj)
    if len(r) > 500:
        return r[:497] + "..."
    return r


# ---------------------------------------------------------------------------
# Exam packet preparation
# ---------------------------------------------------------------------------

_REVIEW_PROMPT_TEMPLATE = textwrap.dedent("""\
    # Code Review Task

    You are reviewing code submitted for the following task:
    {task_specification}

    ## Code Under Review
    ```python
    {anonymized_code}
    ```

    ## Failing Test Cases
    The following inputs produced incorrect results:
    {failures_text}

    ## Your Task
    1. Identify the root cause of each failure
    2. Explain what the code does wrong
    3. Propose a specific fix
    4. Identify any additional edge cases the code may fail on
    5. Rate your confidence in the code's overall correctness (0-1)

    Respond by calling the janusmask execute tool with command 'submit_code' \
    containing your fixed version of the code. Include an 'explanation' field \
    describing what you changed and why.
""")


def prepare_exam_packets(
    code_a: str,
    code_b: str,
    task_spec: str,
    failures: list[FuzzFailure],
) -> tuple[ExamPacket, ExamPacket]:
    """Prepare examination packets for both agents.

    Claude reviews (anonymized) code_B + failures.
    Gemini reviews (anonymized) code_A + failures.

    Neither agent knows which code is theirs.
    """
    anon_a = anonymize_code(code_a)
    anon_b = anonymize_code(code_b)

    serialized_failures = [serialize_failure(f) for f in failures[:10]]  # cap at 10

    claude_failures_text = ""
    for i, f in enumerate(serialized_failures, 1):
        claude_failures_text += f"\n### Failure {i}\n"
        claude_failures_text += f"- Input: {f['input']['args']}\n"
        claude_failures_text += f"- Result from Code Under Review: {json.dumps(f['result_b'])}\n"
        claude_failures_text += f"- Result from Other Code: {json.dumps(f['result_a'])}\n"
        claude_failures_text += f"- Divergence reason: {f['reason']}\n"

    gemini_failures_text = ""
    for i, f in enumerate(serialized_failures, 1):
        gemini_failures_text += f"\n### Failure {i}\n"
        gemini_failures_text += f"- Input: {f['input']['args']}\n"
        gemini_failures_text += f"- Result from Code Under Review: {json.dumps(f['result_a'])}\n"
        gemini_failures_text += f"- Result from Other Code: {json.dumps(f['result_b'])}\n"
        gemini_failures_text += f"- Divergence reason: {f['reason']}\n"

    # Claude reviews code_B
    claude_prompt = _REVIEW_PROMPT_TEMPLATE.format(
        task_specification=task_spec,
        anonymized_code=anon_b,
        failures_text=claude_failures_text,
    )
    claude_packet = ExamPacket(
        agent="claude",
        code_under_review=anon_b,
        task_specification=task_spec,
        fuzz_failures=serialized_failures,
        review_prompt=claude_prompt,
    )

    # Gemini reviews code_A
    gemini_prompt = _REVIEW_PROMPT_TEMPLATE.format(
        task_specification=task_spec,
        anonymized_code=anon_a,
        failures_text=gemini_failures_text,
    )
    gemini_packet = ExamPacket(
        agent="gemini",
        code_under_review=anon_a,
        task_specification=task_spec,
        fuzz_failures=serialized_failures,
        review_prompt=gemini_prompt,
    )

    logger.info(
        "Prepared exam packets: %d failures, anon_a=%d chars, anon_b=%d chars",
        len(serialized_failures), len(anon_a), len(anon_b),
    )

    return claude_packet, gemini_packet


# ---------------------------------------------------------------------------
# Feedback file management
# ---------------------------------------------------------------------------

def write_feedback_files(
    state_dir: Path,
    claude_packet: ExamPacket,
    gemini_packet: ExamPacket,
    round_number: int,
) -> None:
    """Write feedback JSON files that agents read via get_feedback command.

    Each agent's feedback file contains the code they should review,
    the failing test cases, and the review prompt.
    """
    sessions_dir = state_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    for packet in (claude_packet, gemini_packet):
        feedback = {
            "round": round_number,
            "code_under_review": packet.code_under_review,
            "review_prompt": packet.review_prompt,
            "previous_fuzz_failures": packet.fuzz_failures,
        }
        task_id = os.environ.get("JANUSMASK_TASK_ID", "")
        path = sessions_dir / generate_feedback_filename(packet.agent, round_number, task_id)
        with open(path, "w") as f:
            json.dump(feedback, f, indent=2, ensure_ascii=False)
            f.write("\n")

    logger.info("Wrote feedback files for round %d", round_number)


def clear_feedback_files(state_dir: Path) -> None:
    """Remove feedback files (all rounds) after cross-examination is complete."""
    sessions_dir = state_dir / "sessions"
    task_id = os.environ.get("JANUSMASK_TASK_ID", "")
    for agent in ("claude", "gemini"):
        pattern = feedback_glob_pattern(agent, task_id if task_id else None)
        for path in sessions_dir.glob(pattern):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    logger.info("Cleared feedback files")
