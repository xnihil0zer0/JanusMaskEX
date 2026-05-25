"""AST retry module for synthesizing code with validation retries."""
from pathlib import Path
from typing import Callable

def synthesize_with_retries(agent_name: str, base_prompt: str, config: dict, state_dir: Path, round_number: int, task: dict, run_agent_func: Callable, validate_code_func: Callable) -> tuple[bool, str | None, list]:
    """
    Synthesize code with retries on validation failures.

    Attempts to generate valid code by:
    1. Calling the agent to generate code
    2. Validating the generated code
    3. On validation failure, appending violations to the prompt and retrying

    Args:
        agent_name: Name of the agent to invoke
        base_prompt: Initial prompt for code synthesis
        config: Configuration dictionary
        state_dir: Path to the state directory
        round_number: Current round number
        task: Task specification dictionary
        run_agent_func: Callable that runs the agent and returns code or None
        validate_code_func: Callable that validates code and returns (valid, violations)

    Returns:
        Tuple of (success: bool, code: str | None, violations: list)
        - success: True if valid code was synthesized, False otherwise
        - code: The synthesized code (last attempt if exhausted)
        - violations: AST violations from the last validation attempt
    """
    max_ast_retries = config.get('synthesis', {}).get('max_ast_retries', 3)
    current_prompt = base_prompt
    code = None
    violations = []
    for attempt in range(max_ast_retries):
        code = run_agent_func(agent_name, current_prompt, config, state_dir, round_number, phase_name='synthesis')
        if code is None:
            timeout_error = f'\n\n[Retry attempt {attempt + 1}/{max_ast_retries}] Previous attempt timed out. Please try again and ensure the response completes.'
            current_prompt += timeout_error
            continue
        valid, violations = validate_code_func(code, task)
        if valid:
            return (True, code, violations)
        violations_text = f'\n\n[Retry attempt {attempt + 1}/{max_ast_retries}] Code validation failed with the following issues:\n'
        for violation in violations:
            violations_text += f'- {violation}\n'
        violations_text += 'Please fix these issues and regenerate the code.'
        current_prompt += violations_text
    return (False, code, violations)