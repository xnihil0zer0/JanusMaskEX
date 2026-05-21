"""Safe-subpath check used by hooks and orchestrator scope gates.

``is_safe_subpath(candidate, root)`` returns True iff ``Path(candidate).resolve()``
is a descendant of ``Path(root).resolve()``. The function never raises; any
exception (including ``ValueError`` from ``relative_to``, ``OSError`` from a
missing path component, or ``TypeError`` from ``None`` inputs) is converted
to a ``False`` return so callers can use it as a pure boolean predicate.

This module deliberately has NO module-scope test dependencies: ``pytest`` is
imported only inside the ``__main__`` block below, so importing
``harness.safe_subpath`` works in environments where pytest is not installed
(production sandboxes, batch workers, etc.). Tests live in the sibling file
``tests/test_safe_subpath.py``.
"""
from __future__ import annotations
import pathlib

def is_safe_subpath(candidate: str, root: str) -> bool:
    """Check if candidate path is a safe descendant of root.

    Returns True iff Path(candidate).resolve() is a descendant of
    Path(root).resolve(). Uses Path.resolve() and Path.relative_to() to
    detect escapes. Never raises; returns False on any exception (e.g.,
    ValueError from relative_to, TypeError from None inputs).

    Args:
        candidate: Path to check (str)
        root: Root path (str)

    Returns:
        bool: True if candidate is a safe descendant of root, False otherwise
    """
    try:
        candidate_resolved = Path(candidate).resolve()
        root_resolved = Path(root).resolve()
        candidate_resolved.relative_to(root_resolved)
        return True
    except Exception:
        return False
from pathlib import Path
if __name__ == '__main__':
    import pytest
    import sys
    sys.exit(pytest.main(['tests/test_safe_subpath.py', '-v']))