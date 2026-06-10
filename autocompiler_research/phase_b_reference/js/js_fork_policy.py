"""Pure spawn-policy descriptor for the JS runner (Phase B, ac-js-fork-policy).

Data only — no process is ever created here. The spawn itself is injected at
the js_sandbox seam and, at runtime, routed through the bwrap agent jail (the
seccomp fuzz sandbox blocks execve/fork by design).
"""
from __future__ import annotations

_DEFAULT_TIMEOUT_MS = 5000


def fork_spec(node_bin, runner_path, batch_file, timeout_ms=_DEFAULT_TIMEOUT_MS) -> dict:
    """Build the exact spawn plan for one ``js_runner.js`` batch.

    Raises ``ValueError`` on any malformed input — a bad plan must never
    silently launch.
    """
    for label, part in (('node_bin', node_bin), ('runner_path', runner_path),
                        ('batch_file', batch_file)):
        if not isinstance(part, str) or not part:
            raise ValueError(f'{label} must be a non-empty str, got {part!r}')
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0:
        raise ValueError(f'timeout_ms must be a positive int, got {timeout_ms!r}')
    return {
        'argv': [node_bin, runner_path, batch_file],
        'start_new_session': True,
        'result_fd': 3,
        'timeout_ms': timeout_ms,
        'kill': {'signal': 'SIGKILL', 'scope': 'process_group'},
    }
