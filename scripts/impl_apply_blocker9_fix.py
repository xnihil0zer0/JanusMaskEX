"""Idempotent re-application of B3 blocker #9 fix to harness/orchestrator.py.

The agent's deterministic submission for task ORCHESTRATOR-002-planner-tooling-bypass
re-introduces the BYPASS_FUZZER_TYPES NameError each time it auto-commits: the bypass
logic block (BYPASS_FUZZER_TYPES + Task + should_bypass_fuzzer + process_task) lands
AFTER the `if __name__ == '__main__': main()` guard, so the symbols are unbound when
orchestrator.py is invoked as a script (the only invocation path scripts/impl_drain_capture.py
uses, via subprocess).

This script locates that block via AST and relocates it to BEFORE the guard. Idempotent:
running it on a file that already has the fix is a no-op (exit 0, message printed).

Usage: python3 scripts/impl_apply_blocker9_fix.py [path/to/orchestrator.py]

See ledger row 2026-04-19T20:25:45Z (blocker_resolved #9) for the original fix and
2026-04-19T21:05:00Z (scope_exception) for why this idempotent re-applier exists.
"""
import ast
import pathlib
import sys

DEFAULT_PATH = pathlib.Path(__file__).resolve().parent.parent / 'harness' / 'orchestrator.py'
TARGET_NAMES = {
    'BYPASS_FUZZER_TYPES',
    'Task',
    'should_bypass_fuzzer',
    'process_task',
}
GUARD_MARKER = "if __name__ == '__main__':"


def _find_guard_and_movees(tree: ast.Module) -> tuple[int, list[ast.stmt]]:
    """Return (guard_index_in_body, movee_nodes_after_guard)."""
    guard_idx = None
    for i, node in enumerate(tree.body):
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == '__name__'
            and len(node.test.comparators) == 1
            and isinstance(node.test.comparators[0], ast.Constant)
            and node.test.comparators[0].value == '__main__'
        ):
            guard_idx = i
            break
    if guard_idx is None:
        raise SystemExit("no `if __name__ == '__main__':` guard found")
    movees = []
    for node in tree.body[guard_idx + 1 :]:
        name = None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id in TARGET_NAMES:
                    name = tgt.id
                    break
        if name in TARGET_NAMES:
            movees.append(node)
    return guard_idx, movees


def _block_line_range(node: ast.stmt) -> tuple[int, int]:
    start = node.lineno
    end = node.end_lineno
    for d in getattr(node, 'decorator_list', []) or []:
        if d.lineno < start:
            start = d.lineno
    return start, end


def apply(path: pathlib.Path) -> int:
    text = path.read_text(encoding='utf-8')
    tree = ast.parse(text)
    guard_idx, movees = _find_guard_and_movees(tree)
    if not movees:
        print(f"{path}: already fixed (no target symbols after guard)")
        return 0
    lines = text.splitlines(keepends=True)
    ranges = sorted(_block_line_range(n) for n in movees)
    extracted_chunks = []
    for start, end in ranges:
        extracted_chunks.append(''.join(lines[start - 1 : end]))
    survivors = list(lines)
    for start, end in reversed(ranges):
        del survivors[start - 1 : end]
    new_text = ''.join(survivors)
    guard_pos = new_text.index(GUARD_MARKER)
    moved = '\n'.join(chunk.rstrip('\n') for chunk in extracted_chunks) + '\n\n'
    new_text = new_text[:guard_pos] + moved + new_text[guard_pos:]
    path.write_text(new_text, encoding='utf-8')
    verify = ast.parse(new_text)
    g = b = None
    for n in verify.body:
        if (
            isinstance(n, ast.If)
            and isinstance(n.test, ast.Compare)
            and isinstance(n.test.left, ast.Name)
            and n.test.left.id == '__name__'
        ):
            g = n.lineno
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == 'BYPASS_FUZZER_TYPES':
            b = n.lineno
    if b is None or g is None or b >= g:
        raise SystemExit(f"verification failed: BYPASS_FUZZER_TYPES={b}, guard={g}")
    print(f"{path}: fix applied; BYPASS_FUZZER_TYPES at line {b}, __main__ guard at line {g}")
    return 0


if __name__ == '__main__':
    target = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    sys.exit(apply(target))
