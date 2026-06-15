---
interfaces: "in-place EDIT of harness/git_integration.py — inside _ast_merge, give the nested _node_key a stable sentinel key ('__main_guard__',) for a module-level `if __name__ == \"__main__\":` guard (ast.If matched structurally via the existing nested _is_main_guard, both operand orders), so the guard becomes a MERGEABLE keyed unit: candidate-wins wholesale replace, omitted => target's preserved, target-absent => candidate's added. 2 inserted lines at the top of _node_key; NO other line of _ast_merge changes; no signatures change."
---

# Title

Make the module-level `if __name__ == "__main__":` guard a MERGEABLE keyed unit in _ast_merge (harness/git_integration.py EDIT — harness_self_fix)

# Scope

EDIT `harness/git_integration.py` (SENSITIVE path — meta_task_type MUST be `harness_self_fix`; the operator decision file `state/control/decisions/fix-ast-merge-main-guard.json` authorizes the commit).

THE BUG (root-caused; blocked the NGv2 `cfix-mcp-main` fix): `_ast_merge(output_code, target_code)` merges top-level nodes keyed by the NESTED helper `_node_key` (def/class wholesale-replace; import/assign/AnnAssign keyed; G23a/G23b). A module-level `if __name__ == "__main__":` guard is an `ast.If` for which `_node_key` returns None, and the candidate-side collection loop EXPLICITLY drops it (`if _is_main_guard(node): continue` — the loop that builds `out_no_key`). So on a whole-file submission to an EXISTING .py file the candidate's `__main__` block is silently DISCARDED and the target's OLD `__main__` survives. Consequence: a module's `__main__` block cannot be edited via the pipeline AT ALL — not symbol-patchable (it is unnamed), not merged (dropped), no region sentinels. In `cfix-mcp-main` the new `__main__` calling `SessionDB(resolve_db_path())` was silently discarded and the old `SessionDB()` survived.

Reproduced live 2026-06-11: `_ast_merge('if __name__ == "__main__":\n    x = 2\n', 'if __name__ == "__main__":\n    x = 1\n')` returns the TARGET's `x = 1` block; merging a candidate guard into a guard-less target drops the guard entirely.

THE FIX (verified-diff: built in a /tmp copy 2026-06-11 and proven green — see Inputs): insert EXACTLY TWO lines at the very top of the nested `_node_key` body so a module-level main-guard `ast.If` gets the stable sentinel key `('__main_guard__',)`. The existing keyed-merge machinery then does everything else with NO further change:
  * candidate guard + target guard => same key => candidate's node wholesale-replaces target's in the matched-key replacement loop (both are `ast.If`, not `ClassDef`, so no class-body recursion);
  * candidate WITHOUT a guard => key absent from `out_nodes` => target's guard flows through the target-walk untouched (omitted => preserved, same as symbols);
  * target WITHOUT a guard + candidate WITH => key survives in `out_nodes`; the forward-ref `name_lookup` skips it (key[0] `'__main_guard__'` matches no lookup branch); `guard_idx` is None so the guard APPENDS at end-of-body;
  * the now-redundant `if _is_main_guard(node): continue` in the `out_no_key` loop becomes unreachable for guards (the `key is not None` continue fires first) — LEAVE IT IN PLACE (harmless belt-and-braces; minimal diff).

The CURRENT nested `_node_key` (harness/git_integration.py lines 219-241 at HEAD, inside `_ast_merge` which spans lines 103-560) is, byte-for-byte:

```python
    def _node_key(node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return ('name', node.name)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            return ('assign', node.target.id)
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            return ('assign', node.targets[0].id)
        if isinstance(node, ast.Import):
            if len(node.names) == 1:
                alias = node.names[0]
                return ('import', alias.asname or alias.name)
            return None
        if isinstance(node, ast.ImportFrom):
            if len(node.names) == 1:
                alias = node.names[0]
                return ('import_from', node.module or '', node.level or 0, alias.asname or alias.name)
            return None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], (ast.Tuple, ast.List)):
            elts = node.targets[0].elts
            if elts and all((isinstance(e, ast.Name) for e in elts)):
                return ('assign_tuple', tuple((e.id for e in elts)))
            return None
        return None
```

REPLACE its first two lines' opening with EXACTLY this (the ONLY change in the whole file — two inserted lines; every other line of `_node_key` and of `_ast_merge` stays byte-identical):

```python
    def _node_key(node):
        if isinstance(node, ast.If) and _is_main_guard(node):
            return ('__main_guard__',)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return ('name', node.name)
```

`_is_main_guard` is the EXISTING nested helper defined immediately after `_node_key` (lines 243-266) — it already matches `ast.Compare` with `left=ast.Name(id='__name__')`, a single `ast.Eq`/`ast.Is`, a single `ast.Constant` comparator `'__main__'`, AND the reversed `"__main__" == __name__` form. Do NOT modify it. Calling it from `_node_key` is safe: both are sibling closures of `_ast_merge`, and every `_node_key` call site executes after both defs are bound (closure names resolve at call time).

ACCEPTED DOCUMENTED EDGE: `_node_key` is also consulted by the nested `_merge_class_body` (G24) for CLASS-body nodes, so a main-guard `ast.If` nested directly in a class body would also key — that input is pathological/nonsensical Python and acceptable; function bodies are NEVER keyed (no recursion into FunctionDef bodies), so genuinely nested guards are untouched. Only module-immediate (and class-immediate) `If` nodes ever reach `_node_key`.

LOUD DISPATCH DIRECTIVE — PATCH FORMAT (`harness/git_integration.py` is a LARGE file, this MUST be a partial edit): emit a single top-level `__JANUSMASK_PATCHES__` list with EXACTLY ONE entry, kind `'symbol'`, name `'_ast_merge'`, whose `code` is the FULL `def _ast_merge(output_code: str, target_code: str) -> str:` reproduced BYTE-FOR-BYTE from the read-only staged target at `{WORK_DIR}/inbox/targets/harness/git_integration.py`, changing ONLY the two inserted lines at the top of the nested `_node_key` shown above. The nested helper is NOT independently addressable: `_apply_symbol_patch` resolves 2-part qualnames ONLY as `ClassDef.method` (git_integration.py lines 1146-1153), so `_ast_merge._node_key` would raise KeyError — the whole top-level `_ast_merge` is the smallest patchable unit. KNOWN GOTCHA — LARGE-SYMBOL TRUNCATION: `_ast_merge` is ~458 lines at HEAD (lines 103-560); agents have deterministically truncated large symbol reproductions before. POST-EMIT SELF-CHECK (mandatory): your emitted `_ast_merge` code block must be 460 lines (458 current + 2 inserted) and must still END with `return ast.unparse(tgt_tree)`; if your draft is shorter, you truncated — re-read the staged target and re-emit. Do NOT alter the docstring, do NOT reformat, do NOT touch `_is_main_guard`, `_expand_imports`, `_merge_class_body`, `_def_time_scan_roots`, `_bound_names`, or any other nested or top-level symbol. Do NOT emit a `__JANUSMASK_MANIFEST__`, do NOT emit a whole-file rewrite, no new top-level symbols (no R-anchor needed — the change is wholly inside the existing `_ast_merge`).

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the operator decision file is keyed to it): `task_id`: `fix-ast-merge-main-guard`. meta_task_type=`harness_self_fix`. priority: high. dependencies: []. SELF task (no `working_dir` — this edits JM itself). files_touched: `["harness/git_integration.py"]` ONLY (no other file). partial_edit semantics (single `__JANUSMASK_PATCHES__` list with ONE `'symbol'` entry for `_ast_merge`, per the LOUD DISPATCH DIRECTIVE in `# Scope`). verification_command: `pytest tests/test_ast_merge_main_guard_wired.py tests/adversarial/test_ast_merge_regression_adversarial.py tests/integration/test_auto_commit_merge.py`. The leaf's `non_goals` MUST carry the literal word `integration` (out of scope is integration testing beyond the listed pre-existing suites). The pre-committed RED oracle `tests/test_ast_merge_main_guard_wired.py` (committed at d74db42 on JM master) is the authoritative contract — make it 5/5 green; do NOT author new tests. The third verification path `tests/integration/test_auto_commit_merge.py` is the live `_auto_commit_accepted` round-trip whose anti-balloon bound was reconciled for this fix at 1aa3ef6 — it must stay 24/24.

REQUIRED: at least TWO `edge_cases` in `test_spec`, mirrored into `regression_tests` (and/or `property_tests`) — name exactly these two:
  1. reversed-form guard keys identically: a candidate `if '__main__' == __name__:` block wholesale-replaces a target's canonical `if __name__ == "__main__":` block (one guard in the result, candidate body, old body gone).
  2. no-guard inputs unchanged: merging a candidate with NO main guard into a target with NO main guard produces an AST byte-identical to the pre-fix merge (added def appends, omitted def preserved, no guard materializes, import/assign keying untouched).
A third (candidate guard + new def + target guard => new def still inserted BEFORE the guard, guard body is candidate's) MAY be included. `minimum_test_count` must be >= 1.5 × functional_requirements.

# Non-Goals

- Does NOT modify `_is_main_guard`, `_expand_imports`, `_merge_class_body`, `_def_time_scan_roots`, `_bound_names`, the JANUSMASK_DELETE directive handling, the `__future__`-import hoist, the forward-reference reorder, or the agent-node topological stabilization — all byte-identical.
- Does NOT remove the now-redundant `if _is_main_guard(node): continue` in the `out_no_key` loop (kept as harmless belt-and-braces; minimal diff).
- Does NOT change `_ast_merge`'s docstring, signature, or any caller (`commit_accepted_output`, orchestrator `_auto_commit_accepted` mirror).
- Does NOT touch the separate inline merge in `harness/orchestrator.py` if any remains — only `harness/git_integration.py`.
- Does NOT give nested (function-body) `if __name__ == "__main__":` blocks any new semantics — they are never keyed.
- Does NOT touch any file other than `harness/git_integration.py`.
- Out of scope: integration testing of the end-to-end worker/daemon submission flow beyond the three listed pytest suites; this leaf is a behavior-only unit fix verified by the pre-committed oracle plus the existing regression batteries.

# Inputs

- Authoritative contract: the pre-committed RED oracle `tests/test_ast_merge_main_guard_wired.py` (JM master commit d74db42). Confirmed RED 2026-06-11: 3 failed (candidate-guard-replaces, reversed-form-replaces, target-gains-candidate-guard) / 2 passed (omitted-preserves, no-guard regression pin).
- Drift guards (pre-existing, all green at HEAD and against the verified diff): `tests/adversarial/test_ast_merge_regression_adversarial.py` (7 tests, commit_accepted_output round-trip ratchet) and `tests/integration/test_auto_commit_merge.py` (24 tests; its stale `1.1 * len(original)` anti-balloon bound — implicitly tuned to the guard-DROP defect — was reconciled to `1.1 * max(len(original), len(OUTPUT_MODULE))` at 1aa3ef6 and passes both pre- and post-fix).
- VERIFIED DIFF (2026-06-11, /tmp clean-copy build): with ONLY the two inserted `_node_key` lines, the full ast-merge surface is green — `tests/test_ast_merge_main_guard_wired.py` 5/5, `tests/adversarial/test_ast_merge_regression_adversarial.py` 7/7, `tests/integration/test_auto_commit_merge.py` 24/24, plus `tests/test_ast_merge_future_imports.py`, `tests/test_ast_merge_future.py`, `tests/adversarial/test_ast_merge_apply_edge_adversarial.py`, `tests/adversarial/test_ast_merge_importfrom_additive.py`, `tests/adversarial/test_git_integration_import_forward_ref.py`, `tests/adversarial/test_git_integration_annotation_forward_ref.py`, `tests/autocompiler/test_crossover.py` — 83/83 total.
- The verbatim CURRENT `_node_key` and the exact corrected opening are embedded in `# Scope`; the staged read-only target is at `{WORK_DIR}/inbox/targets/harness/git_integration.py` (`_ast_merge` spans lines 103-560 at HEAD).

# Deliverables

`harness/git_integration.py` with exactly two lines inserted at the top of the nested `_node_key` inside `_ast_merge`, giving a module-level `if __name__ == "__main__":` guard the stable sentinel key `('__main_guard__',)` so the existing keyed merge makes it candidate-wins replaceable / omitted-preserved / target-absent-addable. Turns `tests/test_ast_merge_main_guard_wired.py` 5/5 GREEN while `tests/adversarial/test_ast_merge_regression_adversarial.py` (7/7) and `tests/integration/test_auto_commit_merge.py` (24/24) stay green. A whole-file submission can now EDIT a module's `__main__` block through the pipeline (the NGv2 `cfix-mcp-main` class of fix lands instead of being silently discarded); merges of inputs without a `__main__` guard are byte-identical to today.
