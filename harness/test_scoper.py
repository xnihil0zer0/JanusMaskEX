"""AST-based static analysis for test scoping.

Maps source modules to the test files that import them so verification
commands can run only the relevant subset of the suite rather than the
full 5.8K test run.

Public API: :func:`get_relevant_test_files`.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Iterable

DEFAULT_TESTS_DIR = "tests"
DEFAULT_FALLBACK_TEST = "tests/test_import.py"


def _path_to_module(rel_path: str) -> str:
    """Convert a relative .py path to a dotted module name."""
    rel = rel_path.replace(os.sep, "/")
    if rel.endswith(".py"):
        rel = rel[:-3]
    if rel.endswith("/__init__"):
        rel = rel[: -len("/__init__")]
    return rel.replace("/", ".")


def _imports_from_tree(tree: ast.AST) -> set[str]:
    """Collect the set of module / attribute names imported by an AST."""
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
                for alias in node.names:
                    if alias.name:
                        imports.add(f"{node.module}.{alias.name}")
    return imports


def _gather_test_files(source_root: Path, tests_subdir: str) -> list[Path]:
    """Find all test_*.py / *_test.py files under source_root / tests_subdir."""
    tests_path = source_root / tests_subdir
    if not tests_path.is_dir():
        return []
    out: list[Path] = []
    for p in tests_path.rglob("*.py"):
        name = p.name
        if name.startswith("test_") or name.endswith("_test.py"):
            out.append(p)
    return out


def _parse_imports(file_path: Path) -> set[str]:
    """Parse imports out of a single .py file. Returns empty set on failure."""
    try:
        text = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    return _imports_from_tree(tree)


def _candidate_modules(rel: str) -> set[str]:
    """Return the dotted-module candidates a source rel-path can match."""
    candidates: set[str] = set()
    if not rel.endswith(".py"):
        return candidates
    mod = _path_to_module(rel)
    if mod:
        candidates.add(mod)
    parts = mod.split(".") if mod else []
    if parts:
        candidates.add(parts[-1])
    return candidates


def _file_stem(rel: str) -> str:
    return Path(rel).stem


def get_relevant_test_files(
    source_root: Path | str,
    files_touched: Iterable[str],
    tests_subdir: str = DEFAULT_TESTS_DIR,
    fallback: str = DEFAULT_FALLBACK_TEST,
) -> list[str]:
    """Return the list of relevant test files (rel-paths) for *files_touched*.

    Strategy:

    1. Gather every ``test_*.py`` / ``*_test.py`` under
       ``source_root/tests_subdir`` and statically parse each one's
       imports with :mod:`ast`.
    2. For each touched ``.py`` file, build a candidate set of dotted
       module names (full dotted path plus bare stem) and intersect
       against each test's import set. A test that imports any candidate
       directly (e.g. ``from harness import orchestrator`` or
       ``import harness.orchestrator``) is considered relevant.
    3. Apply the ``test_<stem>.py`` naming-convention fallback so a
       test that doesn't statically import the module still counts.
    4. If no relevant tests are found, return ``[fallback]`` when that
       file exists under ``source_root`` and ``[]`` otherwise -- the
       caller uses the single-file fallback to keep verification fast
       rather than running the full suite.

    Returned paths are repo-relative and are filtered through
    ``Path.is_file`` so the caller can append them to a pytest command
    without producing "file not found" errors.
    """
    root = Path(source_root)
    try:
        root = root.resolve()
    except OSError:
        pass

    touched = [
        str(f)
        for f in files_touched
        if isinstance(f, str) and f.endswith(".py")
    ]
    if not touched:
        fb = root / fallback
        return [fallback] if fb.is_file() else []

    test_files = _gather_test_files(root, tests_subdir)
    import_map: dict[Path, set[str]] = {}
    for tf in test_files:
        import_map[tf] = _parse_imports(tf)

    relevant: set[Path] = set()
    for src_rel in touched:
        # If the touched file is itself a test file, include it directly
        if src_rel.startswith(tests_subdir + "/") or src_rel.startswith("./" + tests_subdir + "/"):
            src_path = root / src_rel
            if src_path.is_file():
                relevant.add(src_path)
                continue

        candidates = _candidate_modules(src_rel)
        stem = _file_stem(src_rel)

        for tf, imports in import_map.items():
            if imports & candidates:
                relevant.add(tf)
                continue
            for imp in imports:
                last = imp.split(".")[-1]
                if last and last == stem:
                    relevant.add(tf)
                    break

        for tf in test_files:
            if tf.stem == f"test_{stem}":
                relevant.add(tf)

    if not relevant:
        fb = root / fallback
        return [fallback] if fb.is_file() else []

    out: list[str] = []
    for tf in sorted(relevant):
        try:
            rel = tf.resolve().relative_to(root)
        except (ValueError, OSError):
            continue
        rel_str = str(rel).replace(os.sep, "/")
        if (root / rel_str).is_file():
            out.append(rel_str)
    return out
