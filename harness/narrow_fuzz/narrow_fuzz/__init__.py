"""Per-``meta_task_type`` narrow-fuzz harness (W77b).

Runs property-style fuzzing on bypass-eligible canaries that the
diff-fuzzer cannot exercise (validators that take ``ast.AST`` inputs,
hook callbacks, internal plumbing). Per-type modules register under
``harness/narrow_fuzz/<meta_task_type>.py`` and expose one public
function::

    def fuzz(module_name: str, module_src: str, *, timeout: float = 5.0) -> str | None

Returns ``None`` on pass/skip; descriptive error string on fail. The
public :func:`run_narrow_fuzz` dispatches via :data:`._registry.REGISTRY`;
unregistered types return ``None`` silently to preserve bypass semantics
per the brief's G3 ("a type without a narrow-fuzz module still
bypasses").
"""
from __future__ import annotations

from harness.narrow_fuzz._registry import REGISTRY


def run_narrow_fuzz(
    meta_task_type: str,
    module_name: str,
    module_src: str,
    *,
    timeout: float = 5.0,
) -> str | None:
    """Dispatch to the per-type fuzz module.

    Returns ``None`` when no module is registered for
    ``meta_task_type`` (skip; preserves bypass semantics).
    """
    fuzz_fn = REGISTRY.get(meta_task_type)
    if fuzz_fn is None:
        return None
    return fuzz_fn(module_name, module_src, timeout=timeout)


__all__ = ["run_narrow_fuzz"]
