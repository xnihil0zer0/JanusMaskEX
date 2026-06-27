"""Extraction primitive for the task payload stored in a session row.

This module exposes :func:`get_task`, which reads the task payload --
phase input, target, prior findings and parked package -- out of a session
row supplied as a plain ``dict``.  It performs no database or network I/O;
the row is always passed in by the caller.  It fails closed: if any required
field is absent from the row a ``KeyError`` is raised naming the missing
field rather than silently substituting a default.
"""
from typing import Any, Dict, Tuple
REQUIRED_FIELDS: Tuple[str, ...] = ('phase_input', 'target', 'prior_findings', 'parked_package')

def get_task(session_row: dict) -> dict:
    """Extract the task payload from a session row dict.

    Parameters
    ----------
    session_row:
        A mapping representing one database session row.  It must contain
        every field listed in :data:`REQUIRED_FIELDS`.

    Returns
    -------
    dict
        A new dict mapping each canonical task field name to the value read
        from ``session_row``.  Nested values are returned by reference and
        are not copied or mutated.

    Raises
    ------
    KeyError
        If any required field is absent from ``session_row`` (fail closed).
    """
    missing = [field for field in REQUIRED_FIELDS if field not in session_row]
    if missing:
        raise KeyError('session_row is missing required field(s): ' + ', '.join(missing))
    task: Dict[str, Any] = {field: session_row[field] for field in REQUIRED_FIELDS}
    return task