"""Pure spawn-policy descriptor for the JS runner (leaf ac-js-fork-policy).

Data only: :func:`fork_spec` builds and returns the exact spawn plan dict for
one ``js_runner.js`` batch and NEVER launches a process. The actual spawn is
injected downstream at the js_sandbox seam; this module merely describes the
plan and fail-closes on any malformed input. Stdlib-only, no process creation.
"""
from __future__ import annotations
_DEFAULT_TIMEOUT_MS = 5000

def fork_spec(node_bin, runner_path, batch_file, timeout_ms=_DEFAULT_TIMEOUT_MS) -> dict:
    """Return the spawn plan describing how to run one js_runner.js batch.

    The returned dict has EXACTLY the keys ``argv``, ``start_new_session``,
    ``result_fd``, ``timeout_ms`` and ``kill``. No process is ever created.

    Raises:
        ValueError: if any path part is non-str or empty, or if ``timeout_ms``
            is a bool, is not an int, or is non-positive.
    """
    for name, part in (('node_bin', node_bin), ('runner_path', runner_path), ('batch_file', batch_file)):
        if not isinstance(part, str) or not part:
            raise ValueError(f'{name} must be a non-empty str, got {part!r}')
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0:
        raise ValueError(f'timeout_ms must be a positive int, got {timeout_ms!r}')
    return {'argv': [node_bin, runner_path, batch_file], 'start_new_session': True, 'result_fd': 3, 'timeout_ms': timeout_ms, 'kill': {'signal': 'SIGKILL', 'scope': 'process_group'}}