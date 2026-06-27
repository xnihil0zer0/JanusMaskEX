"""ngv2.semgrep_adapter -- deterministic, injected-runner adapter around the
semgrep CLI.

This module never touches a real subprocess, shell, filesystem, or network.
``build_semgrep_argv`` purely constructs the semgrep argument vector, and
``run_semgrep`` reaches semgrep *only* through an injected ``runner`` callable.
Pure stdlib -- no third-party imports.
"""
from __future__ import annotations
import json
from typing import Any, Callable, Dict, List, Tuple
__all__ = ['build_semgrep_argv', 'run_semgrep']
Runner = Callable[[List[str]], Tuple[int, str, str]]

def build_semgrep_argv(target: str, *, config: str='auto') -> List[str]:
    """Deterministically build the semgrep command-line argv.

    Identical inputs always produce a byte-for-byte identical list with a
    stable flag/value ordering. The target is always placed last; ``--config``
    is always immediately followed by its value.
    """
    return ['semgrep', '--json', '--quiet', '--config', config, target]

def run_semgrep(target: str, *, runner: Runner, config: str='auto') -> Dict[str, Any]:
    """Run semgrep against ``target`` via the injected ``runner``.

    Builds the argv with :func:`build_semgrep_argv`, invokes ``runner(argv)``,
    and normalizes the ``(returncode, stdout, stderr)`` result into a semgrep
    JSON-shaped dict. A non-zero return code or unparseable stdout yields a
    safe empty-results dict instead of raising.
    """
    argv = build_semgrep_argv(target, config=config)
    returncode, stdout, stderr = runner(argv)
    if returncode != 0:
        return {'results': [], 'errors': [stderr or 'semgrep returned a non-zero exit code']}
    try:
        parsed = json.loads(stdout)
    except (ValueError, TypeError):
        return {'results': [], 'errors': []}
    if not isinstance(parsed, dict):
        return {'results': [], 'errors': []}
    parsed.setdefault('results', [])
    return parsed