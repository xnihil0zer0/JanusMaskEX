"""geopack: a small real PACKAGE (C9.9 clean-room replication target).

Re-exports the pure public surface. ``deputil`` (which imports the third-party
``inflection``) is intentionally NOT re-exported here so importing the package
does not pull the dependency at load time -- it is reached only via its own
submodule import, which the engine routes to the replicant venv.
"""
from .base import unit_length, double_area
from .shapes import square_area
from .accumulator import Accumulator
from .fuzzy import clamp

__all__ = ["unit_length", "double_area", "square_area", "Accumulator", "clamp"]
