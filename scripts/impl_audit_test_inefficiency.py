#!/usr/bin/env python3
"""Audit JanusMask test infrastructure for inefficiency and redundancy.

Walks tests/ via AST, sniffs for duplicate assertion bodies, mock-heavy tests,
skip/xfail rot, and "tests-of-tests". Optionally invokes pytest --collect-only
and --durations=25 (sampled) to surface slow tests, and uses codebase-memory-mcp
(if available via uv/uvx/CLI) to flag tests that exercise functions with no
non-test callers.

Run:
    python3 scripts/impl_audit_test_inefficiency.py [--root /path/to/repo]

Writes a JSON report to stdout (preceded by a human summary). Exit code is
always 0 — this is a reporter, not an enforcer.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "tests"

# ---------------------------------------------------------------------------
# AST walker
# ---------------------------------------------------------------------------


class TestFileSummary:
    __slots__ = (
        "path",
        "rel_path",
        "test_count",
        "loc",
        "mock_hits",
        "patch_hits",
        "fixture_count",
        "fixture_depth_max",
        "skip_marks",
        "xfail_marks",
        "skip_reasons",
        "test_names",
        "assert_hashes",
        "called_funcs",
        "test_fn_to_assert_hashes",
        "imports",
    )

    def __init__(self, path: Path) -> None:
        self.path = path
        self.rel_path = str(path.relative_to(REPO_ROOT))
        self.test_count = 0
        self.loc = 0
        self.mock_hits = 0
        self.patch_hits = 0
        self.fixture_count = 0
        self.fixture_depth_max = 0
        self.skip_marks: list[dict[str, Any]] = []
        self.xfail_marks: list[dict[str, Any]] = []
        self.skip_reasons: list[str] = []
        self.test_names: list[str] = []
        self.assert_hashes: list[str] = []
        self.called_funcs: set[str] = set()
        self.test_fn_to_assert_hashes: dict[str, list[str]] = {}
        self.imports: set[str] = set()


def _hash_node(node: ast.AST) -> str:
    """Stable hash of an assertion subtree, ignoring positions/spaces."""
    canonical = ast.dump(node, annotate_fields=False, include_attributes=False)
    # Collapse whitespace, numbers, and string literals so renamed-only dupes
    # still collide.
    canonical = re.sub(r"\s+", "", canonical)
    canonical = re.sub(r"Constant\([^)]*\)", "C()", canonical)
    return hashlib.blake2b(canonical.encode(), digest_size=10).hexdigest()


def _decorator_name(dec: ast.AST) -> str:
    if isinstance(dec, ast.Call):
        return _decorator_name(dec.func)
    if isinstance(dec, ast.Attribute):
        return f"{_decorator_name(dec.value)}.{dec.attr}"
    if isinstance(dec, ast.Name):
        return dec.id
    return ""


def _extract_skip_reason(dec: ast.AST) -> str | None:
    if not isinstance(dec, ast.Call):
        return None
    for kw in dec.keywords:
        if kw.arg == "reason" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    if dec.args:
        for a in dec.args:
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                return a.value
    return None


def analyse_file(path: Path) -> TestFileSummary | None:
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return None
    s = TestFileSummary(path)
    s.loc = src.count("\n") + 1
    # Imports
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            s.imports.add(n.module)
        elif isinstance(n, ast.Import):
            for a in n.names:
                s.imports.add(a.name)
    # Mock/patch references
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            if n.id in ("Mock", "MagicMock", "AsyncMock"):
                s.mock_hits += 1
            elif n.id in ("patch",):
                s.patch_hits += 1
        elif isinstance(n, ast.Attribute):
            if n.attr in ("Mock", "MagicMock", "AsyncMock"):
                s.mock_hits += 1
            elif n.attr in ("patch", "patch_object", "patch_dict"):
                s.patch_hits += 1
    # Walk top-level + class-level functions to find tests/fixtures.

    def _visit_func(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        nonlocal s
        names = [_decorator_name(d) for d in fn.decorator_list]
        is_fixture = any(n.endswith("fixture") or n.endswith("pytest.fixture") for n in names)
        if is_fixture:
            s.fixture_count += 1
            # Approximate "depth" as body-statement count.
            s.fixture_depth_max = max(s.fixture_depth_max, len(fn.body))
        is_test = fn.name.startswith("test_")
        if is_test:
            s.test_count += 1
            s.test_names.append(fn.name)
            local_hashes: list[str] = []
            for sub in ast.walk(fn):
                if isinstance(sub, ast.Assert):
                    h = _hash_node(sub.test)
                    s.assert_hashes.append(h)
                    local_hashes.append(h)
                elif isinstance(sub, ast.Call):
                    target = _decorator_name(sub.func)
                    if target:
                        s.called_funcs.add(target)
            s.test_fn_to_assert_hashes[fn.name] = local_hashes
            for d in fn.decorator_list:
                dn = _decorator_name(d)
                if dn.endswith("mark.skip") or dn.endswith("mark.skipif"):
                    reason = _extract_skip_reason(d) or "(no reason)"
                    s.skip_marks.append({"test": fn.name, "reason": reason})
                    s.skip_reasons.append(reason)
                elif dn.endswith("mark.xfail"):
                    reason = _extract_skip_reason(d) or "(no reason)"
                    s.xfail_marks.append({"test": fn.name, "reason": reason})

    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _visit_func(n)
        elif isinstance(n, ast.ClassDef):
            for sub in n.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    _visit_func(sub)
    # Module-level pytestmark = pytest.mark.skipif(...)
    for n in tree.body:
        if isinstance(n, ast.Assign):
            targets = [t.id for t in n.targets if isinstance(t, ast.Name)]
            if "pytestmark" in targets:
                # Capture reason if present.
                if isinstance(n.value, ast.Call):
                    dn = _decorator_name(n.value.func)
                    reason = _extract_skip_reason(n.value) or "(module-level, no reason)"
                    if dn.endswith("skip") or dn.endswith("skipif"):
                        s.skip_marks.append({"test": "<module>", "reason": reason})
                        s.skip_reasons.append(reason)
                    elif dn.endswith("xfail"):
                        s.xfail_marks.append({"test": "<module>", "reason": reason})
    # Also find any pytest.skip(...) calls inside function bodies (runtime skip).
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            dn = _decorator_name(n.func)
            if dn in ("pytest.skip", "pytest.xfail"):
                reason = _extract_skip_reason(n) or "(runtime, no reason)"
                if dn == "pytest.skip":
                    s.skip_marks.append({"test": "<runtime>", "reason": reason})
                    s.skip_reasons.append(reason)
                else:
                    s.xfail_marks.append({"test": "<runtime>", "reason": reason})
    return s


# ---------------------------------------------------------------------------
# Pytest collection + durations
# ---------------------------------------------------------------------------


def pytest_collect_count(root: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=120,
        )
        tail = proc.stdout.strip().splitlines()[-3:]
        return {"exit": proc.returncode, "tail": tail, "stdout_lines": len(proc.stdout.splitlines())}
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"exit": -1, "error": str(e)}


def pytest_sample_durations(root: Path, target: str = "tests/test_taxonomy.py") -> dict[str, Any]:
    """Sample a small dir for slowest tests — full sweep too slow."""
    sample_dirs = [
        "tests/test_taxonomy.py",
        "tests/test_state.py",
        "tests/test_configuration.py",
    ]
    paths = [p for p in sample_dirs if (root / p).exists()]
    if not paths:
        return {"error": "no sample paths exist"}
    cmd = [sys.executable, "-m", "pytest", "-q", "--durations=25", "-x", *paths]
    try:
        t0 = time.time()
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=180,
        )
        elapsed = time.time() - t0
        out = proc.stdout + proc.stderr
        # Pull the "slowest durations" section.
        lines = out.splitlines()
        cap = []
        in_section = False
        for line in lines:
            if "slowest" in line.lower() and "durations" in line.lower():
                in_section = True
                cap.append(line)
                continue
            if in_section:
                if not line.strip():
                    break
                cap.append(line)
        return {
            "exit": proc.returncode,
            "wall_seconds": round(elapsed, 2),
            "sampled_paths": paths,
            "slowest_lines": cap[:30],
        }
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"error": str(e), "cmd": cmd[:8]}


# ---------------------------------------------------------------------------
# Scope-exception / improper-fix cross-reference
# ---------------------------------------------------------------------------


def scope_exception_scripts(root: Path) -> list[str]:
    return sorted(p.name for p in (root / "scripts").glob("*scope_exception*.py"))


def carve_out_or_scope_commits(root: Path) -> list[dict[str, str]]:
    try:
        proc = subprocess.run(
            [
                "git",
                "log",
                "--oneline",
                "--all",
                "-i",
                "--grep=scope_exception|carve_out|carveout|carve-out|nonpy",
                "-E",
                "-n",
                "50",
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        out = []
        for line in proc.stdout.splitlines():
            parts = line.split(" ", 1)
            if len(parts) == 2:
                out.append({"sha": parts[0], "subject": parts[1]})
        return out
    except (subprocess.TimeoutExpired, OSError):
        return []


# ---------------------------------------------------------------------------
# codebase-memory-mcp: find tests that exercise no-other-caller functions
# ---------------------------------------------------------------------------


def find_test_only_callees(root: Path) -> list[dict[str, Any]]:
    """Use codebase-memory-mcp CLI if available — fall back gracefully."""
    # Try `uvx codebase-memory-mcp query ...` form first. We avoid any real
    # MCP wire protocol here because this script is a one-shot reporter.
    candidates = [
        ["uvx", "codebase-memory-mcp", "--help"],
        ["uv", "run", "codebase-memory-mcp", "--help"],
    ]
    for cmd in candidates:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if proc.returncode == 0:
                break
        except (OSError, subprocess.TimeoutExpired):
            continue
    # The MCP tool isn't trivially CLI-pingable from here. Return a stub note
    # so the caller documents this gap — the operator can re-run with the
    # MCP graph queried separately and merge.
    return [{
        "note": (
            "codebase-memory-mcp query not invoked from this script: "
            "MCP tools are JSON-RPC over stdio and not designed for one-shot "
            "Python invocation. See report for the equivalent query_graph "
            "results collected at audit time."
        )
    }]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def collect_all(root: Path) -> tuple[list[TestFileSummary], dict[str, Any]]:
    files = []
    for p in sorted((root / "tests").rglob("test_*.py")):
        s = analyse_file(p)
        if s:
            files.append(s)
    # Duplicate-assert detection
    hash_to_locations: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for s in files:
        for fn_name, hashes in s.test_fn_to_assert_hashes.items():
            for h in hashes:
                hash_to_locations[h].append((s.rel_path, fn_name))
    duplicates = []
    for h, locs in hash_to_locations.items():
        # Only report when assertion appears in distinct tests across files.
        distinct_tests = {(p, t) for p, t in locs}
        if len(distinct_tests) > 4:
            duplicates.append({
                "hash": h,
                "occurrence_count": len(distinct_tests),
                "first_5_locations": sorted(distinct_tests)[:5],
            })
    duplicates.sort(key=lambda d: -d["occurrence_count"])
    # Mock-heavy ratio
    mock_heavy = []
    for s in files:
        if s.test_count == 0:
            continue
        ratio = (s.mock_hits + s.patch_hits) / max(s.test_count, 1)
        if ratio >= 3.0 and s.test_count >= 3:
            mock_heavy.append({
                "file": s.rel_path,
                "tests": s.test_count,
                "mock_calls": s.mock_hits + s.patch_hits,
                "ratio_per_test": round(ratio, 2),
            })
    mock_heavy.sort(key=lambda d: -d["ratio_per_test"])
    # Skip/xfail census
    skip_rows = []
    xfail_rows = []
    for s in files:
        for m in s.skip_marks:
            skip_rows.append({"file": s.rel_path, **m})
        for m in s.xfail_marks:
            xfail_rows.append({"file": s.rel_path, **m})
    # Zombies: skip/xfail with no condition AND no remove-by date
    zombies = []
    REMOVE_BY_RE = re.compile(
        r"(remove[ -]by|until|after|once|when [A-Z]|TODO|by 20\d\d)",
        re.IGNORECASE,
    )
    for row in skip_rows + xfail_rows:
        reason = row["reason"]
        if reason in ("(no reason)", "(module-level, no reason)", "(runtime, no reason)"):
            zombies.append({**row, "kind": "no-reason"})
        elif not REMOVE_BY_RE.search(reason) and "not yet" not in reason.lower():
            # Conditional skips with platform/symlink/etc. are fine.
            if any(
                t in reason.lower()
                for t in (
                    "symlink",
                    "platform",
                    "not supported",
                    "not available",
                    "not installed",
                    "missing",
                    "absent",
                    "unavailable",
                    "no /proc",
                    "no sidecar",
                    "not in real repo",
                    "ci_no_timing",
                    "cannot test",
                    "remained writable",
                    "fork() unavailable",
                )
            ):
                continue
            zombies.append({**row, "kind": "no-remove-by"})
    # Files-per-test density
    biggest = sorted(files, key=lambda s: -s.test_count)[:15]
    big_files = [
        {"file": s.rel_path, "tests": s.test_count, "loc": s.loc}
        for s in biggest
    ]
    # Scope exception clustering
    scope_files = scope_exception_scripts(root)
    scope_commits = carve_out_or_scope_commits(root)
    # "Tests-of-tests" / meta tests: those that import from tests.* or
    # scripts/_audit*, or live under tests/meta/, or whose subjects are other
    # test fixtures.
    test_of_tests = []
    for s in files:
        score = 0
        reasons = []
        if s.rel_path.startswith("tests/meta/"):
            score += 3
            reasons.append("lives under tests/meta/")
        if any(i.startswith("tests.") for i in s.imports):
            score += 2
            reasons.append("imports from tests.*")
        if any(i.startswith("scripts._audit") for i in s.imports):
            score += 2
            reasons.append("imports scripts._audit*")
        if "mock_agent_harness" in s.rel_path or "mock_agent" in s.rel_path:
            score += 2
            reasons.append("tests mock agent harness, not production")
        for tname in s.test_names:
            if "fixture" in tname or "mock" in tname:
                score += 1
                reasons.append(f"test name '{tname}' targets fixture/mock")
                break
        if score >= 2:
            test_of_tests.append({"file": s.rel_path, "score": score, "reasons": reasons})
    test_of_tests.sort(key=lambda d: -d["score"])
    return files, {
        "totals": {
            "files": len(files),
            "tests": sum(s.test_count for s in files),
            "loc": sum(s.loc for s in files),
            "fixtures": sum(s.fixture_count for s in files),
            "skip_marks": len(skip_rows),
            "xfail_marks": len(xfail_rows),
        },
        "biggest_files": big_files,
        "duplicate_assert_clusters_top10": duplicates[:10],
        "mock_heavy_top15": mock_heavy[:15],
        "skip_census": skip_rows,
        "xfail_census": xfail_rows,
        "zombies_top20": zombies[:20],
        "test_of_tests_top15": test_of_tests[:15],
        "scope_exception_scripts": scope_files,
        "scope_exception_script_count": len(scope_files),
        "carve_out_scope_commits_top": scope_commits[:20],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(REPO_ROOT))
    ap.add_argument(
        "--no-pytest", action="store_true",
        help="Skip pytest --collect-only and --durations sample",
    )
    args = ap.parse_args()
    root = Path(args.root)
    files, agg = collect_all(root)
    if not args.no_pytest:
        agg["pytest_collect"] = pytest_collect_count(root)
        agg["pytest_durations_sample"] = pytest_sample_durations(root)
    else:
        agg["pytest_collect"] = {"skipped": True}
        agg["pytest_durations_sample"] = {"skipped": True}
    agg["mcp_test_only_callees"] = find_test_only_callees(root)
    # Human summary first
    t = agg["totals"]
    summary_lines = [
        "=" * 72,
        "JanusMask test infrastructure audit",
        "=" * 72,
        f"Total test files:       {t['files']}",
        f"Total test functions:   {t['tests']}",
        f"Total test LoC:         {t['loc']}",
        f"Total fixtures (def):   {t['fixtures']}",
        f"Skip marks (incl mod):  {t['skip_marks']}",
        f"xfail marks:            {t['xfail_marks']}",
        f"scope_exception scripts under scripts/: {agg['scope_exception_script_count']}",
        "",
        "Top 5 biggest test files (by test count):",
    ]
    for row in agg["biggest_files"][:5]:
        summary_lines.append(f"  {row['tests']:4d} tests  {row['loc']:5d} LoC  {row['file']}")
    summary_lines += ["", "Top 5 mock-heavy files (mock+patch calls / test):"]
    for row in agg["mock_heavy_top15"][:5]:
        summary_lines.append(
            f"  ratio {row['ratio_per_test']:.1f}  {row['mock_calls']:3d} mocks  "
            f"{row['tests']:3d} tests  {row['file']}"
        )
    summary_lines += ["", "Top 5 'tests-of-tests' (meta layer / fixture suites):"]
    for row in agg["test_of_tests_top15"][:5]:
        summary_lines.append(
            f"  score {row['score']}  {row['file']}  [{'; '.join(row['reasons'])}]"
        )
    summary_lines += ["", "Top 5 duplicate-assertion clusters (same hash across 5+ tests):"]
    for row in agg["duplicate_assert_clusters_top10"][:5]:
        summary_lines.append(
            f"  {row['occurrence_count']}x  first: {row['first_5_locations'][0]}"
        )
    summary_lines += ["", "Zombie skip/xfail (no reason / no remove-by) — first 10:"]
    for row in agg["zombies_top20"][:10]:
        summary_lines.append(
            f"  {row['kind']:14s}  {row['file']}::{row['test']}  ({row['reason'][:60]})"
        )
    summary_lines += ["", "=" * 72, "JSON report follows.", "=" * 72]
    print("\n".join(summary_lines))
    print(json.dumps(agg, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
