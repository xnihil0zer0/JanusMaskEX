"""ngv2.fail_fast -- pure, stdlib-only silent-failure prevention utility.

Three severity tiers and two boundary assertions guard the run lifecycle
against silent failure:

* ``fatal``  -- always raises (re-raises an in-flight exception when one is
  active, raises an explicitly supplied exception, or otherwise raises a
  fresh ``RuntimeError``).
* ``warn``   -- logs and returns a caller-supplied default, allowing a
  degraded-but-continuing path.
* ``trace``  -- logs a low-severity diagnostic and returns ``None``.

Plus exactly two boundary assertions:

* ``assert_not_none``     -- guards against ``None`` slipping past a seam.
* ``assert_file_exists``  -- guards against a missing required file.

The durable contract is the *control-flow* behavior (always-raise vs
return-sentinel vs no-op) together with the stable human-readable stderr
line format ``"<LEVEL> [<context>]: <message>"`` where ``<LEVEL>`` is
left-justified to a width of five characters. No clock, network,
randomness, or subprocess influences raising or return values; the only
filesystem touch is the existence probe required by ``assert_file_exists``.
"""
from __future__ import annotations
import os
import sys
from typing import Any, Optional, Union
__all__ = ['LEVEL_FATAL', 'LEVEL_WARN', 'LEVEL_TRACE', 'fatal', 'warn', 'trace', 'assert_not_none', 'assert_file_exists']
LEVEL_FATAL: str = 'FATAL'
LEVEL_WARN: str = 'WARN'
LEVEL_TRACE: str = 'TRACE'
_LEVEL_WIDTH = 5

def _format_line(level: str, context: str, message: str) -> str:
    """Build the stable single-line diagnostic string for a tier."""
    return '{level:<{width}} [{context}]: {message}'.format(level=level, width=_LEVEL_WIDTH, context=context, message=message)

def _emit(line: str) -> None:
    """Write a diagnostic line to stderr (the only output side-effect)."""
    print(line, file=sys.stderr)

def fatal(context: str, message: str, exc: Optional[BaseException]=None) -> None:
    """Log a fatal diagnostic and unconditionally raise.

    Behavior, in priority order:

    1. If an explicit ``exc`` is provided, raise it.
    2. Otherwise, if an exception is currently in flight (``fatal`` was
       called from within an ``except`` block), re-raise that exact
       exception object -- preserving the original error rather than
       masking it with a new one.
    3. Otherwise, raise a fresh ``RuntimeError`` whose message is the
       formatted diagnostic line.

    This function never returns.
    """
    line = _format_line(LEVEL_FATAL, context, message)
    _emit(line)
    if exc is not None:
        raise exc
    in_flight = sys.exc_info()[1]
    if in_flight is not None:
        raise in_flight
    raise RuntimeError(line)

def warn(context: str, message: str, default: Any=None) -> Any:
    """Log a warning diagnostic and return ``default`` (``None`` if omitted).

    Used for recoverable, degraded-path conditions: the caller continues
    with the supplied fallback value instead of aborting the run.
    """
    _emit(_format_line(LEVEL_WARN, context, message))
    return default

def trace(context: str, message: str) -> None:
    """Log a low-severity trace diagnostic and return ``None``.

    Used for best-effort, non-actionable notes (e.g. failed cleanup of a
    temporary resource) that should be visible but never alter control flow.
    """
    _emit(_format_line(LEVEL_TRACE, context, message))
    return None

def assert_not_none(value: Any, context: str, message: str) -> Any:
    """Return ``value`` unchanged unless it is exactly ``None``.

    Only the ``None`` singleton triggers a failure; other falsy values
    (``0``, ``""``, ``[]``, ``False``) pass through untouched. On ``None``
    a ``RuntimeError`` is raised carrying the bracketed context and message.
    """
    if value is None:
        raise RuntimeError(_format_line(LEVEL_FATAL, context, message))
    return value

def assert_file_exists(path: Union[str, 'os.PathLike[str]'], context: str) -> None:
    """Return ``None`` if ``path`` exists; raise ``FileNotFoundError`` if not.

    Accepts either a ``str`` or any ``os.PathLike`` (e.g. ``pathlib.Path``).
    The single filesystem probe (``os.path.exists``) is intentional: it is
    the boundary check this assertion exists to perform.
    """
    if not os.path.exists(path):
        message = 'file not found: {0}'.format(os.fspath(path))
        raise FileNotFoundError(_format_line(LEVEL_FATAL, context, message))
    return None