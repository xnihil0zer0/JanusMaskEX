"""TargetDescriptor: declarative spec of a project the rebuild engine rebuilds.

A descriptor names the source modules to skeletonize, the test files that act
as the behavioral spec (copied verbatim), any seed/scaffolding files (package
``__init__``, conftest) the tests need to run in isolation, and where the
reconstructed replicant lands.
"""
from __future__ import annotations
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

@dataclass
class TargetDescriptor:
    """Everything the engine needs to rebuild a project clean-room.

    Attributes:
        name: Short slug used in task ids and commit messages.
        source_root: Absolute dir holding the original modules (read-only oracle).
        modules: Rel paths (under source_root) of .py modules to strip + rebuild.
        test_files: Rel paths of pytest files copied VERBATIM (the spec).
        output_dir: Absolute dir the skeleton + reconstructed code land in (its
            own git repo). MUST be distinct from source_root.
        stash_dir: Absolute dir (OUTSIDE output_dir) where original bodies are
            stashed for the oracle gate. Never committed into the replicant, so
            the replicant stays genuinely body-free until the agents fill it.
        seed_files: Rel paths copied VERBATIM into output_dir as scaffolding so
            the tests import-resolve in isolation (e.g. ``harness/__init__.py``).
        full_test_command: Whole-suite verification run in output_dir at VERIFY.
        unit_test_selector: pytest argument template scoping a single unit's
            tests; ``{unit}`` is substituted with the unit name. Empty -> the
            unit verification falls back to the bare test files.
        dependencies: External (3rd-party) pip-installable requirement lines the
            replicant needs to run -- discovered from requirements/pyproject/AST.
            Materialized into ``<out>/requirements.txt`` and installed into the
            replicant's own ``.venv`` so a clone runs standalone.
        requirements_files: Rel paths (under source_root) of the requirement
            manifests the deps were sourced from (audit trail).
        python_exe: Resolved interpreter the per-unit + full-suite verification
            run under -- the replicant's ``<out>/.venv/bin/python`` once
            provisioned, else ``None`` (ambient ``python``). The merged==original
            ORACLE always stays on the parent ambient python (it imports
            ``harness``); only the scoped pytest + full suite use this.
    """
    name: str
    source_root: Path
    modules: list[str]
    test_files: list[str]
    output_dir: Path
    stash_dir: Path
    seed_files: list[str] = field(default_factory=list)
    full_test_command: str = 'python -m pytest -q'
    unit_test_selector: str = ''
    dependencies: list[str] = field(default_factory=list)
    requirements_files: list[str] = field(default_factory=list)
    python_exe: str | None = None

    def __post_init__(self) -> None:
        """Normalize the path fields to absolute, resolved ``Path`` objects.

        Accepts ``str`` or ``Path`` for ``source_root``, ``output_dir`` and
        ``stash_dir``; each is coerced to a ``Path`` and ``.resolve()``d so the
        stored value is absolute and free of ``..`` segments. The remaining
        fields keep their declared values / defaults untouched.
        """
        self.source_root = Path(self.source_root).resolve()
        self.output_dir = Path(self.output_dir).resolve()
        self.stash_dir = Path(self.stash_dir).resolve()
    'Everything the engine needs to rebuild a project clean-room.'
from harness.rebuild.target import TargetDescriptor

def mathlib_descriptor(output_dir: Path, stash_dir: Path, source_root: Path) -> TargetDescriptor:
    """Build the descriptor for the shipped samples/mathlib smoke target."""
    return TargetDescriptor(name='mathlib', source_root=source_root, modules=['mathlib.py'], test_files=['test_mathlib.py'], output_dir=output_dir, stash_dir=stash_dir, seed_files=[], unit_test_selector='test_mathlib.py -k {unit}')

def janusmask_module_descriptor(name: str, modules: list[str], test_files: list[str], output_dir: Path, stash_dir: Path, source_root: Path, seed_files: list[str] | None=None, unit_test_selector: str='') -> TargetDescriptor:
    """Build a descriptor for rebuilding JanusMask's own leaf module(s) into JR."""
    raise NotImplementedError
'TargetDescriptor: declarative spec of a project the rebuild engine rebuilds.'