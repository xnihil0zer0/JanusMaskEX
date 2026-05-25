"""Static dispatch registry for narrow-fuzz per-type modules.

Per the brief's §11.1 decision the registry is a hardcoded dict literal,
not an ``importlib`` walk; dynamic discovery is deferred until the
registry exceeds three entries.
"""
from __future__ import annotations
from typing import Callable
from typing import Optional
from harness.narrow_fuzz import validation
FuzzFn = Callable[..., Optional[str]]
REGISTRY: dict[str, FuzzFn | None] = {'validation': validation.fuzz}
__version__ = '1.0.0'