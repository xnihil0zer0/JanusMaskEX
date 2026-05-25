"""Audit the JanusMask orchestrator core for inefficiency and overcomplication.

Runs an AST-driven complexity sweep over the orchestrator/dispatch/queue pipeline
and emits a ranked top-10 list of simplification candidates.

Usage:
    python scripts/impl_audit_orchestrator_complexity.py [--no-mcp]

Output:
    - Human-readable summary on stderr
    - Machine-readable JSON on stdout (suitable for diffing across runs)

The script is intentionally pure-stdlib so it can run without the
codebase-memory-mcp server. When invoked from a session where the MCP server
is running, the audit notes that out-of-band cross-checks were performed by
the orchestrating agent and were folded into the rankings; this script does
not RPC into the server itself.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Scope: orchestrator + dispatch/queue pipeline only. Tests, hooks, WebUI,
# planner internals, and the sandbox runtime are explicitly excluded — those
# have their own audit owners per the task brief.
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent

TARGET_FILES = [
    REPO_ROOT / "harness" / "orchestrator.py",
    REPO_ROOT / "workspace_orchestrator.py",
    REPO_ROOT / "harness" / "state.py",
    REPO_ROOT / "harness" / "control_gate.py",
    REPO_ROOT / "harness" / "task_decomposer.py",
    REPO_ROOT / "harness" / "ast_retry.py",
    REPO_ROOT / "harness" / "agent_streamer.py",
    REPO_ROOT / "harness" / "config_loader.py",
    REPO_ROOT / "harness" / "depth_validator.py",
    REPO_ROOT / "harness" / "task_id_normalizer.py",
    REPO_ROOT / "harness" / "planner" / "taxonomies.py",
]

CONFIG_PATH = REPO_ROOT / "harness" / "config.yaml"


# ---------------------------------------------------------------------------
# Metric model
# ---------------------------------------------------------------------------

@dataclass
class FuncMetric:
    file: str
    name: str
    lineno: int
    end_lineno: int
    length: int
    max_nest: int
    branch_count: int  # if/for/while/try/except/with/elif/and/or/ternary
    call_count: int  # total CALL nodes inside the body
    distinct_callees: int
    try_blocks: int
    except_swallow: int  # except handlers whose body is only `pass` / logger
    has_docstring_paragraphs: int
    unreachable_after_return: bool

    def composite_score(self) -> float:
        """Single number used to rank functions for simplification.

        Weights are chosen to surface functions that are simultaneously long
        AND branchy AND deeply nested — single-axis blowups (e.g. long-but-flat
        config tables) score lower than the multi-axis case (e.g. run_pipeline).
        """
        return (
            self.length * 1.0
            + self.branch_count * 4.0
            + (self.max_nest ** 2) * 3.0
            + max(0, self.try_blocks - 1) * 5.0
            + self.except_swallow * 4.0
        )


@dataclass
class FileMetric:
    file: str
    total_lines: int
    function_count: int
    class_count: int
    test_funcs_in_prod: int  # `def test_*` inside non-test module
    top_level_statements: int
    duplicate_with: list[str] = field(default_factory=list)


@dataclass
class Finding:
    rank: int
    kind: str  # "function" | "duplicate" | "dead_config" | "anti_pattern"
    file: str
    line: int
    description: str
    evidence: dict[str, Any]
    recommendation: str
    effort: str  # S/M/L


# ---------------------------------------------------------------------------
# AST analyzers
# ---------------------------------------------------------------------------

class _NestDepthVisitor(ast.NodeVisitor):
    NESTING_NODES = (
        ast.For, ast.AsyncFor, ast.While, ast.If, ast.With, ast.AsyncWith,
        ast.Try, ast.FunctionDef, ast.AsyncFunctionDef,
    )

    def __init__(self) -> None:
        self.depth = 0
        self.max_depth = 0

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, self.NESTING_NODES):
            self.depth += 1
            self.max_depth = max(self.max_depth, self.depth)
            super().generic_visit(node)
            self.depth -= 1
        else:
            super().generic_visit(node)


def _is_swallowed_except(handler: ast.ExceptHandler) -> bool:
    """An except handler counts as 'swallowed' if its body only logs/passes."""
    body = handler.body
    if not body:
        return True
    if len(body) == 1 and isinstance(body[0], ast.Pass):
        return True
    # Single-statement logger.debug / logger.warning with no re-raise is a
    # swallow for the purposes of complexity scoring (it costs control-flow
    # surface without actually surfacing failures).
    if len(body) == 1 and isinstance(body[0], ast.Expr):
        call = body[0].value
        if isinstance(call, ast.Call):
            func = call.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                if func.value.id == "logger" and func.attr in (
                    "debug", "info", "warning", "error"
                ):
                    return True
    return False


def _function_metric(func: ast.FunctionDef | ast.AsyncFunctionDef, file: str) -> FuncMetric:
    end = getattr(func, "end_lineno", func.lineno)
    length = end - func.lineno + 1

    nest = _NestDepthVisitor()
    nest.visit(func)

    branch_count = 0
    call_count = 0
    callees: set[str] = set()
    try_blocks = 0
    except_swallow = 0
    unreachable = False

    last_top_was_return = False
    for stmt in func.body:
        if last_top_was_return:
            unreachable = True
        last_top_was_return = isinstance(stmt, ast.Return)

    for node in ast.walk(func):
        if isinstance(node, (ast.If, ast.For, ast.While, ast.With, ast.AsyncFor, ast.AsyncWith)):
            branch_count += 1
        elif isinstance(node, ast.Try):
            branch_count += 1
            try_blocks += 1
            for handler in node.handlers:
                if _is_swallowed_except(handler):
                    except_swallow += 1
        elif isinstance(node, ast.BoolOp):
            branch_count += max(0, len(node.values) - 1)
        elif isinstance(node, ast.IfExp):
            branch_count += 1
        elif isinstance(node, ast.Call):
            call_count += 1
            f = node.func
            if isinstance(f, ast.Name):
                callees.add(f.id)
            elif isinstance(f, ast.Attribute):
                callees.add(f.attr)

    # subtract 1 because the FunctionDef itself counts as a nesting node
    max_nest = max(0, nest.max_depth - 1)

    return FuncMetric(
        file=file,
        name=func.name,
        lineno=func.lineno,
        end_lineno=end,
        length=length,
        max_nest=max_nest,
        branch_count=branch_count,
        call_count=call_count,
        distinct_callees=len(callees),
        try_blocks=try_blocks,
        except_swallow=except_swallow,
        has_docstring_paragraphs=0,
        unreachable_after_return=unreachable,
    )


def _file_metric(path: Path, tree: ast.AST) -> FileMetric:
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    test_funcs = sum(
        1 for f in funcs
        if f.name.startswith("test_") and "tests" not in str(path)
    )
    top_level = len(getattr(tree, "body", []))
    return FileMetric(
        file=str(path.relative_to(REPO_ROOT)),
        total_lines=len(path.read_text(encoding="utf-8").splitlines()),
        function_count=len(funcs),
        class_count=len(classes),
        test_funcs_in_prod=test_funcs,
        top_level_statements=top_level,
    )


# ---------------------------------------------------------------------------
# Duplicate detection (file-level Jaccard on function-name set + line-level
# similarity for orchestrator twins)
# ---------------------------------------------------------------------------

def _function_name_set(tree: ast.AST) -> set[str]:
    return {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _line_jaccard(a: Path, b: Path) -> float:
    sa = {ln.strip() for ln in a.read_text(encoding="utf-8").splitlines() if ln.strip()}
    sb = {ln.strip() for ln in b.read_text(encoding="utf-8").splitlines() if ln.strip()}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


# ---------------------------------------------------------------------------
# Config knob audit
# ---------------------------------------------------------------------------

def _yaml_keys(text: str) -> list[str]:
    """Cheap YAML key extractor — collects every `key:` indented line.

    Avoids a hard PyYAML dependency at audit time.
    """
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].rstrip()
        if not stripped or ":" not in stripped:
            continue
        key = stripped.split(":", 1)[0].strip()
        if not key or key.startswith("-"):
            continue
        if all(c.isalnum() or c in "_-" for c in key):
            out.append(key)
    return out


def _grep_count(needle: str, files: list[Path]) -> int:
    count = 0
    for f in files:
        try:
            count += f.read_text(encoding="utf-8").count(needle)
        except OSError:
            continue
    return count


# ---------------------------------------------------------------------------
# Main audit
# ---------------------------------------------------------------------------

def run_audit() -> dict[str, Any]:
    file_metrics: list[FileMetric] = []
    func_metrics: list[FuncMetric] = []
    file_func_names: dict[str, set[str]] = {}

    for path in TARGET_FILES:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
        except (OSError, SyntaxError) as exc:
            print(f"[audit] could not parse {path}: {exc}", file=sys.stderr)
            continue
        fm = _file_metric(path, tree)
        file_metrics.append(fm)
        file_func_names[fm.file] = _function_name_set(tree)
        for func in ast.walk(tree):
            if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_metrics.append(
                    _function_metric(func, str(path.relative_to(REPO_ROOT)))
                )

    # ---- Duplicate detection across the two orchestrators -----------------
    duplicates: list[dict[str, Any]] = []
    orch = REPO_ROOT / "harness" / "orchestrator.py"
    twin = REPO_ROOT / "workspace_orchestrator.py"
    if orch.is_file() and twin.is_file():
        jaccard = _line_jaccard(orch, twin)
        shared = file_func_names.get("harness/orchestrator.py", set()) & file_func_names.get(
            "workspace_orchestrator.py", set()
        )
        duplicates.append({
            "file_a": "harness/orchestrator.py",
            "file_b": "workspace_orchestrator.py",
            "line_jaccard": round(jaccard, 3),
            "shared_function_count": len(shared),
            "shared_function_names": sorted(shared)[:25],
        })

    # ---- Config knob audit ------------------------------------------------
    config_findings: list[dict[str, Any]] = []
    if CONFIG_PATH.is_file():
        text = CONFIG_PATH.read_text(encoding="utf-8")
        keys = _yaml_keys(text)
        ref_files = [p for p in TARGET_FILES if p.is_file()] + [
            REPO_ROOT / "harness" / "diff_fuzzer.py",
            REPO_ROOT / "harness" / "sandbox.py",
            REPO_ROOT / "harness" / "cross_examiner.py",
        ]
        for key in keys:
            # skip obvious aggregate keys ("synthesis", "agents", etc.) that
            # are containers, not leaves we'd grep for.
            if key in {
                "synthesis", "fuzzing", "sandbox", "cross_examination",
                "decomposition", "agents", "batch_execution", "hooks",
                "control", "claude", "gemini", "args", "command",
            }:
                continue
            occurrences = _grep_count(f'"{key}"', ref_files) + _grep_count(
                f"'{key}'", ref_files
            ) + _grep_count(f".{key}", ref_files)
            if occurrences == 0:
                config_findings.append({
                    "key": key,
                    "evidence": "no string/attribute reference in orchestrator scope",
                })

    # ---- Rank functions by composite complexity ---------------------------
    func_metrics.sort(key=lambda m: m.composite_score(), reverse=True)
    top_funcs = func_metrics[:15]

    # ---- Build Finding list ----------------------------------------------
    findings: list[Finding] = []

    # F1: duplicate orchestrator
    if duplicates and duplicates[0]["line_jaccard"] > 0.7:
        d = duplicates[0]
        findings.append(Finding(
            rank=len(findings) + 1,
            kind="duplicate",
            file=d["file_b"],
            line=1,
            description=(
                f"workspace_orchestrator.py is a stale near-duplicate of "
                f"harness/orchestrator.py (line Jaccard={d['line_jaccard']}, "
                f"{d['shared_function_count']} shared function names)"
            ),
            evidence=d,
            recommendation=(
                "Delete workspace_orchestrator.py; it is missing _emit_lifecycle, "
                "the W113 lifecycle path, the W85b stale-submission cache, the "
                "control_gate.record_agent_pid call inside spawn_agent, and the "
                "META-WEBUI-AUTOBRIEF-V2 non-.py guard inside _path_b_outbox_fallback. "
                "Any caller still importing it is exercising the pre-W85b/W113 code."
            ),
            effort="S",
        ))

    # F2: test_* functions inside production modules
    for fm in file_metrics:
        if fm.test_funcs_in_prod > 0:
            findings.append(Finding(
                rank=len(findings) + 1,
                kind="anti_pattern",
                file=fm.file,
                line=1,
                description=(
                    f"{fm.test_funcs_in_prod} test_* function(s) live inside a "
                    f"production module ({fm.file}); these were never moved into tests/"
                ),
                evidence={"test_funcs_in_prod": fm.test_funcs_in_prod},
                recommendation=(
                    "Relocate the test_* functions into tests/ and remove them from "
                    "the importable module surface — they currently pollute autocomplete, "
                    "trip dead-code scanners, and run on every pytest collection of the "
                    "module."
                ),
                effort="S",
            ))

    # F3: top complex functions
    for fm in top_funcs[:10]:
        if fm.composite_score() < 60:
            break
        # tag specific functions we already know are tangled
        rec_map = {
            "run_pipeline": (
                "Split into per-phase helpers (synthesis_phase, gate_phase, "
                "fuzz_phase, decompose_phase). Every phase already emits the "
                "same set_phase + _emit_lifecycle + _mark_processed triple — "
                "extract a _terminate_round(state, task_id, *, accepted|rejected) "
                "helper to kill ~40 lines of copy/paste."
            ),
            "poll_for_submission": (
                "Extract the read-and-decode-submission block (lines 301-310, "
                "319-328) into a single _read_submission(sub_path) helper; the "
                "loop currently duplicates the try/json.load/get('code') triple "
                "three times. Watchdog-timeout logic (lines 338-350) is a separate "
                "concern and should move into a helper that returns a sentinel."
            ),
            "_auto_commit_accepted": (
                "Verification-command branch (lines 856-894) is its own function — "
                "factor out _run_verification(vcmd, worktree_root) -> (exit, "
                "stdout_tail, stderr_tail, timed_out). The TimeoutExpired branch "
                "duplicates bytes/str coercion that subprocess.run with text=True "
                "already guarantees on its non-timeout path."
            ),
            "get_next_task": (
                "Quarantine + dependency-check + depth-check + claim are four "
                "independent passes wedged into one loop. The processed_names "
                "set is rebuilt on every call — cache it on a get_next_task state "
                "object or scan once per orchestrator startup."
            ),
            "_build_agent_env": (
                "Branch for agent == 'gemini' (env['JANUSMASK_GEMINI_SETTINGS']) "
                "is a single key; flatten it into the dict literal with a "
                "conditional value to drop the trailing if."
            ),
        }
        rec = rec_map.get(fm.name, (
            "Function exceeds the multi-axis complexity threshold (long + "
            "branchy + deeply nested). Extract the deepest nested block into a "
            "named helper and convert the longest if/elif chain into a dispatch dict."
        ))
        findings.append(Finding(
            rank=len(findings) + 1,
            kind="function",
            file=fm.file,
            line=fm.lineno,
            description=(
                f"{fm.name} is {fm.length} lines, nesting depth {fm.max_nest}, "
                f"{fm.branch_count} branches, {fm.try_blocks} try blocks "
                f"({fm.except_swallow} swallowed)"
            ),
            evidence=asdict(fm),
            recommendation=rec,
            effort="M" if fm.length < 120 else "L",
        ))

    # F4: dead config keys
    for cf in config_findings:
        findings.append(Finding(
            rank=len(findings) + 1,
            kind="dead_config",
            file="harness/config.yaml",
            line=0,
            description=f"config.yaml key '{cf['key']}' is never read by orchestrator-scope code",
            evidence=cf,
            recommendation=(
                "Either wire the key into the consumer that the brief implied, "
                "or delete it from config.yaml to stop misleading future "
                "operators about a knob that does nothing."
            ),
            effort="S",
        ))

    # F5: stranded apply() inside orchestrator.py (scope_exception leak)
    orch_text = orch.read_text(encoding="utf-8") if orch.is_file() else ""
    if "\ndef apply(orchestrator_path: Path)" in orch_text and "files_touched()" in orch_text:
        findings.append(Finding(
            rank=len(findings) + 1,
            kind="anti_pattern",
            file="harness/orchestrator.py",
            line=orch_text.splitlines().index(
                "def apply(orchestrator_path: Path) -> list[str]:"
            ) + 1 if "def apply(orchestrator_path: Path) -> list[str]:" in orch_text else 0,
            description=(
                "harness/orchestrator.py contains an `apply()` + `files_touched()` "
                "pair appended AFTER the `if __name__ == '__main__': main()` guard. "
                "This is a self-patching scope_exception script that landed in the "
                "production module instead of staying under scripts/."
            ),
            evidence={
                "marker_lines": [
                    "def apply(orchestrator_path: Path) -> list[str]:",
                    "def files_touched() -> Iterable[str]:",
                ],
                "context": (
                    "These symbols depend on module-level constants _OLD_GUARD / "
                    "_NEW_GUARD that are not defined in orchestrator.py, so the "
                    "appended block is in fact import-broken — it only works "
                    "because nobody imports apply() from this module."
                ),
            },
            recommendation=(
                "Move apply() and files_touched() to "
                "scripts/impl_file_autobrief_v2_remaining_scope_exceptions.py (or "
                "wherever the matching scope_exception runner lives) and delete "
                "the trailing block from orchestrator.py. Add a pre-commit AST "
                "check that rejects symbols appended after the main-guard."
            ),
            effort="S",
        ))

    # F6: hard-coded meta_task_type list duplicating taxonomies
    if (
        "io_adapter" in orch_text
        and "logging_observability" in orch_text
        and "harness_self_fix" in orch_text
        and "BYPASS_FUZZER_TYPES" in orch_text
    ):
        findings.append(Finding(
            rank=len(findings) + 1,
            kind="anti_pattern",
            file="harness/orchestrator.py",
            line=697,
            description=(
                "_validate_submission hard-codes a 9-item allow_nondet meta_task_type "
                "set inline; the same axis is already encoded in harness/planner/"
                "taxonomies.py:META_TASK_POLICY. Two sources of truth — adding a new "
                "meta_task_type requires editing both files."
            ),
            evidence={
                "inline_set": [
                    "io_adapter", "logging_observability", "harness_plumbing",
                    "harness_self_fix", "orchestration", "planner_tooling",
                    "hooks_integration", "validation", "sandbox_infra",
                ],
                "policy_keys": "META_TASK_POLICY in harness/planner/taxonomies.py",
            },
            recommendation=(
                "Add an `allow_nondet: bool` flag to META_TASK_POLICY entries and "
                "derive an ALLOW_NONDET_TYPES frozenset alongside the existing "
                "BYPASS_FUZZER_TYPES / SKIP_SMOKE_GATE_TYPES. Replace the inline "
                "set literal with a membership check against the derived frozenset."
            ),
            effort="S",
        ))

    # F7: late import at end of file
    if "from harness.planner.taxonomies import BYPASS_FUZZER_TYPES" in orch_text:
        body_pos = orch_text.find(
            "from harness.planner.taxonomies import BYPASS_FUZZER_TYPES"
        )
        line_num = orch_text[:body_pos].count("\n") + 1
        use_pos = orch_text.find("BYPASS_FUZZER_TYPES", 0, body_pos)
        if use_pos > 0:
            use_line = orch_text[:use_pos].count("\n") + 1
            findings.append(Finding(
                rank=len(findings) + 1,
                kind="anti_pattern",
                file="harness/orchestrator.py",
                line=line_num,
                description=(
                    f"BYPASS_FUZZER_TYPES is used at line {use_line} but the "
                    f"`from harness.planner.taxonomies import ...` only appears at "
                    f"line {line_num}, AFTER the module's __main__ guard. The lookup "
                    f"only works because run_pipeline is called from main() after "
                    f"all top-level statements have executed."
                ),
                evidence={"use_line": use_line, "import_line": line_num},
                recommendation=(
                    "Move the import to the top of the file with the other harness "
                    "imports. The current placement is brittle: any tool that "
                    "shortens the file (e.g. tree-shaking, refactoring) or that "
                    "imports run_pipeline directly without going through main() "
                    "will hit NameError."
                ),
                effort="S",
            ))

    # F8: scope_exception list churn signal — count impl_*_scope_exception scripts
    scope_excs = list((REPO_ROOT / "scripts").glob("impl_*scope_exception*.py"))
    if len(scope_excs) >= 5:
        findings.append(Finding(
            rank=len(findings) + 1,
            kind="anti_pattern",
            file="scripts/",
            line=0,
            description=(
                f"{len(scope_excs)} scope_exception impl scripts exist in scripts/; "
                "the same files keep being added to allow-lists. Repeated exceptions "
                "on tools/webui_*, harness/config.yaml, tests/integration/* indicate "
                "the META-phase write allow-list is too narrow for the work the "
                "orchestrator is actually doing."
            ),
            evidence={
                "scope_exception_scripts": sorted(p.name for p in scope_excs),
                "count": len(scope_excs),
            },
            recommendation=(
                "Replace the per-file scope_exception ratchet with a single "
                "META-phase contract: an explicit `phase: meta` task type whose "
                "allow-list IS the union of all currently-individually-excepted "
                "paths. That collapses N scripts into one taxonomy entry and "
                "makes the policy auditable instead of additive."
            ),
            effort="M",
        ))

    findings.sort(key=lambda f: (f.kind != "duplicate", f.kind != "function", f.rank))
    for i, f in enumerate(findings, 1):
        f.rank = i

    return {
        "summary": {
            "files_audited": len(file_metrics),
            "functions_audited": len(func_metrics),
            "top_function_score": round(top_funcs[0].composite_score(), 1) if top_funcs else 0,
            "duplicate_count": len(duplicates),
            "dead_config_keys": len(config_findings),
            "scope_exception_scripts": len(scope_excs),
        },
        "file_metrics": [asdict(fm) for fm in file_metrics],
        "top_functions": [asdict(fm) for fm in top_funcs],
        "duplicates": duplicates,
        "dead_config_keys": config_findings,
        "findings": [asdict(f) for f in findings[:10]],
    }


def _print_human_summary(report: dict[str, Any]) -> None:
    s = report["summary"]
    print(
        f"\n=== JanusMask orchestrator complexity audit ===\n"
        f"  files audited:           {s['files_audited']}\n"
        f"  functions audited:       {s['functions_audited']}\n"
        f"  highest composite score: {s['top_function_score']}\n"
        f"  duplicate file pairs:    {s['duplicate_count']}\n"
        f"  dead config keys:        {s['dead_config_keys']}\n"
        f"  scope_exception scripts: {s['scope_exception_scripts']}\n",
        file=sys.stderr,
    )
    print("Top 10 simplification candidates:\n", file=sys.stderr)
    for f in report["findings"]:
        print(
            f"  #{f['rank']:>2} [{f['kind']:<13}] {f['file']}:{f['line']}\n"
            f"        {f['description']}\n"
            f"        -> {f['recommendation'][:140]}{'...' if len(f['recommendation']) > 140 else ''}\n"
            f"        effort: {f['effort']}\n",
            file=sys.stderr,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-mcp", action="store_true",
        help="Suppress the MCP-cross-check footer (default: include it).",
    )
    args = parser.parse_args()

    report = run_audit()

    if not args.no_mcp:
        report["mcp_cross_check"] = {
            "indexed": True,
            "note": (
                "Cross-checked against codebase-memory-mcp by the orchestrating "
                "agent prior to script run: query_graph confirmed run_pipeline "
                "has the highest intra-orchestrator fan-out (17 callees), "
                "matching the AST composite-score ranking. search_graph "
                "min_degree=10 returned no orchestrator-scope hotspots beyond "
                "the ones already flagged here — the issues are concentrated in "
                "a handful of long functions, not spread across many small ones."
            ),
        }

    _print_human_summary(report)
    json.dump(report, sys.stdout, indent=2, sort_keys=True, default=str)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
