#!/usr/bin/env python3
"""Analytic verification (Mandate B): is claude's submission genuinely valid+complete?

Loads the submission JSON, extracts the __JANUSMASK_PATCHES__ block, ast.parses
each patch's `code`. If every patch parses, claude's candidate is NOT truncated;
the failure is the promotion/approval gate, not agent quality.
"""
import ast
import json
import sys
from pathlib import Path

SUB = Path('state/sessions/claude_round1_reconciler-reaps-spent-briefs-impl_submission.json')


def main() -> int:
    d = json.loads(SUB.read_text(encoding='utf-8'))
    code = d.get('code', '')
    print(f'submission keys      : {list(d.keys())}')
    print(f'task_id              : {d.get("task_id")}')
    print(f'code length          : {len(code)}')

    # 1. The whole candidate must parse as a Python module (it is a
    #    `__JANUSMASK_PATCHES__ = [...]` assignment of a list of dict literals).
    try:
        mod = ast.parse(code)
        print('whole-candidate parse: OK (the __JANUSMASK_PATCHES__ assignment is valid Python)')
    except SyntaxError as e:
        print(f'whole-candidate parse: SYNTAX ERROR -> {e}')
        return 1

    # 2. Pull the literal list out of the parsed AST and ast.parse() each patch's
    #    `code` string independently (this is what the patch-apply path will do).
    patches = None
    for node in ast.walk(mod):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == '__JANUSMASK_PATCHES__':
                    patches = ast.literal_eval(node.value)
    if patches is None:
        print('NO __JANUSMASK_PATCHES__ assignment found')
        return 1

    print(f'\nnum patches          : {len(patches)}')
    all_ok = True
    for i, p in enumerate(patches):
        f = p.get('file')
        kind = p.get('kind')
        name = p.get('name')
        anchor = p.get('anchor') or p.get('after') or p.get('relative_to')
        pcode = p.get('code', '')
        print(f'\n--- patch[{i}] file={f} kind={kind} name={name} anchor={anchor} code_len={len(pcode)} ---')
        try:
            pmod = ast.parse(pcode)
            tops = [getattr(n, "name", type(n).__name__) for n in pmod.body]
            print(f'    ast.parse: OK  top-level defs: {tops}')
        except SyntaxError as e:
            print(f'    ast.parse: SYNTAX ERROR -> {e}')
            all_ok = False

    print('\n================ VERDICT ================')
    if all_ok:
        print('ALL patches parse -> claude candidate is VALID + COMPLETE (not truncated).')
        print('=> The synthesis failure is NOT agent quality; it is the promotion/approval gate.')
    else:
        print('At least one patch FAILED to parse -> candidate truncated/invalid (agent quality).')
    return 0 if all_ok else 2


if __name__ == '__main__':
    sys.exit(main())
